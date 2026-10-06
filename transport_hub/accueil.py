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
  transition: transform .25s cubic-bezier(.2,.8,.2,1), box-shadow .25s ease; }
[class*="st-key-tool_"]:hover { transform: translateY(-5px);
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
/* Appui sur une carte + arrivée sur l'accueil */
[class*="st-key-tool_"] .hub-tile { transition: transform .3s cubic-bezier(.2,.8,.2,1); }
[class*="st-key-tool_"]:hover .hub-tile { transform: scale(1.08) rotate(-3deg); }
[class*="st-key-tool_"] [data-testid="stPageLink"] a [data-testid="stIconMaterial"] { transition: transform .25s ease; }
[class*="st-key-tool_"]:hover [data-testid="stPageLink"] a [data-testid="stIconMaterial"] { transform: translateX(4px); }
[class*="st-key-tool_"]:active { transform: scale(.975); transition-duration: .08s; }
@keyframes hubIn { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
.hub-hero > div { animation: hubIn .7s cubic-bezier(.2,.8,.2,1) backwards; }
/* backwards et pas both : une fois finie, l'animation ne bloque plus le transform du survol */
.hub-cat, [class*="st-key-tool_"] { animation: hubIn .6s .12s cubic-bezier(.2,.8,.2,1) backwards; }
@media (prefers-reduced-motion: reduce) {
  .hub-hero > div, .hub-cat, [class*="st-key-tool_"] { animation: none; }
}
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

# ─── Transition vers un outil ────────────────────────────────────────────────
# Au clic, la carte s'agrandit jusqu'à remplir l'écran (effet ouverture d'app iOS),
# puis le contenu de l'outil apparaît par vagues. Script installé une seule fois
# sur le document : il reste actif quand on change de page.
_TRANSITION_JS = """
<script>
(() => {
  if (window.__hubAnim) return;
  window.__hubAnim = true;
  const doc = document;
  const EASE = 'cubic-bezier(.32,.72,0,1)';

  function revealTool() {
    const blk = doc.querySelector('[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]');
    if (!blk) return;
    [...blk.children].filter(el => el.offsetHeight > 0).slice(0, 10).forEach((el, i) => {
      el.animate([{ opacity: 0, transform: 'translateY(18px)' }, { opacity: 1, transform: 'none' }],
                 { duration: 560, delay: 40 + i * 45, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' });
    });
  }

  doc.addEventListener('click', (e) => {
    if (window.__hubGo) return;
    const a = e.target.closest('[class*="st-key-tool_"] [data-testid="stPageLink"] a');
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const card = a.closest('[class*="st-key-tool_"]');
    e.preventDefault(); e.stopPropagation();

    const r = card.getBoundingClientRect();
    const ov = doc.createElement('div');
    Object.assign(ov.style, {
      position: 'fixed', left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px',
      borderRadius: '20px', background: '#fff', zIndex: 999999, pointerEvents: 'none', overflow: 'hidden',
      boxShadow: '0 30px 80px rgba(0,0,0,.35)'
    });
    const inner = card.querySelector('.hub-card');
    if (inner) {
      const c = inner.cloneNode(true);
      c.style.cssText = 'padding:22px 22px 0;font-family:inherit';
      ov.appendChild(c);
      c.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: 'ease-out', fill: 'forwards' });
    }
    // Écran de lancement : icône + nom de l'outil au centre, visible si l'outil met du temps à charger
    const tile = card.querySelector('.hub-tile'), name = card.querySelector('.hub-card .t');
    if (tile) {
      const sp = doc.createElement('div');
      sp.style.cssText = 'position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;'
        + 'justify-content:center;gap:18px;opacity:0;font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif';
      const t = tile.cloneNode(true);
      t.style.transform = 'scale(1.6)'; t.style.borderRadius = '14px';
      sp.appendChild(t);
      if (name) {
        const n = doc.createElement('div');
        n.textContent = name.textContent;
        n.style.cssText = 'margin-top:14px;font-size:22px;font-weight:600;letter-spacing:-.02em;color:#1d1d1f';
        sp.appendChild(n);
      }
      ov.appendChild(sp);
      sp.animate([{ opacity: 0, transform: 'scale(.92)' }, { opacity: 1, transform: 'none' }],
                 { duration: 420, delay: 300, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
    }
    doc.body.appendChild(ov);
    card.style.visibility = 'hidden';

    ov.animate([
      { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px',
        borderRadius: '20px', backgroundColor: '#ffffff' },
      { left: '0px', top: '0px', width: innerWidth + 'px', height: innerHeight + 'px',
        borderRadius: '0px', backgroundColor: '#f5f5f7' }
    ], { duration: 540, easing: EASE, fill: 'forwards' });

    // La navigation démarre pendant l'animation : le chargement se fait en parallèle.
    setTimeout(() => { window.__hubGo = true; try { a.click(); } finally { window.__hubGo = false; } }, 90);

    const t0 = performance.now();
    (function wait() {
      const arrived = doc.querySelector('.ap-hero') && !doc.querySelector('.hub-hero');
      const dt = performance.now() - t0;
      if ((arrived && dt > 700) || dt > 8000) {
        revealTool();
        ov.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, easing: 'ease-out', fill: 'forwards' })
          .onfinish = () => ov.remove();
        card.style.visibility = '';
        return;
      }
      setTimeout(wait, 40);
    })();
  }, true);
})();
</script>
"""
try:
    st.html(_TRANSITION_JS, unsafe_allow_javascript=True)
except TypeError:  # Streamlit trop ancien : pas d'animation, navigation normale
    pass
