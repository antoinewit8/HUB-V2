"""
Stations carburant partagées entre les pages Pompes carburant et Carte manuelle :
- « Mes stations » : la liste Excel des stations préférées (assets/pompes_favorites.xlsx,
  ou la liste remplacée depuis la page Pompes carburant dans data/pompes/)
- prix du gazole : flux officiel français (station par station), prix maximum belge
"""

import hashlib
import io
import re
import json
import urllib.parse as uparse
import unicodedata
import urllib.request as ureq
from pathlib import Path

import pandas as pd
import streamlit as st

UA = {"User-Agent": "CB-Transport-Hub/1.0 (pompes carburant)"}

PAYS = {
    "BE": "Belgique", "LU": "Luxembourg", "FR": "France", "NL": "Pays-Bas", "DE": "Allemagne",
    "CH": "Suisse", "AT": "Autriche", "IT": "Italie", "ES": "Espagne", "PT": "Portugal",
    "GB": "Royaume-Uni", "IE": "Irlande", "DK": "Danemark", "SE": "Suède", "NO": "Norvège",
    "PL": "Pologne", "CZ": "Tchéquie", "SK": "Slovaquie", "HU": "Hongrie",
    "LT": "Lituanie", "LV": "Lettonie", "EE": "Estonie",
}

# Serveurs Overpass interrogés par la carte elle-même (depuis le navigateur), l'un après l'autre
EUROPE_BBOX = (-11.0, 35.0, 32.0, 72.0)  # ouest, sud, est, nord (écarte l'outre-mer)
HUB_DIR = Path(__file__).resolve().parents[2]
FAV_ASSET = HUB_DIR / "assets" / "pompes_favorites.xlsx"          # liste versionnée dans le dépôt
FAV_LOCAL = HUB_DIR / "data" / "pompes" / "favorites.xlsx"        # liste remplacée depuis la page
VERSION_LECTURE = 1          # à monter si lire_favorites change : les .json déjà calculés sont alors ignorés


