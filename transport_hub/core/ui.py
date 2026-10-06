"""
core/ui.py — Habillage commun du Transport Hub (style Apple).

Une seule source pour :
  • le registre des outils (titre, description, icône, catégorie) utilisé par
    le routeur (app.py), la page d'accueil et l'en-tête de chaque outil ;
  • la feuille de style partagée (typographie Apple, fond #f5f5f7, cartes
    blanches, boutons pilule) ;
  • les composants d'en-tête : barre du haut (logo + retour accueil), titre,
    sections.

Dans une page :
    from core import ui
    ui.page("lavages")                 # config + style + barre + titre
    ui.section("Fichiers")             # titre de section
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
HOME_FILE = "accueil.py"

FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter", "Helvetica Neue", Arial, sans-serif'

# ─── Catégories et outils ────────────────────────────────────────────────────
CATEGORIES = {
    "cartes":    ("Cartes et itinéraires", "#0071e3"),
    "citernes":  ("Citernes",              "#30a2c8"),
    "planning":  ("Planning",              "#ff9500"),
    "renta":     ("Rentabilité et analyses", "#34a853"),
    "outils":    ("Utilitaires",           "#8e8e93"),
}

# key, fichier, titre, description, icône, catégorie
TOOLS = [
    dict(key="carte_manuelle", file="outils/carte_manuelle.py", title="Carte manuelle", icon="map", cat="cartes",
         desc="Itinéraires poids lourds, péages et kilomètres par pays, traversées. En plein écran."),
    dict(key="calcul_km", file="outils/calcul_km.py", title="Calcul KM PTV", icon="route", cat="cartes",
         desc="Distances PTV pour tout un fichier Excel, péages et mode préférentiel en option."),
    dict(key="cartes_itineraires", file="outils/cartes_itineraires.py", title="Cartes itinéraires", icon="pin",
         cat="cartes", desc="Tracés PTV de chaque trajet d’un fichier, à parcourir sur carte."),
    dict(key="carte_chesca", file="outils/carte_chesca.py", title="Carte Chesca", icon="message", cat="cartes",
         desc="Le message de suivi de Chesca, géolocalisé sur carte avec le tableau de dispatch."),
    dict(key="lavages", file="outils/lavages_citernes.py", title="Lavages citernes", icon="drop", cat="citernes",
         desc="Stations de lavage autour d’une position, prix pratiqués et historique. En plein écran."),
    dict(key="trajets_vides", file="outils/trajets_vides_cit.py", title="Trajets vides CIT", icon="swap",
         cat="citernes", desc="Après un déchargement : les meilleurs endroits où recharger, d’après l’historique."),
    dict(key="aide_planning", file="outils/aide_planning.py", title="Aide planning", icon="calendar",
         cat="planning", desc="Vue planeur des chargements et déchargements, par jour ou par ressource."),
    dict(key="missions_ca_km", file="outils/missions_ca_km.py", title="Missions, CA et KM", icon="euro",
         cat="renta", desc="Missions et chiffre d’affaires consolidés, km chargés et à vide calculés via PTV."),
    dict(key="tractionnaires", file="outils/tractionnaires_km.py", title="Tractionnaires KM", icon="people",
         cat="renta", desc="Km estimés PTV, CA et rentabilité par tractionnaire et par véhicule."),
    dict(key="renta_departements", file="outils/renta_departements.py", title="Rentabilité par département",
         icon="pie", cat="renta", desc="Lot sec ou groupage, km en route chaînée et km à vide par département."),
    dict(key="renta_benne", file="outils/renta_benne.py", title="Rentabilité benne", icon="truck", cat="renta",
         desc="Rotations benne : CA, km chargés, km à vide et rentabilité au kilomètre."),
    dict(key="txflex", file="outils/analyse_txflex.py", title="Analyse TX-FLEX", icon="gauge", cat="renta",
         desc="Fichiers TX-FLEX : km à vide, alertes du vendredi et rapport Excel."),
    dict(key="gasoil", file="outils/prix_gasoil.py", title="Prix gasoil", icon="fuel", cat="outils",
         desc="Prix officiels SPF Economie, tendances et calcul du coût carburant."),
    dict(key="codes_postaux", file="outils/codes_postaux.py", title="Codes postaux", icon="mail", cat="outils",
         desc="Complète les codes postaux manquants d’un fichier Excel via PTV."),
    dict(key="ocr", file="outils/ocr_pdf.py", title="OCR et PDF", icon="doc", cat="outils",
         desc="Rend un PDF scanné cherchable, ou améliore sa lisibilité."),
    dict(key="ressources", file="outils/ressources.py", title="Ressources", icon="link", cat="outils",
         desc="Liens utiles : fichiers Excel, Google Sheets, PDF et documents."),
    dict(key="cache", file="outils/cache.py", title="Cache", icon="trash", cat="outils",
         desc="Vider les caches de calcul KM et la base des routes du serveur carte."),
]
TOOLS_BY_KEY = {t["key"]: t for t in TOOLS}

# ─── Icônes (traits 24×24, blanc sur tuile de couleur) ───────────────────────
ICONS = {
    "map": '<path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    "route": '<circle cx="6" cy="18.5" r="2.3"/><circle cx="18" cy="5.5" r="2.3"/>'
             '<path d="M8.3 18.5H16.5a3.25 3.25 0 0 0 0-6.5h-9a3.25 3.25 0 0 1 0-6.5h8.2"/>',
    "pin": '<path d="M12 21s-6.5-5.9-6.5-11a6.5 6.5 0 0 1 13 0c0 5.1-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/>',
    "message": '<path d="M4.5 5.5h15a1.5 1.5 0 0 1 1.5 1.5v8.5a1.5 1.5 0 0 1-1.5 1.5H10l-5 3.5V17h-.5A1.5 1.5 0 0 1 3 15.5V7a1.5 1.5 0 0 1 1.5-1.5z"/><path d="M7.5 10h9M7.5 13h5.5"/>',
    "drop": '<path d="M12 3.2s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z"/><path d="M9.2 15a2.9 2.9 0 0 0 2.8 2.6"/>',
    "swap": '<path d="M4 8h13M13.5 4.5 17 8l-3.5 3.5"/><path d="M20 16H7M10.5 12.5 7 16l3.5 3.5"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'
                '<path d="M7.5 13.5h3M13.5 13.5h3M7.5 16.5h3"/>',
    "euro": '<path d="M17.5 6.6A7 7 0 1 0 17.5 17.4"/><path d="M4.5 10.5h9M4.5 13.5h9"/>',
    "people": '<circle cx="9" cy="8.5" r="3.3"/><path d="M3 19.5a6 6 0 0 1 12 0"/>'
              '<path d="M15.5 5.4a3.3 3.3 0 0 1 0 6.2M17.5 14a6 6 0 0 1 3.5 5.5"/>',
    "pie": '<path d="M11 4.1A8 8 0 1 0 19.9 13H11z"/><path d="M14 3.2A8 8 0 0 1 20.8 10H14z"/>',
    "truck": '<path d="M2.5 6.5h11.5v10H2.5z"/><path d="M14 9.5h3.8l3.2 3.4v3.6H14"/>'
             '<circle cx="6.5" cy="17.5" r="1.9"/><circle cx="17" cy="17.5" r="1.9"/>',
    "gauge": '<path d="M4.2 17.5a8.5 8.5 0 1 1 15.6 0"/><path d="m12 13.5 4-4.5"/><circle cx="12" cy="13.8" r="1.2"/>',
    "fuel": '<path d="M4.5 20.5V5.5a2 2 0 0 1 2-2h5a2 2 0 0 1 2 2v15M3 20.5h12M4.5 10h9"/>'
            '<path d="M13.5 8.5h1.8a1.7 1.7 0 0 1 1.7 1.7v5.6a1.5 1.5 0 0 0 3 0V8.3l-2.8-2.8"/>',
    "mail": '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="m3.8 7.5 8.2 5.8 8.2-5.8"/>',
    "doc": '<path d="M14 3H7.5A2 2 0 0 0 5.5 5v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7.5z"/><path d="M14 3v4.5h4.5"/>'
           '<path d="M8.8 12.5h6.4M8.8 16h6.4"/>',
    "link": '<path d="M10 14a4.3 4.3 0 0 0 6.1 0l3-3A4.3 4.3 0 0 0 13 4.9l-1 1"/>'
            '<path d="M14 10a4.3 4.3 0 0 0-6.1 0l-3 3a4.3 4.3 0 0 0 6.1 6.1l1-1"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6.2 7l.9 12.2a1.5 1.5 0 0 0 1.5 1.3h6.8a1.5 1.5 0 0 0 1.5-1.3L17.8 7"/>'
             '<path d="M10 11v5.5M14 11v5.5"/>',
}


def icon_tile(icon: str, color: str, size: int = 44) -> str:
    """Tuile carrée arrondie façon icône iOS, pictogramme blanc."""
    radius = round(size * 0.26)
    glyph = round(size * 0.56)
    return (f'<span class="hub-tile" style="width:{size}px;height:{size}px;border-radius:{radius}px;'
            f'background:{color};"><svg width="{glyph}" height="{glyph}" viewBox="0 0 24 24" fill="none" '
            f'stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS.get(icon, "")}</svg></span>')


# ─── Images ──────────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def image_b64(name: str) -> str:
    path = ASSETS / name
    return base64.b64encode(path.read_bytes()).decode() if path.exists() else ""


def logo_tag(height: int = 32, css_class: str = "hub-logo") -> str:
    b64 = image_b64("logo_cb.jpg")
    return f'<img class="{css_class}" src="data:image/jpeg;base64,{b64}" style="height:{height}px" alt="CB Groupe">'


# ─── Feuille de style commune ────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {
  --ap-bg: #f5f5f7; --ap-card: #ffffff; --ap-text: #1d1d1f; --ap-sub: #6e6e73; --ap-line: #d2d2d7;
  --ap-hair: #e5e5ea; --ap-soft: #e8e8ed; --ap-blue: #0071e3; --ap-blue-hover: #0077ed;
  --ap-green: #248a3d; --ap-red: #d70015; --ap-orange: #c93400;
  --ap-shadow: 0 1px 2px rgba(0,0,0,.04), 0 0 0 .5px rgba(0,0,0,.06);
  --ap-font: __FONT__;
}

/* Fond, typographie, largeur */
.stApp, [data-testid="stAppViewContainer"] { background: var(--ap-bg) !important; }
[data-testid="stMain"] *:not([data-testid="stIconMaterial"]):not([class*="material-symbols"]):not(code):not(pre),
section.main *:not([data-testid="stIconMaterial"]):not([class*="material-symbols"]):not(code):not(pre) {
  font-family: var(--ap-font);
}
[data-testid="stMain"] { -webkit-font-smoothing: antialiased; }
[data-testid="stHeader"] { background: transparent !important; }
.block-container, [data-testid="stMainBlockContainer"] {
  max-width: 1100px !important; padding-top: 4.25rem !important; padding-bottom: 4rem !important;
}
[data-testid="stMain"] p, [data-testid="stMain"] label, [data-testid="stMain"] li,
section.main p, section.main label { color: var(--ap-text); }
[data-testid="stMain"] [data-testid="stCaptionContainer"] p,
[data-testid="stMain"] [data-testid="stCaptionContainer"] { color: var(--ap-sub); }

/* Pas de barre latérale : la navigation passe par l'accueil */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarNav"] { display: none !important; }
.stDeployButton, [data-testid="stAppDeployButton"], #MainMenu, footer { display: none !important; }

/* Titres Markdown (st.subheader, ###, ####) */
[data-testid="stMain"] h1 { font-size: 40px; font-weight: 700; letter-spacing: -0.03em; color: var(--ap-text); }
[data-testid="stMain"] h2 { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; color: var(--ap-text); }
[data-testid="stMain"] h3 { font-size: 22px; font-weight: 600; letter-spacing: -0.015em; color: var(--ap-text); }
[data-testid="stMain"] h4, [data-testid="stMain"] h5 { font-size: 17px; font-weight: 600; letter-spacing: -0.01em; color: var(--ap-text); }
[data-testid="stMain"] hr { border-color: var(--ap-hair) !important; margin: 1.6rem 0 !important; }

/* Barre du haut */
.st-key-hub_topbar { padding: 0 0 .4rem; margin-bottom: 1.6rem; border-bottom: .5px solid var(--ap-line); }
.st-key-hub_topbar [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
.st-key-hub_topbar [data-testid="stElementContainer"] { width: auto !important; }
.hub-brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
.hub-brand img { border-radius: 6px; display: block; }
.hub-brand span { font-size: 14px; font-weight: 600; letter-spacing: -0.01em; color: var(--ap-text); }
.hub-brand em { font-style: normal; color: var(--ap-sub); font-weight: 400; }
.st-key-hub_topbar [data-testid="stPageLink"] a {
  background: transparent; border-radius: 980px; padding: 8px 16px 8px 12px; min-height: 0;
  position: relative; z-index: 1000; cursor: pointer;
}
.st-key-hub_topbar [data-testid="stPageLink"] a:hover { background: var(--ap-soft); }
.st-key-hub_topbar [data-testid="stPageLink"] a p,
.st-key-hub_topbar [data-testid="stPageLink"] a span { color: var(--ap-blue) !important; font-size: 14px; font-weight: 500; }

/* En-tête de page */
.hub-tile { display: inline-flex; align-items: center; justify-content: center; flex: none;
  box-shadow: inset 0 0 0 .5px rgba(0,0,0,.08); }
.ap-hero { margin-bottom: .4rem; }
.ap-hero .hub-tile { margin-bottom: 14px; }
.ap-hero .ap-eyebrow { font-size: 13px; font-weight: 600; color: var(--ap-sub); letter-spacing: 0; margin: 0 0 6px; }
.ap-hero h1 { font-size: 48px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.05; color: var(--ap-text);
  margin: 0 0 .5rem; padding: 0; }
.ap-hero p { font-size: 21px; line-height: 1.38; color: var(--ap-sub); margin: 0 0 1.5rem; max-width: 52ch; }
.ap-hero h1, .hub-hero h1 { padding: 0 !important; }
.ap-hero [data-testid="stHeaderActionElements"], .hub-hero [data-testid="stHeaderActionElements"] { display: none !important; }
.ap-section { font-size: 24px; font-weight: 600; letter-spacing: -0.015em; color: var(--ap-text);
  border-top: 1px solid var(--ap-hair); padding-top: 1.4rem; margin: 2rem 0 1rem; }
.sect { font-size: 24px; font-weight: 600; letter-spacing: -0.015em; color: var(--ap-text);
  border-top: 1px solid var(--ap-hair); padding-top: 1.4rem; margin: 2rem 0 1rem; }
.sect .hint { font-size: 14px; font-weight: 400; letter-spacing: 0; color: var(--ap-sub); margin-left: 8px; }
.ap-list { margin: 0 !important; padding: 0 !important; list-style: none; max-width: 62ch; }
.ap-list li { margin: 0 !important; font-size: 15px; line-height: 1.5; color: var(--ap-text);
  padding: 9px 0; border-bottom: .5px solid var(--ap-hair); }
.ap-list li b { font-weight: 600; }
.ap-list li span { color: var(--ap-sub); }
.ap-statut { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ap-sub); margin-top: 6px; }
.ap-statut i { width: 8px; height: 8px; border-radius: 50%; background: #34c759; }
.ap-statut.off i { background: #ff9f0a; }
.ap-card { background: var(--ap-card); border-radius: 18px; padding: 18px 20px; box-shadow: var(--ap-shadow);
  color: var(--ap-text); margin-bottom: 1rem; line-height: 1.55; }
.ap-card h4 { margin: 0 0 .5rem; font-size: 17px; font-weight: 600; }
.ap-note { font-size: 14px; color: var(--ap-sub); background: var(--ap-card); border-radius: 14px;
  padding: 12px 16px; box-shadow: var(--ap-shadow); margin: 1rem 0; }

/* Indicateurs */
[data-testid="stMetric"] { background: var(--ap-card); border-radius: 18px; padding: 16px 18px; box-shadow: var(--ap-shadow); }
[data-testid="stMetricValue"] div, [data-testid="stMetricValue"] { font-weight: 600; letter-spacing: -0.02em; color: var(--ap-text); }
[data-testid="stMetricLabel"] p { color: var(--ap-sub) !important; font-size: 13px; }

/* Champs, dépôts de fichiers, blocs dépliants, tableaux */
[data-testid="stFileUploaderDropzone"] { background: var(--ap-card); border: 1px dashed #c7c7cc; border-radius: 14px; }
[data-testid="stFileUploaderDropzone"] button { border-radius: 980px; }
[data-testid="stExpander"] details { background: var(--ap-card); border: 1px solid var(--ap-hair); border-radius: 14px; }
[data-testid="stExpander"] summary p { font-weight: 500; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 12px; overflow: hidden; }
[data-testid="stAlert"] > div { border-radius: 14px; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius: 10px !important; }
[data-testid="stTabs"] [data-baseweb="tab"] p { font-weight: 500; }
[data-testid="stMain"] iframe { border: none; }

/* Boutons : pilule grise (secondaire) ou bleue (principal) */
[data-testid="stMain"] .stDownloadButton > button, [data-testid="stMain"] .stButton > button,
[data-testid="stMain"] .stFormSubmitButton > button, [data-testid="stMain"] [data-testid="stLinkButton"] a {
  border-radius: 980px; border: none; background: var(--ap-soft); min-height: 42px; padding: 0 20px; box-shadow: none;
}
[data-testid="stMain"] .stDownloadButton > button p, [data-testid="stMain"] .stButton > button p,
[data-testid="stMain"] .stFormSubmitButton > button p, [data-testid="stMain"] [data-testid="stLinkButton"] a p {
  color: var(--ap-blue) !important; font-weight: 500;
}
[data-testid="stMain"] .stDownloadButton > button:hover, [data-testid="stMain"] .stButton > button:hover,
[data-testid="stMain"] .stFormSubmitButton > button:hover { background: #dedee3; }
[data-testid="stMain"] button[kind="primary"], [data-testid="stMain"] button[data-testid="stBaseButton-primary"] {
  background: var(--ap-blue) !important;
}
[data-testid="stMain"] button[kind="primary"] p, [data-testid="stMain"] button[data-testid="stBaseButton-primary"] p {
  color: #fff !important;
}
[data-testid="stMain"] button[kind="primary"]:hover, [data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover {
  background: var(--ap-blue-hover) !important;
}
</style>
""".replace("__FONT__", FONT)


