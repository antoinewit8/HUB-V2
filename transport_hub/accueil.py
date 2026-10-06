"""
accueil.py — Page d'accueil du Transport Hub.
Tous les outils regroupés par catégorie, sur une seule page.
"""

from datetime import datetime

import streamlit as st

from core import ui

ui.page_config("Accueil")
ui.apply_style()

st.markdown("""
<style>
.block-container, [data-testid="stMainBlockContainer"] { max-width: 1180px !important; }

/* Bandeau */
/* Fond : bleu nuit + photo citerne en haut à droite */
.stApp, [data-testid="stAppViewContainer"] { background: var(--hub-night) !important; }
:root { --hub-night: #0c1a2c; }
[data-testid="stAppViewContainer"] { position: relative; }
[data-testid="stMain"] { position: relative; z-index: 1; }

.hub-hero { padding: 72px 0 96px; margin: 0 0 1.4rem; max-width: 560px; }
.hub-hero .hub-hero-logo { height: 76px; border-radius: 12px; display: block; margin-bottom: 30px;
  box-shadow: 0 0 0 1px rgba(255,255,255,.18); }
.hub-hero .eb { font-size: 15px; font-weight: 600; color: rgba(255,255,255,.72); margin: 0 0 8px; }
.hub-hero h1 { font-size: 68px !important; font-weight: 700; letter-spacing: -0.035em; line-height: 1.02;
  color: #fff !important; margin: 0 0 16px; padding: 0; }
.hub-hero p.lead { font-size: 21px; line-height: 1.4; color: rgba(255,255,255,.82) !important; margin: 0; max-width: 30ch; }
.hub-hero .meta { margin-top: 28px; font-size: 13px; color: rgba(255,255,255,.62); display: flex; gap: 18px; flex-wrap: wrap; }
.hub-hero .meta b { color: #fff; font-weight: 600; }
@media (max-width: 800px) {
  .hub-hero { padding: 48px 0 64px; }
  .hub-hero h1 { font-size: 46px !important; }
}

/* Catégories */
.hub-cat { display: flex; align-items: baseline; gap: 12px; margin: 2.2rem 0 .9rem; }
.hub-cat .t { font-size: 26px !important; font-weight: 600; letter-spacing: -0.02em; margin: 0; padding: 0; color: #fff; }
.hub-cat .n { font-size: 14px; color: rgba(255,255,255,.55); }

/* Cartes outils : toute la carte est cliquable */
[class*="st-key-tool_"] { position: relative; background: #fff; border-radius: 20px; padding: 22px 22px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,.2), 0 8px 24px rgba(0,0,0,.18); min-height: 196px; gap: 0 !important;
  transition: transform .18s ease, box-shadow .18s ease; }
[class*="st-key-tool_"]:hover { transform: translateY(-2px);
  box-shadow: 0 2px 4px rgba(0,0,0,.2), 0 16px 40px rgba(0,0,0,.32); }
[class*="st-key-tool_"] * { position: static !important; }
[class*="st-key-tool_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
.hub-card { padding-bottom: 14px; }
[class*="st-key-tool_"] [data-testid="stPageLink"] a::after { content: ""; position: absolute; inset: 0;
  border-radius: 20px; z-index: 2; }
.hub-card .hub-tile { margin-bottom: 16px; }
.hub-card .t { font-size: 19px !important; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 6px !important;
  padding: 0 !important; color: var(--ap-text); }
.hub-card p { font-size: 14px !important; line-height: 1.45; color: var(--ap-sub) !important; margin: 0 !important; }
[class*="st-key-tool_"] [data-testid="stPageLink"] { margin-top: auto; }
[class*="st-key-tool_"] [data-testid="stPageLink"] a { padding: 0; background: transparent !important; }
[class*="st-key-tool_"] [data-testid="stPageLink"] a p,
[class*="st-key-tool_"] [data-testid="stPageLink"] a span { color: var(--ap-blue) !important; font-size: 14px;
  font-weight: 500; }
.hub-foot { margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid rgba(255,255,255,.12);
  font-size: 12px; color: rgba(255,255,255,.5); display: flex; justify-content: space-between; }
</style>
""", unsafe_allow_html=True)

_PHOTO = ui.image_b64("camion.jpg")
st.markdown(f"""<style>
[data-testid="stAppViewContainer"]::before {{
  content: ""; position: absolute; top: 0; right: 0; z-index: 0; pointer-events: none;
  width: min(64vw, 980px); height: 760px;
  background:
    linear-gradient(90deg, var(--hub-night) 0%, rgba(12,26,44,.85) 18%, rgba(12,26,44,0) 55%),
    linear-gradient(0deg, var(--hub-night) 0%, rgba(12,26,44,0) 45%),
    linear-gradient(rgba(12,26,44,.22), rgba(12,26,44,.22)),
    url("data:image/jpeg;base64,{_PHOTO}") center 48% / cover no-repeat;
}}
@media (max-width: 800px) {{
  [data-testid="stAppViewContainer"]::before {{ width: 100vw; height: 560px;
    background:
      linear-gradient(0deg, var(--hub-night) 0%, rgba(12,26,44,.55) 60%, rgba(12,26,44,.35) 100%),
      url("data:image/jpeg;base64,{_PHOTO}") center 48% / cover no-repeat; }}
}}
</style>""", unsafe_allow_html=True)

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
now = datetime.now()
date_fr = f"{JOURS[now.weekday()].capitalize()} {now.day} {MOIS[now.month - 1]} {now.year}"

st.markdown(f"""
<div class="hub-hero">
  <div>
    {ui.logo_tag(76, "hub-hero-logo")}
    <div class="eb">CB Groupe · Transport et logistique</div>
    <h1>Transport Hub</h1>
    <p class="lead">Les outils internes de gestion et d’optimisation des transports, réunis au même endroit.</p>
    <div class="meta"><span><b>{len(ui.TOOLS)}</b> outils</span><span>{date_fr}</span></div>
  </div>
</div>
""", unsafe_allow_html=True)

for cat_key, (cat_label, color) in ui.CATEGORIES.items():
    outils = [t for t in ui.TOOLS if t["cat"] == cat_key]
    if not outils:
        continue
    n = len(outils)
    st.markdown(f'<div class="hub-cat"><div class="t">{cat_label}</div><div class="n">{n} outil{"s" if n > 1 else ""}</div></div>',
                unsafe_allow_html=True)
    for start in range(0, n, 3):
        cols = st.columns(3, gap="medium")
        for col, t in zip(cols, outils[start:start + 3]):
            with col, st.container(key=f"tool_{t['key']}"):
                st.markdown(f'<div class="hub-card">{ui.icon_tile(t["icon"], color, 44)}'
                            f'<div class="t">{t["title"]}</div><p>{t["desc"]}</p></div>', unsafe_allow_html=True)
                st.page_link(ui.page_ref(t["file"]), label="Ouvrir", icon=":material/arrow_forward:")

st.markdown('<div class="hub-foot"><span>Transport Hub · CB Groupe</span>'
            '<span>Usage interne</span></div>', unsafe_allow_html=True)
