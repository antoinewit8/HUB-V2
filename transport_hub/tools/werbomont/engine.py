"""
tools/werbomont/engine.py — Calcul du détour par le centre logistique de Werbomont.

Entrées
  • LISTES_MISSIONS : une ligne par activité (CHARGER, DECHARGER, LAVAGE, DECROCHER…)
    avec n° de dossier, date/heure, adresse, chauffeur, tracteur, remorque.
  • CA CIT : une ligne par dossier avec prix transport, suppléments, client.

Méthode (voir docstrings) :
  1. Chaque arrêt est géolocalisé par code postal + localité (table GeoNames embarquée,
     aucun appel réseau).
  2. Par dossier : séquence chargée C1 → … → Dn, lavage(s) après Dn.
  3. Chaînage par citerne (remorque, à défaut tracteur) : le dossier suivant donne
     le point de rechargement B. Le trajet à vide du dossier = Dn → lavage(s) → B
     (convention : le vide est imputé au dossier qui se termine, comme dans
     Tractionnaires KM).
  4. Détour à vide  = km(Dn → W → B) − km(Dn → lavage actuel → B)
     Détour en charge = meilleure insertion de W entre deux arrêts chargés consécutifs.
  5. Km estimés = vol d'oiseau × coefficient routier ; remplacés par PTV quand
     la page le demande (candidats seulement).
"""

from __future__ import annotations

import gzip
import io
import math
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CP_FILE = HERE / "cp_geo.csv.gz"

WERBOMONT = (50.3807, 5.6822)          # 4190 Werbomont (centre du village)
COEF_ROUTE = 1.30                      # vol d'oiseau → route PL (calé sur routes_apprises.json : médiane 1,30)
SEUILS = (60, 80)                      # acceptable ≤ 60 < à vérifier ≤ 80 < trop lourd
ECART_MAX_JOURS = 4                    # au-delà, le dossier suivant n'est plus « le suivant »

PAYS_ISO = {"F": "FR", "B": "BE", "NL": "NL", "D": "DE", "L": "LU", "I": "IT", "E": "ES", "GB": "GB",
            "CH": "CH", "A": "AT", "S": "SE", "PL": "PL", "GR": "GR", "DK": "DK", "CZ": "CZ", "RO": "RO",
            "HU": "HU", "HR": "HR", "IRL": "IE", "BG": "BG", "P": "PT", "CN": "CN"}

# Localités absentes de GeoNames ou mal placées (iso, cp, localité normalisée) → (lat, lon)
CORRECTIFS = {
    ("LU", "6169", "ESCHWEILER JUNGLISTER"): (49.7177, 6.3083),   # Eschweiler (Junglinster)
    ("LU", "6169", "ESCHWEILER JUNGLINSTER"): (49.7177, 6.3083),
    ("LU", "6169", "ESCHWEILER"): (49.7177, 6.3083),
}

CAT_LABELS = {"ok": "Acceptable", "verif": "À vérifier", "lourd": "Trop lourd", "deja": "Déjà via Werbomont",
              "na": "Non calculé"}
# Trajet à vide jugé atypique (lavage très éloigné, saisie douteuse) : km actuel > 2 × direct + 300 km.
# On le compare alors au trajet direct, pour ne pas compter un « gain » artificiel.
ATYPIQUE = (2.0, 300.0)


