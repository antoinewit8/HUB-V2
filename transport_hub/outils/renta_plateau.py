"""
renta_plateau.py
──────────────────────────────────────────────────────────────────
Outil Rentabilité Plateau
──────────────────────────────────────────────────────────────────
Entrées :
  • Exports planning « Traject_xxxxx.xlsx » (un ou plusieurs) — une ligne par
    arrêt (CH / DECH), dans l'ordre chronologique (colonne Séq.), avec
    N° dossier, Exécution (tracteur · chauffeur · plateau), Km Vehicle…
  • Fichier CA (.xlsx) — N° Dossier | Total des ventes | Client facturation | Etat vente

Logique :
  1. Les lignes sont regroupées par TRACTEUR (lu dans la colonne Exécution),
     tous fichiers confondus, puis remises dans l'ordre (Séq. dans un même
     fichier, date planifiée entre fichiers). Doublons entre fichiers retirés.
  2. On suit la cargaison à bord d'arrêt en arrêt : un CH ajoute le dossier,
     son dernier DECH le retire. Chaque trajet entre deux arrêts est donc :
       – à vide (rien à bord)        → imputé selon la convention choisie ;
       – chargé (un dossier à bord)  → imputé à ce dossier ;
       – groupage (plusieurs)        → parts égales (provisoire, l'outil
                                        groupage fera la vraie répartition).
  3. Km de chaque trajet via PTV. Le compteur (Km Vehicle) sert de contrôle
     global par camion : il n'est pas fiable trajet par trajet (relevés groupés).
  4. Dossiers coupés par la période : le chargement (ou le déchargement)
     manquant est reconstitué depuis Origine / Destination du dossier.
  5. CA joint sur le N° dossier. Un dossier partagé entre deux tracteurs
     (accroche / décroche) voit son CA réparti au prorata des km chargés.
──────────────────────────────────────────────────────────────────
"""

import heapq
import io
import math
import os
import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════

PTV_API_KEY  = os.environ.get("PTV_API_KEY", "METS_TA_CLE_ICI")
PTV_BASE_URL = "https://api.myptv.com/routing/v1"
GEOCODE_URL  = "https://api.myptv.com/geocoding/v1"
HEADERS      = {"apiKey": PTV_API_KEY}
MAX_RETRIES  = 3
RETRY_DELAY  = 2
VEHICLE      = "EUR_TRAILER_TRUCK"

RESULT_SCHEMA      = "plateau-v1"   # change → les résultats en session sont purgés
SEUIL_ALERTE_VIDE  = 150            # km — trajet à vide signalé au-delà
SEUIL_ECART_ODO    = 15             # % — écart compteur / PTV signalé au-delà (par camion)
SEUIL_TEMPS_SITE   = 4.0            # h — temps sur site signalé au-delà

CONVENTIONS_VIDE = {
    "precedent": "Dossier précédent (comme Renta Benne)",
    "suivant":   "Dossier suivant",
    "moitie":    "50/50 entre les deux",
}

PAYS_CODE_TO_ISO2 = {
    "F": "FR", "B": "BE", "D": "DE", "L": "LU", "NL": "NL", "E": "ES", "I": "IT",
    "CH": "CH", "GB": "GB", "A": "AT", "P": "PT", "PL": "PL", "CZ": "CZ",
    "FR": "FR", "BE": "BE", "DE": "DE", "LU": "LU",
}
PAYS_CODE_TO_FULL = {
    "F": "France", "B": "Belgium", "D": "Germany", "L": "Luxembourg", "NL": "Netherlands",
    "E": "Spain", "I": "Italy", "CH": "Switzerland", "GB": "United Kingdom", "A": "Austria",
    "P": "Portugal", "PL": "Poland", "CZ": "Czech Republic",
    "FR": "France", "BE": "Belgium", "DE": "Germany", "LU": "Luxembourg",
}

# Couleurs (cohérentes avec le hub)
C_CHARGE, C_VIDE, C_GROUP, C_RECON = "#0071e3", "#8e8e93", "#ff9500", "#af52de"


# ══════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════════

def _norm(s) -> str:
    s = str(s).lower()
    for a, b in [("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"), ("ô", "o"),
                 ("û", "u"), ("î", "i"), ("ù", "u"), ("ç", "c"), ("°", "")]:
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    v = str(v).strip()
    return "" if v.lower() in ("nan", "none", "nat") else v


def _cp_norm(cp) -> str:
    """'07470' / '7470.0' / 'F 7470' → '7470' (comparaison seulement)."""
    s = re.sub(r"\.0+$", "", _clean(cp)).upper()
    s = re.sub(r"^(F|B|D|L|NL|E|I|CH|A|P|FR|BE|DE|LU)[\s\-]*(?=\d)", "", s)
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s.lstrip("0") or s


