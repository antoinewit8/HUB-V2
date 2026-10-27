"""
Page Streamlit : Pompes carburant
- Mes stations : la liste Excel des stations préférées (assets/pompes_favorites.xlsx, réseau Total Trucks),
  affichée directement à l'ouverture de la carte, prix du gazole officiel en France
- Autres stations : TotalEnergies, AS24 et Circle K cherchées à la demande depuis la carte (OpenStreetMap,
  via Overpass), dans le rayon autour du point choisi ou dans tout un pays ; liste officielle Circle K
  pour BE, LU, NL et DE
- La carte s'ouvre dans un nouvel onglet, en plein écran, dans le même esprit que Lavages citernes
"""

import io
import re
import json
import urllib.request as ureq
import urllib.parse as uparse
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import ui
from tools.pompes.favorites import (  # noqa: F401  (partagé avec la Carte manuelle)
    PAYS, EUROPE_BBOX, FAV_ASSET, FAV_LOCAL, norm, lire_favorites, fichier_favorites, favorites_depuis,
    _get, prix_france, lier_prix_france, prix_max_belgique, circlek_officiel, circlek_lu_services,
)
from core import parallele as par

ui.page("pompes", "Mes stations préférées dès l’ouverture, et les autres stations TotalEnergies, AS24 et Circle K "
                  "cherchées à la demande, dans le rayon ou dans tout le pays. La carte s’ouvre en plein écran.")

UA = {"User-Agent": "CB-Transport-Hub/1.0 (pompes carburant)"}

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# ─── Frontières : core/frontieres.py (fichier local, plus de téléchargement) ──
from core.frontieres import load_borders  # noqa: E402


# ─── Carte plein écran ───────────────────────────────────────────────────────
APP_HTML = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Pompes carburant</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%E2%9B%BD%3C/text%3E%3C/svg%3E">
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
.search-row { display: flex; gap: 8px; }
.search { position: relative; flex: 1; }
.search input { width: 100%; height: 46px; border: 1px solid var(--line); border-radius: 12px; background: #fff;
  padding: 0 40px 0 40px; font-size: 15px; color: var(--text); outline: none;
  transition: border-color .15s, box-shadow .15s; }
.search input::placeholder { color: #86868b; }
.search input:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(0,113,227,.18); }
.search .ico { position: absolute; left: 14px; top: 15px; color: #86868b; pointer-events: none; }
.search .clear { position: absolute; right: 10px; top: 12px; width: 22px; height: 22px; border-radius: 50%;
  border: none; background: #c7c7cc; color: #fff; cursor: pointer; display: none; font-size: 13px; line-height: 22px; padding: 0; }
.search.filled .clear { display: block; }
#geoloc { flex: none; width: 46px; height: 46px; border-radius: 12px; border: 1px solid var(--line); background: #fff;
  color: var(--blue); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background .15s; }
#geoloc:hover { background: var(--bg); }
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
.rows { margin-top: 4px; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 11px 0; font-size: 15px; gap: 10px; }
.row + .row { border-top: .5px solid #e5e5ea; }
.row .nm { display: flex; align-items: center; gap: 10px; min-width: 0; }
.row .nm small { color: var(--sub); font-size: 12.5px; }
.dot { width: 22px; height: 22px; border-radius: 50%; flex: none; color: #fff; font: 700 11px/22px var(--font);
  text-align: center; box-shadow: 0 0 0 2px #fff, 0 1px 4px rgba(0,0,0,.25); }
.sw { position: relative; width: 51px; height: 31px; flex: none; }
.sw input { position: absolute; opacity: 0; width: 0; height: 0; }
.sw span { position: absolute; inset: 0; background: #e9e9eb; border-radius: 31px; cursor: pointer; transition: background .2s; }
.sw span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 3px 8px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.16); transition: transform .2s var(--ease); }
.sw input:checked + span { background: var(--green); }
.sw input:checked + span::after { transform: translateX(20px); }
.sw input:focus-visible + span { box-shadow: 0 0 0 4px rgba(0,113,227,.25); }
.facts { font-size: 13px; color: var(--sub); line-height: 1.6; margin: 0; }
.facts b { color: var(--text); font-weight: 600; }

/* ── Synthèse en haut à droite ── */
#info { position: absolute; z-index: 1000; top: var(--gap); right: var(--gap); width: 290px; padding: 16px 18px 14px;
  border-radius: 18px; max-height: calc(100vh - 140px); overflow-y: auto; }
#info .k { font-size: 12px; font-weight: 500; color: var(--sub); }
#info .t { font-size: 17px; font-weight: 600; letter-spacing: -.01em; line-height: 1.25; margin: 2px 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#info .s { font-size: 12.5px; color: var(--sub); line-height: 1.4; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 10px; }
.stats .n { font-size: 26px; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; }
.stats .l { font-size: 11.5px; color: var(--sub); }
.near { display: block; width: 100%; text-align: left; border: none; background: none; cursor: pointer;
  border-top: .5px solid rgba(0,0,0,.12); padding: 9px 0 7px; font-family: var(--font); color: var(--text); }
.near:hover .nn { color: var(--blue); }
.near .top { display: flex; justify-content: space-between; align-items: baseline; font-size: 12px; color: var(--sub); }
.near .top b { font-size: 15px; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.near .nn { font-size: 13.5px; font-weight: 500; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  transition: color .15s; }
.near .top i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }

/* ── Légende ── */
#legend { position: absolute; z-index: 999; left: max(var(--gap), var(--map-left)); bottom: var(--gap);
  padding: 10px 14px; border-radius: 16px; font-size: 11.5px; display: grid; grid-template-columns: auto auto;
  gap: 5px 16px; transition: left .34s var(--ease), opacity .2s; }
