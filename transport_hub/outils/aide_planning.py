"""
Page Streamlit : Planning Plateaux — Vue planeur
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
import importlib.util as _ilu
import types as _types
import urllib.request as _ureq
import urllib.parse as _uparse

def _load_ptv(project_root: str):
    if "modules" not in sys.modules:
        pkg = _types.ModuleType("modules")
        pkg.__path__ = [project_root]
        pkg.__package__ = "modules"
        sys.modules["modules"] = pkg
    for mod_name, filename in [
        ("modules.route_optimizer", "route_optimizer.py"),
        ("modules.villes_jalons",   "villes_jalons.py"),
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
                    pass
    ptv_path = os.path.join(project_root, "ptv_router_km.py")
    if not os.path.exists(ptv_path):
        return None
    spec = _ilu.spec_from_file_location("modules.ptv_router_km", ptv_path)
    mod  = _ilu.module_from_spec(spec)
    mod.__package__ = "modules"
    sys.modules["modules.ptv_router_km"] = mod
    spec.loader.exec_module(mod)
    return mod

_HERE  = os.path.dirname(os.path.abspath(__file__))
_ROOTS = [_HERE, os.path.dirname(_HERE)]
PTV_AVAILABLE = False
_ptv_mod = None
for _root in _ROOTS:
    if os.path.exists(os.path.join(_root, "ptv_router_km.py")):
        try:
            _ptv_mod = _load_ptv(_root)
            if _ptv_mod:
                PTV_AVAILABLE = True
                break
        except Exception:
            pass

if PTV_AVAILABLE and _ptv_mod:
    geocode_by_postal_code = _ptv_mod.geocode_by_postal_code
    _geocode_by_text       = _ptv_mod._geocode_by_text
    PAYS_TO_ISO            = _ptv_mod.PAYS_TO_ISO
    GPS_FIXES              = _ptv_mod.GPS_FIXES
else:
    PAYS_TO_ISO = {}
    GPS_FIXES   = {}

from core import ui

ui.page_config("Aide planning")

st.markdown("""
<style>
:root{
  --bg:#f5f5f7; --panel:#ffffff; --panel2:#fafafc;
  --line:#e5e5ea; --line2:#efeff4;
  --txt:#1d1d1f; --muted:#6e6e73; --faint:#8e8e93;
  --charg:#248a3d; --charg-d:#eaf6ec; --charg-l:#bfe3c7;
  --dech:#0071e3;  --dech-d:#e8f1fc;  --dech-l:#b9d4f5;
  --tra:#b25000;   --tra-d:#fff3e5;   --tra-l:#ffd3a3;
  --alert:#d70015; --alert-d:#fdecee; --alert-l:#f5b8bf;
}
.hero{
  background:var(--panel); border:1px solid var(--line);
  border-radius:18px; padding:1.4rem 1.8rem; margin-bottom:1.2rem;
  display:flex; align-items:flex-end; justify-content:space-between; gap:1rem;
}
.hero h1{ color:var(--txt);
  font-size:2.05rem; font-weight:700; margin:0; letter-spacing:0; line-height:1;
}
.hero p{ color:var(--muted); font-size:.88rem; margin:.4rem 0 0; }
.badge{
  display:inline-block; font-weight:600;
  font-size:.68rem; letter-spacing:0;
  padding:3px 11px; border-radius:980px; white-space:nowrap;
}
.dayhead{ color:var(--txt);
  font-size:1.3rem; font-weight:700; letter-spacing:0;
  margin:1.1rem 0 .5rem; padding-bottom:.3rem; border-bottom:1px solid var(--line);
  display:flex; align-items:baseline; gap:.7rem;
}
.dayhead .cnt{ font-size:.72rem; color:var(--muted); letter-spacing:0; font-weight:500; }
.coltag{ font-size:.7rem; font-weight:700; letter-spacing:0; margin:.2rem 0 .55rem; }
.coltag.c{ color:var(--charg); } .coltag.d{ color:var(--dech); }
.card{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:.7rem .85rem; margin-bottom:.55rem; display:grid; grid-template-columns:auto 1fr; gap:.7rem; align-items:start; }
.card.c{ border-color:var(--charg-l); } .card.d{ border-color:var(--dech-l); }
.card .hour{ font-size:1.25rem; font-weight:700; line-height:1; padding-top:1px; min-width:3.1rem; }
.card.c .hour{ color:var(--charg); } .card.d .hour{ color:var(--dech); }
.card .hour .dno{ display:block; font-size:.6rem; font-weight:500; color:var(--faint); letter-spacing:0; margin-top:3px; }
.card .loc{ font-size:1.08rem; font-weight:600; color:var(--txt); letter-spacing:0; line-height:1.05; }
.card .site{ font-size:.78rem; color:var(--muted); margin-top:1px; }
.card .leg{ font-size:.73rem; color:var(--faint); margin-top:3px; }
.card .leg b{ color:var(--muted); font-weight:600; }
.tags{ display:flex; flex-wrap:wrap; gap:5px; margin-top:.5rem; }
.tag{ font-size:.68rem; font-weight:600; letter-spacing:0; padding:1px 6px; border-radius:980px; border:1px solid var(--line); color:var(--muted); background:var(--panel2); }
.tag.tra{ color:var(--tra); border-color:var(--tra-l); background:var(--tra-d); }
.tag.cb{ color:var(--charg); border-color:var(--charg-l); background:var(--charg-d); }
.tag.prod{ color:var(--txt); }
.lane{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:.65rem .85rem; margin-bottom:.55rem; }
.lane .who{ font-size:1.05rem; font-weight:700; color:var(--txt); letter-spacing:0; display:flex; gap:.6rem; align-items:center; }
.lane .who .meta{ font-size:.68rem; color:var(--faint); font-weight:500; letter-spacing:0; text-transform:none; }
.flow{ display:flex; flex-wrap:wrap; gap:6px; margin-top:.5rem; }
.stop{ font-size:.72rem; font-weight:600; padding:3px 9px; border-radius:980px; border:1px solid; letter-spacing:0; white-space:nowrap; }
.stop.c{ color:var(--charg); border-color:var(--charg-l); background:var(--charg-d); }
.stop.d{ color:var(--dech); border-color:var(--dech-l); background:var(--dech-d); }
.stop .t{ opacity:.7; font-weight:500; margin-right:5px; }
.rows{ border:1px solid var(--line); border-radius:14px; overflow:hidden; margin-bottom:.5rem; }
.row{ display:grid; grid-template-columns:108px minmax(0,1.5fr) 16px minmax(0,1.5fr) minmax(0,1.4fr); gap:.45rem .75rem; align-items:center; padding:.42rem .75rem; border-bottom:1px solid var(--line2); }
.row:last-child{ border-bottom:none; }
.row:nth-child(odd){ background:var(--panel2); }
.row .c1{ display:flex; flex-direction:column; gap:3px; align-items:flex-start; }
.row .c1 .dos{ font-weight:600; font-size:.7rem; letter-spacing:0; color:var(--faint); }
.leg2{ display:grid; grid-template-columns:auto auto minmax(0,1fr); gap:.4rem; align-items:baseline; min-width:0; }
.leg2 .lh{ font-weight:700; font-size:.9rem; white-space:nowrap; letter-spacing:0; }
.leg2.c .lh{ color:var(--charg); } .leg2.d .lh{ color:var(--dech); }
.leg2 .ll{ font-weight:600; font-size:.9rem; color:var(--txt); letter-spacing:0; white-space:nowrap; }
.leg2 .ls{ font-size:.72rem; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
.leg2.off{ display:block; grid-template-columns:none; color:var(--faint); font-size:.74rem; font-style:italic; }
.rarrow{ color:var(--faint); font-size:.85rem; text-align:center; }
.row .res{ display:flex; flex-wrap:wrap; gap:3px; }
.dens-compact .row{ padding:.28rem .65rem; }
.dens-compact .leg2 .lh, .dens-compact .leg2 .ll{ font-size:.82rem; }
.dens-compact .leg2 .ls{ font-size:.68rem; }
.dens-large .row{ padding:.62rem .85rem; gap:.5rem .9rem; }
.dens-large .leg2 .lh, .dens-large .leg2 .ll{ font-size:1.02rem; }
.dens-large .leg2 .ls{ font-size:.78rem; }
@media(max-width:820px){ .row{ grid-template-columns:1fr; gap:.18rem; } .rarrow{ display:none; } }
.trips{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:.5rem; margin-bottom:.5rem; }
.trip{ background:var(--panel2); border:1px solid var(--line2); border-radius:14px; padding:.5rem .65rem .55rem; }
.trip-h{ display:flex; justify-content:space-between; align-items:center; gap:.4rem; margin-bottom:.3rem; flex-wrap:wrap; }
.trip-h .dos{ font-weight:600; font-size:.72rem; letter-spacing:0; color:var(--faint); }
.trip-tags{ display:flex; flex-wrap:wrap; gap:3px; }
.leg{ display:grid; grid-template-columns:auto 1fr; column-gap:.65rem; align-items:baseline; padding:.08rem 0; }
.leg .lh{ font-weight:700; font-size:.9rem; line-height:1.25; white-space:nowrap; letter-spacing:0; }
.leg.c .lh{ color:var(--charg); } .leg.d .lh{ color:var(--dech); }
.leg .ll{ grid-column:2; font-weight:600; font-size:.95rem; color:var(--txt); letter-spacing:0; line-height:1.25; }
.leg .ls{ grid-column:2; font-size:.72rem; color:var(--muted); line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.leg.off{ display:block; grid-template-columns:none; font-size:.72rem; font-style:italic; color:var(--faint); padding:.12rem 0; }
.arrow{ color:var(--faint); font-size:.78rem; line-height:1; margin:.1rem 0 .15rem .15rem; }
.cluster{ background:var(--alert-d); border:1px solid var(--alert-l); border-radius:14px; padding:.7rem .95rem; margin-bottom:.5rem; }
.cluster .ch{ font-weight:700; font-size:1rem; color:#d70015; letter-spacing:0; }
.cluster .cs{ font-size:.76rem; color:#6e6e73; margin-top:3px; }
.cluster.d{ background:var(--dech-d); border-color:var(--dech-l); }
.cluster.d .ch{ color:#0060c0; } .cluster.d .cs{ color:#6e6e73; }
.legendline{ color:var(--faint); font-size:.74rem; margin-top:.4rem; }
.legendline b.c{ color:var(--charg); } .legendline b.d{ color:var(--dech); } .legendline b.x{ color:var(--alert); }
/* ── Boutons pays : nouveau visuel ── */
.pp-card-btn {
    background: #ffffff;
    border: 1.5px solid #e5e5ea;
    border-radius: 18px;
    padding: 1rem 1.1rem .85rem;
    transition: border-color .15s, background .15s;
    display: flex;
    flex-direction: column;
    gap: .15rem;
    min-height: 88px;
    margin-bottom: 0;
}
.pp-card-btn:hover { border-color: #c7c7cc; background: #f5f5f7; }
.pp-row-top { display: flex; align-items: baseline; gap: .5rem; }
.pp-flag { font-size: 1.6rem; line-height: 1; }
.pp-code {
    font-size: 1.5rem; font-weight: 700;
    color: #1d1d1f; letter-spacing:0; line-height: 1;
}
.pp-detail-line {
    font-size: .75rem; font-weight: 600; color: #6e6e73;
    letter-spacing:0; line-height: 1.4;
    margin-top: .3rem; border-top: 1px solid #f5f5f7; padding-top: .3rem;
}
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

def classify_activite(v) -> str:
    n = normalize(v)
    if not n:
        return "?"
    if "DECH" in n or "LIVR" in n or "UNLOAD" in n or n.startswith("D"):
        return "D"
    if "CHARG" in n or "ENLEV" in n or "LOAD" in n or n.startswith("C") or n.startswith("E"):
        return "C"
    return "?"

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
    p = (pays_source or "").upper().strip()
    MAP = {"F": "FR", "B": "BE", "D": "DE", "E": "ES", "I": "IT",
           "L": "LU", "A": "AT", "P": "PT", "UK": "GB"}
    return MAP.get(p, p) if p else "??"

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
def geocode_cached(ville: str, cp: str, pays: str):
    ville = (ville or "").strip()
    if not ville and not cp:
        return None
    ville_exp = re.sub(r'\bST\b', 'SAINT', ville, flags=re.IGNORECASE)
    ville_exp = re.sub(r'\bSTE\b', 'SAINTE', ville_exp, flags=re.IGNORECASE)
    pays_u = (pays or "").upper()
    pays_label = PAYS_MAP_DISPLAY.get(pays_u, pays) if pays else ""
    if PTV_AVAILABLE:
        fix_key = ville.strip().lower()
        if fix_key in GPS_FIXES:
            return GPS_FIXES[fix_key]
        if cp and pays_u:
            iso = PAYS_TO_ISO.get((pays_label or "").lower())
            if not iso and len(pays_u) == 2:
                iso = pays_u
            if iso:
                r = geocode_by_postal_code(cp, iso)
                if r:
                    return r
        for v in ([ville_exp, ville] if ville_exp != ville else [ville]):
            for q in filter(None, [
                f"{v}, {cp}, {pays_label}" if cp and pays_label else None,
                f"{v}, {pays_label}" if pays_label else None, v or None]):
                r = _geocode_by_text(q)
                if r:
                    return r
    else:
        for v in ([ville_exp, ville] if ville_exp != ville else [ville]):
            for q in filter(None, [
                f"{v}, {cp}, {pays_label}" if cp and pays_label else None,
                f"{v}, {pays_label}" if pays_label else None, v or None]):
                r = _photon(q) or _nominatim(q)
                if r:
                    return r
    return None

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
    out["pays"]       = col("pays").fillna("").astype(str).str.strip().str.upper()
    out["produit"]    = col("produit").fillna("").astype(str).str.strip()
    out["chauffeur"]  = col("chauffeur").fillna("").astype(str).str.strip()
    out["depart_trac"]= col("depart_trac").fillna("").astype(str).str.strip()
    out["immat"]      = col("immat").fillna("").astype(str).str.strip()
    out["remorque"]   = col("remorque").fillna("").astype(str).str.strip()
    cp2 = out["cp"].str.extract(r"^(\d{2})", expand=False)
    out["dept"] = out["dept"].where(out["dept"].str.len() > 0, cp2).fillna("")
    out["is_tra"] = out["depart_trac"].str.upper().str.contains("TRA", na=False)
    out["pays_logi"] = out.apply(lambda r: pays_logistique(r["localite"], r["pays"]), axis=1)
    out["_dt"] = out["date"] + pd.to_timedelta(out["_hval"].where(out["_hval"] < 30, 0), unit="h")
    out = out[out["dossier"] != ""].copy()
    out = out.sort_values(["date", "_hval"], na_position="last").reset_index(drop=True)
    act_distinct = (df[C["activite"]].dropna().astype(str).str.strip().value_counts()
                    if C["activite"] else pd.Series(dtype=int))
    return out, C, act_distinct, _date_order

def build_dossier_legs(df):
    legs = {}
    for dos, g in df.groupby("dossier"):
        ch = g[g["type"] == "C"].sort_values("_hval")
        de = g[g["type"] == "D"].sort_values("_hval")
        c0 = ch.iloc[0] if len(ch) else None
        d0 = de.iloc[-1] if len(de) else None
        legs[dos] = {
            "c_loc": c0["localite"] if c0 is not None else "",
            "c_date": c0["date"]    if c0 is not None else pd.NaT,
            "c_cp":   c0["cp"]      if c0 is not None else "",
            "c_pays": c0["pays"]    if c0 is not None else "",
            "d_loc":  d0["localite"]if d0 is not None else "",
            "d_date": d0["date"]    if d0 is not None else pd.NaT,
            "d_cp":   d0["cp"]      if d0 is not None else "",
            "d_pays": d0["pays"]    if d0 is not None else "",
        }
    return legs

def build_trips(d):
    trips = []
    for dos, g in d.groupby("dossier"):
        ch = g[g["type"] == "C"].sort_values("_hval")
        de = g[g["type"] == "D"].sort_values("_hval")
        c  = ch.iloc[0]  if len(ch) else None
        dd = de.iloc[-1] if len(de) else None
        base = c if c is not None else dd
        if base is None:
            continue
        trips.append({
            "dossier": dos,
            "has_c": c is not None, "has_d": dd is not None,
            "c_date": c["date"]   if c is not None else pd.NaT,
            "c_heure":c["heure"]  if c is not None else "",
            "c_loc":  c["localite"]if c is not None else "",
            "c_dept": c["dept"]   if c is not None else "",
            "c_pays": c["pays"]   if c is not None else "",
            "c_site": c["site"]   if c is not None else "",
            "d_date": dd["date"]  if dd is not None else pd.NaT,
            "d_heure":dd["heure"] if dd is not None else "",
            "d_loc":  dd["localite"]if dd is not None else "",
            "d_dept": dd["dept"]  if dd is not None else "",
            "d_pays": dd["pays"]  if dd is not None else "",
            "d_site": dd["site"]  if dd is not None else "",
            "chauffeur": base["chauffeur"], "immat": base["immat"],
            "remorque": base["remorque"],   "depart_trac": base["depart_trac"],
            "is_tra": bool(g["is_tra"].any()),
            "produit": (c["produit"] if c is not None and c["produit"] else base["produit"]),
            "plan_date": (c["date"]  if c is not None else dd["date"]),
            "plan_hval": float(c["_hval"] if c is not None else dd["_hval"]),
        })
    return trips

def html(s: str):
    st.markdown("\n".join(line.lstrip() for line in s.splitlines()), unsafe_allow_html=True)

def build_pays_panel(points_list, show_mode_param):
    from collections import defaultdict
    pays_total  = defaultdict(int)
    pays_detail = defaultdict(list)
    for p in points_list:
        pl = p.get("pays_logi", p.get("pays", "??"))
        ps = p.get("pays", "??")
        n  = p["camions"]
        pays_total[pl] += n
        ps_norm = pays_logistique("__no_override__", ps)
        if pl != ps_norm:
            pays_detail[pl].append((p["nom"], n))
    return pays_total, pays_detail

# ─── Géocodage mis en cache ──────────────────────────────────────────────────
# Construit points_all (tous les lieux, charg + déch) et arcs_all (toutes les
# liaisons charg→déch). Mis en cache : ne se relance QUE si dmap change vraiment.
# Le clic carte / bouton pays / filtre show_mode ne re-géocodent plus rien.
@st.cache_data(show_spinner="📡 Géocodage des lieux…")
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
                "nom": row["localite"], "loc_norm": row["loc_norm"], "label": str(n),
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
                "cn": normalize(lg["c_loc"]), "dn": normalize(lg["d_loc"]),
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
@st.fragment
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
            f'Camions · {title_mode}</div>',
            unsafe_allow_html=True)

        pays_order = sorted(pays_total.keys(), key=lambda k: -pays_total[k])
        for pays_code in pays_order:
            total     = pays_total[pays_code]
            flag      = PAYS_FLAGS.get(pays_code, "🏳️")
            details   = pays_detail.get(pays_code, [])
            is_active = st.session_state["pp_selected_pays"] == pays_code

            detail_html = ""
            if details:
                parts = [f"+{n} {loc}" for loc, n in details[:4]]
                detail_html = '<div class="pp-detail-line">⤷ ' + "  ·  ".join(parts) + '</div>'

            active_style = (
                f"border-color:{val_color};background:#f2faf4;"
                f"box-shadow:0 0 0 1px {val_color}33;"
            ) if is_active else ""

            st.markdown(f"""
<div class="pp-card-btn" style="{active_style};margin-bottom:0;">
  <div class="pp-row-top">
    <span class="pp-flag">{flag}</span>
    <span class="pp-code">{pays_code}</span>
    <span style="font-size:2.2rem;font-weight:600;letter-spacing:-0.02em;color:{val_color};line-height:1;margin-left:auto;">{total}</span>
  </div>
  {detail_html}
</div>""", unsafe_allow_html=True)

            btn_label = "Fermer" if is_active else "Détails"
            btn_type  = "primary" if is_active else "secondary"
            if st.button(btn_label, key=f"pp_btn_{pays_code}",
                         use_container_width=True, type=btn_type):
                st.session_state["pp_selected_pays"] = (None if is_active else pays_code)
                st.session_state["pp_focus_raw"] = None
                st.rerun(scope="fragment")

        if focus_norm:
            if st.button("↩ Vue d'ensemble", key="pp_reset_focus",
                         use_container_width=True, type="primary"):
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
                f"Recliquez le point (ou le fond de carte / « ↩ Vue d'ensemble ») pour revenir.")
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
                        zoom=zoom_level, pitch=25),
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
                    event = st.pydeck_chart(deck, use_container_width=True, height=680,
                                            key=map_key, selection_mode="single-object",
                                            on_select="rerun")
                    new_sel = _read_pydeck_sel(event, map_key)
                    if new_sel != st.session_state.get("pp_focus_raw"):
                        st.session_state["pp_focus_raw"] = new_sel
                        st.rerun(scope="fragment")
                except TypeError:
                    st.pydeck_chart(deck, use_container_width=True, height=680)
                if n_agg >= MAX_GEO and not focus_norm:
                    st.caption(f"Géocodage limité aux {MAX_GEO} lieux les plus actifs.")
            except ImportError:
                st.map(pd.DataFrame(points_map).rename(columns={"lat":"latitude","lon":"longitude"}))

    # ── Détail pays pleine largeur ─────────────────────────────────────────
    if sel_pays and sel_pays in pays_rows:
        flag_s = PAYS_FLAGS.get(sel_pays, "🏳️")
        rows_sel = pays_rows[sel_pays]
        detail_records = []
        for row in rows_sel:
            dos = row["dossier"]
            lg  = legs.get(dos, {})
            detail_records.append({
                "N° Dossier":  dos,
                "Type":        "Chargement" if row["type"] == "C" else (
                               "Déchargement" if row["type"] == "D" else "?"),
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
        df_detail = pd.DataFrame(detail_records).sort_values(["Date", "Heure", "N° Dossier"])
        n_dos = df_detail["N° Dossier"].nunique()
        st.markdown(
            f'<div class="sect">{flag_s} Détail {sel_pays} '
            f'<span class="hint">{n_dos} dossiers · {len(df_detail)} activités</span></div>',
            unsafe_allow_html=True)
        st.dataframe(df_detail, hide_index=True, use_container_width=True,
                     height=min(420, 38 + len(df_detail) * 36))

# ─── Header ──────────────────────────────────────────────────────────────────
ui.page("aide_planning", "Vue planeur : chargements et déchargements par chauffeur, tracteur ou remorque, "
        "flotte CB et tractionnaires confondus.")
st.markdown('<div class="ap-statut"><i></i>PTV routing actif</div>' if PTV_AVAILABLE else
            '<div class="ap-statut off"><i></i>PTV indisponible, géocodage OSM</div>', unsafe_allow_html=True)
st.write("")

up = st.file_uploader("Fichier des activités (chargements / déchargements)", type=["xlsx", "xls"])
if not up:
    st.info("Chargez l'export des activités pour démarrer.")
    st.stop()

df, COLS, ACT_DISTINCT, DATE_ORDER = load_activites(up.read())
if df.empty:
    st.error("Aucune ligne exploitable (colonne « N° Dossier » introuvable ou vide).")
    st.stop()

legs = build_dossier_legs(df)

with st.expander("Debug — colonnes détectées & valeurs Activité"):
    st.write("**Colonnes mappées :**", {k: v for k, v in COLS.items()})
    st.write("**Valeurs distinctes de « Activité » :**")
    st.dataframe(ACT_DISTINCT.rename("Nb").reset_index().rename(columns={"index": "Activité"}),
                 hide_index=True, use_container_width=True)
    n_unknown = int((df["type"] == "?").sum())
    if n_unknown:
        st.warning(f"{n_unknown} activité(s) non classées.")
    _dd = df["date"].dropna()
    if not _dd.empty:
        st.write(f"**Format de date détecté :** `{DATE_ORDER}` — "
                 f"du {_dd.min().strftime('%d/%m/%Y')} au {_dd.max().strftime('%d/%m/%Y')} "
                 f"({_dd.dt.date.nunique()} jours).")

st.markdown('<div class="sect">Filtres planning <span class="hint">multiselect vide = tout confondu</span></div>',
            unsafe_allow_html=True)

f1, f2, f3, f4 = st.columns([1.1, 1.1, .9, 1])
with f1:
    dimension = st.radio("Dimension", ["Chauffeur", "Tracteur (immat.)", "Remorque"], horizontal=True)
    dim_col = {"Chauffeur": "chauffeur", "Tracteur (immat.)": "immat", "Remorque": "remorque"}[dimension]
with f2:
    flotte = st.radio("Périmètre", ["Tous", "Flotte CB", "Tractionnaires"], horizontal=True)
with f3:
    type_tr_f = st.radio("Type transport", ["Tous", "PLA", "CIT"], horizontal=True)
with f4:
    vue = st.radio("Vue", ["Par jour", "Par ressource"], horizontal=True)

df_scope = df.copy()
if flotte == "Flotte CB":
    df_scope = df_scope[~df_scope["is_tra"]]
elif flotte == "Tractionnaires":
    df_scope = df_scope[df_scope["is_tra"]]

if type_tr_f != "Tous":
    df_scope = df_scope[df_scope["type_tr"].str.upper().str.contains(type_tr_f, na=False)]

options = sorted([v for v in df_scope[dim_col].dropna().unique() if str(v).strip()])
g1, g2 = st.columns([2.2, 1])
with g1:
    sel = st.multiselect(f"{dimension} — laisser vide pour tout confondu", options)
with g2:
    dts = df_scope["date"].dropna()
    if not dts.empty:
        dmin, dmax = dts.min().date(), dts.max().date()
        date_range = st.date_input("Période", value=(dmin, dmax),
                                    min_value=dmin, max_value=dmax, format="DD/MM/YYYY")
    else:
        date_range = None

dfx = df_scope.copy()
if sel:
    dfx = dfx[dfx[dim_col].isin(sel)]

def _range_bounds(dr):
    if dr is None:
        return None, None
    if isinstance(dr, (list, tuple)):
        if len(dr) == 0:
            return None, None
        if len(dr) == 1:
            return dr[0], dr[0]
        return dr[0], dr[1]
    return dr, dr

_lo, _hi = _range_bounds(date_range)
if _lo is not None:
    d0 = pd.Timestamp(_lo)
    d1 = pd.Timestamp(_hi) + pd.Timedelta(days=1)
    dfx = dfx[(dfx["date"] >= d0) & (dfx["date"] < d1)]

if dfx.empty:
    avail = sorted(df_scope["date"].dropna().dt.date.unique())
    if avail:
        lst = ", ".join(d.strftime("%d/%m/%Y") for d in avail[:15]) + (" …" if len(avail) > 15 else "")
        st.warning(f"Aucune activité sur cette sélection. Dates disponibles : {lst}")
    else:
        st.warning("Aucune activité ne correspond à ces filtres.")
    st.stop()

n_charg = int((dfx["type"] == "C").sum())
n_dech  = int((dfx["type"] == "D").sum())
n_tra   = int(dfx["is_tra"].sum())

st.markdown('<div class="sect">Carte des activités '
            '<span class="hint">clic sur un point = isole + montre ses liaisons · reclic = vue d\'ensemble</span></div>',
            unsafe_allow_html=True)

MAX_GEO = 120

mc1, mc2, mc3, mc4 = st.columns([1.3, 1, 1, 1.5])
with mc1:
    dates_opt = sorted(dfx["date"].dropna().dt.date.unique())
    date_lbls = ["Toutes les dates"] + [d.strftime("%d/%m/%Y") for d in dates_opt]
    msel_date = st.selectbox("Date (carte)", date_lbls)
with mc2:
    show_mode = st.radio("Afficher", ["Les deux", "Chargements", "Déchargements"], horizontal=True)
with mc3:
    show_arcs = st.checkbox("Relier les points (arcs)", value=True)
with mc4:
    loc_opts = sorted({l for l in dfx["localite"] if str(l).strip()})
    focus_choice = st.selectbox("Isoler un point", ["— tout afficher"] + loc_opts)

dmap = dfx.copy()
if msel_date != "Toutes les dates":
    chosen = pd.to_datetime(msel_date, format="%d/%m/%Y").date()
    dmap = dmap[dmap["date"].dt.date == chosen]

if dmap.empty:
    st.info("Aucune activité pour ces filtres carte.")
else:
    # Focus manuel via selectbox (le clic carte est géré DANS le fragment)
    focus_norm_ext = normalize(focus_choice) if focus_choice != "— tout afficher" else None

    agg = (dmap.assign(loc_norm=dmap["localite"].apply(normalize))
               .groupby(["loc_norm", "type"])
               .agg(localite=("localite", "first"), cp=("cp", "first"),
                    pays=("pays", "first"), pays_logi=("pays_logi", "first"),
                    dept=("dept", "first"),
                    camions=("dossier", "nunique"),
                    dossiers=("dossier", lambda s: ", ".join(sorted(set(s))[:10])))
               .reset_index())
    agg = agg[agg["localite"].str.strip() != ""]
    agg = agg.sort_values("camions", ascending=False).head(MAX_GEO)

    arc_legs = []
    for dos in dmap["dossier"].unique():
        lg = legs.get(dos, {})
        if lg.get("c_loc") or lg.get("d_loc"):
            arc_legs.append({
                "dos":    str(dos),
                "c_loc":  lg.get("c_loc", ""),  "c_cp": lg.get("c_cp", ""),  "c_pays": lg.get("c_pays", ""),
                "d_loc":  lg.get("d_loc", ""),  "d_cp": lg.get("d_cp", ""),  "d_pays": lg.get("d_pays", ""),
            })

    points_all, arcs_all = build_geo_data(
        agg.to_json(orient="records"),
        json.dumps(arc_legs, ensure_ascii=False))

    if not points_all:
        st.info("Aucun lieu géocodé (vérifie le périmètre, ou PTV/OSM indisponible).")
    else:
        from collections import defaultdict
        pays_rows = defaultdict(list)
        for _, row in dmap.iterrows():
            pl = row.get("pays_logi", row.get("pays", "??"))
            pays_rows[pl].append(row)

        render_pays_carte(points_all, arcs_all, len(agg), pays_rows,
                          show_mode, show_arcs, focus_norm_ext, legs, MAX_GEO)

# ─── Regroupements géographiques ─────────────────────────────────────────────
st.markdown('<div class="sect">Regroupements géographiques <span class="hint">≥2 activités même jour · même département</span></div>',
            unsafe_allow_html=True)

clusters = []
for (d, dept, typ), g in dfx[dfx["dept"].str.len() > 0].groupby(
        [dfx["date"].dt.date, "dept", "type"]):
    if typ == "?" or len(g) < 2:
        continue
    clusters.append({
        "date": d, "dept": dept, "type": typ, "n": len(g),
        "pays": g["pays"].mode().iloc[0] if not g["pays"].mode().empty else "",
        "lieux": ", ".join(sorted(set(x for x in g["localite"] if x))[:6]),
    })
clusters.sort(key=lambda c: (-c["n"], c["date"]))

if clusters:
    cc = st.columns(2)
    for i, cl in enumerate(clusters[:12]):
        kind = "Chargements" if cl["type"] == "C" else "Déchargements"
        cls  = "" if cl["type"] == "C" else "d"
        flag = PAYS_FLAGS.get(cl["pays"], "")
        dnom = DEPT_NOM.get(cl["dept"], "")
        dlbl = f"Dépt {cl['dept']}" + (f" · {dnom}" if dnom else "")
        with cc[i % 2]:
            html(f"""
            <div class="cluster {cls}">
              <div class="ch">{flag} {cl['n']} {kind} — {dlbl}</div>
              <div class="cs">{cl['date'].strftime('%d/%m/%Y')} · {cl['lieux']}</div>
            </div>""")
    if len(clusters) > 12:
        st.caption(f"… et {len(clusters) - 12} autre(s) regroupement(s).")
else:
    st.caption("Aucune concentration ≥2 activités sur un même jour/département dans ce périmètre.")

def _badge(t):
    if t["is_tra"]:
        dep = (t["depart_trac"] or "").strip()
        extra = "" if (not dep or dep.upper() == "TRA") else f" · {dep}"
        return f'<span class="tag tra">TRA{extra}</span>'
    return '<span class="tag cb">CB</span>'

def _tags(t, with_badge=True):
    tg = [_badge(t)] if with_badge else []
    if t["chauffeur"]: tg.append(f'<span class="tag">👤 {t["chauffeur"]}</span>')
    if t["immat"]:     tg.append(f'<span class="tag">🚚 {t["immat"]}</span>')
    if t["remorque"]:  tg.append(f'<span class="tag">📦 {t["remorque"]}</span>')
    if t["produit"]:   tg.append(f'<span class="tag prod">🧪 {t["produit"][:22]}</span>')
    return "".join(tg)

def _ddate(t):
    diff = (pd.notna(t["d_date"]) and
            (pd.isna(t["plan_date"]) or t["d_date"].date() != t["plan_date"].date()))
    return f' · {t["d_date"].strftime("%d/%m")}' if diff else ""

with st.expander(f"Planning par jour — {vue}", expanded=False):
    if vue == "Par jour":
        lc1, lc2, _sp = st.columns([1.1, 1.5, 2])
        with lc1:
            layout = st.radio("Disposition", ["Lignes", "Cartes"], horizontal=True, key="layout_pj")
        with lc2:
            densite = st.select_slider("Densité", options=["Compact", "Normal", "Large"],
                                       value="Normal", key="dens_pj")
        dens_cls = {"Compact": "dens-compact", "Normal": "dens-normal", "Large": "dens-large"}[densite]
        df_sel = df_scope[df_scope[dim_col].isin(sel)] if sel else df_scope
        trips  = build_trips(df_sel)
        _lo2, _hi2 = _range_bounds(date_range)
        if _lo2 is not None:
            d0t, d1t = pd.Timestamp(_lo2), pd.Timestamp(_hi2)
            trips = [t for t in trips if pd.notna(t["plan_date"]) and d0t <= t["plan_date"] <= d1t]
        if not trips:
            st.warning("Aucun dossier sur cette période.")
        else:
            from collections import defaultdict
            by_day = defaultdict(list)
            for t in trips:
                by_day[t["plan_date"].date()].append(t)
            for day in sorted(by_day.keys()):
                day_trips = sorted(by_day[day], key=lambda t: t["plan_hval"])
                n_full = sum(1 for t in day_trips if t["has_c"] and t["has_d"])
                html(f'<div class="dayhead">{pd.Timestamp(day).strftime("%A %d %B %Y").capitalize()}'
                     f'<span class="cnt">{len(day_trips)} dossiers · {n_full} avec charg.+déch.</span></div>')
                if layout == "Cartes":
                    parts = ['<div class="trips">']
                    for t in day_trips:
                        cflag, dflag = PAYS_FLAGS.get(t["c_pays"], ""), PAYS_FLAGS.get(t["d_pays"], "")
                        cdept = f' · {t["c_dept"]}' if t["c_dept"] else ""
                        ddept = f' · {t["d_dept"]}' if t["d_dept"] else ""
                        leg_c = (f'<div class="leg c"><span class="lh">{t["c_heure"] or "—"}</span>'
                                 f'<span class="ll">{cflag} {(t["c_loc"] or "?").upper()}{cdept}</span>'
                                 f'<span class="ls">{t["c_site"] or "—"}</span></div>') if t["has_c"] \
                                else '<div class="leg c off">— chargement hors période —</div>'
                        leg_d = (f'<div class="leg d"><span class="lh">{t["d_heure"] or "—"}{_ddate(t)}</span>'
                                 f'<span class="ll">{dflag} {(t["d_loc"] or "?").upper()}{ddept}</span>'
                                 f'<span class="ls">{t["d_site"] or "—"}</span></div>') if t["has_d"] \
                                else '<div class="leg d off">— déchargement hors période —</div>'
                        parts.append(
                            f'<div class="trip"><div class="trip-h">'
                            f'<span class="dos">N° {t["dossier"]}</span>'
                            f'<span class="trip-tags">{_tags(t)}</span></div>'
                            f'{leg_c}<div class="arrow">↓</div>{leg_d}</div>')
                    parts.append('</div>')
                    html("".join(parts))
                else:
                    parts = [f'<div class="rows {dens_cls}">']
                    for t in day_trips:
                        cflag, dflag = PAYS_FLAGS.get(t["c_pays"], ""), PAYS_FLAGS.get(t["d_pays"], "")
                        cdept = f' · {t["c_dept"]}' if t["c_dept"] else ""
                        ddept = f' · {t["d_dept"]}' if t["d_dept"] else ""
                        cell_c = (f'<div class="leg2 c"><span class="lh">{t["c_heure"] or "—"}</span>'
                                  f'<span class="ll">{cflag} {(t["c_loc"] or "?").upper()}{cdept}</span>'
                                  f'<span class="ls">{t["c_site"] or ""}</span></div>') if t["has_c"] \
                                 else '<div class="leg2 off">— chargement hors période —</div>'
                        cell_d = (f'<div class="leg2 d"><span class="lh">{t["d_heure"] or "—"}{_ddate(t)}</span>'
                                  f'<span class="ll">{dflag} {(t["d_loc"] or "?").upper()}{ddept}</span>'
                                  f'<span class="ls">{t["d_site"] or ""}</span></div>') if t["has_d"] \
                                 else '<div class="leg2 off">— déchargement hors période —</div>'
                        parts.append(
                            f'<div class="row">'
                            f'<div class="c1"><span class="dos">N° {t["dossier"]}</span>{_badge(t)}</div>'
                            f'{cell_c}<div class="rarrow">→</div>{cell_d}'
                            f'<div class="res">{_tags(t, with_badge=False)}</div></div>')
                    parts.append('</div>')
                    html("".join(parts))
    else:
        st.markdown(f'<div class="sect">Planning par {dimension.lower()} '
                    f'<span class="hint">enchaînement chronologique des activités</span></div>',
                    unsafe_allow_html=True)
        resources = [r for r in dfx[dim_col].dropna().unique() if str(r).strip()]
        resources = sorted(resources, key=lambda r: -len(dfx[dfx[dim_col] == r]))
        MAX_LANES = 40
        for r in resources[:MAX_LANES]:
            gr = dfx[dfx[dim_col] == r].sort_values(["date", "_hval"])
            is_tra = bool(gr["is_tra"].any())
            nb = len(gr)
            meta_bits = []
            if dim_col != "chauffeur":
                chs = sorted(set(x for x in gr["chauffeur"] if x))
                if chs:
                    meta_bits.append("👤 " + ", ".join(chs[:3]))
            if dim_col != "remorque":
                rms = sorted(set(x for x in gr["remorque"] if x))
                if rms:
                    meta_bits.append("📦 " + ", ".join(rms[:3]))
            tra_badge = '<span class="tag tra" style="font-size:.66rem">TRA</span>' if is_tra else ''
            stops = ""
            for _, row in gr.iterrows():
                kl = "c" if row["type"] == "C" else ("d" if row["type"] == "D" else "")
                dlabel = row["date"].strftime("%d/%m") if pd.notna(row["date"]) else "—"
                stops += (f'<span class="stop {kl}"><span class="t">{dlabel} {row["heure"]}</span>'
                          f'{row["localite"].upper() or "?"}</span>')
            html(f"""
            <div class="lane">
              <div class="who">{tra_badge}{r}
                <span class="meta">· {nb} activités{(" · " + " · ".join(meta_bits)) if meta_bits else ""}</span></div>
              <div class="flow">{stops}</div>
            </div>""")
        if len(resources) > MAX_LANES:
            st.caption(f"Affichage des {MAX_LANES} ressources les plus actives.")

with st.expander("Tableau détaillé + export"):
    show = dfx.copy()
    show["Type"]   = show["type"].map({"C":"Chargement","D":"Déchargement","?":"?"})
    show["Flotte"] = np.where(show["is_tra"], "Tractionnaire", "CB")
    show["Date"]   = show["date"].dt.strftime("%d/%m/%Y")
    table = show[["Date","heure","Type","dossier","localite","dept","pays",
                  "site","produit","chauffeur","immat","remorque","Flotte","depart_trac"]].rename(columns={
        "heure":"Heure","dossier":"N° Dossier","localite":"Localité","dept":"Dépt",
        "pays":"Pays","site":"Site","produit":"Produit","chauffeur":"Chauffeur",
        "immat":"Immat. tracteur","remorque":"Remorque","depart_trac":"Départ. tracteur"})
    st.dataframe(table, hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    table.to_excel(buf, index=False, engine="openpyxl")
    st.download_button("Exporter Excel", data=buf.getvalue(),
                       file_name="planning_plateaux.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
