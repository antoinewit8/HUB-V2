"""
tools/trajets_vides/engine.py — « Je viens de décharger en X : où aller recharger ? »

Deux sources possibles :
  • LISTES_MISSIONS + CA CIT (recommandé) : chaque dossier a sa remorque, ses vraies
    dates/heures de chargement et de déchargement et ses lavages. Le dossier suivant
    est celui de la même citerne (remorque, à défaut tracteur ; affrétés exclus) :
    même logique que Détour Werbomont (tools/werbomont/engine.py, réutilisé).
  • CA CIT + fichier Lavages (dépannage) : la remorque ne vient que des dossiers
    lavés ; seuls ceux-là sont chaînés, sans date de déchargement (écart entre deux
    chargements). Plus de repli « première mission de la flotte le lendemain ».

Un enchaînement = déchargement A (dernier DECHARGER du dossier) → rechargement B
(premier CHARGER du dossier suivant de la citerne), avec :
  km vide   = A → lavage(s) → B (vol d'oiseau × 1,30, remplacé par PTV si connu)
  renta     = prix du dossier suivant / (km vide + km chargés du dossier suivant)
Par lieu de rechargement : renta = Σ prix / Σ km (rapport des sommes).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.werbomont import engine as E

COEF_ROUTE = E.COEF_ROUTE


# ─── Lecture ────────────────────────────────────────────────────────────────
def adapter_geo(localiser):
    """localiser(pays, cp, lieu) → dict  ⇒  geo(iso, cp, lieu) → (lat, lon, précision) attendu par Werbomont."""
    def geo(iso, cp, lieu):
        r = localiser(iso, cp, lieu)
        if not r:
            return None, None, "introuvable"
        return r["lat"], r["lon"], r.get("niveau", "")
    return geo


def _cp_dernier_dechargement(m: pd.DataFrame) -> dict:
    d = m[m["activite"].eq("DECHARGER")]
    last = d.groupby("dossier").tail(1)
    return dict(zip(last["dossier"], last["cpn"]))


def dossiers_missions(raw_missions: pd.DataFrame, raw_ca: pd.DataFrame | None, geo) -> pd.DataFrame:
    """LISTES_MISSIONS (+ CA) → une ligne par dossier (format Werbomont) + CP du déchargement."""
    m = E.preparer_missions(raw_missions, geo)
    ca = E.preparer_ca(raw_ca) if raw_ca is not None else pd.DataFrame(columns=["dossier", "prix"])
    d = E.construire_dossiers(m, ca)
    cps = _cp_dernier_dechargement(m)
    d["cp_Dn"] = d["dossier"].map(cps).fillna("")
    d["source"] = "missions"
    return d


COLS_LAVAGES = {
    "dossier": ["N° Dossier", "N° dossier", "Dossier"],
    "remorque": ["Remorque"], "tracteur": ["Tracteur", "Immat. tracteur"], "chauffeur": ["Chauffeur"],
}


def dossiers_ca(raw_ca: pd.DataFrame, raw_lavages: pd.DataFrame | None, geo) -> pd.DataFrame:
    """CA CIT (+ Lavages) → une ligne par dossier ; déchargement daté au jour du chargement."""
    c = E._mapper(raw_ca, E.COLS_CA, ["dossier", "prix", "date_ch", "loc_ch", "loc_de"])
    c["dossier"] = c["dossier"].map(E.norm_dossier)
    c = c[c["dossier"] != ""]
    c["prix"] = pd.to_numeric(c["prix"], errors="coerce")
    for k in ("ventes",):
        if k in c:
            c[k] = pd.to_numeric(c[k], errors="coerce")
    c = c.groupby("dossier", as_index=False).agg(
        {**{k: "first" for k in c.columns if k not in ("dossier", "prix")}, "prix": "sum"})

    if raw_lavages is not None:
        lv = E._mapper(raw_lavages, COLS_LAVAGES, ["dossier", "remorque"])
        lv["dossier"] = lv["dossier"].map(E.norm_dossier)
        lv = lv.drop_duplicates("dossier")
        c = c.merge(lv, on="dossier", how="left")
    for k in ("remorque", "tracteur", "chauffeur", "client", "produit"):
        if k not in c:
            c[k] = ""
        c[k] = c[k].fillna("").astype(str).str.strip()
    for k in ("remorque", "tracteur"):
        c[k] = c[k].str.upper().replace("NAN", "")

    lignes = []
    cache = {}

    def point(pays, cp, loc):
        iso = E.norm_iso(pays)
        cle = (iso, E.norm_cp(cp, iso), E.norm_txt(loc))
        if cle not in cache:
            cache[cle] = geo(*cle)
        la, lo, prec = cache[cle]
        ville = f"{str(loc or '').strip().title()} ({iso})"
        return ((la, lo) if la is not None else (None, None)), ville, prec, cle[1]

    for r in c.itertuples(index=False):
        dt = pd.to_datetime(getattr(r, "date_ch", None), errors="coerce", dayfirst=True)
        C1, v1, g1, _ = point(getattr(r, "pays_ch", ""), getattr(r, "cp_ch", ""), getattr(r, "loc_ch", ""))
        Dn, vn, gn, cpn = point(getattr(r, "pays_de", ""), getattr(r, "cp_de", ""), getattr(r, "loc_de", ""))
        lignes.append({
            "dossier": r.dossier, "statut": "ok" if pd.notna(dt) else "sans date",
            "seq_charge": [C1, Dn], "seq_villes": [v1, vn], "multi": False,
            "C1": C1, "Dn": Dn, "ville_C1": v1, "ville_Dn": vn, "geo_C1": g1, "geo_Dn": gn,
            "dt_C1": dt, "dt_Dn": dt, "lavages": [], "lavage_noms": "",
            "remorque": r.remorque, "tracteur": r.tracteur, "chauffeur": r.chauffeur,
            "dep_tracteur": "", "produit": r.produit, "client": r.client,
            "prix": r.prix, "dans_ca": pd.notna(r.prix), "cp_Dn": cpn,
            "nb_charg": 1, "nb_decharg": 1,
        })
    d = pd.DataFrame(lignes)
    d["source"] = "ca"
    return d


# ─── Enchaînements ──────────────────────────────────────────────────────────
def _km(dist, pts):
    pts = [p for p in pts if p is not None and p[0] is not None]
    return dist.chemin(pts) if len(pts) > 1 else np.nan


def enchainements(d: pd.DataFrame, dist, fenetre_jours: float = 3, bonus_weekend: float = 2) -> pd.DataFrame:
    """Une ligne par couple (dossier déchargé, dossier suivant de la même citerne)."""
    ch = E.chainer(d, ecart_max_jours=fenetre_jours + bonus_weekend)
    idx = ch.set_index("dossier")
    rows = []
    for a in ch.itertuples(index=False):
        if not a.dossier_suivant:
            continue
        b = idx.loc[a.dossier_suivant]
        jour = a.dt_Dn.dayofweek if pd.notna(a.dt_Dn) else None
        limite = (fenetre_jours + (bonus_weekend if jour in (4, 5) else 0)) * 24
        if pd.isna(a.ecart_h) or a.ecart_h > limite:
            continue
        lav = list(a.lavages) if isinstance(a.lavages, list) else []
        km_vide = _km(dist, [a.Dn, *lav, b["C1"]])
        km_direct = _km(dist, [a.Dn, b["C1"]])
        km_ch = _km(dist, b["seq_charge"]) if isinstance(b["seq_charge"], list) else np.nan
        prix = b.get("prix", np.nan)
        km_tot = (km_vide if pd.notna(km_vide) else 0) + (km_ch if pd.notna(km_ch) else 0)
        rows.append({
            "dossier": a.dossier, "dossier_suivant": a.dossier_suivant,
            "A_ville": a.ville_Dn, "A_cp": getattr(a, "cp_Dn", ""), "A_lat": a.Dn[0], "A_lon": a.Dn[1],
            "A_dt": a.dt_Dn,
            "B_ville": b["ville_C1"], "B_lat": b["C1"][0], "B_lon": b["C1"][1], "B_dt": b["dt_C1"],
            "ecart_h": a.ecart_h, "km_vide": km_vide, "km_vide_direct": km_direct,
            "lavage": bool(lav), "lavage_noms": getattr(a, "lavage_noms", ""),
            "km_charge_suivant": km_ch, "prix_suivant": prix,
            "renta": prix / km_tot if pd.notna(prix) and km_tot > 0 else np.nan,
            "client_suivant": b.get("client", "") or "", "produit_suivant": b.get("produit", "") or "",
            "remorque": a.remorque, "tracteur": a.tracteur, "chauffeur": a.chauffeur,
            "citerne": a.citerne,
        })
    return pd.DataFrame(rows)


def bilan_chainage(d: pd.DataFrame, ench: pd.DataFrame) -> dict:
    ok = d[d["statut"].eq("ok")]
    rem = ok["remorque"].fillna("").astype(str)
    tra = ok["tracteur"].fillna("").astype(str)
    affretes = int(tra.str.startswith("AFF").sum())
    sans_vehicule = int(((rem.isin(["", "NAN"])) & tra.eq("")).sum())
    return {"dossiers": len(d), "dossiers_ok": len(ok), "sans_vehicule": sans_vehicule,
            "affretes": affretes, "enchainements": len(ench),
            "sans_coord": int(ok["Dn"].map(lambda p: p is None or p[0] is None).sum())}


# ─── Lieux et candidats ─────────────────────────────────────────────────────
def lieux_dechargement(ench: pd.DataFrame) -> pd.DataFrame:
    """Lieux de déchargement distincts (ville + CP) avec le nombre d'enchaînements connus."""
    x = ench.dropna(subset=["A_lat"])
    g = x.groupby(["A_ville", "A_cp"]).agg(n=("dossier", "size"), lat=("A_lat", "mean"), lon=("A_lon", "mean"))
    g = g.reset_index().sort_values(["n", "A_ville"], ascending=[False, True])
    homonymes = g["A_ville"].duplicated(keep=False)
    g["label"] = np.where(homonymes | g["A_cp"].ne(""), g["A_ville"] + " " + g["A_cp"].astype(str), g["A_ville"])
    g["label"] = g["label"].str.strip() + " — " + g["n"].astype(str) + " enchaînement(s)"
    return g.reset_index(drop=True)


