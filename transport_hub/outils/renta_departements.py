"""
renta_departements.py
──────────────────────────────────────────────────────────────────
Rentabilité par DÉPARTEMENT de déchargement — Lot sec vs Groupage
──────────────────────────────────────────────────────────────────
Entrées :
  • Fichier CA       (.xlsx) — montants par dossier
  • Fichier Missions (.xlsx) — 1 ligne par stop (CHARGER / DECHARGER / ...)

Apports du fichier missions :
  • Classification LOT SEC / GROUPAGE (chargement, livraison, complet)
  • KM chargés en route chaînée multi-stops (au lieu d'un A→B direct)
  • KM À VIDE par chaînage tracteur (dernier déchargement → chargement suivant)
  • Département de livraison réel (dominant ou prorata)
──────────────────────────────────────────────────────────────────
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import os
import io
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  CONFIG PTV
# ══════════════════════════════════════════════════════════════════

PTV_API_KEY  = os.environ.get("PTV_API_KEY", "METS_TA_CLE_ICI")
PTV_BASE_URL = "https://api.myptv.com/routing/v1"
GEOCODE_URL  = "https://api.myptv.com/geocoding/v1"
HEADERS      = {"apiKey": PTV_API_KEY}
MAX_RETRIES  = 3
RETRY_DELAY  = 2
MAX_WORKERS  = 4
VEHICLE      = "EUR_TRAILER_TRUCK"

try:
    from excel_handler_km import PAYS_MAP, parse_origin_from_parts
except ImportError:
    PAYS_MAP = {
        "F": "France", "B": "Belgium", "D": "Germany", "L": "Luxembourg",
        "NL": "Netherlands", "E": "Spain", "I": "Italy", "CH": "Switzerland",
        "GB": "United Kingdom", "A": "Austria", "P": "Portugal",
        "FR": "France", "BE": "Belgium", "DE": "Germany", "LU": "Luxembourg",
        "IT": "Italy", "ES": "Spain", "AT": "Austria", "PT": "Portugal",
    }

    def parse_origin_from_parts(city, cp, country):
        pays_full = PAYS_MAP.get(str(country).strip().upper(), country)
        return ", ".join(p for p in [city, cp, pays_full] if p and p != "nan")

PAYS_TO_ISO2 = {
    "F": "FR", "B": "BE", "D": "DE", "L": "LU", "I": "IT", "E": "ES",
    "A": "AT", "P": "PT", "CH": "CH", "GB": "GB", "NL": "NL",
    "FR": "FR", "BE": "BE", "DE": "DE", "LU": "LU", "IT": "IT",
    "ES": "ES", "AT": "AT", "PT": "PT",
}

PAYS_LABELS = {
    "F": "🇫🇷 France", "B": "🇧🇪 Belgique", "L": "🇱🇺 Luxembourg",
    "NL": "🇳🇱 Pays-Bas", "D": "🇩🇪 Allemagne", "CH": "🇨🇭 Suisse",
    "I": "🇮🇹 Italie", "E": "🇪🇸 Espagne", "GB": "🇬🇧 Royaume-Uni",
    "A": "🇦🇹 Autriche", "P": "🇵🇹 Portugal",
}

BASES_CA = {
    "💶 Total des ventes":            "total_vente",
    "🚚 Prix transport seul":         "prix_transport",
    "⛽ Prix transport + S.G.":       "prix_sg",
    "➕ Prix transport + suppléments": "prix_supp",
}

BASES_AIDE = {
    "total_vente":    "Prix transport + suppléments + S.G. + heures d'attente (facturation totale).",
    "prix_transport": "Prix transport nu, hors surcharge gasoil, suppléments et attente.",
    "prix_sg":        "Prix transport + surcharge gasoil, hors suppléments et attente.",
    "prix_supp":      "Prix transport + suppléments, hors surcharge gasoil et attente.",
}

# ══════════════════════════════════════════════════════════════════
#  DÉPARTEMENTS FRANÇAIS
# ══════════════════════════════════════════════════════════════════

DEPT_NOMS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze",
    "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne",
    "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne",
    "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise",
    "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin",
    "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe",
    "73": "Savoie", "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime",
    "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme",
    "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges",
    "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}

PAYS_FRANCE = {"F", "FR", "FRA", "FRANCE"}


def normalize_cp_fr(cp):
    cp = re.sub(r"[^0-9A-Za-z]", "", str(cp or "").strip()).upper()
    if not cp or cp == "NAN":
        return ""
    if cp.isdigit() and len(cp) == 4:
        cp = "0" + cp
    return cp


def extract_departement(cp, pays):
    pays_n = str(pays or "").strip().upper()
    cp_n   = normalize_cp_fr(cp)
    if not cp_n:
        return None
    if pays_n not in PAYS_FRANCE:
        if pays_n not in ("", "NAN", "NONE"):
            return None
        if not (cp_n.isdigit() and len(cp_n) == 5):
            return None
    if cp_n.startswith("2A"):
        return "2A"
    if cp_n.startswith("2B"):
        return "2B"
    if cp_n.startswith("20") and cp_n.isdigit() and len(cp_n) == 5:
        return "2A" if int(cp_n) < 20200 else "2B"
    if cp_n[:2] in ("97", "98") and len(cp_n) >= 3:
        return cp_n[:3]
    if len(cp_n) >= 2:
        return cp_n[:2]
    return None


def dept_label(code):
    if not code:
        return ""
    nom = DEPT_NOMS.get(code, "")
    return f"{code} — {nom}" if nom else str(code)


# ══════════════════════════════════════════════════════════════════
#  PTV
# ══════════════════════════════════════════════════════════════════

def _ptv_by_text(query):
    if not query:
        return None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(f"{GEOCODE_URL}/locations/by-text",
                             params={"searchText": query}, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(RETRY_DELAY * attempt)
                continue
            if r.status_code != 200:
                return None
            locs = r.json().get("locations", [])
            if locs:
                p = locs[0]["referencePosition"]
                return (p["latitude"], p["longitude"])
            return None
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


def _ptv_by_postal_code(cp, iso2):
    if not cp or not iso2:
        return None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(f"{GEOCODE_URL}/locations/by-postal-code",
                             params={"postalCode": cp, "countryCode": iso2},
                             headers=HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(RETRY_DELAY * attempt)
                continue
            if r.status_code != 200:
                return None
            locs = r.json().get("locations", [])
            if locs:
                p = locs[0]["referencePosition"]
                return (p["latitude"], p["longitude"])
            return None
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


def geocode_point(ville, cp, pays):
    pays      = str(pays or "").strip().upper()
    pays_full = PAYS_MAP.get(pays, pays)
    iso2      = PAYS_TO_ISO2.get(pays, pays if len(pays) == 2 else "")
    cp        = str(cp or "").strip()
    ville     = str(ville or "").strip()

    if ville and cp and pays_full:
        r = _ptv_by_text(f"{ville}, {cp}, {pays_full}")
        if r:
            return r
    if cp and iso2:
        r = _ptv_by_postal_code(cp, iso2)
        if r:
            return r
    if ville and pays_full:
        r = _ptv_by_text(f"{ville}, {pays_full}")
        if r:
            return r
    return None


def calculate_route(coords):
    """Route chaînée sur N points. Rayon large sur les points intermédiaires."""
    coords = [c for c in coords if c]
    if len(coords) < 2:
        return None
    params = [("profile", VEHICLE)]
    for i, (lat, lon) in enumerate(coords):
        if 0 < i < len(coords) - 1:
            params.append(("waypoints", f"{lat},{lon};radius=5000"))
        else:
            params.append(("waypoints", f"{lat},{lon}"))
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(f"{PTV_BASE_URL}/routes", headers=HEADERS,
                             params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(RETRY_DELAY * attempt)
                continue
            if r.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            d = r.json()
            return {"km": round(d.get("distance", 0) / 1000, 1),
                    "h":  round(d.get("travelTime", 0) / 3600, 2)}
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


# ══════════════════════════════════════════════════════════════════
#  PARSING
# ══════════════════════════════════════════════════════════════════

def _norm_col(s):
    s = str(s).strip().lower()
    for a, b in [("é","e"),("è","e"),("ê","e"),("à","a"),("â","a"),
                 ("ô","o"),("û","u"),("î","i"),("ù","u"),("ç","c")]:
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def _map_cols(df, candidates):
    cols = {_norm_col(c): c for c in df.columns}
    out = {}
    for role, cands in candidates.items():
        found = None
        for cand in cands:
            k = _norm_col(cand)
            if k in cols:
                found = cols[k]
                break
        out[role] = found
    return out


def _c(v):
    v = str(v or "").strip()
    return "" if v.lower() in ("nan", "none", "nat") else v


def to_float(s):
    try:
        return float(str(s).replace(",", ".").replace("\xa0", "")
                     .replace(" ", "").replace("€", "").strip())
    except Exception:
        return 0.0


# ── Activités ────────────────────────────────────────────────────
#  CHARGEMENT / DECHARGEMENT : structurants (classification + route)
#  TRANSIT   : douane, tunnel, bateau — points de passage
#  TECHNIQUE : accrochage, dépôt, lavage, positionnement — vrais arrêts
ACT_EXACT = {
    "CHARGER": "CHARGEMENT", "CHARGEMENT": "CHARGEMENT",
    "DECHARGER": "DECHARGEMENT", "DÉCHARGER": "DECHARGEMENT",
    "DECHARGEMENT": "DECHARGEMENT", "DÉCHARGEMENT": "DECHARGEMENT",
    "DOUANE": "TRANSIT", "TRANSIT": "TRANSIT", "TUNNEL": "TRANSIT",
    "BATEAU IN": "TRANSIT", "BATEAU OUT": "TRANSIT",
    "ACCROCHER": "TECHNIQUE", "DECROCHER": "TECHNIQUE", "DÉCROCHER": "TECHNIQUE",
    "DEPOT IN": "TECHNIQUE", "DEPOT OUT": "TECHNIQUE", "DÉPOT IN": "TECHNIQUE",
    "DÉPOT OUT": "TECHNIQUE", "POSITIONNEMENT": "TECHNIQUE", "LAVAGE": "TECHNIQUE",
}

ACT_KEYWORDS = [
    ("dechargement", "DECHARGEMENT"), ("déchargement", "DECHARGEMENT"),
    ("decharger", "DECHARGEMENT"), ("décharger", "DECHARGEMENT"),
    ("chargement", "CHARGEMENT"), ("charger", "CHARGEMENT"),
    ("douane", "TRANSIT"), ("tunnel", "TRANSIT"), ("bateau", "TRANSIT"),
    ("accroch", "TECHNIQUE"), ("decroch", "TECHNIQUE"), ("décroch", "TECHNIQUE"),
    ("depot", "TECHNIQUE"), ("dépot", "TECHNIQUE"), ("dépôt", "TECHNIQUE"),
    ("lavage", "TECHNIQUE"), ("positionnement", "TECHNIQUE"),
]


def normalize_activite(val):
    """Exact d'abord, puis mots-clés du plus long au plus court.
    L'ordre est critique : 'DECHARGER' contient 'charger'."""
    raw = str(val or "").strip().upper()
    if raw in ACT_EXACT:
        return ACT_EXACT[raw]
    low = raw.lower()
    for kw, mapped in sorted(ACT_KEYWORDS, key=lambda x: -len(x[0])):
        if kw in low:
            return mapped
    return "AUTRE"


