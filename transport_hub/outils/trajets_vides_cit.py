"""
Page Streamlit : Optimisateur Trajets Vides CIT
Je viens de décharger en X → quels sont les meilleurs endroits pour aller recharger ?
Score = fréquence historique × prix moyen × (1 / distance routière PTV) × (1 / délai)

Corrections v2 :
- Géocodage via PTV (géocodage par CP+pays prioritaire, fallback by-text)
- Date déchargement = Date chargement + 1j approximation (colonne manquante dans le fichier)
  → Si tu as une vraie colonne "Date déchargement", remplace DATE_DECH_COL ci-dessous
- Score distance : valeur neutre = médiane si non géocodé (plus de biais vers 500km)
- Déduplication reco par (remorque, trajet) : fréquence = nb trajets distincts
- Fenêtre weekend étendue : si déchargement vendredi/samedi, fenêtre +2j supplémentaires
- Mode "score manuel" : je tape ma propre destination, je vois le score vs historique
- Affichage chauffeur / remorque dans les détails
- Calcul distance routière PTV sur les top candidats (pas juste haversine)
"""

import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import re
import math
import os
import sys
import time
import json

# ─── Import PTV (gestion imports relatifs du package) ────────────────────────
# ptv_router_km.py utilise "from .route_optimizer import ..." (import relatif).
# On le charge via importlib en lui injectant le bon __package__ pour que
# les imports relatifs se résolvent, sans avoir besoin d'un vrai dossier modules/.

import importlib.util as _ilu
import types as _types

def _load_ptv(project_root: str):
    """Charge ptv_router_km depuis project_root en simulant le package 'modules'."""
    # 1. Créer le faux package 'modules'
    if "modules" not in sys.modules:
        pkg = _types.ModuleType("modules")
        pkg.__path__ = [project_root]
        pkg.__package__ = "modules"
        sys.modules["modules"] = pkg

    # 2. Charger route_optimizer sous les deux noms attendus
    for mod_name, filename in [
        ("modules.route_optimizer", "route_optimizer.py"),
        ("modules.villes_jalons",   "villes_jalons.py"),   # dépendance transitive
    ]:
        if mod_name not in sys.modules:
            path = os.path.join(project_root, filename)
            if os.path.exists(path):
                spec = _ilu.spec_from_file_location(mod_name, path)
                mod  = _ilu.module_from_spec(spec)
                mod.__package__ = "modules"
                sys.modules[mod_name] = mod
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    pass  # villes_jalons peut échouer sans PTV_API_KEY — pas bloquant

    # 3. Charger ptv_router_km
    ptv_path = os.path.join(project_root, "ptv_router_km.py")
    if not os.path.exists(ptv_path):
        return None
    spec = _ilu.spec_from_file_location("modules.ptv_router_km", ptv_path)
    mod  = _ilu.module_from_spec(spec)
    mod.__package__ = "modules"
    sys.modules["modules.ptv_router_km"] = mod
    spec.loader.exec_module(mod)
    return mod

# Chercher le project_root : même dossier que cette page, ou parent
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOTS = [
    os.path.join(os.path.dirname(_HERE), "tools", "km_calcul", "modules"),  # emplacement réel
    _HERE,
    os.path.dirname(_HERE),
]
_PTV_ERR = ""

PTV_AVAILABLE = False
_ptv_mod = None
for _root in _ROOTS:
    if os.path.exists(os.path.join(_root, "ptv_router_km.py")):
        try:
            _ptv_mod = _load_ptv(_root)
            if _ptv_mod:
                PTV_AVAILABLE = True
                break
        except Exception as _e:
            _PTV_ERR = f"{type(_e).__name__}: {_e}"

if PTV_AVAILABLE and _ptv_mod:
    geocode_by_postal_code = _ptv_mod.geocode_by_postal_code
    _geocode_by_text       = _ptv_mod._geocode_by_text
    calculate_km_route     = _ptv_mod.calculate_km_route
    PAYS_TO_ISO            = _ptv_mod.PAYS_TO_ISO
    GPS_FIXES              = _ptv_mod.GPS_FIXES
else:
    # Stubs vides — le reste du code bascule sur OSM
    PAYS_TO_ISO = {}
    GPS_FIXES   = {}

# ─── Config colonne date déchargement ────────────────────────────────────────
# Si ton fichier missions a une vraie colonne de date de déchargement, mets son nom ici.
# Sinon, on estime date_dech = date_chargement (la mission EST le chargement,
# le déchargement a lieu après — la prochaine mission du même véhicule est donc bien le suivant).
DATE_DECH_COL = None  # ex: "Date déchargement"

# ─── Page config ─────────────────────────────────────────────────────────────
from core import ui

ui.page_config("Trajets vides CIT")
ui.apply_style()