def km_vol(a, b) -> float:
    return float(E.hav(a[0], a[1], b[0], b[1]))


def autour(ench: pd.DataFrame, centre, rayon_km: float) -> pd.DataFrame:
    x = ench.dropna(subset=["A_lat"]).copy()
    if x.empty:
        return x
    x["dist_A"] = E.hav(centre[0], centre[1], x["A_lat"].to_numpy(), x["A_lon"].to_numpy())
    return x[x["dist_A"] <= max(rayon_km, 0.5)]


def candidats(x: pd.DataFrame, centre, filtres: dict | None = None) -> pd.DataFrame:
    """Agrège les enchaînements partant de la zone par lieu de rechargement."""
    f = filtres or {}
    x = x.dropna(subset=["B_lat"]).copy()
    if f.get("pays"):
        x = x[x["B_ville"].str.extract(r"\((\w+)\)$", expand=False).isin(f["pays"])]
    if f.get("prix_min"):
        x = x[x["prix_suivant"].fillna(0) >= f["prix_min"]]
    if x.empty:
        return pd.DataFrame()
    x["B_cle"] = x["B_ville"] + "|" + x["B_lat"].round(2).astype(str) + "|" + x["B_lon"].round(2).astype(str)
    x["_km_tot"] = x["km_vide"].fillna(0) + x["km_charge_suivant"].fillna(0)
    x["_avec_prix"] = x["prix_suivant"].notna() & (x["_km_tot"] > 0)
    g = x.groupby("B_cle")
    c = pd.DataFrame({
        "lieu": g["B_ville"].first(),
        "lat": g["B_lat"].mean(), "lon": g["B_lon"].mean(),
        "frequence": g.size(),
        "citernes": g["citerne"].nunique(),
        "ecart_h_median": g["ecart_h"].median(),
        "km_vide_moyen": g["km_vide"].mean(),
        "part_lavage": g["lavage"].mean(),
        "prix_moyen": g["prix_suivant"].mean(),
        "km_charge_moyen": g["km_charge_suivant"].mean(),
        "dernier": g["B_dt"].max(),
        "clients": g["client_suivant"].agg(lambda s: ", ".join(sorted({v for v in s if v})[:3])),
        "produits": g["produit_suivant"].agg(lambda s: ", ".join(sorted({v for v in s if v})[:3])),
        "chauffeurs": g["chauffeur"].agg(lambda s: ", ".join(sorted({v for v in s if v})[:3])),
    })
    xp = x[x["_avec_prix"]]
    gp = xp.groupby("B_cle")
    c["renta"] = (gp["prix_suivant"].sum() / gp["_km_tot"].sum()).reindex(c.index)
    c["km_depuis_point"] = [km_vol(centre, (la, lo)) * COEF_ROUTE for la, lo in zip(c["lat"], c["lon"])]
    return c.reset_index(drop=True)


