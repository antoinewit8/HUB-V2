"""
Page Streamlit : Pompes TotalEnergies / Circle K
- Stations-service des réseaux TotalEnergies (avec AS24, sa filiale poids lourds) et Circle K,
  récupérées pays par pays dans OpenStreetMap (Overpass), mises en cache 7 jours
- La carte s'ouvre dans un nouvel onglet, en plein écran, dans le même esprit que Lavages citernes :
  panneau à gauche (style Apple), synthèse en haut à droite, détail en bas sur demande
- Carte téléchargeable en fichier HTML autonome, base téléchargeable en Excel
"""

import io
import re
import json
import unicodedata
import urllib.request as ureq
import urllib.parse as uparse
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import ui

ui.page("pompes", "Stations TotalEnergies, AS24 et Circle K autour d’un point, accès poids lourds et services. "
                  "La carte s’ouvre en plein écran dans un nouvel onglet.")

UA = {"User-Agent": "CB-Transport-Hub/1.0 (pompes carburant)"}

PAYS = {
    "BE": "Belgique", "LU": "Luxembourg", "FR": "France", "NL": "Pays-Bas", "DE": "Allemagne",
    "CH": "Suisse", "AT": "Autriche", "IT": "Italie", "ES": "Espagne", "PT": "Portugal",
    "GB": "Royaume-Uni", "IE": "Irlande", "DK": "Danemark", "SE": "Suède", "NO": "Norvège",
    "PL": "Pologne", "CZ": "Tchéquie", "SK": "Slovaquie", "HU": "Hongrie",
    "LT": "Lituanie", "LV": "Lettonie", "EE": "Estonie",
}
PAYS_DEFAUT = ["BE", "LU", "FR", "NL", "DE"]

RESEAUX = {
    "total": "TotalEnergies",
    "as24": "AS24 (TotalEnergies, poids lourds)",
    "circlek": "Circle K",
}

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Filtre large côté Overpass, tri fin côté Python (classer())
QUERY = """[out:json][timeout:240];
area["ISO3166-1"="{cc}"]["admin_level"="2"]->.a;
(
  nwr(area.a)["amenity"="fuel"]["brand"~"total|circle ?k|as ?24|^elan",i];
  nwr(area.a)["amenity"="fuel"]["name"~"total|circle ?k|as ?24",i];
  nwr(area.a)["amenity"="fuel"]["operator"~"total|circle ?k|as ?24",i];
);
out center tags;"""

EUROPE_BBOX = (-11.0, 35.0, 32.0, 72.0)  # ouest, sud, est, nord (écarte l'outre-mer)