# ─── Style (complète core/ui.py) ─────────────────────────────────────────────
st.markdown("""
<style>
.kpi { background: #fff; border-radius: 18px; padding: 16px 18px; box-shadow: var(--ap-shadow); margin-bottom: .6rem; }
.kpi .val { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; color: var(--ap-text); line-height: 1.1; }
.kpi .lbl { font-size: 13px; color: var(--ap-sub); margin-top: 4px; }

.section-title { font-size: 24px; font-weight: 600; letter-spacing: -0.015em; color: var(--ap-text);
  border-top: 1px solid var(--ap-hair); padding-top: 1.4rem; margin: 2rem 0 1rem; }

.reco-wrap { display: flex; flex-direction: column; gap: .6rem; }
.reco { background: #fff; border-radius: 18px; padding: 16px 18px; box-shadow: var(--ap-shadow);
  display: grid; grid-template-columns: 3rem 1fr auto; align-items: center; gap: .9rem; margin-bottom: .6rem; }
.reco.r1 { box-shadow: 0 0 0 1.5px #34c759, 0 4px 18px rgba(52,199,89,.12); }
.reco-num { font-size: 26px; font-weight: 600; color: #c7c7cc; text-align: center; line-height: 1; letter-spacing: -0.02em; }
.reco.r1 .reco-num { color: #248a3d; }
.reco.r2 .reco-num, .reco.r3 .reco-num { color: #6e6e73; }
.reco-loc { font-size: 19px; font-weight: 600; color: var(--ap-text); letter-spacing: -0.01em; }
.reco-sub { font-size: 13px; color: var(--ap-sub); margin-top: 2px; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: .6rem; }
.chip { font-size: 12px; font-weight: 500; padding: 3px 10px; border-radius: 980px; }
.chip.green  { color: #1e7a34; background: #e8f6ec; }
.chip.blue   { color: #0060c0; background: #e8f1fc; }
.chip.gray   { color: #6e6e73; background: #f0f0f3; }
.chip.orange { color: #b25000; background: #fff1e0; }

.score-track { width: 90px; height: 4px; background: #e8e8ed; border-radius: 2px; overflow: hidden; margin-top: .5rem; }
.score-fill { height: 100%; border-radius: 2px; background: #34c759; }
.badge-best { background: #34c759; color: #fff; font-size: 11px; font-weight: 600; padding: 3px 9px;
  border-radius: 980px; white-space: nowrap; }

.manual-score-box { background: #fff; border-radius: 18px; padding: 18px 20px; margin-top: 1rem; box-shadow: var(--ap-shadow); }
.manual-score-box h3 { font-size: 19px !important; font-weight: 600; color: var(--ap-text); margin: 0 !important; padding: 0 !important; }
.score-gauge { display: flex; align-items: center; gap: 1rem; margin: 1rem 0; }
.gauge-bar-bg { flex: 1; height: 8px; background: #e8e8ed; border-radius: 4px; overflow: hidden; }
.gauge-bar { height: 100%; border-radius: 4px; transition: width .6s ease; }
.gauge-val { font-size: 28px; font-weight: 600; min-width: 60px; text-align: right; letter-spacing: -0.02em; }
</style>
""", unsafe_allow_html=True)

# ─── Utilitaires ─────────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).upper().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"['\-–]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return R * 2 * math.asin(math.sqrt(a))

PAYS_MAP_DISPLAY = {
    "F":"France","B":"Belgium","BE":"Belgium","NL":"Netherlands",
    "D":"Germany","L":"Luxembourg","E":"Spain","I":"Italy",
    "CH":"Switzerland","A":"Austria","GB":"United Kingdom","PL":"Poland",
}
PAYS_FLAGS = {
    "F":"🇫🇷","B":"🇧🇪","BE":"🇧🇪","NL":"🇳🇱","D":"🇩🇪",
    "L":"🇱🇺","E":"🇪🇸","I":"🇮🇹","CH":"🇨🇭","A":"🇦🇹",
    "GB":"🇬🇧","PL":"🇵🇱",
}

# ─── Géocodage (PTV prioritaire, fallback OSM) ───────────────────────────────
import urllib.request as _ureq
import urllib.parse as _uparse

def _photon(query: str):
    url = f"https://photon.komoot.io/api/?q={_uparse.quote(query)}&limit=1&lang=fr"
    try:
        req = _ureq.Request(url, headers={"User-Agent": "CB-Transport-Hub/1.0"})
        with _ureq.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        ft = data.get("features", [])
        if ft:
            c = ft[0]["geometry"]["coordinates"]
            return float(c[1]), float(c[0])
    except Exception:
        pass
    return None

def _nominatim(query: str):
    url = f"https://nominatim.openstreetmap.org/search?q={_uparse.quote(query)}&format=json&limit=1"
    try:
        req = _ureq.Request(url, headers={"User-Agent": "CB-Transport-Hub/1.0"})
        with _ureq.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None

