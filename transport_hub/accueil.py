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
.hub-hero { display: grid; grid-template-columns: 1.15fr .85fr; gap: 40px; align-items: center;
  background: #fff; border-radius: 28px; padding: 44px 48px; box-shadow: var(--ap-shadow); margin: .4rem 0 2.6rem; }
.hub-hero .hub-hero-logo { height: 76px; border-radius: 12px; display: block; margin-bottom: 26px; }
.hub-hero .eb { font-size: 15px; font-weight: 600; color: var(--ap-sub); margin: 0 0 8px; }
.hub-hero h1 { font-size: 64px !important; font-weight: 700; letter-spacing: -0.035em; line-height: 1.02;
  color: var(--ap-text); margin: 0 0 14px; padding: 0; }
.hub-hero p.lead { font-size: 21px; line-height: 1.4; color: var(--ap-sub); margin: 0; max-width: 30ch; }
.hub-hero .meta { margin-top: 26px; font-size: 13px; color: var(--ap-sub); display: flex; gap: 18px; flex-wrap: wrap; }
.hub-hero .meta b { color: var(--ap-text); font-weight: 600; }
.hub-hero .photo { border-radius: 22px; overflow: hidden; aspect-ratio: 5 / 4; background: #dfe3e8; }
.hub-hero .photo img { width: 100%; height: 100%; object-fit: cover; object-position: center 52%; display: block; }
@media (max-width: 800px) {
  .hub-hero { grid-template-columns: 1fr; padding: 28px 24px; gap: 24px; }
  .hub-hero h1 { font-size: 44px !important; }
}

/* Catégories */
.hub-cat { display: flex; align-items: baseline; gap: 12px; margin: 2.2rem 0 .9rem; }
.hub-cat .t { font-size: 26px !important; font-weight: 600; letter-spacing: -0.02em; margin: 0; padding: 0; }
.hub-cat .n { font-size: 14px; color: var(--ap-sub); }

/* Cartes outils : toute la carte est cliquable */
[class*="st-key-tool_"] { position: relative; background: #fff; border-radius: 20px; padding: 22px 22px 16px;
  box-shadow: var(--ap-shadow); min-height: 196px; gap: 0 !important;
  transition: transform .18s ease, box-shadow .18s ease; }
[class*="st-key-tool_"]:hover { transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0,0,0,.08), 0 0 0 .5px rgba(0,0,0,.06); }
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
.hub-foot { margin-top: 3rem; padding-top: 1.2rem; border-top: .5px solid var(--ap-line);
  font-size: 12px; color: var(--ap-sub); display: flex; justify-content: space-between; }
</style>
""", unsafe_allow_html=True)

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
  <div class="photo"><img src="data:image/jpeg;base64,{ui.image_b64('camion.jpg')}" alt="Citerne CB Groupe"></div>
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
