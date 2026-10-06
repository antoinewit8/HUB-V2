# -*- coding: utf-8 -*-
"""
HUB — Carte Chesca
Colle le message de suivi Chesca : la page parse chaque ligne, géolocalise
les sites et affiche la carte + le tableau de dispatch.

Formats acceptés (séparateur virgule ou tiret) :
  GL51CHE – he will be around 10:15 at the unloading place in Sarre Union, we will keep you posted.
  B205ADN – he is heading unloading in Grunenbach – should be there tomorrow around 11:30

Dépendances : streamlit, pandas, pydeck, requests
Emplacement : outils/carte_chesca.py
"""

import json
import re
import time
import unicodedata
from datetime import date

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

from core import ui

ui.page_config("Carte Chesca")

CARTO_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "CB-HUB-Chesca/1.1 (dispatch tool)"}
PAYS_WEB = "fr,be,lu,de,nl,it,es,pt,at,ch,pl,cz,sk,hu,si,hr,ro,dk,gb,ie"

STATUTS = {
    "sur_dech":    {"label": "Sur place déchargement", "rgb": [240, 162,  60]},
    "sur_charg":   {"label": "Sur place chargement",   "rgb": [107, 203, 139]},
    "swap":        {"label": "Échange remorque",       "rgb": [227, 112, 127]},
    "lavage":      {"label": "Lavage",                 "rgb": [168, 143, 227]},
    "route_dech":  {"label": "En route déchargement",  "rgb": [ 79, 179, 201]},
    "route_charg": {"label": "En route chargement",    "rgb": [ 86, 168, 118]},
    "route":       {"label": "En route",               "rgb": [110, 150, 170]},
    "vide":        {"label": "Vide – attente ordre",   "rgb": [236, 214,  92]},
    "repos":       {"label": "Repos",                  "rgb": [ 95, 121, 130]},
    "garage":      {"label": "Garage / panne",         "rgb": [205,  82,  62]},
    "inconnu":     {"label": "Position inconnue",      "rgb": [135, 148, 160]},
}
ORDRE = ["sur_dech", "sur_charg", "swap", "lavage", "route_dech", "route_charg",
         "route", "vide", "repos", "garage", "inconnu"]

# ─────────────────────────────────────────────────────────────────────────────
# RÉFÉRENTIEL DES SITES
# clé = nom normalisé (minuscule, sans accent, tirets/apostrophes → espace)
# valeur = (libellé propre, pays, lat, lon, alerte éventuelle)
# ─────────────────────────────────────────────────────────────────────────────

