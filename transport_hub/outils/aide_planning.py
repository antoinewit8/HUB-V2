"""
Page Streamlit : Aide planning — vue planeur des chargements / déchargements
(plateaux et citernes, flotte CB et tractionnaires).

Lieux localisés par la table CP du hub (core/ptv.py, PTV seulement si inconnu).
"""
import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import re
import os
import sys
import io
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core import ptv, ui  # noqa: E402

ui.page_config("Aide planning")

st.markdown("""
<style>
/* Page large : la frise a besoin de place (plus spécifique que la règle du hub à 1 100 px) */
[data-testid="stMain"] [data-testid="stMainBlockContainer"] { max-width: 1360px !important; }

/* Bandeau fichier */
.ap-fichier { display:inline-flex; align-items:center; gap:10px; background:#fff; border-radius:980px; padding:7px 14px 7px 10px;
  box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.08); font-size:13px; color:#1d1d1f; }
.ap-fichier i { width:22px; height:22px; border-radius:6px; background:#ff9500; display:inline-flex; align-items:center;
  justify-content:center; color:#fff; font-style:normal; font-size:11px; font-weight:700; }
.ap-fichier span { color:#6e6e73; }

/* Barre de filtres : une carte, des pastilles */
.st-key-ap_barre { background:#fff; border-radius:18px; padding:14px 18px 6px; box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.06);
  margin-bottom:.4rem; }
.st-key-ap_barre label p { font-size:12px !important; font-weight:600 !important; color:#6e6e73 !important; }
[data-testid="stMain"] [role="radiogroup"] { background:#f0f0f3; border-radius:980px; padding:3px; gap:2px; width:fit-content;
  flex-wrap:nowrap; }
[data-testid="stMain"] button[data-variant="segmented_control"] { border:0 !important; border-radius:980px !important;
  background:transparent !important; min-height:32px; padding:0 13px !important; box-shadow:none !important; white-space:nowrap; }
[data-testid="stMain"] button[data-variant="segmented_control"] p { color:#6e6e73 !important; font-weight:500 !important; font-size:13px !important; }
[data-testid="stMain"] button[data-variant="segmented_control"]:hover p { color:#1d1d1f !important; }
[data-testid="stMain"] button[data-variant="segmented_control"][aria-checked="true"] { background:#fff !important;
  box-shadow:0 1px 3px rgba(0,0,0,.14), 0 0 0 .5px rgba(0,0,0,.04) !important; }
[data-testid="stMain"] button[data-variant="segmented_control"][aria-checked="true"] p { color:#1d1d1f !important; font-weight:600 !important; }
.st-key-ap_barre .stButton button { min-height:38px !important; width:38px; padding:0 !important; }
.st-key-ap_barre .stButton button p { font-size:18px !important; line-height:1; }
.ap-periode { font-size:17px; font-weight:600; letter-spacing:-0.01em; color:#1d1d1f; padding-bottom:8px; white-space:nowrap; }

/* Onglets : soulignement orange (couleur de la catégorie Planning) */
[data-testid="stTabs"] [role="tablist"] { gap:6px; border-bottom:1px solid #e5e5ea; }
[data-testid="stTab"] { padding:10px 14px !important; }
[data-testid="stTab"] p { font-size:15px !important; font-weight:500 !important; color:#6e6e73 !important; }
[data-testid="stTab"][aria-selected="true"] p { color:#1d1d1f !important; font-weight:600 !important; }
[data-testid="stTab"][aria-selected="true"] > div:last-child:empty { background:#ff9500 !important; }
[data-testid="stTab"]:hover p { color:#1d1d1f !important; }

/* Fiche dossier */
.ap-fiche { background:#fff; border-radius:18px; padding:18px 20px; box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.06); }
.ap-fiche .eye { font-size:12px; color:#6e6e73; margin:0; }
.ap-fiche h3 { font-size:20px !important; font-weight:600; letter-spacing:-0.015em; margin:4px 0 14px !important; padding:0 !important;
  line-height:1.25; }
.ap-fiche .etape { display:grid; grid-template-columns:12px minmax(0,1fr); gap:10px; margin-bottom:12px; }
.ap-fiche .pt { width:10px; height:10px; border-radius:50%; margin-top:5px; }
.ap-fiche .q { font-size:12px; color:#6e6e73; }
.ap-fiche .l { font-size:15px; font-weight:600; }
.ap-fiche .s { font-size:12px; color:#6e6e73; }
.ap-fiche .tags { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0 2px; }
.ap-fiche .tags span { font-size:12px; background:#f0f0f3; color:#1d1d1f; padding:4px 10px; border-radius:980px; }
.ap-fiche .tags span.tra { background:#fff3e5; color:#b25000; }
.ap-vide { background:#fff; border-radius:18px; padding:28px 20px; box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.06);
  color:#6e6e73; font-size:14px; text-align:center; }

/* Regroupements */
.ap-groupes { display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:12px; }
.ap-groupe { background:#fff; border-radius:18px; padding:16px 18px; box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.06); }
.ap-groupe .t { display:inline-block; font-size:11px; font-weight:600; padding:3px 9px; border-radius:980px; }
.ap-groupe .t.c { background:#e8f6ec; color:#1e7a34; } .ap-groupe .t.d { background:#e8f1fc; color:#0060c0; }
.ap-groupe .n { font-size:18px; font-weight:600; margin-top:8px; letter-spacing:-0.01em; }
.ap-groupe .z { font-size:13px; color:#6e6e73; margin-top:3px; }

/* Panneau pays de la carte */
.pp-card-btn { background:#fff; border-radius:16px; padding:.85rem 1rem .75rem; box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 .5px rgba(0,0,0,.08);
  display:flex; flex-direction:column; gap:.15rem; margin-top:.4rem; }
.pp-row-top { display:flex; align-items:baseline; gap:.5rem; }
.pp-code { font-size:1.15rem; font-weight:700; color:#1d1d1f; line-height:1; }
.pp-detail-line { font-size:.75rem; font-weight:500; color:#6e6e73; line-height:1.4; margin-top:.3rem; border-top:1px solid #f0f0f3; padding-top:.3rem; }
</style>
""", unsafe_allow_html=True)

COMMUNES_PAYS_LOGISTIQUE = {
    "bazeilles": "BE", "carignan": "BE", "mouzon": "BE",
    "remilly aillicourt": "BE", "douzy": "BE", "sedan": "BE",
    "thionville": "LU", "yutz": "LU", "metzange": "LU",
}