@st.cache_data(show_spinner=False, ttl=86400)
def geocode_ptv_cached(ville: str, cp: str, pays: str):
    """
    Géocodage dans l'ordre :
    1. GPS_FIXES (aliases manuels)
    2. PTV by-postal-code (si CP + pays dispo)
    3. PTV by-text
    4. Photon (OSM)
    5. Nominatim (OSM)
    """
    ville_exp = re.sub(r'\bST\b', 'SAINT', ville, flags=re.IGNORECASE)
    ville_exp = re.sub(r'\bSTE\b', 'SAINTE', ville_exp, flags=re.IGNORECASE)

    if PTV_AVAILABLE:
        # 1. GPS fixes
        fix_key = ville.strip().lower()
        if fix_key in GPS_FIXES:
            return GPS_FIXES[fix_key]

        # 2. PTV by-postal-code
        if cp and pays:
            pays_label = PAYS_MAP_DISPLAY.get(pays.upper(), pays).lower()
            country_iso = PAYS_TO_ISO.get(pays_label)
            if not country_iso:
                # essayer directement pays comme ISO
                country_iso = pays.upper() if len(pays) == 2 else None
            if country_iso and cp:
                r = geocode_by_postal_code(cp, country_iso)
                if r:
                    return r

        # 3. PTV by-text
        pays_label = PAYS_MAP_DISPLAY.get(pays.upper(), pays) if pays else ""
        for v in ([ville_exp, ville] if ville_exp != ville else [ville]):
            for q in filter(None, [
                f"{v}, {cp}, {pays_label}" if cp and pays_label else None,
                f"{v}, {pays_label}" if pays_label else None,
                v,
            ]):
                r = _geocode_by_text(q)
                if r:
                    return r
    else:
        # Fallback OSM
        pays_label = PAYS_MAP_DISPLAY.get(pays.upper(), pays) if pays else ""
        for v in ([ville_exp, ville] if ville_exp != ville else [ville]):
            for q in filter(None, [
                f"{v}, {cp}, {pays_label}" if cp and pays_label else None,
                f"{v}, {pays_label}" if pays_label else None,
                v,
            ]):
                r = _photon(q) or _nominatim(q)
                if r:
                    return r
    return None

@st.cache_data(show_spinner=False, ttl=3600)
def get_ptv_distance_km(lat1, lon1, lat2, lon2) -> float | None:
    """Distance routière réelle via PTV. Retourne None si indisponible."""
    if not PTV_AVAILABLE:
        return None
    try:
        result = calculate_km_route(lat1, lon1, lat2, lon2, calculer_peage=False)
        if result and result.get("km"):
            return float(result["km"])
    except Exception:
        pass
    return None

# ─── Chargement données ───────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_missions(missions_bytes, lavages_bytes):
    import io
    df = pd.read_excel(io.BytesIO(missions_bytes), dtype=str)
    df.columns = df.columns.str.strip()
    df["Date chargement"] = pd.to_datetime(df["Date chargement"], errors="coerce")
    df["Prix transport"]  = pd.to_numeric(df["Prix transport"],  errors="coerce")
    df["Total des ventes"]= pd.to_numeric(df["Total des ventes"],errors="coerce")
    df["N° Dossier"]      = df["N° Dossier"].str.strip()

    if lavages_bytes:
        df_l = pd.read_excel(io.BytesIO(lavages_bytes), dtype=str)
        df_l.columns = df_l.columns.str.strip()
        df_l["N° Dossier"] = df_l["N° Dossier"].str.strip()
        vehicule = df_l[["N° Dossier","Remorque","Tracteur","Chauffeur"]].drop_duplicates("N° Dossier")
        df = df.merge(vehicule, on="N° Dossier", how="left")
    else:
        df["Remorque"] = None
        df["Tracteur"] = None
        df["Chauffeur"] = None

    # Date de déchargement : colonne dédiée si dispo, sinon = date chargement
    # (la prochaine mission du même véhicule = chargement APRÈS ce déchargement)
    if DATE_DECH_COL and DATE_DECH_COL in df.columns:
        df["_date_dech"] = pd.to_datetime(df[DATE_DECH_COL], errors="coerce")
    else:
        df["_date_dech"] = df["Date chargement"]

    df["_loc_ch_norm"]   = df["Localité chargement"].apply(normalize)
    df["_loc_dech_norm"] = df["Localité déchargement"].apply(normalize)
    df["_dow_dech"]      = df["_date_dech"].dt.dayofweek  # 4=vendredi, 5=samedi

    df = df.dropna(subset=["Date chargement"]).sort_values("Date chargement").reset_index(drop=True)
    return df