#legend div { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
#legend i { display: inline-block; flex: none; }
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
.sheet-head .ttl { font-size: 17px; font-weight: 600; letter-spacing: -.01em; }
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
td.hor { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
tr.click { cursor: pointer; }
tr.click:hover td { background: #f5f5f7; }
td a { color: #0066cc; text-decoration: none; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 980px; font-size: 11.5px; font-weight: 600; color: #fff; }
.ok { color: #00873c; font-weight: 600; }
.ko { color: #c62828; font-weight: 600; }
.nr { color: #aeaeb2; }
.empty { padding: 34px 0; text-align: center; color: var(--sub); font-size: 14px; }
.more { padding: 12px 0 2px; text-align: center; color: var(--sub); font-size: 12.5px; }

/* ── Marqueurs ── */
.cb-icon { background: none; border: none; }
.pp { position: relative; width: 26px; height: 26px; transform: translate(-50%, -50%); border-radius: 50%;
  background: var(--c); border: 2px solid #fff; color: #fff; font: 700 12px/22px var(--font); text-align: center;
  box-shadow: 0 2px 6px rgba(0,0,0,.4); cursor: pointer; }
.pp.best { width: 32px; height: 32px; font-size: 14px; line-height: 28px; box-shadow: 0 0 0 4px rgba(255,255,255,.55), 0 2px 10px rgba(0,0,0,.5); }
.pp .pl { position: absolute; right: -9px; bottom: -6px; background: #1d1d1f; color: #fff; border: 1.5px solid #fff;
  border-radius: 6px; font: 700 8px/11px var(--font); padding: 0 3px; letter-spacing: .02em; }
.pp.doute { opacity: .55; border-style: dashed; }
.src-off { color: #00873c; font-weight: 600; }
.src-osm { color: var(--sub); }
.src-hors { color: #b45a00; font-weight: 600; }
.src-fav { color: #a07800; font-weight: 600; }
.pp.fav { box-shadow: 0 0 0 2.5px #ffcc00, 0 2px 6px rgba(0,0,0,.45); }
.pp.fav.best { box-shadow: 0 0 0 3px #ffcc00, 0 0 0 7px rgba(255,255,255,.5), 0 2px 10px rgba(0,0,0,.5); }
.star { color: #ffb800; }

/* Recherche des autres stations */
.select { width: 100%; height: 40px; margin-top: 10px; border: 1px solid var(--line); border-radius: 10px; background: #fff;
  padding: 0 12px; font: 14px var(--font); color: var(--text); outline: none; cursor: pointer; }
.select:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(0,113,227,.18); }
.etat { display: flex; gap: 9px; align-items: flex-start; margin: 12px 0 0; font-size: 12.5px; line-height: 1.45; color: var(--sub); }
.etat.err { color: #c62828; }
.etat.ok { color: #1d1d1f; }
.spin { flex: none; width: 14px; height: 14px; margin-top: 1px; border-radius: 50%; border: 2px solid var(--soft);
  border-top-color: var(--blue); animation: tour .8s linear infinite; }
@keyframes tour { to { transform: rotate(360deg); } }
.lien { border: none; background: none; padding: 0; color: var(--blue); font: 500 12.5px var(--font); cursor: pointer; }
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
.pop-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0 4px; }
.pop-tags span { background: var(--soft); border-radius: 980px; padding: 1px 8px; font-size: 11.5px; font-weight: 500; }
.pop-tags span.on { background: #e3f6ea; color: #00753a; }
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
  <h1 class="title">Pompes carburant</h1>
  <p class="lede">Mes stations dès l’ouverture. Les autres stations TotalEnergies, AS24 et Circle K sont cherchées quand vous activez leur réseau.</p>

  <div class="sec">
    <h2>Position</h2>
    <div class="search-row">
      <div class="search" id="searchbox">
        <svg class="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="q" type="text" autocomplete="off" placeholder="Adresse, ville, code postal ou station" aria-label="Rechercher une adresse ou une station">
        <button class="clear" id="qclear" aria-label="Effacer">✕</button>
      </div>
      <button id="geoloc" title="Ma position" aria-label="Utiliser ma position">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M21 3 3 10.5l7.2 2.3L12.5 20z"/></svg>
      </button>
    </div>
    <ul id="results" role="listbox"></ul>
    <p class="hint" id="pos-hint">Ou cliquez directement sur la carte.</p>
    <div class="range-head"><span class="lbl" style="margin:0">Rayon de recherche</span><b id="rval">30 km</b></div>
    <input id="rayon" type="range" min="2" max="150" step="1" value="30" aria-label="Rayon de recherche">
    <div class="range-scale"><span>2 km</span><span>150 km</span></div>
  </div>

  <div class="sec">
    <h2>Mes stations</h2>
    <div class="rows">
      <label class="row"><span class="nm"><span class="dot" style="background:#2f6bff;box-shadow:0 0 0 2px #ffcc00,0 1px 4px rgba(0,0,0,.25)">★</span><span>Liste Excel<br><small id="fav-n"></small></span></span><span class="sw"><input type="checkbox" id="t-fav" checked><span></span></span></label>
    </div>
  </div>

  <div class="sec">
    <h2>Autres stations</h2>
    <p class="lbl">Chercher</p>
    <div class="seg" id="zone">
      <button data-z="rayon" class="on">Dans le rayon</button>
      <button data-z="pays">Tout le pays</button>
    </div>
    <select class="select" id="pays-rech" aria-label="Pays à parcourir" style="display:none"></select>
    <div class="rows" id="reseaux"></div>
    <div class="etat" id="rech-etat"></div>
  </div>

  <div class="sec">
    <h2>Filtres</h2>
    <div class="rows">
      <label class="row"><span class="nm">Accès poids lourds confirmé</span><span class="sw"><input type="checkbox" id="f-pl"><span></span></span></label>
      <label class="row"><span class="nm">AdBlue à la pompe</span><span class="sw"><input type="checkbox" id="f-ad"><span></span></span></label>
      <label class="row"><span class="nm">Ouvert 24 h/24</span><span class="sw"><input type="checkbox" id="f-24"><span></span></span></label>
      <label class="row" id="row-hors"><span class="nm">Masquer les non confirmées</span><span class="sw"><input type="checkbox" id="f-hors"><span></span></span></label>
    </div>
    <p class="hint">Ces informations viennent d’OpenStreetMap et sont souvent absentes : un filtre actif masque aussi les stations non renseignées.</p>
  </div>

  <div class="sec">
    <h2>Affichage</h2>
    <p class="lbl">Fond de carte</p>
    <div class="seg" id="fonds"></div>
    <div class="rows">
      <label class="row"><span class="nm">Frontières renforcées</span><span class="sw"><input type="checkbox" id="t-borders" checked><span></span></span></label>
      <label class="row"><span class="nm">Stations hors rayon</span><span class="sw"><input type="checkbox" id="t-hors" checked><span></span></span></label>
    </div>
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
    <div class="ttl" id="sheet-ttl">Stations</div>
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
const ST = D.stations;                       // mes stations au départ, puis les stations trouvées
const RES = {
  total:   { l: 'TotalEnergies', c: '#2f6bff', k: 'T', s: 'stations-service' },
  as24:    { l: 'AS24', c: '#00a37a', k: 'A', s: 'poids lourds, filiale TotalEnergies' },
  circlek: { l: 'Circle K', c: '#e5202e', k: 'K', s: 'stations-service' },
  autre:   { l: 'Autre réseau', c: '#636366', k: '•', s: '' },
};
const RES_RECH = ['total', 'as24', 'circlek'];          // réseaux que l'on peut chercher
const RES_ORDRE = RES_RECH.concat(ST.some(s => s.r === 'autre') ? ['autre'] : []);
const PAYS = D.pays_noms || {};
const CK_PAYS = new Set(['BE', 'LU', 'NL', 'DE']);
const EUROPE = { w: -11, s: 35, e: 32, n: 72 };
function esri(s) { return `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`; }
const FONDS = {
  'Satellite': { layers: [[esri('World_Imagery'), 'Tiles © Esri', 18], [esri('Reference/World_Boundaries_and_Places'), '© Esri', 18]],
                 front: '#ffd54f', halo: '#000000' },
  'Plan': { layers: [[esri('World_Street_Map'), 'Tiles © Esri', 18]], front: '#c62828', halo: '#ffffff' },
  'Sombre': { layers: [[esri('Canvas/World_Dark_Gray_Base'), 'Tiles © Esri', 16], [esri('Canvas/World_Dark_Gray_Reference'), '© Esri', 16]],
              front: '#ffd54f', halo: '#000000' },
};
const MAX_BADGES = 400, MAX_LIGNES = 600;

const state = { fav: true, res: { total: false, as24: false, circlek: false, autre: true }, center: null, rayon: 30,
                zone: 'rayon', paysRech: D.pays_defaut || 'FR', paysManuel: false, fond: 'Satellite',
                borders: true, hors: true, pl: false, ad: false, h24: false, sansDoute: false, sort: { key: 'dist', dir: 1 }, filtre: '',
                proches: [], best: {} };
const $ = id => document.getElementById(id);

// ── Utilitaires ──
function esc(v) { return v == null ? '' : String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function hav(a, b, c, d) {
  const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}
function nn(t) { return (t || '').toUpperCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim(); }
function km(v) { return v == null ? '—' : v.toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }); }
function nb(v) { return v.toLocaleString('fr-FR'); }
function gmaps(la, lo) { return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(6)},${lo.toFixed(6)}`; }
function iti(s) {
  const c = state.center;
  return c ? `https://www.google.com/maps/dir/?api=1&origin=${c.lat.toFixed(6)},${c.lon.toFixed(6)}&destination=${s.la.toFixed(6)},${s.lo.toFixed(6)}&travelmode=driving` : gmaps(s.la, s.lo);
}
function eurL(v) { return v == null ? '—' : v.toLocaleString('fr-FR', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' €'; }
function majTxt(s) {
  if (s.pxs === 'max') return 'maximum officiel' + (s.pxm ? ` (${s.pxm})` : '');
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(s.pxm || '');
  return m ? `affiché, mis à jour le ${m[3]}/${m[2]} à ${m[4]}` : 'affiché';
}
function lieu(s) { return [s.cp, s.v].filter(Boolean).join(' '); }
function plTxt(v) { return v === 1 ? 'Confirmé' : v === 0 ? 'Interdit' : 'Non renseigné'; }
function divIcon(html) { return L.divIcon({ className: 'cb-icon', html, iconSize: [0, 0], iconAnchor: [0, 0] }); }
function prep(s) { s.h24 = (s.h || '').trim() === '24/7'; s._nn = nn(`${s.n} ${s.v} ${s.cp} ${s.code || ''}`); }
ST.forEach((s, i) => { s.i = i; prep(s); });
const vis = s => (s.fav ? state.fav : state.res[s.r]) && (!state.pl || s.pl === 1) && (!state.ad || s.ad === 1) && (!state.h24 || s.h24)
  && (!state.sansDoute || s.src !== 'osm_hors');
const SRC = { favori: ['src-fav', 'Mes stations (liste Excel)'], officiel: ['src-off', 'Liste officielle Circle K'],
              osm: ['src-osm', 'OpenStreetMap'], osm_hors: ['src-hors', 'OpenStreetMap, absente de la liste officielle'] };
const nHors = () => ST.filter(s => s.src === 'osm_hors').length;
const N_FAV = ST.filter(s => s.fav).length;

// ── Carte ──
const map = L.map('map', { zoomControl: false, worldCopyJump: true, preferCanvas: false }).setView([46.6, 2.5], 6);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ position: 'bottomright', imperial: false }).addTo(map);
const canvas = L.canvas({ padding: .5 });
const dots = L.layerGroup().addTo(map);      // stations visibles (petits points, canvas)
const zone = L.layerGroup().addTo(map);      // centre, cercle et pastilles
let tiles = [], bHalo = null, bLine = null, circle = null;
const mk = {};

function mapLeft() { return document.body.classList.contains('collapsed') ? 0 : $('panel').offsetWidth + 24; }
function fitTo(bounds) {
  map.fitBounds(bounds, { paddingTopLeft: [mapLeft() + 16, 20], paddingBottomRight: [window.innerWidth > 760 ? 320 : 20, 20], maxZoom: 14 });
}
function applyFond() {
  tiles.forEach(t => map.removeLayer(t)); tiles = [];
  FONDS[state.fond].layers.forEach(([u, a, z], i) => tiles.push(L.tileLayer(u, { attribution: i ? a : a + ' · Stations © OpenStreetMap', maxNativeZoom: z, maxZoom: 19, zIndex: i }).addTo(map)));
  drawBorders();
}
function drawBorders() {
  [bHalo, bLine].forEach(l => l && map.removeLayer(l)); bHalo = bLine = null;
  if (!state.borders || !BORDERS) return;
  const f = FONDS[state.fond];
  bHalo = L.geoJSON(BORDERS, { interactive: false, style: { color: f.halo, weight: 7, opacity: .7 } }).addTo(map);
  bLine = L.geoJSON(BORDERS, { interactive: false, style: { color: f.front, weight: 2.6, opacity: 1 } }).addTo(map);
}

function popup(s) {
  const r = RES[s.r];
  const tag = (on, t) => `<span class="${on ? 'on' : ''}">${t}</span>`;
  const l = [`<b style="font-size:14px">${s.fav ? '<span class="star">★</span> ' : ''}${esc(s.n)}</b>`,
             `<span style="color:${r.c};font-weight:600">${esc(s.e)}</span>${s.code ? ` <span style="color:var(--sub)">· ${esc(s.code)}</span>` : ''}`];
  if (s.a) l.push(esc(s.a));
  l.push(`${esc(lieu(s))} ${esc(PAYS[s.p] || s.p || '')}`.trim());
  const plNote = s.plo ? ' (piste PL officielle)' : s.pln ? ` (réseau ${esc(s.pln)})` : '';
  const tags = [tag(s.pl === 1, `PL : ${plTxt(s.pl).toLowerCase()}${plNote}`)];
  if (s.ad === 1) tags.push(tag(true, 'AdBlue'));
  if (s.lng === 1) tags.push(tag(true, 'GNL'));
  if (s.cng === 1) tags.push(tag(true, 'GNC'));
  if (s.h24) tags.push(tag(true, '24 h/24'));
  l.push(`<div class="pop-tags">${tags.join('')}</div>`);
  if (s.px != null) l.push(`Gazole : <b style="font-size:14px">${eurL(s.px)}/L</b> <span style="color:var(--sub)">${esc(majTxt(s))}</span>`);
  if (s.h && !s.h24) l.push(`Horaires : ${esc(s.h)}`);
  if (s.t) l.push(`Tél. ${esc(s.t)}`);
  if (s.dist != null) l.push(`À ${km(s.dist)} km à vol d’oiseau`);
  const src = SRC[s.src] || SRC.osm;
  l.push(`<span class="${src[0]}">Source : ${src[1]}</span>`);
  const liens = [`<a href="${iti(s)}" target="_blank" rel="noopener">${state.center ? 'Itinéraire depuis le centre' : 'Ouvrir dans Google Maps'}</a>`];
  if (s.w) liens.push(`<a href="${esc(s.w)}" target="_blank" rel="noopener">${s.src === 'officiel' ? 'Fiche Circle K' : 'Site'}</a>`);
  if (s.id) liens.push(`<a href="https://www.openstreetmap.org/${esc(s.id)}" target="_blank" rel="noopener">Fiche OSM</a>`);
  l.push(liens.join(' · '));
  return l.join('<br>');
}
function pastille(s, best, dist) {
  const r = RES[s.r];
  const html = `<div class="pp${best ? ' best' : ''}${s.fav ? ' fav' : ''}${s.src === 'osm_hors' ? ' doute' : ''}" style="--c:${r.c}">${r.k}${s.pl === 1 ? '<span class="pl">PL</span>' : ''}</div>`;
  return L.marker([s.la, s.lo], { icon: divIcon(html), riseOnHover: true, zIndexOffset: best ? 1000 : s.fav ? 200 : 0 })
    .bindTooltip(`${s.fav ? '★ ' : ''}${esc(s.n)}${dist ? ' · ' + km(s.dist) + ' km' : s.v ? ' · ' + esc(s.v) : ''}${s.px != null ? ' · ' + eurL(s.px) : ''}`, { direction: 'top', offset: [0, -14] })
    .bindPopup(() => popup(s), { maxWidth: 320 });
}

// Petits points : reconstruits seulement quand les filtres ou les stations changent
function renderDots() {
  dots.clearLayers(); for (const k in mk) delete mk[k];
  if (state.hors) {
    const n = ST.filter(vis).length, rad = n > 4000 ? 3.5 : 4.5;
    ST.forEach(s => {
      if (!vis(s)) return;
      const m = L.circleMarker([s.la, s.lo], { renderer: canvas, radius: s.fav ? rad + 1 : rad, color: s.fav ? '#ffcc00' : '#fff', weight: s.fav ? 2 : 1.2,
        fillColor: RES[s.r].c, fillOpacity: s.src === 'osm_hors' ? .45 : .95, bubblingMouseEvents: false })
        .bindTooltip(() => `${s.fav ? '★ ' : ''}${esc(s.n)} (${esc(s.v || PAYS[s.p] || s.p || '')})`).bindPopup(() => popup(s), { maxWidth: 320 });
      dots.addLayer(m); mk['s' + s.i] = m;
    });
  }
  renderZone();
}

// Zone : centre, cercle, pastilles des stations du rayon (sans point : pastilles de mes stations)
function renderZone() {
  zone.clearLayers();
  if (circle) { map.removeLayer(circle); circle = null; }
  const c = state.center, R = state.rayon;
  ST.forEach(s => s.dist = c ? hav(c.lat, c.lon, s.la, s.lo) : null);
  let proches = [];
  state.best = {};
  if (c) {
    circle = L.circle([c.lat, c.lon], { radius: R * 1000, color: '#e53935', weight: 2, dashArray: '6 6', fillOpacity: .05, interactive: false }).addTo(map);
    zone.addLayer(L.marker([c.lat, c.lon], { icon: divIcon('<div class="cb-centre"></div>'), interactive: false, keyboard: false, zIndexOffset: -1000 }));
    proches = ST.filter(s => vis(s) && s.dist <= R).sort((a, b) => a.dist - b.dist);
    // Plus proche de mes stations, par réseau et avec accès PL, même hors rayon
    ST.forEach(s => {
      if (!vis(s)) return;
      const k = s.fav ? 'fav' : s.r;
      if (!state.best[k] || s.dist < state.best[k].dist) state.best[k] = s;
      if (s.pl === 1 && (!state.best.pl || s.dist < state.best.pl.dist)) state.best.pl = s;
    });
    const prixRayon = proches.filter(s => s.px != null && s.pxs === 'station');
    if (prixRayon.length) state.best.prix = prixRayon.reduce((a, b) => (b.px < a.px ? b : a));
    const bestIds = new Set(Object.values(state.best).map(s => s.i));
    const badges = proches.slice(0, MAX_BADGES);
    const dejaLa = new Set(badges.map(s => s.i));
    Object.values(state.best).forEach(s => { if (!dejaLa.has(s.i)) { badges.push(s); dejaLa.add(s.i); } });
    badges.reverse().forEach(s => { const m = pastille(s, bestIds.has(s.i), true); zone.addLayer(m); mk['s' + s.i] = m; });
  } else if (state.fav) {
    ST.filter(s => s.fav && vis(s)).slice(0, 800).forEach(s => { const m = pastille(s, false, false); zone.addLayer(m); mk['s' + s.i] = m; });
  }
  state.proches = proches;
  updateInfo(); updateChip(); legend();
  if (document.body.classList.contains('sheet-open')) renderSheet();
}

function groupes() {
  return (state.fav ? [['fav', '★ Mes stations', '#a07800']] : [])
    .concat(RES_ORDRE.filter(r => state.res[r] && (r !== 'autre' || ST.some(s => !s.fav && s.r === 'autre'))).map(r => [r, RES[r].l, RES[r].c]));
}
const cle = s => s.fav ? 'fav' : s.r;
function compte(liste) { const o = {}; liste.forEach(s => o[cle(s)] = (o[cle(s)] || 0) + 1); return o; }
function updateInfo() {
  const c = state.center;
  const stat = (v, l) => `<div><div class="n">${v}</div><div class="l">${l}</div></div>`;
  const gr = groupes();
  if (!c) {
    const n = compte(ST.filter(vis));
    $('info').innerHTML = `<div class="k">Aucune position</div><div class="t">Choisissez un point</div>
      <div class="stats">${gr.map(([k, l]) => stat(nb(n[k] || 0), l.replace('★ ', ''))).join('')}</div>
      <div class="s">Recherchez une adresse ou une station dans le panneau, ou cliquez sur la carte.</div>`;
    return;
  }
  const n = compte(state.proches), npl = state.proches.filter(s => s.pl === 1).length;
  const cases = gr.map(([k, l]) => stat(n[k] || 0, l.replace('★ ', ''))).concat(gr.length < 3 ? [stat(npl, 'PL confirmé')] : []);
  const near = (s, titre, col) => s ? `<button class="near" data-i="${s.i}"><div class="top"><span><i style="background:${col}"></i>${titre}</span><b${s.dist > state.rayon ? ' style="color:#b45a00"' : ''}>${km(s.dist)} km</b></div><div class="nn">${esc(s.n)}${s.v ? ' · ' + esc(s.v) : ''}</div></button>` : '';
  $('info').innerHTML = `<div class="k">Rayon de ${state.rayon} km autour de</div><div class="t">${esc(c.label)}</div>
    <div class="stats">${cases.join('')}</div>`
    + gr.map(([k, l, col]) => near(state.best[k], k === 'fav' ? 'Plus proche de mes stations' : `Plus proche ${l}`, k === 'fav' ? '#ffcc00' : col)).join('')
    + near(state.best.pl, 'Plus proche, accès PL confirmé', '#1d1d1f')
    + (state.best.prix ? `<button class="near" data-i="${state.best.prix.i}"><div class="top"><span><i style="background:#00a854"></i>Gazole le moins cher du rayon</span><b style="color:#00873c">${eurL(state.best.prix.px)}/L</b></div><div class="nn">${esc(state.best.prix.n)}${state.best.prix.v ? ' · ' + esc(state.best.prix.v) : ''} · ${km(state.best.prix.dist)} km</div></button>` : '')
    + `<div class="s" style="margin-top:6px">Distances à vol d’oiseau.${state.proches.length ? '' : ' Aucune station dans ce rayon avec les filtres actuels : les plus proches sont plus loin (en orange).'}</div>`;
}
$('info').addEventListener('click', e => {
  const b = e.target.closest('.near'); if (!b) return;
  document.body.classList.remove('sheet-open');
  focusStation(ST[+b.dataset.i]);
});
function focusStation(s) {
  map.flyTo([s.la, s.lo], Math.max(map.getZoom(), 13), { duration: .6 });
  setTimeout(() => { const m = mk['s' + s.i]; if (m) m.openPopup(); }, 650);
}
function updateChip() {
  const n = state.center ? state.proches.length : ST.filter(vis).length;
  $('chip-txt').textContent = state.center ? 'Afficher les stations du rayon' : 'Afficher toutes les stations';
  $('chip-n').textContent = nb(n);
}
function legend() {
  const it = (html, t) => `<div>${html}${t}</div>`;
  const rond = c => `<i style="width:12px;height:12px;border-radius:50%;background:${c};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3)"></i>`;
  const gr = RES_ORDRE.filter(r => state.res[r] && ST.some(s => !s.fav && s.r === r));
  $('legend').innerHTML = [it('<i style="width:12px;height:12px;border-radius:50%;background:#2f6bff;border:2px solid #ffcc00;box-shadow:0 1px 3px rgba(0,0,0,.3)"></i>', 'Mes stations')]
    .concat(gr.map(r => it(rond(RES[r].c), RES[r].l))).concat([
    it('<i style="background:#1d1d1f;color:#fff;border:1.5px solid #fff;border-radius:5px;font:700 8px/11px var(--font);padding:0 3px;box-shadow:0 1px 3px rgba(0,0,0,.3)">PL</i>', 'Accès PL confirmé'),
    it('<i style="width:12px;height:12px;border-radius:50%;border:3px solid #e53935;background:#fff"></i>', 'Centre de recherche'),
  ]).concat(nHors() ? [it('<i style="width:12px;height:12px;border-radius:50%;background:#8e8e93;opacity:.5;box-shadow:0 0 0 1.5px #fff"></i>', 'Non confirmée (hors liste officielle)')] : []).join('');
}

function setCenter(c, fit = true) {
  state.center = c; renderZone();
  if (fit && circle) fitTo(circle.getBounds());
  if (state.zone === 'rayon') planifierRecherche();
}
function paysDuCentre(cc) {
  cc = (cc || '').toUpperCase();
  if (!cc || !PAYS[cc] || state.paysManuel) return;
  state.paysRech = cc; $('pays-rech').value = cc;
  if (state.zone === 'pays') planifierRecherche();
}

// ══ Recherche des autres stations (OpenStreetMap via Overpass, depuis le navigateur) ══
const RX_AS24 = /\bAS ?24\b/, RX_CK = /\bCIRCLE ?K\b/, RX_TOTAL_BRAND = /^(TOTAL ?ENERGIES|TOTAL|ELAN)\b/,
      RX_TOTAL = /\bTOTAL ?ENERGIES\b|^TOTAL\b|\bTOTAL ACCESS\b/;
function classer(t) {   // la marque décide si elle est renseignée ; sinon le nom, puis l'exploitant
  for (const champ of ['brand', 'name', 'operator']) {
    const v = nn(t[champ]); if (!v) continue;
    if (RX_AS24.test(v)) return 'as24';
    if (RX_CK.test(v)) return 'circlek';
    if ((champ === 'brand' ? RX_TOTAL_BRAND : RX_TOTAL).test(v)) return 'total';
    if (champ === 'brand') return null;     // autre marque explicite (Esso, Q8…)
  }
  return null;
}
function enseigne(r, t) {
  const txt = nn(`${t.brand || ''} ${t.name || ''}`);
  if (r === 'total') return /\bELAN\b/.test(nn(t.brand)) ? 'Elan (TotalEnergies)' : txt.includes('ACCESS') ? 'TotalEnergies Access' : 'TotalEnergies';
  if (r === 'circlek') return txt.includes('TRUCK') ? 'Circle K Truck' : 'Circle K';
  return 'AS24';
}
function ouiNon(v) { v = (v || '').trim().toLowerCase(); return ['yes', 'designated', 'only'].includes(v) ? 1 : v === 'no' ? 0 : null; }
function accesPL(r, t) {
  if (r === 'as24') return 1;
  if (ouiNon(t['fuel:HGV_diesel']) === 1 || ouiNon(t.hgv) === 1) return 1;
  if (nn(`${t.brand || ''} ${t.name || ''}`).includes('TRUCK')) return 1;
  if (ouiNon(t.hgv) === 0) return 0;
  return null;
}
function requete(filtre, tmo) {
  const reg = (k, x) => `nwr${filtre}["amenity"="fuel"]["${k}"~"${x}",i];`;
  return `[out:json][timeout:${tmo}];${filtre.startsWith('(area') ? `area["ISO3166-1"="${state.paysRech}"]["admin_level"="2"]->.a;` : ''}(`
    + reg('brand', 'total|circle ?k|as ?24|^elan') + reg('name', 'total|circle ?k|as ?24') + reg('operator', 'total|circle ?k|as ?24')
    + ');out center tags;';
}
async function overpass(q, tmo, signal) {
  const err = [];
  for (const url of D.overpass) {
    const hote = new URL(url).host;
    for (let essai = 0; essai < 2; essai++) {
      if (signal.aborted) throw new DOMException('annulé', 'AbortError');
      const ctl = new AbortController(), stop = () => ctl.abort();
      signal.addEventListener('abort', stop, { once: true });
      const t = setTimeout(stop, (tmo + 20) * 1000);
      try {
        const r = await fetch(url, { method: 'POST', body: 'data=' + encodeURIComponent(q),
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, signal: ctl.signal });
        if (!r.ok) {
          err.push(`${hote} : HTTP ${r.status}`);
          if ([429, 502, 503, 504].includes(r.status) && essai === 0) { await new Promise(ok => setTimeout(ok, 6000)); continue; }
          break;
        }
        const j = await r.json();
        if (/runtime error/i.test(j.remark || '')) { err.push(`${hote} : réponse incomplète`); break; }
        return j;
      } catch (e) {
        if (signal.aborted) throw e;
        err.push(`${hote} : ${e.name === 'AbortError' ? 'délai dépassé' : 'injoignable'}`);
        break;
      } finally { clearTimeout(t); signal.removeEventListener('abort', stop); }
    }
  }
  throw new Error(err.join(' ; '));
}

// Index spatial (~150 m) des stations déjà sur la carte, pour fusionner les doublons
const grille = new Map();
const gk = (la, lo) => `${Math.round(la * 300)}:${Math.round(lo * 200)}`;
function indexer(s) { const k = gk(s.la, s.lo); if (!grille.has(k)) grille.set(k, []); grille.get(k).push(s); }
function voisins(la, lo, metres, test) {
  const a = Math.round(la * 300), b = Math.round(lo * 200);
  let best = null, dmin = metres / 1000;
  for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (const s of grille.get(`${a + x}:${b + y}`) || []) {
    if (test && !test(s)) continue;
    const d = hav(la, lo, s.la, s.lo); if (d <= dmin) { best = s; dmin = d; }
  }
  return best;
}
ST.forEach(indexer);
const vusOsm = new Set(ST.map(s => s.id).filter(Boolean));
const ckAjoutes = new Set();

// Prix officiels France : par l'identifiant du flux stocké dans OSM, sinon le point le plus proche à moins de 120 m
const PRIX = D.prix_fr || [];               // [lat, lon, id, prix, maj, piste PL]
const prixId = new Map(), prixGrille = new Map();
PRIX.forEach(p => { if (p[2]) prixId.set(p[2], p); const k = `${Math.round(p[0] * 100)}:${Math.round(p[1] * 70)}`; if (!prixGrille.has(k)) prixGrille.set(k, []); prixGrille.get(k).push(p); });
function lierPrix(s, refFr) {
  let p = refFr ? prixId.get(refFr) : null;
  if (!p) {
    const a = Math.round(s.la * 100), b = Math.round(s.lo * 70); let dmin = .12;
    for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (const q of prixGrille.get(`${a + x}:${b + y}`) || []) {
      const d = hav(s.la, s.lo, q[0], q[1]); if (d < dmin) { p = q; dmin = d; }
    }
  }
  if (p) {
    if (!s.p) s.p = 'FR';
    if (p[3] != null && s.p === 'FR') { s.px = p[3]; s.pxm = p[4]; s.pxs = 'station'; }
    if (p[5] && s.p === 'FR') { s.pl = 1; s.plo = 1; }
  }
  if (s.px == null && s.p === 'BE' && D.prix_be) { s.px = D.prix_be.px; s.pxm = D.prix_be.label; s.pxs = 'max'; }
}
function enrichir(cible, s) {
  for (const k of ['pl', 'ad', 'lng', 'cng']) if (cible[k] == null && s[k] != null) cible[k] = s[k];
  for (const k of ['h', 't', 'w', 'id']) if (!cible[k] && s[k]) cible[k] = s[k];
  if (cible.px == null && s.px != null) { cible.px = s.px; cible.pxm = s.pxm; cible.pxs = s.pxs; }
  prep(cible);
}
function ajouter(s) { s.i = ST.length; ST.push(s); prep(s); indexer(s); if (s.id) vusOsm.add(s.id); }

function versStation(el, ccZone) {
  const t = el.tags || {};
  const la = el.lat ?? el.center?.lat, lo = el.lon ?? el.center?.lon;
  if (la == null || lo == null || la < EUROPE.s || la > EUROPE.n || lo < EUROPE.w || lo > EUROPE.e) return null;
  const r = classer(t); if (!r) return null;
  const pc = (t['addr:country'] || '').toUpperCase().slice(0, 2);
  return {
    r, e: enseigne(r, t), n: t.name || t.brand || RES[r].l, a: [t['addr:street'], t['addr:housenumber']].filter(Boolean).join(' '),
    cp: t['addr:postcode'] || '', v: t['addr:city'] || t['addr:place'] || '', p: ccZone || (PAYS[pc] ? pc : ''),
    la: +(+la).toFixed(6), lo: +(+lo).toFixed(6), pl: accesPL(r, t), ad: ouiNon(t['fuel:adblue']), lng: ouiNon(t['fuel:lng']), cng: ouiNon(t['fuel:cng']),
    h: t.opening_hours || '', t: t.phone || t['contact:phone'] || '', w: t.website || t['contact:website'] || '',
    id: `${el.type || 'node'}/${el.id}`, src: 'osm', _ref: (t['ref:FR:prix-carburants'] || '').replace(/\D/g, ''), _nt: Object.keys(t).length,
  };
}
// Intègre une réponse Overpass (et la liste officielle Circle K de la même zone) aux stations de la carte
function integrer(data, dansZone, ccZone) {
  let n = 0;
  // 1. liste officielle Circle K (BE, LU, NL, DE) de la zone, avant OSM : elle fait foi
  for (const o of D.ck || []) {
    if (ckAjoutes.has(o.code) || !dansZone(o)) continue;
    ckAjoutes.add(o.code);
    const f = voisins(o.la, o.lo, 150, s => s.fav);
    if (f) { enrichir(f, o); continue; }
    const s = { ...o }; lierPrix(s); ajouter(s); n++;
  }
  // 2. OpenStreetMap, fiche la plus complète d'abord (une station dessinée en point et en surface)
  const els = (data.elements || []).map(el => versStation(el, ccZone)).filter(Boolean).sort((a, b) => b._nt - a._nt);
  for (const s of els) {
    if (vusOsm.has(s.id)) continue;
    vusOsm.add(s.id);
    const f = voisins(s.la, s.lo, 150, x => x.fav);
    if (f) { if (!f.id) f.id = s.id; enrichir(f, s); continue; }                       // déjà dans mes stations
    if (voisins(s.la, s.lo, 80, x => !x.fav && x.r === s.r && x.src !== 'officiel')) continue;   // doublon point / surface
    if (s.r !== 'as24') {
      const o = voisins(s.la, s.lo, 250, x => x.src === 'officiel');
      if (o) { if (!o.id) o.id = s.id; enrichir(o, s); continue; }                     // fusion avec la liste officielle
    }
    lierPrix(s, s._ref);
    if (D.ck && D.ck.length && CK_PAYS.has(s.p) && s.r !== 'as24') s.src = 'osm_hors';
    delete s._ref; delete s._nt;
    ajouter(s); n++;
  }
  return n;
}

const deja = { cercles: [], pays: new Set() };
let rechCtl = null, rechTmr = null;
const actifs = () => RES_RECH.filter(r => state.res[r]);
function etat(html, cl = '', spin = false) { $('rech-etat').className = 'etat ' + cl; $('rech-etat').innerHTML = (spin ? '<span class="spin"></span>' : '') + `<span>${html}</span>`; }
function etatRepos(avant = '') {
  const a = actifs();
  if (!a.length) { etat(avant + 'Activez un réseau : la recherche part sur OpenStreetMap' + (state.zone === 'rayon' ? ', dans le rayon autour du point choisi.' : `, dans tout le pays choisi.`)); return; }
  if (state.zone === 'rayon' && !state.center) { etat(avant + 'Choisissez un point (adresse, clic sur la carte ou ma position) : la recherche se lance dans le rayon. Ou passez sur « Tout le pays ».'); return; }
  const n = compte(ST.filter(s => !s.fav));
  const zoneTxt = state.zone === 'rayon' ? `${state.rayon} km autour du point` : `${PAYS[state.paysRech] || state.paysRech} (tout le pays)`;
  etat(avant + `${a.map(r => `${RES[r].l} : <b>${nb(n[r] || 0)}</b>`).join(' · ')} trouvée(s) au total. Zone parcourue : ${zoneTxt}.`, 'ok');
}
function majCompteurs() {
  const n = compte(ST.filter(s => !s.fav));
  RES_RECH.forEach(r => {
    const el = $('n-' + r); if (!el) return;
    el.textContent = state.res[r] || n[r] ? `${nb(n[r] || 0)} trouvée(s) · ${RES[r].s}` : `${RES[r].s} · cherchées à l’activation`;
  });
}
function couvert() {
  if (state.zone === 'pays') return deja.pays.has(state.paysRech);
  const c = state.center; if (!c) return true;
  return deja.cercles.some(z => hav(z.lat, z.lon, c.lat, c.lon) + state.rayon <= z.r + .01);
}
function planifierRecherche(delai = 350) {
  clearTimeout(rechTmr);
  rechTmr = setTimeout(rechercher, delai);
}
async function rechercher() {
  if (!actifs().length || (state.zone === 'rayon' && !state.center)) { etatRepos(); return; }
  if (couvert()) { etatRepos(); return; }
  if (rechCtl) rechCtl.abort();
  const ctl = rechCtl = new AbortController();
  let q, tmo, dansZone, cc = '', libelle, zoneOk = null;
  if (state.zone === 'rayon') {
    const c = state.center, R = state.rayon;
    tmo = 90; q = requete(`(around:${Math.round(R * 1000)},${c.lat.toFixed(5)},${c.lon.toFixed(5)})`, tmo);
    dansZone = s => hav(c.lat, c.lon, s.la, s.lo) <= R;
    libelle = `dans un rayon de ${R} km`;
    zoneOk = { lat: c.lat, lon: c.lon, r: R };
  } else {
    cc = state.paysRech; tmo = 240; q = requete('(area.a)', tmo);
    dansZone = s => s.p === cc;
    libelle = `dans tout le pays : ${PAYS[cc] || cc}`;
  }
  etat(`Recherche ${libelle}…${state.zone === 'pays' ? ' Jusqu’à une minute pour un grand pays.' : ''}`, '', true);
  try {
    const data = await overpass(q, tmo, ctl.signal);
    if (ctl !== rechCtl) return;
    const n = integrer(data, dansZone, cc);
    if (state.zone === 'rayon') deja.cercles.push(zoneOk); else deja.pays.add(cc);
    rechCtl = null;
    renderDots(); majCompteurs(); facts();
    etatRepos(n ? `${nb(n)} nouvelle(s) station(s) ${libelle}. ` : `Aucune nouvelle station ${libelle}. `);
  } catch (e) {
    if (e.name === 'AbortError' && ctl !== rechCtl) return;
    rechCtl = null;
    etat(`OpenStreetMap n’a pas répondu (${esc(e.message)}). <button class="lien" id="relancer">Réessayer</button>`, 'err');
  }
}
$('rech-etat').addEventListener('click', e => { if (e.target.id === 'relancer') rechercher(); });

// ── Recherche d'adresse ──
let tmr = null, resultats = [], actif = -1;
function afficherResultats() {
  const ul = $('results');
  if (!resultats.length) { ul.innerHTML = '<li class="vide">Aucun résultat. Essayez avec le code postal.</li>'; ul.classList.add('show'); return; }
  ul.innerHTML = resultats.map((r, i) => `<li role="option" data-i="${i}" class="${i === actif ? 'active' : ''}">${r.fav ? '<span class="star">★</span> ' : ''}${esc(r.label)}<small>${esc(r.sub)}</small></li>`).join('');
  ul.classList.add('show');
}
async function chercherAdresse(q) {
  const qn = nn(q);
  const loc = qn.length >= 3 ? ST.filter(s => s._nn.includes(qn)).sort((a, b) => (b.fav || 0) - (a.fav || 0)).slice(0, 4)
    .map(s => ({ label: s.n, sub: `${s.e}, ${[lieu(s), PAYS[s.p] || s.p].filter(Boolean).join(', ')}`, lat: s.la, lon: s.lo, cc: s.p, fav: s.fav })) : [];
  let geo = [];
  try {
    const j = await (await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=5&lang=fr`)).json();
    geo = (j.features || []).map(f => {
      const p = f.properties || {}, [lo, la] = f.geometry.coordinates;
      const rue = [p.street, p.housenumber].filter(Boolean).join(' ');
      return { label: p.name || rue || p.city || q, sub: [p.name ? rue : '', [p.postcode, p.city].filter(Boolean).join(' '), p.country].filter(Boolean).join(', '), lat: la, lon: lo, cc: p.countrycode };
    });
  } catch (e) {
    try {
      const j = await (await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5&addressdetails=1`)).json();
      geo = j.map(d => ({ label: d.display_name.split(',')[0], sub: d.display_name.split(',').slice(1, 4).join(',').trim(), lat: +d.lat, lon: +d.lon, cc: d.address?.country_code }));
    } catch (e2) { }
  }
  if ($('q').value.trim() !== q) return;
  resultats = loc.concat(geo); actif = resultats.length ? 0 : -1; afficherResultats();
}
function choisir(i) {
  const r = resultats[i]; if (!r) return;
  $('q').value = r.label; $('results').classList.remove('show');
  paysDuCentre(r.cc);
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

async function libelleInverse(c) {
  try {
    const j = await (await fetch(`https://photon.komoot.io/reverse?lat=${c.lat}&lon=${c.lon}&lang=fr`)).json();
    const p = (j.features || [])[0]?.properties;
    if (p && state.center === c) {
      c.label = [[p.street, p.housenumber].filter(Boolean).join(' '), [p.postcode, p.city || p.name].filter(Boolean).join(' '), p.country].filter(Boolean).join(', ') || c.label;
      updateInfo(); paysDuCentre(p.countrycode);
    }
  } catch (err) { }
}
map.on('click', e => {
  const c = { lat: e.latlng.lat, lon: e.latlng.lng, label: `Point sélectionné (${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)})` };
  setCenter(c, false); libelleInverse(c);
});
$('geoloc').addEventListener('click', () => {
  if (!navigator.geolocation) { $('pos-hint').textContent = 'Géolocalisation indisponible dans ce navigateur.'; return; }
  $('pos-hint').textContent = 'Localisation en cours…';
  navigator.geolocation.getCurrentPosition(p => {
    $('pos-hint').textContent = 'Ou cliquez directement sur la carte.';
    const c = { lat: p.coords.latitude, lon: p.coords.longitude, label: 'Ma position' };
    setCenter(c); libelleInverse(c);
  }, () => { $('pos-hint').textContent = 'Position refusée ou introuvable. Cherchez une adresse à la place.'; }, { timeout: 10000 });
});

// ── Réglages ──
function majRayon() {
  const r = $('rayon'); $('rval').textContent = `${r.value} km`;
  r.style.setProperty('--p', `${(r.value - r.min) / (r.max - r.min) * 100}%`);
}
$('rayon').addEventListener('input', () => { majRayon(); state.rayon = +$('rayon').value; renderZone(); });
$('rayon').addEventListener('change', () => { if (circle) fitTo(circle.getBounds()); if (state.zone === 'rayon') planifierRecherche(); });
$('fav-n').textContent = `${nb(N_FAV)} station(s)${D.fav_fichier ? ' · ' + D.fav_fichier : ''}`;
$('t-fav').addEventListener('change', e => { state.fav = e.target.checked; renderDots(); });
$('reseaux').innerHTML = RES_RECH.map(r =>
  `<label class="row"><span class="nm"><span class="dot" style="background:${RES[r].c}">${RES[r].k}</span><span>${RES[r].l}<br><small id="n-${r}"></small></span></span><span class="sw"><input type="checkbox" data-r="${r}"><span></span></span></label>`).join('');
$('reseaux').addEventListener('change', e => {
  const r = e.target.dataset.r; if (!r) return;
  state.res[r] = e.target.checked; renderDots(); majCompteurs();
  if (e.target.checked) rechercher(); else etatRepos();
});
$('pays-rech').innerHTML = Object.entries(PAYS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
$('pays-rech').value = state.paysRech;
$('pays-rech').addEventListener('change', e => { state.paysRech = e.target.value; state.paysManuel = true; rechercher(); });
$('zone').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.zone = b.dataset.z; [...$('zone').children].forEach(x => x.classList.toggle('on', x === b));
  $('pays-rech').style.display = state.zone === 'pays' ? 'block' : 'none';
  rechercher();
});
$('f-pl').addEventListener('change', e => { state.pl = e.target.checked; renderDots(); });
$('f-ad').addEventListener('change', e => { state.ad = e.target.checked; renderDots(); });
$('f-24').addEventListener('change', e => { state.h24 = e.target.checked; renderDots(); });
$('f-hors').addEventListener('change', e => { state.sansDoute = e.target.checked; renderDots(); });
$('fonds').innerHTML = Object.keys(FONDS).map(k => `<button data-f="${k}" class="${k === state.fond ? 'on' : ''}">${k}</button>`).join('');
$('fonds').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.fond = b.dataset.f; [...$('fonds').children].forEach(x => x.classList.toggle('on', x === b)); applyFond();
});
$('t-borders').addEventListener('change', e => { state.borders = e.target.checked; drawBorders(); });
$('t-hors').addEventListener('change', e => { state.hors = e.target.checked; renderDots(); });
$('collapse').addEventListener('click', () => {
  document.body.classList.toggle('collapsed');
  $('collapse').setAttribute('aria-label', document.body.classList.contains('collapsed') ? 'Afficher le panneau' : 'Réduire le panneau');
});

// ── Feuille de détail ──
$('chip').addEventListener('click', () => { document.body.classList.add('sheet-open'); renderSheet(); });
$('close').addEventListener('click', () => document.body.classList.remove('sheet-open'));
document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.activeElement !== $('q')) document.body.classList.remove('sheet-open'); });
$('filtre').addEventListener('input', () => { state.filtre = nn($('filtre').value); renderSheet(); });
$('tbl').addEventListener('click', e => {
  const th = e.target.closest('th[data-k]');
  if (th) { const k = th.dataset.k; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : 1 }; renderSheet(); return; }
  if (e.target.closest('a')) return;
  const tr = e.target.closest('tr[data-i]'); if (tr) focusStation(ST[+tr.dataset.i]);
});

const oui = v => v === 1 ? '<span class="ok">Oui</span>' : v === 0 ? '<span class="ko">Non</span>' : '<span class="nr">—</span>';
const COLS = [
  ['fav', '★', '', v => v ? '<span class="star">★</span>' : '', s => s.fav ? 'Oui' : ''],
  ['r', 'Réseau', '', (v, s) => `<span class="badge" style="background:${RES[v].c}">${RES[v].l}</span>`, s => RES[s.r].l],
  ['n', 'Station'], ['e', 'Enseigne'], ['code', 'Code'], ['a', 'Adresse'], ['cp', 'CP'], ['v', 'Localité'],
  ['p', 'Pays', '', v => esc(PAYS[v] || v), s => PAYS[s.p] || s.p],
  ['dist', 'Distance (km)', 'num', v => km(v), s => s.dist == null ? '' : Math.round(s.dist * 10) / 10],
  ['pl', 'Accès PL', '', v => v === 1 ? '<span class="ok">Confirmé</span>' : v === 0 ? '<span class="ko">Interdit</span>' : '<span class="nr">—</span>', s => plTxt(s.pl)],
  ['px', 'Gazole €/L', 'num', (v, s) => v == null ? '<span class="nr">—</span>' : `<span${state.best.prix && state.best.prix.i === s.i ? ' class="ok"' : ''}>${eurL(v).replace(' €', '')}</span>${s.pxs === 'max' ? '<span class="nr"> max</span>' : ''}`, s => s.px ?? ''],
  ['ad', 'AdBlue', '', oui, s => s.ad === 1 ? 'Oui' : s.ad === 0 ? 'Non' : ''],
  ['h24', '24 h/24', '', v => v ? '<span class="ok">Oui</span>' : '<span class="nr">—</span>', s => s.h24 ? 'Oui' : ''],
  ['h', 'Horaires', 'hor', (v, s) => s.h24 ? '' : esc(v)],
  ['t', 'Téléphone'],
  ['src', 'Source', '', v => { const x = SRC[v] || SRC.osm; return `<span class="${x[0]}">${x[1]}</span>`; }, s => (SRC[s.src] || SRC.osm)[1]],
  ['_iti', 'Itinéraire', '', (v, s) => `<a href="${iti(s)}" target="_blank" rel="noopener">${state.center ? 'Itinéraire' : 'Carte'}</a>`, s => iti(s)],
];
function lignes() {
  let rows = state.center ? state.proches : ST.filter(vis);
  if (state.filtre) rows = rows.filter(s => nn(`${s.n} ${s.e} ${s.code || ''} ${s.a} ${s.cp} ${s.v} ${PAYS[s.p] || s.p}`).includes(state.filtre));
  const { key, dir } = state.sort;
  return rows.slice().sort((a, b) => {
    const x = a[key], y = b[key]; if (x == null && y == null) return 0; if (x == null || x === '') return 1; if (y == null || y === '') return -1;
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'fr')) * dir;
  });
}
function renderSheet() {
  $('sheet-ttl').textContent = state.center ? `Stations à moins de ${state.rayon} km` : 'Toutes les stations affichées';
  const rows = lignes();
  if (!rows.length) {
    $('tbl').innerHTML = `<div class="empty">${state.center ? `Aucune station dans un rayon de ${state.rayon} km avec les filtres actuels.` : 'Aucune station avec les filtres actuels.'}</div>`;
    return;
  }
  const { key, dir } = state.sort;
  const th = COLS.map(([k, l, cl]) => `<th data-k="${k}" class="${cl || ''}">${esc(l)}${k === key ? ` <span class="arr">${dir > 0 ? '↑' : '↓'}</span>` : ''}</th>`).join('');
  const body = rows.slice(0, MAX_LIGNES).map(s => `<tr class="click" data-i="${s.i}">${COLS.map(([k, , cl, fmt]) => `<td class="${cl || ''}">${fmt ? fmt(s[k], s) : esc(s[k] ?? '')}</td>`).join('')}</tr>`).join('');
  const plus = rows.length > MAX_LIGNES ? `<div class="more">${MAX_LIGNES} premières lignes sur ${nb(rows.length)}. L’export contient tout.</div>` : '';
  $('tbl').innerHTML = `<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>${plus}`;
}
$('export').addEventListener('click', () => {
  const rows = lignes(); if (!rows.length) return;
  const data = rows.map(s => Object.fromEntries(COLS.map(([k, l, , , ex]) => [k === 'fav' ? 'Mes stations' : l, ex ? ex(s) : (s[k] ?? '')])));
  const nom = state.center ? 'pompes_rayon' : 'pompes_affichees';
  if (window.XLSX) {
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data), 'Stations');
    XLSX.writeFile(wb, `${nom}.xlsx`);
  } else {
    const cols = Object.keys(data[0]);
    const csv = '﻿' + [cols.join(';')].concat(data.map(r => cols.map(c => `"${String(r[c]).replace(/"/g, '""')}"`).join(';'))).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = `${nom}.csv`; a.click();
  }
});