MISSIONS_COLS = {
    "dossier":        ["N° Dossier", "N°Dossier", "Dossier"],
    "activite":       ["Activité", "Activite"],
    "date":           ["Date"],
    "heure":          ["Heure"],
    "type_transport": ["Type de transport"],
    "nom1":           ["Nom 1", "Nom1"],
    "nom2":           ["Nom 2", "Nom2"],
    "adresse":        ["Adresse"],
    "numero":         ["Numéro", "Numero"],
    "code_pays":      ["Code pays"],
    "code_postal":    ["Code postal"],
    "localite":       ["Localité", "Localite"],
    "produit":        ["Produit"],
    "chauffeur":      ["Chauffeur"],
    "tracteur":       ["Immat. tracteur", "Immat tracteur", "Tracteur"],
    "remorque":       ["Remorque"],
}


@st.cache_data(show_spinner=False)
def parse_missions(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    cm = _map_cols(df, MISSIONS_COLS)

    manquantes = [r for r in ("dossier", "activite", "code_postal", "code_pays")
                  if cm.get(r) is None]
    if manquantes:
        st.error(f"Colonnes missions manquantes : {manquantes}\n\n{list(df.columns)}")
        st.stop()

    df = df.rename(columns={v: k for k, v in cm.items() if v})
    for c in MISSIONS_COLS:
        if c not in df.columns:
            df[c] = ""

    df["dossier"] = df["dossier"].astype(str).str.strip()
    df = df[df["dossier"].str.match(r"^\d+", na=False)].copy()

    for c in ("localite", "code_postal", "code_pays", "nom1", "chauffeur",
              "tracteur", "remorque", "type_transport", "produit"):
        df[c] = df[c].apply(_c)
    df["code_pays"] = df["code_pays"].str.upper()

    df["act"] = df["activite"].apply(normalize_activite)

    d = pd.to_datetime(df["date"], errors="coerce")
    if d.isna().mean() > 0.5:                      # repli format jj/mm/aaaa
        d = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    h = pd.to_timedelta(
        df["heure"].apply(lambda v: _c(v) if re.match(r"^\d{1,2}:\d{2}", _c(v)) else "00:00:00"),
        errors="coerce",
    ).fillna(pd.Timedelta(0))
    df["dt"] = d + h

    df["lieu_key"] = (df["code_pays"] + "|" + df["code_postal"].apply(normalize_cp_fr))
    return df.reset_index(drop=True)


CA_COLS = {
    "dossier":          ["N° Dossier", "N°Dossier", "Dossier"],
    "reference":        ["Référence", "Reference"],
    "date_charg":       ["Date chargement"],
    "type_transport":   ["Type de transport"],
    "client":           ["Client facturation", "Client"],
    "localite_charg":   ["Localité chargement", "Localite chargement"],
    "cp_charg":         ["C.P. chargement", "CP chargement"],
    "pays_charg":       ["Pays chargement"],
    "localite_decharg": ["Localité déchargement", "Localite dechargement"],
    "cp_decharg":       ["C.P. déchargement", "CP dechargement"],
    "pays_decharg":     ["Pays déchargement", "Pays dechargement"],
    "produit":          ["Produit"],
    "etat_vente":       ["Etat vente", "État vente"],
    "prix_transport":   ["Prix transport"],
    "supplements":      ["Suppléments", "Supplements"],
    "sg":               ["S.G.", "SG"],
    "heures_attente":   ["Heures d'attente"],
    "total_vente":      ["Total des ventes", "Total ventes"],
    "total_achat":      ["Total des achats", "Total achats"],
}


@st.cache_data(show_spinner=False)
def parse_ca(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    cm = _map_cols(df, CA_COLS)

    manquantes = [r for r in ("dossier", "total_vente") if cm.get(r) is None]
    if manquantes:
        st.error(f"Colonnes CA manquantes : {manquantes}\n\n{list(df.columns)}")
        st.stop()

    df = df.rename(columns={v: k for k, v in cm.items() if v})
    for c in CA_COLS:
        if c not in df.columns:
            df[c] = ""

    df["dossier"] = df["dossier"].astype(str).str.strip()
    df = df[df["dossier"].str.match(r"^\d+", na=False)].copy()

    for c in ("prix_transport", "supplements", "sg", "heures_attente",
              "total_vente", "total_achat"):
        df[c] = df[c].apply(to_float)
    for c in ("localite_charg", "cp_charg", "pays_charg", "localite_decharg",
              "cp_decharg", "pays_decharg", "client", "etat_vente",
              "type_transport", "produit"):
        df[c] = df[c].apply(_c)
    df["pays_charg"]   = df["pays_charg"].str.upper()
    df["pays_decharg"] = df["pays_decharg"].str.upper()

    agg = df.groupby("dossier", as_index=False).agg(
        prix_transport   = ("prix_transport", "sum"),
        supplements      = ("supplements",    "sum"),
        sg               = ("sg",             "sum"),
        heures_attente   = ("heures_attente", "sum"),
        total_vente      = ("total_vente",    "sum"),
        total_achat      = ("total_achat",    "sum"),
        client           = ("client",         "first"),
        etat_vente       = ("etat_vente",     "first"),
        type_transport   = ("type_transport", "first"),
        produit          = ("produit",        "first"),
        date_charg       = ("date_charg",     "first"),
        localite_charg   = ("localite_charg", "first"),
        cp_charg         = ("cp_charg",       "first"),
        pays_charg       = ("pays_charg",     "first"),
        localite_decharg = ("localite_decharg", "first"),
        cp_decharg       = ("cp_decharg",     "first"),
        pays_decharg     = ("pays_decharg",   "first"),
    )
    agg["prix_sg"]   = agg["prix_transport"] + agg["sg"]
    agg["prix_supp"] = agg["prix_transport"] + agg["supplements"]

    dt = pd.to_datetime(agg["date_charg"], errors="coerce")
    agg["date_dt"] = dt
    agg["mois"]    = dt.dt.strftime("%Y-%m").fillna("").astype(str)
    return agg


# ══════════════════════════════════════════════════════════════════
#  CONSTRUCTION DES DOSSIERS (missions + CA)
# ══════════════════════════════════════════════════════════════════

def _pt(row):
    return (row["localite"], row["code_postal"], row["code_pays"])


@st.cache_data(show_spinner="🧩 Analyse des dossiers...")
def build_dossiers(df_ca, df_stops):
    """Assemble un dossier par ligne : stops ordonnés, classification, départements."""
    infos = {}

    if df_stops is not None and not df_stops.empty:
        # Seuls les dossiers présents dans le CA nous intéressent ici
        sub = df_stops[df_stops["dossier"].isin(set(df_ca["dossier"]))]
        sub = sub.sort_values(["dossier", "dt"], kind="stable")

        for dos, grp in sub.groupby("dossier", sort=False):
            act   = grp["act"].tolist()
            loc   = grp["localite"].tolist()
            cp    = grp["code_postal"].tolist()
            pays  = grp["code_pays"].tolist()
            keys  = grp["lieu_key"].tolist()
            pts   = list(zip(loc, cp, pays))

            idx_ch = [i for i, a in enumerate(act) if a == "CHARGEMENT"]
            idx_de = [i for i, a in enumerate(act) if a == "DECHARGEMENT"]

            # Points de route : tout sauf AUTRE, doublons consécutifs supprimés
            route, prev = [], None
            for i, a in enumerate(act):
                if a == "AUTRE":
                    continue
                if keys[i] and keys[i] != prev:
                    route.append(pts[i])
                    prev = keys[i]

            depts_ok = [d for d in
                        (extract_departement(cp[i], pays[i]) for i in idx_de) if d]
            if depts_ok:
                cnt = Counter(depts_ok)
                top = max(cnt.values())
                ex  = {d for d, n in cnt.items() if n == top}
                principal = next(d for d in reversed(depts_ok) if d in ex)
            else:
                principal = None

            def _first(col):
                v = [x for x in grp[col].tolist() if x]
                return v[0] if v else ""

            infos[dos] = {
                "n_charg":     len(idx_ch),
                "n_decharg":   len(idx_de),
                "lieux_charg": len({keys[i] for i in idx_ch}),
                "lieux_dech":  len({keys[i] for i in idx_de}),
                "n_transit":   act.count("TRANSIT"),
                "n_technique": act.count("TECHNIQUE"),
                "route_pts":   route,
                "pts_charg":   [pts[i] for i in idx_ch],
                "pts_dech":    [pts[i] for i in idx_de],
                "depts":       depts_ok,
                "dept_principal": principal,
                "nb_depts":    len(set(depts_ok)),
                "tracteur":    _first("tracteur"),
                "remorque":    _first("remorque"),
                "chauffeur":   _first("chauffeur"),
                "dt_debut":    grp["dt"].min(),
                "dt_fin":      grp["dt"].max(),
                "villes_ch":   " + ".join(dict.fromkeys(
                    [loc[i] for i in idx_ch if loc[i]])),
                "villes_de":   " → ".join(dict.fromkeys(
                    [loc[i] for i in idx_de if loc[i]])),
            }

    rows = []
    for ca in df_ca.to_dict("records"):
        dos = ca["dossier"]
        i   = infos.get(dos)

        if i is None:
            # Repli : uniquement les données du fichier CA
            pt_ch = (ca["localite_charg"], ca["cp_charg"], ca["pays_charg"])
            pt_de = (ca["localite_decharg"], ca["cp_decharg"], ca["pays_decharg"])
            dep   = extract_departement(ca["cp_decharg"], ca["pays_decharg"])
            i = {
                "n_charg": 1, "n_decharg": 1, "lieux_charg": 1, "lieux_dech": 1,
                "n_transit": 0, "n_technique": 0,
                "route_pts": [pt_ch, pt_de], "pts_charg": [pt_ch], "pts_dech": [pt_de],
                "depts": [dep] if dep else [], "dept_principal": dep,
                "nb_depts": 1 if dep else 0,
                "tracteur": "", "remorque": "", "chauffeur": "",
                "dt_debut": ca.get("date_dt"), "dt_fin": ca.get("date_dt"),
                "villes_ch": ca["localite_charg"], "villes_de": ca["localite_decharg"],
                "_sans_missions": True,
            }

        groupage_ch = i["lieux_charg"] > 1
        groupage_de = i["lieux_dech"] > 1
        if groupage_ch and groupage_de:
            type_dos, sous = "Groupage", "Groupage complet"
        elif groupage_de:
            type_dos, sous = "Groupage", "Groupage livraison"
        elif groupage_ch:
            type_dos, sous = "Groupage", "Groupage chargement"
        else:
            type_dos, sous = "Lot sec", "Lot sec"

        # 2 stops au même lieu : double prise, pas un groupage
        double_prise = (i["n_charg"] + i["n_decharg"] > 2) and not (groupage_ch or groupage_de)

        r = dict(ca)
        r.update({
            "type_dossier":   type_dos,
            "sous_type":      sous,
            "n_charg":        i["n_charg"],
            "n_decharg":      i["n_decharg"],
            "lieux_charg":    i["lieux_charg"],
            "lieux_dech":     i["lieux_dech"],
            "n_transit":      i["n_transit"],
            "n_technique":    i["n_technique"],
            "double_prise":   double_prise,
            "route_pts":      i["route_pts"],
            "pts_charg":      i["pts_charg"],
            "pts_dech":       i["pts_dech"],
            "depts":          i["depts"],
            "dept_decharg":   i["dept_principal"],
            "nb_depts":       i["nb_depts"],
            "multi_dept":     i["nb_depts"] > 1,
            "tracteur":       i["tracteur"],
            "remorque":       i["remorque"],
            "chauffeur":      i["chauffeur"],
            "dt_debut":       i["dt_debut"],
            "dt_fin":         i["dt_fin"],
            "villes_ch":      i["villes_ch"] or ca["localite_charg"],
            "villes_de":      i["villes_de"] or ca["localite_decharg"],
            "sans_missions":  i.get("_sans_missions", False),
        })
        rows.append(r)

    out = pd.DataFrame(rows)
    out["dept_label"] = out["dept_decharg"].map(
        lambda c: dept_label(c) if c else "🌍 Hors France")
    return out


# ══════════════════════════════════════════════════════════════════
#  KM À VIDE — chaînage par tracteur sur TOUT le fichier missions
# ══════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner="🔗 Chaînage des tracteurs...")
def compute_bornes(df_stops, cle="tracteur"):
    """Premier chargement et dernier déchargement de CHAQUE dossier du fichier
    missions (11 000+), vectorisé. Sert de base au calcul des trajets à vide."""
    if df_stops is None or df_stops.empty:
        return pd.DataFrame()

    d = df_stops[df_stops["act"].isin(("CHARGEMENT", "DECHARGEMENT"))]
    d = d.sort_values(["dossier", "dt"], kind="stable")
    cols = ["dt", "localite", "code_postal", "code_pays", "lieu_key"]

    ch = d[d["act"] == "CHARGEMENT"].groupby("dossier", sort=False)[cols].first()
    de = d[d["act"] == "DECHARGEMENT"].groupby("dossier", sort=False)[cols].last()
    b  = ch.join(de, how="inner", lsuffix="_ch", rsuffix="_de")
    if b.empty:
        return pd.DataFrame()

    tr = (df_stops[df_stops[cle] != ""]
          .sort_values(["dossier", "dt"], kind="stable")
          .groupby("dossier", sort=False)[cle].first())
    b["cle"] = b.index.map(tr).fillna("")
    return b.reset_index()


def build_empty_legs(bornes, dossiers_cibles, max_jours=3):
    """Dernier déchargement d'un dossier → premier chargement du dossier suivant
    du même tracteur. Le rattachement se fait au dossier de départ."""
    if bornes is None or bornes.empty:
        return []

    b = bornes[bornes["cle"] != ""].sort_values(["cle", "dt_ch"], kind="stable")
    cibles, legs = set(dossiers_cibles), []

    for _, grp in b.groupby("cle", sort=False):
        recs = grp.to_dict("records")
        for a, nxt in zip(recs, recs[1:]):
            if a["dossier"] not in cibles:
                continue
            if pd.isna(a["dt_de"]) or pd.isna(nxt["dt_ch"]):
                continue
            gap = (nxt["dt_ch"] - a["dt_de"]).total_seconds() / 86400
            if gap < 0 or gap > max_jours:
                continue
            legs.append({
                "dossier":      a["dossier"],
                "dossier_next": nxt["dossier"],
                "cle":          a["cle"],
                "pt_from":      (a["localite_de"], a["code_postal_de"], a["code_pays_de"]),
                "pt_to":        (nxt["localite_ch"], nxt["code_postal_ch"], nxt["code_pays_ch"]),
                "meme_lieu":    a["lieu_key_de"] == nxt["lieu_key_ch"],
                "gap_jours":    round(gap, 2),
            })
    return legs


# ══════════════════════════════════════════════════════════════════
#  EXÉCUTION PTV
# ══════════════════════════════════════════════════════════════════

def run_ptv(df_dos, legs, status, bar):
    geo   = st.session_state.setdefault("_geo", {})
    routes = st.session_state.setdefault("_routes", {})

    pts = set()
    for r in df_dos["route_pts"]:
        pts.update(r)
    for l in legs:
        pts.add(l["pt_from"])
        pts.add(l["pt_to"])
    pts = {p for p in pts if p[0] or p[1]}
    todo = [p for p in pts if p not in geo]

    echecs = []
    if todo:
        status.text(f"Géocodage de {len(todo)} points (sur {len(pts)})...")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(geocode_point, *p): p for p in todo}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    geo[p] = fut.result()
                except Exception:
                    geo[p] = None
                if geo[p] is None:
                    echecs.append(p)
                done += 1
                bar.progress(min(done / len(todo) * 0.40, 0.40))
                if done % 10 == 0 or done == len(todo):
                    status.text(f"Géocodage {done}/{len(todo)} — {p[0]} {p[1]}")

    def key_of(points):
        cs = [geo.get(p) for p in points]
        cs = [c for c in cs if c]
        return tuple(cs) if len(cs) >= 2 else None

    # ── Routes chargées ──
    keys_ch = [key_of(r) for r in df_dos["route_pts"]]
    a_faire = [k for k in dict.fromkeys([k for k in keys_ch if k]) if k not in routes]
    if a_faire:
        status.text(f"Calcul de {len(a_faire)} itinéraires chargés...")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(calculate_route, list(k)): k for k in a_faire}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    routes[k] = fut.result()
                except Exception:
                    routes[k] = None
                done += 1
                bar.progress(0.40 + min(done / len(a_faire) * 0.35, 0.35))
                if done % 10 == 0 or done == len(a_faire):
                    status.text(f"Itinéraires chargés {done}/{len(a_faire)}")

    # ── Trajets à vide ──
    keys_vide = {}
    for l in legs:
        if l["meme_lieu"]:
            keys_vide[l["dossier"]] = "SAME"
            continue
        k = key_of([l["pt_from"], l["pt_to"]])
        if k:
            keys_vide[l["dossier"]] = k
    a_faire_v = [k for k in dict.fromkeys(
        [k for k in keys_vide.values() if k != "SAME"]) if k not in routes]
    if a_faire_v:
        status.text(f"Calcul de {len(a_faire_v)} trajets à vide...")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(calculate_route, list(k)): k for k in a_faire_v}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    routes[k] = fut.result()
                except Exception:
                    routes[k] = None
                done += 1
                bar.progress(0.75 + min(done / len(a_faire_v) * 0.25, 0.25))
                if done % 10 == 0 or done == len(a_faire_v):
                    status.text(f"Trajets à vide {done}/{len(a_faire_v)}")

    out = df_dos.copy()
    out["km"] = [
        (routes.get(k) or {}).get("km") if k else np.nan for k in keys_ch
    ]
    out["heures"] = [
        (routes.get(k) or {}).get("h") if k else np.nan for k in keys_ch
    ]

    def _vide(dos):
        k = keys_vide.get(dos)
        if k is None:
            return np.nan
        if k == "SAME":
            return 0.0
        r = routes.get(k)
        return r["km"] if r else np.nan

    out["km_vide"]    = out["dossier"].map(_vide)
    out["km_complet"] = (pd.to_numeric(out["km"], errors="coerce").fillna(0) +
                         pd.to_numeric(out["km_vide"], errors="coerce").fillna(0))
    out.loc[out["km"].isna(), "km_complet"] = np.nan

    legs_df = pd.DataFrame(legs)
    if not legs_df.empty:
        legs_df["km_vide"] = legs_df["dossier"].map(_vide)
        legs_df["ville_from"] = legs_df["pt_from"].map(lambda p: p[0])
        legs_df["ville_to"]   = legs_df["pt_to"].map(lambda p: p[0])

    return out, echecs, legs_df