# ─── Utilitaires ─────────────────────────────────────────────────────────────
def norm(text) -> str:
    if text is None:
        return ""
    s = unicodedata.normalize("NFD", str(text).upper().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


RX_AS24 = re.compile(r"\bAS ?24\b")
RX_CK = re.compile(r"\bCIRCLE ?K\b")
RX_TOTAL_BRAND = re.compile(r"^(TOTAL ?ENERGIES|TOTAL|ELAN)\b")
RX_TOTAL = re.compile(r"\bTOTAL ?ENERGIES\b|^TOTAL\b|\bTOTAL ACCESS\b")


def classer(tags: dict):
    """Réseau d'une station : 'total', 'as24', 'circlek' ou None.
    La marque (brand) décide si elle est renseignée ; sinon le nom, puis l'exploitant."""
    for champ in ("brand", "name", "operator"):
        v = norm(tags.get(champ))
        if not v:
            continue
        if RX_AS24.search(v):
            return "as24"
        if RX_CK.search(v):
            return "circlek"
        if (RX_TOTAL_BRAND if champ == "brand" else RX_TOTAL).search(v):
            return "total"
        if champ == "brand":
            return None  # autre marque explicite (Esso, Q8…) : on n'en veut pas
    return None


def enseigne(reseau: str, tags: dict) -> str:
    txt = norm(" ".join(str(tags.get(k, "")) for k in ("brand", "name")))
    if reseau == "total":
        if re.search(r"\bELAN\b", norm(tags.get("brand"))):
            return "Elan (TotalEnergies)"
        return "TotalEnergies Access" if "ACCESS" in txt else "TotalEnergies"
    if reseau == "circlek":
        return "Circle K Truck" if "TRUCK" in txt else "Circle K"
    return "AS24"


def oui_non(v):
    v = (v or "").strip().lower()
    if v in ("yes", "designated", "only"):
        return 1
    if v == "no":
        return 0
    return None


def acces_pl(reseau: str, tags: dict):
    """1 = confirmé, 0 = interdit, None = non renseigné."""
    if reseau == "as24":
        return 1
    if oui_non(tags.get("fuel:HGV_diesel")) == 1 or oui_non(tags.get("hgv")) == 1:
        return 1
    if "TRUCK" in norm(" ".join(str(tags.get(k, "")) for k in ("brand", "name"))):
        return 1
    if oui_non(tags.get("hgv")) == 0:
        return 0
    return None


def _overpass(query: str, timeout: int = 260) -> dict:
    body = uparse.urlencode({"data": query}).encode()
    derniere = None
    for url in OVERPASS_URLS:
        try:
            req = ureq.Request(url, data=body, headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
            with ureq.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            if "runtime error" in (data.get("remark") or "").lower():
                derniere = data["remark"]          # réponse partielle : on n'en veut pas en cache
                continue
            return data
        except Exception as e:  # noqa: BLE001
            derniere = e
    raise RuntimeError(f"OpenStreetMap n’a pas répondu ({derniere})")


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def stations_pays(cc: str) -> dict:
    """Stations TotalEnergies / AS24 / Circle K d'un pays. Lève une erreur si Overpass ne répond pas
    (une erreur n'est pas mise en cache : on réessaie au prochain chargement)."""
    data = _overpass(QUERY.format(cc=cc))
    w, s, e, n = EUROPE_BBOX
    out = []
    for el in data.get("elements", []):
        t = el.get("tags") or {}
        la = el.get("lat", (el.get("center") or {}).get("lat"))
        lo = el.get("lon", (el.get("center") or {}).get("lon"))
        if la is None or lo is None or not (s <= la <= n and w <= lo <= e):
            continue
        res = classer(t)
        if not res:
            continue
        rue = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
        out.append({
            "r": res,
            "e": enseigne(res, t),
            "n": t.get("name") or t.get("brand") or RESEAUX[res],
            "a": rue,
            "cp": t.get("addr:postcode", ""),
            "v": t.get("addr:city") or t.get("addr:place") or "",
            "p": cc,
            "la": round(float(la), 6),
            "lo": round(float(lo), 6),
            "pl": acces_pl(res, t),
            "ad": oui_non(t.get("fuel:adblue")),
            "lng": oui_non(t.get("fuel:lng")),
            "cng": oui_non(t.get("fuel:cng")),
            "h": t.get("opening_hours", ""),
            "t": t.get("phone") or t.get("contact:phone") or "",
            "w": t.get("website") or t.get("contact:website") or "",
            "id": f"{el.get('type', 'node')}/{el.get('id')}",
            "_nt": len(t),
        })
    return {"stations": dedoublonner(out), "osm": (data.get("osm3s") or {}).get("timestamp_osm_base", "")}


def dedoublonner(stations: list) -> list:
    """Une station dessinée à la fois en point et en surface : on garde la fiche la plus complète (< 80 m)."""
    stations = sorted(stations, key=lambda d: -d["_nt"])
    gardees, grille = [], {}
    for d in stations:
        cle = (round(d["la"] * 200), round(d["lo"] * 130))
        doublon = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for g in grille.get((cle[0] + dx, cle[1] + dy), []):
                    if g["r"] == d["r"] and abs(g["la"] - d["la"]) < 0.0008 and abs(g["lo"] - d["lo"]) < 0.0012:
                        doublon = True
                        break
        if not doublon:
            grille.setdefault(cle, []).append(d)
            gardees.append(d)
    for d in gardees:
        d.pop("_nt", None)
    return gardees


# ─── Frontières (même source que Lavages citernes) ───────────────────────────
BORDER_URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_boundary_lines_land.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_boundary_lines_land.geojson",
]


def _decimer(ligne, pas=0.003):
    if len(ligne) < 3:
        return [[round(p[0], 4), round(p[1], 4)] for p in ligne]
    out = [ligne[0]]
    for p in ligne[1:-1]:
        if abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= pas:
            out.append(p)
    out.append(ligne[-1])
    return [[round(p[0], 4), round(p[1], 4)] for p in out]


@st.cache_data(ttl=30 * 86400, show_spinner="Chargement des frontières…")
def load_borders():
    w, s, e, n = EUROPE_BBOX
    for url in BORDER_URLS:
        try:
            with ureq.urlopen(ureq.Request(url, headers=UA), timeout=40) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        lignes = []
        for f in data.get("features", []):
            g = f.get("geometry") or {}
            parts = [g["coordinates"]] if g.get("type") == "LineString" else (
                g["coordinates"] if g.get("type") == "MultiLineString" else [])
            for l in parts:
                if any(w <= p[0] <= e and s <= p[1] <= n for p in l):
                    lignes.append(_decimer(l))
        if lignes:
            return {"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "MultiLineString", "coordinates": lignes}}]}
    raise RuntimeError("frontières indisponibles")


# ─── Carte plein écran ───────────────────────────────────────────────────────
APP_HTML = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Pompes TotalEnergies · Circle K</title>
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
  <p class="lede">Stations TotalEnergies et Circle K autour d’un point, avec l’accès poids lourds quand il est connu.</p>

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
    <h2>Réseaux</h2>
    <div class="rows" id="reseaux"></div>
  </div>

  <div class="sec">
    <h2>Filtres</h2>
    <div class="rows">
      <label class="row"><span class="nm">Accès poids lourds confirmé</span><span class="sw"><input type="checkbox" id="f-pl"><span></span></span></label>
      <label class="row"><span class="nm">AdBlue à la pompe</span><span class="sw"><input type="checkbox" id="f-ad"><span></span></span></label>
      <label class="row"><span class="nm">Ouvert 24 h/24</span><span class="sw"><input type="checkbox" id="f-24"><span></span></span></label>
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
const ST = D.stations;
const RES = {
  total:   { l: 'TotalEnergies', c: '#2f6bff', k: 'T', s: 'stations-service' },
  as24:    { l: 'AS24', c: '#00a37a', k: 'A', s: 'poids lourds, filiale TotalEnergies' },
  circlek: { l: 'Circle K', c: '#e5202e', k: 'K', s: 'stations-service' },
};
const RES_ORDRE = Object.keys(RES).filter(r => ST.some(s => s.r === r));
const PAYS = D.pays_noms || {};
function esri(s) { return `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`; }
const FONDS = {
  'Satellite': { layers: [[esri('World_Imagery'), 'Tiles © Esri', 18], [esri('Reference/World_Boundaries_and_Places'), '© Esri', 18]],
                 front: '#ffd54f', halo: '#000000' },
  'Plan': { layers: [[esri('World_Street_Map'), 'Tiles © Esri', 18]], front: '#c62828', halo: '#ffffff' },
  'Sombre': { layers: [[esri('Canvas/World_Dark_Gray_Base'), 'Tiles © Esri', 16], [esri('Canvas/World_Dark_Gray_Reference'), '© Esri', 16]],
              front: '#ffd54f', halo: '#000000' },
};
const MAX_BADGES = 400, MAX_LIGNES = 600;

const state = { res: Object.fromEntries(RES_ORDRE.map(r => [r, true])), center: null, rayon: 30, fond: 'Satellite',
                borders: true, hors: true, pl: false, ad: false, h24: false, sort: { key: 'dist', dir: 1 }, filtre: '',
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
function gmaps(la, lo) { return `https://www.google.com/maps/search/?api=1&query=${la.toFixed(6)},${lo.toFixed(6)}`; }
function iti(s) {
  const c = state.center;
  return c ? `https://www.google.com/maps/dir/?api=1&origin=${c.lat.toFixed(6)},${c.lon.toFixed(6)}&destination=${s.la.toFixed(6)},${s.lo.toFixed(6)}&travelmode=driving` : gmaps(s.la, s.lo);
}
function lieu(s) { return [s.cp, s.v].filter(Boolean).join(' '); }
function plTxt(v) { return v === 1 ? 'Confirmé' : v === 0 ? 'Interdit' : 'Non renseigné'; }
function divIcon(html) { return L.divIcon({ className: 'cb-icon', html, iconSize: [0, 0], iconAnchor: [0, 0] }); }
ST.forEach((s, i) => { s.i = i; s.h24 = (s.h || '').trim() === '24/7'; s._nn = nn(`${s.n} ${s.v} ${s.cp}`); });
const vis = s => state.res[s.r] && (!state.pl || s.pl === 1) && (!state.ad || s.ad === 1) && (!state.h24 || s.h24);

// ── Carte ──
const map = L.map('map', { zoomControl: false, worldCopyJump: true, preferCanvas: false }).setView([49.8, 5.5], 6);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ position: 'bottomright', imperial: false }).addTo(map);
const canvas = L.canvas({ padding: .5 });
const dots = L.layerGroup().addTo(map);      // toutes les stations visibles (petits points, canvas)
const zone = L.layerGroup().addTo(map);      // centre, cercle et pastilles des stations du rayon
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
  const l = [`<b style="font-size:14px">${esc(s.n)}</b>`, `<span style="color:${r.c};font-weight:600">${esc(s.e)}</span>`];
  if (s.a) l.push(esc(s.a));
  l.push(`${esc(lieu(s))} ${esc(PAYS[s.p] || s.p)}`.trim());
  const tags = [tag(s.pl === 1, `PL : ${plTxt(s.pl).toLowerCase()}`)];
  if (s.ad === 1) tags.push(tag(true, 'AdBlue'));
  if (s.lng === 1) tags.push(tag(true, 'GNL'));
  if (s.cng === 1) tags.push(tag(true, 'GNC'));
  if (s.h24) tags.push(tag(true, '24 h/24'));
  l.push(`<div class="pop-tags">${tags.join('')}</div>`);
  if (s.h && !s.h24) l.push(`Horaires : ${esc(s.h)}`);
  if (s.t) l.push(`Tél. ${esc(s.t)}`);
  if (s.dist != null) l.push(`À ${km(s.dist)} km à vol d’oiseau`);
  const liens = [`<a href="${iti(s)}" target="_blank" rel="noopener">${state.center ? 'Itinéraire depuis le centre' : 'Ouvrir dans Google Maps'}</a>`];
  if (s.w) liens.push(`<a href="${esc(s.w)}" target="_blank" rel="noopener">Site</a>`);
  liens.push(`<a href="https://www.openstreetmap.org/${esc(s.id)}" target="_blank" rel="noopener">Fiche OSM</a>`);
  l.push(liens.join(' · '));
  return l.join('<br>');
}

