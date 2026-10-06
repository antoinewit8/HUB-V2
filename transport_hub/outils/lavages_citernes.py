"""
Page Streamlit : Optimisateur Lavages Citernes
- Préparation dans le HUB : historique des lavages + annuaire des stations → base unifiée géocodée
- La carte s'ouvre dans un nouvel onglet, en plein écran façon Google Maps :
  panneau à gauche (style Apple), synthèse en haut à droite, détail en bas sur demande
- La carte est aussi téléchargeable en fichier HTML autonome (partage, usage hors HUB)

Plus besoin de folium ni de streamlit-folium pour cette page.
"""

import io
import re
import json
import math
import html
import difflib
import unicodedata
import urllib.request as ureq
import urllib.parse as uparse
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import ui

ui.page_config(ui.TOOLS_BY_KEY["lavages"]["title"])

UA = {"User-Agent": "CB-Transport-Hub/1.0"}

# Statuts de la base unifiée
S_HIST_ANN = "Utilisée · dans l'annuaire"
S_HIST = "Utilisée · hors annuaire"
S_HIST_SEUL = "Utilisée"
S_ANN = "Annuaire · jamais utilisée"

# ─── Utilitaires ─────────────────────────────────────────────────────────────
def normalize(text) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    text = str(text).upper().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"['\-–.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


FORMES_JUR = (r"\b(SA|SAS|SASU|SARL|EURL|SNC|SPRL|SRL|SC|NV|BV|BVBA|VOF|GMBH|AG|KG|CO|"
              r"LTD|SPA|SL|ETS|ETABLISSEMENTS|STE|SOCIETE)\b")


def normalize_nom(text) -> str:
    """Nom comparable : sans accents, ponctuation ni forme juridique."""
    s = re.sub(r"[^A-Z0-9 ]", " ", normalize(text))
    s = re.sub(FORMES_JUR, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cp_norm(cp) -> str:
    """'F-57190' / '57190.0' / 'L-1234' → '57190' / '1234'."""
    if cp is None or (isinstance(cp, float) and np.isnan(cp)):
        return ""
    s = re.sub(r"\.0+$", "", str(cp).strip())
    s = re.sub(r"[^A-Z0-9]", "", normalize(s))
    return re.sub(r"^(F|L|D|B|NL|CH|I|E|A|LU|BE|FR|DE)(?=\d)", "", s)


def similarite(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def parse_prix(val):
    """'1.234,50 €' / '85,00' / '85.5' → float, sinon NaN."""
    if val is None:
        return np.nan
    s = str(val).strip().replace("€", "").replace("EUR", "").replace("\xa0", "").replace(" ", "")
    if not s or s.lower() == "nan":
        return np.nan
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_coord(val, borne):
    try:
        v = float(str(val).strip().replace(",", "."))
    except (TypeError, ValueError):
        return np.nan
    return v if -borne <= v <= borne and v != 0 else np.nan


def haversine(lat1, lon1, lat2, lon2):
    """Distance vol d'oiseau en km (vectorisé)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def gmaps_link(lat, lon):
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def esc(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return html.escape(str(v))


def _get_json(url, timeout=10):
    req = ureq.Request(url, headers=UA)
    with ureq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post_json(url, body: bytes, headers: dict, timeout=30):
    req = ureq.Request(url, data=body, headers={**UA, **headers}, method="POST")
    with ureq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ─── Géocodage ───────────────────────────────────────────────────────────────
def _photon(query: str, limit: int = 1):
    url = f"https://photon.komoot.io/api/?q={uparse.quote(query)}&limit={limit}&lang=fr"
    try:
        return _get_json(url, timeout=8).get("features", [])
    except Exception:
        return []


def _nominatim(query: str, limit: int = 1):
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={uparse.quote(query)}&format=json&limit={limit}&addressdetails=1"
    )
    try:
        return _get_json(url, timeout=8)
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def search_address(query: str):
    """Renvoie jusqu'à 5 propositions {label, lat, lon} pour une adresse tapée."""
    out = []
    for f in _photon(query, limit=5):
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"]
        rue = " ".join(x for x in [p.get("street"), p.get("housenumber")] if x)
        ville = " ".join(x for x in [p.get("postcode"), p.get("city")] if x)
        parts = [p.get("name"), rue, ville, p.get("country")]
        label = ", ".join(dict.fromkeys(x for x in parts if x)) or query
        out.append({"label": label, "lat": float(lat), "lon": float(lon)})
    if not out:
        for d in _nominatim(query, limit=5):
            out.append({"label": d.get("display_name", query), "lat": float(d["lat"]), "lon": float(d["lon"])})
    return out


@st.cache_data(ttl=30 * 86400, show_spinner=False)
def geocode_station(nom: str, localite: str, cp: str, pays: str = "", adresse: str = ""):
    """
    Géocode une station, du plus précis au moins précis :
    adresse complète (annuaire) → nom de la station → centre de la commune.
    Un résultat n'est accepté que si le CP ou la localité retournés concordent
    (évite les homonymes ailleurs en Europe).
    Retour : (lat, lon, précision) ou None.
    """
    cp_n, loc_n = cp_norm(cp), normalize(localite)

    def concorde(postcode, city):
        return bool((cp_n and cp_norm(postcode) == cp_n) or (loc_n and normalize(city) == loc_n))

    lieu = f"{cp} {localite} {pays}".strip()

    if adresse and lieu:
        q = f"{adresse}, {lieu}"
        for f in _photon(q, limit=3):
            p = f.get("properties", {})
            if concorde(p.get("postcode"), p.get("city")):
                lon, lat = f["geometry"]["coordinates"]
                return float(lat), float(lon), "adresse"
        for d in _nominatim(q, limit=3):
            a = d.get("address", {})
            ville = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
            if concorde(a.get("postcode"), ville):
                return float(d["lat"]), float(d["lon"]), "adresse"

    for f in _photon(f"{nom}, {lieu}".strip(" ,"), limit=3):
        p = f.get("properties", {})
        if concorde(p.get("postcode"), p.get("city")):
            lon, lat = f["geometry"]["coordinates"]
            return float(lat), float(lon), "station"

    if not lieu:
        return None
    feats = _photon(lieu, limit=1)
    if feats:
        lon, lat = feats[0]["geometry"]["coordinates"]
        return float(lat), float(lon), "localité"
    res = _nominatim(lieu, limit=1)
    if res:
        return float(res[0]["lat"]), float(res[0]["lon"]), "localité"
    return None


PRECISION_LBL = {
    "annuaire": "Coordonnées de l'annuaire",
    "adresse": "Adresse exacte",
    "station": "Nom de la station",
    "localité": "⚠️ Centre de la commune",
    "échec": "❌ Non géocodée",
}



# ─── Frontières (Natural Earth) ──────────────────────────────────────────────
BORDER_URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_boundary_lines_land.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_boundary_lines_land.geojson",
]
EUROPE_BBOX = (-11.0, 35.0, 32.0, 62.0)  # ouest, sud, est, nord


def _decimer(ligne, pas=0.003):
    """Allège un tracé (~250 m entre points) pour garder une carte rapide."""
    if len(ligne) < 3:
        return [[round(p[0], 4), round(p[1], 4)] for p in ligne]
    out = [ligne[0]]
    for p in ligne[1:-1]:
        if abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= pas:
            out.append(p)
    out.append(ligne[-1])
    return [[round(p[0], 4), round(p[1], 4)] for p in out]


@st.cache_data(ttl=30 * 86400, show_spinner="Chargement des frontières…")
def load_borders():
    """Frontières terrestres Natural Earth, limitées à l'Europe. Lève une erreur si indisponible
    (pour ne pas mettre un échec en cache)."""
    w, s, e, n = EUROPE_BBOX
    for url in BORDER_URLS:
        try:
            data = _get_json(url, timeout=40)
        except Exception:
            continue
        lignes = []
        for f in data.get("features", []):
            g = f.get("geometry") or {}
            if g.get("type") == "LineString":
                parts = [g["coordinates"]]
            elif g.get("type") == "MultiLineString":
                parts = g["coordinates"]
            else:
                continue
            for l in parts:
                if any(w <= p[0] <= e and s <= p[1] <= n for p in l):
                    lignes.append(_decimer(l))
        if lignes:
            return {"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "MultiLineString", "coordinates": lignes},
            }]}
    raise RuntimeError("frontières indisponibles")


# ─── Chargement ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_excel(b: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(b), dtype=str)
    df.columns = df.columns.astype(str).str.strip()
    return df