# ══════════════════════════════════════════════════════════════════
#  AGRÉGATION PAR DÉPARTEMENT
# ══════════════════════════════════════════════════════════════════

def explode_depts(df, base_col, regle, km_col):
    """Une ligne par (dossier, département). Règle dominante ou prorata."""
    rows = []
    for _, r in df.iterrows():
        depts = [d for d in (r.get("depts") or []) if d]
        base  = float(r.get(base_col) or 0)
        km    = pd.to_numeric(pd.Series([r.get(km_col)]), errors="coerce").iloc[0]
        prix  = float(r.get("prix_transport") or 0)
        tv    = float(r.get("total_vente") or 0)

        if not depts:
            continue

        if regle == "prorata":
            cnt = Counter(depts)
            n   = len(depts)
            for d, k in cnt.items():
                w = k / n
                rows.append({
                    "dept": d, "dossier": r["dossier"], "client": r.get("client", ""),
                    "type_dossier": r["type_dossier"], "poids": w,
                    "base": base * w, "prix_transport": prix * w,
                    "total_vente": tv * w,
                    "km": km * w if pd.notna(km) else np.nan,
                })
        else:
            d = r.get("dept_decharg")
            if not d:
                continue
            rows.append({
                "dept": d, "dossier": r["dossier"], "client": r.get("client", ""),
                "type_dossier": r["type_dossier"], "poids": 1.0,
                "base": base, "prix_transport": prix, "total_vente": tv, "km": km,
            })
    return pd.DataFrame(rows)


