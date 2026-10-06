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

/* Barre de pastilles par catégorie (collante, verre dépoli une fois collée) */
/* Streamlit enveloppe le conteneur dans un stLayoutWrapper : c'est lui qui doit coller */
[data-testid="stLayoutWrapper"]:has(> .st-key-hub_pills) { position: sticky; top: 22px; z-index: 50; }
.st-key-hub_pills { margin: -.6rem 0 .4rem; width: fit-content;
  max-width: 100%; padding: 6px; border-radius: 980px; transition: background .3s ease, box-shadow .3s ease; }
.st-key-hub_pills.stuck { background: rgba(12,26,44,.62); -webkit-backdrop-filter: saturate(160%) blur(18px);
  backdrop-filter: saturate(160%) blur(18px); box-shadow: 0 0 0 1px rgba(255,255,255,.1), 0 10px 30px rgba(0,0,0,.35); }
.st-key-hub_pills [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
.hub-pills { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.hub-pills::-webkit-scrollbar { display: none; }
.hub-pill { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 980px;
  font-size: 14px; font-weight: 500; white-space: nowrap; text-decoration: none !important; cursor: pointer;
  color: rgba(255,255,255,.86) !important; background: rgba(255,255,255,.08);
  transition: background .25s ease, color .25s ease, transform .15s ease; }
.hub-pill:hover { background: rgba(255,255,255,.16); }
.hub-pill:active { transform: scale(.96); }
.hub-pill i { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.hub-pill span { color: rgba(255,255,255,.5); font-weight: 400; transition: color .25s ease; }
.hub-pill.on { background: #fff; color: #1d1d1f !important; }
.hub-pill.on span { color: #6e6e73; }

/* Catégories */
.hub-cat { display: flex; align-items: baseline; gap: 12px; margin: 2.2rem 0 .9rem; scroll-margin-top: 84px; }
.hub-cat .t { font-size: 26px !important; font-weight: 600; letter-spacing: -0.02em; margin: 0; padding: 0; color: #fff; }
.hub-cat .n { font-size: 14px; color: rgba(255,255,255,.55); }

/* Cartes outils : toute la carte est cliquable */
[class*="st-key-tool_"] { position: relative; background: #fff; border-radius: 20px; padding: 22px 22px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,.2), 0 8px 24px rgba(0,0,0,.18); min-height: 196px; gap: 0 !important;
  transition: transform .25s cubic-bezier(.2,.8,.2,1), box-shadow .3s ease; --hub-c: #0071e3; --mx: 50%; --my: 0%; }
/* Survol : halo de la couleur de la catégorie */
[class*="st-key-tool_"]:hover { transform: translateY(-5px);
  box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--hub-c) 70%, transparent),
              0 0 32px 2px color-mix(in srgb, var(--hub-c) 45%, transparent),
              0 18px 44px rgba(0,0,0,.34); }
/* Reflet qui suit la souris (position mise à jour en JS via --mx / --my) */
[class*="st-key-tool_"]::before { content: ""; position: absolute; inset: 0; border-radius: 20px; z-index: 1;
  pointer-events: none; opacity: 0; transition: opacity .3s ease;
  background: radial-gradient(280px circle at var(--mx) var(--my),
              color-mix(in srgb, var(--hub-c) 10%, transparent), transparent 70%); }
[class*="st-key-tool_"]:hover::before { opacity: 1; }
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
/* Cascade : chaque carte reçoit son propre délai (voir _CARD_CSS plus bas).
   backwards et pas both : une fois finie, l'animation ne bloque plus le transform du survol */
.hub-cat, .st-key-hub_pills { animation: hubIn .6s .12s cubic-bezier(.2,.8,.2,1) backwards; }
@keyframes hubCard { from { opacity: 0; transform: translateY(26px) scale(.96); } to { opacity: 1; transform: none; } }
[class*="st-key-tool_"] { animation: hubCard .7s .2s cubic-bezier(.2,.8,.2,1) backwards; }
/* Retour depuis un outil : l'accueil se construit sous un voile, animations en pause
   jusqu'à ce que tout soit prêt (classe posée/retirée par le JS de transition) */
html.hub-hold .hub-hero > div, html.hub-hold .hub-cat, html.hub-hold .st-key-hub_pills,
html.hub-hold [class*="st-key-tool_"] { animation-play-state: paused !important; }
@media (prefers-reduced-motion: reduce) {
  .hub-hero > div, .hub-cat, .st-key-hub_pills, [class*="st-key-tool_"] { animation: none; }
  [class*="st-key-tool_"]::before { display: none; }
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

CATS = [(k, lbl, col, [t for t in ui.TOOLS if t["cat"] == k]) for k, (lbl, col) in ui.CATEGORIES.items()]
CATS = [c for c in CATS if c[3]]

# Barre de pastilles : un clic fait défiler jusqu'à la catégorie (géré en JS plus bas)
with st.container(key="hub_pills"):
    st.markdown('<nav class="hub-pills">' + "".join(
        f'<a class="hub-pill" href="#cat-{k}" data-cat="{k}"><i style="background:{col}"></i>{lbl}<span>{len(o)}</span></a>'
        for k, lbl, col, o in CATS) + "</nav>", unsafe_allow_html=True)

# Couleur de catégorie + délai de cascade propres à chaque carte
_CARD_CSS, i = [], 0
for k, lbl, col, outils in CATS:
    for t in outils:
        _CARD_CSS.append(f'.st-key-tool_{t["key"]} {{ --hub-c: {col}; animation-delay: {0.2 + min(i, 14) * 0.05:.2f}s; }}')
        i += 1
st.markdown("<style>" + "\n".join(_CARD_CSS) + "</style>", unsafe_allow_html=True)

for cat_key, cat_label, color, outils in CATS:
    n = len(outils)
    st.markdown(f'<div class="hub-cat" id="cat-{cat_key}" data-cat="{cat_key}"><div class="t">{cat_label}</div>'
                f'<div class="n">{n} outil{"s" if n > 1 else ""}</div></div>', unsafe_allow_html=True)
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
  const doc = document, html = doc.documentElement;
  const EASE = 'cubic-bezier(.32,.72,0,1)';
  const OUT = 'cubic-bezier(.2,.8,.2,1)';
  const NIGHT = '#0c1a2c';
  const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Toutes les animations ci-dessous ne touchent qu'à transform et opacity : le navigateur
  // les joue sur la carte graphique, elles restent fluides même quand Streamlit bloque la
  // page pendant qu'il construit la suivante (130 à 380 ms mesurés).

  // Attend que la page cible soit là, que Streamlit ait fini de la construire (nombre
  // d'éléments stable, plus d'élément périmé) et que le navigateur respire (images < 40 ms),
  // le tout pendant ~150 ms d'affilée. Sinon, des éléments remplacés après coup relancent
  // leurs animations et la page clignote.
  function whenReady(test, cb, maxMs = 8000) {
    const t0 = performance.now();
    let last = t0, since = 0, prevN = -1;
    (function f(now) {
      const dt = now - last; last = now;
      const n = doc.querySelectorAll('[data-testid="stMain"] *').length;
      const ok = test() && dt < 40 && n === prevN && !doc.querySelector('[data-stale="true"]');
      prevN = n;
      since = ok ? (since || now) : 0;
      if ((since && now - since > 150) || now - t0 > maxMs) return cb();
      requestAnimationFrame(f);
    })(t0);
  }

  function layer(css) {
    const el = doc.createElement('div');
    el.style.cssText = 'position:fixed;left:0;top:0;pointer-events:none;' + css;
    return el;
  }

  // Contenu de l'outil qui apparaît par vagues. Le bloc qui contient `still` (le titre, où
  // l'icône vient se poser) n'a qu'un fondu : s'il glissait, l'icône viserait une cible mobile.
  function revealTool(still) {
    const blk = doc.querySelector('[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]');
    if (!blk) return;
    [...blk.children].filter(el => el.offsetHeight > 0).slice(0, 10).forEach((el, i) => {
      const fixed = still && el.contains(still);
      el.animate(fixed ? [{ opacity: 0 }, { opacity: 1 }]
                       : [{ opacity: 0, transform: 'translateY(14px)' }, { opacity: 1, transform: 'none' }],
                 { duration: 520, delay: i * 40, easing: OUT, fill: 'backwards' });
    });
  }

  // ─── Accueil → outil ───
  // 1. fondu doux vers le bleu nuit de l'accueil
  // 2. le pictogramme se dessine trait par trait au centre, avec le nom de l'outil
  // 3. il pulse pendant que Streamlit charge l'outil
  // 4. l'écran de couleur s'efface, le pictogramme s'envole en grossissant, l'outil apparaît
  doc.addEventListener('click', (e) => {
    if (window.__hubGo) return;
    const a = e.target.closest('[class*="st-key-tool_"] [data-testid="stPageLink"] a');
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || calm()) return;
    const card = a.closest('[class*="st-key-tool_"]');
    const tile = card.querySelector('.hub-tile');
    if (!tile) return;
    e.preventDefault(); e.stopPropagation();

    const W = innerWidth, H = innerHeight;
    const color = getComputedStyle(tile).backgroundColor;   // couleur de la catégorie : sert à l'icône
    const SOFT = 'cubic-bezier(.45,0,.25,1)';                // ease-in-out doux pour les fondus
    const root = layer(`width:${W}px;height:${H}px;z-index:999999;`);

    // Fond : fondu plein écran vers le bleu nuit de l'accueil (opacité seule, accélérée)
    const full = layer(`width:${W}px;height:${H}px;background:${NIGHT};opacity:0;will-change:opacity;`);
    root.append(full);

    // Pictogramme dessiné à sa taille réelle (net), chaque trait se trace l'un après l'autre
    const S = 104;
    const sp = layer(`width:${W}px;height:${H}px;display:flex;flex-direction:column;align-items:center;`
      + 'justify-content:center;gap:22px;font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif;');
    const ico = doc.createElement('div');
    ico.style.cssText = `width:${S}px;height:${S}px;will-change:transform,opacity;`;
    const src = tile.querySelector('svg');
    const svg = src ? src.cloneNode(true) : doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', S); svg.setAttribute('height', S);
    svg.setAttribute('stroke-width', '1.5');
    svg.setAttribute('stroke', color);                       // seule l'icône prend la couleur de l'outil
    svg.style.display = 'block';
    const strokes = [...svg.querySelectorAll('path, circle, rect, line, polyline, polygon, ellipse')];
    // Trait caché au départ (opacité 0) : sinon ses bouts arrondis apparaissent déjà en petits points
    strokes.forEach(el => { el.setAttribute('pathLength', '1');
                            el.style.strokeDasharray = '1 1'; el.style.strokeDashoffset = '1'; el.style.opacity = '0'; });
    ico.appendChild(svg);
    const nm = card.querySelector('.hub-card .t');
    const label = doc.createElement('div');
    label.textContent = nm ? nm.textContent : '';
    label.style.cssText = 'font-size:24px;font-weight:600;letter-spacing:-.02em;color:#fff;opacity:0;'
      + 'will-change:opacity,transform;';
    sp.append(ico, label);
    root.appendChild(sp);
    doc.body.appendChild(root);

    full.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, easing: SOFT, fill: 'forwards' });

    // Tracé : ~450 ms au total, traits décalés
    const DRAW0 = 260, per = Math.min(300, 420 / Math.max(1, strokes.length));
    strokes.forEach((el, i) => el.animate([{ strokeDashoffset: 1, opacity: 0 }, { opacity: 1, offset: .08 },
                                           { strokeDashoffset: 0, opacity: 1 }],
      { duration: 300, delay: DRAW0 + i * per * .6, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' }));
    const drawEnd = DRAW0 + (strokes.length - 1) * per * .6 + 300;
    label.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
                  { duration: 360, delay: DRAW0 + 120, easing: OUT, fill: 'forwards' });

    // Pulsation pendant le chargement (transform seul : continue même si la page est occupée)
    let pulse = null;
    setTimeout(() => {
      pulse = ico.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.07)' }, { transform: 'scale(1)' }],
                          { duration: 1100, iterations: Infinity, easing: 'ease-in-out' });
    }, drawEnd);

    // Navigation une fois le tracé fini : le tracé passe par le fil principal, que Streamlit
    // bloque 100 à 400 ms en construisant la page suivante.
    setTimeout(() => { window.__hubGo = true; try { a.click(); } finally { window.__hubGo = false; } }, drawEnd + 20);

    const t0 = performance.now();
    whenReady(() => doc.querySelector('.ap-hero') && !doc.querySelector('.hub-hero')
                    && performance.now() - t0 > drawEnd + 200, () => {
      revealTool();
      if (pulse) pulse.cancel();
      ico.animate([{ transform: 'scale(1)', opacity: 1 }, { transform: 'scale(1.5)', opacity: 0 }],
                  { duration: 380, easing: 'cubic-bezier(.4,0,1,1)', fill: 'forwards' });
      label.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: 'ease-out', fill: 'forwards' });
      full.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 520, delay: 60, easing: SOFT, fill: 'forwards' });
      setTimeout(() => root.remove(), 620);
    });
  }, true);

  // ─── Outil → accueil : fondu bleu nuit, puis cascade une fois l'accueil prêt ───
  doc.addEventListener('click', (e) => {
    if (window.__hubBack) return;
    const a = e.target.closest('.st-key-hub_topbar [data-testid="stPageLink"] a');
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || calm()) return;
    e.preventDefault(); e.stopPropagation();

    // Contenu de l'outil qui recule légèrement, voile bleu nuit par-dessus
    const main = doc.querySelector('[data-testid="stMainBlockContainer"]');
    const recul = main && main.animate([{ transform: 'none', opacity: 1 }, { transform: 'scale(.97)', opacity: .6 }],
                                       { duration: 260, easing: OUT, fill: 'forwards' });
    const cover = layer(`width:100vw;height:100vh;z-index:999999;background:${NIGHT};opacity:0;will-change:opacity;`);
    doc.body.appendChild(cover);
    cover.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: 'cubic-bezier(.45,0,.25,1)', fill: 'forwards' });
    html.classList.add('hub-hold');   // l'accueil se construit sous le voile, animations en pause

    // Navigation une fois le voile posé : le blocage de Streamlit se passe derrière
    setTimeout(() => { window.__hubBack = true; try { a.click(); } finally { window.__hubBack = false; } }, 310);

    const t0 = performance.now();
    whenReady(() => doc.querySelector('.hub-foot') && !doc.querySelector('.ap-hero')
                    && performance.now() - t0 > 300, () => {
      // Le conteneur principal est réutilisé par Streamlit d'une page à l'autre : sans ça,
      // l'accueil resterait à 97 % et 60 % d'opacité (page floue et délavée)
      if (recul) recul.cancel();
      html.classList.remove('hub-hold');
      cover.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 480, easing: 'cubic-bezier(.45,0,.25,1)', fill: 'forwards' })
        .onfinish = () => cover.remove();
    });
  }, true);
})();