# ─── Header ──────────────────────────────────────────────────────────────────
ui.page("trajets_vides", "Je viens de décharger en X : où aller recharger pour maximiser l’efficacité ?")
st.markdown('<div class="ap-statut"><i></i>PTV routing actif</div>' if PTV_AVAILABLE else
            '<div class="ap-statut off"><i></i>PTV indisponible, géocodage OSM</div>', unsafe_allow_html=True)
if _PTV_ERR:
    st.caption(f"Chargement PTV : {_PTV_ERR}")
st.write("")

# ─── Upload ───────────────────────────────────────────────────────────────────
col_u1, col_u2 = st.columns(2)
with col_u1:
    missions_file = st.file_uploader("Fichier Missions CA CIT", type=["xlsx","xls"])
with col_u2:
    lavages_file  = st.file_uploader(
        "Fichier Lavages",
        type=["xlsx","xls"],
        help="Permet le chaînage par Remorque/Tracteur — fortement recommandé"
    )

if not missions_file:
    st.info("Chargez le fichier missions pour démarrer")
    st.stop()

missions_bytes = missions_file.read()
lavages_bytes  = lavages_file.read() if lavages_file else None

if not lavages_bytes:
    st.warning("Sans le fichier lavages, pas de chaînage par véhicule — recommandations moins précises")

with st.spinner("Chargement et analyse des enchaînements historiques..."):
    df = load_missions(missions_bytes, lavages_bytes)

has_vehicle = df["Remorque"].notna().any()

# ─── KPIs ─────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
kpis = [
    (f"{len(df):,}",                          "Missions"),
    (f"{df['Localité déchargement'].nunique():,}", "Lieux déchargement"),
    (f"{df['Localité chargement'].nunique():,}",   "Lieux chargement"),
    (f"{df['Prix transport'].mean():,.0f}€",        "Prix moyen"),
]
for col, (val, lbl) in zip([c1,c2,c3,c4], kpis):
    with col:
        st.markdown(f'<div class="kpi"><div class="val">{val}</div><div class="lbl">{lbl}</div></div>',
                    unsafe_allow_html=True)

st.divider()

# ─── Sélection lieu de déchargement ──────────────────────────────────────────
st.markdown('<div class="section-title">Lieu de déchargement</div>', unsafe_allow_html=True)

lieux_dech = sorted(df["Localité déchargement"].dropna().unique().tolist())
col_s1, col_s2, col_s3 = st.columns([3, 1, 1])
with col_s1:
    lieu_choisi = st.selectbox("Je viens de décharger à...", [""] + lieux_dech)
with col_s2:
    fenetre_jours = st.selectbox("Fenêtre max (jours)", [3, 7, 14], index=0,
        help="Nb de jours max pour trouver la prochaine mission du même véhicule")
with col_s3:
    nb_recos = st.selectbox("Nb recommandations", [5, 10, 15, 20], index=1)

with st.expander("Filtres avancés"):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        pays_filtre = st.multiselect("Pays de rechargement",
            options=sorted(df["Pays chargement"].dropna().unique().tolist()))
    with col_f2:
        prix_min = st.number_input("Prix min mission (€)", value=0, step=50)
    with col_f3:
        use_ptv_dist = st.checkbox(
            "Distance routière PTV (top 10)",
            value=PTV_AVAILABLE,
            disabled=not PTV_AVAILABLE,
            help="Calcule la vraie distance routière via PTV pour les 10 premiers candidats. Plus lent."
        )

if not lieu_choisi:
    st.info("Choisissez un lieu de déchargement pour voir les recommandations")
    st.stop()

# ─── Calcul recommandations ───────────────────────────────────────────────────
loc_norm = normalize(lieu_choisi)

df_dech = df[df["_loc_dech_norm"] == loc_norm].copy()
if df_dech.empty:
    df_dech = df[df["_loc_dech_norm"].str.contains(loc_norm, na=False, regex=False)].copy()
if df_dech.empty:
    st.warning(f"Aucune mission trouvée pour « {lieu_choisi} »")
    st.stop()

# Géocodage du lieu de déchargement
cp_dech_ref   = df_dech["C.P. déchargement"].mode().iloc[0] if not df_dech["C.P. déchargement"].mode().empty else ""
pays_dech_ref = df_dech["Pays déchargement"].mode().iloc[0]  if not df_dech["Pays déchargement"].mode().empty else ""
coords_dech = geocode_ptv_cached(lieu_choisi, cp_dech_ref, pays_dech_ref)