def build_dept_stats(df_exp, par_type=False):
    if df_exp.empty:
        return pd.DataFrame()
    cles = ["dept", "type_dossier"] if par_type else ["dept"]
    g = df_exp.groupby(cles, as_index=False).agg(
        nb_dossiers    = ("dossier",        "nunique"),
        poids          = ("poids",          "sum"),
        km             = ("km",             "sum"),
        prix_transport = ("prix_transport", "sum"),
        total_vente    = ("total_vente",    "sum"),
        base           = ("base",           "sum"),
        nb_clients     = ("client",         "nunique"),
    )
    g["km"]       = g["km"].round(0)
    for c in ("prix_transport", "total_vente", "base"):
        g[c] = g[c].round(2)
    g["renta"]    = (g["base"] / g["km"].replace(0, np.nan)).round(2)
    g["ca_moyen"] = (g["base"] / g["poids"].replace(0, np.nan)).round(0)
    g["km_moyen"] = (g["km"] / g["poids"].replace(0, np.nan)).round(0)
    tot           = g["base"].sum()
    g["pct_ca"]   = (g["base"] / tot * 100).round(1) if tot else np.nan
    g["poids"]    = g["poids"].round(1)
    g["nom_dept"] = g["dept"].map(lambda c: DEPT_NOMS.get(c, "—"))
    return g.sort_values("base", ascending=False).reset_index(drop=True)