// ─── Effets de l'accueil : reflet, pastilles ───
(() => {
  if (window.__hubFx) return;
  window.__hubFx = true;
  const doc = document;

  // Reflet : position de la souris relative à la carte survolée
  let raf = 0, last = null;
  doc.addEventListener('pointermove', (e) => {
    last = e;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const card = last.target.closest && last.target.closest('[class*="st-key-tool_"]');
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (last.clientX - r.left) + 'px');
      card.style.setProperty('--my', (last.clientY - r.top) + 'px');
    });
  }, { passive: true });

  // Pastilles : défilement fluide vers la catégorie
  doc.addEventListener('click', (e) => {
    const p = e.target.closest('.hub-pill');
    if (!p) return;
    e.preventDefault();
    const h = doc.getElementById('cat-' + p.dataset.cat);
    if (h) h.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
                              block: 'start' });
  }, true);

  // Pastille active + barre en verre une fois collée
  let tick = 0;
  function update() {
    tick = 0;
    const bar = doc.querySelector('.st-key-hub_pills');
    if (!bar) return;
    const top = bar.getBoundingClientRect().top;
    bar.classList.toggle('stuck', top <= 16);
    const heads = [...doc.querySelectorAll('.hub-cat[data-cat]')];
    let cur = heads[0]?.dataset.cat;
    for (const h of heads) if (h.getBoundingClientRect().top < innerHeight * 0.35) cur = h.dataset.cat;
    // Tout en bas : la dernière catégorie est active même si son titre n'atteint pas le seuil
    const sc = doc.querySelector('[data-testid="stMain"]');
    if (sc && sc.scrollHeight - sc.scrollTop - sc.clientHeight < 4 && heads.length) cur = heads.at(-1).dataset.cat;
    doc.querySelectorAll('.hub-pill').forEach(p => {
      const on = p.dataset.cat === cur;
      if (on !== p.classList.contains('on')) {
        p.classList.toggle('on', on);
        // Pastille active visible dans la barre (mobile) — scrollTo et pas scrollIntoView,
        // qui interromprait le défilement fluide de la page
        const nav = p.parentElement;
        if (on && nav.scrollWidth > nav.clientWidth)
          nav.scrollTo({ left: p.offsetLeft - nav.clientWidth / 2 + p.offsetWidth / 2, behavior: 'smooth' });
      }
    });
  }
  const schedule = () => { if (!tick) tick = requestAnimationFrame(update); };
  doc.addEventListener('scroll', schedule, { capture: true, passive: true });
  addEventListener('resize', schedule);
  new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true });
  schedule();
})();
</script>
"""
try:
    st.html(_TRANSITION_JS, unsafe_allow_javascript=True)
except TypeError:  # Streamlit trop ancien : pas d'animation, navigation normale
    pass