// Petits points : reconstruits seulement quand les filtres changent
function renderDots() {
  dots.clearLayers(); for (const k in mk) delete mk[k];
  if (state.hors) {
    const n = ST.filter(vis).length, rad = n > 4000 ? 3.5 : 4.5;
    ST.forEach(s => {
      if (!vis(s)) return;
      const m = L.circleMarker([s.la, s.lo], { renderer: canvas, radius: rad, color: '#fff', weight: 1.2, fillColor: RES[s.r].c, fillOpacity: .95, bubblingMouseEvents: false })
        .bindTooltip(() => `${esc(s.n)} (${esc(s.v || PAYS[s.p] || s.p)})`).bindPopup(() => popup(s), { maxWidth: 320 });
      dots.addLayer(m); mk['s' + s.i] = m;
    });
  }
  renderZone();
}

// Zone : centre, cercle, pastilles des stations du rayon
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
    // Plus proche par réseau (et avec accès PL), même hors rayon
    ST.forEach(s => {
      if (!vis(s)) return;
      if (!state.best[s.r] || s.dist < state.best[s.r].dist) state.best[s.r] = s;
      if (s.pl === 1 && (!state.best.pl || s.dist < state.best.pl.dist)) state.best.pl = s;
    });
    const bestIds = new Set(Object.values(state.best).map(s => s.i));
    const badges = proches.slice(0, MAX_BADGES);
    const dejaLa = new Set(badges.map(s => s.i));
    Object.values(state.best).forEach(s => { if (!dejaLa.has(s.i)) { badges.push(s); dejaLa.add(s.i); } });
    badges.reverse().forEach(s => {
      const r = RES[s.r], best = bestIds.has(s.i);
      const html = `<div class="pp${best ? ' best' : ''}" style="--c:${r.c}">${r.k}${s.pl === 1 ? '<span class="pl">PL</span>' : ''}</div>`;
      const m = L.marker([s.la, s.lo], { icon: divIcon(html), riseOnHover: true, zIndexOffset: best ? 1000 : 0 })
        .bindTooltip(`${esc(s.n)} · ${km(s.dist)} km`, { direction: 'top', offset: [0, -14] }).bindPopup(() => popup(s), { maxWidth: 320 });
      zone.addLayer(m); mk['s' + s.i] = m;
    });
  }
  state.proches = proches;
  updateInfo(); updateChip(); legend();
  if (document.body.classList.contains('sheet-open')) renderSheet();
}