DEPT_RENAME = {
    "dept": "Dépt", "nom_dept": "Département", "type_dossier": "Type",
    "nb_dossiers": "Nb Dossiers",
    "poids": "Dossiers pondérés", "nb_clients": "Nb Clients",
    "km": "KM", "km_moyen": "KM moy/dossier",
    "prix_transport": "Prix Transport (€)", "total_vente": "Total Vente (€)",
    "base": "CA retenu (€)", "ca_moyen": "CA retenu moy/dossier (€)",
    "pct_ca": "% du CA retenu", "renta": "Renta €/km",
}

DEPT_ORDER = ["dept", "nom_dept", "type_dossier", "nb_dossiers", "poids",
              "nb_clients", "km", "km_moyen", "prix_transport", "total_vente",
              "base", "ca_moyen", "pct_ca", "renta"]


def format_dept(df_dept, base_col="total_vente", regle="dominant", avec_km=True):
    if df_dept.empty:
        return df_dept
    cols = list(DEPT_ORDER)
    if not avec_km:
        cols = [c for c in cols if c not in ("km", "km_moyen", "renta")]
    if base_col in ("total_vente", "prix_transport"):
        cols = [c for c in cols if c != "base"]
    if regle != "prorata":
        cols = [c for c in cols if c != "poids"]
    cols = [c for c in cols if c in df_dept.columns]
    return df_dept[cols].rename(columns=DEPT_RENAME)


# ══════════════════════════════════════════════════════════════════
#  EXPORT EXCEL
# ══════════════════════════════════════════════════════════════════

def _style(ws, n):
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")
    for i in range(2, n + 2):
        if i % 2 == 0:
            for cell in ws[i]:
                cell.fill = PatternFill("solid", fgColor="EEF2F7")
    for col in ws.columns:
        w = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 4, 55)


DETAIL_RENAME = {
    "dossier": "N° Dossier", "date_charg": "Date chargement", "client": "Client",
    "type_dossier": "Type", "sous_type": "Détail type",
    "n_charg": "Nb charg.", "n_decharg": "Nb déch.", "nb_depts": "Nb dépts",
    "villes_ch": "Chargement(s)", "villes_de": "Livraison(s)",
    "dept_label": "Département", "tracteur": "Tracteur", "remorque": "Remorque",
    "km": "KM Chargés", "km_vide": "KM À Vide", "km_complet": "KM Complet",
    "prix_transport": "Prix Transport (€)", "supplements": "Suppléments (€)",
    "sg": "S.G. (€)", "total_vente": "Total Vente (€)",
    "renta_base": "Renta €/km", "etat_vente": "État vente",
}


def export_excel(df_dept, df_detail, df_type, legs, base_col, regle):
    out = io.BytesIO()
    try:
        with pd.ExcelWriter(out, engine="openpyxl") as wr:
            if not df_dept.empty:
                d = format_dept(df_dept, base_col, regle).fillna("")
                d.to_excel(wr, sheet_name="Renta Départements", index=False)
                _style(wr.sheets["Renta Départements"], len(d))
            if df_type is not None and not df_type.empty:
                df_type.to_excel(wr, sheet_name="Lot sec vs Groupage", index=False)
                _style(wr.sheets["Lot sec vs Groupage"], len(df_type))
            cols = [c for c in DETAIL_RENAME if c in df_detail.columns]
            dd = df_detail[cols].rename(columns=DETAIL_RENAME).fillna("")
            dd.to_excel(wr, sheet_name="Détail dossiers", index=False)
            _style(wr.sheets["Détail dossiers"], len(dd))
            if legs is not None and not legs.empty:
                lv = legs[[c for c in ["dossier", "dossier_next", "cle", "ville_from",
                                       "ville_to", "gap_jours", "km_vide"]
                           if c in legs.columns]].rename(columns={
                    "dossier": "Dossier", "dossier_next": "Dossier suivant",
                    "cle": "Tracteur", "ville_from": "Départ", "ville_to": "Arrivée",
                    "gap_jours": "Écart (j)", "km_vide": "KM à vide",
                }).fillna("")
                lv.to_excel(wr, sheet_name="KM à vide", index=False)
                _style(wr.sheets["KM à vide"], len(lv))
    except Exception as e:
        st.error(f"Erreur Excel : {e}")
        return b""
    return out.getvalue()


# ══════════════════════════════════════════════════════════════════
#  INTERFACE
# ══════════════════════════════════════════════════════════════════