def apply_style():
    st.markdown(CSS, unsafe_allow_html=True)


def page_config(title: str):
    try:
        st.set_page_config(page_title=f"{title} · Transport Hub", page_icon=str(ASSETS / "logo_cb.jpg"),
                           layout="wide", initial_sidebar_state="collapsed")
    except Exception:
        pass


def page_ref(file: str):
    """Objet page déclaré par app.py (repli : chemin du fichier)."""
    return st.session_state.get("_hub_pages", {}).get(file, file)


def topbar(home: bool = False):
    """Logo + nom du hub à gauche, retour à l'accueil à droite."""
    with st.container(key="hub_topbar", horizontal=True, vertical_alignment="center",
                      horizontal_alignment="distribute"):
        st.markdown(f'<div class="hub-brand">{logo_tag(30)}<span>Transport Hub <em>· CB Groupe</em></span></div>',
                    unsafe_allow_html=True)
        if not home:
            st.page_link(page_ref(HOME_FILE), label="Tous les outils", icon=":material/apps:")


def hero(title: str, subtitle: str = "", icon: str | None = None, color: str | None = None, eyebrow: str = ""):
    tile = icon_tile(icon, color or "#0071e3", 52) if icon else ""
    eb = f'<div class="ap-eyebrow">{eyebrow}</div>' if eyebrow else ""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f'<div class="ap-hero">{tile}{eb}<h1>{title}</h1>{sub}</div>', unsafe_allow_html=True)


def section(title: str):
    st.markdown(f'<div class="ap-section">{title}</div>', unsafe_allow_html=True)


def page(key: str, subtitle: str | None = None, title: str | None = None):
    """En-tête complet d'un outil : config, style, barre du haut, titre."""
    tool = TOOLS_BY_KEY[key]
    cat_label, color = CATEGORIES[tool["cat"]]
    page_config(title or tool["title"])
    apply_style()
    topbar()
    hero(title or tool["title"], tool["desc"] if subtitle is None else subtitle,
         icon=tool["icon"], color=color, eyebrow=cat_label)