def _to_float(v):
    s = _clean(v).replace("\xa0", "").replace(" ", "").replace("€", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _to_ts(date_v, heure_v=None):
    """Date (datetime ou texte) + heure ('07:33:00') → Timestamp, NaT si vide."""
    d = pd.to_datetime(_clean(date_v) or None, errors="coerce", dayfirst=False)
    if pd.isna(d) or d.year < 2000:
        return pd.NaT
    h = _clean(heure_v)
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", h)
    if m:
        d = d.normalize() + pd.Timedelta(hours=int(m.group(1)), minutes=int(m.group(2)),
                                         seconds=int(m.group(3) or 0))
    return d


def haversine_km(a, b):
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


# ══════════════════════════════════════════════════════════════════
#  PTV — géocodage et distances (mis en cache pour la session)
# ══════════════════════════════════════════════════════════════════

def _ptv_get(url, params):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                time.sleep(RETRY_DELAY * attempt)
                continue
            if resp.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            return resp.json()
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


def _first_pos(js):
    locs = (js or {}).get("locations", [])
    if locs:
        pos = locs[0]["referencePosition"]
        return (pos["latitude"], pos["longitude"])
    return None


@st.cache_data(show_spinner=False)
def geocode_stop(ville: str, cp: str, pays: str):
    """Priorité : CP + pays → ville, CP, pays → ville, pays → ville seule."""
    iso2 = PAYS_CODE_TO_ISO2.get(pays.upper(), "")
    full = PAYS_CODE_TO_FULL.get(pays.upper(), "")
    if cp and iso2:
        r = _first_pos(_ptv_get(f"{GEOCODE_URL}/locations/by-postal-code",
                                {"postalCode": cp, "countryCode": iso2}))
        if r:
            return r
    for q in ([f"{ville}, {cp}, {full}"] if ville and cp and full else []) + \
             ([f"{ville}, {full}"] if ville and full else []) + ([ville] if ville else []):
        r = _first_pos(_ptv_get(f"{GEOCODE_URL}/locations/by-text", {"searchText": q}))
        if r:
            return r
    return None


@st.cache_data(show_spinner=False)
def route_km(a: tuple, b: tuple):
    """Distance routière PTV (poids lourd) entre deux points GPS, en km."""
    if not a or not b:
        return None
    if haversine_km(a, b) < 0.3:
        return 0.0
    js = _ptv_get(f"{PTV_BASE_URL}/routes",
                  [("profile", VEHICLE), ("waypoints", f"{a[0]},{a[1]}"), ("waypoints", f"{b[0]},{b[1]}")])
    if js is None:
        return None
    return round(js.get("distance", 0) / 1000, 1)


# ══════════════════════════════════════════════════════════════════
#  LECTURE DES EXPORTS PLANNING
# ══════════════════════════════════════════════════════════════════

PLAN_COLS = {
    "dossier":    ["N° dossier", "N° Dossier", "Dossier"],
    "date":       ["Date"],
    "heure":      ["De"],
    "seq":        ["Séq.", "Seq.", "Séq"],
    "activite":   ["Activité"],
    "nom":        ["Nom"],
    "cp":         ["Code postal"],
    "ville":      ["Ville"],
    "vente":      ["Vente"],
    "execution":  ["Exécution"],
    "date_ob":    ["Date OB"],
    "ob_de":      ["OB de"],
    "ob_a":       ["OB à"],
    "odo":        ["Km Vehicle"],
    "poids":      ["Poids"],
    "produit":    ["Product Nature", "Produit"],
    "client_pl":  ["Client"],
    "type_trans": ["Type trans."],
    "statut":     ["Statut dos."],
    "nom_orig":   ["Origine"],
    "pays_orig":  ["Pays d'origine"],
    "cp_orig":    ["CP orig."],
    "ville_orig": ["Ville origine"],
    "nom_dest":   ["Destination"],
    "pays_dest":  ["Pays de destination"],
    "cp_dest":    ["CP dest."],
    "ville_dest": ["Ville destination"],
}
OBLIGATOIRES = ["dossier", "seq", "activite", "cp", "ville", "execution"]


def parse_execution(txt: str):
    """
    'WM7434 EL-ABBADI QACF329' → tracteur WM7434, chauffeur EL-ABBADI, plateau QACF329.
    Plaques = mots contenant un chiffre ; noms = les autres.
    Plus d'un plateau ou d'un nom → accroche / décroche probable.
    """
    toks = _clean(txt).split()
    if not toks:
        return "", "", "", False
    is_plate = [bool(re.search(r"\d", t)) and len(t) >= 4 for t in toks]
    tracteur = toks[0] if is_plate[0] else ""
    groupes, cur = [], []
    for t, p in zip(toks[1:] if tracteur else toks, is_plate[1:] if tracteur else is_plate):
        if p:
            if cur:
                groupes.append(("nom", " ".join(cur)))
                cur = []
            groupes.append(("plaque", t))
        else:
            cur.append(t)
    if cur:
        groupes.append(("nom", " ".join(cur)))
    noms = [g for k, g in groupes if k == "nom"]
    plaques = [g for k, g in groupes if k == "plaque"]
    chauffeur = noms[0] if noms else ""
    accroche = len(noms) > 1 or len(plaques) > 1
    return tracteur or (plaques[0] if plaques else ""), chauffeur, " / ".join(plaques), accroche


def _pays_arret(cp, act, r):
    """Le planning ne donne pas le pays de l'arrêt : on le déduit d'Origine / Destination."""
    c = _cp_norm(cp)
    po, pd_ = r.get("pays_orig", "").upper(), r.get("pays_dest", "").upper()
    if c and c == _cp_norm(r.get("cp_orig")) and po:
        return po
    if c and c == _cp_norm(r.get("cp_dest")) and pd_:
        return pd_
    guess = (po if act == "CH" else pd_) or po or pd_
    digits = re.sub(r"\D", "", _clean(cp))
    if len(digits) == 5 and guess in ("B", "L", "NL", "A", "CH", ""):
        guess = "F"
    elif len(digits) == 4 and guess in ("F", "D", "E", "I", ""):
        guess = "B"
    return guess


def parse_planning(file, file_idx: int):
    df = pd.read_excel(file, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    by_norm = {}
    for c in df.columns:
        by_norm.setdefault(_norm(c), c)
    col_map = {}
    for role, cands in PLAN_COLS.items():
        col_map[role] = next((by_norm[_norm(c)] for c in cands if _norm(c) in by_norm), None)
    manquantes = [r for r in OBLIGATOIRES if not col_map.get(r)]
    if manquantes:
        raise ValueError(f"colonnes introuvables : {manquantes}")

    nom_fichier = getattr(file, "name", f"fichier {file_idx + 1}")
    rows = []
    for i, src in df.iterrows():
        r = {role: (_clean(src[col]) if col else "") for role, col in col_map.items()}
        if not r["dossier"]:
            continue
        r["dossier"] = re.sub(r"\.0+$", "", r["dossier"])
        act = r["activite"].upper()
        r["activite"] = "CH" if act.startswith("CH") else ("DECH" if act.startswith("DE") else act)
        r["tracteur"], r["chauffeur"], r["plateau"], r["accroche"] = parse_execution(r["execution"])
        r["pays"] = _pays_arret(r["cp"], r["activite"], r)
        r["cp"] = re.sub(r"\.0+$", "", r["cp"])
        r["seq_num"] = _to_float(r["seq"])
        r["ts_plan"] = _to_ts(src[col_map["date"]] if col_map["date"] else None, r["heure"])
        r["ts_arr"] = _to_ts(src[col_map["date_ob"]], r["ob_de"]) if col_map["date_ob"] else pd.NaT
        r["ts_dep"] = _to_ts(src[col_map["date_ob"]], r["ob_a"]) if col_map["date_ob"] else pd.NaT
        if pd.notna(r["ts_arr"]) and pd.notna(r["ts_dep"]) and r["ts_dep"] < r["ts_arr"]:
            r["ts_dep"] += pd.Timedelta(days=1)          # départ après minuit
        r["realise"] = pd.notna(r["ts_arr"])
        odo = _to_float(r["odo"])
        r["odo_km"] = odo if odo and odo > 0 else np.nan
        r["poids_t"] = _to_float(r["poids"])
        r["fichier"] = nom_fichier
        r["file_idx"] = file_idx
        r["ligne"] = int(i) + 2
        rows.append(r)
    return pd.DataFrame(rows)


def ordonner(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ordre de la tournée par tracteur.
    Dans un même fichier : la Séq. fait foi. Entre fichiers : fusion sur la date
    planifiée, sans jamais casser l'ordre Séq. d'un fichier.
    """
    out = []
    for tr, g in df.groupby("tracteur", sort=True):
        blocs = []
        for _, b in g.groupby("file_idx", sort=True):
            b = b.sort_values(["seq_num", "ligne"], kind="stable")
            blocs.append([(r.ts_plan if pd.notna(r.ts_plan) else pd.Timestamp.max, r.file_idx, k, idx)
                          for k, (idx, r) in enumerate(b.iterrows())])
        ordre = [t[3] for t in heapq.merge(*blocs, key=lambda t: (t[0], t[1], t[2]))]
        o = g.loc[ordre].copy()
        o["ordre"] = range(1, len(o) + 1)
        out.append(o)
    return pd.concat(out, ignore_index=True) if out else df


def charger_plannings(files):
    frames, erreurs = [], []
    for k, f in enumerate(files):
        try:
            frames.append(parse_planning(f, k))
        except Exception as e:
            erreurs.append(f"{getattr(f, 'name', k)} : {e}")
    if not frames:
        return pd.DataFrame(), erreurs, 0
    df = pd.concat(frames, ignore_index=True)
    n0 = len(df)
    df = df.drop_duplicates(subset=["tracteur", "dossier", "activite", "cp", "ville", "seq", "ts_plan"],
                            keep="first")
    return ordonner(df.reset_index(drop=True)), erreurs, n0 - len(df)


# ══════════════════════════════════════════════════════════════════
#  FICHIER CA
# ══════════════════════════════════════════════════════════════════

def parse_ca(file):
    df = pd.read_excel(file, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    by_norm = {_norm(c): c for c in df.columns}

    def _find(cands):
        return next((by_norm[_norm(c)] for c in cands if _norm(c) in by_norm), None)

    c_dos = _find(["N° Dossier", "N°Dossier", "Dossier"])
    c_tot = _find(["Total des ventes", "Total ventes", "Total des vente"])
    c_cli = _find(["Client facturation", "Client"])
    c_eta = _find(["Etat vente", "État vente", "Etat"])
    if not c_dos or not c_tot:
        raise ValueError(f"colonnes CA manquantes — disponibles : {list(df.columns)}")
    ca = {}
    for _, r in df.iterrows():
        d = re.sub(r"\.0+$", "", _clean(r[c_dos]))
        if not d:
            continue
        v = _to_float(r[c_tot])
        v = 0.0 if np.isnan(v) else v
        if d in ca:
            ca[d]["ca"] += v
        else:
            ca[d] = {"ca": v, "client": _clean(r[c_cli]) if c_cli else "",
                     "etat": _clean(r[c_eta]) if c_eta else ""}
    return ca


# ══════════════════════════════════════════════════════════════════
#  MOTEUR : cargaison à bord, trajets, imputation
# ══════════════════════════════════════════════════════════════════

def _lieu(r, prefix=""):
    if prefix:
        return (r.get(f"ville_{prefix}", ""), _clean(r.get(f"cp_{prefix}", "")).split(".")[0],
                r.get(f"pays_{prefix}", "").upper())
    return (r["ville"], r["cp"], r["pays"])


def construire_trajets(stops: pd.DataFrame, reconstituer: bool = True):
    """
    Retourne la liste des trajets (sans km) avec leur cargaison et le type.
    Chaque trajet : tracteur, de/à (lieu + arrêt), dossiers à bord, type, dossier_prec / dossier_suiv.
    """
    trajets, controles = [], []
    for tr, g in stops.groupby("tracteur", sort=True):
        g = g.sort_values("ordre").to_dict("records")
        dernier_dech = {}
        premier = {}
        for k, r in enumerate(g):
            premier.setdefault(r["dossier"], (k, r["activite"]))
            if r["activite"] == "DECH":
                dernier_dech[r["dossier"]] = k

        # Dossiers déjà à bord au début (chargés avant la période)
        a_bord = {d for d, (k, act) in premier.items() if act == "DECH"}
        for d in sorted(a_bord):
            controles.append(dict(tracteur=tr, dossier=d, type="Chargement avant la période",
                                  detail="Dossier déchargé sans chargement dans le fichier — "
                                         + ("chargement reconstitué depuis Origine." if reconstituer
                                            else "km chargés incomplets.")))
        if reconstituer and g and g[0]["activite"] == "DECH":
            r0 = g[0]
            o = _lieu(r0, "orig")
            if o[0] or o[1]:
                trajets.append(dict(
                    tracteur=tr, chauffeur=r0["chauffeur"], ordre=0, reconstitue=True,
                    de_nom=r0.get("nom_orig", ""), de=o, de_act="CH*", de_ts=pd.NaT, de_odo=np.nan,
                    a_nom=r0["nom"], a=_lieu(r0), a_act=r0["activite"], a_ts=r0["ts_arr"], a_odo=r0["odo_km"],
                    a_bord=tuple(sorted(a_bord)), dossier_prec="", dossier_suiv=r0["dossier"]))

        dernier_livre = ""
        for k in range(len(g)):
            r = g[k]
            d = r["dossier"]
            if r["activite"] == "CH":
                a_bord.add(d)
            elif r["activite"] == "DECH" and dernier_dech.get(d) == k:
                a_bord.discard(d)
                dernier_livre = d
            if k == len(g) - 1:
                break
            n = g[k + 1]
            suiv = next((x["dossier"] for x in g[k + 1:] if x["activite"] == "CH"), "")
            trajets.append(dict(
                tracteur=tr, chauffeur=r["chauffeur"] or n["chauffeur"], ordre=k + 1, reconstitue=False,
                de_nom=r["nom"], de=_lieu(r), de_act=r["activite"], de_ts=r["ts_dep"], de_odo=r["odo_km"],
                a_nom=n["nom"], a=_lieu(n), a_act=n["activite"], a_ts=n["ts_arr"], a_odo=n["odo_km"],
                a_bord=tuple(sorted(a_bord)), dossier_prec=dernier_livre, dossier_suiv=suiv))

        # Dossiers encore à bord à la fin (déchargement après la période / pas encore réalisé)
        if a_bord:
            for d in sorted(a_bord):
                controles.append(dict(tracteur=tr, dossier=d, type="Déchargement après la période",
                                      detail="Dossier chargé sans déchargement dans le fichier — "
                                             + ("déchargement reconstitué depuis Destination." if reconstituer
                                                else "km chargés incomplets.")))
            if reconstituer:
                rl = g[-1]
                # Un seul trajet de fin, vers la destination du dossier le plus récemment chargé
                d_fin = next((x["dossier"] for x in reversed(g) if x["dossier"] in a_bord), sorted(a_bord)[0])
                ref = next(x for x in g if x["dossier"] == d_fin)
                dst = _lieu(ref, "dest")
                if dst[0] or dst[1]:
                    trajets.append(dict(
                        tracteur=tr, chauffeur=rl["chauffeur"], ordre=len(g), reconstitue=True,
                        de_nom=rl["nom"], de=_lieu(rl), de_act=rl["activite"], de_ts=rl["ts_dep"],
                        de_odo=rl["odo_km"], a_nom=ref.get("nom_dest", ""), a=dst, a_act="DECH*",
                        a_ts=pd.NaT, a_odo=np.nan, a_bord=tuple(sorted(a_bord)),
                        dossier_prec=dernier_livre, dossier_suiv=""))

    for t in trajets:
        nb = len(t["a_bord"])
        t["type"] = "Reconstitué" if t["reconstitue"] else ("À vide" if nb == 0 else
                                                            ("Chargé" if nb == 1 else "Groupage"))
    return trajets, controles


def imputer(trajets, convention: str):
    """Part de km de chaque trajet attribuée à chaque dossier → liste (tracteur, dossier, km_ch, km_vide)."""
    parts = []
    for t in trajets:
        km = t.get("km")
        if km is None or (isinstance(km, float) and np.isnan(km)):
            continue
        if t["a_bord"]:
            share = km / len(t["a_bord"])
            for d in t["a_bord"]:
                parts.append((t["tracteur"], d, share, 0.0))
        else:
            p, s = t["dossier_prec"], t["dossier_suiv"]
            if convention == "suivant":
                cibles = [s or p]
            elif convention == "moitie" and p and s and p != s:
                cibles = [p, s]
            else:
                cibles = [p or s]
            cibles = [c for c in cibles if c]
            for c in cibles:
                parts.append((t["tracteur"], c, 0.0, km / len(cibles)))
    return pd.DataFrame(parts, columns=["tracteur", "dossier", "km_charge", "km_vide"])


def calculer(stops, ca_dict, convention, reconstituer, progress_cb=None, geocoder=None, distance=None):
    geocoder = geocoder or geocode_stop
    distance = distance or route_km
    trajets, controles = construire_trajets(stops, reconstituer)

    # 1. Géocodage des lieux uniques
    lieux = sorted({t["de"] for t in trajets} | {t["a"] for t in trajets}
                   | {_lieu(r) for r in stops.to_dict("records")})
    coords = {}
    for i, l in enumerate(lieux):
        if progress_cb:
            progress_cb(f"Géocodage {i + 1}/{len(lieux)} : {l[0]} {l[1]}", i / max(len(lieux), 1) * 0.3)
        coords[l] = geocoder(*l)
        if coords[l] is None and (l[0] or l[1]):
            controles.append(dict(tracteur="", dossier="", type="Géocodage échoué",
                                  detail=f"{l[0]} {l[1]} ({l[2]}) — km des trajets concernés non calculés."))

    # 2. Km PTV par trajet
    for i, t in enumerate(trajets):
        if progress_cb:
            progress_cb(f"Km {i + 1}/{len(trajets)} : {t['de'][0]} → {t['a'][0]}",
                        0.3 + i / max(len(trajets), 1) * 0.7)
        a, b = coords.get(t["de"]), coords.get(t["a"])
        t["km"] = 0.0 if t["de"] == t["a"] else distance(a, b)
        t["lat_de"], t["lon_de"] = (a or (np.nan, np.nan))
        t["lat_a"], t["lon_a"] = (b or (np.nan, np.nan))
        odo = t["a_odo"] - t["de_odo"] if pd.notna(t["a_odo"]) and pd.notna(t["de_odo"]) else np.nan
        t["km_compteur"] = odo
        t["releve_groupe"] = bool(pd.notna(odo) and t["km"] and t["km"] > 20 and odo < 0.3 * t["km"])
        if t["type"] == "À vide" and t["km"] and t["km"] > SEUIL_ALERTE_VIDE:
            controles.append(dict(tracteur=t["tracteur"], dossier=t["dossier_suiv"] or t["dossier_prec"],
                                  type=f"Vide > {SEUIL_ALERTE_VIDE} km",
                                  detail=f"{t['de'][0]} → {t['a'][0]} : {t['km']:.0f} km à vide."))

    df_traj = pd.DataFrame(trajets)

    # 3. Imputation par dossier / tracteur
    parts = imputer(trajets, convention)
    dt = parts.groupby(["tracteur", "dossier"], as_index=False)[["km_charge", "km_vide"]].sum()

    # Dossiers présents dans le planning mais sans aucun km imputé (garder pour le CA)
    presents = stops.groupby(["tracteur", "dossier"], as_index=False).size()[["tracteur", "dossier"]]
    dt = presents.merge(dt, on=["tracteur", "dossier"], how="left").fillna({"km_charge": 0.0, "km_vide": 0.0})

    # 4. CA (réparti au prorata des km chargés si le dossier a roulé sur plusieurs tracteurs)
    tot_ch = dt.groupby("dossier")["km_charge"].transform("sum")
    nb_tr = dt.groupby("dossier")["tracteur"].transform("count")
    dt["part_ca"] = np.where(tot_ch > 0, dt["km_charge"] / tot_ch.replace(0, np.nan), 1 / nb_tr)
    dt["ca_dossier"] = dt["dossier"].map(lambda d: ca_dict.get(d, {}).get("ca", np.nan))
    dt["ca_trouve"] = dt["dossier"].map(lambda d: d in ca_dict)
    dt["ca"] = (dt["ca_dossier"].fillna(0) * dt["part_ca"]).round(2)
    dt["client"] = dt["dossier"].map(lambda d: ca_dict.get(d, {}).get("client", ""))
    dt["etat_vente"] = dt["dossier"].map(lambda d: ca_dict.get(d, {}).get("etat", ""))
    dt["km_total"] = dt["km_charge"] + dt["km_vide"]
    dt["renta"] = (dt["ca"] / dt["km_total"].replace(0, np.nan)).round(3).where(dt["ca_trouve"])

    # Infos dossier depuis le planning
    info = stops.sort_values("ordre").groupby(["tracteur", "dossier"]).agg(
        chauffeur=("chauffeur", "first"),
        client_planning=("client_pl", "first"),
        produit=("produit", "first"),
        poids=("poids_t", "max"),
        vente_planning=("vente", "first"),
        chargement=("ville", lambda s: " · ".join(dict.fromkeys(
            stops.loc[s.index][stops.loc[s.index, "activite"] == "CH"]["ville"]))),
        dechargement=("ville", lambda s: " · ".join(dict.fromkeys(
            stops.loc[s.index][stops.loc[s.index, "activite"] == "DECH"]["ville"]))),
        nb_ch=("activite", lambda s: int((s == "CH").sum())),
        nb_dech=("activite", lambda s: int((s == "DECH").sum())),
        date_debut=("ts_plan", "min"),
        realise=("realise", "all"),
    ).reset_index()
    dt = dt.merge(info, on=["tracteur", "dossier"], how="left")
    dt["client"] = np.where(dt["client"] != "", dt["client"], dt["client_planning"])
    groupes = set()
    for t in trajets:
        if len(t["a_bord"]) > 1:
            groupes.update((t["tracteur"], d) for d in t["a_bord"])
    dt["groupage"] = [(r.tracteur, r.dossier) in groupes for r in dt.itertuples()]

    for r in dt[~dt["ca_trouve"]].itertuples():
        controles.append(dict(tracteur=r.tracteur, dossier=r.dossier, type="Dossier sans CA",
                              detail=f"Absent du fichier CA (vente planning : {r.vente_planning or '—'})."))

    # 5. Synthèse par tracteur
    df_flotte = synthese_flotte(stops, df_traj, dt, controles)
    df_ctrl = pd.DataFrame(controles, columns=["tracteur", "dossier", "type", "detail"])
    return df_traj, dt, df_flotte, df_ctrl


def synthese_flotte(stops, df_traj, dt, controles):
    lignes = []
    for tr, g in stops.groupby("tracteur", sort=True):
        tj = df_traj[df_traj["tracteur"] == tr] if not df_traj.empty else df_traj
        km = tj["km"].fillna(0) if not tj.empty else pd.Series(dtype=float)
        km_tot = float(km.sum())
        km_vide = float(km[tj["type"] == "À vide"].sum()) if not tj.empty else 0.0
        km_group = float(km[tj["type"] == "Groupage"].sum()) if not tj.empty else 0.0
        ca = float(dt.loc[dt["tracteur"] == tr, "ca"].sum())
        jours = g["ts_plan"].dropna().dt.normalize().nunique()

        # Contrôle compteur : du premier au dernier arrêt réalisé avec un relevé
        km_cpt, ecart = np.nan, np.nan
        go = g.sort_values("ordre")
        odo = go[go["odo_km"].notna()]
        if len(odo) >= 2 and not tj.empty:
            o1, o2 = odo.iloc[0]["ordre"], odo.iloc[-1]["ordre"]
            km_cpt = float(odo.iloc[-1]["odo_km"] - odo.iloc[0]["odo_km"])
            km_ptv_span = float(tj[(~tj["reconstitue"]) & (tj["ordre"] >= o1) & (tj["ordre"] < o2)]["km"]
                                .fillna(0).sum())
            if km_ptv_span > 0:
                ecart = round((km_cpt - km_ptv_span) / km_ptv_span * 100, 1)
                if abs(ecart) > SEUIL_ECART_ODO:
                    controles.append(dict(tracteur=tr, dossier="", type="Écart compteur / PTV",
                                          detail=f"Compteur {km_cpt:,.0f} km vs PTV {km_ptv_span:,.0f} km "
                                                 f"sur les arrêts réalisés ({ecart:+.1f} %)."))
        chauffeurs = list(dict.fromkeys(c for c in g.sort_values("ordre")["chauffeur"] if c))
        plateaux = list(dict.fromkeys(p for p in g.sort_values("ordre")["plateau"] if p))
        if g["accroche"].any() or len(plateaux) > 1:
            controles.append(dict(tracteur=tr, dossier="", type="Accroche / décroche",
                                  detail=f"Plateaux : {', '.join(plateaux) or '—'} · "
                                         f"chauffeurs : {', '.join(chauffeurs) or '—'}."))
        lignes.append(dict(
            tracteur=tr, chauffeurs=", ".join(chauffeurs), plateaux=", ".join(plateaux),
            debut=g["ts_plan"].min(), fin=g["ts_plan"].max(), jours=jours,
            dossiers=g["dossier"].nunique(), arrets=len(g), ca=round(ca, 2),
            km_charge=round(km_tot - km_vide, 1), km_vide=round(km_vide, 1), km_total=round(km_tot, 1),
            pct_vide=round(km_vide / km_tot * 100, 1) if km_tot else np.nan,
            renta=round(ca / km_tot, 3) if km_tot else np.nan,
            ca_jour=round(ca / jours, 0) if jours else np.nan,
            km_groupage=round(km_group, 1), km_compteur=km_cpt, ecart_compteur=ecart,
            sans_ca=int((~dt.loc[dt["tracteur"] == tr, "ca_trouve"]).sum()),
        ))
    return pd.DataFrame(lignes)


# ══════════════════════════════════════════════════════════════════
#  EXPORT EXCEL
# ══════════════════════════════════════════════════════════════════

COLS_FLOTTE = {
    "tracteur": "Tracteur", "chauffeurs": "Chauffeur(s)", "plateaux": "Plateau(x)",
    "jours": "Jours", "dossiers": "Dossiers", "ca": "CA (€)", "km_charge": "KM chargés",
    "km_vide": "KM à vide", "km_total": "KM total", "pct_vide": "% vide", "renta": "Renta €/km",
    "ca_jour": "CA / jour (€)", "sans_ca": "Dossiers sans CA", "km_compteur": "KM compteur", "ecart_compteur": "Écart compteur (%)",
}
COLS_DOSSIERS = {
    "tracteur": "Tracteur", "chauffeur": "Chauffeur", "dossier": "N° dossier", "client": "Client",
    "chargement": "Chargement", "dechargement": "Déchargement", "produit": "Produit", "poids": "Poids (t)",
    "ca": "CA (€)", "km_charge": "KM chargés", "km_vide": "KM à vide", "km_total": "KM total",
    "renta": "Renta €/km", "groupage": "Groupage", "realise": "Réalisé", "etat_vente": "État vente",
    "vente_planning": "Vente planning",
}
COLS_TRAJETS = {
    "tracteur": "Tracteur", "ordre": "Ordre", "de_act": "De (act.)", "de_nom": "De", "de_ville": "Ville départ",
    "a_act": "À (act.)", "a_nom": "À", "a_ville": "Ville arrivée", "type": "Type", "bord": "À bord",
    "km": "KM PTV", "km_compteur": "KM compteur", "a_ts": "Arrivée",
}
COLS_CTRL = {"type": "Contrôle", "tracteur": "Tracteur", "dossier": "N° dossier", "detail": "Détail"}


def _traj_affichage(df_traj):
    if df_traj.empty:
        return df_traj
    d = df_traj.copy()
    d["de_ville"] = d["de"].map(lambda l: f"{l[0]} ({l[2]}-{l[1]})")
    d["a_ville"] = d["a"].map(lambda l: f"{l[0]} ({l[2]}-{l[1]})")
    d["bord"] = d["a_bord"].map(lambda t: ", ".join(t) if t else "—")
    return d


def export_excel(df_flotte, df_dos, df_traj, df_ctrl):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        for nom, df, cols in [("Flotte", df_flotte, COLS_FLOTTE), ("Dossiers", df_dos, COLS_DOSSIERS),
                              ("Trajets", _traj_affichage(df_traj), COLS_TRAJETS), ("Contrôles", df_ctrl, COLS_CTRL)]:
            if df is None or df.empty:
                continue
            c = [k for k in cols if k in df.columns]
            x = df[c].rename(columns=cols).copy()
            for col in x.columns:
                if pd.api.types.is_datetime64_any_dtype(x[col]):
                    x[col] = x[col].dt.strftime("%d/%m/%Y %H:%M").fillna("")
                if x[col].dtype == bool:
                    x[col] = x[col].map({True: "Oui", False: "Non"})
            x.to_excel(w, sheet_name=nom, index=False)
            _style(w.sheets[nom], len(x))
    return out.getvalue()


def _style(ws, n):
    head = PatternFill("solid", fgColor="003087")
    alt = PatternFill("solid", fgColor="EEF2F7")
    for cell in ws[1]:
        cell.fill, cell.font = head, Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in range(2, n + 2):
        if r % 2 == 0:
            for cell in ws[r]:
                cell.fill = alt
    for col in ws.columns:
        L = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(L + 3, 9), 55)
    ws.freeze_panes = "A2"


# ══════════════════════════════════════════════════════════════════
#  INTERFACE
# ══════════════════════════════════════════════════════════════════

def _fmt_eur(v):
    return "—" if v is None or pd.isna(v) else f"{v:,.0f} €".replace(",", " ")


def _fmt_km(v):
    return "—" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", " ")


def _carte(tj: pd.DataFrame, stops_tr: pd.DataFrame):
    import pydeck as pdk
    d = tj.dropna(subset=["lat_de", "lat_a"]).copy()
    if d.empty:
        st.info("Aucun trajet géocodé à afficher.")
        return
    couleurs = {"Chargé": [0, 113, 227], "À vide": [142, 142, 147], "Groupage": [255, 149, 0],
                "Reconstitué": [175, 82, 222]}
    d["color"] = d["type"].map(lambda t: couleurs.get(t, [0, 0, 0]))
    d["path"] = d.apply(lambda r: [[r.lon_de, r.lat_de], [r.lon_a, r.lat_a]], axis=1)
    d["label"] = d.apply(lambda r: f"{r.de[0]} → {r.a[0]} · {r.type} · "
                                   f"{'' if pd.isna(r.km) else f'{r.km:.0f} km'}", axis=1)
    pts = pd.concat([d[["lat_de", "lon_de"]].set_axis(["lat", "lon"], axis=1),
                     d[["lat_a", "lon_a"]].set_axis(["lat", "lon"], axis=1)]).drop_duplicates()
    deck = pdk.Deck(
        layers=[
            pdk.Layer("PathLayer", data=d[["path", "color", "label"]], get_path="path", get_color="color",
                      width_min_pixels=3, pickable=True),
            pdk.Layer("ScatterplotLayer", data=pts, get_position="[lon, lat]", get_radius=4500,
                      radius_min_pixels=4, get_fill_color=[29, 29, 31], pickable=False),
        ],
        initial_view_state=pdk.ViewState(latitude=float(pts["lat"].mean()), longitude=float(pts["lon"].mean()),
                                         zoom=5, pitch=0),
        tooltip={"text": "{label}"},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )
    st.pydeck_chart(deck, use_container_width=True, height=460)
    st.caption("Tracé à vol d'oiseau entre arrêts · bleu chargé · gris à vide · orange groupage · "
               "violet reconstitué. Les km affichés sont les km routiers PTV.")


def _legende_types():
    st.markdown(
        f'<div class="ap-note"><b>Chargé</b> un dossier à bord · <b>À vide</b> rien à bord, imputé selon la '
        f'convention choisie · <b>Groupage</b> plusieurs dossiers à bord, km partagés à parts égales '
        f'(provisoire) · <b>Reconstitué</b> chargement ou déchargement hors période, recalculé depuis '
        f'Origine / Destination du dossier.</div>', unsafe_allow_html=True)


def main():
    from core import ui

    ui.page("renta_plateau", "Exports planning des plateaux : tournées recomposées par tracteur, "
                             "CA par dossier, km chargés et à vide, rentabilité au kilomètre.")

    if not PTV_API_KEY or PTV_API_KEY == "METS_TA_CLE_ICI":
        st.error("Clé PTV_API_KEY non configurée : le calcul des distances ne fonctionnera pas.")

    if st.session_state.get("rp_schema") != RESULT_SCHEMA:
        for k in [k for k in st.session_state if k.startswith("rp_")]:
            st.session_state.pop(k, None)
        st.session_state["rp_schema"] = RESULT_SCHEMA

    # ── Fichiers ──
    ui.section("Fichiers")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Exports planning")
        st.caption("Un ou plusieurs fichiers Traject_xxxxx.xlsx. Les lignes d'un même tracteur sont "
                   "recomposées d'un fichier à l'autre ; les doublons sont retirés.")
        files_pl = st.file_uploader("Plannings (.xlsx)", type=["xlsx"], accept_multiple_files=True,
                                    key="rp_up_pl", label_visibility="collapsed")
    with c2:
        st.markdown("#### Fichier CA")
        st.caption("N° Dossier · Total des ventes · Client facturation · Etat vente")
        file_ca = st.file_uploader("CA (.xlsx)", type=["xlsx"], key="rp_up_ca", label_visibility="collapsed")

    if not files_pl:
        st.markdown(
            '<ul class="ap-list">'
            '<li><b>1. Plannings</b> <span>— exports Traject, un par tracteur ou plusieurs pour le même.</span></li>'
            '<li><b>2. CA</b> <span>— export habituel, jointure sur le N° dossier.</span></li>'
            '<li><b>3. Contrôle</b> <span>— tracteurs détectés, chauffeurs, plateaux, dossiers incomplets.</span></li>'
            '<li><b>4. Calcul PTV</b> <span>— km par trajet, imputation chargé / vide / groupage.</span></li>'
            '<li><b>5. Résultats</b> <span>— flotte, tournée par camion, dossiers, contrôles, export Excel.</span></li>'
            '</ul>', unsafe_allow_html=True)
        return

    stops, erreurs, doublons = charger_plannings(files_pl)
    for e in erreurs:
        st.error(f"Lecture impossible — {e}")
    if stops.empty:
        return
    ca_dict = {}
    if file_ca:
        try:
            ca_dict = parse_ca(file_ca)
        except Exception as e:
            st.error(f"Fichier CA : {e}")

    # ── Périmètre ──
    ui.section("Périmètre")
    p1, p2, p3 = st.columns([1.2, 1, 1])
    with p1:
        dmin, dmax = stops["ts_plan"].min(), stops["ts_plan"].max()
        if pd.notna(dmin) and pd.notna(dmax):
            periode = st.date_input("Période (date planifiée de l'arrêt)", value=(dmin.date(), dmax.date()),
                                    min_value=dmin.date(), max_value=dmax.date(), format="DD/MM/YYYY")
        else:
            periode = None
    with p2:
        types = sorted(t for t in stops["type_trans"].unique() if t)
        f_types = st.multiselect("Type de transport", types, default=[t for t in types if t == "PLA"] or types)
    with p3:
        tracteurs = sorted(t for t in stops["tracteur"].unique() if t)
        f_tr = st.multiselect("Tracteurs", tracteurs, default=[], placeholder="Tous")

    o1, o2, o3 = st.columns([1.2, 1, 1])
    with o1:
        convention = st.radio("Km à vide imputés au", list(CONVENTIONS_VIDE), format_func=CONVENTIONS_VIDE.get,
                              horizontal=False)
    with o2:
        realise_seul = st.toggle("Arrêts réalisés uniquement", value=True,
                                 help="Exclut les arrêts planifiés sans pointage OB (trajets à venir).")
    with o3:
        reconstituer = st.toggle("Reconstituer les dossiers coupés", value=True,
                                 help="Ajoute le trajet chargé manquant depuis Origine (dossier commencé avant "
                                      "la période) ou vers Destination (dossier terminé après).")

    sel = stops.copy()
    if periode and isinstance(periode, (tuple, list)) and len(periode) == 2:
        a, b = pd.Timestamp(periode[0]), pd.Timestamp(periode[1]) + pd.Timedelta(days=1)
        sel = sel[(sel["ts_plan"] >= a) & (sel["ts_plan"] < b) | sel["ts_plan"].isna()]
    if f_types:
        sel = sel[sel["type_trans"].isin(f_types) | (sel["type_trans"] == "")]
    if f_tr:
        sel = sel[sel["tracteur"].isin(f_tr)]
    if realise_seul:
        sel = sel[sel["realise"]]
    sel = sel[sel["tracteur"] != ""]

    nb_dos = sel["dossier"].nunique()
    nb_ca = sum(1 for d in sel["dossier"].unique() if d in ca_dict)
    k = st.columns(5)
    k[0].metric("Tracteurs", sel["tracteur"].nunique())
    k[1].metric("Dossiers", nb_dos)
    k[2].metric("Arrêts", len(sel))
    k[3].metric("Dossiers avec CA", f"{nb_ca}/{nb_dos}" if file_ca else "—")
    k[4].metric("Doublons retirés", doublons)
    if not file_ca:
        st.info("Ajoutez le fichier CA pour obtenir la rentabilité. Sans lui, seuls les km sont calculés.")
    if sel.empty:
        st.warning("Aucun arrêt dans le périmètre choisi.")
        return

    with st.expander("Tracteurs détectés"):
        det = sel.sort_values("ordre").groupby("tracteur").agg(
            chauffeurs=("chauffeur", lambda s: ", ".join(dict.fromkeys(x for x in s if x))),
            plateaux=("plateau", lambda s: ", ".join(dict.fromkeys(x for x in s if x))),
            fichiers=("fichier", lambda s: ", ".join(dict.fromkeys(s))),
            arrets=("dossier", "size"), dossiers=("dossier", "nunique"),
            debut=("ts_plan", "min"), fin=("ts_plan", "max")).reset_index()
        st.dataframe(det, hide_index=True, use_container_width=True, column_config={
            "tracteur": "Tracteur", "chauffeurs": "Chauffeur(s)", "plateaux": "Plateau(x)",
            "fichiers": "Fichier(s)", "arrets": "Arrêts", "dossiers": "Dossiers",
            "debut": st.column_config.DatetimeColumn("Début", format="DD/MM/YY"),
            "fin": st.column_config.DatetimeColumn("Fin", format="DD/MM/YY")})

    # ── Calcul ──
    st.write("")
    if st.button("Calculer les km et la rentabilité", type="primary"):
        for key in ["rp_res"]:
            st.session_state.pop(key, None)
        bar, txt = st.progress(0.0), st.empty()

        def _p(msg, pct):
            txt.caption(msg)
            bar.progress(min(max(pct, 0.0), 1.0))
        try:
            res = calculer(sel, ca_dict, convention, reconstituer, progress_cb=_p)
            st.session_state["rp_res"] = dict(res=res, sel=sel, convention=convention)
            bar.progress(1.0)
            txt.empty()
        except Exception as e:
            st.session_state.pop("rp_res", None)
            st.error(f"Erreur pendant le calcul : {e}")

    if "rp_res" not in st.session_state:
        return
    df_traj, df_dos, df_flotte, df_ctrl = st.session_state["rp_res"]["res"]
    sel_c = st.session_state["rp_res"]["sel"]

    # ── Synthèse ──
    ui.section("Synthèse")
    ca_t, km_t = df_flotte["ca"].sum(), df_flotte["km_total"].sum()
    km_v = df_flotte["km_vide"].sum()
    m = st.columns(5)
    m[0].metric("CA", _fmt_eur(ca_t))
    m[1].metric("KM total", _fmt_km(km_t))
    m[2].metric("% à vide", f"{km_v / km_t * 100:.1f} %" if km_t else "—")
    m[3].metric("Renta €/km", f"{ca_t / km_t:.3f}" if km_t else "—")
    m[4].metric("Contrôles", len(df_ctrl))

    t_fl, t_tour, t_dos, t_ctrl = st.tabs(["Flotte", "Tournée par camion", "Dossiers", "Contrôles"])

    with t_fl:
        st.dataframe(
            df_flotte.sort_values("renta", ascending=False)[list(COLS_FLOTTE)],
            hide_index=True, use_container_width=True,
            column_config={
                "tracteur": "Tracteur", "chauffeurs": "Chauffeur(s)", "plateaux": "Plateau(x)",
                "jours": "Jours", "dossiers": "Dossiers",
                "ca": st.column_config.NumberColumn("CA", format="%.0f €"),
                "km_charge": st.column_config.NumberColumn("KM chargés", format="%.0f"),
                "km_vide": st.column_config.NumberColumn("KM à vide", format="%.0f"),
                "km_total": st.column_config.NumberColumn("KM total", format="%.0f"),
                "pct_vide": st.column_config.ProgressColumn("% vide", format="%.1f %%", min_value=0, max_value=50),
                "renta": st.column_config.NumberColumn("Renta €/km", format="%.3f"),
                "ca_jour": st.column_config.NumberColumn("CA / jour", format="%.0f €"),
                "sans_ca": st.column_config.NumberColumn("Sans CA", help="Dossiers absents du fichier CA : "
                                                         "leurs km comptent, pas leur CA — renta sous-estimée."),
                "km_compteur": st.column_config.NumberColumn("KM compteur", format="%.0f"),
                "ecart_compteur": st.column_config.NumberColumn("Écart compteur", format="%+.1f %%"),
            })
        st.caption("Le compteur couvre du premier au dernier arrêt pointé ; l'écart est calculé face aux km PTV "
                   "du même intervalle. Renta = CA ÷ km total du camion (ratio des sommes).")

    with t_tour:
        trs = df_flotte["tracteur"].tolist()
        tr = st.selectbox("Tracteur", trs, format_func=lambda t: (
            f"{t} — {df_flotte.set_index('tracteur').at[t, 'chauffeurs']}"))
        f = df_flotte.set_index("tracteur").loc[tr]
        q = st.columns(5)
        q[0].metric("CA", _fmt_eur(f["ca"]))
        q[1].metric("KM chargés", _fmt_km(f["km_charge"]))
        q[2].metric("KM à vide", _fmt_km(f["km_vide"]))
        q[3].metric("Renta €/km", "—" if pd.isna(f["renta"]) else f"{f['renta']:.3f}")
        q[4].metric("KM compteur", _fmt_km(f["km_compteur"]),
                    None if pd.isna(f["ecart_compteur"]) else f"{f['ecart_compteur']:+.1f} % vs PTV",
                    delta_color="off")
        tj = _traj_affichage(df_traj[df_traj["tracteur"] == tr].sort_values("ordre"))
        _carte(tj, sel_c[sel_c["tracteur"] == tr])

        # Arrêts avec temps sur site
        ar = sel_c[sel_c["tracteur"] == tr].sort_values("ordre").copy()
        ar["temps_site"] = ((ar["ts_dep"] - ar["ts_arr"]).dt.total_seconds() / 3600).round(1)
        st.markdown("#### Trajets")
        _legende_types()
        st.dataframe(
            tj[["ordre", "de_act", "de_nom", "de_ville", "a_act", "a_nom", "a_ville", "type", "bord", "km",
                "km_compteur", "a_ts"]],
            hide_index=True, use_container_width=True,
            column_config={
                "ordre": "N°", "de_act": "", "de_nom": "Départ", "de_ville": "Ville", "a_act": "",
                "a_nom": "Arrivée", "a_ville": "Ville", "type": "Type", "bord": "À bord",
                "km": st.column_config.NumberColumn("KM PTV", format="%.0f"),
                "km_compteur": st.column_config.NumberColumn("KM compteur", format="%.0f",
                                                             help="Indicatif : relevés parfois groupés."),
                "a_ts": st.column_config.DatetimeColumn("Arrivée", format="DD/MM HH:mm")})
        st.markdown("#### Arrêts")
        st.dataframe(
            ar[["ordre", "dossier", "activite", "nom", "ville", "pays", "ts_plan", "ts_arr", "ts_dep",
                "temps_site", "odo_km", "chauffeur", "plateau"]],
            hide_index=True, use_container_width=True,
            column_config={
                "ordre": "N°", "dossier": "Dossier", "activite": "Act.", "nom": "Lieu", "ville": "Ville",
                "pays": "Pays", "ts_plan": st.column_config.DatetimeColumn("Prévu", format="DD/MM HH:mm"),
                "ts_arr": st.column_config.DatetimeColumn("Arrivée", format="DD/MM HH:mm"),
                "ts_dep": st.column_config.DatetimeColumn("Départ", format="DD/MM HH:mm"),
                "temps_site": st.column_config.NumberColumn("Sur site (h)", format="%.1f"),
                "odo_km": st.column_config.NumberColumn("Compteur", format="%.0f"),
                "chauffeur": "Chauffeur", "plateau": "Plateau"})
        longs = ar[ar["temps_site"] > SEUIL_TEMPS_SITE]
        if not longs.empty:
            st.caption(f"{len(longs)} arrêt(s) de plus de {SEUIL_TEMPS_SITE:.0f} h sur site : "
                       + ", ".join(f"{r.ville} ({r.temps_site:.1f} h)" for r in longs.itertuples()))

    with t_dos:
        dd = df_dos.sort_values(["tracteur", "date_debut"])
        clients = sorted(c for c in dd["client"].dropna().unique() if c)
        fc = st.multiselect("Client", clients, default=[], placeholder="Tous les clients")
        if fc:
            dd = dd[dd["client"].isin(fc)]
        st.dataframe(
            dd[list(COLS_DOSSIERS)], hide_index=True, use_container_width=True,
            column_config={
                "tracteur": "Tracteur", "chauffeur": "Chauffeur", "dossier": "Dossier", "client": "Client",
                "chargement": "Chargement", "dechargement": "Déchargement", "produit": "Produit",
                "poids": st.column_config.NumberColumn("Poids (t)", format="%.2f"),
                "ca": st.column_config.NumberColumn("CA", format="%.2f €"),
                "km_charge": st.column_config.NumberColumn("KM chargés", format="%.0f"),
                "km_vide": st.column_config.NumberColumn("KM à vide", format="%.0f"),
                "km_total": st.column_config.NumberColumn("KM total", format="%.0f"),
                "renta": st.column_config.NumberColumn("Renta €/km", format="%.3f"),
                "groupage": "Groupage", "realise": "Réalisé", "etat_vente": "État vente",
                "vente_planning": "Vente planning"})
        if not dd.empty:
            par_client = dd.groupby("client", as_index=False).agg(
                dossiers=("dossier", "nunique"), ca=("ca", "sum"), km=("km_total", "sum"))
            par_client["renta"] = (par_client["ca"] / par_client["km"].replace(0, np.nan)).round(3)
            st.markdown("#### Par client")
            st.dataframe(par_client.sort_values("ca", ascending=False), hide_index=True,
                         use_container_width=True, column_config={
                             "client": "Client", "dossiers": "Dossiers",
                             "ca": st.column_config.NumberColumn("CA", format="%.0f €"),
                             "km": st.column_config.NumberColumn("KM", format="%.0f"),
                             "renta": st.column_config.NumberColumn("Renta €/km", format="%.3f")})

    with t_ctrl:
        if df_ctrl.empty:
            st.success("Aucune anomalie détectée.")
        else:
            resume = df_ctrl.groupby("type").size().sort_values(ascending=False)
            st.caption(" · ".join(f"{t} : {n}" for t, n in resume.items()))
            st.dataframe(df_ctrl[list(COLS_CTRL)], hide_index=True, use_container_width=True,
                         column_config={"type": "Contrôle", "tracteur": "Tracteur", "dossier": "Dossier",
                                        "detail": "Détail"})

    st.write("")
    b1, b2 = st.columns([1, 1])
    with b1:
        st.download_button("Télécharger le rapport Excel", data=export_excel(df_flotte, df_dos, df_traj, df_ctrl),
                           file_name="Rapport_Renta_Plateau.xlsx", type="primary",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with b2:
        if st.button("Nouveau calcul"):
            st.session_state.pop("rp_res", None)
            st.rerun()


if os.environ.get("RENTA_PLATEAU_NO_UI") != "1":
    main()