# ─── Normalisation ───────────────────────────────────────────────────────────
def norm_txt(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def norm_iso(code) -> str:
    c = str(code).strip().upper() if code is not None and not (isinstance(code, float) and math.isnan(code)) else ""
    return PAYS_ISO.get(c, c)


def norm_cp(cp, iso: str) -> str:
    if cp is None or (isinstance(cp, float) and math.isnan(cp)):
        return ""
    s = str(cp).strip().upper().replace("*", "")
    if s.endswith(".0"):
        s = s[:-2]
    if iso == "GB":
        s = s.split()[0] if " " in s else (s[:-3] if len(s) >= 5 else s)
        return s
    s = s.replace(" ", "")
    if iso == "NL":
        return s[:4]
    if iso == "PT":
        return s[:4]
    if iso in ("FR", "DE", "IT", "ES") and s.isdigit():
        return s.zfill(5)
    if iso in ("BE", "LU", "CH", "AT", "DK", "HU") and s.isdigit():
        return s.zfill(4)
    return s


def norm_dossier(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.lstrip("0") or s


# ─── Géolocalisation hors ligne ──────────────────────────────────────────────
class Geocodeur:
    """CP + localité → (lat, lon, précision). Table GeoNames embarquée."""

    def __init__(self, path: Path = CP_FILE):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            t = pd.read_csv(f, dtype={"iso": str, "cp": str, "place": str})
        t["place"] = t["place"].fillna("")
        self.exact = {(i, c, p): (la, lo) for i, c, p, la, lo in t[["iso", "cp", "place", "lat", "lon"]].itertuples(index=False)}
        self.par_cp = self._moy(t, ["iso", "cp"])
        self.par_lieu = self._moy(t, ["iso", "place"])
        t["p2"] = t["cp"].str[:2]          # zone CP (2 premiers caractères) pour les CP inconnus
        self.par_prefixe = self._moy(t, ["iso", "p2"])
        self.manuel: dict[tuple, tuple] = dict(CORRECTIFS)

    @staticmethod
    def _moy(t, cles):
        g = t.groupby(cles)[["lat", "lon"]].mean()
        return dict(zip(g.index, zip(g["lat"], g["lon"])))

    def __call__(self, iso: str, cp: str, lieu: str):
        if (iso, cp, lieu) in self.manuel:
            la, lo = self.manuel[(iso, cp, lieu)]
            return la, lo, "manuel"
        if cp and (iso, cp, lieu) in self.exact:
            la, lo = self.exact[(iso, cp, lieu)]
            return la, lo, "cp+localité"
        if cp and lieu:
            # localité « SAINT POL SUR TERNOISE » vs « ST POL… » : on tente l'inclusion
            for (i, c, p), (la, lo) in self._candidats(iso, cp):
                if p and (p in lieu or lieu in p):
                    return la, lo, "cp+localité"
        if cp and (iso, cp) in self.par_cp:
            la, lo = self.par_cp[(iso, cp)]
            return la, lo, "cp"
        if lieu and (iso, lieu) in self.par_lieu:
            la, lo = self.par_lieu[(iso, lieu)]
            return la, lo, "localité"
        if cp and (iso, cp[:2]) in self.par_prefixe:
            la, lo = self.par_prefixe[(iso, cp[:2])]
            return la, lo, "zone CP"
        return None, None, "introuvable"

    def _candidats(self, iso, cp):
        if not hasattr(self, "_idx"):
            idx: dict = {}
            for k, v in self.exact.items():
                idx.setdefault(k[:2], []).append((k, v))
            self._idx = idx
        return self._idx.get((iso, cp), [])


# ─── Distances ───────────────────────────────────────────────────────────────
def hav(lat1, lon1, lat2, lon2):
    """Vol d'oiseau en km (fonctionne sur scalaires ou tableaux numpy)."""
    r = np.pi / 180
    a = np.sin((lat2 - lat1) * r / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


class Distances:
    """km routiers entre deux points : PTV si connu (cache), sinon vol d'oiseau × coef."""

    def __init__(self, coef: float = COEF_ROUTE, cache: dict | None = None):
        self.coef = coef
        self.cache = cache if cache is not None else {}   # {(lat1,lon1,lat2,lon2) arrondis: km}

    @staticmethod
    def cle(a, b):
        return (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3))

    def km(self, a, b):
        if a is None or b is None or a[0] is None or b[0] is None:
            return np.nan
        if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
            return 0.0
        k = self.cle(a, b)
        if k in self.cache:
            return self.cache[k]
        return float(hav(a[0], a[1], b[0], b[1])) * self.coef

    def est_ptv(self, a, b) -> bool:
        if a is None or b is None or a[0] is None or b[0] is None:
            return True
        return self.cle(a, b) in self.cache or (abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6)

    def chemin(self, pts):
        pts = [p for p in pts if p is not None and p[0] is not None]
        return float(sum(self.km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))) if len(pts) > 1 else 0.0


# ─── Lecture des fichiers ────────────────────────────────────────────────────
COLS_MISSIONS = {
    "dossier": ["N° Dossier", "N° dossier", "Dossier"],
    "activite": ["Activité", "Activite"],
    "date": ["Date"],
    "heure": ["Heure"],
    "nom": ["Nom 1", "Nom"],
    "nom2": ["Nom 2"],
    "adresse": ["Adresse"],
    "pays": ["Code pays", "Pays"],
    "cp": ["Code postal", "CP"],
    "localite": ["Localité", "Localite"],
    "produit": ["Produit"],
    "chauffeur": ["Chauffeur"],
    "dep_tracteur": ["Départ. tracteur", "Dépt. tracteur"],
    "tracteur": ["Immat. tracteur", "Tracteur"],
    "remorque": ["Remorque"],
}
COLS_CA = {
    "dossier": ["N° Dossier", "N° dossier"],
    "date_ch": ["Date chargement"],
    "client": ["Client facturation"],
    "type_dossier": ["Type de dossier"],
    "produit": ["Produit"],
    "loc_ch": ["Localité chargement"], "cp_ch": ["C.P. chargement"], "pays_ch": ["Pays chargement"],
    "loc_de": ["Localité déchargement"], "cp_de": ["C.P. déchargement"], "pays_de": ["Pays déchargement"],
    "prix": ["Prix transport"],
    "supplements": ["Suppléments"],
    "ventes": ["Total des ventes"],
    "achats": ["Total des achats"],
    "etat": ["Etat vente"],
}


def _mapper(df: pd.DataFrame, spec: dict, obligatoires: list[str]) -> pd.DataFrame:
    low = {norm_txt(c): c for c in df.columns}
    out = {}
    for cle, noms in spec.items():
        for n in noms:
            if norm_txt(n) in low:
                out[cle] = df[low[norm_txt(n)]]
                break
    manque = [c for c in obligatoires if c not in out]
    if manque:
        raise ValueError("Colonnes introuvables : " + ", ".join(spec[c][0] for c in manque))
    return pd.DataFrame(out)


def _heure_td(v):
    try:
        if v is None or pd.isna(v):
            return pd.Timedelta(0)
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timedelta):
        return v
    if hasattr(v, "hour"):
        return pd.Timedelta(hours=v.hour, minutes=v.minute)
    try:
        return pd.to_timedelta(str(v))
    except Exception:
        return pd.Timedelta(0)