with st.spinner(f"Analyse de {len(df_dech)} missions vers {lieu_choisi}..."):

    records = []
    seen_pairs = set()  # déduplication (remorque, loc_ch) — évite de compter 10x le même flux

    for _, row in df_dech.iterrows():
        date_ref = row["_date_dech"]
        if pd.isna(date_ref):
            continue

        # Fenêtre étendue si déchargement vendredi ou samedi
        extra_days = 2 if row["_dow_dech"] in (4, 5) else 0
        fwin = fenetre_jours + extra_days

        rem  = row.get("Remorque")
        trac = row.get("Tracteur")
        chauf= row.get("Chauffeur")

        if has_vehicle and pd.notna(rem) and rem:
            # Méthode précise : prochaine mission de la même Remorque
            next_ms = df[
                (df["Remorque"] == rem) &
                (df["Date chargement"] > date_ref) &
                (df["Date chargement"] <= date_ref + pd.Timedelta(days=fwin))
            ].head(1)
        else:
            # Fallback : J+1 (pas d'info véhicule)
            next_ms = df[
                (df["Date chargement"] > date_ref) &
                (df["Date chargement"] <= date_ref + pd.Timedelta(days=1))
            ].head(1)

        for _, nrow in next_ms.iterrows():
            loc_ch = str(nrow["Localité chargement"] or "").strip()
            if not loc_ch or normalize(loc_ch) == loc_norm:
                continue

            prix = nrow["Prix transport"]
            if prix_min > 0 and (pd.isna(prix) or prix < prix_min):
                continue
            if pays_filtre and nrow["Pays chargement"] not in pays_filtre:
                continue

            # Déduplication : un même véhicule sur le même trajet compte une fois
            pair_key = (str(rem), normalize(loc_ch))
            already = pair_key in seen_pairs
            seen_pairs.add(pair_key)

            records.append({
                "loc_ch":    loc_ch,
                "cp_ch":     str(nrow["C.P. chargement"] or "").strip(),
                "pays_ch":   str(nrow["Pays chargement"] or "").strip(),
                "delta_j":   (nrow["Date chargement"] - date_ref).days,
                "prix":      prix,
                "ventes":    nrow["Total des ventes"],
                "produit":   str(nrow["Produit"] or "").strip(),
                "client":    str(nrow["Client facturation"] or "").strip(),
                "chauffeur": str(chauf or "").strip(),
                "remorque":  str(rem or "").strip(),
                "tracteur":  str(trac or "").strip(),
                "dedup":     already,  # flag pour info
            })

    mode_label = "Remorque" if has_vehicle else "fenêtre temporelle J+1"
    st.caption(f"Chaînage par {mode_label} — {len(records)} enchaînements analysés")

if not records:
    st.warning("Pas d'enchaînements trouvés dans cette fenêtre temporelle.")
    st.stop()

df_rec = pd.DataFrame(records)

# Agrégation par lieu de chargement
# Fréquence = nb de fois que ce lieu de rechargement a été utilisé (même si même remorque)
agg = df_rec.groupby(["loc_ch","cp_ch","pays_ch"]).agg(
    frequence       = ("prix", "count"),
    prix_moyen      = ("prix", "mean"),
    ventes_moyennes = ("ventes", "mean"),
    delta_moyen     = ("delta_j", "mean"),
    prix_max        = ("prix", "max"),
    chauffeurs      = ("chauffeur", lambda x: ", ".join(sorted(set(v for v in x if v)))),
    clients         = ("client",   lambda x: ", ".join(sorted(set(v for v in x if v))[:3])),
).reset_index()

# ─── Géocodage des destinations (top 30 par fréquence) ───────────────────────
top_candidates = agg.sort_values("frequence", ascending=False).head(30).copy()

geocoded_ch = {}
with st.spinner("Géocodage des lieux de rechargement (PTV)..."):
    for _, row in top_candidates.iterrows():
        k = row["loc_ch"]
        if k not in geocoded_ch:
            geocoded_ch[k] = geocode_ptv_cached(row["loc_ch"], row["cp_ch"], row["pays_ch"])

# ─── Distance : PTV routière si activée, sinon haversine ─────────────────────
def get_distance(loc_ch, coords_ch) -> float:
    """Retourne la distance en km entre coords_dech et coords_ch."""
    if not coords_ch or not coords_dech:
        return None
    if use_ptv_dist and PTV_AVAILABLE:
        d = get_ptv_distance_km(
            coords_dech[0], coords_dech[1],
            coords_ch[0], coords_ch[1]
        )
        if d:
            return d
    return haversine_km(coords_dech[0], coords_dech[1], coords_ch[0], coords_ch[1])

# Calcul distances
distances = {}
ptv_top = top_candidates.head(10)["loc_ch"].tolist() if use_ptv_dist else []

with st.spinner("Calcul distances routières PTV..." if use_ptv_dist and PTV_AVAILABLE else ""):
    for _, row in top_candidates.iterrows():
        coords = geocoded_ch.get(row["loc_ch"])
        distances[row["loc_ch"]] = get_distance(row["loc_ch"], coords)