from core import ui

ui.page("renta_departements", "Lot sec ou groupage, km chargés en route chaînée et km à vide par chaînage tracteur.")

if not PTV_API_KEY or PTV_API_KEY == "METS_TA_CLE_ICI":
    st.error("Clé PTV_API_KEY non configurée.")

u1, u2 = st.columns(2)
with u1:
    f_ca = st.file_uploader("Fichier CA (.xlsx)", type=["xlsx"])
with u2:
    f_mi = st.file_uploader("Fichier Missions (.xlsx)", type=["xlsx"])

if not f_ca:
    st.info(
        "**Fichier CA** obligatoire (montants par dossier). "
        "**Fichier missions** fortement recommandé : sans lui, pas de détection "
        "des groupages, pas de route chaînée et pas de km à vide."
    )
    st.stop()

df_ca = parse_ca(f_ca.getvalue())
df_stops = parse_missions(f_mi.getvalue()) if f_mi else None

# ── Diagnostic activités ──
if df_stops is not None:
    with st.expander("Diagnostic — activités reconnues dans le fichier missions"):
        diag = (df_stops.groupby(["activite", "act"], dropna=False)
                .size().reset_index(name="Lignes")
                .rename(columns={"activite": "Libellé fichier", "act": "Classé comme"})
                .sort_values("Lignes", ascending=False))
        st.dataframe(diag, use_container_width=True, hide_index=True)
        n_autre = int((df_stops["act"] == "AUTRE").sum())
        if n_autre:
            st.warning(
                f"{n_autre} ligne(s) classée(s) en AUTRE : elles sont ignorées "
                "dans la classification et dans le calcul des km. Signale-moi les "
                "libellés concernés si l'un d'eux devrait compter."
            )
    manquants = int((~df_ca["dossier"].isin(df_stops["dossier"])).sum())
    if manquants:
        st.warning(
            f"{manquants} dossier(s) du fichier CA absent(s) du fichier missions. "
            "Ils sont traités en lot sec avec les seules adresses du CA."
        )
else:
    st.warning(
        "Sans fichier missions : tous les dossiers seront classés en lot sec, "
        "les km seront calculés en A→B direct et les km à vide indisponibles."
    )

df_dos = build_dossiers(df_ca, df_stops)

# ── KPI global ──
dv = df_ca["date_dt"].dropna()
MOIS_FR = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
if not dv.empty:
    a, b = dv.min(), dv.max()
    periode = (f"{MOIS_FR[a.month]} {a.year}" if (a.month, a.year) == (b.month, b.year)
               else f"{a:%d/%m/%Y} → {b:%d/%m/%Y}")
else:
    periode = "Période inconnue"

st.markdown(f"### 📊 Aperçu — {periode}")
n_grp = int((df_dos["type_dossier"] == "Groupage").sum())
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Dossiers", len(df_dos))
k2.metric("Lot sec", int((df_dos["type_dossier"] == "Lot sec").sum()))
k3.metric("Groupage", n_grp, f"{n_grp / len(df_dos) * 100:.0f} %", delta_color="off")
k4.metric("Déch. France", int(df_dos["dept_decharg"].notna().sum()))
k5.metric("Départements", int(df_dos["dept_decharg"].nunique()))
k6.metric("Total Ventes", f"{df_dos['total_vente'].sum():,.0f} €")

n_multi = int(df_dos["multi_dept"].sum())
if n_multi:
    st.caption(
        f"{n_multi} dossier(s) livrent dans plusieurs départements "
        f"({n_multi / len(df_dos) * 100:.1f} %) — la règle d'attribution ci-dessous les concerne."
    )

st.divider()

# ══════════════════════════════════════════════════════════════════
#  FILTRES & RÈGLES
# ══════════════════════════════════════════════════════════════════

st.markdown("### 🎛️ Filtres")

c1, c2, c3, c4 = st.columns(4)
with c1:
    pays_dispo = sorted({p for p in df_ca["pays_decharg"] if p})
    f_pays = st.multiselect("Pays de déchargement (CA)", pays_dispo,
                            default=["F"] if "F" in pays_dispo else [],
                            format_func=lambda p: PAYS_LABELS.get(p, p),
                            placeholder="Tous les pays")
with c2:
    f_type = st.multiselect("Type de dossier", ["Lot sec", "Groupage"],
                            default=[], placeholder="Lot sec + Groupage")
with c3:
    sous_dispo = sorted(df_dos["sous_type"].unique())
    f_sous = st.multiselect("Détail groupage", sous_dispo, default=[],
                            placeholder="Tous")
with c4:
    etats = sorted({e for e in df_ca["etat_vente"] if e})
    f_etat = st.multiselect("État vente", etats, default=[], placeholder="Tous")

c5, c6, c7 = st.columns(3)
with c5:
    clients = sorted({c for c in df_ca["client"] if c})
    f_client = st.multiselect("Client", clients, default=[], placeholder="Tous")
with c6:
    mois_dispo = sorted({str(m) for m in df_dos["mois"].dropna().unique()
                         if str(m) not in ("", "NaT", "nan", "None")})
    f_mois = st.multiselect("Mois de chargement", mois_dispo, default=[],
                            placeholder="Tous les mois")
with c7:
    regle_lbl = st.selectbox(
        "Attribution des groupages multi-départements",
        ["Département dominant", "Prorata entre départements"],
        help="Dominant : le département où le dossier livre le plus (à égalité, le dernier livré). "
             "Prorata : CA et km répartis proportionnellement au nombre de livraisons.",
    )
    regle = "prorata" if regle_lbl.startswith("Prorata") else "dominant"

g1, g2 = st.columns([2, 3])
with g1:
    max_jours = st.slider("Écart max pour un trajet à vide (jours)", 1, 10, 3,
                          help="Au-delà, le tracteur a fait autre chose entre-temps : "
                               "le trajet n'est pas rattaché au dossier.")
with g2:
    base_choix = st.radio("Base de calcul", list(BASES_CA.keys()),
                          index=0, horizontal=True)
    base_col   = BASES_CA[base_choix]
    base_label = base_choix.split(" ", 1)[1]

st.caption(f"**{base_label}** — {BASES_AIDE[base_col]}")

dff = df_dos.copy()
if f_pays:
    dff = dff[dff["pays_decharg"].isin(f_pays)]
if f_type:
    dff = dff[dff["type_dossier"].isin(f_type)]
if f_sous:
    dff = dff[dff["sous_type"].isin(f_sous)]
if f_etat:
    dff = dff[dff["etat_vente"].isin(f_etat)]
if f_client:
    dff = dff[dff["client"].isin(f_client)]
if f_mois:
    dff = dff[dff["mois"].isin(f_mois)]

st.info(
    f"**{len(dff)} dossiers** · **{dff[base_col].sum():,.0f} €** ({base_label}) · "
    f"{int((dff['type_dossier'] == 'Groupage').sum())} groupage(s) · "
    f"**{int(dff['dept_decharg'].nunique())} départements**."
)

if dff.empty:
    st.stop()

st.divider()

# ══════════════════════════════════════════════════════════════════
#  PTV
# ══════════════════════════════════════════════════════════════════

st.markdown("### 🗺️ Calcul PTV")

bornes = compute_bornes(df_stops, "tracteur") if df_stops is not None else pd.DataFrame()
legs = build_empty_legs(bornes, set(dff["dossier"]), max_jours)
nb_pts = len({p for r in dff["route_pts"] for p in r if p[0] or p[1]})
st.caption(
    f"≈ {nb_pts} points à géocoder · {len(dff)} itinéraires chargés · "
    f"{len(legs)} trajets à vide détectés. Le cache évite tout recalcul."
)