function compteParReseau(liste) {
  const o = {}; RES_ORDRE.forEach(r => o[r] = 0); liste.forEach(s => o[s.r]++); return o;
}
function updateInfo() {
  const c = state.center;
  const stat = (v, l) => `<div><div class="n">${v}</div><div class="l">${l}</div></div>`;
  if (!c) {
    const n = compteParReseau(ST.filter(vis));
    $('info').innerHTML = `<div class="k">Aucune position</div><div class="t">Choisissez un point</div>
      <div class="stats">${RES_ORDRE.map(r => stat(n[r].toLocaleString('fr-FR'), RES[r].l)).join('')}</div>
      <div class="s">Recherchez une adresse ou une station dans le panneau, ou cliquez sur la carte.</div>`;
    return;
  }
  const n = compteParReseau(state.proches), npl = state.proches.filter(s => s.pl === 1).length;
  const cases = RES_ORDRE.map(r => stat(n[r], RES[r].l)).concat(RES_ORDRE.length < 3 ? [stat(npl, 'PL confirmé')] : []);
  const near = (s, titre, col) => s ? `<button class="near" data-i="${s.i}"><div class="top"><span><i style="background:${col}"></i>${titre}</span><b${s.dist > state.rayon ? ' style="color:#b45a00"' : ''}>${km(s.dist)} km</b></div><div class="nn">${esc(s.n)}${s.v ? ' · ' + esc(s.v) : ''}</div></button>` : '';
  $('info').innerHTML = `<div class="k">Rayon de ${state.rayon} km autour de</div><div class="t">${esc(c.label)}</div>
    <div class="stats">${cases.join('')}</div>`
    + RES_ORDRE.filter(r => state.res[r]).map(r => near(state.best[r], `Plus proche ${RES[r].l}`, RES[r].c)).join('')
    + near(state.best.pl, 'Plus proche, accès PL confirmé', '#1d1d1f')
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
  $('chip-n').textContent = n.toLocaleString('fr-FR');
}
function legend() {
  const it = (html, t) => `<div>${html}${t}</div>`;
  const rond = c => `<i style="width:12px;height:12px;border-radius:50%;background:${c};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3)"></i>`;
  $('legend').innerHTML = RES_ORDRE.map(r => it(rond(RES[r].c), RES[r].l)).concat([
    it('<i style="background:#1d1d1f;color:#fff;border:1.5px solid #fff;border-radius:5px;font:700 8px/11px var(--font);padding:0 3px;box-shadow:0 1px 3px rgba(0,0,0,.3)">PL</i>', 'Accès PL confirmé'),
    it('<i style="width:12px;height:12px;border-radius:50%;border:3px solid #e53935;background:#fff"></i>', 'Centre de recherche'),
  ]).join('');
}