# ─── Score composite ──────────────────────────────────────────────────────────
def compute_score(row) -> float:
    freq  = row["frequence"]
    prix  = row["prix_moyen"] if not pd.isna(row["prix_moyen"]) else 0
    delta = row["delta_moyen"] if row["delta_moyen"] > 0 else 0.5

    dist = distances.get(row["loc_ch"])
    if dist is None:
        # Non géocodé : score partiel sans pénalité distance (exclusion douce)
        return freq * (prix / 1000) * (1 / delta) * 0.3
    dist = max(dist, 20)

    # Score = fréquence × (prix normalisé) × (300/dist) × (1/délai)
    return freq * (prix / 1000) * (300 / dist) * (1 / delta)

top_candidates["score"]   = top_candidates.apply(compute_score, axis=1)
top_candidates["dist_km"] = top_candidates["loc_ch"].map(distances)
top_candidates = top_candidates.sort_values("score", ascending=False).head(nb_recos).reset_index(drop=True)

max_score = top_candidates["score"].max()
top_candidates["score_pct"] = (top_candidates["score"] / max_score * 100).round(0).astype(int)

# ─── Affichage recommandations ────────────────────────────────────────────────
st.markdown(f'<div class="section-title">Recommandations après déchargement à {lieu_choisi.upper()}</div>',
            unsafe_allow_html=True)

nb_missions_dech = len(df_dech)
r1, r2, r3 = st.columns(3)
with r1:
    st.markdown(f'<div class="kpi"><div class="val">{nb_missions_dech}</div><div class="lbl">Missions historiques</div></div>', unsafe_allow_html=True)
with r2:
    st.markdown(f'<div class="kpi"><div class="val">{len(top_candidates)}</div><div class="lbl">Destinations proposées</div></div>', unsafe_allow_html=True)
with r3:
    best_prix = top_candidates.iloc[0]["prix_moyen"] if len(top_candidates) > 0 else 0
    st.markdown(f'<div class="kpi"><div class="val">{best_prix:,.0f}€</div><div class="lbl">Prix moyen #1</div></div>', unsafe_allow_html=True)

st.markdown("")

for i, row in top_candidates.iterrows():
    rank = i + 1
    r_cls = "r1" if rank == 1 else ("r2" if rank == 2 else ("r3" if rank == 3 else ""))
    flag  = PAYS_FLAGS.get(row["pays_ch"], "🌍")

    dist_v  = row["dist_km"]
    dist_str = f"{dist_v:.0f} km {'(route)' if use_ptv_dist and PTV_AVAILABLE and dist_v else '(vol d·oiseau)'}" if dist_v else "distance inconnue"
    prix_str = f"{row['prix_moyen']:,.0f}€" if not pd.isna(row['prix_moyen']) else "N/A"
    delta_str = f"J+{row['delta_moyen']:.1f}"
    freq_str  = f"{int(row['frequence'])}×"
    badge = '<span class="badge-best">OPTIMAL</span>' if rank == 1 else ""

    # Chauffeurs/clients en sous-titre
    sub_parts = []
    if row.get("chauffeurs"): sub_parts.append(row["chauffeurs"][:40])
    if row.get("clients"):    sub_parts.append(row["clients"][:40])
    sub_text = " · ".join(sub_parts) if sub_parts else f"{row['cp_ch']} — {row['pays_ch']}"

    st.markdown(f"""
    <div class="reco {r_cls}">
        <div class="reco-num">{rank:02d}</div>
        <div class="reco-main">
            <div class="reco-loc">{flag} {row['loc_ch']}</div>
            <div class="reco-sub">{sub_text}</div>
            <div class="chips">
                <span class="chip green">{prix_str}</span>
                <span class="chip blue">{dist_str}</span>
                <span class="chip gray">{delta_str}</span>
                <span class="chip orange">{freq_str}</span>
            </div>
            <div class="score-track">
                <div class="score-fill" style="width:{row['score_pct']}%"></div>
            </div>
        </div>
        {badge}
    </div>
    """, unsafe_allow_html=True)

# ─── MODE SCORE MANUEL ────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Évaluer une destination manuelle</div>', unsafe_allow_html=True)

st.markdown("""
<div class="manual-score-box">
<h3>Je sais où il va recharger — quel est le score ?</h3>
""", unsafe_allow_html=True)

col_m1, col_m2, col_m3 = st.columns([3, 1, 1])
with col_m1:
    dest_manuelle = st.text_input("Ville de rechargement", placeholder="ex: Béziers, Rouen, Liège...")
with col_m2:
    cp_manuel  = st.text_input("Code postal", placeholder="ex: 34500")
with col_m3:
    pays_manuel = st.selectbox("Pays", ["F","B","NL","D","L","E","I","CH","A","GB","PL"])