GEO = {
    # — Allemagne
    "grunenbach":              ("Grünenbach", "DE", 47.6167,  9.9333, ""),
    "bernkastel":              ("Bernkastel-Kues", "DE", 49.9167, 7.0667, ""),
    "bernkastel kues":         ("Bernkastel-Kues", "DE", 49.9167, 7.0667, ""),
    "langenlonsheim":          ("Langenlonsheim", "DE", 49.9000, 7.9000, ""),
    "monheim":                 ("Monheim am Rhein", "DE", 51.0917, 6.8917,
                                "Homonyme : Monheim am Rhein retenu — vérifier Monheim (Bavière)"),
    "riedlingen":              ("Riedlingen", "DE", 48.1553, 9.4728, ""),
    "stockach":                ("Stockach", "DE", 47.8514, 9.0114, ""),
    "velen":                   ("Velen", "DE", 51.8939, 6.9894, ""),

    # — Autriche
    "woergl":                  ("Wörgl", "AT", 47.4833, 12.0667, ""),
    "worgl":                   ("Wörgl", "AT", 47.4833, 12.0667, ""),

    # — Belgique
    "gent":                    ("Gand", "BE", 51.0543, 3.7174, ""),
    "gand":                    ("Gand", "BE", 51.0543, 3.7174, ""),
    "manage":                  ("Manage", "BE", 50.5000, 4.2333, ""),
    "werbomont":               ("Werbomont", "BE", 50.3667, 5.6500, ""),
    "eupen":                   ("Eupen", "BE", 50.6283, 6.0361, ""),
    "aalter":                  ("Aalter", "BE", 51.0900, 3.4470, ""),
    "bruxelles":               ("Bruxelles", "BE", 50.8503, 4.3517, ""),
    "brussels":                ("Bruxelles", "BE", 50.8503, 4.3517, ""),
    "brussel":                 ("Bruxelles", "BE", 50.8503, 4.3517, ""),

    # — Espagne
    "mollerussa":              ("Mollerussa", "ES", 41.6311, 0.8947, ""),

    # — France
    "reims":                   ("Reims", "FR", 49.2583,  4.0317, ""),
    "sottevast":               ("Sottevast", "FR", 49.5333, -1.6167, ""),
    "clery petit":             ("Cléry-le-Petit", "FR", 49.3667, 5.1667, ""),
    "clery le petit":          ("Cléry-le-Petit", "FR", 49.3667, 5.1667, ""),
    "sarre union":             ("Sarre-Union", "FR", 48.9333, 7.0833, ""),
    "jouy":                    ("Jouy", "FR", 48.5167, 1.5667,
                                "Homonyme : Jouy (28) retenu — vérifier Jouy-en-Josas / Jouy-aux-Arches"),
    "la chapelle d andaine":   ("La Chapelle-d'Andaine", "FR", 48.5500, -0.4333, ""),
    "la chapelle dandaine":    ("La Chapelle-d'Andaine", "FR", 48.5500, -0.4333, ""),
    "belleville":              ("Belleville-sur-Loire", "FR", 47.5117, 2.8500,
                                "Homonyme : Belleville-sur-Loire retenu — vérifier Belleville-sur-Vie / en-Beaujolais"),
    "belleville sur loire":    ("Belleville-sur-Loire", "FR", 47.5117, 2.8500, ""),
    "belleville sur vie":      ("Belleville-sur-Vie", "FR", 46.7833, -1.4333, ""),
    "mayenne":                 ("Mayenne", "FR", 48.3000, -0.6167, ""),
    "nantes":                  ("Nantes", "FR", 47.2184, -1.5536, ""),
    "valence":                 ("Valence", "FR", 44.9333, 4.8917, ""),
    "chevrieres":              ("Chevrières", "FR", 49.3500, 2.6833,
                                "Homonyme : Chevrières (60) retenu — vérifier Chevrières (42)"),
    "rouvroy sur audry":       ("Rouvroy-sur-Audry", "FR", 49.8000, 4.4667, ""),
    "vienne":                  ("Vienne", "FR", 45.5254, 4.8745,
                                "Homonyme : Vienne (38) retenu — vérifier s'il s'agit de Wien (AT)"),
    "baleycourt":              ("Baleycourt", "FR", 49.1500, 5.3167, ""),
    "montauban":               ("Montauban", "FR", 44.0181, 1.3556, ""),
    "moneteau":                ("Monéteau", "FR", 47.8494, 3.5808, ""),
    "sarrebourg":              ("Sarrebourg", "FR", 48.7353, 7.0539, ""),
    "marges":                  ("Marges", "FR", 45.1470, 5.0390, ""),
    "corcieux":                ("Corcieux", "FR", 48.1717, 6.8811, ""),
    "cesson sevigne":          ("Cesson-Sévigné", "FR", 48.1211, -1.6031, ""),
    "chevigny saint sauveur":  ("Chevigny-Saint-Sauveur", "FR", 47.3000, 5.1350, ""),
    "chevigny st sauveur":     ("Chevigny-Saint-Sauveur", "FR", 47.3000, 5.1350, ""),
    "chevigny":                ("Chevigny-Saint-Sauveur", "FR", 47.3000, 5.1350, ""),
    "isigny sur mer":          ("Isigny-sur-Mer", "FR", 49.3183, -1.1022, ""),
    "isigny":                  ("Isigny-sur-Mer", "FR", 49.3183, -1.1022, ""),
    "malestroit":              ("Malestroit", "FR", 47.8097, -2.3831, ""),

    # — Italie
    "faenza":                  ("Faenza", "IT", 44.2853, 11.8833, ""),
    "collecchio":              ("Collecchio", "IT", 44.7528, 10.2167, ""),
    "ovaro":                   ("Ovaro", "IT", 46.4833, 12.8667, ""),

    # — Luxembourg
    "septfontaines":           ("Septfontaines", "LU", 49.7011, 5.9669,
                                "Homonyme : Septfontaines (LU) retenu — vérifier Septfontaines (25, FR)"),

    # — Pays-Bas
    "kampen":                  ("Kampen", "NL", 52.5553, 5.9111, ""),
    "dalfsen":                 ("Dalfsen", "NL", 52.5089, 6.2578, ""),
    "rotterdam":               ("Rotterdam", "NL", 51.9225, 4.4792, ""),
    "zaandam":                 ("Zaandam", "NL", 52.4389, 4.8258, ""),
    "riel":                    ("Riel", "NL", 51.5250, 5.0220,
                                "Homonyme : Riel (NL, Goirle) retenu — vérifier Riel-les-Eaux (FR)"),

    # — Pologne
    "siemiatycze":             ("Siemiatycze", "PL", 52.4272, 22.8625, ""),
}