// ── Démarrage ──
function facts() {
  const fav = ST.filter(s => s.fav), autres = ST.filter(s => !s.fav);
  const parPays = {}; fav.forEach(s => parPays[s.p || '?'] = (parPays[s.p || '?'] || 0) + 1);
  const nPx = fav.filter(s => s.px != null && s.pxs === 'station').length;
  $('facts').innerHTML = `<b>${nb(fav.length)}</b> stations dans ma liste${D.fav_fichier ? ` (${esc(D.fav_fichier)})` : ''} : `
    + Object.entries(parPays).sort((a, b) => b[1] - a[1]).map(([p, n]) => `${esc(PAYS[p] || p)} ${nb(n)}`).join(', ') + '.'
    + (nPx ? `<br>Prix du gazole affiché pour <b>${nb(nPx)}</b> d’entre elles (flux officiel français, relevé le ${esc(D.prix_le)}).` : '')
    + (autres.length ? `<br><b>${nb(autres.length)}</b> autres stations chargées : OpenStreetMap${D.ck && D.ck.length ? ', et liste officielle Circle K en BE, LU, NL et DE (en BE et LU, pompes TotalEnergies, boutique Circle K)' : ''}.` : '')
    + (nHors() ? ` ${nHors()} station(s) OpenStreetMap non confirmée(s) par la liste officielle.` : '')
    + (D.prix_be ? `<br>Belgique : prix maximum officiel du gasoil routier.` : '')
    + `<br>Carte préparée le ${esc(D.generated)} dans le HUB.`;
  $('row-hors').style.display = nHors() ? '' : 'none';
}
majRayon(); facts(); majCompteurs(); etatRepos(); legend(); applyFond(); renderDots();
if (N_FAV) fitTo(L.latLngBounds(ST.filter(s => s.fav).map(s => [s.la, s.lo])));
</script>
</body>
</html>
'''


def build_app_html(favorites: list, borders, extra: dict, fav_fichier: str = "") -> str:
    payload = {
        "stations": favorites, "fav_fichier": fav_fichier, "pays_noms": PAYS, "overpass": OVERPASS_URLS,
        "pays_defaut": "FR" if any(f["p"] == "FR" for f in favorites) or not favorites else favorites[0]["p"],
        "prix_fr": extra.get("prix_fr", []), "prix_le": extra.get("prix_le", ""), "prix_be": extra.get("prix_be"),
        "ck": extra.get("ck", []),
        "generated": datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
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


def excel_base(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Stations")
        ws = xw.sheets["Stations"]
        for i, col in enumerate(df.columns, start=1):
            larg = max([len(str(col))] + [len(str(v)) for v in df[col].head(500).tolist()])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(larg + 2, 8), 45)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    return buf.getvalue()


# ─── Page ────────────────────────────────────────────────────────────────────
ui.section("Mes stations")
source = fichier_favorites()
favorites, remarques = [], []
if source is not None:
    try:
        favorites, remarques = favorites_depuis(str(source), source.stat().st_mtime)
    except Exception as e:  # noqa: BLE001
        st.error(f"La liste {source.name} n’a pas pu être lue : {e}")
nom_liste = "liste importée depuis cette page" if source == FAV_LOCAL else (source.name if source else "")

if favorites:
    dff = pd.DataFrame(favorites)
    m1, m2, m3 = st.columns(3)
    m1.metric("Stations dans ma liste", f"{len(dff):,}".replace(",", " "))
    m2.metric("Accès PL", f"{int((dff['pl'] == 1).sum()):,}".replace(",", " "))
    m3.metric("Pays", ", ".join(PAYS.get(c, c) for c in dff["p"].value_counts().index if c) or "—")
    reseaux_txt = ", ".join(f"{v} {k}" for k, v in dff["e"].value_counts().items())
    groupes = ", ".join(sorted({g for g in dff["grp"] if g}))
    st.caption(f"Source : {nom_liste}{f' ({groupes})' if groupes else ''}. {reseaux_txt}. "
               "Elles s’affichent dès l’ouverture de la carte.")
    for r in remarques:
        st.caption(r)
else:
    st.info("Aucune liste de stations préférées : importez un fichier Excel ci-dessous.")

with st.expander("Remplacer la liste"):
    st.caption("Fichier Excel ou CSV, une ligne par station. Colonnes reconnues : LIBELLE (ou NOM), ADRESSE, "
               "CODE_POSTAL, VILLE, LATITUDE, LONGITUDE, et si possible MARQUE, NOM_GROUPE, CODE, PAYS. Sans "
               "coordonnées, les stations sont placées d’après le code postal et la localité.")
    up = st.file_uploader("Nouvelle liste", type=["xlsx", "xls", "csv"], key="pompes_fav_upload",
                          label_visibility="collapsed")
    if up is not None:
        try:
            essai, rem_essai = lire_favorites(up.getvalue(), up.name)
        except Exception as e:  # noqa: BLE001
            essai, rem_essai = [], []
            st.error(f"Fichier non reconnu : {e}")
        if essai:
            st.caption(f"{len(essai)} station(s) lue(s) dans {up.name}. " + " ".join(rem_essai))
            if st.button("Utiliser cette liste", type="primary"):
                FAV_LOCAL.parent.mkdir(parents=True, exist_ok=True)
                FAV_LOCAL.write_bytes(up.getvalue())
                favorites_depuis.clear()
                st.rerun()
    st.caption("La liste importée ici reste en place jusqu’au prochain redémarrage du serveur. Pour la garder "
               "définitivement, elle doit remplacer assets/pompes_favorites.xlsx dans le dépôt.")
    if FAV_LOCAL.exists() and FAV_ASSET.exists():
        if st.button("Revenir à la liste du dépôt"):
            FAV_LOCAL.unlink()
            favorites_depuis.clear()
            st.rerun()

ui.section("Carte")
st.caption("La carte s’ouvre avec mes stations. Dans le panneau « Autres stations », activer TotalEnergies, AS24 ou "
           "Circle K lance la recherche sur OpenStreetMap : dans le rayon autour du point choisi, ou dans tout le pays.")

try:
    frontieres = load_borders()
except Exception:  # noqa: BLE001
    frontieres = None

# Prix France, prix max Belgique, liste officielle Circle K et fiches circlek.lu : demandés en même temps.
# Déjà en cache (cas courant) → une seule carte envoyée, tout de suite. Sinon : carte avec mes stations
# d'abord, puis la carte complète une fois tout arrivé (deux envois au lieu de trois).
f_fr, f_be = par.lancer(prix_france), par.lancer(prix_max_belgique)
f_ck, f_lu = par.lancer(circlek_officiel), par.lancer(circlek_lu_services)
taches = [f_fr, f_be, f_ck, f_lu]
zone_bouton, zone_etat = st.empty(), st.empty()


def afficher_bouton(extra: dict) -> str:
    html_ = build_app_html(favorites, frontieres, extra, nom_liste)
    with zone_bouton.container():
        bouton_ouvrir(html_)
    return html_


if not par.attendre(taches, 1.5):
    afficher_bouton({})                       # mes stations tout de suite, le reste arrive ensuite
    zone_etat.caption("Chargement des prix du gazole et de la liste officielle Circle K…")
    par.attendre(taches)

extra: dict = {}
notes = []
pts = par.resultat(f_fr)
if pts:
    n_px = lier_prix_france(favorites, pts)
    extra["prix_fr"] = [[round(p["la"], 5), round(p["lo"], 5), p["id"], p["px"], p["maj"], 1 if p["pl"] else 0]
                        for p in pts if p["px"] is not None or p["pl"]]
    extra["prix_le"] = datetime.now().strftime("%d/%m/%Y à %H:%M")
    if any(f["p"] == "FR" for f in favorites):
        notes.append(f"Prix du gazole affiché pour {n_px} de mes stations (flux officiel français, mis à jour toutes "
                     "les 10 min).")
else:
    notes.append(f"Prix France indisponibles pour le moment ({str(f_fr.exception())[:120]}).")
if par.resultat(f_be):
    extra["prix_be"] = f_be.result()

officiel = par.resultat(f_ck)
if officiel:
    officiel = [dict(o) for o in officiel]
    serv = par.resultat(f_lu)
    if serv:
        for o in officiel:
            sv = serv.get(norm(o["n"]))
            if o["p"] == "LU" and sv:
                o["pl"] = sv["pl"] if sv["pl"] is not None else o["pl"]
                o["ad"] = sv["ad"] if sv["ad"] is not None else o["ad"]
                o["w"] = sv["w"]
    else:
        notes.append("Fiches circlek.lu indisponibles : pas de détail Pompe PL / AdBlue pour le Luxembourg.")
    for o in officiel:
        o["code"] = o.get("code") or f"{o['la']},{o['lo']}"
    extra["ck"] = officiel
else:
    notes.append("La liste officielle Circle K n’a pas répondu : en Belgique, au Luxembourg, aux Pays-Bas et en "
                 "Allemagne, la recherche utilisera OpenStreetMap seul.")

app_html = afficher_bouton(extra)
zone_etat.caption(" ".join(notes))
if frontieres is None:
    st.caption("Tracé des frontières indisponible pour le moment : la carte s’ouvre sans.")

if favorites:
    dff = pd.DataFrame(favorites)
    for c in ("px", "pxs", "pxm"):
        if c not in dff:
            dff[c] = None
    xls = dff.assign(
        Pays=dff["p"].map(PAYS),
        **{"Accès PL": dff["pl"].map({1: "Confirmé", 0: "Interdit"}).fillna("Non renseigné"),
           "Gazole €/L": dff["px"],
           "Prix mis à jour": dff["pxm"]},
    ).rename(columns={"code": "Code", "e": "Enseigne", "n": "Station", "a": "Adresse", "cp": "CP", "v": "Localité",
                      "la": "Latitude", "lo": "Longitude", "grp": "Réseau"})
    xls = xls[["Code", "Station", "Enseigne", "Réseau", "Adresse", "CP", "Localité", "Pays", "Latitude", "Longitude",
               "Accès PL", "Gazole €/L", "Prix mis à jour"]]
    d1, d2 = st.columns(2)
    with d1:
        st.download_button("Télécharger la carte (HTML)", lambda: app_html.encode("utf-8"), on_click="ignore",
                           file_name="carte_pompes_carburant.html", mime="text/html", use_container_width=True)
    with d2:
        st.download_button("Télécharger mes stations avec les prix (Excel)", lambda: excel_base(xls), on_click="ignore",
                           file_name="mes_stations_carburant.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

st.caption("Sources : ma liste Excel ; pour les autres stations, OpenStreetMap (cherché depuis la carte) et la liste "
           "officielle Circle K pour BE, LU, NL et DE. L’accès poids lourds, l’AdBlue et les horaires ne sont "
           "renseignés que pour une partie des stations OpenStreetMap.")