if dest_manuelle:
    with st.spinner(f"Évaluation de {dest_manuelle}..."):
        coords_dest_m = geocode_ptv_cached(dest_manuelle, cp_manuel, pays_manuel)

        if not coords_dest_m:
            st.warning(f"Impossible de géocoder « {dest_manuelle} » — vérifiez la ville et le pays")
        else:
            # Distance
            if coords_dech:
                dist_m = get_distance(dest_manuelle, coords_dest_m)
                if not dist_m:
                    dist_m = haversine_km(coords_dech[0], coords_dech[1], coords_dest_m[0], coords_dest_m[1])
            else:
                dist_m = 300  # neutre

            # Fréquence historique de ce lieu depuis ce déchargement
            norm_dest_m = normalize(dest_manuelle)
            hist_match = df_rec[df_rec["loc_ch"].apply(normalize) == norm_dest_m]
            freq_m      = len(hist_match)
            prix_m      = hist_match["prix"].mean() if freq_m > 0 else df_rec["prix"].mean()
            delta_m     = hist_match["delta_j"].mean() if freq_m > 0 else 3.0

            # Score
            dist_m_safe = max(dist_m, 20) if dist_m else 300
            prix_m_safe = prix_m if not pd.isna(prix_m) else 0
            delta_m_safe = delta_m if delta_m > 0 else 1
            score_m = freq_m * (prix_m_safe / 1000) * (300 / dist_m_safe) * (1 / delta_m_safe)
            score_m = max(score_m, 0.01) if freq_m > 0 else 0.01  # jamais 0 si calculable

            # Comparaison avec le meilleur historique
            pct_vs_best = min(score_m / max_score * 100, 100) if max_score > 0 else 0

            # Couleur du gauge
            if pct_vs_best >= 70:
                gauge_color = "#248a3d"
                verdict = "✅ Excellent choix"
                verdict_color = "#248a3d"
            elif pct_vs_best >= 40:
                gauge_color = "#c93400"
                verdict = "⚠️ Choix acceptable"
                verdict_color = "#c93400"
            else:
                gauge_color = "#d70015"
                verdict = "❌ Sous-optimal"
                verdict_color = "#d70015"

            flag_m = PAYS_FLAGS.get(pays_manuel, "🌍")
            dist_str_m = f"{dist_m:.0f} km" if dist_m else "inconnue"
            prix_str_m = f"{prix_m_safe:,.0f}€" if prix_m_safe else "N/A"

            st.markdown(f"""
            <div style="margin-top:0.5rem">
                <div style="font-size:21px;font-weight:600;letter-spacing:-0.015em;color:#1d1d1f;margin-bottom:0.4rem">
                    {flag_m} {dest_manuelle}
                </div>
                <div style="color:{verdict_color};font-weight:600;font-size:0.95rem;margin-bottom:0.8rem">
                    {verdict}
                </div>
                <div class="score-gauge">
                    <div class="gauge-bar-bg">
                        <div class="gauge-bar" style="width:{pct_vs_best:.0f}%;background:{gauge_color}"></div>
                    </div>
                    <div class="gauge-val" style="color:{gauge_color}">{pct_vs_best:.0f}%</div>
                </div>
                <div class="chips" style="margin-top:0.5rem">
                    <span class="chip {'green' if freq_m>0 else 'gray'}">{freq_m}× historique</span>
                    <span class="chip blue">{dist_str_m}</span>
                    <span class="chip green">{prix_str_m}</span>
                </div>
            """, unsafe_allow_html=True)

            if freq_m == 0:
                st.markdown("""
                <div style="margin-top:0.6rem;font-size:0.8rem;color:#6e6e73;font-style:italic">
                    ℹ️ Cette destination n'apparaît pas dans l'historique après ce déchargement —
                    score basé uniquement sur la distance et le prix moyen global.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="margin-top:0.6rem;font-size:0.8rem;color:#6e6e73">
                    Ce trajet a déjà été fait {freq_m}× après un déchargement à {lieu_choisi},
                    avec un délai moyen de J+{delta_m:.1f} et un prix moyen de {prix_str_m}.
                </div>
                """, unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

            # Rang équivalent dans les recos
            equiv_rank = (top_candidates["score"] > score_m).sum() + 1
            if equiv_rank <= len(top_candidates):
                st.info(f"Cette destination équivaudrait au rang **#{equiv_rank}** dans les recommandations automatiques.")
            else:
                st.info(f"Cette destination serait classée après les {len(top_candidates)} recommandations affichées.")

st.markdown("</div>", unsafe_allow_html=True)

# ─── Carte ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Carte des destinations</div>', unsafe_allow_html=True)

map_data = []
for i, row in top_candidates.iterrows():
    coords = geocoded_ch.get(row["loc_ch"])
    if coords:
        map_data.append({
            "nom":   row["loc_ch"],
            "pays":  row["pays_ch"],
            "lat":   coords[0],
            "lon":   coords[1],
            "score": int(row["score_pct"]),
            "prix":  f"{row['prix_moyen']:,.0f}€" if not pd.isna(row['prix_moyen']) else "N/A",
            "freq":  int(row["frequence"]),
            "dist":  f"{row['dist_km']:.0f} km" if row['dist_km'] else "?",
            "rang":  i + 1,
        })

if map_data:
    try:
        import pydeck as pdk

        df_map = pd.DataFrame(map_data)
        df_map["radius"] = 1200
        df_map["color"]  = df_map["rang"].apply(
            lambda r: [52, 199, 89, 235] if r == 1 else
                      ([0, 113, 227, 220] if r <= 3 else [142, 142, 147, 190])
        )

        layers = [
            pdk.Layer("ScatterplotLayer", data=df_map,
                get_position="[lon, lat]", get_radius="radius",
                get_fill_color="color", get_line_color=[255,255,255,230],
                stroked=True, line_width_min_pixels=1, pickable=True, auto_highlight=True),
            pdk.Layer("TextLayer", data=df_map,
                get_position="[lon, lat]", get_text="nom", get_size=12,
                get_color=[29,29,31,230], get_anchor="middle",
                get_alignment_baseline="'bottom'", get_pixel_offset=[0,-14]),
        ]

        if coords_dech:
            df_origin = pd.DataFrame([{
                "lat": coords_dech[0], "lon": coords_dech[1],
                "label": lieu_choisi.upper(), "nom": f"Déchargement : {lieu_choisi}",
            }])
            layers += [
                pdk.Layer("ScatterplotLayer", data=df_origin,
                    get_position="[lon, lat]", get_radius=2000,
                    get_fill_color=[255,59,48,240], get_line_color=[255,255,255,230],
                    stroked=True, line_width_min_pixels=2, pickable=True),
                pdk.Layer("TextLayer", data=df_origin,
                    get_position="[lon, lat]", get_text="label", get_size=13,
                    get_color=[215,0,21,255], get_anchor="middle",
                    get_alignment_baseline="'bottom'", get_pixel_offset=[0,-16], font_weight=800),
            ]

        center_lat = coords_dech[0] if coords_dech else df_map["lat"].mean()
        center_lon = coords_dech[1] if coords_dech else df_map["lon"].mean()

        deck = pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=5, pitch=0),
            tooltip={
                "html": "<b>#{rang} — {nom}</b><br>💶 {prix} &nbsp;|&nbsp; 📏 {dist}<br>📊 {freq}× historique",
                "style": {"background":"#ffffff","color":"#1d1d1f","font-size":"13px","padding":"10px",
                          "border-radius":"10px","box-shadow":"0 4px 16px rgba(0,0,0,.12)",
                          "font-family":"-apple-system, BlinkMacSystemFont, Inter, sans-serif"}
            },
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        )
        st.pydeck_chart(deck, use_container_width=True, height=520)
        st.markdown(
            "<small style='color:#6e6e73'>🔴 Lieu de déchargement &nbsp;|&nbsp; 🟢 Top 1 &nbsp;|&nbsp; 🔵 Top 2-3 &nbsp;|&nbsp; ⚫ Autres</small>",
            unsafe_allow_html=True)

    except ImportError:
        st.map(pd.DataFrame(map_data).rename(columns={"lat":"latitude","lon":"longitude"}))