def dossier_norm(v) -> str:
    """'D-012345 ' / '12345.0' / '012345' → '12345' (pour lier CA et lavages)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = re.sub(r"\.0+$", "", str(v).strip())
    s = re.sub(r"\s+", "", s).upper()
    s = s.lstrip("0")
    return "" if s in ("", "NAN", "NONE") else s


CHAMPS_CA = {
    "dossier": ("N° de dossier *", ["N° DOSSIER", "N DOSSIER", "NO DOSSIER", "NUMERO DOSSIER", "N DE DOSSIER",
                                    "DOSSIER", "REF DOSSIER"]),
    "supplements": ("Suppléments (prix du lavage) *", ["SUPPLEMENTS", "SUPPLEMENT", "SUPPL", "SUPPLEMENTS HT"]),
    "produit": ("Produit transporté", ["PRODUIT", "MARCHANDISE", "PRODUCT", "NATURE MARCHANDISE"]),
}
CA_REGLES = ["Additionner les lignes", "Garder la plus élevée"]


@st.cache_data(show_spinner=False)
def build_lavages(df_l: pd.DataFrame, df_ca: pd.DataFrame | None, map_ca: tuple | None = None):
    """
    Lavages + fichier CA liés par N° de dossier.
    Prix retenu : suppléments du CA (réparti si plusieurs lavages sur le même dossier),
    à défaut la colonne Prix du fichier lavages. La source est tracée dans _prix_src.
    """
    df = df_l.copy()
    for c in ["Nom 1", "Localité", "Code postal", "N° Dossier"]:
        if c in df.columns:
            df[c] = df[c].fillna("").str.strip()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True) if "Date" in df.columns else pd.NaT
    df["_prix_lav"] = df["Prix"].apply(parse_prix) if "Prix" in df.columns else np.nan
    df["_pays"] = df["Pays"].fillna("").str.strip() if "Pays" in df.columns else ""
    df["_cle"] = df["Nom 1"].map(normalize) + "|" + df["Code postal"]
    # Station de lavage = « Nom 2 » renseigné ; laiterie / usine = « Nom 2 » vide
    df["_nom2"] = df["Nom 2"].fillna("").astype(str).str.strip() if "Nom 2" in df.columns else "?"
    df["_dos"] = df["N° Dossier"].map(dossier_norm) if "N° Dossier" in df.columns else ""
    df["_prix"] = df["_prix_lav"]
    df["_prix_src"] = np.where(df["_prix_lav"].notna(), "Fichier lavages", "")
    df["_sup_ca"] = np.nan
    df["_lignes_ca"] = 0
    df["_nb_lav_dossier"] = 1

    if df_ca is None or not map_ca:
        return df
    mp = dict(map_ca)
    if not mp.get("dossier"):
        return df

    ca = pd.DataFrame({"_dos": df_ca[mp["dossier"]].map(dossier_norm)})
    if mp.get("produit"):
        ca["_prod"] = df_ca[mp["produit"]].fillna("").astype(str).str.strip()
    if mp.get("supplements"):
        ca["_sup"] = df_ca[mp["supplements"]].map(parse_prix)
    ca = ca[ca["_dos"] != ""]

    if mp.get("produit"):
        prod = ca[ca["_prod"] != ""].drop_duplicates("_dos").set_index("_dos")["_prod"]
        df["Produit"] = df["_dos"].map(prod)

    if mp.get("supplements"):
        sup = ca[ca["_sup"] > 0]
        regle = mp.get("regle") or CA_REGLES[0]
        agg = sup.groupby("_dos")["_sup"].sum() if regle == CA_REGLES[0] else sup.groupby("_dos")["_sup"].max()
        lignes = sup.groupby("_dos").size()
        a_dos = df["_dos"] != ""
        nb_lav = df[a_dos].groupby("_dos")["_dos"].transform("size")
        df.loc[a_dos, "_nb_lav_dossier"] = nb_lav
        df["_sup_ca"] = df["_dos"].map(agg)
        df["_lignes_ca"] = df["_dos"].map(lignes).fillna(0).astype(int)
        ok = df["_sup_ca"].notna() & a_dos
        df.loc[ok, "_prix"] = df.loc[ok, "_sup_ca"] / df.loc[ok, "_nb_lav_dossier"]
        df.loc[ok, "_prix_src"] = np.where(
            df.loc[ok, "_nb_lav_dossier"] > 1,
            "CA (réparti sur " + df.loc[ok, "_nb_lav_dossier"].astype(int).astype(str) + " lavages)", "CA")
    return df


@st.cache_data(show_spinner=False)
def build_stations(df: pd.DataFrame) -> pd.DataFrame:
    g = df.sort_values("Date").groupby("_cle", dropna=False)
    st_df = g.agg(
        nom=("Nom 1", "first"),
        localite=("Localité", "first"),
        cp=("Code postal", "first"),
        pays=("_pays", "first"),
        nb=("_cle", "size"),
        prix_med=("_prix", "median"),
        prix_min=("_prix", "min"),
        prix_max=("_prix", "max"),
        dernier_prix=("_prix", "last"),
        dernier_lavage=("Date", "max"),
        nb_nom2=("_nom2", lambda x: int((x != "").sum())),
    ).reset_index()
    st_df["type"] = np.where(st_df["nb_nom2"] > 0, "station", "laiterie")
    # Classement mixte : certaines lignes avec « Nom 2 », d'autres sans
    st_df["type_mixte"] = (st_df["nb_nom2"] > 0) & (st_df["nb_nom2"] < st_df["nb"])
    return st_df[st_df["nom"] != ""].reset_index(drop=True)


# ─── Annuaire des stations (fichier adresses) ────────────────────────────────
CHAMPS_ANNUAIRE = {
    "nom": ("Nom de la station *", ["NOM 1", "NOM", "RAISON SOCIALE", "STATION", "SOCIETE", "NAME",
                                    "LIBELLE", "DESIGNATION", "ENSEIGNE", "FOURNISSEUR"]),
    "adresse": ("Adresse (rue)", ["ADRESSE", "ADRESSE 1", "RUE", "STREET", "ADDRESS", "VOIE", "STRASSE"]),
    "cp": ("Code postal", ["CODE POSTAL", "CP", "POSTAL", "ZIP", "POSTCODE", "PLZ"]),
    "localite": ("Localité", ["LOCALITE", "VILLE", "COMMUNE", "CITY", "LOCALITY", "ORT"]),
    "pays": ("Pays", ["PAYS", "COUNTRY", "CODE PAYS", "LAND"]),
    "telephone": ("Téléphone", ["TELEPHONE", "TEL", "PHONE", "GSM", "TELEFON"]),
    "email": ("E-mail", ["EMAIL", "E MAIL", "MAIL", "COURRIEL"]),
    "lat": ("Latitude", ["LATITUDE", "LAT"]),
    "lon": ("Longitude", ["LONGITUDE", "LON", "LNG", "LONG"]),
}


def detect_colonnes(colonnes, champs=None) -> dict:
    """Associe automatiquement les colonnes du fichier aux champs attendus."""
    champs = champs or CHAMPS_ANNUAIRE
    norm = {c: normalize(c) for c in colonnes}
    pris, out = set(), {}
    for champ, (_, candidats) in champs.items():
        meilleur, score_max = None, 0
        for col, n in norm.items():
            if col in pris:
                continue
            for i, cand in enumerate(candidats):
                score = 0
                if n == cand:
                    score = 100 - i
                elif len(cand) >= 4 and cand in n:
                    score = 50 - i
                if score > score_max:
                    meilleur, score_max = col, score
        if meilleur:
            out[champ] = meilleur
            pris.add(meilleur)
    return out


@st.cache_data(show_spinner=False)
def build_annuaire(df_a: pd.DataFrame, mapping: tuple) -> pd.DataFrame:
    mp = dict(mapping)
    out = pd.DataFrame(index=df_a.index)
    for champ in CHAMPS_ANNUAIRE:
        col = mp.get(champ)
        out[champ] = df_a[col].fillna("").astype(str).str.strip() if col else ""
    out["cp"] = out["cp"].str.replace(r"\.0+$", "", regex=True)
    out["lat"] = out["lat"].map(lambda v: parse_coord(v, 90))
    out["lon"] = out["lon"].map(lambda v: parse_coord(v, 180))
    out = out[out["nom"] != ""].copy()
    out["_nn"] = out["nom"].map(normalize_nom)
    out["_cpn"] = out["cp"].map(cp_norm)
    out["_locn"] = out["localite"].map(normalize)
    return out.drop_duplicates(["_nn", "_cpn"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def build_base(hist: pd.DataFrame, ann: pd.DataFrame | None) -> pd.DataFrame:
    """
    Base unifiée = historique des lavages + annuaire.
    Rapprochement : même CP et nom proche (≥ 75 %), sinon même localité et nom très proche (≥ 85 %).
    Chaque station de l'annuaire n'est rattachée qu'à une seule station de l'historique.
    """
    hist = hist.copy()
    for c in ["adresse", "telephone", "email", "nom_annuaire", "rapprochement"]:
        hist[c] = ""
    hist["lat_ann"], hist["lon_ann"] = np.nan, np.nan

    if ann is None or ann.empty:
        hist["statut"] = S_HIST_SEUL
        return hist

    hist["_nn"] = hist["nom"].map(normalize_nom)
    hist["_cpn"] = hist["cp"].map(cp_norm)
    hist["_locn"] = hist["localite"].map(normalize)

    candidats = []
    for ai, a in ann.iterrows():
        meilleur = None
        if a["_cpn"]:
            for hi, h in hist[hist["_cpn"] == a["_cpn"]].iterrows():
                s = similarite(a["_nn"], h["_nn"])
                if s >= 0.75 and (meilleur is None or s > meilleur[0]):
                    meilleur = (s, hi, "exact" if s == 1 else "approchant")
        if meilleur is None and a["_locn"]:
            for hi, h in hist[hist["_locn"] == a["_locn"]].iterrows():
                s = similarite(a["_nn"], h["_nn"])
                if s >= 0.85 and (meilleur is None or s > meilleur[0]):
                    meilleur = (s, hi, "même localité")
        if meilleur:
            candidats.append((meilleur[0], ai, meilleur[1], meilleur[2]))

    candidats.sort(key=lambda x: -x[0])
    pris_h, pris_a = set(), set()
    for s, ai, hi, t in candidats:
        if hi in pris_h or ai in pris_a:
            continue
        pris_h.add(hi)
        pris_a.add(ai)
        a = ann.loc[ai]
        for c in ["adresse", "telephone", "email"]:
            hist.at[hi, c] = a[c]
        hist.at[hi, "nom_annuaire"] = a["nom"]
        hist.at[hi, "rapprochement"] = "exact" if t == "exact" else f"{t} ({s:.0%})"
        hist.at[hi, "lat_ann"] = a["lat"]
        hist.at[hi, "lon_ann"] = a["lon"]
        if not hist.at[hi, "pays"] and a["pays"]:
            hist.at[hi, "pays"] = a["pays"]
    hist["statut"] = np.where(hist.index.isin(list(pris_h)), S_HIST_ANN, S_HIST)

    seules = ann[~ann.index.isin(list(pris_a))]
    nouv = pd.DataFrame({
        "_cle": seules["nom"].map(normalize) + "|" + seules["cp"],
        "nom": seules["nom"], "localite": seules["localite"], "cp": seules["cp"], "pays": seules["pays"],
        "nb": 0, "prix_med": np.nan, "prix_min": np.nan, "prix_max": np.nan,
        "type": "station", "type_mixte": False, "nb_nom2": 0,
        "dernier_prix": np.nan, "dernier_lavage": pd.NaT,
        "adresse": seules["adresse"], "telephone": seules["telephone"], "email": seules["email"],
        "nom_annuaire": seules["nom"], "rapprochement": "",
        "lat_ann": seules["lat"], "lon_ann": seules["lon"],
        "statut": S_ANN,
    })
    base = pd.concat([hist.drop(columns=["_nn", "_cpn", "_locn"]), nouv], ignore_index=True)
    return base.drop_duplicates("_cle").reset_index(drop=True)


def excel_auto(sheets: dict) -> bytes:
    """Export Excel multi-onglets avec largeurs de colonnes ajustées."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom, df in sheets.items():
            df.to_excel(xw, sheet_name=nom[:31], index=False)
            ws = xw.sheets[nom[:31]]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                largeur = max([len(str(col))] + [len(str(v)) for v in df[col].head(300).tolist()])
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(largeur + 2, 8), 50)
    return buf.getvalue()






# ─── Page HTML de la carte plein écran ───────────────────────────────────────
APP_HTML = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Lavages citernes</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%AA%A3%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<style>
:root {
  --bg: #f5f5f7; --card: #ffffff; --text: #1d1d1f; --sub: #6e6e73; --line: #d2d2d7; --soft: #e8e8ed;
  --blue: #0071e3; --blue-h: #0077ed; --green: #34c759;
  --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif;
  --pw: 380px; --gap: 12px; --map-left: calc(var(--pw) + 2 * var(--gap));
  --ease: cubic-bezier(.32, .72, 0, 1);
}
body.collapsed { --map-left: 0px; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; overflow: hidden; font-family: var(--font); color: var(--text);
  background: var(--bg); -webkit-font-smoothing: antialiased; }
button, input { font-family: var(--font); }
#map { position: absolute; inset: 0; z-index: 0; background: #e5e3df; }
.glass { background: rgba(255,255,255,.82); backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  box-shadow: 0 10px 34px rgba(0,0,0,.14), 0 0 0 .5px rgba(0,0,0,.08); }

/* ── Panneau latéral ── */
#panel { position: absolute; z-index: 1001; top: var(--gap); left: var(--gap); bottom: var(--gap);
  width: var(--pw); max-width: calc(100vw - 2 * var(--gap)); border-radius: 20px; overflow-y: auto;
  padding: 24px 22px 28px; background: rgba(255,255,255,.9); transition: transform .34s var(--ease); }
