"""
Carte de France des départements colorés selon un indicateur (renta, km à vide…).

Fond : assets/departements_fr.json — contours IGN (france-geojson, version simplifiée)
projetés une fois pour toutes en chemins SVG (1000 × 965). Aucune tuile ni librairie
externe : la carte s'affiche aussi hors ligne et s'exporte telle quelle en HTML.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

FOND = Path(__file__).resolve().parents[2] / "assets" / "departements_fr.json"


@lru_cache(maxsize=1)
def fond():
    return json.loads(FOND.read_text(encoding="utf-8"))


def _f(v, nd=3):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else round(v, nd)


def donnees(zones: pd.DataFrame) -> dict:
    """code département → indicateurs (France uniquement)."""
    out = {}
    for r in zones[zones["france"]].to_dict("records"):
        out[r["dept"]] = dict(
            liv=_f(r["livraisons"], 1), ca=_f(r["ca"], 0), kmc=_f(r["km_charge"], 0),
            rc=_f(r["renta_chargee"]), rv=_f(r["renta_conv"]), rs=_f(r["renta_sortie"]),
            vs=_f(r["vide_sortie_moy"], 0), ve=_f(r["vide_entree_moy"], 0), loc=_f(r["pct_local"], 1),
            dl=_f(r["delai_h"], 2), so=int(r["sorties"] or 0), en=int(r["entrees"] or 0),
            ch=int(r["chargements"] or 0), grp=_f(r["pct_groupage"], 0), aff=_f(r["livraisons_aff"], 1),
            rep=bool(r["representatif"]))
    return out


def carte_html(zones: pd.DataFrame, tot: dict, seuil_local: int, min_liv: int, conv_lbl: str,
               titre: str = "", autonome: bool = False) -> str:
    """Page HTML de la carte. autonome=True : document complet (téléchargement), sinon composant Streamlit."""
    f = fond()
    cfg = dict(
        w=f["w"], h=f["h"], seuil=seuil_local, minliv=min_liv, conv=conv_lbl, titre=titre,
        ref=dict(rc=_f(tot.get("renta_chargee")), rv=_f(tot.get("renta_conv")), rs=_f(tot.get("renta_conv")),
                 vs=_f(tot.get("vide_sortie_moy"), 0), ve=_f(tot.get("vide_sortie_moy"), 0),
                 loc=_f(tot.get("pct_local"), 1)),
    )
    data = json.dumps(dict(cfg=cfg, d=donnees(zones), g=f["d"]), ensure_ascii=False, separators=(",", ":"))
    html = _TEMPLATE.replace("/*__DATA__*/null", data)
    if autonome:
        html = ("<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                f"<title>Renta par département</title></head><body class='seul'>{html}</body></html>")
    return html


_TEMPLATE = r"""
<style>
  :root { --txt:#1d1d1f; --sub:#6e6e73; --line:#e5e5ea; --bg:#f5f5f7; --card:#fff;
          --vert:#34a853; --rouge:#d93025; --bleu:#0071e3; --vide:#ececf0; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
         color:var(--txt); background:transparent; -webkit-font-smoothing:antialiased; }
  body.seul { background:var(--bg); padding:24px; }
  .rdc { background:var(--card); border-radius:18px; box-shadow:0 1px 2px rgba(0,0,0,.04), 0 4px 18px rgba(0,0,0,.05);
         padding:18px 20px 16px; }
  .top { display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; justify-content:space-between; }
  .top h3 { margin:0; font-size:17px; font-weight:600; letter-spacing:-.01em; }
  .top .st { font-size:12px; color:var(--sub); margin-top:2px; }
  .seg { display:flex; flex-wrap:wrap; gap:4px; background:var(--bg); padding:3px; border-radius:11px; }
  .seg button { border:0; background:transparent; font:inherit; font-size:13px; color:var(--txt); padding:6px 11px;
                border-radius:8px; cursor:pointer; transition:background .15s, box-shadow .15s; white-space:nowrap; }
  .seg button:hover { background:rgba(0,0,0,.04); }
  .seg button.on { background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.12); font-weight:600; }
  .grid { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(250px,1fr); gap:18px; margin-top:14px; }
  @media (max-width:820px){ .grid { grid-template-columns:1fr; } }
  .mapw { position:relative; }
  svg { width:100%; height:auto; display:block; }
  path.d { stroke:#fff; stroke-width:.9; transition:opacity .15s; cursor:default; }
  path.d.nr { stroke:#8e8e93; stroke-width:1.1; stroke-dasharray:3 2; }
  path.d.hl { stroke:#1d1d1f; stroke-width:2; }
  g.dims path.d:not(.hl) { opacity:.55; }
  g.z path.d { vector-effect:non-scaling-stroke; }
  text.enc { font-size:15px; font-weight:600; fill:#6e6e73; }
  text.n { font-size:19px; font-weight:600; fill:#1d1d1f; pointer-events:none; text-anchor:middle;
           dominant-baseline:central; paint-order:stroke; stroke:rgba(255,255,255,.85); stroke-width:4px; }
  text.n.petit { font-size:12px; }
  .tip { position:absolute; pointer-events:none; background:rgba(29,29,31,.94); color:#fff; border-radius:12px;
         padding:10px 12px; font-size:12px; line-height:1.45; min-width:210px; box-shadow:0 8px 24px rgba(0,0,0,.2);
         opacity:0; transform:translateY(4px); transition:opacity .12s, transform .12s; z-index:5; }
  .tip.on { opacity:1; transform:none; }
  .tip b { font-size:13px; } .tip .r { display:flex; justify-content:space-between; gap:14px; }
  .tip .r span:first-child { color:rgba(255,255,255,.65); } .tip .nr { color:#ffcc66; margin-top:4px; }
  .side h4 { margin:2px 0 8px; font-size:13px; font-weight:600; color:var(--sub); text-transform:uppercase;
             letter-spacing:.04em; }
  .leg { margin-bottom:16px; }
  .bar { height:10px; border-radius:6px; }
  .ticks { display:flex; justify-content:space-between; font-size:11px; color:var(--sub); margin-top:4px; }
  .moy { font-size:12px; color:var(--sub); margin-top:6px; }
  .moy b { color:var(--txt); }
  .sw { display:flex; gap:14px; flex-wrap:wrap; font-size:11px; color:var(--sub); margin-top:8px; }
  .sw i { display:inline-block; width:14px; height:10px; border-radius:3px; vertical-align:-1px; margin-right:5px; }
  .sw i.nr { background:#fff; border:1.2px dashed #8e8e93; } .sw i.nd { background:var(--vide); }
  ol { margin:0 0 14px; padding:0; list-style:none; }
  ol li { display:flex; justify-content:space-between; gap:10px; font-size:13px; padding:6px 8px; border-radius:8px;
          cursor:default; }
  ol li:hover { background:var(--bg); }
  ol li .v { font-weight:600; font-variant-numeric:tabular-nums; }
  ol li .v.bon { color:var(--vert); } ol li .v.mauvais { color:var(--rouge); }
  .vide-msg { font-size:12px; color:var(--sub); }
  .note { font-size:11.5px; color:var(--sub); margin-top:8px; line-height:1.45; }
</style>
<div class="rdc">
  <div class="top">
    <div><h3 id="t">Carte</h3><div class="st" id="st"></div></div>
    <div class="seg" id="seg"></div>
  </div>
  <div class="grid">
    <div class="mapw" id="mapw">
      <svg id="svg" role="img" aria-label="Carte des départements"></svg>
      <div class="tip" id="tip"></div>
    </div>
    <div class="side">
      <div class="leg"><h4 id="lt"></h4><div class="bar" id="bar"></div><div class="ticks" id="ticks"></div>
        <div class="moy" id="moy"></div>
        <div class="sw"><span><i class="nr"></i>moins de <span id="ml"></span> livraisons</span>
          <span><i class="nd"></i>pas de donnée</span></div></div>
      <h4 id="h1"></h4><ol id="top"></ol>
      <h4 id="h2"></h4><ol id="flop"></ol>
      <div class="note" id="note"></div>
    </div>
  </div>
</div>
<script>
(function(){
const D = /*__DATA__*/null;
const C = D.cfg, NS = "http://www.w3.org/2000/svg";
const fmtE = v => v == null ? "—" : v.toFixed(2).replace(".", ",") + " €/km";
const fmtK = v => v == null ? "—" : Math.round(v).toLocaleString("fr-FR") + " km";
const fmtP = v => v == null ? "—" : Math.round(v) + " %";
const fmtN = v => v == null ? "—" : (Math.round(v * 10) / 10).toLocaleString("fr-FR");
const fmtH = v => { if (v == null) return "—"; const m = Math.round(v * 60), h = Math.floor(m / 60), r = m % 60;
  return h ? h + " h " + String(r).padStart(2, "0") : r + " min"; };
const fmtC = v => v == null ? "—" : Math.round(v).toLocaleString("fr-FR") + " €";
const M = [
  {k:"rc", l:"Renta chargée", f:fmtE, s:+1, span:.25, d:"CA ÷ km chargés"},
  {k:"rv", l:"Renta avec vide", f:fmtE, s:+1, span:.25, d:"CA ÷ (km chargés + vide imputé : " + C.conv.toLowerCase() + ")"},
  {k:"rs", l:"Livraison + sortie", f:fmtE, s:+1, span:.25, d:"CA ÷ (km chargés + repositionnements qui partent du département)"},
  {k:"vs", l:"Vide de sortie", f:fmtK, s:-1, span:.45, d:"km à vide moyens entre un déchargement dans le département et le chargement suivant"},
  {k:"ve", l:"Vide d'entrée", f:fmtK, s:-1, span:.45, d:"km à vide moyens pour venir charger dans le département"},
  {k:"loc", l:"Rechargement local", f:fmtP, s:+1, span:null, d:"part des repositionnements de moins de " + C.seuil + " km"},
  {k:"liv", l:"Livraisons", f:fmtN, s:0, span:null, d:"nombre de livraisons (dossiers pondérés)"},
];
let cur = M[0];

// ── couleurs ──
const hex = h => [1,3,5].map(i => parseInt(h.slice(i, i + 2), 16));
const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
const NEU = hex("#f2f2f5"), VE = hex("#2e9d4d"), RO = hex("#d23a2f"), BL = hex("#0a5fc2"), BL0 = hex("#e3eefb");
function vals(m){ return Object.values(D.d).map(x => x[m.k]).filter(v => v != null); }
function scale(m){
  const ref = C.ref[m.k];
  if (m.s === 0 || ref == null) {           // séquentiel
    const v = vals(m); const mx = Math.max(...v, 1);
    return {seq:true, ref:null, lo:0, hi:mx, col: x => mix(BL0, BL, Math.sqrt(Math.max(0, x) / mx))};
  }
  if (m.span == null) {                     // pourcentages : ± 25 points
    return {seq:false, ref, lo:Math.max(0, ref - 25), hi:Math.min(100, ref + 25),
            col: x => { const t = Math.max(-1, Math.min(1, (x - ref) / 25 * m.s)); return t >= 0 ? mix(NEU, VE, t) : mix(NEU, RO, -t); }};
  }
  return {seq:false, ref, lo:ref * (1 - m.span), hi:ref * (1 + m.span),
          col: x => { const t = Math.max(-1, Math.min(1, (x - ref) / (ref * m.span) * m.s)); return t >= 0 ? mix(NEU, VE, t) : mix(NEU, RO, -t); }};
}

// ── carte ──
const svg = document.getElementById("svg");
svg.setAttribute("viewBox", "0 0 " + C.w + " " + C.h);
const g = document.createElementNS(NS, "g"), gl = document.createElementNS(NS, "g");
svg.appendChild(g); svg.appendChild(gl);
const P = {};
Object.entries(D.g).forEach(([code, o]) => {
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", o.p); p.setAttribute("class", "d"); p.dataset.c = code;
  g.appendChild(p); P[code] = p;
  if (D.d[code] && !["75", "92", "93", "94"].includes(code)) {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", o.x); t.setAttribute("y", o.y);
    t.setAttribute("class", "n" + (o.a < 900 ? " petit" : ""));
    t.textContent = code; gl.appendChild(t);
  }
});

// ── encart Île-de-France (agrandi, en bas à gauche, sur l'Atlantique) ──
const IDF = ["75", "77", "78", "91", "92", "93", "94", "95"].filter(c => P[c]);
const Q = {};                                   // clones de l'encart
const gi = document.createElementNS(NS, "g");
if (IDF.length) {
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const PC = ["75", "92", "93", "94"].filter(c => P[c]);
  PC.forEach(c => { const b = P[c].getBBox(); x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
                     x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height); });
  const px = (x1 - x0) * .18, py = (y1 - y0) * .18;
  x0 -= px; x1 += px; y0 -= py; y1 += py;
  const W = 290, H = 250, ox = 6, oy = C.h - H - 70;
  const k = Math.min((W - 8) / (x1 - x0), (H - 32) / (y1 - y0));
  const fr = document.createElementNS(NS, "rect");
  Object.entries({x: ox, y: oy, width: W, height: H, rx: 14, fill: "#fff", stroke: "#d2d2d7", "stroke-width": 1})
        .forEach(([a, v]) => fr.setAttribute(a, v));
  gi.appendChild(fr);
  const lb = document.createElementNS(NS, "text");
  lb.setAttribute("x", ox + 12); lb.setAttribute("y", oy + 20); lb.setAttribute("class", "enc");
  lb.textContent = "Paris et petite couronne"; gi.appendChild(lb);
  const cp = document.createElementNS(NS, "clipPath"); cp.setAttribute("id", "clipidf");
  const cr = document.createElementNS(NS, "rect");
  Object.entries({x: ox + 1, y: oy + 28, width: W - 2, height: H - 29, rx: 12}).forEach(([a, v]) => cr.setAttribute(a, v));
  cp.appendChild(cr); gi.appendChild(cp);
  const gc = document.createElementNS(NS, "g"); gc.setAttribute("clip-path", "url(#clipidf)"); gi.appendChild(gc);
  const gz = document.createElementNS(NS, "g"); gz.setAttribute("class", "z");
  const tx = ox + (W - (x1 - x0) * k) / 2, ty = oy + 28 + (H - 30 - (y1 - y0) * k) / 2;
  gz.setAttribute("transform", "translate(" + tx + "," + ty + ") scale(" + k + ") translate(" + (-x0) + "," + (-y0) + ")");
  IDF.forEach(c => { const q = P[c].cloneNode(true); gz.appendChild(q); Q[c] = q; });
  gc.appendChild(gz);
  IDF.forEach(c => { if (!D.d[c]) return; const o0 = D.g[c];
    if (o0.x < x0 || o0.x > x1 || o0.y < y0 || o0.y > y1) return; const b = Q[c].getBBox(), o = D.g[c];
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", tx + (o.x - x0) * k); t.setAttribute("y", ty + (o.y - y0) * k);
    t.setAttribute("class", "n"); t.textContent = c; gi.appendChild(t); });
  svg.appendChild(gi);
  // cadre discret autour de la zone réelle
  const z = document.createElementNS(NS, "rect");
  Object.entries({x: x0 - 3, y: y0 - 3, width: x1 - x0 + 6, height: y1 - y0 + 6, rx: 4, fill: "none",
                  stroke: "#8e8e93", "stroke-width": 1, "stroke-dasharray": "3 2"}).forEach(([a, v]) => z.setAttribute(a, v));
  gl.appendChild(z);
}
const tous = c => [P[c], Q[c]].filter(Boolean);

const tip = document.getElementById("tip"), wrap = document.getElementById("mapw");
function ligne(a, b){ return '<div class="r"><span>' + a + '</span><span>' + b + '</span></div>'; }
function montrer(code, ev){
  const o = D.g[code], x = D.d[code];
  let h = "<b>" + code + " — " + o.n + "</b>";
  if (!x) h += '<div class="r"><span>Aucune livraison ni chargement</span></div>';
  else {
    h += ligne("Livraisons", fmtN(x.liv) + (x.grp ? " · " + x.grp + " % groupage" : ""));
    h += ligne("CA", fmtC(x.ca));
    h += ligne("Renta chargée", fmtE(x.rc));
    h += ligne("Renta avec vide", fmtE(x.rv));
    h += ligne("Livraison + sortie", fmtE(x.rs));
    h += ligne("Vide de sortie", fmtK(x.vs) + " (" + x.so + ")");
    h += ligne("Rechargement local", fmtP(x.loc));
    if (x.dl != null) h += ligne("Délai avant rechargement", fmtH(x.dl));
    h += ligne("Chargements ici", x.ch + (x.en ? " · vide d'entrée " + fmtK(x.ve) : ""));
    if (x.aff) h += ligne("Livraisons affrétés", fmtN(x.aff));
    if (!x.rep && x.liv > 0) h += '<div class="nr">Moins de ' + C.minliv + " livraisons : chiffres indicatifs</div>";
  }
  tip.innerHTML = h; tip.classList.add("on");
  placer(ev);
  document.querySelectorAll("path.d.hl").forEach(p => p.classList.remove("hl"));
  tous(code).forEach(p => { p.classList.add("hl"); p.parentNode.appendChild(p); });
  g.classList.add("dims"); gi.classList.add("dims");
}
function placer(ev){
  if (!ev) return;
  const r = wrap.getBoundingClientRect();
  let x = ev.clientX - r.left + 14, y = ev.clientY - r.top + 14;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  if (x + tw > r.width) x = ev.clientX - r.left - tw - 14;
  if (y + th > r.height) y = Math.max(0, r.height - th);
  tip.style.left = Math.max(0, x) + "px"; tip.style.top = y + "px";
}
function cacher(){ tip.classList.remove("on"); g.classList.remove("dims"); gi.classList.remove("dims");
  document.querySelectorAll("path.d.hl").forEach(p => p.classList.remove("hl")); }
[g, gi].forEach(el => {
  el.addEventListener("mousemove", e => { const c = e.target.dataset && e.target.dataset.c;
    if (c) { if (!e.target.classList.contains("hl")) montrer(c, e); else placer(e); } else cacher(); });
  el.addEventListener("mouseleave", cacher);
});

// ── rendu d'un indicateur ──
function rendre(m){
  cur = m;
  document.querySelectorAll("#seg button").forEach(b => b.classList.toggle("on", b.dataset.k === m.k));
  const sc = scale(m);
  Object.keys(P).forEach(code => tous(code).forEach(p => {
    const x = D.d[code], v = x ? x[m.k] : null;
    p.setAttribute("fill", v == null ? "var(--vide)" : sc.col(v));
    p.classList.toggle("nr", !!x && !x.rep && x.liv > 0 && m.k !== "ve");
  }));
  document.getElementById("t").textContent = (C.titre ? C.titre + " — " : "") + m.l;
  document.getElementById("st").textContent = m.d;
  document.getElementById("lt").textContent = m.l;
  let stops, ticks;
  if (sc.seq) {
    stops = [0, .25, .5, .75, 1].map(t => sc.col(sc.hi * t * t));
    ticks = [m.f(0), m.f(sc.hi)];
  } else {
    const worst = m.s < 0 ? sc.hi : sc.lo, best = m.s < 0 ? sc.lo : sc.hi;
    stops = [0, .25, .5, .75, 1].map(t => sc.col(worst + (best - worst) * t));
    ticks = [(m.s < 0 ? "≥ " : "≤ ") + m.f(worst), "moyenne", (m.s < 0 ? "≤ " : "≥ ") + m.f(best)];
  }
  document.getElementById("bar").style.background = "linear-gradient(90deg," + stops.join(",") + ")";
  document.getElementById("ticks").innerHTML = ticks.map(t => "<span>" + t + "</span>").join("");
  document.getElementById("moy").innerHTML = sc.ref != null ? "Moyenne France : <b>" + m.f(sc.ref) + "</b>"
      + (m.s < 0 ? " — vert = moins de vide" : " — vert = mieux") : "Plus foncé = plus de livraisons";
  document.getElementById("ml").textContent = C.minliv;

  // classement (départements représentatifs uniquement, sauf livraisons)
  const L = Object.entries(D.d).filter(([c, x]) => x[m.k] != null && (m.k === "liv" || m.k === "ve" ? true : x.rep))
                               .map(([c, x]) => [c, x[m.k]]);
  const dir = m.s < 0 ? 1 : -1;
  L.sort((a, b) => dir * (a[1] - b[1]));
  const li = (arr, cls) => arr.length ? arr.map(([c, v]) => '<li data-c="' + c + '"><span>' + c + " — " + D.g[c].n
      + '</span><span class="v ' + cls + '">' + m.f(v) + "</span></li>").join("") : '<li class="vide-msg">—</li>';
  let haut, bas;
  if (sc.ref == null) { haut = L.slice(0, 5); bas = []; }
  else {                                     // mieux / moins bien que la moyenne France
    const mieux = v => m.s < 0 ? v < sc.ref : v > sc.ref;
    haut = L.filter(([c, v]) => mieux(v)).slice(0, 5);
    bas = L.filter(([c, v]) => !mieux(v) && v !== sc.ref).slice(-5).reverse();
  }
  document.getElementById("h1").textContent = m.k === "liv" ? "Plus gros volumes" : "Au-dessus de la moyenne";
  document.getElementById("top").innerHTML = li(haut, m.s ? "bon" : "");
  document.getElementById("h2").textContent = m.k === "liv" ? "" : "En dessous de la moyenne";
  document.getElementById("flop").innerHTML = m.k === "liv" ? "" : li(bas, "mauvais");
  document.querySelectorAll("ol li[data-c]").forEach(el => {
    el.addEventListener("mouseenter", () => { const c = el.dataset.c, r = (Q[c] || P[c]).getBoundingClientRect(); montrer(el.dataset.c, {clientX: r.left + r.width / 2, clientY: r.top + r.height / 2}); });
    el.addEventListener("mouseleave", cacher);
  });
  document.getElementById("note").textContent = (m.k === "liv" || m.k === "ve")
    ? "Classement sur tous les départements."
    : "Classement sur les départements d'au moins " + C.minliv + " livraisons. Belgique, Luxembourg et autres pays : onglet Hors France.";
}

const seg = document.getElementById("seg");
M.forEach(m => { const b = document.createElement("button"); b.textContent = m.l; b.dataset.k = m.k;
  b.onclick = () => rendre(m); seg.appendChild(b); });
rendre(M[0]);
})();
</script>
"""