TRIS = {
    "Renta (€/km, vide compris)": ("renta", False),
    "Fréquence": ("frequence", False),
    "Km à vide": ("km_vide_moyen", True),
    "Prix moyen": ("prix_moyen", False),
}


def classer(c: pd.DataFrame, tri: str, min_freq: int = 1) -> pd.DataFrame:
    if c.empty:
        return c
    col, asc = TRIS[tri]
    c = c[c["frequence"] >= min_freq].copy()
    c = c.sort_values([col, "frequence"], ascending=[asc, False], na_position="last").reset_index(drop=True)
    c["rang"] = np.arange(1, len(c) + 1)
    return c


def evaluer(x: pd.DataFrame, centre, point_B, rayon_hist: float = 15, prix=None, point_livraison=None,
            km_vide_ptv=None, km_charge_ptv=None) -> dict:
    """Destination saisie à la main : historique proche + estimation de renta si prix et livraison donnés."""
    km_vide = km_vide_ptv or km_vol(centre, point_B) * COEF_ROUTE
    hist = x.dropna(subset=["B_lat"])
    if not hist.empty:
        dB = E.hav(point_B[0], point_B[1], hist["B_lat"].to_numpy(), hist["B_lon"].to_numpy())
        hist = hist[dB <= rayon_hist]
    res = {"km_vide": km_vide, "source_km": "PTV" if km_vide_ptv else "vol d'oiseau × 1,3",
           "historique": len(hist)}
    if len(hist):
        tot = hist["km_vide"].fillna(0) + hist["km_charge_suivant"].fillna(0)
        okp = hist["prix_suivant"].notna() & (tot > 0)
        res.update({
            "prix_moyen": hist["prix_suivant"].mean(),
            "ecart_h_median": hist["ecart_h"].median(),
            "renta_hist": hist.loc[okp, "prix_suivant"].sum() / tot[okp].sum() if okp.any() else np.nan,
        })
    if prix and point_livraison:
        km_ch = km_charge_ptv or km_vol(point_B, point_livraison) * COEF_ROUTE
        res["km_charge"] = km_ch
        res["renta_estimee"] = prix / (km_vide + km_ch) if (km_vide + km_ch) > 0 else np.nan
    return res