def normalize(text) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    text = str(text).upper().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"['\-–/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def normalize_key(text) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"['\-–/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _norm_col(c) -> str:
    c = unicodedata.normalize("NFD", str(c))
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", c.lower())

def find_col(cols, *candidates):
    nmap = {}
    for c in cols:
        nmap.setdefault(_norm_col(c), c)
    for cand in candidates:
        nc = _norm_col(cand)
        if nc in nmap:
            return nmap[nc]
    for cand in candidates:
        nc = _norm_col(cand)
        if not nc:
            continue
        for k, v in nmap.items():
            if nc in k or k in nc:
                return v
    return None

# Vocabulaire explicite : la 1re lettre ne suffit pas (DECROCHER, DEPOT, DEPART ne sont pas des
# déchargements ; ECHANGE, COUPLER, CONTROLE ne sont pas des chargements).
_RE_DECH = re.compile(r"DECHARG|LIVR|UNLOAD|LOSSEN|ABLAD|ENTLAD")
_RE_CHARG = re.compile(r"\bCHARG|ENLEV|\bLOAD|LADEN|BELAD|OPHAL")


def classify_activite(v) -> str:
    """C = chargement, D = déchargement, A = autre activité (lavage, décrochage, dépôt…), ? = vide."""
    n = normalize(v)
    if not n:
        return "?"
    if _RE_DECH.search(n):
        return "D"
    if _RE_CHARG.search(n):
        return "C"
    return "A"


def parse_heure(v):
    if v is None:
        return "", 99.0
    s = str(v).strip()
    m = re.search(r"(\d{1,2})\s*[:hH]\s*(\d{0,2})", s)
    if m:
        h = int(m.group(1)); mi = int(m.group(2) or 0)
        return f"{h:02d}:{mi:02d}", h + mi / 60.0
    try:
        f = float(s.replace(",", "."))
        if 0 <= f < 1:
            h = int(f * 24); mi = int(round((f * 24 - h) * 60))
            return f"{h:02d}:{mi:02d}", h + mi / 60.0
    except Exception:
        pass
    return s[:5], 99.0

PAYS_MAP_DISPLAY = {
    "F":"France","FR":"France","B":"Belgium","BE":"Belgium","NL":"Netherlands",
    "D":"Germany","DE":"Germany","L":"Luxembourg","LU":"Luxembourg","E":"Spain","ES":"Spain",
    "I":"Italy","IT":"Italy","CH":"Switzerland","A":"Austria","AT":"Austria",
    "GB":"United Kingdom","UK":"United Kingdom","PL":"Poland","P":"Portugal","PT":"Portugal",
}
PAYS_FLAGS = {
    "F":"🇫🇷","FR":"🇫🇷","B":"🇧🇪","BE":"🇧🇪","NL":"🇳🇱","D":"🇩🇪","DE":"🇩🇪",
    "L":"🇱🇺","LU":"🇱🇺","E":"🇪🇸","ES":"🇪🇸","I":"🇮🇹","IT":"🇮🇹","CH":"🇨🇭",
    "A":"🇦🇹","AT":"🇦🇹","GB":"🇬🇧","UK":"🇬🇧","PL":"🇵🇱","P":"🇵🇹","PT":"🇵🇹",
}
TYPE_LIB = {"C": "Chargement", "D": "Déchargement", "A": "Autre", "?": "?"}
DEPT_NOM = {
    "59":"Nord","62":"Pas-de-Calais","80":"Somme","02":"Aisne","60":"Oise","76":"Seine-Maritime",
    "27":"Eure","75":"Paris","77":"Seine-et-Marne","93":"Seine-St-Denis","51":"Marne","54":"Meurthe-et-M.",
    "57":"Moselle","67":"Bas-Rhin","69":"Rhône","13":"Bouches-du-Rh.","33":"Gironde","31":"Hte-Garonne",
    "44":"Loire-Atl.","35":"Ille-et-V.","49":"Maine-et-L.","53":"Mayenne","72":"Sarthe","85":"Vendée",
}

def pays_logistique(localite: str, pays_source: str) -> str:
    key = normalize_key(localite)
    if key in COMMUNES_PAYS_LOGISTIQUE:
        return COMMUNES_PAYS_LOGISTIQUE[key]
    return iso(pays_source) or "??"


def iso(pays) -> str:
    try:
        return ptv.geo().iso_pays(pays) or str(pays or "").strip().upper()
    except Exception:
        p = str(pays or "").strip().upper()
        return {"F": "FR", "B": "BE", "D": "DE", "E": "ES", "I": "IT", "L": "LU", "A": "AT", "P": "PT",
                "UK": "GB"}.get(p, p)


def norm_cp(cp, iso_pays) -> str:
    try:
        return ptv.geo().norm_cp(cp, iso_pays)
    except Exception:
        return str(cp or "").strip()


@st.cache_data(show_spinner=False, ttl=86400)
def geocode_cached(ville: str, cp: str, pays: str):
    """(lat, lon) par la table CP du hub, PTV si le lieu est inconnu ; None sinon."""
    if not (ville or "").strip() and not (cp or "").strip():
        return None
    r = ptv.localiser(pays, cp, ville)
    return (r["lat"], r["lon"]) if r else None


def smart_to_datetime(s):
    s = s.fillna("").astype(str).str.strip()
    a = pd.to_datetime(s, errors="coerce", dayfirst=True)
    b = pd.to_datetime(s, errors="coerce", dayfirst=False)
    def span_days(x):
        x = x.dropna()
        return (x.max() - x.min()).days if len(x) > 1 else 0
    na_a, na_b = int(a.isna().sum()), int(b.isna().sum())
    if na_a != na_b:
        return (a, "jour/mois") if na_a < na_b else (b, "mois/jour")
    if span_days(a) == span_days(b):
        return a, "jour/mois (défaut)"
    return (a, "jour/mois") if span_days(a) < span_days(b) else (b, "mois/jour")

@st.cache_data(show_spinner=False)
def load_activites(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    df.columns = df.columns.str.strip()
    cols = list(df.columns)
    C = {
        "dossier":    find_col(cols, "N° Dossier", "No Dossier", "Dossier", "N Dossier"),
        "activite":   find_col(cols, "Activité", "Activite", "Activ"),
        "date":       find_col(cols, "Date"),
        "heure":      find_col(cols, "Heure"),
        "type_tr":    find_col(cols, "Type de transport", "Type transport"),
        "nom1":       find_col(cols, "Nom 1", "Nom1", "Nom"),
        "nom2":       find_col(cols, "Nom 2", "Nom2"),
        "adresse":    find_col(cols, "Adresse"),
        "numero":     find_col(cols, "Numéro", "Numero", "No"),
        "pays":       find_col(cols, "Code pays", "Pays"),
        "dept":       find_col(cols, "Département", "Departement", "Dept"),
        "cp":         find_col(cols, "Code postal", "CP"),
        "localite":   find_col(cols, "Localité", "Localite", "Ville"),
        "produit":    find_col(cols, "Produit"),
        "chauffeur":  find_col(cols, "Chauffeur"),
        "depart_trac":find_col(cols, "Départ. tracteur", "Depart tracteur", "Depart. tracteur", "Départ tracteur"),
        "immat":      find_col(cols, "Immat. tracteur", "Immat tracteur", "Immatriculation", "Immat"),
        "remorque":   find_col(cols, "Remorque"),
    }
    def col(key):
        c = C[key]
        return df[c] if c and c in df.columns else pd.Series([None] * len(df))
    out = pd.DataFrame()
    out["dossier"]    = col("dossier").fillna("").astype(str).str.strip()
    out["_act_raw"]   = col("activite").fillna("").astype(str).str.strip()
    out["type"]       = out["_act_raw"].apply(classify_activite)
    out["date"], _date_order = smart_to_datetime(col("date"))
    he = col("heure").apply(parse_heure)
    out["heure"]      = he.apply(lambda x: x[0])
    out["_hval"]      = he.apply(lambda x: x[1])
    out["type_tr"]    = col("type_tr").fillna("").astype(str).str.strip()
    n1 = col("nom1").fillna("").astype(str).str.strip()
    n2 = col("nom2").fillna("").astype(str).str.strip()
    out["site"]       = (n1 + " " + n2).str.strip().replace(r"\s+", " ", regex=True)
    out["localite"]   = col("localite").fillna("").astype(str).str.strip()
    out["cp"]         = col("cp").fillna("").astype(str).str.strip()
    out["dept"]       = col("dept").fillna("").astype(str).str.strip()
    out["pays"]       = col("pays").fillna("").astype(str).str.strip().str.upper().map(iso)
    out["produit"]    = col("produit").fillna("").astype(str).str.strip()
    out["chauffeur"]  = col("chauffeur").fillna("").astype(str).str.strip()
    out["depart_trac"]= col("depart_trac").fillna("").astype(str).str.strip()
    out["immat"]      = col("immat").fillna("").astype(str).str.strip()
    out["remorque"]   = col("remorque").fillna("").astype(str).str.strip()
    out["cp"] = [norm_cp(c, p) if c else "" for c, p in zip(out["cp"], out["pays"])]   # 2100 → 02100 (FR)
    # Département : France seulement (2 premiers chiffres du CP) ; ailleurs, zone CP préfixée du pays
    cp2 = out["cp"].str.replace("L-", "", regex=False).str.extract(r"^(\d{2})", expand=False).fillna("")
    out["dept"] = np.where(out["pays"].eq("FR"),
                           out["dept"].where(out["dept"].str.len() > 0, cp2),
                           np.where(cp2.ne(""), out["pays"] + " " + cp2, ""))
    out["lieu_cle"] = out["pays"] + "|" + out["cp"] + "|" + out["localite"].map(normalize)
    out["is_tra"] = out["depart_trac"].str.upper().str.contains("TRA", na=False)
    out["pays_logi"] = out.apply(lambda r: pays_logistique(r["localite"], r["pays"]), axis=1)
    out["_dt"] = out["date"] + pd.to_timedelta(out["_hval"].where(out["_hval"] < 30, 0), unit="h")
    out = out[out["dossier"] != ""].copy()
    out = out.sort_values(["date", "_hval"], na_position="last", kind="stable").reset_index(drop=True)
    act_distinct = (df[C["activite"]].dropna().astype(str).str.strip().value_counts()
                    if C["activite"] else pd.Series(dtype=int))
    return out, C, act_distinct, _date_order

def html(s: str):
    st.markdown("\n".join(line.lstrip() for line in s.splitlines()), unsafe_allow_html=True)

def build_pays_panel(points_list, show_mode_param):
    """Dossiers distincts par pays logistique (un dossier à deux arrêts dans le même pays compte une fois)."""
    from collections import defaultdict
    pays_dos    = defaultdict(set)
    pays_detail = defaultdict(list)
    for p in points_list:
        pl = p.get("pays_logi", p.get("pays", "??"))
        ps = p.get("pays", "??")
        pays_dos[pl].update(p.get("dos_all", []))
        ps_norm = pays_logistique("__no_override__", ps)
        if pl != ps_norm:
            pays_detail[pl].append((p["nom"], p["camions"]))
    return {k: len(v) for k, v in pays_dos.items()}, pays_detail

# ─── Géocodage mis en cache ──────────────────────────────────────────────────
# Construit points_all (tous les lieux, charg + déch) et arcs_all (toutes les
# liaisons charg→déch). Mis en cache : ne se relance QUE si dmap change vraiment.
# Le clic carte / bouton pays / filtre show_mode ne re-géocodent plus rien.
@st.cache_data(show_spinner="Localisation des lieux…")
def build_geo_data(agg_json, arc_legs_json):
    agg_records = json.loads(agg_json)
    arc_legs    = json.loads(arc_legs_json)

    _local = {}
    def geo(loc, cp, pays):
        k = (normalize(loc), str(cp or ""), str(pays or ""))
        if k not in _local:
            _local[k] = geocode_cached(loc, cp, pays)
        return _local[k]

    points_all = []
    for row in agg_records:
        c = geo(row["localite"], row.get("cp", ""), row.get("pays", ""))
        if c:
            n = int(row["camions"])
            points_all.append({
                "nom": row["localite"], "loc_norm": row["lieu_cle"], "label": str(n),
                "dos_all": row.get("dos_all", []),
                "camions": n,
                "typ": "Chargement" if row["type"] == "C" else "Déchargement",
                "pays": row.get("pays", ""),
                "pays_logi": row.get("pays_logi", row.get("pays", "")),
                "dossiers": row.get("dossiers", ""),
                "lat": c[0], "lon": c[1],
                "radius": 900 + (n ** 0.5) * 1150,
                "color": [52, 199, 89, 225] if row["type"] == "C" else [0, 113, 227, 225],
                "type_code": row["type"],
            })

    arcs_all = []
    for lg in arc_legs:
        cc = geo(lg["c_loc"], lg.get("c_cp", ""), lg.get("c_pays", "")) if lg.get("c_loc") else None
        dc = geo(lg["d_loc"], lg.get("d_cp", ""), lg.get("d_pays", "")) if lg.get("d_loc") else None
        if cc and dc:
            arcs_all.append({
                "sl": cc[1], "sla": cc[0], "tl": dc[1], "tla": dc[0],
                "dos": lg["dos"],
                "cn": lg.get("c_cle", ""), "dn": lg.get("d_cle", ""),
                "c_nom": lg["c_loc"], "d_nom": lg["d_loc"],
                "w": 1.6,
            })
    return points_all, arcs_all

def _read_pydeck_sel(event, key):
    """Lit le loc_norm du point sélectionné dans pydeck, sinon None."""
    def _from_sel(s):
        if s is None:
            return None
        objs = s.get("objects") if isinstance(s, dict) else getattr(s, "objects", None)
        if isinstance(objs, dict):
            pts = objs.get("pts")
            if pts:
                return pts[0].get("loc_norm")
        return None
    try:
        s = getattr(event, "selection", None)
        if s is None and isinstance(event, dict):
            s = event.get("selection")
        r = _from_sel(s)
        if r is not None:
            return r
    except Exception:
        pass
    try:
        stt = st.session_state.get(key)
        if isinstance(stt, dict):
            return _from_sel(stt.get("selection"))
    except Exception:
        pass
    return None

# ─── Fragment : panneau pays + carte (rerun partiel) ─────────────────────────
def render_pays_carte(points_all, arcs_all, n_agg, pays_rows,
                      show_mode, show_arcs, focus_norm_ext, legs, MAX_GEO):
    from collections import defaultdict

    val_color = "#0071e3" if show_mode == "Déchargements" else "#1d1d1f" if show_mode == "Les deux" else "#248a3d"
    title_mode = {"Les deux": "Tous", "Chargements": "Charg.", "Déchargements": "Déch."}[show_mode]

    if "pp_selected_pays" not in st.session_state:
        st.session_state["pp_selected_pays"] = None

    # Focus = clic carte (écrit en fin de fragment) sinon selectbox
    clicked_norm = st.session_state.get("pp_focus_raw")
    focus_norm   = clicked_norm or focus_norm_ext

    # Panneau pays : compteurs selon le mode d'affichage
    if show_mode == "Chargements":
        panel_points = [p for p in points_all if p["type_code"] == "C"]
    elif show_mode == "Déchargements":
        panel_points = [p for p in points_all if p["type_code"] == "D"]
    else:
        panel_points = points_all
    pays_total, pays_detail = build_pays_panel(panel_points, show_mode)

    col_panel, col_map = st.columns([1, 5])

    with col_panel:
        st.markdown(
            f'<div style="font-size:13px;font-weight:600;color:#6e6e73;margin-bottom:.5rem;">'
            f'Dossiers par pays · {title_mode}</div>',
            unsafe_allow_html=True)

        pays_order = sorted(pays_total.keys(), key=lambda k: -pays_total[k])
        for pays_code in pays_order:
            total     = pays_total[pays_code]
            flag      = ""
            details   = pays_detail.get(pays_code, [])
            is_active = st.session_state["pp_selected_pays"] == pays_code

            detail_html = ""
            if details:
                parts = [f"+{n} {loc}" for loc, n in details[:4]]
                detail_html = '<div class="pp-detail-line">dont ' + "  ·  ".join(parts) + '</div>'

            active_style = (
                f"border-color:{val_color};background:#f2faf4;"
                f"box-shadow:0 0 0 1px {val_color}33;"
            ) if is_active else ""

            st.markdown(f"""
<div class="pp-card-btn" style="{active_style};margin-bottom:0;">
  <div class="pp-row-top">
    <span class="pp-code">{pays_code}</span>
    <span style="font-size:2.2rem;font-weight:600;letter-spacing:-0.02em;color:{val_color};line-height:1;margin-left:auto;">{total}</span>
  </div>
  {detail_html}
</div>""", unsafe_allow_html=True)

            btn_label = "Fermer" if is_active else "Détails"
            btn_type  = "primary" if is_active else "secondary"
            if st.button(btn_label, key=f"pp_btn_{pays_code}",
                         width="stretch", type=btn_type):
                st.session_state["pp_selected_pays"] = (None if is_active else pays_code)
                st.session_state["pp_focus_raw"] = None
                st.rerun(scope="fragment")

        if focus_norm:
            if st.button("Vue d'ensemble", key="pp_reset_focus", icon=":material/undo:",
                         width="stretch", type="primary"):
                st.session_state["pp_focus_raw"] = None
                st.rerun(scope="fragment")

    sel_pays = st.session_state.get("pp_selected_pays")

    # ── Jeu de points / arcs à afficher ────────────────────────────────────
    if focus_norm:
        # Point isolé : on cherche les liaisons dans TOUTE la liste d'arcs,
        # et les points liés dans TOUS les points (autre pays / autre type OK).
        # Si un point lié manque (non géocodé en propre), on le reconstruit
        # depuis les coordonnées portées par l'arc.
        arcs_map = [dict(a) for a in arcs_all if a["cn"] == focus_norm or a["dn"] == focus_norm]
        pmap     = {p["loc_norm"]: p for p in points_all}
        related  = {focus_norm}
        for a in arcs_map:
            related.add(a["cn"]); related.add(a["dn"])

        points_map = []
        for nrm in related:
            if nrm in pmap:
                points_map.append(dict(pmap[nrm]))
            else:
                syn = None
                for a in arcs_map:
                    if a["cn"] == nrm:
                        syn = {"nom": a["c_nom"], "loc_norm": nrm, "label": "",
                               "camions": 0, "typ": "Chargement", "pays": "",
                               "pays_logi": "", "dossiers": "",
                               "lat": a["sla"], "lon": a["sl"], "radius": 1100,
                               "color": [52, 199, 89, 225], "type_code": "C"}
                        break
                    if a["dn"] == nrm:
                        syn = {"nom": a["d_nom"], "loc_norm": nrm, "label": "",
                               "camions": 0, "typ": "Déchargement", "pays": "",
                               "pays_logi": "", "dossiers": "",
                               "lat": a["tla"], "lon": a["tl"], "radius": 1100,
                               "color": [0, 113, 227, 225], "type_code": "D"}
                        break
                if syn:
                    points_map.append(syn)

        for a in arcs_map:
            a["w"] = 3.0
        for p in points_map:
            if p["loc_norm"] == focus_norm:
                p["radius"] = p["radius"] * 1.5
                p["color"]  = p["color"][:3] + [255]
        foc_name = next((p["nom"] for p in points_map if p["loc_norm"] == focus_norm), focus_norm)
        st.info(f"**{foc_name}** isolé — {len(arcs_map)} liaison(s). "
                f"Recliquez le point (ou « Vue d'ensemble ») pour revenir.")
        foc = next((p for p in points_map if p["loc_norm"] == focus_norm), None)
        if foc is not None and any(p["loc_norm"] == focus_norm and p["type_code"] == "D" for p in points_all):
            if st.button(f"Où recharger après {foc_name} ?", key="pp_vers_tv", icon=":material/swap_horiz:", type="primary"):
                st.session_state["tv_point"] = {"nom": foc_name, "lat": foc["lat"], "lon": foc["lon"]}
                st.switch_page(ui.page_ref("outils/trajets_vides_cit.py"))
    else:
        pts = list(points_all)
        if sel_pays:
            pts = [p for p in pts if p.get("pays_logi", p.get("pays")) == sel_pays]
        if show_mode == "Chargements":
            pts = [p for p in pts if p["type_code"] == "C"]
        elif show_mode == "Déchargements":
            pts = [p for p in pts if p["type_code"] == "D"]
        points_map = [dict(p) for p in pts]
        if show_arcs and points_map:
            locs = {p["loc_norm"] for p in points_map}
            if sel_pays:
                arcs_map = [a for a in arcs_all if a["cn"] in locs or a["dn"] in locs]
            else:
                arcs_map = list(arcs_all)
        else:
            arcs_map = []

    # ── Carte ──────────────────────────────────────────────────────────────
    with col_map:
        if not points_map:
            st.info("Aucun point à afficher pour ces filtres.")
        else:
            try:
                import pydeck as pdk
                dfp = pd.DataFrame(points_map)
                layers = [
                    pdk.Layer("ScatterplotLayer", data=dfp, id="pts",
                              get_position="[lon, lat]", get_radius="radius",
                              radius_min_pixels=8, radius_max_pixels=48,
                              get_fill_color="color", get_line_color=[255,255,255,230],
                              stroked=True, line_width_min_pixels=1, pickable=True,
                              auto_highlight=True),
                    pdk.Layer("TextLayer", data=dfp, get_position="[lon, lat]",
                              get_text="label", get_size=14, get_color=[255,255,255,255],
                              get_anchor="middle", get_alignment_baseline="'center'", font_weight=800),
                    pdk.Layer("TextLayer", data=dfp, get_position="[lon, lat]",
                              get_text="nom", get_size=11, get_color=[29,29,31,220],
                              get_anchor="middle", get_alignment_baseline="'bottom'",
                              get_pixel_offset=[0,-16]),
                ]
                if arcs_map:
                    layers.insert(0, pdk.Layer("ArcLayer", data=pd.DataFrame(arcs_map),
                        get_source_position="[sl, sla]", get_target_position="[tl, tla]",
                        get_source_color=[52,199,89,170], get_target_color=[0,113,227,190],
                        get_width="w", width_min_pixels=1))
                zoom_level = 7 if focus_norm else (6 if sel_pays else 5)
                deck = pdk.Deck(
                    layers=layers,
                    initial_view_state=pdk.ViewState(
                        latitude=dfp["lat"].mean(),
                        longitude=dfp["lon"].mean(),
                        zoom=zoom_level, pitch=0),
                    tooltip={"html": "<b>{nom}</b><br>{typ} · <b>{camions}</b> dossier(s)<br>"
                                     "<span style='color:#6e6e73'>Dossiers : {dossiers}</span>",
                             "style": {"background":"#ffffff","color":"#1d1d1f","border-radius":"10px",
                                       "box-shadow":"0 4px 16px rgba(0,0,0,.12)",
                                       "font-family":"-apple-system, BlinkMacSystemFont, Inter, sans-serif","padding":"9px"}},
                    map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
                )
                # Clé stable (ne dépend pas du focus) → la sélection pydeck
                # persiste : recliquer le point sélectionné le désélectionne.
                map_key = f"planmap_{sel_pays or 'all'}"
                try:
                    event = st.pydeck_chart(deck, use_container_width=True, height=620,
                                            key=map_key, selection_mode="single-object",
                                            on_select="rerun")
                    new_sel = _read_pydeck_sel(event, map_key)
                    if new_sel != st.session_state.get("pp_focus_raw"):
                        st.session_state["pp_focus_raw"] = new_sel
                        st.rerun(scope="fragment")
                except TypeError:
                    st.pydeck_chart(deck, use_container_width=True, height=680)
            except ImportError:
                st.map(pd.DataFrame(points_map).rename(columns={"lat":"latitude","lon":"longitude"}))

    # ── Détail pays pleine largeur ─────────────────────────────────────────
    if sel_pays and sel_pays in pays_rows:
        flag_s = ""
        rows_sel = pays_rows[sel_pays]
        detail_records = []
        for row in rows_sel.to_dict("records"):
            dos = row["dossier"]
            lg  = legs.get(dos, {})
            detail_records.append({
                "N° Dossier":  dos,
                "Type":        TYPE_LIB.get(row["type"], "?"),
                "_d":          row["date"], "_h": row["_hval"],
                "Date":        row["date"].strftime("%d/%m/%Y") if pd.notna(row["date"]) else "—",
                "Heure":       row["heure"] or "—",
                "Localité":    row["localite"] or "—",
                "Chauffeur":   row["chauffeur"] or "—",
                "Tracteur":    row["immat"] or "—",
                "Remorque":    row["remorque"] or "—",
                "Flotte":      "TRA" if row["is_tra"] else "CB",
                "Charg. →":    lg.get("c_loc", "—"),
                "→ Déch.":     lg.get("d_loc", "—"),
            })
        df_detail = (pd.DataFrame(detail_records).sort_values(["_d", "_h", "N° Dossier"], na_position="last")
                     .drop(columns=["_d", "_h"]))
        n_dos = df_detail["N° Dossier"].nunique()
        st.markdown(
            f'<div class="sect">{flag_s} Détail {sel_pays} '
            f'<span class="hint">{n_dos} dossiers · {len(df_detail)} activités</span></div>',
            unsafe_allow_html=True)
        st.dataframe(df_detail, hide_index=True, width="stretch",
                     height=min(420, 38 + len(df_detail) * 36))

# ─── En-tête ─────────────────────────────────────────────────────────────────
import datetime as _dtm  # noqa: E402

from tools.aide_planning import planeur as PL  # noqa: E402
from tools.aide_planning.composant import frise as _FRISE  # noqa: E402

ui.page("aide_planning", "Le planning de la flotte d’un coup d’œil : qui charge, qui décharge, qui roule à vide, "
        "et où il reste de la place.")

_err_ptv = ptv.erreur_chargement()
if _err_ptv:
    st.caption(f"Localisation des lieux indisponible : {_err_ptv}")


def _esc(v) -> str:
    import html as _h
    return _h.escape(str(v if v is not None else ""))


def _nb(x) -> str:
    return f"{x:,.0f}".replace(",", " ")


# ─── Fichier ─────────────────────────────────────────────────────────────────
def _uploader(cle):
    f = st.file_uploader("Export des activités (LISTES_MISSIONS)", type=["xlsx", "xls"], key=cle,
                         help="Une ligne par activité : chargement, déchargement, lavage, décrochage…")
    if f is not None:
        st.session_state["ap_fichier"] = (f.name, f.getvalue())
        st.session_state.pop("ap_sel", None)
        return True
    return False


if "ap_fichier" not in st.session_state:
    if _uploader("ap_up"):
        st.rerun()
    st.markdown('<div class="ap-vide">Chargez l’export des activités pour afficher le planning. '
                'Il reste en mémoire si vous passez par un autre outil.</div>', unsafe_allow_html=True)
    st.stop()

df, COLS, ACT_DISTINCT, DATE_ORDER = load_activites(st.session_state["ap_fichier"][1])
if df.empty:
    st.error("Aucune ligne exploitable : la colonne « N° Dossier » est introuvable ou vide.")
    st.session_state.pop("ap_fichier", None)
    st.stop()

@st.cache_data(show_spinner="Préparation du planning…", max_entries=3)
def _preparer(cle, _df):
    """Une fois par fichier : lieux localisés, table des dossiers, liaisons de la carte."""
    u = _df.drop_duplicates("lieu_cle")
    coords = {k: geocode_cached(l, c, p) for k, l, c, p in zip(u["lieu_cle"], u["localite"], u["cp"], u["pays"])}
    t, autres = PL.table_dossiers(_df, coords)
    legs = {str(dos): {"c_loc": r.clocalite, "c_cp": r.ccp, "c_pays": r.cpays, "c_cle": r.clieu_cle,
                       "d_loc": r.dlocalite, "d_cp": r.dcp, "d_pays": r.dpays, "d_cle": r.dlieu_cle}
            for dos, r in zip(t.index, t.itertuples())}
    return coords, t, autres, legs


@st.cache_data(show_spinner=False, max_entries=32)
def _vue(cle, filtres, dim, t0, t1, couverture, _t, _autres, _act, _coords):
    """Une fois par période / filtre : frise, ressources, indicateurs."""
    return PL.vue(_t, _autres, _act, dim, t0, t1, _coords, couverture=couverture)


@st.cache_data(show_spinner=False, max_entries=8)
def _excel(cle, _table):
    buf = io.BytesIO()
    _table.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


import hashlib as _hashlib  # noqa: E402
CLE = _hashlib.md5(st.session_state["ap_fichier"][1]).hexdigest()
COORDS, T_ALL, AUTRES, legs = _preparer(CLE, df)
_dd = df["date"].dropna()
dmin, dmax = _dd.min().date(), _dd.max().date()

fb1, fb2, fb3 = st.columns([6, 1.2, 1.4], vertical_alignment="center")
fb1.markdown(
    f'<div class="ap-fichier"><i>XL</i><b>{_esc(st.session_state["ap_fichier"][0])}</b>'
    f'<span>{dmin:%d/%m/%Y} → {dmax:%d/%m/%Y} · {_nb(df["dossier"].nunique())} dossiers · '
    f'{_nb(len(df))} activités</span></div>', unsafe_allow_html=True)
with fb2.popover("Changer", use_container_width=True):
    if _uploader("ap_up2"):
        st.rerun()
    if st.button("Retirer le fichier", key="ap_rm"):
        st.session_state.pop("ap_fichier", None)
        st.rerun()
with fb3.popover("Données lues", use_container_width=True):
    st.markdown(f"**Colonnes reconnues** — format de date : {DATE_ORDER}")
    st.dataframe(pd.DataFrame([{"Champ": k, "Colonne du fichier": v or "—"} for k, v in COLS.items()]),
                 hide_index=True, width="stretch")
    autres = df.loc[df["type"].eq("A"), "_act_raw"].value_counts()
    if len(autres):
        st.caption("Activités comptées à part (ni chargement ni déchargement) : "
                   + ", ".join(f"{k} ({v})" for k, v in autres.items()))
    n_unknown = int((df["type"] == "?").sum())
    if n_unknown:
        st.caption(f"{n_unknown} activité(s) sans libellé.")

# ─── Filtres ─────────────────────────────────────────────────────────────────
ss = st.session_state
ss.setdefault("ap_mode", "Semaine")
if "ap_pivot" not in ss:
    auj = _dtm.date.today()
    ss["ap_pivot"] = auj if dmin <= auj <= dmax else dmax


def _seg(label, options, cle, defaut):
    v = st.segmented_control(label, options, key=cle, default=defaut)
    return v if v is not None else defaut


with st.container(key="ap_barre"):
    r1 = st.columns([1.55, .95, .3, .3, 2.6], vertical_alignment="bottom")
    with r1[0]:
        mode = _seg("Période", ["Jour", "Semaine", "Mois", "Tout"], "ap_mode_w", ss["ap_mode"])
        ss["ap_mode"] = mode
    if mode == "Tout":
        with r1[1]:
            plage = st.date_input("Du … au", value=(dmin, dmax), min_value=dmin, max_value=dmax,
                                  format="DD/MM/YYYY", key="ap_plage")
        plage = plage if isinstance(plage, (list, tuple)) and len(plage) == 2 else (dmin, dmax)
        t0, t1 = PL.fenetre("Tout", None, plage)
    else:
        with r1[1]:
            piv = st.date_input("Date", value=ss["ap_pivot"], format="DD/MM/YYYY", key=f"ap_piv_{ss['ap_pivot']}")
            if piv != ss["ap_pivot"]:
                ss["ap_pivot"] = piv
                st.rerun()
        if r1[2].button("‹", key="ap_prec", help="Période précédente"):
            ss["ap_pivot"] = PL.decaler(mode, ss["ap_pivot"], -1)
            st.rerun()
        if r1[3].button("›", key="ap_suiv", help="Période suivante"):
            ss["ap_pivot"] = PL.decaler(mode, ss["ap_pivot"], 1)
            st.rerun()
        t0, t1 = PL.fenetre(mode, ss["ap_pivot"])
    r1[4].markdown(f'<div class="ap-periode">{PL.libelle_periode(t0, t1)}</div>', unsafe_allow_html=True)

    r2 = st.columns([1.3, 1.1, 1.3, 1.9], vertical_alignment="bottom")
    with r2[0]:
        flotte = _seg("Flotte", ["Tous", "Flotte CB", "Tractionnaires"], "ap_flotte", "Tous")
    with r2[1]:
        metier = _seg("Métier", ["Tous", "Plateau", "Citerne"], "ap_metier", "Tous")
    with r2[2]:
        dimension = _seg("Une ligne par", ["Remorque", "Tracteur", "Chauffeur"], "ap_dim", "Remorque")
    dim_col = {"Chauffeur": "chauffeur", "Tracteur": "immat", "Remorque": "remorque"}[dimension]

df_scope = df
if flotte == "Flotte CB":
    df_scope = df_scope[~df_scope["is_tra"]]
elif flotte == "Tractionnaires":
    df_scope = df_scope[df_scope["is_tra"]]
if metier != "Tous":
    df_scope = df_scope[df_scope["type_tr"].str.upper().str.contains({"Plateau": "PLA", "Citerne": "CIT"}[metier], na=False)]

options = sorted(v for v in df_scope[dim_col].dropna().unique() if str(v).strip())
sel = r2[3].multiselect(f"Rechercher ({dimension.lower()})", options, placeholder="Toutes", key="ap_recherche")
if sel:
    df_scope = df_scope[df_scope[dim_col].isin(sel)]

dfx = df_scope[(df_scope["_dt"] >= t0) & (df_scope["_dt"] < t1)]
T = T_ALL
if flotte == "Flotte CB":
    T = T[~T["is_tra"]]
elif flotte == "Tractionnaires":
    T = T[T["is_tra"]]
if metier != "Tous":
    T = T[T["type_tr"].str.upper().str.contains({"Plateau": "PLA", "Citerne": "CIT"}[metier], na=False)]
if sel:
    T = T[T[dim_col].isin(sel)]
V = _vue(CLE, (flotte, metier, tuple(sel)), dimension, t0, t1, (dmin, dmax), T, AUTRES, df_scope, COORDS)
synthese = V["synthese"]

# ─── Indicateurs ─────────────────────────────────────────────────────────────
k = st.columns(4)
k[0].metric("Dossiers sur la période", _nb(len(V["dossiers_periode"])))
k[1].metric(f"{dimension}s actives" if dimension != "Chauffeur" else "Chauffeurs actifs", _nb(V["n_lignes"]))
if not synthese.empty and (t1 - t0).days > 1:
    k[2].metric("Jours ouvrés sans activité", _nb(synthese["Jours ouvrés sans activité"].sum()),
                help="Total sur les lignes affichées (lundi → vendredi, dans les dates de l’export).")
else:
    k[2].metric("Activités", _nb(len(dfx)))
kc, kv = (synthese["Km chargés estimés"].sum(), synthese["Km à vide estimés"].sum()) if not synthese.empty else (0, 0)
k[3].metric("Part de km à vide", f"{kv / (kc + kv) * 100:.0f} %" if kc + kv else "—",
            help="Estimée au vol d’oiseau × 1,3 : dernier déchargement → lavage / décrochage → chargement suivant.")

if dfx.empty:
    st.markdown(f'<div class="ap-vide">Aucune activité {PL.libelle_periode(t0, t1)} avec ces filtres. '
                f'L’export couvre du {dmin:%d/%m/%Y} au {dmax:%d/%m/%Y}.</div>', unsafe_allow_html=True)
    st.stop()

# ─── Onglets ─────────────────────────────────────────────────────────────────
t_plan, t_carte, t_res, t_grp, t_tab = st.tabs(["Planning", "Carte", "Ressources", "Regroupements", "Tableau"])

@st.fragment
def _onglet_planning():
    """Fragment : un clic sur la frise ne recalcule que cet onglet."""
    ss = st.session_state
    jours, lignes = V["jours"], V["lignes"]
    if V["n_lignes"] > PL.MAX_LIGNES:
        st.caption(f"Les {PL.MAX_LIGNES} {dimension.lower()}s les plus actives sont affichées : "
                   "utilisez « Rechercher » pour en voir d’autres.")
    c_frise, c_fiche = st.columns([3.3, 1.1], gap="medium")
    with c_frise:
        retour = _FRISE(jours=jours, lignes=lignes, sel=ss.get("ap_sel"), titre_ressource=dimension,
                        maintenant=PL.position_maintenant(t0, t1), key=f"ap_frise_{CLE[:6]}", default=None)
    if isinstance(retour, dict) and retour.get("t") != ss.get("ap_frise_t"):
        ss["ap_frise_t"] = retour.get("t")
        ss["ap_sel"] = retour.get("dossier")
    with c_fiche:
        det = PL.fiche(T_ALL, AUTRES, str(ss.get("ap_sel") or ""), COORDS)
        if not det:
            st.markdown('<div class="ap-vide">Cliquez une barre bleue du planning pour voir le dossier.</div>',
                        unsafe_allow_html=True)
        else:
            tags = "".join(f"<span>{_esc(x)}</span>" for x in (det["chauffeur"], det["tracteur"], det["produit"]) if x)
            if det["km_charge"]:
                tags += f"<span>~{_nb(det['km_charge'])} km chargés</span>"
            if det["tra"]:
                tags += '<span class="tra">Tractionnaire</span>'
            etapes = ""
            if det["charg"]:
                etapes += (f'<div class="etape"><div class="pt" style="background:#248a3d"></div><div>'
                           f'<div class="q">Chargement · {_esc(det["charg_quand"])}</div>'
                           f'<div class="l">{_esc(det["charg"])} <span class="s">{_esc(det["charg_pays"])}</span></div>'
                           f'<div class="s">{_esc(det["charg_site"])}</div></div></div>')
            if det["dech"]:
                etapes += (f'<div class="etape"><div class="pt" style="background:#0071e3"></div><div>'
                           f'<div class="q">Déchargement · {_esc(det["dech_quand"])}</div>'
                           f'<div class="l">{_esc(det["dech"])} <span class="s">{_esc(det["dech_pays"])}</span></div>'
                           f'<div class="s">{_esc(det["dech_site"])}</div></div></div>')
            autres = f'<div class="s" style="margin-bottom:6px">Ensuite : {_esc(det["autres"])}</div>' if det["autres"] else ""
            multi = (f' · {det["nb_charg"]} chargements, {det["nb_dech"]} déchargements'
                     if det["nb_charg"] > 1 or det["nb_dech"] > 1 else "")
            st.markdown(
                f'<div class="ap-fiche"><p class="eye">Dossier {_esc(det["dossier"])} · {_esc(det["remorque"])}{multi}</p>'
                f'<h3>{_esc(det["charg"] or "?")} → {_esc(det["dech"] or "?")}</h3>{etapes}{autres}'
                f'<div class="tags">{tags}</div></div>', unsafe_allow_html=True)
            if det["dech_point"]:
                if st.button(f"Où recharger après {det['dech']} ?", key="ap_vers_tv", type="primary",
                             icon=":material/swap_horiz:", width="stretch"):
                    ss["tv_point"] = {"nom": det["dech"], "lat": det["dech_point"][0], "lon": det["dech_point"][1]}
                    st.switch_page(ui.page_ref("outils/trajets_vides_cit.py"))



with t_plan:
    _onglet_planning()

@st.fragment
def _onglet_carte():
    """Fragment : filtres de carte, clic sur un point, panneau pays sans recharger la page."""
    m1, m2, m3 = st.columns([1.4, 1, 2], vertical_alignment="bottom")
    with m1:
        show_mode = st.segmented_control("Afficher", ["Les deux", "Chargements", "Déchargements"],
                                         default="Les deux", key="ap_show") or "Les deux"
    with m2:
        show_arcs = st.toggle("Relier les points", value=True, key="ap_arcs", help="Trait du chargement au déchargement de chaque dossier.")
    _lx = dfx[dfx["localite"].str.strip().ne("") & dfx["type"].isin(["C", "D"])].drop_duplicates("lieu_cle")
    loc_map = {f'{l} ({p} {c})'.replace(" )", ")"): kk for l, p, c, kk in
               zip(_lx["localite"], _lx["pays"], _lx["cp"], _lx["lieu_cle"])}
    with m3:
        focus_choice = st.selectbox("Isoler un lieu", ["Tous les lieux"] + sorted(loc_map), key="ap_focus")
    focus_norm_ext = loc_map.get(focus_choice)
    MAX_GEO = 1000
    agg = (dfx[dfx["type"].isin(["C", "D"])]
           .groupby(["lieu_cle", "type"])
           .agg(localite=("localite", "first"), cp=("cp", "first"), pays=("pays", "first"),
                pays_logi=("pays_logi", "first"), dept=("dept", "first"),
                camions=("dossier", "nunique"), dos_all=("dossier", lambda s: sorted(set(s))),
                dossiers=("dossier", lambda s: ", ".join(sorted(set(s))[:10])))
           .reset_index())
    agg = agg[agg["localite"].str.strip() != ""].sort_values("camions", ascending=False).head(MAX_GEO)
    arc_legs = []
    for dos in dfx["dossier"].unique():
        lg = legs.get(dos, {})
        if lg.get("c_loc") or lg.get("d_loc"):
            arc_legs.append({"dos": str(dos),
                             "c_loc": lg.get("c_loc", ""), "c_cp": lg.get("c_cp", ""), "c_pays": lg.get("c_pays", ""),
                             "d_loc": lg.get("d_loc", ""), "d_cp": lg.get("d_cp", ""), "d_pays": lg.get("d_pays", ""),
                             "c_cle": lg.get("c_cle", ""), "d_cle": lg.get("d_cle", "")})
    points_all, arcs_all = build_geo_data(agg.to_json(orient="records"), json.dumps(arc_legs, ensure_ascii=False))
    if not points_all:
        st.markdown('<div class="ap-vide">Aucun lieu localisé : vérifiez les colonnes pays, code postal et localité.</div>',
                    unsafe_allow_html=True)
    else:
        pays_rows = {kk: g for kk, g in dfx.groupby("pays_logi")}
        render_pays_carte(points_all, arcs_all, len(agg), pays_rows, show_mode, show_arcs, focus_norm_ext, legs, MAX_GEO)



with t_carte:
    _onglet_carte()

with t_res:
    if synthese.empty:
        st.markdown('<div class="ap-vide">Aucune ressource sur la période.</div>', unsafe_allow_html=True)
    else:
        st.caption("Jours ouvrés du lundi au vendredi. Km estimés au vol d’oiseau × 1,3 : chargés = 1er chargement → "
                   "dernier déchargement ; à vide = dernier déchargement → lavage / décrochage → chargement suivant.")
        st.dataframe(
            synthese.rename(columns={"Ressource": dimension}).assign(**{"Part à vide": synthese["Part à vide"] * 100}),
            hide_index=True, width="stretch",
            height=min(640, 40 + 36 * len(synthese)),
            column_config={
                "Part à vide": st.column_config.ProgressColumn("Part à vide", format="%.0f %%", min_value=0, max_value=100),
                "Jours ouvrés sans activité": st.column_config.NumberColumn("Jours sans activité"),
                "Dates sans activité": st.column_config.TextColumn("Dates", width="medium"),
                "Plus long écart (h)": st.column_config.NumberColumn("Plus long arrêt (h)", format="%.0f"),
                "Km chargés estimés": st.column_config.NumberColumn("Km chargés", format="%.0f"),
                "Km à vide estimés": st.column_config.NumberColumn("Km à vide", format="%.0f"),
            })

with t_grp:
    clusters = []
    for (d, dept, typ), g in dfx[dfx["dept"].str.len() > 0].groupby([dfx["date"].dt.date, "dept", "type"]):
        if typ not in ("C", "D") or g["dossier"].nunique() < 2:
            continue
        clusters.append({"date": d, "dept": dept, "type": typ, "n": g["dossier"].nunique(),
                         "lieux": ", ".join(sorted({str(x).title() for x in g["localite"] if x})[:5])})
    clusters.sort(key=lambda c: (-c["n"], c["date"]))
    if not clusters:
        st.markdown('<div class="ap-vide">Aucun jour avec au moins 2 dossiers dans un même département '
                    '(ou une même zone CP à l’étranger).</div>', unsafe_allow_html=True)
    else:
        st.caption("Au moins 2 dossiers le même jour dans un même département français, ou une même zone CP "
                   "du même pays à l’étranger : des pistes de groupage.")
        cartes = []
        for cl in clusters[:30]:
            if " " in cl["dept"]:
                zone = f"{cl['dept'].split()[0]} · zone CP {cl['dept'].split()[1]}"
            else:
                zone = f"Dépt {cl['dept']}" + (f" · {DEPT_NOM[cl['dept']]}" if cl["dept"] in DEPT_NOM else "")
            t = "c" if cl["type"] == "C" else "d"
            cartes.append(
                f'<div class="ap-groupe"><span class="t {t}">{"Chargements" if t == "c" else "Déchargements"}</span>'
                f'<div class="n">{cl["n"]} dossiers · {_esc(zone)}</div>'
                f'<div class="z">{PL.JOURS[cl["date"].weekday()]} {cl["date"]:%d/%m} · {_esc(cl["lieux"])}</div></div>')
        st.markdown('<div class="ap-groupes">' + "".join(cartes) + "</div>", unsafe_allow_html=True)
        if len(clusters) > 30:
            st.caption(f"… et {len(clusters) - 30} autre(s).")

with t_tab:
    show = dfx.copy()
    show["Type"] = np.where(show["type"].eq("A"), "Autre (" + show["_act_raw"] + ")", show["type"].map(TYPE_LIB).fillna("?"))
    show["Flotte"] = np.where(show["is_tra"], "Tractionnaire", "CB")
    show = show.sort_values(["_dt", "dossier"])
    show["Date"] = show["date"].dt.strftime("%d/%m/%Y")
    table = show[["Date", "heure", "Type", "dossier", "localite", "cp", "pays", "site", "produit", "chauffeur",
                  "immat", "remorque", "Flotte"]].rename(columns={
        "heure": "Heure", "dossier": "N° Dossier", "localite": "Localité", "cp": "CP", "pays": "Pays", "site": "Site",
        "produit": "Produit", "chauffeur": "Chauffeur", "immat": "Tracteur", "remorque": "Remorque"})
    tb1, tb2 = st.columns([4, 1], vertical_alignment="center")
    tb1.caption(f"{_nb(len(table))} activités · {_nb(table['N° Dossier'].nunique())} dossiers · "
                f"{PL.libelle_periode(t0, t1)}")
    tb2.download_button("Exporter Excel", data=_excel((CLE, flotte, metier, tuple(sel), str(t0), str(t1)), table),
                        file_name=f"planning_{t0:%Y%m%d}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    st.dataframe(table, hide_index=True, width="stretch", height=min(640, 40 + 36 * len(table)))