b1, b2 = st.columns([1, 3])
with b1:
    go = st.button("Lancer le calcul PTV", type="primary")
with b2:
    if st.button("Vider le cache PTV"):
        for k in ("_geo", "_routes", "_res"):
            st.session_state.pop(k, None)
        st.success("Cache vidé.")

if go:
    bar, status = st.progress(0.0), st.empty()
    t0 = time.time()
    res, echecs, legs_df = run_ptv(dff, legs, status, bar)
    bar.progress(1.0)
    status.success(
        f"Terminé en {time.time() - t0:.0f}s — "
        f"{res['km'].notna().sum()}/{len(res)} dossiers avec km chargés, "
        f"{res['km_vide'].notna().sum()} avec km à vide."
    )
    st.session_state["_res"]  = res
    st.session_state["_legs"] = legs_df
    if echecs:
        with st.expander(f"{len(echecs)} points non géocodés"):
            st.dataframe(pd.DataFrame(echecs, columns=["Localité", "CP", "Pays"]),
                         use_container_width=True, hide_index=True)

res = st.session_state.get("_res")
if res is None:
    st.warning("Lance le calcul PTV pour obtenir les km et la rentabilité. "
               "En attendant, voici la répartition du CA par département :")
    exp0 = explode_depts(dff, base_col, regle, "km_complet")
    dep0 = build_dept_stats(exp0)
    if not dep0.empty:
        st.dataframe(format_dept(dep0, base_col, regle, avec_km=False),
                     use_container_width=True, height=460, hide_index=True)
    st.stop()

res  = res[res["dossier"].isin(dff["dossier"])].copy()
legs_df = st.session_state.get("_legs", pd.DataFrame())

# ══════════════════════════════════════════════════════════════════
#  RÉSULTATS
# ══════════════════════════════════════════════════════════════════

km_col_lbl = st.radio("Base kilométrique", ["KM complet (chargé + vide)", "KM chargés seuls"],
                      horizontal=True, index=0)
km_col = "km_complet" if km_col_lbl.startswith("KM complet") else "km"

res["renta_base"] = (
    pd.to_numeric(res[base_col], errors="coerce") /
    pd.to_numeric(res[km_col], errors="coerce").replace(0, np.nan)
).round(2)

km_ch   = pd.to_numeric(res["km"], errors="coerce").fillna(0).sum()
km_vd   = pd.to_numeric(res["km_vide"], errors="coerce").fillna(0).sum()
km_ref  = pd.to_numeric(res[km_col], errors="coerce").fillna(0).sum()
base_t  = res[base_col].sum()

st.markdown(f"### 📈 Résultats — {base_label}, {km_col_lbl.lower()}")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("KM Chargés", f"{km_ch:,.0f}")
m2.metric("KM À Vide", f"{km_vd:,.0f}",
          f"{km_vd / (km_ch + km_vd) * 100:.1f} %" if (km_ch + km_vd) else None,
          delta_color="off")
m3.metric("KM Complet", f"{km_ch + km_vd:,.0f}")
m4.metric("CA retenu", f"{base_t:,.0f} €")
m5.metric("Renta", f"{base_t / km_ref:.2f} €/km" if km_ref else "—")
m6.metric("Sans km", int(res["km"].isna().sum()))

tabs = st.tabs(["Par département", "Lot sec vs Groupage",
                "Détail dossiers", "KM à vide", "Par client"])

# ── Par département ──
with tabs[0]:
    exp = explode_depts(res, base_col, regle, km_col)

    s1, s2 = st.columns([1, 3])
    with s1:
        par_type = st.checkbox(
            "Séparer lot sec / groupage", value=False,
            help="Une ligne par département ET par type, au lieu d'une moyenne "
                 "qui mélange les deux.",
        )
    with s2:
        if par_type:
            st.caption(
                "Chaque département apparaît une fois par type présent. "
                "Un département sans groupage n'aura qu'une ligne."
            )

    dep = build_dept_stats(exp, par_type=par_type)

    if dep.empty:
        st.info("Aucun déchargement en France dans la sélection.")
    else:
        d1, d2, d3 = st.columns([1, 1, 2])
        with d1:
            min_dos = st.number_input("Nb dossiers min", 1, 50, 1, 1)
        with d2:
            tri = st.selectbox("Trier par", ["Renta €/km", "CA retenu (€)",
                                             "Nb Dossiers", "KM", "Dépt"], index=0)
        with d3:
            asc = st.radio("Ordre", ["Décroissant", "Croissant"],
                           horizontal=True, index=0) == "Croissant"

        depv = dep[dep["nb_dossiers"] >= min_dos].copy()
        if depv.empty:
            st.warning("Aucun département au-dessus du seuil.")
        else:
            col_tri = {v: k for k, v in DEPT_RENAME.items()}.get(tri, "renta")
            depv = depv.sort_values(col_tri, ascending=asc,
                                    na_position="last").reset_index(drop=True)
            val = depv[depv["renta"].notna()]
            if not val.empty:
                b_ = val.sort_values("renta", ascending=False).iloc[0]
                w_ = val.sort_values("renta", ascending=True).iloc[0]
                _sfx = (lambda r: f" ({r['type_dossier']})") if par_type else (lambda r: "")
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Meilleur", f"{b_['renta']:.2f} €/km",
                          f"{b_['dept']} — {b_['nom_dept']}{_sfx(b_)}")
                q2.metric("Moins bon", f"{w_['renta']:.2f} €/km",
                          f"{w_['dept']} — {w_['nom_dept']}{_sfx(w_)}")
                q3.metric("Départements", depv["dept"].nunique())
                q4.metric("Dossiers", int(depv["nb_dossiers"].sum()))

            st.dataframe(
                format_dept(depv, base_col, regle), use_container_width=True,
                height=520, hide_index=True,
                column_config={
                    "Renta €/km":                st.column_config.NumberColumn(format="%.2f €"),
                    "CA retenu (€)":             st.column_config.NumberColumn(format="%.0f €"),
                    "Total Vente (€)":           st.column_config.NumberColumn(format="%.0f €"),
                    "Prix Transport (€)":        st.column_config.NumberColumn(format="%.0f €"),
                    "CA retenu moy/dossier (€)": st.column_config.NumberColumn(format="%.0f €"),
                    "% du CA retenu":            st.column_config.NumberColumn(format="%.1f %%"),
                },
            )

            ch = depv[depv["renta"].notna()].copy()
            if not ch.empty:
                ch["Dépt"] = ch["dept"] + " " + ch["nom_dept"]
                if par_type:
                    ch["Dépt"] = ch["Dépt"] + " · " + ch["type_dossier"]
                st.bar_chart(ch.set_index("Dépt")["renta"], height=320)

            st.download_button(
                "CSV départements",
                format_dept(depv, base_col, regle)
                .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                "Renta_departements.csv", "text/csv")

            st.markdown("##### 🔍 Détail d'un département")
            dsel = st.selectbox("Département", sorted(depv["dept"].unique()),
                                format_func=dept_label)
            det = res[res["depts"].map(lambda L: dsel in (L or []))]
            st.dataframe(
                det[[c for c in ["dossier", "date_charg", "client", "type_dossier",
                                 "villes_ch", "villes_de", "nb_depts", "km", "km_vide",
                                 "prix_transport", "total_vente", "renta_base"]
                     if c in det.columns]].rename(columns=DETAIL_RENAME),
                use_container_width=True, height=320, hide_index=True)