body.collapsed #panel { transform: translateX(calc(-100% - 2 * var(--gap))); }
#collapse { position: absolute; z-index: 1002; top: 30px; left: calc(var(--pw) + var(--gap)); width: 24px; height: 52px;
  border: none; border-radius: 0 12px 12px 0; cursor: pointer; color: var(--sub);
  display: flex; align-items: center; justify-content: center; transition: left .34s var(--ease); }
#collapse svg { transition: transform .34s var(--ease); }
body.collapsed #collapse { left: 0; }
body.collapsed #collapse svg { transform: rotate(180deg); }
.title { font-size: 30px; font-weight: 700; letter-spacing: -.025em; line-height: 1.08; margin: 0 0 6px; }
.lede { font-size: 15px; line-height: 1.42; color: var(--sub); margin: 0; }
.sec { border-top: 1px solid #e5e5ea; margin-top: 20px; padding-top: 18px; }
.sec h2 { font-size: 17px; font-weight: 600; letter-spacing: -.01em; margin: 0 0 12px; }
.lbl { font-size: 13px; font-weight: 500; color: var(--sub); margin: 0 0 8px; }
.hint { font-size: 12.5px; color: var(--sub); line-height: 1.45; margin: 10px 0 0; }

/* Recherche */
.search { position: relative; }
.search input { width: 100%; height: 46px; border: 1px solid var(--line); border-radius: 12px; background: #fff;
  padding: 0 40px 0 40px; font-size: 15px; color: var(--text); outline: none;
  transition: border-color .15s, box-shadow .15s; }
.search input::placeholder { color: #86868b; }
.search input:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(0,113,227,.18); }
.search .ico { position: absolute; left: 14px; top: 15px; color: #86868b; pointer-events: none; }
.search .clear { position: absolute; right: 10px; top: 12px; width: 22px; height: 22px; border-radius: 50%;
  border: none; background: #c7c7cc; color: #fff; cursor: pointer; display: none; font-size: 13px; line-height: 22px; padding: 0; }
.search.filled .clear { display: block; }
#results { list-style: none; margin: 8px 0 0; padding: 5px; background: #fff; border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0,0,0,.12), 0 0 0 .5px rgba(0,0,0,.06); display: none; }
#results.show { display: block; }
#results li { padding: 9px 12px; border-radius: 9px; cursor: pointer; font-size: 14px; line-height: 1.3; }
#results li small { display: block; color: var(--sub); font-size: 12px; margin-top: 2px; }
#results li:hover, #results li.active { background: var(--bg); }
#results li.vide { color: var(--sub); cursor: default; }
#results li.vide:hover { background: none; }

/* Curseur */
.range-head { display: flex; justify-content: space-between; align-items: baseline; margin-top: 18px; }
.range-head b { color: var(--blue); font-weight: 600; font-size: 15px; }
input[type=range] { -webkit-appearance: none; appearance: none; width: 100%; height: 4px; border-radius: 2px;
  margin: 16px 0 4px; outline: none; cursor: pointer;
  background: linear-gradient(to right, var(--blue) var(--p, 25%), var(--soft) var(--p, 25%)); }
input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 26px; height: 26px; border-radius: 50%;
  background: #fff; box-shadow: 0 1px 5px rgba(0,0,0,.28), 0 0 0 .5px rgba(0,0,0,.08); }
input[type=range]::-moz-range-thumb { width: 26px; height: 26px; border: none; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 5px rgba(0,0,0,.28), 0 0 0 .5px rgba(0,0,0,.08); }
.range-scale { display: flex; justify-content: space-between; font-size: 11.5px; color: #86868b; }

/* Contrôle segmenté */
.seg { display: flex; background: var(--soft); border-radius: 10px; padding: 3px; }
.seg button { flex: 1; border: none; background: transparent; padding: 7px 10px; border-radius: 8px;
  font-size: 13px; font-weight: 500; color: var(--text); cursor: pointer; white-space: nowrap;
  transition: background .15s, box-shadow .15s; }
.seg button.on { background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.12), 0 0 0 .5px rgba(0,0,0,.04); }

/* Interrupteurs */
.rows { margin-top: 10px; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 11px 0; font-size: 15px; }
.row + .row { border-top: .5px solid #e5e5ea; }
.sw { position: relative; width: 51px; height: 31px; flex: none; }
.sw input { position: absolute; opacity: 0; width: 0; height: 0; }
.sw span { position: absolute; inset: 0; background: #e9e9eb; border-radius: 31px; cursor: pointer; transition: background .2s; }
.sw span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 3px 8px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.16); transition: transform .2s var(--ease); }
.sw input:checked + span { background: var(--green); }
.sw input:checked + span::after { transform: translateX(20px); }
.sw input:focus-visible + span { box-shadow: 0 0 0 4px rgba(0,113,227,.25); }

/* Boutons */
.btn { width: 100%; height: 44px; border: none; border-radius: 980px; font-size: 15px; font-weight: 500;
  cursor: pointer; transition: background .15s, transform .1s, opacity .15s; }
.btn.primary { background: var(--blue); color: #fff; }
.btn.primary:hover { background: var(--blue-h); }
.btn.secondary { background: var(--soft); color: var(--blue); }
.btn.secondary:hover { background: #dedee3; }
.btn:active { transform: scale(.98); }
.btn:disabled { opacity: .4; cursor: default; transform: none; }
.btn + .btn { margin-top: 10px; }
.facts { font-size: 13px; color: var(--sub); line-height: 1.6; margin: 0; }
.facts b { color: var(--text); font-weight: 600; }

/* ── Synthèse en haut à droite ── */
#info { position: absolute; z-index: 1000; top: var(--gap); right: var(--gap); width: 280px; padding: 16px 18px 14px;
  border-radius: 18px; }
#info .k { font-size: 12px; font-weight: 500; color: var(--sub); }
#info .t { font-size: 17px; font-weight: 600; letter-spacing: -.01em; line-height: 1.25; margin: 2px 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#info .s { font-size: 12.5px; color: var(--sub); line-height: 1.4; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 12px; }
.stats .n { font-size: 26px; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; }
.stats .l { font-size: 11.5px; color: var(--sub); }
.kv { display: flex; justify-content: space-between; align-items: baseline; border-top: .5px solid rgba(0,0,0,.12);
  padding: 8px 0 2px; font-size: 13px; }
.kv span { color: var(--sub); }
.kv b { font-weight: 600; }
.kv b.vert { color: #00a854; }

/* ── Légende ── */
#legend { position: absolute; z-index: 999; left: max(var(--gap), var(--map-left)); bottom: var(--gap);
  padding: 10px 14px; border-radius: 16px; font-size: 11.5px; display: grid; grid-template-columns: auto auto;
  gap: 5px 16px; transition: left .34s var(--ease), opacity .2s; }
#legend div { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
#legend i { display: inline-block; flex: none; border: 2px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,.3); }
body.sheet-open #legend { opacity: 0; pointer-events: none; }

/* ── Bouton « Détail » en bas ── */
#chip { position: absolute; z-index: 1000; bottom: 22px;
  left: calc(var(--map-left) + (100vw - var(--map-left)) / 2); transform: translateX(-50%);
  border: none; border-radius: 980px; padding: 11px 20px; font-size: 14px; font-weight: 500; color: var(--text);
  cursor: pointer; display: flex; align-items: center; gap: 8px;
  transition: left .34s var(--ease), opacity .2s, transform .1s; }
#chip:active { transform: translateX(-50%) scale(.97); }
#chip .count { background: var(--blue); color: #fff; border-radius: 980px; padding: 1px 8px; font-size: 12px; font-weight: 600; }
body.sheet-open #chip { opacity: 0; pointer-events: none; }

/* ── Feuille de détail ── */
#sheet { position: absolute; z-index: 1003; left: max(var(--gap), var(--map-left)); right: var(--gap); bottom: var(--gap);
  height: min(48vh, 520px); border-radius: 20px; background: rgba(255,255,255,.96); display: flex; flex-direction: column;
  transform: translateY(calc(100% + 40px)); transition: transform .4s var(--ease), left .34s var(--ease); }
body.sheet-open #sheet { transform: translateY(0); }
.grab { width: 38px; height: 5px; border-radius: 3px; background: #c7c7cc; margin: 8px auto 4px; }
.sheet-head { display: flex; align-items: center; gap: 12px; padding: 6px 18px 12px; flex-wrap: wrap; }
.sheet-head .seg { flex: none; }
.sheet-head .grow { flex: 1; }
.filter { position: relative; width: 240px; }
.filter input { width: 100%; height: 34px; border-radius: 10px; border: none; background: var(--soft);
  padding: 0 12px 0 32px; font-size: 13.5px; outline: none; color: var(--text); }
.filter input:focus { box-shadow: 0 0 0 3px rgba(0,113,227,.25); }
.filter svg { position: absolute; left: 10px; top: 10px; color: #86868b; }
.small-btn { height: 34px; border: none; border-radius: 980px; padding: 0 16px; background: var(--soft);
  color: var(--blue); font-size: 13.5px; font-weight: 500; cursor: pointer; }
.small-btn:hover { background: #dedee3; }
.close { width: 30px; height: 30px; border-radius: 50%; border: none; background: var(--soft); color: var(--sub);
  cursor: pointer; font-size: 15px; line-height: 30px; padding: 0; }
.tbl-wrap { flex: 1; overflow: auto; padding: 0 18px 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { position: sticky; top: 0; background: rgba(255,255,255,.98); text-align: left; font-weight: 600; color: var(--sub);
  font-size: 12px; padding: 9px 10px; border-bottom: .5px solid var(--line); cursor: pointer; white-space: nowrap;
  user-select: none; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
th .arr { color: var(--blue); }
td { padding: 9px 10px; border-bottom: .5px solid #ececf0; white-space: nowrap; }
tr.click { cursor: pointer; }
tr.click:hover td { background: #f5f5f7; }
td.min { background: #e3f6ea; font-weight: 600; color: #00753a; }
td a { color: #0066cc; text-decoration: none; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 980px; font-size: 11.5px; font-weight: 500; }
.b-used { background: #e8f1fc; color: #0057A8; }
.b-ann { background: #e0f6f8; color: #00808f; }
.b-hors { background: #fff1e0; color: #b45a00; }
.empty { padding: 34px 0; text-align: center; color: var(--sub); font-size: 14px; }

/* ── Marqueurs ── */
.cb-icon { background: none; border: none; }
.cb-pill { display: inline-block; white-space: nowrap; transform: translate(-50%, -50%); padding: 2px 8px;
  border-radius: 11px; border: 2px solid #fff; font: 600 12px/1.25 var(--font); color: #fff;
  box-shadow: 0 2px 6px rgba(0,0,0,.35); cursor: pointer; }
.cb-carre { width: 14px; height: 14px; transform: translate(-50%, -50%); background: #00acc1; border: 2px solid #fff;
  border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,.35); cursor: pointer; }
.cb-losange { width: 13px; height: 13px; transform: translate(-50%, -50%) rotate(45deg); background: #aa00ff;
  border: 2px solid #fff; border-radius: 2px; box-shadow: 0 2px 6px rgba(0,0,0,.35); cursor: pointer; }
.cb-centre { width: 22px; height: 22px; transform: translate(-50%, -50%); border-radius: 50%;
  border: 5px solid #e53935; background: rgba(255,255,255,.95); box-shadow: 0 0 0 2px #fff, 0 2px 8px rgba(0,0,0,.45); }

/* ── Leaflet façon Apple ── */
.leaflet-bar { border: none !important; border-radius: 12px !important; overflow: hidden;
  box-shadow: 0 4px 16px rgba(0,0,0,.14), 0 0 0 .5px rgba(0,0,0,.08) !important; }
.leaflet-bar a { background: rgba(255,255,255,.9) !important; color: var(--text) !important; width: 36px !important;
  height: 36px !important; line-height: 36px !important; border-bottom: .5px solid rgba(0,0,0,.1) !important; }
.leaflet-popup-content-wrapper { border-radius: 14px; box-shadow: 0 10px 34px rgba(0,0,0,.18); }
.leaflet-popup-content { font: 13px/1.5 var(--font); color: var(--text); margin: 14px 16px; }
.leaflet-popup-content a { color: #0066cc; text-decoration: none; }
.leaflet-tooltip { border-radius: 8px; border: none; box-shadow: 0 4px 14px rgba(0,0,0,.18); font: 500 12px var(--font); }
.leaflet-control-attribution { background: rgba(255,255,255,.72) !important; border-radius: 8px 0 0 0;
  font: 10px var(--font); color: var(--sub); }
.leaflet-control-scale-line { background: rgba(255,255,255,.72); border-color: var(--sub); color: var(--text); font: 10px var(--font); }
.leaflet-bottom.leaflet-right { margin-bottom: 4px; }

@media (max-width: 760px) {
  :root { --pw: calc(100vw - 24px); }
  #info { display: none; }
  .filter { width: 100%; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div id="map"></div>

<aside id="panel" class="glass">
  <h1 class="title">Lavages citernes</h1>
  <p class="lede">Stations utilisées, prix pratiqués et nouvelles stations autour d’un point.</p>

  <div class="sec">
    <h2>Position</h2>
    <div class="search" id="searchbox">
      <svg class="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="text" autocomplete="off" placeholder="Adresse, ville, code postal ou station" aria-label="Rechercher une adresse ou une station">
      <button class="clear" id="qclear" aria-label="Effacer">✕</button>
    </div>
    <ul id="results" role="listbox"></ul>
    <p class="hint">Ou cliquez directement sur la carte.</p>
    <div class="range-head"><span class="lbl" style="margin:0">Rayon de recherche</span><b id="rval">50 km</b></div>
    <input id="rayon" type="range" min="5" max="200" step="5" value="50" aria-label="Rayon de recherche">
    <div class="range-scale"><span>5 km</span><span>200 km</span></div>
  </div>

  <div class="sec">
    <h2>Affichage</h2>
    <div id="bloc-types">
      <p class="lbl">Type de lieu</p>
      <div class="seg" id="types"></div>
      <p class="lbl" style="margin-top:16px">Fond de carte</p>
    </div>
    <div class="seg" id="fonds"></div>
    <div class="rows">
      <label class="row">Frontières renforcées<span class="sw"><input type="checkbox" id="t-borders" checked><span></span></span></label>
      <label class="row">Lieux hors rayon<span class="sw"><input type="checkbox" id="t-hors" checked><span></span></span></label>
    </div>
  </div>

  <div class="sec">
    <h2>Nouvelles stations</h2>
    <button class="btn primary" id="b-pistes" disabled>Chercher de nouvelles stations</button>
    <p class="hint" id="pistes-etat">Choisissez d’abord une position.</p>
  </div>

  <div class="sec">
    <h2>Données</h2>
    <p class="facts" id="facts"></p>
  </div>
</aside>
<button id="collapse" class="glass" aria-label="Réduire le panneau">
  <svg width="10" height="16" viewBox="0 0 10 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2 2 8l6 6"/></svg>
</button>

<div id="info" class="glass"></div>
<div id="legend" class="glass"></div>

<button id="chip" class="glass">
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2 8l4-4 4 4"/></svg>
  <span id="chip-txt">Afficher le détail</span><span class="count" id="chip-n">0</span>
</button>

<section id="sheet" class="glass" aria-label="Détail">
  <div class="grab"></div>
  <div class="sheet-head">
    <div class="seg" id="tabs"></div>
    <div class="grow"></div>
    <div class="filter">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="filtre" type="text" placeholder="Filtrer" aria-label="Filtrer le tableau">
    </div>
    <button class="small-btn" id="export">Exporter</button>
    <button class="close" id="close" aria-label="Fermer le détail">✕</button>
  </div>
  <div class="tbl-wrap" id="tbl"></div>
</section>

<script>
const D = __DATA__;
const BORDERS = __BORDERS__;
const ST = D.stations;
const LAV = D.lavages || [];
const HAS_PROD = LAV.length > 0;
const TYPE_C = { station: '#0a84ff', laiterie: '#ff9f0a' };
const TYPE_L = { station: 'Station de lavage', laiterie: 'Laiterie ou usine' };
const C = { vert: '#00a854', orange: '#f57c00', rouge: '#e53935', gris: '#78909c', ann: '#00acc1', piste: '#aa00ff', centre: '#e53935' };
function esri(s) { return `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`; }
const FONDS = {
  'Satellite': { layers: [[esri('World_Imagery'), 'Tiles © Esri', 18], [esri('Reference/World_Boundaries_and_Places'), '© Esri', 18]],
                 front: '#ffd54f', halo: '#000000', point: '#ffffff' },
  'Sombre': { layers: [[esri('Canvas/World_Dark_Gray_Base'), 'Tiles © Esri', 16], [esri('Canvas/World_Dark_Gray_Reference'), '© Esri', 16]],
              front: '#ffd54f', halo: '#000000', point: '#8ab4f8' },
};
const OSM_MAX = 100;
const OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
const NAME_RX = 'tank ?clean|tank ?wash|tankreinig|tankinnenreinig|tankwasch|tankreiniging|lavage.{0,12}citerne|nettoyage.{0,12}citerne|station de lavage poids|lavaggio.{0,6}cisterne|limpieza.{0,6}cisternas|cleaning station';

const state = { type: 'tout', center: null, rayon: 50, fond: 'Satellite', borders: true, hors: true,
                pistes: {}, tab: 'proches', sort: { key: 'dist', dir: 1 }, filtre: '',
                proches: [], used: [], ann: [], pis: [] };
const $ = id => document.getElementById(id);

// ── Utilitaires ──
function esc(v) { return v == null ? '' : String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function hav(a, b, c, d) {
  const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}
function quant(a, q) { const p = (a.length - 1) * q, lo = Math.floor(p), hi = Math.ceil(p); return a[lo] + (a[hi] - a[lo]) * (p - lo); }
function median(a) { const s = a.slice().sort((x, y) => x - y); return s.length ? quant(s, .5) : null; }
const FJ = /\b(SA|SAS|SASU|SARL|EURL|SNC|SPRL|SRL|SC|NV|BV|BVBA|VOF|GMBH|AG|KG|CO|LTD|SPA|SL|ETS|ETABLISSEMENTS|STE|SOCIETE)\b/g;
function nn(t) { return (t || '').toUpperCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^A-Z0-9 ]/g, ' ').replace(FJ, ' ').replace(/\s+/g, ' ').trim(); }
function sim(a, b) {
  if (!a || !b) return 0; if (a === b) return 1;
  if (a.length >= 5 && b.length >= 5 && (a.includes(b) || b.includes(a))) return .9;
  const bg = s => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const k = s.substr(i, 2); m.set(k, (m.get(k) || 0) + 1); } return m; };
  const A = bg(a), B = bg(b); let inter = 0, tot = 0;
  A.forEach((v, k) => { inter += Math.min(v, B.get(k) || 0); tot += v; }); B.forEach(v => tot += v);
  return tot ? 2 * inter / tot : 0;
}
function eur(v, d = 2) { return v == null ? '—' : v.toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }) + ' €'; }
function km(v) { return v == null ? '—' : v.toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }); }
function dfr(s) { if (!s) return '—'; const [y, m, d] = s.split('-'); return `${d}/${m}/${y}`; }
function gmaps(la, lo) { return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(6)},${lo.toFixed(6)}`; }
function divIcon(cls, txt = '', bg = null) {
  return L.divIcon({ className: 'cb-icon', html: `<div class="${cls}"${bg ? ` style="background:${bg}"` : ''}>${txt}</div>`, iconSize: [0, 0], iconAnchor: [0, 0] });
}
ST.forEach((s, i) => { s.i = i; s._nn = nn(s.nom); s.type = s.type || 'station'; });
const vis = s => state.type === 'tout' || s.type === state.type;

// ── Carte ──
const map = L.map('map', { zoomControl: false, worldCopyJump: true }).setView([49.8, 5.5], 6);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ position: 'bottomright', imperial: false }).addTo(map);
const lyr = L.layerGroup().addTo(map);
let tiles = [], bHalo = null, bLine = null, circle = null;
const mk = {};

function mapLeft() { return document.body.classList.contains('collapsed') ? 0 : $('panel').offsetWidth + 24; }
function fitTo(bounds) {
  map.fitBounds(bounds, { paddingTopLeft: [mapLeft() + 16, 20], paddingBottomRight: [window.innerWidth > 760 ? 310 : 20, 20], maxZoom: 14 });
}

function applyFond() {
  tiles.forEach(t => map.removeLayer(t)); tiles = [];
  FONDS[state.fond].layers.forEach(([u, a, z], i) => tiles.push(L.tileLayer(u, { attribution: a, maxNativeZoom: z, maxZoom: 19, zIndex: i }).addTo(map)));
  drawBorders(); render();
}
function drawBorders() {
  [bHalo, bLine].forEach(l => l && map.removeLayer(l)); bHalo = bLine = null;
  if (!state.borders || !BORDERS) return;
  const f = FONDS[state.fond];
  bHalo = L.geoJSON(BORDERS, { interactive: false, style: { color: f.halo, weight: 7, opacity: .75 } }).addTo(map);
  bLine = L.geoJSON(BORDERS, { interactive: false, style: { color: f.front, weight: 2.6, opacity: 1 } }).addTo(map);
}

function popupStation(s) {
  const l = [`<b style="font-size:14px">${esc(s.nom)}</b>`];
  if (D.has_type) l.push(`<span style="color:${TYPE_C[s.type]};font-weight:600">${TYPE_L[s.type]}</span>`);
  if (s.adresse) l.push(esc(s.adresse));
  l.push(`${esc(s.cp)} ${esc(s.localite)} ${esc(s.pays)}`.trim());
  if (s.nb > 0) {
    l.push(`Prix médian : <b>${eur(s.prix_med)}</b>${s.prix_min != null ? ` (min ${eur(s.prix_min)}, max ${eur(s.prix_max)})` : ''}`);
    l.push(`${s.nb} lavage(s), dernier le ${dfr(s.dernier_lavage)}`);
  } else l.push('Dans l’annuaire, jamais utilisée. Prix à demander.');
  if (s.telephone) l.push(`Tél. ${esc(s.telephone)}`);
  if (s.email) l.push(esc(s.email));
  if (s.dist != null) l.push(`À ${km(s.dist)} km`);
  if (s.precision === 'localité') l.push('<i>Position approximative (centre de la commune)</i>');
  l.push(`<a href="${gmaps(s.lat, s.lon)}" target="_blank" rel="noopener">Ouvrir dans Google Maps</a>`);
  return l.join('<br>');
}
function popupPiste(p) {
  return `<b style="font-size:14px">${esc(p.nom)}</b><br>${esc(p.adresse) || 'Adresse non renseignée'}<br>Jamais utilisée. Prix à demander.<br>À ${km(p.dist)} km, source ${p.source}<br>`
    + (p.telephone ? `Tél. ${esc(p.telephone)}<br>` : '')
    + (p.site ? `<a href="${esc(p.site)}" target="_blank" rel="noopener">Site web</a><br>` : '')
    + `<a href="${gmaps(p.lat, p.lon)}" target="_blank" rel="noopener">Ouvrir dans Google Maps</a>`;
}

// ── Nouvelles pistes (OpenStreetMap) ──
function pisteCache() {
  const c = state.center; if (!c) return null;
  const pre = `${c.lat.toFixed(3)}|${c.lon.toFixed(3)}|`;
  const cible = Math.min(state.rayon, OSM_MAX);
  let best = null;
  for (const k in state.pistes) if (k.startsWith(pre) && +k.slice(pre.length) >= cible) best = state.pistes[k];
  return best;
}
function preparePistes() {
  const res = pisteCache(); if (!res) return null;
  const c = state.center, out = [];
  res.trouves.forEach(p => {
    const d = hav(c.lat, c.lon, p.lat, p.lon); if (d > state.rayon) return;
    if (out.some(g => hav(p.lat, p.lon, g.lat, g.lon) <= .15)) return;
    const pn = nn(p.nom);
    const connue = ST.some(s => { const dd = hav(p.lat, p.lon, s.lat, s.lon); return dd < 5 && (dd < .4 || sim(pn, s._nn) > .75); });
    if (!connue) out.push({ ...p, dist: d });
  });
  return out.sort((a, b) => a.dist - b.dist);
}
async function chercherPistes() {
  const c = state.center; if (!c) return;
  const r = Math.min(state.rayon, OSM_MAX), dlat = r / 111, dlon = r / (111 * Math.max(Math.cos(c.lat * Math.PI / 180), .1));
  const bb = [c.lat - dlat, c.lon - dlon, c.lat + dlat, c.lon + dlon].map(v => v.toFixed(4)).join(',');
  const q = `[out:json][timeout:25][bbox:${bb}];(nw["name"~"${NAME_RX}",i][!"highway"];nw["amenity"="vehicle_wash"]["hgv"~"yes|designated|only"];nw["amenity"="truck_wash"];);out center tags;`;
  const btn = $('b-pistes'); btn.disabled = true; btn.textContent = 'Recherche en cours…';
  $('pistes-etat').textContent = 'Interrogation d’OpenStreetMap…';
  const t0 = performance.now(); let data = null;
  for (const url of OVERPASS) {
    try { const res = await fetch(url, { method: 'POST', body: new URLSearchParams({ data: q }) }); if (res.ok) { data = await res.json(); break; } } catch (e) { }
  }
  btn.textContent = 'Chercher de nouvelles stations';
  if (!data) { btn.disabled = false; $('pistes-etat').textContent = 'OpenStreetMap n’a pas répondu à temps. Relancez dans une minute.'; return; }
  const trouves = [];
  (data.elements || []).forEach(el => {
    const t = el.tags || {}, la = el.lat ?? el.center?.lat, lo = el.lon ?? el.center?.lon; if (la == null || lo == null) return;
    const rue = [t['addr:street'], t['addr:housenumber']].filter(Boolean).join(' ');
    const ville = [t['addr:postcode'], t['addr:city']].filter(Boolean).join(' ');
    trouves.push({ nom: t.name || t.operator || 'Station de lavage PL (sans nom)', adresse: [rue, ville].filter(Boolean).join(', '),
      lat: +la, lon: +lo, telephone: t.phone || t['contact:phone'] || '', site: t.website || t['contact:website'] || '', source: 'OpenStreetMap' });
  });
  state.pistes[`${c.lat.toFixed(3)}|${c.lon.toFixed(3)}|${r}`] = { trouves, duree: (performance.now() - t0) / 1000 };
  render();
}

// ── Rendu principal ──
function render() {
  lyr.clearLayers(); for (const k in mk) delete mk[k];
  if (circle) { map.removeLayer(circle); circle = null; }
  const c = state.center, R = state.rayon, f = FONDS[state.fond];
  ST.forEach(s => s.dist = c ? hav(c.lat, c.lon, s.lat, s.lon) : null);
  let proches = [];
  if (c) {
    circle = L.circle([c.lat, c.lon], { radius: R * 1000, color: C.centre, weight: 2, dashArray: '6 6', fillOpacity: .05, interactive: false }).addTo(map);
    lyr.addLayer(L.marker([c.lat, c.lon], { icon: divIcon('cb-centre'), interactive: false, keyboard: false, zIndexOffset: -1000 }));
    proches = ST.filter(s => vis(s) && s.dist <= R).sort((a, b) => a.dist - b.dist);
  }
  const dedans = new Set(proches.map(s => s.i));
  if (state.hors) ST.forEach(s => {
    if (dedans.has(s.i) || !vis(s)) return;
    const fill = s.nb === 0 ? C.ann : (state.type === 'tout' && D.has_type ? TYPE_C[s.type] : f.point);
    const m = L.circleMarker([s.lat, s.lon], { radius: 5, color: '#fff', weight: 1.5, fillColor: fill, fillOpacity: .95, bubblingMouseEvents: false })
      .bindTooltip(`${esc(s.nom)} (${esc(s.localite)})`).bindPopup(() => popupStation(s), { maxWidth: 320 });
    lyr.addLayer(m); mk['s' + s.i] = m;
  });
  const used = proches.filter(s => s.nb > 0), ann = proches.filter(s => s.nb === 0);
  const px = used.map(s => s.prix_med).filter(v => v != null).sort((a, b) => a - b);
  const [q1, q2] = px.length >= 3 ? [quant(px, 1 / 3), quant(px, 2 / 3)] : [Infinity, Infinity];
  const add = (key, ll, icon, tip, pop) => {
    const m = L.marker(ll, { icon, riseOnHover: true }).bindTooltip(esc(tip), { direction: 'top', offset: [0, -12] }).bindPopup(pop, { maxWidth: 320 });
    lyr.addLayer(m); mk[key] = m;
  };
  ann.forEach(s => add('s' + s.i, [s.lat, s.lon], divIcon('cb-carre'), `${s.nom} (jamais utilisée)`, () => popupStation(s)));
  used.forEach(s => {
    const p = s.prix_med;
    const col = (state.type === 'tout' && D.has_type) ? TYPE_C[s.type]
      : (p == null ? C.gris : (p <= q1 ? C.vert : p <= q2 ? C.orange : C.rouge));
    const txt = p == null ? '? €' : `${Math.round(p)} €`;
    add('s' + s.i, [s.lat, s.lon], divIcon('cb-pill', txt, col), `${s.nom} : ${txt}`, () => popupStation(s));
  });
  const pis = state.type === 'laiterie' ? null : preparePistes();
  (pis || []).forEach((p, j) => { p.j = j; add('p' + j, [p.lat, p.lon], divIcon('cb-losange'), `Nouvelle piste : ${p.nom}`, () => popupPiste(p)); });
  Object.assign(state, { proches, used, ann, pis });
  updateInfo(); updateEtatPistes(); updateChip(); legend();
  if (document.body.classList.contains('sheet-open')) renderSheet();
}

function updateInfo() {
  const c = state.center;
  if (!c) {
    $('info').innerHTML = '<div class="k">Aucune position</div><div class="t">Choisissez un point</div><div class="s">Recherchez une adresse ou une station dans le panneau, ou cliquez directement sur la carte.</div>';
    return;
  }
  const px = state.used.filter(s => s.prix_med != null);
  const moins = px.slice().sort((a, b) => a.prix_med - b.prix_med)[0];
  const stat = (v, l) => `<div><div class="n">${v}</div><div class="l">${l}</div></div>`;
  $('info').innerHTML = `<div class="k">Rayon de ${state.rayon} km autour de</div><div class="t">${esc(c.label)}</div>
    <div class="stats">${stat(state.used.length, 'utilisées')}${stat(D.has_annuaire ? state.ann.length : '—', 'annuaire')}${stat(state.pis ? state.pis.length : '—', 'pistes')}</div>
    ` + (state.type === 'tout' && D.has_type
      ? ['station', 'laiterie'].map(t => { const v = px.filter(s => s.type === t).map(s => s.prix_med);
          return `<div class="kv"><span>Prix médian ${t === 'station' ? 'stations de lavage' : 'laiteries'}</span><b>${v.length ? Math.round(median(v)) + ' €' : '—'}</b></div>`; }).join('')
      : `<div class="kv"><span>Prix médian de la zone</span><b>${px.length ? Math.round(median(px.map(s => s.prix_med))) + ' €' : '—'}</b></div>`)
    + (moins ? `<div class="kv"><span>Moins cher</span><b class="vert">${Math.round(moins.prix_med)} €</b></div><div class="s">${esc(moins.nom)}${D.has_type && state.type === 'tout' ? ` (${TYPE_L[moins.type].toLowerCase()})` : ''}</div>` : '');
}
function updateEtatPistes() {
  const btn = $('b-pistes'), e = $('pistes-etat');
  if (!state.center) { btn.disabled = true; e.textContent = 'Choisissez d’abord une position.'; return; }
  if (state.type === 'laiterie') { btn.disabled = true; e.textContent = 'Les nouvelles pistes concernent les stations de lavage.'; return; }
  const res = pisteCache();
  btn.disabled = !!res;
  if (res) e.textContent = `${state.pis.length} nouvelle(s) station(s) trouvée(s) en ${res.duree.toFixed(1)} s, hors stations déjà connues.`;
  else e.textContent = state.rayon > OSM_MAX ? `Source OpenStreetMap, recherche limitée à ${OSM_MAX} km.` : 'Source OpenStreetMap. Lancée uniquement sur demande.';
}
function updateChip() {
  const n = state.center ? state.proches.length : ST.filter(vis).length;
  $('chip-txt').textContent = state.center ? 'Afficher le détail de la zone' : 'Afficher toutes les stations';
  $('chip-n').textContent = n;
}

function legend() {
  const it = (css, t) => `<div><i style="${css}"></i>${t}</div>`, pill = c => `width:20px;height:11px;border-radius:7px;background:${c}`;
  const commun = [it(`width:10px;height:10px;border-radius:3px;background:${C.ann}`, 'Annuaire, jamais utilisée'),
    it(`width:9px;height:9px;transform:rotate(45deg);background:${C.piste}`, 'Nouvelle piste'),
    it(`width:10px;height:10px;border-radius:50%;border:3px solid ${C.centre};background:#fff`, 'Centre de recherche'),
    it(`width:8px;height:8px;border-radius:50%;background:${state.type === 'tout' && D.has_type ? TYPE_C.station : FONDS[state.fond].point}`, 'Hors rayon (petit point)')];
  const prix = state.type === 'tout' && D.has_type
    ? [it(pill(TYPE_C.station), 'Station de lavage'), it(pill(TYPE_C.laiterie), 'Laiterie ou usine'), '', '']
    : [it(pill(C.vert), 'Prix bas'), it(pill(C.orange), 'Prix moyen'), it(pill(C.rouge), 'Prix élevé'), it(pill(C.gris), 'Prix inconnu')];
  $('legend').innerHTML = prix.filter(Boolean).concat(commun).join('');
}

function setCenter(c, fit = true) {
  state.center = c; render();
  if (fit && circle) fitTo(circle.getBounds());
}

// ── Recherche d'adresse ──
let tmr = null, resultats = [], actif = -1;
function afficherResultats() {
  const ul = $('results');
  if (!resultats.length) { ul.innerHTML = '<li class="vide">Aucun résultat. Essayez avec le code postal.</li>'; ul.classList.add('show'); return; }
  ul.innerHTML = resultats.map((r, i) => `<li role="option" data-i="${i}" class="${i === actif ? 'active' : ''}">${esc(r.label)}<small>${esc(r.sub)}</small></li>`).join('');
  ul.classList.add('show');
}
async function chercherAdresse(q) {
  const qn = nn(q);
  const loc = ST.filter(s => s._nn.includes(qn)).slice(0, 3)
    .map(s => ({ label: s.nom, sub: `${D.has_type ? TYPE_L[s.type] : 'Lieu'} de la base, ${[s.cp, s.localite].filter(Boolean).join(' ')}`, lat: s.lat, lon: s.lon }));
  let geo = [];
  try {
    const j = await (await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=5&lang=fr`)).json();
    geo = (j.features || []).map(f => {
      const p = f.properties || {}, [lo, la] = f.geometry.coordinates;
      const rue = [p.street, p.housenumber].filter(Boolean).join(' ');
      return { label: p.name || rue || p.city || q, sub: [p.name ? rue : '', [p.postcode, p.city].filter(Boolean).join(' '), p.country].filter(Boolean).join(', '), lat: la, lon: lo };
    });
  } catch (e) {
    try {
      const j = await (await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`)).json();
      geo = j.map(d => ({ label: d.display_name.split(',')[0], sub: d.display_name.split(',').slice(1, 4).join(',').trim(), lat: +d.lat, lon: +d.lon }));
    } catch (e2) { }
  }
  if ($('q').value.trim() !== q) return;
  resultats = loc.concat(geo); actif = resultats.length ? 0 : -1; afficherResultats();
}
function choisir(i) {
  const r = resultats[i]; if (!r) return;
  $('q').value = r.label; $('results').classList.remove('show');
  setCenter({ lat: r.lat, lon: r.lon, label: [r.label, r.sub].filter(Boolean).join(', ') });
}
$('q').addEventListener('input', () => {
  const q = $('q').value.trim(); $('searchbox').classList.toggle('filled', q.length > 0);
  clearTimeout(tmr); if (q.length < 2) { $('results').classList.remove('show'); return; }
  tmr = setTimeout(() => chercherAdresse(q), 280);
});
$('q').addEventListener('keydown', e => {
  if (!$('results').classList.contains('show')) return;
  if (e.key === 'ArrowDown') { actif = Math.min(actif + 1, resultats.length - 1); afficherResultats(); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { actif = Math.max(actif - 1, 0); afficherResultats(); e.preventDefault(); }
  else if (e.key === 'Enter') choisir(Math.max(actif, 0));
  else if (e.key === 'Escape') $('results').classList.remove('show');
});
$('results').addEventListener('mousedown', e => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); choisir(+li.dataset.i); } });
$('q').addEventListener('blur', () => setTimeout(() => $('results').classList.remove('show'), 120));
$('qclear').addEventListener('click', () => { $('q').value = ''; $('searchbox').classList.remove('filled'); $('results').classList.remove('show'); $('q').focus(); });

map.on('click', async e => {
  const lat = e.latlng.lat, lon = e.latlng.lng;
  const c = { lat, lon, label: `Point sélectionné (${lat.toFixed(4)}, ${lon.toFixed(4)})` };
  setCenter(c, false);
  try {
    const j = await (await fetch(`https://photon.komoot.io/reverse?lat=${lat}&lon=${lon}&lang=fr`)).json();
    const p = (j.features || [])[0]?.properties;
    if (p && state.center === c) {
      c.label = [[p.street, p.housenumber].filter(Boolean).join(' '), [p.postcode, p.city || p.name].filter(Boolean).join(' '), p.country].filter(Boolean).join(', ') || c.label;
      updateInfo();
    }
  } catch (err) { }
});

// ── Réglages ──
function majRayon() {
  const r = $('rayon'); $('rval').textContent = `${r.value} km`;
  r.style.setProperty('--p', `${(r.value - r.min) / (r.max - r.min) * 100}%`);
}
$('rayon').addEventListener('input', () => { majRayon(); state.rayon = +$('rayon').value; render(); });
$('rayon').addEventListener('change', () => { if (circle) fitTo(circle.getBounds()); });
$('fonds').innerHTML = Object.keys(FONDS).map(k => `<button data-f="${k}" class="${k === state.fond ? 'on' : ''}">${k}</button>`).join('');
$('fonds').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.fond = b.dataset.f; [...$('fonds').children].forEach(x => x.classList.toggle('on', x === b)); legend(); applyFond();
});
const TYPES = [['tout', 'Tout'], ['station', 'Stations'], ['laiterie', 'Laiteries']];
$('types').innerHTML = TYPES.map(([k, l]) => `<button data-t="${k}" class="${k === state.type ? 'on' : ''}">${l}</button>`).join('');
$('types').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.type = b.dataset.t; [...$('types').children].forEach(x => x.classList.toggle('on', x === b)); render();
});
if (!D.has_type) $('bloc-types').style.display = 'none';
$('t-borders').addEventListener('change', e => { state.borders = e.target.checked; drawBorders(); });
$('t-hors').addEventListener('change', e => { state.hors = e.target.checked; render(); });
$('b-pistes').addEventListener('click', chercherPistes);
$('collapse').addEventListener('click', () => {
  document.body.classList.toggle('collapsed');
  $('collapse').setAttribute('aria-label', document.body.classList.contains('collapsed') ? 'Afficher le panneau' : 'Réduire le panneau');
});

// ── Feuille de détail ──
const TABS = [['proches', 'Stations'], ['pistes', 'Nouvelles pistes']].concat(HAS_PROD ? [['produit', 'Prix par produit']] : []);
$('tabs').innerHTML = TABS.map(([k, l]) => `<button data-t="${k}" class="${k === state.tab ? 'on' : ''}">${l}</button>`).join('');
$('tabs').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.tab = b.dataset.t; state.sort = { key: state.tab === 'produit' ? 'produit' : 'dist', dir: 1 };
  [...$('tabs').children].forEach(x => x.classList.toggle('on', x === b)); renderSheet();
});
$('chip').addEventListener('click', () => { document.body.classList.add('sheet-open'); renderSheet(); });
$('close').addEventListener('click', () => document.body.classList.remove('sheet-open'));
document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.activeElement !== $('q')) document.body.classList.remove('sheet-open'); });
$('filtre').addEventListener('input', () => { state.filtre = nn($('filtre').value); renderSheet(); });
$('tbl').addEventListener('click', e => {
  const th = e.target.closest('th[data-k]');
  if (th) { const k = th.dataset.k; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : 1 }; renderSheet(); return; }
  if (e.target.closest('a')) return;
  const tr = e.target.closest('tr[data-key]'); if (!tr) return;
  const m = mk[tr.dataset.key];
  const ll = tr.dataset.ll.split(',').map(Number);
  map.flyTo(ll, Math.max(map.getZoom(), 12), { duration: .6 });
  if (m) setTimeout(() => m.openPopup(), 650);
});