# ─────────────────────────────────────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────────────────────────────────────

JOURS = {
    "monday": "lundi", "tuesday": "mardi", "wednesday": "mercredi",
    "thursday": "jeudi", "friday": "vendredi", "saturday": "samedi",
    "sunday": "dimanche", "tomorrow": "demain", "today": "aujourd'hui",
}

LINE_RE = re.compile(r"^\s*([A-Z0-9][A-Z0-9 \-]{3,12}?)\s*[–—−-]\s*(.+)$")
PLATE_RE = re.compile(r"^[A-Z0-9]{5,10}$")
HEURE_RE = re.compile(r"(\d{1,2})\s*[:h]\s*(\d{2})")
KM_RE = re.compile(r"(\d{1,4})\s*km", re.I)

SUR_PLACE_RE = re.compile(
    r"\b(is at|are at|just arrived|in process|process of|is waiting to be called|"
    r"is unloading|is loading|is in process)\b")
EN_ROUTE_RE = re.compile(
    r"\b(heading|driving|towards|direction|left to go|will be around|should be there|"
    r"km from|on the way|on his way|is left)\b")

# Déclencheurs d'un nom de lieu : la capture s'arrête à la première ponctuation forte.
# Lookahead → toutes les occurrences sont testées (même imbriquées).
LIEU_RE = re.compile(r"(?=\b(?:in|near|towards|direction of)\s+([^,;:()?!–—]+))", re.I)

# Petits mots autorisés à l'intérieur d'un nom de commune
CONNECTEURS = {
    "sur", "sous", "le", "la", "les", "de", "du", "des", "en", "et", "aux", "lez",
    "am", "an", "der", "im", "bei", "ob", "op", "aan", "den", "di", "del", "della",
    "al", "sint", "sankt", "saint", "sainte", "st", "ste",
}
# Mots en majuscule qui ne sont jamais un lieu
FAUX_LIEUX = {"ETA", "CMR", "The", "Our", "He", "We", "They", "His", "Please"}