# ── Lot sec vs Groupage ──
with tabs[1]:
    r2 = res.copy()
    r2["_base"] = pd.to_numeric(r2[base_col], errors="coerce").fillna(0)
    r2["_km"]   = pd.to_numeric(r2[km_col], errors="coerce")

    comp = r2.groupby("sous_type", as_index=False).agg(
        Dossiers      = ("dossier",   "count"),
        Stops_moyens  = ("n_decharg", "mean"),
        KM            = ("_km",       "sum"),
        KM_moyen      = ("_km",       "mean"),
        CA            = ("_base",     "sum"),
        CA_moyen      = ("_base",     "mean"),
    )
    comp["Renta €/km"] = (comp["CA"] / comp["KM"].replace(0, np.nan)).round(2)
    comp["% du CA"]    = (comp["CA"] / comp["CA"].sum() * 100).round(1)
    comp = comp.round({"Stops_moyens": 1, "KM": 0, "KM_moyen": 0,
                       "CA": 0, "CA_moyen": 0})
    comp = comp.rename(columns={"sous_type": "Type", "Stops_moyens": "Déch. moyens",
                                "KM_moyen": "KM moyen", "CA_moyen": "CA moyen"})
    st.dataframe(comp.sort_values("CA", ascending=False),
                 use_container_width=True, hide_index=True)

    glob = r2.groupby("type_dossier", as_index=False).agg(
        n=("dossier", "count"), km=("_km", "sum"), ca=("_base", "sum"))
    glob["renta"] = (glob["ca"] / glob["km"].replace(0, np.nan)).round(2)
    if len(glob) == 2:
        ls = glob[glob["type_dossier"] == "Lot sec"].iloc[0]
        gr = glob[glob["type_dossier"] == "Groupage"].iloc[0]
        e1, e2, e3 = st.columns(3)
        e1.metric("Lot sec", f"{ls['renta']:.2f} €/km", f"{int(ls['n'])} dossiers",
                  delta_color="off")
        e2.metric("Groupage", f"{gr['renta']:.2f} €/km", f"{int(gr['n'])} dossiers",
                  delta_color="off")
        ecart = (gr["renta"] - ls["renta"]) if pd.notna(gr["renta"]) and pd.notna(ls["renta"]) else np.nan
        e3.metric("Écart groupage − lot sec",
                  f"{ecart:+.2f} €/km" if pd.notna(ecart) else "—")
        st.caption(
            "Un groupage mutualise plusieurs livraisons sur une même tournée : "
            "son €/km est structurellement plus élevé. Comparer les deux dans une "
            "moyenne unique masque cet effet — d'où la séparation."
        )

    st.markdown("##### Par département et par type")
    pivot = res.copy()
    pivot["_base"] = pd.to_numeric(pivot[base_col], errors="coerce").fillna(0)
    pivot["_km"]   = pd.to_numeric(pivot[km_col], errors="coerce")
    pv = pivot[pivot["dept_decharg"].notna()].groupby(
        ["dept_decharg", "type_dossier"], as_index=False).agg(
        n=("dossier", "count"), km=("_km", "sum"), ca=("_base", "sum"))
    pv["renta"] = (pv["ca"] / pv["km"].replace(0, np.nan)).round(2)
    tab_pv = pv.pivot(index="dept_decharg", columns="type_dossier",
                      values="renta").fillna(np.nan)
    tab_n = pv.pivot(index="dept_decharg", columns="type_dossier",
                     values="n").fillna(0).astype(int)
    tab_pv.columns = [f"Renta {c}" for c in tab_pv.columns]
    tab_n.columns  = [f"Nb {c}" for c in tab_n.columns]
    fusion = tab_pv.join(tab_n).reset_index().rename(columns={"dept_decharg": "Dépt"})
    fusion["Département"] = fusion["Dépt"].map(lambda c: DEPT_NOMS.get(c, "—"))
    st.dataframe(fusion, use_container_width=True, height=420, hide_index=True)

# ── Détail dossiers ──
with tabs[2]:
    cols = [c for c in DETAIL_RENAME if c in res.columns]
    st.dataframe(res[cols].rename(columns=DETAIL_RENAME),
                 use_container_width=True, height=520, hide_index=True)
    st.caption(f"Renta calculée sur {base_label} / {km_col_lbl.lower()}.")

# ── KM à vide ──
with tabs[3]:
    if legs_df is None or legs_df.empty:
        st.info(
            "Aucun trajet à vide détecté. Vérifie que le fichier missions est chargé "
            "et que l'écart maximum n'est pas trop restrictif."
        )
    else:
        lv = legs_df.copy()
        lv["km_vide"] = pd.to_numeric(lv["km_vide"], errors="coerce")
        v1, v2, v3, v4 = st.columns(4)
        v1.metric("Trajets à vide", len(lv))
        v2.metric("KM à vide", f"{lv['km_vide'].sum():,.0f}")
        v3.metric("Moyenne", f"{lv['km_vide'].mean():,.0f} km")
        v4.metric("Repartis du même lieu", int(lv["meme_lieu"].sum()))
        st.dataframe(
            lv[["dossier", "dossier_next", "cle", "ville_from", "ville_to",
                "gap_jours", "km_vide"]].rename(columns={
                "dossier": "Dossier", "dossier_next": "Dossier suivant",
                "cle": "Tracteur", "ville_from": "Départ", "ville_to": "Arrivée",
                "gap_jours": "Écart (j)", "km_vide": "KM à vide"}),
            use_container_width=True, height=460, hide_index=True)
        st.caption(
            "Le trajet à vide relie le dernier déchargement d'un dossier au premier "
            "chargement du dossier suivant du même tracteur, sur l'ensemble du fichier "
            "missions — y compris des dossiers absents du fichier CA. Il est rattaché "
            "au dossier de départ."
        )

# ── Par client ──
with tabs[4]:
    r3 = res.copy()
    r3["_base"] = pd.to_numeric(r3[base_col], errors="coerce").fillna(0)
    r3["_km"]   = pd.to_numeric(r3[km_col], errors="coerce")
    cl = r3.groupby("client", as_index=False).agg(
        Dossiers=("dossier", "count"),
        Groupages=("type_dossier", lambda s: int((s == "Groupage").sum())),
        KM=("_km", "sum"), CA=("_base", "sum"),
        Depts=("dept_decharg", "nunique"))
    cl["Renta €/km"] = (cl["CA"] / cl["KM"].replace(0, np.nan)).round(2)
    cl["CA moyen"]   = (cl["CA"] / cl["Dossiers"]).round(0)
    cl = cl.round({"KM": 0, "CA": 0}).sort_values("CA", ascending=False)
    st.dataframe(cl.rename(columns={"client": "Client", "Depts": "Nb dépts livrés"}),
                 use_container_width=True, height=480, hide_index=True)

st.divider()

exp_f = explode_depts(res, base_col, regle, km_col)
dep_f = build_dept_stats(exp_f, par_type=locals().get("par_type", False))
comp_f = None
try:
    comp_f = comp
except NameError:
    pass

st.download_button(
    "Rapport Excel complet",
    export_excel(dep_f, res, comp_f, legs_df, base_col, regle),
    "Renta_Departements.xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary")

st.caption(
    f"Base {base_label} · {km_col_lbl.lower()} · attribution « {regle_lbl.lower()} » · "
    f"écart max {max_jours} j pour les trajets à vide. "
    "Km calculés par PTV, profil EUR_TRAILER_TRUCK 44 t."
)