function statutBadge(s) {
  if (s.nb === 0) return '<span class="badge b-ann">Annuaire</span>';
  return s.statut && s.statut.includes('hors') ? '<span class="badge b-hors">Hors annuaire</span>' : '<span class="badge b-used">Utilisée</span>';
}
function tableau() {
  if (state.tab === 'pistes') {
    if (!state.center) return { vide: 'Choisissez d’abord une position.' };
    if (!state.pis) return { vide: 'Lancez « Chercher de nouvelles stations » dans le panneau.' };
    return {
      cols: [['nom', 'Station'], ['adresse', 'Adresse'], ['dist', 'Distance (km)', 'num', km], ['telephone', 'Téléphone'],
             ['site', 'Site', '', v => v ? `<a href="${esc(v)}" target="_blank" rel="noopener">Ouvrir</a>` : ''], ['source', 'Source']],
      rows: state.pis.map(p => ({ ...p, _key: 'p' + p.j })), vide: 'Aucune nouvelle station dans ce rayon. Élargissez le rayon.'
    };
  }
  if (state.tab === 'produit') {
    const base = state.center ? state.used : ST.filter(s => s.nb > 0 && vis(s));
    const ids = new Set(base.map(s => s.i)), parP = {};
    LAV.forEach(([si, prod, prix]) => { if (!ids.has(si)) return; ((parP[prod] ??= {})[si] ??= []).push(prix); });
    const stations = base.filter(s => Object.values(parP).some(o => o[s.i]));
    const rows = Object.keys(parP).map(prod => { const r = { produit: prod }; stations.forEach(s => r['s' + s.i] = parP[prod][s.i] ? median(parP[prod][s.i]) : null); return r; });
    return {
      cols: [['produit', 'Produit']].concat(stations.map(s => ['s' + s.i, s.nom, 'num', v => eur(v)])),
      rows, pivot: true, vide: 'Pas de lavage avec prix et produit identifiés dans cette zone.'
    };
  }
  const src = state.center ? state.proches : ST.filter(vis);
  return {
    cols: [['statut', 'Statut', '', (v, r) => statutBadge(r)]].concat(D.has_type
           ? [['type', 'Type', '', v => `<span style="color:${TYPE_C[v]};font-weight:600">${v === 'station' ? 'Station' : 'Laiterie'}</span>`]] : [])
           .concat([['nom', 'Lieu'], ['adresse', 'Adresse'], ['localite', 'Localité'], ['cp', 'CP'],
           ['dist', 'Distance (km)', 'num', km], ['nb', 'Lavages', 'num'], ['prix_med', 'Prix médian', 'num', v => eur(v)],
           ['prix_min', 'Min', 'num', v => eur(v)], ['prix_max', 'Max', 'num', v => eur(v)], ['dernier_prix', 'Dernier prix', 'num', v => eur(v)],
           ['dernier_lavage', 'Dernier lavage', '', dfr], ['telephone', 'Téléphone'], ['email', 'E-mail']]),
    rows: src.map(s => ({ ...s, _key: 's' + s.i })), vide: `Aucune station de la base dans un rayon de ${state.rayon} km.`
  };
}
function renderSheet() {
  const t = tableau();
  if (!t.rows || !t.rows.length) { $('tbl').innerHTML = `<div class="empty">${t.vide}</div>`; return; }
  let rows = t.rows;
  if (state.filtre) rows = rows.filter(r => nn(t.cols.map(([k]) => r[k] ?? '').join(' ')).includes(state.filtre));
  const { key, dir } = state.sort;
  if (t.cols.some(([k]) => k === key)) rows = rows.slice().sort((a, b) => {
    const x = a[key], y = b[key]; if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'fr')) * dir;
  });
  const th = t.cols.map(([k, l, cl]) => `<th data-k="${k}" class="${cl || ''}">${esc(l)}${k === key ? ` <span class="arr">${dir > 0 ? '↑' : '↓'}</span>` : ''}</th>`).join('');
  const body = rows.map(r => {
    let mn = null;
    if (t.pivot) { const v = t.cols.slice(1).map(([k]) => r[k]).filter(x => x != null); mn = v.length > 1 ? Math.min(...v) : null; }
    const tds = t.cols.map(([k, , cl, fmt]) => {
      const v = r[k], txt = fmt ? fmt(v, r) : esc(v ?? '');
      return `<td class="${cl || ''}${t.pivot && v != null && v === mn ? ' min' : ''}">${txt}</td>`;
    }).join('');
    return r._key ? `<tr class="click" data-key="${r._key}" data-ll="${r.lat},${r.lon}">${tds}</tr>` : `<tr>${tds}</tr>`;
  }).join('');
  $('tbl').innerHTML = `<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`;
}
$('export').addEventListener('click', () => {
  const t = tableau(); if (!t.rows || !t.rows.length) return;
  const data = t.rows.map(r => Object.fromEntries(t.cols.map(([k, l]) => [l, k === 'statut' ? (r.statut || '') : k === 'type' ? TYPE_L[r.type] : (k === 'dernier_lavage' ? dfr(r[k]) : (r[k] ?? ''))])));
  const nom = { proches: 'stations', pistes: 'nouvelles_pistes', produit: 'prix_par_produit' }[state.tab];
  if (window.XLSX) {
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data), nom.slice(0, 31));
    XLSX.writeFile(wb, `lavages_${nom}.xlsx`);
  } else {
    const cols = Object.keys(data[0]);
    const csv = '\ufeff' + [cols.join(';')].concat(data.map(r => cols.map(c => `"${String(r[c]).replace(/"/g, '""')}"`).join(';'))).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = `lavages_${nom}.csv`; a.click();
  }
});

