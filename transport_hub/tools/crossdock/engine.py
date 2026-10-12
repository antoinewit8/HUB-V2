"""
tools/crossdock/engine.py — Étude d'une plateforme de cross-dock / groupage (version test).

Entrées
  • LISTES_MISSIONS : une ligne par activité (CHARGER, DECHARGER, …) et par n° de dossier.
  • Export CA : une ligne par dossier (prix transport, client, total des ventes…).
  Les deux sont joints par n° de dossier : les missions donnent les vrais arrêts
  (multi-points compris), le CA donne ce que le dossier rapporte.

Méthode
  1. Géolocalisation hors ligne par code postal + localité (table GeoNames du module
     Werbomont, aucun appel réseau).
  2. Un dossier = ses chargements C1…Ck puis ses déchargements D1…Dn (ordre chronologique).
     Groupage chargement si plusieurs lieux de chargement, groupage livraison si plusieurs
     lieux de déchargement.
  3. Centre de gravité : point qui minimise la somme des distances pondérées
     (algorithme de Weiszfeld), sur les chargements, les déchargements ou les deux.
  4. Pour chaque site candidat H : route via le site = C1…Ck → H → D1…Dn.
     Détour = km via H − km de la route réelle. Km = vol d'oiseau × coefficient routier.
  5. Consolidation (hypothèse à régler) : les dossiers compatibles (détour sous le seuil)
     d'une même semaine et d'une même zone de livraison partent du site ensemble,
     « lots par camion » lots par camion. Chaque camion évité économise le trajet
     site → zone de livraison. Les exports ne donnent ni poids ni mètres de plancher :
     le taux de remplissage n'est pas connu, d'où ce paramètre.
  6. Bilan : km économisés − km de détour, valorisés au coût du km, moins la manutention
     par lot et le coût fixe du quai.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.werbomont import engine as W

COEF_ROUTE = W.COEF_ROUTE          # 1,30 : calé sur les routes PTV apprises

# Sites candidats par défaut : (nom, pays ISO, code postal, localité)
SITES_DEFAUT = [
    ("Liège (Grâce-Hollogne)", "BE", "4460", "Grâce-Hollogne"),
    ("Bettembourg (Eurohub Sud)", "LU", "3225", "Bettembourg"),
    ("Lorraine (Metz)", "FR", "57000", "Metz"),
    ("Werbomont", "BE", "4190", "Werbomont"),
]

COLS_MISSIONS = dict(W.COLS_MISSIONS, type_transport=["Type de transport"])
COLS_CA = {
    "dossier": ["N° Dossier", "N° dossier", "N°Dossier", "Dossier"],
    "client": ["Client facturation", "Client"],
    "type_transport": ["Type de transport"],
    "type_dossier": ["Type de dossier"],
    "prix": ["Prix transport"],
    "supplements": ["Suppléments", "Supplements"],
    "sg": ["S.G.", "SG"],
    "ventes": ["Total des ventes", "Total ventes"],
    "achats": ["Total des achats", "Total achats"],
}

MOIS_PAR_AN = 12


# ─── Géolocalisation ─────────────────────────────────────────────────────────
def geolocaliser(geo: W.Geocodeur, iso: str, cp: str, lieu: str):
    """Comme le géocodeur Werbomont, avec le préfixe « L- » des CP luxembourgeois de GeoNames."""
    la, lo, prec = geo(iso, cp, lieu)
    if iso == "LU" and cp and prec not in ("manuel", "cp+localité", "cp"):
        la2, lo2, prec2 = geo(iso, "L-" + cp, lieu)
        if la2 is not None:
            return la2, lo2, prec2
    return la, lo, prec


def geolocaliser_sites(geo: W.Geocodeur, sites: pd.DataFrame) -> pd.DataFrame:
    """sites : colonnes nom, pays, cp, localite (+ lat/lon facultatives qui priment)."""
    s = sites.copy()
    for c in ("nom", "pays", "cp", "localite"):
        if c not in s:
            s[c] = ""
        s[c] = s[c].fillna("").astype(str).str.strip()
    s = s[s["nom"] != ""].reset_index(drop=True)
    lat, lon, prec = [], [], []
    for r in s.itertuples(index=False):
        la0, lo0 = getattr(r, "lat", None), getattr(r, "lon", None)
        if la0 is not None and lo0 is not None and pd.notna(la0) and pd.notna(lo0):
            lat.append(float(la0)); lon.append(float(lo0)); prec.append("coordonnées")
            continue
        iso = W.norm_iso(r.pays)
        la, lo, p = geolocaliser(geo, iso, W.norm_cp(r.cp, iso), W.norm_txt(r.localite))
        lat.append(la); lon.append(lo); prec.append(p)
    s["lat"], s["lon"], s["geo"] = lat, lon, prec
    return s


# ─── Lecture ─────────────────────────────────────────────────────────────────
def preparer_missions(raw: pd.DataFrame, geo: W.Geocodeur) -> pd.DataFrame:
    m = W._mapper(raw, COLS_MISSIONS, ["dossier", "activite", "pays", "cp", "localite"])
    m["ordre"] = np.arange(len(m))
    m["dossier"] = m["dossier"].map(W.norm_dossier)
    m = m[m["dossier"] != ""]
    m["activite"] = m["activite"].fillna("").astype(str).str.strip().str.upper()
    m = m[m["activite"].isin(["CHARGER", "DECHARGER", "CHARGEMENT", "DECHARGEMENT"])].copy()
    m["activite"] = m["activite"].replace({"CHARGEMENT": "CHARGER", "DECHARGEMENT": "DECHARGER"})
    if "date" in m:
        m["dt"] = pd.to_datetime(m["date"], errors="coerce", dayfirst=True) + (
            m["heure"].map(W._heure_td) if "heure" in m else pd.Timedelta(0))
    else:
        m["dt"] = pd.NaT
    m["iso"] = m["pays"].map(W.norm_iso)
    m["cpn"] = [W.norm_cp(c, i) for c, i in zip(m["cp"], m["iso"])]
    m["lieu"] = m["localite"].map(W.norm_txt)
    cles = m[["iso", "cpn", "lieu"]].drop_duplicates()
    res = {tuple(k): geolocaliser(geo, *k) for k in cles.itertuples(index=False)}
    trip = [res[k] for k in zip(m["iso"], m["cpn"], m["lieu"])]
    m["lat"] = [t[0] for t in trip]
    m["lon"] = [t[1] for t in trip]
    m["geo"] = [t[2] for t in trip]
    for c in ("nom", "type_transport", "tracteur", "remorque"):
        if c not in m:
            m[c] = ""
        m[c] = m[c].fillna("").astype(str).str.strip()
    m["ville"] = m["localite"].fillna("").astype(str).str.strip().str.title() + " (" + m["iso"] + ")"
    m["site"] = m["nom"].str.upper() + "|" + m["lieu"]
    m["zone"] = [zone(i, c) for i, c in zip(m["iso"], m["cpn"])]
    return m.sort_values(["dossier", "dt", "ordre"], kind="stable")


def preparer_ca(raw: pd.DataFrame) -> pd.DataFrame:
    c = W._mapper(raw, COLS_CA, ["dossier"])
    c["dossier"] = c["dossier"].map(W.norm_dossier)
    c = c[c["dossier"] != ""]
    num = [k for k in ("prix", "supplements", "sg", "ventes", "achats") if k in c]
    for k in num:
        c[k] = pd.to_numeric(c[k].astype(str).str.replace("\xa0", "").str.replace(" ", "")
                             .str.replace(",", "."), errors="coerce")
    agg = {k: "sum" for k in num}
    agg.update({k: "first" for k in c.columns if k not in agg and k != "dossier"})
    out = c.groupby("dossier", as_index=False).agg(agg)
    if "prix" not in out and "ventes" in out:
        out["prix"] = out["ventes"]
    if "prix" not in out:
        raise ValueError("Colonnes introuvables dans le CA : Prix transport ou Total des ventes")
    return out


def zone(iso: str, cp: str) -> str:
    """Zone de livraison : département en France, 2 premiers chiffres du CP ailleurs,
    pays entier pour le Luxembourg."""
    if iso == "LU" or not cp:
        return iso
    c = cp.replace("L-", "")
    if iso == "FR":
        return "FR-" + (c[:3] if c[:2] in ("97", "98") else c[:2])
    return f"{iso}-{c[:2]}"


# ─── Dossiers ────────────────────────────────────────────────────────────────
def _sans_doublons_consecutifs(items):
    out = []
    for it in items:
        if not out or out[-1][0] != it[0]:
            out.append(it)
    return out


def construire_dossiers(m: pd.DataFrame, ca: pd.DataFrame | None) -> pd.DataFrame:
    """Une ligne par dossier : chargements, déchargements, type, prix."""
    lignes = []
    for dos, g in m.groupby("dossier", sort=False):
        ch = g[g["activite"] == "CHARGER"]
        de = g[g["activite"] == "DECHARGER"]
        r = {"dossier": dos, "nb_charg": len(ch), "nb_decharg": len(de)}
        if ch.empty or de.empty:
            r["statut"] = "sans chargement" if ch.empty else "sans déchargement"
            lignes.append(r)
            continue
        cs = _sans_doublons_consecutifs(list(zip(ch["site"], zip(ch["lat"], ch["lon"]), ch["ville"])))
        ds = _sans_doublons_consecutifs(list(zip(de["site"], zip(de["lat"], de["lon"]), de["ville"])))
        geo_ok = all(p[1][0] is not None and pd.notna(p[1][0]) for p in cs + ds)
        n_lieux_c, n_lieux_d = ch["site"].nunique(), de["site"].nunique()
        if n_lieux_c > 1 and n_lieux_d > 1:
            typ = "Groupage complet"
        elif n_lieux_d > 1:
            typ = "Groupage livraison"
        elif n_lieux_c > 1:
            typ = "Groupage chargement"
        else:
            typ = "Lot sec"
        seq_reelle = [(la, lo) for la, lo in zip(g["lat"], g["lon"])]
        r.update({
            "statut": "ok" if geo_ok else "non géolocalisé",
            "type": typ, "groupage": typ != "Lot sec",
            "lieux_charg": n_lieux_c, "lieux_decharg": n_lieux_d,
            "C": [p[1] for p in cs], "D": [p[1] for p in ds], "seq": seq_reelle,
            "ville_C1": cs[0][2], "ville_Dn": ds[-1][2], "ville_D1": ds[0][2],
            "client_C1": ch["nom"].iat[0], "client_D1": de["nom"].iat[0],
            "zone_livraison": de["zone"].iat[0], "pays_livraison": de["iso"].iat[0],
            "dt": ch["dt"].iat[0],
            "type_transport": g["type_transport"].iat[0],
            "tracteur": g["tracteur"].iat[0],
        })
        lignes.append(r)
    d = pd.DataFrame(lignes)
    if "groupage" in d:
        d["groupage"] = d["groupage"].astype("boolean").fillna(False).astype(bool)
    if ca is not None and len(ca):
        d = d.merge(ca, on="dossier", how="left", suffixes=("", "_ca"))
        if "type_transport_ca" in d:          # missions vides → on prend celui du CA
            vide = d["type_transport"].fillna("").astype(str).eq("")
            d.loc[vide, "type_transport"] = d.loc[vide, "type_transport_ca"]
        d["dans_ca"] = d["prix"].notna()
    else:
        d["prix"] = np.nan
        d["dans_ca"] = False
    if "client" not in d:
        d["client"] = ""
    d["client"] = d["client"].fillna("").astype(str)
    d.loc[d["client"].eq(""), "client"] = d["client_C1"]
    d["semaine"] = pd.to_datetime(d["dt"]).dt.strftime("%G-S%V")
    return d


# ─── Distances ───────────────────────────────────────────────────────────────
def km(a, b, coef=COEF_ROUTE):
    if a is None or b is None or a[0] is None or b[0] is None or pd.isna(a[0]) or pd.isna(b[0]):
        return np.nan
    return float(W.hav(a[0], a[1], b[0], b[1])) * coef


def chemin(pts, coef=COEF_ROUTE):
    pts = [p for p in pts if p is not None and p[0] is not None and pd.notna(p[0])]
    return float(sum(km(pts[i], pts[i + 1], coef) for i in range(len(pts) - 1))) if len(pts) > 1 else 0.0


# ─── Centre de gravité ───────────────────────────────────────────────────────
def points_flux(d: pd.DataFrame, quoi: str = "tous", poids: str = "dossiers") -> pd.DataFrame:
    """Points de chargement / déchargement avec leur poids (un dossier se répartit
    également entre ses lieux de chargement, et entre ses lieux de déchargement)."""
    rows = []
    for r in d.itertuples(index=False):
        w = 1.0 if poids == "dossiers" else (float(r.prix) if pd.notna(r.prix) else 0.0)
        if w <= 0:
            continue
        if quoi in ("tous", "chargements"):
            for p in r.C:
                rows.append((p[0], p[1], w / len(r.C), "C"))
        if quoi in ("tous", "dechargements"):
            for p in r.D:
                rows.append((p[0], p[1], w / len(r.D), "D"))
    return pd.DataFrame(rows, columns=["lat", "lon", "w", "role"])


def centre_gravite(pts: pd.DataFrame, iterations: int = 200):
    """Médiane géométrique pondérée (Weiszfeld) en projection locale équirectangulaire.
    Renvoie (lat, lon) du point qui minimise Σ poids × distance, et le barycentre simple."""
    if pts.empty or pts["w"].sum() <= 0:
        return None, None
    w = pts["w"].to_numpy(float)
    lat0 = np.average(pts["lat"], weights=w)
    k = math.cos(math.radians(lat0))
    x = pts["lon"].to_numpy(float) * k
    y = pts["lat"].to_numpy(float)
    bx, by = np.average(x, weights=w), np.average(y, weights=w)
    cx, cy = bx, by
    for _ in range(iterations):
        dist = np.hypot(x - cx, y - cy)
        dist = np.where(dist < 1e-9, 1e-9, dist)
        inv = w / dist
        nx, ny = (inv * x).sum() / inv.sum(), (inv * y).sum() / inv.sum()
        if abs(nx - cx) < 1e-7 and abs(ny - cy) < 1e-7:
            break
        cx, cy = nx, ny
    return (cy, cx / k), (by, bx / k)


def distance_moyenne(pts: pd.DataFrame, site, coef=COEF_ROUTE) -> float:
    """Km routier moyen pondéré entre le site et les points de flux."""
    if pts.empty:
        return np.nan
    dist = W.hav(pts["lat"].to_numpy(float), pts["lon"].to_numpy(float), site[0], site[1]) * coef
    return float(np.average(dist, weights=pts["w"].to_numpy(float)))


# ─── Passage par un site ─────────────────────────────────────────────────────
def detours(d: pd.DataFrame, site, coef=COEF_ROUTE) -> pd.DataFrame:
    """km de la route réelle, km via le site (C… → site → D…), détour, km site → 1er déchargement."""
    ok = d["statut"].eq("ok")
    out = pd.DataFrame(index=d.index, columns=["km_reel", "km_via", "detour", "km_site_D1", "km_C_site"],
                       dtype=float)
    for i, r in d[ok].iterrows():
        reel = chemin(r["seq"], coef)
        approche = chemin(r["C"], coef) + km(r["C"][-1], site, coef)
        distrib = km(site, r["D"][0], coef) + chemin(r["D"], coef)
        out.loc[i] = (reel, approche + distrib, approche + distrib - reel, km(site, r["D"][0], coef),
                      km(r["C"][-1], site, coef))
    return out


def simuler(d: pd.DataFrame, det: pd.DataFrame, seuil_km: float, seuil_pct: float, lots_camion: int,
            groupage_seul: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Consolidation par semaine × zone de livraison.

    Dossier compatible : détour ≤ seuil_km ET ≤ seuil_pct % de la route réelle.
    Groupe = mêmes semaine et zone de livraison. Un groupe d'au moins 2 dossiers passe par
    le site ; camions = ⌈n / lots_camion⌉ ; camions évités = n − camions.
    Km économisés = camions évités × km moyen site → 1er déchargement du groupe.
    Km ajoutés = Σ détours des dossiers du groupe (un dossier seul ne passe pas par le site)
               + camions évités × écart moyen entre les livraisons du groupe (tournée).
    """
    x = d[d["statut"].eq("ok")].join(det)
    x["compatible"] = (x["detour"] <= seuil_km) & (x["detour"] <= x["km_reel"] * seuil_pct / 100)
    if groupage_seul:
        x["compatible"] &= x["groupage"]
    c = x[x["compatible"]]
    if c.empty:
        g = pd.DataFrame(columns=["semaine", "zone_livraison", "dossiers", "camions", "camions_evites",
                                  "km_site_D1", "km_economises", "km_detours", "km_tournee", "km_ajoutes",
                                  "km_net", "ca", "liste"])
        x["consolide"] = False
        return x, g
    c = c.assign(d1_lat=[p[0][0] for p in c["D"]], d1_lon=[p[0][1] for p in c["D"]])
    g = c.groupby(["semaine", "zone_livraison"]).agg(
        dossiers=("dossier", "size"), km_site_D1=("km_site_D1", "mean"),
        km_detours=("detour", "sum"), ca=("prix", "sum"),
        liste=("dossier", lambda s: ", ".join(s))).reset_index()
    g = g[g["dossiers"] >= 2].copy()
    # Écart moyen entre les premiers déchargements du groupe : ce que le camion consolidé
    # ajoute pour enchaîner les livraisons d'un lot à l'autre dans la zone.
    ecart = {}
    for (sem, zo), gg in c.groupby(["semaine", "zone_livraison"]):
        if len(gg) < 2:
            continue
        la, lo = gg["d1_lat"].to_numpy(float), gg["d1_lon"].to_numpy(float)
        dm = W.hav(la[:, None], lo[:, None], la[None, :], lo[None, :]) * COEF_ROUTE
        ecart[(sem, zo)] = float(dm[np.triu_indices(len(la), 1)].mean())
    g["km_entre_livraisons"] = [ecart.get((s, z), 0.0) for s, z in zip(g["semaine"], g["zone_livraison"])]
    g["camions"] = np.ceil(g["dossiers"] / max(int(lots_camion), 1)).astype(int)
    g["camions_evites"] = g["dossiers"] - g["camions"]
    g["km_economises"] = g["camions_evites"] * g["km_site_D1"]
    g["km_tournee"] = g["camions_evites"] * g["km_entre_livraisons"]
    g["km_ajoutes"] = g["km_detours"] + g["km_tournee"]
    g["km_net"] = g["km_economises"] - g["km_ajoutes"]
    consol = set(",".join(g["liste"]).replace(" ", "").split(",")) if len(g) else set()
    x["consolide"] = x["dossier"].isin(consol)
    return x, g.sort_values(["camions_evites", "dossiers"], ascending=False)