def norm(txt: str) -> str:
    """minuscule, sans accent, sans ponctuation, espaces simples."""
    t = unicodedata.normalize("NFKD", str(txt or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("'", " ").replace("’", " ").replace("-", " ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _capture_nom(segment: str):
    """Garde la suite de mots capitalisés (+ connecteurs internes) en début de segment."""
    parts, attente = [], []
    for tok in segment.split():
        clean = tok.strip(".'’\"")
        if not clean:
            break
        fin_phrase = tok.endswith(".") and clean.lower() not in ("st", "ste")
        low = clean.lower()

        est_nom = clean[0].isupper() or (parts and re.match(r"^[dl]['’][A-ZÀ-Ý]", clean))
        if est_nom:
            if clean in FAUX_LIEUX:
                break
            if PLATE_RE.match(clean) and any(c.isdigit() for c in clean):
                break
            parts += attente + [clean]
            attente = []
        elif parts and low in CONNECTEURS:
            attente.append(clean)
        else:
            break
        if fin_phrase:
            break
    return " ".join(parts) or None


def extrait_lieu(txt: str):
    """Nom de commune trouvé dans la ligne, ou None."""
    zone = txt
    # Camion au garage : on ne regarde que la proposition qui parle du garage
    if re.search(r"\bgarage\b", txt, re.I):
        clauses = [c for c in re.split(r"[,;]", txt) if re.search(r"\bgarage\b", c, re.I)]
        zone = clauses[0] if clauses else ""
    for m in LIEU_RE.finditer(zone):
        nom = _capture_nom(m.group(1))
        if nom:
            return nom
    return None


def detecte_statut(txt: str) -> str:
    t = txt.lower()
    a_quai = bool(re.search(r"\b(un)?loading place\b", t))

    if re.search(r"\bgarage\b", t):
        return "garage"
    if "swap" in t or "changing trailer" in t:
        return "swap"
    if "cleaning station" in t or re.search(r"called for cleaning|\bis cleaning\b|being cleaned", t):
        return "lavage"
    if re.search(r"\bempty\b", t):
        return "vide"
    if not a_quai and re.search(r"\bbreak\b|\b(24|45)\s*h\b", t):
        return "repos"

    dech = bool(re.search(r"\bunload|\bdeliver", t))
    charg = bool(re.search(r"\bload(ing|ed)?\b", t)) and not dech
    en_route = bool(EN_ROUTE_RE.search(t))
    sur_place = bool(SUR_PLACE_RE.search(t)) and not en_route

    if dech:
        return "sur_dech" if sur_place else "route_dech"
    if charg:
        return "sur_charg" if (sur_place and "just loaded" not in t) else "route_charg"
    if en_route:
        return "route"
    return "inconnu"


def detecte_alertes(txt: str) -> list:
    t = txt.lower()
    alertes = []
    if re.search(r"technical issue|breakdown|broken|assistance|reparation|repair|"
                 r"loosing|losing|valve|puncture|flat tyre|gearbox", t):
        alertes.append("Incident technique")
    if re.search(r"don.?t have room|no room|will not load|won.?t load|will not unload|"
                 r"refused|not accepted", t):
        alertes.append("Blocage site")
    if "?" in txt or re.search(r"\bplease\b|\bcan you\b|\bcan we\b", t):
        alertes.append("Réponse attendue")
    return alertes


def extrait_eta(txt: str) -> str:
    """ETA lisible : jour + heure, heure contextualisée (fin repos, chauffe), km restants."""
    t = txt.lower()

    heures = []
    for m in HEURE_RE.finditer(t):
        avant = t[max(0, m.start() - 40):m.start()].split(",")[-1]
        h = f"{int(m.group(1)):02d}:{m.group(2)}"
        if "break" in avant:
            h = f"fin repos {h}"
        elif "heat" in avant:
            h = f"chauffe {h}"
        heures.append((m.start(), h))

    jour, pos_jour = None, 10 ** 6
    for en, fr in JOURS.items():
        m = re.search(rf"\b{en}\b", t)
        if m and m.start() < pos_jour:
            jour, pos_jour = fr, m.start()
    km = KM_RE.search(t)

    parts = []
    if heures:
        h = " – ".join(x[1] for x in heures[:2])
        parts.append(f"{jour} {h}" if (jour and pos_jour < heures[0][0]) else h)
    elif "morning" in t:
        parts.append(f"{jour} matin" if jour else "matin")
    elif "evening" in t or "night" in t:
        parts.append(f"{jour} soir" if jour else "soir")
    elif jour:
        parts.append(jour)

    if km:
        parts.append(f"≈ {km.group(1)} km")

    if not parts:
        if re.search(r"in process|process of|\bnow\b", t):
            parts.append("en cours")
        elif "just arrived" in t:
            parts.append("arrivé")
        elif "waiting" in t:
            parts.append("en attente")
        elif SUR_PLACE_RE.search(t):
            parts.append("sur place")

    if heures and re.search(r"(deliver|park)[^.]{0,60}(tomorrow|morning)", t):
        parts.append("livraison demain matin")

    return " · ".join(parts)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def _nominatim(nom: str, settlement: bool):
    """Appel brut Nominatim. Lève une exception en cas d'erreur réseau (non mise en cache)."""
    time.sleep(1.1)  # politique d'usage Nominatim : 1 requête / seconde
    params = {"q": nom, "format": "jsonv2", "limit": 1, "addressdetails": 1,
              "countrycodes": PAYS_WEB}
    if settlement:
        params["featureType"] = "settlement"
    r = requests.get(NOMINATIM, params=params, headers=UA, timeout=8)
    r.raise_for_status()
    return r.json()


def geocode_web(nom: str):
    """Fallback Nominatim pour un lieu absent du référentiel."""
    for settlement in (True, False):
        try:
            data = _nominatim(nom, settlement)
        except Exception:
            return None
        if data:
            d = data[0]
            addr = d.get("address", {}) or {}
            pays = (addr.get("country_code") or "").upper() or "—"
            libelle = (addr.get("city") or addr.get("town") or addr.get("village")
                       or addr.get("municipality") or nom)
            return (libelle, pays, float(d["lat"]), float(d["lon"]),
                    "Géocodage automatique — à vérifier")
    return None


def est_code_site(brut: str) -> bool:
    """BSM, PTK, SNF… : code client, pas une commune."""
    return bool(re.fullmatch(r"[A-Z0-9]{2,5}", (brut or "").replace(" ", "")))


def resout_lieu(brut: str, autoriser_web: bool):
    """(libellé, pays, lat, lon, alerte) ou None."""
    if not brut:
        return None
    cle = norm(brut)
    if cle in GEO:
        return GEO[cle]
    for variante in (cle.replace(" st ", " saint "), cle.replace(" saint ", " st ")):
        if variante in GEO:
            return GEO[variante]
    if est_code_site(brut):
        return None
    if autoriser_web:
        geo = geocode_web(brut)
        if geo:
            return geo
    premier = cle.split()[0] if cle else ""
    if premier in GEO and premier != cle:
        lib, pays, lat, lon, _ = GEO[premier]
        return (lib, pays, lat, lon, f"Correspondance partielle « {brut} » → {lib} — à vérifier")
    return None


def parse_message(texte: str, autoriser_web: bool):
    lignes_ok, lignes_ko = [], []
    for ligne in texte.splitlines():
        if not ligne.strip():
            continue
        m = LINE_RE.match(ligne.strip())
        if not m:
            lignes_ko.append(ligne.strip())
            continue
        plaque = m.group(1).replace(" ", "").replace("-", "").upper()
        reste = m.group(2).strip()
        if not PLATE_RE.match(plaque):
            lignes_ko.append(ligne.strip())
            continue

        statut = detecte_statut(reste)
        brut = extrait_lieu(reste)
        geo = resout_lieu(brut, autoriser_web)
        alertes = detecte_alertes(reste)

        if geo is None:
            ville = brut or ("Garage" if statut == "garage" else "Non précisé")
            pays, lat, lon = "—", None, None
            if brut and est_code_site(brut):
                note = f"Code site « {brut} » — ajouter au référentiel GEO"
            elif brut:
                note = "Lieu non reconnu"
            elif statut == "garage":
                note = ""
            else:
                note = "Aucun lieu dans le message"
        else:
            ville, pays, lat, lon, note = geo

        lignes_ok.append({
            "Tracteur": plaque,
            "Statut": statut,
            "Site": ville,
            "Pays": pays,
            "ETA": extrait_eta(reste),
            "Lat": lat,
            "Lon": lon,
            "Alerte": " · ".join([a for a in [note] + alertes if a]),
            "Message": reste,
        })

    df = pd.DataFrame(lignes_ok)
    if not df.empty:
        df = df.drop_duplicates("Tracteur", keep="last").reset_index(drop=True)
        df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
        df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    return df, lignes_ko


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  .legende span {display:inline-block; margin-right:14px; font-size:13px; color:#6e6e73;}
  .legende i {display:inline-block; width:10px; height:10px; border-radius:50%;
              margin-right:6px;}
</style>
""", unsafe_allow_html=True)

ui.page("carte_chesca", "Collez le message de suivi tel quel, une ligne par tracteur : "
        "« PLAQUE – he will be around 10:15 at the unloading place in Ville, … ».")

col_in, col_opt = st.columns([3, 1])
with col_in:
    texte = st.text_area(
        "Message Chesca", height=220, key="msg",
        placeholder="GL51CHE – he will be around 10:15 at the unloading place in Sarre Union, we will keep you posted.",
    )
with col_opt:
    autoriser_web = st.toggle(
        "Géocodage web", value=True,
        help="Interroge Nominatim (OpenStreetMap) pour les sites absents du référentiel. "
             "1 requête/seconde : le premier passage peut prendre quelques secondes.")
    rayon = st.slider("Taille des points", 4, 20, 9)
    lancer = st.button("Générer la carte", type="primary", use_container_width=True)

if lancer and texte.strip():
    with st.spinner("Lecture du message et géolocalisation…"):
        df_parse, rejets = parse_message(texte, autoriser_web)
    st.session_state["chesca_df"] = df_parse
    st.session_state["chesca_rejets"] = rejets

df = st.session_state.get("chesca_df")
if df is None or df.empty:
    st.info("Aucune donnée. Colle le message et clique sur **Générer la carte**.")
    st.stop()

rejets = st.session_state.get("chesca_rejets", [])
if rejets:
    with st.expander(f"{len(rejets)} ligne(s) non reconnue(s)"):
        for r in rejets:
            st.code(r, language=None)

# ── Filtres ─────────────────────────────────────────────────────────────────
presents = [s for s in ORDRE if s in set(df["Statut"])]
choix = st.multiselect(
    "Statuts affichés",
    options=presents,
    default=presents,
    format_func=lambda s: f"{STATUTS[s]['label']} ({(df['Statut'] == s).sum()})",
)
vue = df[df["Statut"].isin(choix)].copy()

alerte_txt = vue["Alerte"].fillna("")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tracteurs", len(vue))
c2.metric("Sites", vue.dropna(subset=["Lat"])["Site"].nunique())
c3.metric("Sans position", int(vue["Lat"].isna().sum()))
c4.metric("Réponse attendue", int(alerte_txt.str.contains("Réponse attendue").sum()))
c5.metric("Incidents / blocages",
          int(alerte_txt.str.contains("Incident technique|Blocage site").sum()))

# ── Carte ───────────────────────────────────────────────────────────────────
carte = vue.dropna(subset=["Lat", "Lon"]).copy()
if not carte.empty:
    carte["_ordre"] = carte["Statut"].map({s: i for i, s in enumerate(ORDRE)})
    carte = carte.sort_values("_ordre")
    grp = (carte.groupby(["Site", "Pays", "Lat", "Lon"], as_index=False, sort=False)
                .agg(Tracteurs=("Tracteur", lambda x: " · ".join(sorted(x))),
                     Nb=("Tracteur", "size"),
                     Statut=("Statut", "first"),
                     Detail=("ETA", lambda x: " / ".join(v for v in x if v))))
    grp["color"] = grp["Statut"].map(lambda s: STATUTS[s]["rgb"] + [220])
    grp["radius"] = (rayon * 1000) * (1 + 0.35 * (grp["Nb"] - 1))

    points = pdk.Layer(
        "ScatterplotLayer",
        data=grp,
        get_position="[Lon, Lat]",
        get_fill_color="color",
        get_radius="radius",
        radius_min_pixels=6,
        radius_max_pixels=30,
        stroked=True,
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        pickable=True,
    )
    etiquettes = pdk.Layer(
        "TextLayer",
        data=grp,
        get_position="[Lon, Lat]",
        get_text="Site",
        get_size=11,
        get_color=[29, 29, 31],
        get_pixel_offset=[0, -18],
        billboard=True,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[points, etiquettes],
        initial_view_state=pdk.ViewState(
            latitude=float(grp["Lat"].mean()),
            longitude=float(grp["Lon"].mean()),
            zoom=4.6, pitch=0,
        ),
        map_style=CARTO_LIGHT,
        tooltip={"html": "<b>{Site}</b> ({Pays})<br/>{Tracteurs}<br/>{Detail}",
                 "style": {"backgroundColor": "#ffffff", "color": "#1d1d1f", "fontSize": "12px",
                           "borderRadius": "10px", "boxShadow": "0 4px 16px rgba(0,0,0,.12)",
                           "fontFamily": "-apple-system, BlinkMacSystemFont, Inter, sans-serif"}},
    ), use_container_width=True)

    legende = " ".join(
        f"<span><i style='background:rgb({','.join(map(str, STATUTS[s]['rgb']))})'></i>"
        f"{STATUTS[s]['label']}</span>" for s in choix
    )
    st.markdown(f"<div class='legende'>{legende}</div>", unsafe_allow_html=True)
else:
    st.warning("Aucun site géolocalisé dans la sélection.")

# ── Tableau éditable ────────────────────────────────────────────────────────
ui.section("Dispatch")
st.caption("Corrige une commune dans le tableau (les coordonnées sont recalculées "
           "si tu ne les touches pas), puis clique sur Appliquer les corrections.")

vue["_ordre"] = vue["Statut"].map({s: i for i, s in enumerate(ORDRE)})
vue = vue.sort_values(["_ordre", "Site", "Tracteur"]).drop(columns="_ordre")

edit = st.data_editor(
    vue[["Tracteur", "Statut", "Site", "Pays", "ETA", "Lat", "Lon", "Alerte", "Message"]],
    hide_index=True,
    use_container_width=True,
    height=460,
    disabled=["Tracteur", "Message"],
    column_config={
        "Statut": st.column_config.SelectboxColumn(options=ORDRE, width="medium"),
        "Lat": st.column_config.NumberColumn(format="%.4f"),
        "Lon": st.column_config.NumberColumn(format="%.4f"),
        "Alerte": st.column_config.TextColumn(width="medium"),
        "Message": st.column_config.TextColumn(width="large"),
    },
    key="editeur",
)

if st.button("Appliquer les corrections"):
    base = st.session_state["chesca_df"].set_index("Tracteur")
    for trac, r in edit.set_index("Tracteur").iterrows():
        if trac not in base.index:
            continue
        ancien = base.loc[trac]
        r = r.copy()
        site_change = norm(r["Site"]) != norm(ancien["Site"])
        coords_idem = ((pd.isna(r["Lat"]) and pd.isna(ancien["Lat"]))
                       or r["Lat"] == ancien["Lat"])
        if site_change and coords_idem:
            geo = resout_lieu(str(r["Site"]), autoriser_web)
            if geo:
                r["Site"], r["Pays"], r["Lat"], r["Lon"], note = geo
                r["Alerte"] = note
            else:
                r["Pays"], r["Lat"], r["Lon"] = "—", None, None
                r["Alerte"] = "Lieu non reconnu"
        for col in r.index:
            base.at[trac, col] = r[col]
    base = base.reset_index()
    base["Lat"] = pd.to_numeric(base["Lat"], errors="coerce")
    base["Lon"] = pd.to_numeric(base["Lon"], errors="coerce")
    st.session_state["chesca_df"] = base
    st.rerun()

# ── Exports ─────────────────────────────────────────────────────────────────
e1, e2 = st.columns(2)
e1.download_button(
    "Export CSV",
    edit.to_csv(index=False, sep=";").encode("utf-8-sig"),
    file_name=f"chesca_{date.today():%Y%m%d}.csv",
    mime="text/csv",
    use_container_width=True,
)

nouveaux = {
    norm(r["Site"]): [r["Site"], r["Pays"], round(float(r["Lat"]), 4),
                      round(float(r["Lon"]), 4), ""]
    for _, r in edit.dropna(subset=["Lat", "Lon"]).iterrows()
    if norm(r["Site"]) not in GEO
}
e2.download_button(
    f"Nouveaux sites ({len(nouveaux)})",
    json.dumps(nouveaux, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="nouveaux_sites.json",
    mime="application/json",
    disabled=not nouveaux,
    use_container_width=True,
    help="À recoller dans le dictionnaire GEO pour éviter un géocodage web la prochaine fois.",
)