function setCenter(c, fit = true) {
  state.center = c; renderZone();
  if (fit && circle) fitTo(circle.getBounds());
}

// ── Recherche d'adresse ──
let tmr = null, resultats = [], actif = -1;
function afficherResultats() {
  const ul = $('results');
  if (!resultats.length) { ul.innerHTML = '<li class="vide">Aucun résultat. Essayez avec le code postal.</li>'; ul.classList.add('show'); return; }
  ul.innerHTML = resultats.map((r, i) => `<li role="option" data-i="${i}" class="${i === actif ? 'active' : ''}">${esc(r.label)}<small>${esc(r.sub)}</small></li>`).join('');
  ul.classList.add('show');
}
async function chercherAdresse(q) {
  const qn = nn(q);
  const loc = qn.length >= 3 ? ST.filter(s => s._nn.includes(qn)).slice(0, 3)
    .map(s => ({ label: s.n, sub: `${s.e}, ${[lieu(s), PAYS[s.p] || s.p].filter(Boolean).join(', ')}`, lat: s.la, lon: s.lo })) : [];
  let geo = [];
  try {
    const j = await (await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=5&lang=fr`)).json();
    geo = (j.features || []).map(f => {
      const p = f.properties || {}, [lo, la] = f.geometry.coordinates;
      const rue = [p.street, p.housenumber].filter(Boolean).join(' ');
      return { label: p.name || rue || p.city || q, sub: [p.name ? rue : '', [p.postcode, p.city].filter(Boolean).join(' '), p.country].filter(Boolean).join(', '), lat: la, lon: lo };
    });
  } catch (e) {
    try {
      const j = await (await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`)).json();
      geo = j.map(d => ({ label: d.display_name.split(',')[0], sub: d.display_name.split(',').slice(1, 4).join(',').trim(), lat: +d.lat, lon: +d.lon }));
    } catch (e2) { }
  }
  if ($('q').value.trim() !== q) return;
  resultats = loc.concat(geo); actif = resultats.length ? 0 : -1; afficherResultats();
}
function choisir(i) {
  const r = resultats[i]; if (!r) return;
  $('q').value = r.label; $('results').classList.remove('show');
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
      updateInfo();
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
$('rayon').addEventListener('change', () => { if (circle) fitTo(circle.getBounds()); });
$('reseaux').innerHTML = RES_ORDRE.map(r => {
  const n = ST.filter(s => s.r === r).length.toLocaleString('fr-FR');
  return `<label class="row"><span class="nm"><span class="dot" style="background:${RES[r].c}">${RES[r].k}</span><span>${RES[r].l}<br><small>${n} ${RES[r].s}</small></span></span><span class="sw"><input type="checkbox" data-r="${r}" checked><span></span></span></label>`;
}).join('');
$('reseaux').addEventListener('change', e => { const r = e.target.dataset.r; if (!r) return; state.res[r] = e.target.checked; renderDots(); });
$('f-pl').addEventListener('change', e => { state.pl = e.target.checked; renderDots(); });
$('f-ad').addEventListener('change', e => { state.ad = e.target.checked; renderDots(); });
$('f-24').addEventListener('change', e => { state.h24 = e.target.checked; renderDots(); });
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
  ['r', 'Réseau', '', (v, s) => `<span class="badge" style="background:${RES[v].c}">${RES[v].l}</span>`, s => RES[s.r].l],
  ['n', 'Station'], ['e', 'Enseigne'], ['a', 'Adresse'], ['cp', 'CP'], ['v', 'Localité'],
  ['p', 'Pays', '', v => esc(PAYS[v] || v), s => PAYS[s.p] || s.p],
  ['dist', 'Distance (km)', 'num', v => km(v), s => s.dist == null ? '' : Math.round(s.dist * 10) / 10],
  ['pl', 'Accès PL', '', v => v === 1 ? '<span class="ok">Confirmé</span>' : v === 0 ? '<span class="ko">Interdit</span>' : '<span class="nr">—</span>', s => plTxt(s.pl)],
  ['ad', 'AdBlue', '', oui, s => s.ad === 1 ? 'Oui' : s.ad === 0 ? 'Non' : ''],
  ['h24', '24 h/24', '', v => v ? '<span class="ok">Oui</span>' : '<span class="nr">—</span>', s => s.h24 ? 'Oui' : ''],
  ['h', 'Horaires', 'hor', (v, s) => s.h24 ? '' : esc(v)],
  ['t', 'Téléphone'],
  ['_iti', 'Itinéraire', '', (v, s) => `<a href="${iti(s)}" target="_blank" rel="noopener">${state.center ? 'Itinéraire' : 'Carte'}</a>`, s => iti(s)],
];
function lignes() {
  let rows = state.center ? state.proches : ST.filter(vis);
  if (state.filtre) rows = rows.filter(s => nn(`${s.n} ${s.e} ${s.a} ${s.cp} ${s.v} ${PAYS[s.p] || s.p}`).includes(state.filtre));
  const { key, dir } = state.sort;
  return rows.slice().sort((a, b) => {
    const x = a[key], y = b[key]; if (x == null && y == null) return 0; if (x == null || x === '') return 1; if (y == null || y === '') return -1;
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'fr')) * dir;
  });
}
function renderSheet() {
  $('sheet-ttl').textContent = state.center ? `Stations à moins de ${state.rayon} km` : 'Toutes les stations';
  const rows = lignes();
  if (!rows.length) {
    $('tbl').innerHTML = `<div class="empty">${state.center ? `Aucune station dans un rayon de ${state.rayon} km avec les filtres actuels.` : 'Aucune station avec les filtres actuels.'}</div>`;
    return;
  }
  const { key, dir } = state.sort;
  const th = COLS.map(([k, l, cl]) => `<th data-k="${k}" class="${cl || ''}">${esc(l)}${k === key ? ` <span class="arr">${dir > 0 ? '↑' : '↓'}</span>` : ''}</th>`).join('');
  const body = rows.slice(0, MAX_LIGNES).map(s => `<tr class="click" data-i="${s.i}">${COLS.map(([k, , cl, fmt]) => `<td class="${cl || ''}">${fmt ? fmt(s[k], s) : esc(s[k] ?? '')}</td>`).join('')}</tr>`).join('');
  const plus = rows.length > MAX_LIGNES ? `<div class="more">${MAX_LIGNES} premières lignes sur ${rows.length.toLocaleString('fr-FR')}. L’export contient tout.</div>` : '';
  $('tbl').innerHTML = `<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>${plus}`;
}
$('export').addEventListener('click', () => {
  const rows = lignes(); if (!rows.length) return;
  const data = rows.map(s => Object.fromEntries(COLS.map(([k, l, , , ex]) => [l, ex ? ex(s) : (s[k] ?? '')])));
  const nom = state.center ? 'pompes_rayon' : 'pompes_toutes';
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
const parPays = {}; ST.forEach(s => parPays[s.p] = (parPays[s.p] || 0) + 1);
const nPL = ST.filter(s => s.pl === 1).length;
$('facts').innerHTML = `<b>${ST.length.toLocaleString('fr-FR')}</b> stations sur la carte : `
  + Object.entries(parPays).sort((a, b) => b[1] - a[1]).map(([p, n]) => `${esc(PAYS[p] || p)} ${n.toLocaleString('fr-FR')}`).join(', ') + '.'
  + `<br><b>${nPL.toLocaleString('fr-FR')}</b> avec accès poids lourds confirmé.`
  + `<br>Source OpenStreetMap${D.osm ? `, données du ${esc(D.osm)}` : ''}. Base préparée le ${esc(D.generated)} dans le HUB.`
  + (D.manquants && D.manquants.length ? `<br>Pays non chargés : ${D.manquants.map(p => esc(PAYS[p] || p)).join(', ')}.` : '');
majRayon(); legend(); applyFond(); renderDots();
if (ST.length) fitTo(L.latLngBounds(ST.map(s => [s.la, s.lo])));
</script>
</body>
</html>
'''


def build_app_html(stations: list, osm: str, manquants: list, borders) -> str:
    payload = {
        "stations": stations, "osm": osm, "manquants": manquants, "pays_noms": PAYS,
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


# ─── Page de préparation ─────────────────────────────────────────────────────
ui.section("Zone et réseaux")
c1, c2 = st.columns([2, 1])
with c1:
    pays_sel = st.multiselect("Pays", list(PAYS), default=PAYS_DEFAUT, format_func=lambda c: PAYS[c], key="pompes_pays")
with c2:
    res_sel = [r for r, lbl in RESEAUX.items() if st.checkbox(lbl, value=True, key=f"pompes_{r}")]
st.caption("Chaque pays est chargé une fois depuis OpenStreetMap puis gardé 7 jours. "
           "Premier chargement : de quelques secondes (Luxembourg) à une minute (France, Allemagne).")

if not pays_sel or not res_sel:
    st.info("Choisissez au moins un pays et un réseau.")
    st.stop()

stations, manquants, dates = [], [], []
barre = st.progress(0.0, text="Chargement des stations…")
for i, cc in enumerate(pays_sel):
    barre.progress(i / len(pays_sel), text=f"Chargement des stations : {PAYS[cc]}…")
    try:
        res = stations_pays(cc)
    except Exception:  # noqa: BLE001
        manquants.append(cc)
        continue
    stations += [s for s in res["stations"] if s["r"] in res_sel]
    if res["osm"]:
        dates.append(res["osm"])
barre.empty()

if manquants:
    st.warning("OpenStreetMap n’a pas répondu pour : " + ", ".join(PAYS[c] for c in manquants)
               + ". Les autres pays sont chargés ; rechargez la page dans une minute pour réessayer.")
if not stations:
    st.error("Aucune station chargée.")
    st.stop()

df = pd.DataFrame(stations)
osm = ""
if dates:
    try:
        osm = datetime.strptime(min(dates)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        osm = ""

ui.section("Carte")
lib = {"total": "TotalEnergies", "as24": "AS24", "circlek": "Circle K"}
cols = st.columns(len(res_sel) + 1)
for col, r in zip(cols, res_sel):
    col.metric(lib[r], f"{int((df['r'] == r).sum()):,}".replace(",", " "))
cols[-1].metric("Accès PL confirmé", f"{int((df['pl'] == 1).sum()):,}".replace(",", " "))

recap = (df.assign(Pays=df["p"].map(PAYS), Réseau=df["r"].map(lib))
           .pivot_table(index="Pays", columns="Réseau", values="la", aggfunc="count", fill_value=0))
recap["Total"] = recap.sum(axis=1)
with st.expander("Détail par pays"):
    st.dataframe(recap.sort_values("Total", ascending=False), use_container_width=True)

try:
    frontieres = load_borders()
except Exception:  # noqa: BLE001
    frontieres = None

app_html = build_app_html(stations, osm, manquants, frontieres)
bouton_ouvrir(app_html)
if frontieres is None:
    st.caption("Tracé des frontières indisponible pour le moment : la carte s’ouvre sans.")

xls = df.assign(
    Réseau=df["r"].map(lib), Pays=df["p"].map(PAYS),
    **{"Accès PL": df["pl"].map({1: "Confirmé", 0: "Interdit"}).fillna("Non renseigné"),
       "AdBlue": df["ad"].map({1: "Oui", 0: "Non"}).fillna(""),
       "GNL": df["lng"].map({1: "Oui", 0: "Non"}).fillna(""),
       "GNC": df["cng"].map({1: "Oui", 0: "Non"}).fillna(""),
       "OSM": "https://www.openstreetmap.org/" + df["id"]},
).rename(columns={"e": "Enseigne", "n": "Station", "a": "Adresse", "cp": "CP", "v": "Localité",
                  "la": "Latitude", "lo": "Longitude", "h": "Horaires", "t": "Téléphone", "w": "Site"})
xls = xls[["Réseau", "Enseigne", "Station", "Adresse", "CP", "Localité", "Pays", "Latitude", "Longitude",
           "Accès PL", "AdBlue", "GNL", "GNC", "Horaires", "Téléphone", "Site", "OSM"]]

d1, d2, d3 = st.columns(3)
with d1:
    st.download_button("Télécharger la carte (HTML)", app_html.encode("utf-8"), file_name="carte_pompes_carburant.html",
                       mime="text/html", use_container_width=True)
with d2:
    st.download_button("Télécharger la base (Excel)", excel_base(xls), file_name="pompes_totalenergies_circlek.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
with d3:
    if st.button("Actualiser depuis OpenStreetMap", use_container_width=True):
        stations_pays.clear()
        st.rerun()

st.caption(f"Source OpenStreetMap{f', données du {osm}' if osm else ''}. Les réseaux officiels évoluent plus vite que la "
           "carte communautaire : une station récemment rebaptisée peut manquer ou apparaître sous l’ancienne marque. "
           "L’accès poids lourds, l’AdBlue et les horaires ne sont renseignés que pour une partie des stations.")