# ─── Utilitaires ─────────────────────────────────────────────────────────────
def norm(text) -> str:
    if text is None:
        return ""
    s = unicodedata.normalize("NFD", str(text).upper().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ─── Mes stations (liste Excel) ──────────────────────────────────────────────
# Noms de colonnes reconnus (normalisés : majuscules, sans accent, « _ » → espace)
FAV_COLS = {
    "la": ["LATITUDE", "LAT", "Y"],
    "lo": ["LONGITUDE", "LON", "LNG", "LONG", "X"],
    "n": ["LIBELLE", "NOM", "NOM STATION", "STATION", "NAME"],
    "a": ["ADRESSE", "ADRESSE 1", "ADDRESS", "RUE"],
    "cp": ["CODE POSTAL", "CP", "ZIP", "POSTCODE"],
    "v": ["VILLE", "LOCALITE", "COMMUNE", "CITY"],
    "p": ["PAYS", "CODE PAYS", "COUNTRY", "ISO"],
    "marque": ["MARQUE", "BRAND", "ENSEIGNE"],
    "reseau": ["NOM GROUPE", "NOM RESEAU", "RESEAU", "GROUPE"],
    "code": ["CODE", "CODE IMPLANTATION", "ID", "REFERENCE"],
}
PAYS_NOMS_NORM = {norm(v): k for k, v in PAYS.items()}


def _num(v):
    try:
        x = float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _joli(s: str) -> str:
    """« RELAIS DEVEZE » → « Relais Deveze » (seulement si tout est en majuscules)."""
    if not s or not s.isupper():
        return s
    mots = s.title().split(" ")
    petits = {"De", "Du", "Des", "La", "Le", "Les", "Et", "En", "Sur", "Sous", "Au", "Aux", "A"}
    mots = [m.lower() if i and m in petits else m for i, m in enumerate(mots)]
    return re.sub(r"\b([DL])'", lambda x: x.group(1).lower() + "'", " ".join(mots))


@st.cache_resource(show_spinner=False)
def _geocodeur():
    from tools.werbomont.engine import Geocodeur
    return Geocodeur()


def _cp_pays(cc: str, cp: str) -> str:
    """Code postal tel que stocké dans GeoNames (FR/DE sur 5 chiffres, LU préfixé « L- »)."""
    cp = re.sub(r"^[A-Z]{1,2}-", "", cp.upper().replace(" ", ""))
    if cc in ("FR", "DE") and cp.isdigit():
        return cp.zfill(5)
    if cc == "LU" and cp.isdigit():
        return f"L-{cp}"
    return cp


def _deviner_pays(cp: str, la, lo) -> str:
    """Pays d'une station sans colonne pays : celui dont le code postal tombe à moins de 40 km du point."""
    try:
        g = _geocodeur()
    except Exception:  # noqa: BLE001
        return "FR"
    meilleur, dmin = "", 40.0
    for cc in ("FR", "BE", "LU", "NL", "DE"):
        pt = g.par_cp.get((cc, _cp_pays(cc, cp)))
        if pt and la is not None:
            d = ((pt[0] - la) * 111) ** 2 + ((pt[1] - lo) * 72) ** 2
            if d ** .5 < dmin:
                meilleur, dmin = cc, d ** .5
    return meilleur or ("FR" if len(re.sub(r"\D", "", cp)) in (4, 5) else "")


def _reseau(texte: str) -> tuple[str, str]:
    """(réseau, enseigne) d'une station de la liste, d'après la marque, le réseau et le nom."""
    t = norm(texte)
    if re.search(r"\bAS ?24\b", t):
        return "as24", "AS24"
    if re.search(r"\bCIRCLE ?K\b", t):
        return "circlek", "Circle K"
    if re.search(r"\bACCES\b|\bACCESS\b", t):
        return "total", "TotalEnergies Access"
    if re.search(r"\bELAN\b", t):
        return "total", "Elan (TotalEnergies)"
    if re.search(r"\bELF", t):
        return "total", "Elf (TotalEnergies)"
    if re.search(r"\bTOTAL", t):
        return "total", "TotalEnergies"
    return "autre", ""


def lire_favorites(contenu: bytes, nom_fichier: str = "") -> tuple[list, list]:
    """Stations de la liste Excel (ou CSV) → (stations, remarques). Les colonnes sont reconnues par leur nom ;
    sans coordonnées, la station est placée d'après son code postal et sa localité (table GeoNames)."""
    if nom_fichier.lower().endswith(".csv"):
        texte = contenu.decode("utf-8-sig", "replace")
        df = pd.read_csv(io.StringIO(texte), sep=None, engine="python", dtype=str)
    else:
        df = pd.read_excel(io.BytesIO(contenu), dtype=str)
    entetes = {norm(str(c).replace("_", " ")): c for c in df.columns}
    col = {k: next((entetes[a] for a in alias if a in entetes), None) for k, alias in FAV_COLS.items()}
    remarques = []
    if not col["n"] and not col["a"]:
        raise ValueError("colonnes introuvables : il faut au moins un nom (LIBELLE / NOM) ou une adresse")
    if not (col["la"] and col["lo"]) and not (col["cp"] or col["v"]):
        raise ValueError("ni coordonnées (LATITUDE / LONGITUDE) ni code postal / ville pour placer les stations")

    out, places, perdues = [], 0, []
    w, s_, e, n_ = EUROPE_BBOX
    for i, r in enumerate(df.to_dict("records")):
        g = lambda k: _txt(r.get(col[k])) if col[k] else ""  # noqa: E731
        nom, cp, ville = g("n"), g("cp"), g("v")
        la, lo = _num(g("la")), _num(g("lo"))
        if la is not None and lo is not None and not (s_ <= la <= n_ and w <= lo <= e) and (s_ <= lo <= n_ and w <= la <= e):
            la, lo = lo, la                       # colonnes inversées
        pays_txt = g("p")
        cc = pays_txt.upper() if len(pays_txt) == 2 and pays_txt.upper() in PAYS else PAYS_NOMS_NORM.get(norm(pays_txt), "")
        if la is None or lo is None or not (s_ <= la <= n_ and w <= lo <= e):
            cc = cc or "FR"
            try:
                la, lo, _prec = _geocodeur()(cc, _cp_pays(cc, cp), norm(ville))
            except Exception:  # noqa: BLE001
                la = lo = None
            if la is None:
                perdues.append(nom or f"ligne {i + 2}")
                continue
            places += 1
        if not cc:
            cc = _deviner_pays(cp, la, lo)
        if cc in ("FR", "DE") and cp.isdigit():
            cp = cp.zfill(5)
        r_, ens = _reseau(" ".join([g("marque"), g("reseau"), nom]))
        groupe = g("reseau")
        trucks = "TRUCK" in norm(groupe) or r_ == "as24"
        code = g("code")
        out.append({
            "r": r_, "e": ens or g("marque").title() or "Autre réseau",
            "n": _joli(nom) or _joli(ville) or "Station", "a": _joli(g("a")), "cp": cp, "v": _joli(ville), "p": cc,
            "la": round(float(la), 6), "lo": round(float(lo), 6),
            "pl": 1 if trucks else None,
            "pln": (re.sub(r"\s*(\d{4}|\().*$", "", groupe).strip() or groupe) if trucks else "",
            "ad": None, "lng": None, "cng": None, "h": "", "t": "", "w": "",
            "id": "", "code": code, "grp": groupe, "src": "favori", "fav": 1,
        })
    if places:
        remarques.append(f"{places} station(s) sans coordonnées placée(s) d’après le code postal et la localité.")
    if perdues:
        remarques.append(f"{len(perdues)} station(s) impossibles à placer : " + ", ".join(perdues[:8])
                         + ("…" if len(perdues) > 8 else ""))
    return out, remarques


def fichier_favorites() -> Path | None:
    """La liste remplacée depuis la page si elle existe, sinon celle du dépôt."""
    for p in (FAV_LOCAL, FAV_ASSET):
        if p.exists():
            return p
    return None


FAV_PRET = FAV_ASSET.with_suffix(".json")        # liste du dépôt déjà lue (voir favorites_depuis)


@st.cache_data(show_spinner=False)
def favorites_depuis(path: str, mtime: float) -> tuple[list, list]:
    """Stations de la liste. Lire l'Excel demande la table GeoNames pour deviner le pays (5 à 8 s au premier
    appel) : le résultat est gardé dans un .json à côté du fichier, réutilisé tant que l'Excel ne change pas
    (empreinte SHA-1). Le .json de la liste du dépôt est versionné."""
    contenu = Path(path).read_bytes()
    empreinte = hashlib.sha1(contenu).hexdigest()
    pret = Path(path).with_suffix(".json")
    try:
        d = json.loads(pret.read_text(encoding="utf-8"))
        if d.get("sha1") == empreinte and d.get("version") == VERSION_LECTURE:
            return d["stations"], d["remarques"]
    except (OSError, ValueError, KeyError):
        pass
    stations, remarques = lire_favorites(contenu, path)
    try:
        pret.write_text(json.dumps({"version": VERSION_LECTURE, "sha1": empreinte, "stations": stations,
                                    "remarques": remarques}, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    except OSError:
        pass
    return stations, remarques


def _get(url: str, headers: dict, timeout: int = 60) -> bytes:
    with ureq.urlopen(ureq.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


# ─── Prix affichés ───────────────────────────────────────────────────────────
# France : flux officiel « prix des carburants » (station par station, mis à jour toutes les 10 min).
# Belgique : prix maximum officiel du gasoil routier (SPF Economie), le même que la page Prix gasoil.
FR_PRIX_URLS = [
    "https://donnees.roulez-eco.fr/opendata/instantane",
    "https://donnees.roulez-eco.fr/opendata/instantane_ruptures",
]
FR_PRIX_JSON = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
                "prix-des-carburants-en-france-flux-instantane-v2/exports/json")


def _coord_fr(v):
    """Coordonnées du flux : degrés × 100 000 (parfois déjà en degrés)."""
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x / 100000 if abs(x) > 1000 else x


def _prix(v):
    """'1.689' / '1689' (millièmes, ancien format) → 1.689."""
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if x > 100:
        x /= 1000
    return round(x, 3) if 0.3 < x < 5 else None


def _fr_depuis_xml(contenu: bytes) -> list:
    import zipfile
    import xml.etree.ElementTree as ET
    if contenu[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            contenu = z.read(next(n for n in z.namelist() if n.lower().endswith(".xml")))
    racine = ET.fromstring(contenu)
    out = []
    for pdv in racine.iter("pdv"):
        la, lo = _coord_fr(pdv.get("latitude")), _coord_fr(pdv.get("longitude"))
        if la is None or lo is None:
            continue
        gazole = next((p for p in pdv.iter("prix") if (p.get("nom") or "").lower() == "gazole"), None)
        services = [(sv.text or "").strip() for sv in pdv.iter("service")]
        out.append({
            "id": re.sub(r"\D", "", pdv.get("id") or ""), "la": la, "lo": lo,
            "px": _prix(gazole.get("valeur")) if gazole is not None else None,
            "maj": (gazole.get("maj") or "")[:16] if gazole is not None else "",
            "pl": any("poids lourds" in x.lower() for x in services),
        })
    return out


def _fr_depuis_json(contenu: bytes) -> list:
    out = []
    for r in json.loads(contenu.decode("utf-8")):
        r = {k.lower(): v for k, v in r.items()}
        geom = r.get("geom") or {}
        la = _coord_fr(r.get("latitude")) if r.get("latitude") is not None else geom.get("lat")
        lo = _coord_fr(r.get("longitude")) if r.get("longitude") is not None else geom.get("lon")
        if la is None or lo is None:
            continue
        services = r.get("services_service") or []
        if isinstance(services, str):
            services = services.split("//")
        out.append({
            "id": re.sub(r"\D", "", str(r.get("id") or "")), "la": float(la), "lo": float(lo),
            "px": _prix(r.get("gazole_prix")), "maj": str(r.get("gazole_maj") or "")[:16].replace("T", " "),
            "pl": any("poids lourds" in str(x).lower() for x in services),
        })
    return out


@st.cache_data(ttl=900, show_spinner=False)
def prix_france() -> list:
    """Toutes les stations du flux officiel français : id, position, prix du gazole, piste poids lourds."""
    erreurs = []
    for url in FR_PRIX_URLS[:1]:
        try:
            pts = _fr_depuis_xml(_get(url, UA, timeout=90))
            if pts:
                return pts
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"roulez-eco : {type(e).__name__} {str(e)[:80]}")
    try:
        pts = _fr_depuis_json(_get(FR_PRIX_JSON, UA, timeout=120))
        if pts:
            return pts
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"data.economie : {type(e).__name__} {str(e)[:80]}")
    raise RuntimeError(" ; ".join(erreurs) or "flux vide")


def lier_prix_france(stations: list, pts: list) -> int:
    """Rattache à chaque station française son prix officiel : par l'identifiant officiel stocké dans
    OpenStreetMap si présent, sinon le point du flux le plus proche à moins de 120 m."""
    par_id = {p["id"]: p for p in pts if p["id"]}
    grille = {}
    for p in pts:
        grille.setdefault((round(p["la"] * 100), round(p["lo"] * 70)), []).append(p)
    n = 0
    for s in stations:
        if s["p"] != "FR":
            continue
        p = par_id.get(s.get("ref_fr") or "")
        if p is None:
            cle, dmin = (round(s["la"] * 100), round(s["lo"] * 70)), 0.12 ** 2
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for q in grille.get((cle[0] + dx, cle[1] + dy), []):
                        d = ((q["la"] - s["la"]) * 111) ** 2 + ((q["lo"] - s["lo"]) * 75) ** 2
                        if d < dmin:
                            p, dmin = q, d
        if p is None:
            continue
        if p["px"] is not None:
            s["px"], s["pxm"], s["pxs"] = p["px"], p["maj"], "station"
            n += 1
        if p["pl"]:
            s["pl"] = 1
            s["plo"] = 1          # piste poids lourds déclarée dans le flux officiel
    return n


@st.cache_data(ttl=3600, show_spinner=False)
def prix_max_belgique():
    """Prix maximum officiel du gasoil routier en Belgique (SPF Economie)."""
    from tools.fuel_scraper import get_tarif_en_vigueur
    t = get_tarif_en_vigueur()
    if "error" in t:
        raise RuntimeError(t["error"])
    px = t["prices"].get("diesel_routier") or t["prices"].get("diesel")
    if not px:
        raise RuntimeError("gasoil absent du tarif")
    return {"px": round(float(px), 3), "label": t.get("label", "")}


# ─── Liste officielle Circle K (API du localisateur de circlek.lu) ──────────
# Ancien réseau TotalEnergies racheté par Couche-Tard (Circle K) en 2024 :
# Allemagne et Pays-Bas vendus entièrement ; Belgique et Luxembourg en coentreprise,
# boutique Circle K mais pompes sous marque TotalEnergies pendant cinq ans.
CK_API = "https://api.circlek.com/eu/ngrp-tardmap-store-locator/api/v4/pois"
CK_PAYS = {"BE", "LU", "NL", "DE"}
CK_POMPE_TOTAL = {"BE", "LU"}
CK_HEADERS = {**UA, "Accept": "application/json", "Origin": "https://www.circlek.lu", "Referer": "https://www.circlek.lu/"}


def _cp_ville(a, b):
    """L'API inverse parfois code postal et localité : on remet chaque valeur à sa place."""
    a, b = (a or "").strip(), (b or "").strip()
    if re.search(r"\d", a) and not re.search(r"\d", b):
        return a, b
    if re.search(r"\d", b) and not re.search(r"\d", a):
        return b, a
    return a, b


@st.cache_data(ttl=86400, show_spinner=False)
def circlek_officiel() -> list:
    """Toutes les stations du localisateur officiel Circle K (BE, LU, NL, DE). Lève une erreur si l'API ne répond pas."""
    q = uparse.urlencode({
        "withDetails": "true", "startLatitude": 50.5, "startLongitude": 6.0, "searchLatitude": 50.5,
        "searchLongitude": 6.0, "maxDistance": 0, "maxPoints": 10000, "filterMode": "API_ITEMS",
        "requireAllFilterItems": "true",
    })
    data = json.loads(_get(f"{CK_API}?{q}", CK_HEADERS).decode("utf-8"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("réponse vide")
    out = []
    for p in data:
        cc = (p.get("country") or "").upper()
        la, lo = p.get("latitude"), p.get("longitude")
        if cc not in CK_PAYS or la is None or lo is None:
            continue
        cp, ville = _cp_ville(p.get("city"), p.get("zip"))
        marque = (p.get("brand") or "").upper()
        fuel = next((h for h in p.get("schedule") or [] if h.get("type") == "openingTimesFuel"), {})
        h24 = bool(fuel.get("isAlwaysOpen"))
        horaires = "" if h24 else "; ".join(f"{k} {fuel[k]}" for k in ("weekdays", "Saturday", "Sunday") if fuel.get(k))
        horaires = horaires.replace("weekdays", "Lu-Ve").replace("Saturday", "Sa").replace("Sunday", "Di")
        total = cc in CK_POMPE_TOTAL
        enseigne_txt = "TotalEnergies (boutique Circle K)" if total else "Circle K (ex-TotalEnergies)"
        if marque == "CKAUTOMAT":
            enseigne_txt += " · automate"
        if marque == "TRUCK":
            enseigne_txt = "Circle K Truck"
        out.append({
            "r": "total" if total and marque != "TRUCK" else "circlek",
            "e": enseigne_txt,
            "n": (p.get("name") or "").title(),
            "a": p.get("add1") or "",
            "cp": cp, "v": ville.title() if ville.isupper() else ville, "p": cc,
            "la": round(float(la), 6), "lo": round(float(lo), 6),
            "pl": 1 if marque == "TRUCK" else None, "ad": None, "lng": None, "cng": None,
            "h": "24/7" if h24 else horaires,
            "t": p.get("phone") or "", "w": "",
            "id": "", "code": str(p.get("code") or ""), "src": "officiel",
        })
    return out


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def circlek_lu_services() -> dict:
    """Services des fiches circlek.lu (Pompe PL, Adblue truck, parking camion), par nom de station normalisé."""
    page = _get("https://www.circlek.lu/fr/stations", UA).decode("utf-8", "replace")
    slugs = sorted(set(re.findall(r'href="/fr/station/([a-z0-9\-]+)"', page)))
    out = {}
    for slug in slugs:
        try:
            html_ = _get(f"https://www.circlek.lu/fr/station/{slug}", UA, timeout=30).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        texte = re.sub(r"<[^>]+>", " ", html_)
        titre = re.search(r"<h1[^>]*>(.*?)</h1>", html_, re.S)
        nom = norm(re.sub(r"<[^>]+>", " ", titre.group(1))) if titre else norm(slug.replace("-", " "))
        out[nom] = {
            "pl": 1 if re.search(r"Pompe PL", texte) else None,
            "ad": 1 if re.search(r"Adblue truck", texte, re.I) else None,
            "parking": bool(re.search(r"Parking camion", texte, re.I)),
            "w": f"https://www.circlek.lu/fr/station/{slug}",
        }
    if not out:
        raise RuntimeError("aucune fiche lue")
    return out