def preparer_missions(raw: pd.DataFrame, geo: Geocodeur, w_cp="4190", w_lieu="WERBOMONT") -> pd.DataFrame:
    m = _mapper(raw, COLS_MISSIONS, ["dossier", "activite", "date", "pays", "cp", "localite"])
    m["ordre"] = np.arange(len(m))
    m["dossier"] = m["dossier"].map(norm_dossier)
    m = m[m["dossier"] != ""]
    m["activite"] = m["activite"].fillna("").astype(str).str.strip().str.upper()
    m["dt"] = pd.to_datetime(m["date"], errors="coerce", dayfirst=True) + (
        m["heure"].map(_heure_td) if "heure" in m else pd.Timedelta(0))
    m["iso"] = m["pays"].map(norm_iso)
    m["cpn"] = [norm_cp(c, i) for c, i in zip(m["cp"], m["iso"])]
    m["lieu"] = m["localite"].map(norm_txt)
    cles = m[["iso", "cpn", "lieu"]].drop_duplicates()
    res = {tuple(k): geo(*k) for k in cles.itertuples(index=False)}
    trip = [res[k] for k in zip(m["iso"], m["cpn"], m["lieu"])]
    m["lat"] = [t[0] for t in trip]
    m["lon"] = [t[1] for t in trip]
    m["geo"] = [t[2] for t in trip]
    m["a_werbomont"] = (m["iso"] == "BE") & ((m["lieu"] == w_lieu) | (m["cpn"] == w_cp) & m["lieu"].str.contains(w_lieu))
    for c in ("tracteur", "remorque", "chauffeur", "dep_tracteur", "nom", "nom2", "produit"):
        if c not in m:
            m[c] = ""
        m[c] = m[c].fillna("").astype(str).str.strip()
    m["ville"] = m["localite"].fillna("").astype(str).str.strip().str.title() + " (" + m["iso"] + ")"
    return m.sort_values(["dossier", "dt", "ordre"], kind="stable")