// ── Démarrage ──
const nUsed = ST.filter(s => s.nb > 0).length;
$('facts').innerHTML = `<b>${ST.length}</b> stations sur la carte, dont <b>${nUsed}</b> déjà utilisées`
  + (D.has_annuaire ? ` et <b>${ST.length - nUsed}</b> de l’annuaire jamais utilisées` : '') + '.'
  + (D.non_geo ? `<br>${D.non_geo} station(s) non géocodée(s), absentes de la carte.` : '')
  + `<br>Base préparée le ${esc(D.generated)} dans le HUB.`;
majRayon(); legend(); applyFond();
if (ST.length) fitTo(L.latLngBounds(ST.map(s => [s.lat, s.lon])));
</script>
</body>
</html>
'''

# ─── Application carte plein écran ───────────────────────────────────────────
def _js_val(x):
    """Valeur pandas/numpy → valeur JSON propre (NaN/NaT → null)."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return round(float(x), 2)
    return x


def build_app_html(df_geo: pd.DataFrame, df_lav: pd.DataFrame, has_ann: bool, non_geo: int, borders,
                   has_type: bool = True) -> str:
    champs = ["nom", "type", "adresse", "cp", "localite", "pays", "telephone", "email", "nb", "prix_med", "prix_min",
              "prix_max", "dernier_prix", "dernier_lavage", "precision", "statut"]
    stations = []
    for r in df_geo[champs + ["lat", "lon"]].to_dict("records"):
        d = {c: _js_val(r[c]) for c in champs}
        d["nb"] = int(r["nb"])
        d["lat"], d["lon"] = round(float(r["lat"]), 6), round(float(r["lon"]), 6)
        stations.append(d)
    index_cle = {k: i for i, k in enumerate(df_geo["_cle"])}

    lavages = []
    if "Produit" in df_lav.columns:
        sel = df_lav[df_lav["_prix"].notna() & df_lav["Produit"].notna() & df_lav["_cle"].isin(index_cle)]
        lavages = [[index_cle[k], str(p), round(float(v), 2)] for k, p, v in zip(sel["_cle"], sel["Produit"], sel["_prix"])]

    payload = {
        "stations": stations, "lavages": lavages, "has_annuaire": has_ann, "has_type": bool(has_type), "non_geo": int(non_geo),
        "generated": datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    front = json.dumps(borders, separators=(",", ":")) if borders else "null"
    return APP_HTML.replace("__DATA__", data, 1).replace("__BORDERS__", front, 1)


def bouton_ouvrir(app_html: str):
    """Bouton qui ouvre la carte dans un nouvel onglet (page autonome, sans Streamlit autour)."""
    contenu = json.dumps(app_html).replace("</", "<\\/")
    components.html(f"""
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif; }}
  button {{ height: 48px; padding: 0 28px; border: none; border-radius: 980px; background: #0071e3; color: #fff;
           font: 500 17px -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif;
           cursor: pointer; transition: background .15s, transform .1s; }}
  button:hover {{ background: #0077ed; }}
  button:active {{ transform: scale(.98); }}
  p {{ margin: 10px 0 0 4px; font-size: 13px; color: #6e6e73; }}
</style>
<button id="ouvrir">Ouvrir la carte plein écran</button>
<p id="msg">S’ouvre dans un nouvel onglet.</p>
<script>
const PAGE = {contenu};
document.getElementById('ouvrir').addEventListener('click', () => {{
  const url = URL.createObjectURL(new Blob([PAGE], {{ type: 'text/html' }}));
  const w = window.open(url, '_blank');
  document.getElementById('msg').textContent = w
    ? 'Carte ouverte dans un nouvel onglet.'
    : 'Le navigateur a bloqué l’ouverture : autorisez les fenêtres pop-up pour le HUB, ou téléchargez la carte ci-dessous.';
}});
</script>
""", height=90)


# ─── Page de préparation ─────────────────────────────────────────────────────
ui.page("lavages", "Préparez la base des stations, puis ouvrez la carte en plein écran dans un nouvel onglet.")

st.markdown('<div class="ap-section">Fichiers</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1:
    lavages_file = st.file_uploader("Historique des lavages (obligatoire)", type=["xlsx", "xls"], key="lavages",
                                    help="liste_lavages : N° Dossier, Date, Nom 1, Localité, Code postal, Prix…")
    missions_file = st.file_uploader("Fichier CA CIT (facultatif)", type=["xlsx", "xls"], key="missions",
                                     help="Lié aux lavages par N° de dossier : suppléments = prix du lavage, "
                                          "et produit transporté")
with c2:
    annuaire_file = st.file_uploader("Adresses des stations (facultatif)", type=["xlsx", "xls"], key="annuaire",
                                     help="Annuaire : nom, adresse, CP, localité, téléphone…")
    ref_file = st.file_uploader("Base géocodée (facultatif)", type=["xlsx"], key="ref",
                                help="Export « base géocodée » : évite de regéocoder les stations")

if not lavages_file:
    st.caption("Chargez au minimum l’historique des lavages pour préparer la carte.")
    st.stop()

try:
    df_l_raw = load_excel(lavages_file.getvalue())
    df_m_raw = load_excel(missions_file.getvalue()) if missions_file else None
    df_a_raw = load_excel(annuaire_file.getvalue()) if annuaire_file else None
except Exception as e:
    st.error(f"Lecture impossible : {e}")
    st.stop()

manquantes = [c for c in ["Nom 1", "Localité", "Code postal"] if c not in df_l_raw.columns]
if manquantes:
    st.error(f"Colonnes manquantes dans l’historique des lavages : {', '.join(manquantes)}")
    st.stop()

df_ann = None
if df_a_raw is not None:
    detect = detect_colonnes(df_a_raw.columns)
    options = ["—"] + list(df_a_raw.columns)
    mapping = {}
    with st.expander("Colonnes de l’annuaire (détectées automatiquement, corrigez si besoin)",
                     expanded="nom" not in detect):
        cols = st.columns(3)
        for i, (champ, (lbl, _)) in enumerate(CHAMPS_ANNUAIRE.items()):
            defaut = detect.get(champ)
            v = cols[i % 3].selectbox(lbl, options, index=options.index(defaut) if defaut else 0, key=f"map_{champ}")
            mapping[champ] = None if v == "—" else v
        st.caption(f"{len(df_a_raw)} ligne(s) dans le fichier adresses.")
    if not mapping["nom"]:
        st.warning("Indiquez la colonne du nom de station pour fusionner l’annuaire.")
    elif not any(mapping[c] for c in ["cp", "localite", "adresse", "lat"]):
        st.warning("L’annuaire doit contenir un CP, une localité, une adresse ou des coordonnées.")
    else:
        df_ann = build_annuaire(df_a_raw, tuple(sorted(mapping.items())))

map_ca = None
if df_m_raw is not None:
    detect_ca = detect_colonnes(df_m_raw.columns, CHAMPS_CA)
    options_ca = ["—"] + list(df_m_raw.columns)
    m_ca = {}
    with st.expander("Colonnes du fichier CA (détectées automatiquement, corrigez si besoin)",
                     expanded=not {"dossier", "supplements"}.issubset(detect_ca)):
        cols = st.columns(3)
        for i, (champ, (lbl, _)) in enumerate(CHAMPS_CA.items()):
            defaut = detect_ca.get(champ)
            v = cols[i].selectbox(lbl, options_ca, index=options_ca.index(defaut) if defaut else 0, key=f"ca_{champ}")
            m_ca[champ] = None if v == "—" else v
        m_ca["regle"] = st.radio("Si un dossier a plusieurs lignes avec des suppléments", CA_REGLES,
                                 horizontal=True, key="ca_regle")
        st.caption(f"{len(df_m_raw)} ligne(s) dans le fichier CA.")
    if "N° Dossier" not in df_l_raw.columns:
        st.warning("Le fichier lavages n’a pas de colonne « N° Dossier » : impossible de le lier au CA.")
    elif not m_ca["dossier"]:
        st.warning("Indiquez la colonne du N° de dossier dans le fichier CA.")
    else:
        if not m_ca["supplements"]:
            st.caption("Sans colonne Suppléments, le fichier CA ne sert qu’au produit transporté.")
        map_ca = tuple(sorted(m_ca.items()))

df_lav = build_lavages(df_l_raw, df_m_raw, map_ca)
df_hist = build_stations(df_lav)
if df_hist.empty:
    st.error("Aucune station exploitable dans l’historique (colonne Nom 1 vide).")
    st.stop()
df_base = build_base(df_hist, df_ann)
has_ann = df_ann is not None

# ─── Géocodage (base géocodée > coordonnées annuaire > géocodage) ───────────
coords = st.session_state.setdefault("coords", {})

ref_sig = (ref_file.name, ref_file.size) if ref_file else None
if ref_file and st.session_state.get("ref_charge") != ref_sig:
    try:
        ref = load_excel(ref_file.getvalue())
        for _, r in ref.dropna(subset=["cle", "lat", "lon"]).iterrows():
            prec = r.get("precision")
            coords[r["cle"]] = (float(str(r["lat"]).replace(",", ".")), float(str(r["lon"]).replace(",", ".")),
                                prec if isinstance(prec, str) and prec else "référentiel")
        st.session_state["ref_charge"] = ref_sig
    except Exception as e:
        st.warning(f"Base géocodée ignorée ({e}). Colonnes attendues : cle, lat, lon, precision.")

for k, la, lo in df_base.loc[df_base["lat_ann"].notna() & df_base["lon_ann"].notna(),
                             ["_cle", "lat_ann", "lon_ann"]].itertuples(index=False):
    actuel = coords.get(k)
    if actuel is None or actuel[2] in ("localité", "échec", "station"):
        coords[k] = (float(la), float(lo), "annuaire")

regeo_fait = st.session_state.setdefault("regeo_fait", set())


def a_geocoder(r) -> bool:
    c = coords.get(r["_cle"])
    if c is None:
        return True
    return c[2] in ("localité", "échec") and bool(r["adresse"]) and r["_cle"] not in regeo_fait


todo = df_base[df_base.apply(a_geocoder, axis=1)]
if not todo.empty:
    bar = st.progress(0, text=f"Géocodage de {len(todo)} station(s). Une seule fois : exportez ensuite la base.")
    for i, (_, r) in enumerate(todo.iterrows()):
        res = geocode_station(r["nom"], r["localite"], r["cp"], r["pays"], r["adresse"])
        if res:
            coords[r["_cle"]] = res
        elif r["_cle"] not in coords:
            coords[r["_cle"]] = (np.nan, np.nan, "échec")
        regeo_fait.add(r["_cle"])
        bar.progress((i + 1) / len(todo), text=f"Géocodage {i + 1}/{len(todo)} : {r['nom']}")
    bar.empty()

df_base["lat"] = df_base["_cle"].map(lambda k: coords.get(k, (np.nan,) * 3)[0])
df_base["lon"] = df_base["_cle"].map(lambda k: coords.get(k, (np.nan,) * 3)[1])
df_base["precision"] = df_base["_cle"].map(lambda k: coords.get(k, (np.nan,) * 3)[2])
df_geo = df_base.dropna(subset=["lat", "lon"]).reset_index(drop=True)
non_geo = len(df_base) - len(df_geo)

# ─── Carte ───────────────────────────────────────────────────────────────────
try:
    frontieres = load_borders()
except Exception:
    frontieres = None

has_type = "Nom 2" in df_l_raw.columns
app_html = build_app_html(df_geo, df_lav, has_ann, non_geo, frontieres, has_type)

st.markdown('<div class="ap-section">Carte</div>', unsafe_allow_html=True)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Stations sur la carte", len(df_geo))
m2.metric("Déjà utilisées", int((df_geo["nb"] > 0).sum()))
m3.metric("Annuaire, jamais utilisées", int((df_geo["nb"] == 0).sum()) if has_ann else "—")
m4.metric("Non géocodées", non_geo)
if has_type:
    n_st = int(((df_geo["type"] == "station") & (df_geo["nb"] > 0)).sum())
    n_lt = int((df_geo["type"] == "laiterie").sum())
    st.caption(f"Parmi les lieux déjà utilisés : {n_st} station(s) de lavage (« Nom 2 » renseigné) "
               f"et {n_lt} laiterie(s) ou usine(s) (« Nom 2 » vide).")
else:
    st.caption("Pas de colonne « Nom 2 » dans le fichier lavages : impossible de distinguer stations et laiteries.")
st.write("")
bouton_ouvrir(app_html)
if frontieres is None:
    st.caption("Tracé des frontières indisponible pour le moment : la carte s’ouvre sans.")

base_out = df_base[["_cle", "statut", "type", "nom", "adresse", "cp", "localite", "pays", "telephone", "email",
                    "nb", "prix_med", "prix_min", "prix_max", "dernier_prix", "dernier_lavage",
                    "lat", "lon", "precision", "rapprochement", "nom_annuaire"]].rename(columns={"_cle": "cle"})
base_xls = base_out.copy()
base_xls["dernier_lavage"] = base_xls["dernier_lavage"].dt.date

d1, d2, _ = st.columns([1, 1, 1])
with d1:
    st.download_button("Télécharger la carte (HTML)", app_html.encode("utf-8"), file_name="carte_lavages_citernes.html",
                       mime="text/html", use_container_width=True)
with d2:
    st.download_button("Télécharger la base géocodée", excel_auto({"Base stations": base_xls}),
                       file_name="base_stations_lavage.xlsx", use_container_width=True,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.caption("Le fichier HTML s’ouvre dans n’importe quel navigateur, sans le HUB. "
           "Rechargez la base géocodée au prochain lancement : plus aucun géocodage à attendre.")

# ─── Contrôles qualité ───────────────────────────────────────────────────────
if map_ca and dict(map_ca).get("supplements"):
    st.markdown('<div class="ap-section">Prix des lavages</div>', unsafe_allow_html=True)
    src = df_lav["_prix_src"]
    via_ca = src.str.startswith("CA")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Prix issus du CA", int(via_ca.sum()))
    p2.metric("Prix du fichier lavages", int((src == "Fichier lavages").sum()))
    p3.metric("Sans prix", int((src == "").sum()))
    p4.metric("Répartis sur plusieurs lavages", int(src.str.contains("réparti").sum()))

    det = ["N° Dossier", "Date", "Nom 1", "Localité"]
    det = [c for c in det if c in df_lav.columns]
    ecarts = df_lav[via_ca & df_lav["_prix_lav"].notna() & ((df_lav["_prix"] - df_lav["_prix_lav"]).abs() > 1)]
    if not ecarts.empty:
        with st.expander(f"Écarts entre le CA et la colonne Prix du fichier lavages ({len(ecarts)})"):
            st.dataframe(ecarts[det + ["_prix", "_prix_lav", "_prix_src"]]
                         .rename(columns={"_prix": "Prix retenu (CA)", "_prix_lav": "Prix fichier lavages",
                                          "_prix_src": "Source"}),
                         hide_index=True, use_container_width=True)
    multi = df_lav[via_ca & ((df_lav["_nb_lav_dossier"] > 1) | (df_lav["_lignes_ca"] > 1))]
    if not multi.empty:
        with st.expander(f"Dossiers à vérifier : plusieurs lavages ou plusieurs lignes CA ({multi['_dos'].nunique()})"):
            st.dataframe(multi[det + ["_lignes_ca", "_nb_lav_dossier", "_sup_ca", "_prix"]]
                         .rename(columns={"_lignes_ca": "Lignes CA avec suppléments",
                                          "_nb_lav_dossier": "Lavages sur le dossier",
                                          "_sup_ca": "Suppléments CA", "_prix": "Prix retenu par lavage"})
                         .sort_values(det[0] if det else "Prix retenu par lavage"),
                         hide_index=True, use_container_width=True)
            st.caption("Les suppléments d’un dossier sont répartis à parts égales entre ses lavages. "
                       "Si un dossier contient d’autres suppléments que le lavage, le prix sera surestimé.")
    sans = df_lav[src == ""]
    if not sans.empty:
        with st.expander(f"Lavages sans prix ({len(sans)})"):
            st.dataframe(sans[det], hide_index=True, use_container_width=True)
            st.caption("Dossier absent du CA, ou suppléments vides / à zéro, et pas de prix dans le fichier lavages.")

if has_ann:
    st.markdown('<div class="ap-section">Rapprochement avec l’annuaire</div>', unsafe_allow_html=True)
    approchants = df_base[(df_base["rapprochement"].str.len() > 0) & (df_base["rapprochement"] != "exact")]
    hors_ann = df_base[df_base["statut"] == S_HIST]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Exacts", int((df_base["rapprochement"] == "exact").sum()))
    r2.metric("Approchants", len(approchants))
    r3.metric("Utilisées, absentes de l’annuaire", len(hors_ann))
    r4.metric("Annuaire, jamais utilisées", int((df_base["statut"] == S_ANN).sum()))
    if not approchants.empty:
        with st.expander(f"Rapprochements approchants à vérifier ({len(approchants)})"):
            st.dataframe(approchants[["nom", "nom_annuaire", "cp", "localite", "rapprochement"]]
                         .rename(columns={"nom": "Nom (historique)", "nom_annuaire": "Nom (annuaire)",
                                          "cp": "CP", "localite": "Localité", "rapprochement": "Type"}),
                         hide_index=True, use_container_width=True)
            st.caption("Si un rapprochement est faux, corrigez le nom ou le CP dans l’annuaire "
                       "pour qu’il corresponde au « Nom 1 » des lavages.")
    if not hors_ann.empty:
        with st.expander(f"Stations utilisées mais absentes de l’annuaire ({len(hors_ann)})"):
            st.dataframe(hors_ann[["nom", "cp", "localite", "pays", "nb", "dernier_lavage"]]
                         .sort_values("nb", ascending=False), hide_index=True, use_container_width=True,
                         column_config={"dernier_lavage": st.column_config.DateColumn("Dernier lavage",
                                                                                     format="DD/MM/YYYY")})

mixtes = df_base[df_base["type_mixte"] == True]
if has_type and not mixtes.empty:
    st.markdown('<div class="ap-section">Type de lieu</div>', unsafe_allow_html=True)
    with st.expander(f"Lieux classés à la fois avec et sans « Nom 2 » ({len(mixtes)})"):
        st.dataframe(mixtes[["nom", "cp", "localite", "nb", "nb_nom2"]]
                     .rename(columns={"nom": "Lieu", "cp": "CP", "localite": "Localité", "nb": "Lavages",
                                      "nb_nom2": "Dont avec « Nom 2 »"}),
                     hide_index=True, use_container_width=True)
        st.caption("Classés en station de lavage dès qu’au moins un lavage a un « Nom 2 ». "
                   "Complétez ou videz « Nom 2 » dans le fichier lavages pour corriger.")

echecs = base_out[base_out["precision"] == "échec"]
approx = base_out[base_out["precision"] == "localité"]
if not echecs.empty or not approx.empty:
    st.markdown('<div class="ap-section">Positions à vérifier</div>', unsafe_allow_html=True)
    if not echecs.empty:
        with st.expander(f"Non géocodées, absentes de la carte ({len(echecs)})"):
            st.dataframe(echecs[["nom", "adresse", "cp", "localite", "pays"]], hide_index=True, use_container_width=True)
    if not approx.empty:
        with st.expander(f"Placées au centre de la commune ({len(approx)})"):
            st.dataframe(approx[["nom", "adresse", "cp", "localite", "pays"]], hide_index=True, use_container_width=True)
    st.caption("Corrigez les lat/lon dans la base géocodée exportée, puis rechargez-la.")