def bilan(x: pd.DataFrame, g: pd.DataFrame, cout_km: float, manut_lot: float, quai_mois: float,
          mois: float) -> dict:
    km_eco = float(g["km_economises"].sum()) if len(g) else 0.0
    km_aj = float(g["km_ajoutes"].sum()) if len(g) else 0.0
    lots = int(g["dossiers"].sum()) if len(g) else 0
    gain = (km_eco - km_aj) * cout_km
    cout = lots * manut_lot + quai_mois * mois
    return {
        "dossiers": int(len(x)), "compatibles": int(x["compatible"].sum()),
        "consolides": lots, "groupes": int(len(g)),
        "camions_evites": int(g["camions_evites"].sum()) if len(g) else 0,
        "km_economises": km_eco, "km_ajoutes": km_aj, "km_net": km_eco - km_aj,
        "gain_km_eur": gain, "manutention_eur": lots * manut_lot, "quai_eur": quai_mois * mois,
        "resultat_eur": gain - cout,
        "resultat_an_eur": (gain - cout) * MOIS_PAR_AN / mois if mois else np.nan,
        "detour_median": float(x.loc[x["compatible"], "detour"].median()) if x["compatible"].any() else np.nan,
    }


def comparer_sites(d: pd.DataFrame, sites: pd.DataFrame, pts: pd.DataFrame, params: dict, coef=COEF_ROUTE):
    """Un tableau de synthèse par site + le détail (dossiers, groupes) de chaque site."""
    res, detail = [], {}
    for s in sites.itertuples(index=False):
        if s.lat is None or pd.isna(s.lat):
            continue
        site = (float(s.lat), float(s.lon))
        det = detours(d, site, coef)
        x, g = simuler(d, det, params["seuil_km"], params["seuil_pct"], params["lots_camion"],
                       params["groupage_seul"])
        b = bilan(x, g, params["cout_km"], params["manut_lot"], params["quai_mois"], params["mois"])
        b.update({"site": s.nom, "lat": site[0], "lon": site[1],
                  "dist_moy_flux": distance_moyenne(pts, site, coef)})
        res.append(b)
        detail[s.nom] = (x, g)
    return pd.DataFrame(res), detail