def preparer_ca(raw: pd.DataFrame) -> pd.DataFrame:
    c = _mapper(raw, COLS_CA, ["dossier", "prix"])
    c["dossier"] = c["dossier"].map(norm_dossier)
    for k in ("prix", "supplements", "ventes", "achats"):
        if k in c:
            c[k] = pd.to_numeric(c[k], errors="coerce")
    agg = {k: "sum" for k in ("prix", "supplements", "ventes", "achats") if k in c}
    agg.update({k: "first" for k in c.columns if k not in agg and k != "dossier"})
    return c.groupby("dossier", as_index=False).agg(agg)


# ─── Construction des dossiers ───────────────────────────────────────────────
def construire_dossiers(m: pd.DataFrame, ca: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par dossier : séquence chargée, lavages, citerne, prix."""
    lignes = []
    for dos, g in m.groupby("dossier", sort=False):
        act = g["activite"].tolist()
        pts = [(la, lo) if pd.notna(la) and pd.notna(lo) else (None, None) for la, lo in zip(g["lat"], g["lon"])]
        ch = [i for i, a in enumerate(act) if a == "CHARGER"]
        de = [i for i, a in enumerate(act) if a == "DECHARGER"]
        r = {"dossier": dos, "nb_charg": len(ch), "nb_decharg": len(de)}
        if not ch or not de:
            r["statut"] = "sans chargement" if not ch else "sans déchargement"
            lignes.append(r)
            continue
        i0, i1 = ch[0], de[-1]
        if i1 < i0:          # saisie hors ordre : on suit l'ordre chronologique malgré tout
            i0, i1 = min(ch + de), max(ch + de)
        charge_idx = [i for i in range(i0, i1 + 1) if act[i] in ("CHARGER", "DECHARGER")]
        lav_idx = [i for i in range(i1 + 1, len(act)) if act[i] == "LAVAGE"]
        w_idx = [i for i in range(len(act)) if g["a_werbomont"].iat[i]]
        rr = g.iloc[i1]
        r.update({
            "statut": "ok",
            "seq_charge": [pts[i] for i in charge_idx],
            "seq_villes": [g["ville"].iat[i] for i in charge_idx],
            "multi": len(charge_idx) > 2,
            "C1": pts[i0], "Dn": pts[i1],
            "ville_C1": g["ville"].iat[i0], "ville_Dn": g["ville"].iat[i1],
            "client_C1": g["nom"].iat[i0], "client_Dn": g["nom"].iat[i1],
            "geo_C1": g["geo"].iat[i0], "geo_Dn": g["geo"].iat[i1],
            "dt_C1": g["dt"].iat[i0], "dt_Dn": g["dt"].iat[i1],
            "lavages": [pts[i] for i in lav_idx],
            "lavage_noms": " + ".join(f'{g["nom"].iat[i]} ({g["ville"].iat[i]})' for i in lav_idx),
            "lavage_a_W": any(g["a_werbomont"].iat[i] for i in lav_idx),
            "passe_W": bool(w_idx),
            "passe_W_charge": any(i0 < i < i1 for i in w_idx),
            "passe_W_vide": any(i > i1 for i in w_idx),
            "passe_W_quoi": ", ".join(sorted({act[i].title() for i in w_idx})),
            "remorque": rr["remorque"], "tracteur": rr["tracteur"], "chauffeur": rr["chauffeur"],
            "dep_tracteur": rr["dep_tracteur"], "produit": g["produit"].iat[i0],
        })
        lignes.append(r)
    d = pd.DataFrame(lignes)
    for c in ("multi", "passe_W", "passe_W_charge", "passe_W_vide", "lavage_a_W"):
        d[c] = d[c].astype("boolean").fillna(False).astype(bool)
    d = d.merge(ca, on="dossier", how="left", suffixes=("", "_ca"))
    d["dans_ca"] = d["prix"].notna()
    return d


def chainer(d: pd.DataFrame, ecart_max_jours: float = ECART_MAX_JOURS) -> pd.DataFrame:
    """Dossier suivant de la même citerne (remorque ; à défaut tracteur) → point B."""
    d = d.copy()
    ok = d["statut"].eq("ok")
    rem = d["remorque"].fillna("")
    tra = d["tracteur"].fillna("")
    sans_rem = rem.isin(["", "NAN"]) | tra.str.startswith("AFF")
    d["citerne"] = np.where(sans_rem, "T:" + tra, "R:" + rem)
    d.loc[tra.str.startswith("AFF") | (sans_rem & tra.eq("")), "citerne"] = ""
    d["B"] = None
    d["ville_B"] = ""
    d["dossier_suivant"] = ""
    d["ecart_h"] = np.nan
    s = d[ok & d["citerne"].ne("")].sort_values(["citerne", "dt_C1"])
    for _, g in s.groupby("citerne", sort=False):
        idx = g.index.tolist()
        for a, b in zip(idx[:-1], idx[1:]):
            ecart = (d.at[b, "dt_C1"] - d.at[a, "dt_Dn"]).total_seconds() / 3600
            if pd.isna(ecart) or ecart < -12 or ecart > ecart_max_jours * 24:
                continue
            d.at[a, "B"] = d.at[b, "C1"]
            d.at[a, "ville_B"] = d.at[b, "ville_C1"]
            d.at[a, "dossier_suivant"] = d.at[b, "dossier"]
            d.at[a, "ecart_h"] = round(ecart, 1)
    return d


def categorie(km, seuils=SEUILS):
    if km is None or pd.isna(km):
        return "na"
    return "ok" if km <= seuils[0] else ("verif" if km <= seuils[1] else "lourd")


def calculer(d: pd.DataFrame, dist: Distances, w=WERBOMONT, seuils=SEUILS) -> pd.DataFrame:
    """km chargés, vide actuel, détours (à vide / en charge), renta avant-après."""
    d = d.copy()
    out = {k: [] for k in ("km_charge", "km_vide_actuel", "km_vide_W", "km_vide_direct",
                           "detour_vide", "detour_vide_vs_direct", "detour_charge", "insertion_charge",
                           "dist_W_Dn", "ptv_vide", "ptv_charge")}
    for r in d.itertuples(index=False):
        if r.statut != "ok":
            for k in out:
                out[k].append(np.nan if k not in ("insertion_charge",) else "")
            continue
        seq = r.seq_charge
        kc = dist.chemin(seq)
        # en charge : meilleure insertion de W entre deux arrêts consécutifs
        best, ou, ptv_c = np.nan, "", True
        for i in range(len(seq) - 1):
            p, q = seq[i], seq[i + 1]
            if p[0] is None or q[0] is None:
                continue
            x = dist.km(p, w) + dist.km(w, q) - dist.km(p, q)
            if pd.isna(best) or x < best:
                best, ou = x, f"{r.seq_villes[i]} → {r.seq_villes[i + 1]}"
                ptv_c = dist.est_ptv(p, w) and dist.est_ptv(w, q) and dist.est_ptv(p, q)
        A, B = r.Dn, r.B
        dW = dist.km(A, w)
        if B is not None and isinstance(B, tuple) and B[0] is not None and A[0] is not None:
            actuel = dist.chemin([A, *r.lavages, B])
            viaW = dist.km(A, w) + dist.km(w, B)
            direct = dist.km(A, B)
            dv, dvd = viaW - actuel, viaW - direct
            pts = [A, *r.lavages, B]
            ptv_v = all(dist.est_ptv(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) and \
                dist.est_ptv(A, w) and dist.est_ptv(w, B)
        else:
            actuel = dist.chemin([A, *r.lavages]) if r.lavages else np.nan
            viaW = direct = dv = dvd = np.nan
            ptv_v = False
        for k, v in zip(out, (kc, actuel, viaW, direct, dv, dvd, best, ou, dW, ptv_v, ptv_c)):
            out[k].append(v)
    for k, v in out.items():
        d[k] = v
    # trajet à vide atypique → comparé au trajet direct (prudent)
    d["vide_atypique"] = d["km_vide_actuel"] > d["km_vide_direct"] * ATYPIQUE[0] + ATYPIQUE[1]
    d.loc[d["vide_atypique"], "detour_vide"] = d.loc[d["vide_atypique"], "detour_vide_vs_direct"]
    d["gain_vide"] = d["detour_vide"] < 0          # Werbomont plus court que le lavage utilisé
    d["cat_vide"] = d["detour_vide"].map(lambda x: categorie(x, seuils))
    d["cat_charge"] = d["detour_charge"].map(lambda x: categorie(x, seuils))
    # passe déjà par Werbomont au même moment (vide après déchargement / en charge) : catégorie à part
    d.loc[d["passe_W_vide"].astype(bool), "cat_vide"] = "deja"
    d.loc[d["passe_W_charge"].astype(bool), "cat_charge"] = "deja"
    km_tot = d["km_charge"] + d["km_vide_actuel"].fillna(0)
    d["km_total"] = km_tot
    d["renta_actuelle"] = d["prix"] / km_tot.replace(0, np.nan)
    d["renta_W_vide"] = d["prix"] / (km_tot + d["detour_vide"]).replace(0, np.nan)
    d["renta_W_charge"] = d["prix"] / (km_tot + d["detour_charge"]).replace(0, np.nan)
    return d


def agreger_lignes(d: pd.DataFrame, mode: str = "vide", seuils=SEUILS) -> pd.DataFrame:
    """Une ligne commerciale = départ (C1) → arrivée (Dn). Renta = Σprix / Σkm."""
    col = "detour_vide" if mode == "vide" else "detour_charge"
    cat = "cat_vide" if mode == "vide" else "cat_charge"
    x = d[d["statut"].eq("ok") & d["dans_ca"]].copy()
    x["ligne"] = x["ville_C1"] + " → " + x["ville_Dn"]
    x["_deja"] = x[cat].eq("deja")
    x["_det"] = x[col].where(~x["_deja"])
    x["_km_apres"] = x["km_total"] + x["_det"]
    x["_ok"] = x["_det"] <= seuils[0]
    x["_calc"] = x["_det"].notna()
    g = x.groupby("ligne")
    L = pd.DataFrame({
        "depart": g["ville_C1"].first(), "arrivee": g["ville_Dn"].first(),
        "client": g["client"].agg(lambda s: s.mode().iat[0] if s.notna().any() else ""),
        "nb_dossiers": g.size(), "nb_calcules": g["_calc"].sum(),
        "multi_points": g["multi"].sum().astype(int),
        "deja_W": g["_deja"].sum().astype(int),
        "prix_moyen": g["prix"].mean(), "ca_total": g["prix"].sum(),
        "km_charge_moy": g["km_charge"].mean(),
        "km_vide_moy": g["km_vide_actuel"].mean(),
        "detour_median": g["_det"].median(),
        "detour_min": g["_det"].min(),
        "part_acceptable": g["_ok"].sum() / g["_calc"].sum().replace(0, np.nan),
        "C1_lat": g["C1"].first().map(lambda p: p[0]), "C1_lon": g["C1"].first().map(lambda p: p[1]),
        "Dn_lat": g["Dn"].first().map(lambda p: p[0]), "Dn_lon": g["Dn"].first().map(lambda p: p[1]),
    })
    xc = x[x["_calc"]]
    gc = xc.groupby("ligne")
    L["renta_actuelle"] = gc["prix"].sum() / gc["km_total"].sum()
    L["renta_via_W"] = gc["prix"].sum() / gc["_km_apres"].sum()
    L["delta_renta_pct"] = (L["renta_via_W"] / L["renta_actuelle"] - 1) * 100
    L["categorie"] = L["detour_median"].map(lambda v: categorie(v, seuils))
    return L.reset_index().sort_values(["nb_dossiers"], ascending=False)


def paires_a_calculer(d: pd.DataFrame, w=WERBOMONT, mode: str = "vide", filtre_km: float = 120) -> list:
    """Paires de points à envoyer à PTV pour les dossiers candidats (estimation ≤ filtre_km)."""
    col = "detour_vide" if mode == "vide" else "detour_charge"
    cand = d[d[col].notna() & (d[col] <= filtre_km)]
    paires = set()
    for r in cand.itertuples(index=False):
        if mode == "vide":
            pts = [r.Dn, *r.lavages, r.B]
            paires.update((pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            paires.update({(r.Dn, w), (w, r.B), (r.Dn, r.B)})
        else:
            s = r.seq_charge
            for i in range(len(s) - 1):
                paires.update({(s[i], s[i + 1]), (s[i], w), (w, s[i + 1])})
    return [p for p in paires if p[0][0] is not None and p[1][0] is not None]


# ─── PTV (km routiers poids lourd) ───────────────────────────────────────────
PTV_URL = "https://api.myptv.com/routing/v1/routes"
PTV_PROFIL = "EUR_TRAILER_TRUCK"           # même profil que tools/km_calcul/modules/ptv_router_km.py


def cle_ptv() -> str:
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    k = os.environ.get("PTV_API_KEY", "")
    if not k:
        try:
            import streamlit as st
            k = st.secrets.get("PTV_API_KEY", "")
        except Exception:
            k = ""
    return "" if k in ("", "METS_TA_CLE_ICI") else k


def ptv_km(a, b, cle: str, timeout: int = 25):
    """km PTV entre deux points (lat, lon). Renvoie (km, None) ou (None, "message d'erreur")."""
    import requests
    import time
    params = [("profile", PTV_PROFIL),
              ("waypoints", f"{float(a[0]):.6f},{float(a[1]):.6f}"),
              ("waypoints", f"{float(b[0]):.6f},{float(b[1]):.6f}")]
    err = "aucune réponse"
    for essai in range(5):
        try:
            r = requests.get(PTV_URL, params=params, headers={"apiKey": cle}, timeout=timeout)
        except Exception as e:
            err = f"réseau : {type(e).__name__}"
            time.sleep(1 + essai)
            continue
        if r.status_code == 200:
            km = round(r.json().get("distance", 0) / 1000, 1)
            return (km, None) if km > 0 else (None, "distance nulle")
        detail = ""
        try:
            j = r.json()
            detail = j.get("description") or j.get("errorCode") or j.get("message") or ""
        except Exception:
            detail = r.text[:120]
        err = f"HTTP {r.status_code}" + (f" : {detail}" if detail else "")
        if r.status_code in (429, 500, 502, 503, 504):        # quota / surcharge : on attend et on réessaie
            try:
                attente = float(r.headers.get("Retry-After", 0))
            except ValueError:
                attente = 0
            time.sleep(max(attente, 2 * (essai + 1)))
            continue
        return None, err                                     # 400, 401, 403… : inutile de réessayer
    return None, err


def ptv_test(cle: str):
    """Un appel de contrôle Liège → Werbomont. Renvoie (km, erreur)."""
    return ptv_km((50.6326, 5.5797), WERBOMONT, cle)


def ptv_lot(paires, cle: str, cache: dict, workers: int = 3, progression=None, arret_si_refus: bool = True):
    """Calcule les paires absentes du cache. Renvoie (nb ok, {erreur: nb}).
    S'arrête tôt si PTV refuse la clé (401/403) : inutile d'envoyer le reste du lot."""
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor, as_completed
    a_faire = [(a, b) for a, b in paires if Distances.cle(a, b) not in cache]
    ok, erreurs = 0, Counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futurs = {ex.submit(ptv_km, a, b, cle): (a, b) for a, b in a_faire}
        for n, f in enumerate(as_completed(futurs), 1):
            a, b = futurs[f]
            km, err = f.result()
            if km is not None:
                cache[Distances.cle(a, b)] = km
                ok += 1
            else:
                erreurs[err] += 1
                if arret_si_refus and err.startswith(("HTTP 401", "HTTP 403")):
                    for g in futurs:
                        g.cancel()
                    break
            if progression:
                progression(n, len(a_faire), ok, sum(erreurs.values()))
    return ok, dict(erreurs)