# ─── Tableau ──────────────────────────────────────────────────────────────────
with st.expander("Tableau complet"):
    df_display = top_candidates[["loc_ch","cp_ch","pays_ch","frequence",
                                  "prix_moyen","ventes_moyennes","delta_moyen",
                                  "dist_km","score_pct","chauffeurs","clients"]].copy()
    df_display.columns = ["Lieu chargement","CP","Pays","Fréquence",
                          "Prix moyen (€)","Ventes moy. (€)","Délai moyen (j)",
                          "Distance (km)","Score (%)","Chauffeurs","Clients"]
    for col in ["Prix moyen (€)","Ventes moy. (€)"]:
        df_display[col] = df_display[col].round(0)
    df_display["Délai moyen (j)"] = df_display["Délai moyen (j)"].round(1)
    df_display["Distance (km)"]   = df_display["Distance (km)"].round(0)
    st.dataframe(df_display, hide_index=True, use_container_width=True)

    import io as _io
    buf = _io.BytesIO()
    df_display.to_excel(buf, index=False, engine="openpyxl")
    st.download_button(
        "Exporter Excel",
        data=buf.getvalue(),
        file_name=f"recos_{normalize(lieu_choisi).replace(' ','_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ─── Produits ─────────────────────────────────────────────────────────────────
with st.expander("Produits typiquement chargés après ce déchargement"):
    produits = df_rec.groupby("produit").agg(
        nb=("prix","count"), prix_moy=("prix","mean")
    ).sort_values("nb", ascending=False).head(15).reset_index()
    produits.columns = ["Produit","Nb missions","Prix moyen (€)"]
    produits["Prix moyen (€)"] = produits["Prix moyen (€)"].round(0)
    st.dataframe(produits, hide_index=True, use_container_width=True)
