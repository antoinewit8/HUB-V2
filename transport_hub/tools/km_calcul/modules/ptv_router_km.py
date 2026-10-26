"""
ptv_router_km.py — Géocodage et calcul d'itinéraire PL via PTV Developer.

Utilisé par Calcul KM, Missions CA KM, Aide planning, Trajets vides CIT et
Cartes itinéraires : les fonctions publiques gardent leurs noms et signatures.

Géocodage (« Ville, CP, Pays ») :
  1. table GeoNames embarquée (geo_offline.py) : CP + localité, hors ligne ;
  2. PTV seulement si le lieu est inconnu ou réduit à une zone CP, avec le CP
     et le filtre pays dans la recherche, et contrôle que le résultat tombe
     dans la bonne zone CP ;
  3. autres formats (adresse avec rue, texte libre) : recherche texte PTV.
`geocode_detail` renvoie aussi le niveau de confiance et une note lisible.
"""

import importlib.util
import json
import os
import re
import sys
import threading
import time

import requests
from dotenv import load_dotenv

from .route_optimizer import get_super_pref_logic

load_dotenv()

PTV_API_KEY = os.environ.get("PTV_API_KEY", "METS_TA_CLE_ICI")
BASE_URL = "https://api.myptv.com/routing/v1"
GEOCODE_URL = "https://api.myptv.com/geocoding/v1"

MAX_RETRIES = 3
RETRY_DELAY = 2
VEHICLE_PROFILE = "EUR_TRAILER_TRUCK"

HEADERS = {"apiKey": PTV_API_KEY}

PAYS_TO_ISO = {
    "france": "FR", "belgium": "BE", "germany": "DE", "netherlands": "NL",
    "luxembourg": "LU", "italy": "IT", "spain": "ES", "portugal": "PT",
    "united kingdom": "GB", "switzerland": "CH", "austria": "AT",
    "poland": "PL", "czech republic": "CZ", "hungary": "HU",
    "romania": "RO", "bulgaria": "BG", "slovakia": "SK", "slovenia": "SI",
    "croatia": "HR", "denmark": "DK", "sweden": "SE", "norway": "NO",
    "finland": "FI", "ireland": "IE", "greece": "GR",
}

GPS_FIXES = {
    "basse indre": (47.2055, -1.6694),
    "indre":       (47.2055, -1.6694),
    "rumbek":      (50.9441,  3.1214),
    "rumbeke":     (50.9441,  3.1214),
}

# ─────────────────────────────────────────────
# HTTP : une session keep-alive (évite une poignée de main TLS par appel)
# ─────────────────────────────────────────────
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        _local.session = s
    return s


def _get(url, params, timeout=15):
    """GET PTV avec nouvel essai uniquement sur 429 / 5xx / coupure réseau.
    Retourne (réponse ou None, message d'erreur)."""
    dernier = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session().get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            dernier = f"réseau : {type(e).__name__}"
            time.sleep(RETRY_DELAY * attempt)
            continue
        if r.status_code == 200:
            return r, ""
        if r.status_code == 429 or r.status_code >= 500:
            dernier = f"PTV {r.status_code}"
            time.sleep(RETRY_DELAY * attempt)
            continue
        return r, _message_ptv(r)
    return None, dernier or "PTV injoignable"


def _message_ptv(r) -> str:
    try:
        j = r.json()
        txt = j.get("description") or j.get("message") or ""
        det = j.get("details") or {}
        if isinstance(det, dict) and det.get("message"):
            txt = f"{txt} ({det['message']})"
        code = j.get("errorCode") or ""
        return f"PTV {r.status_code} {code} {txt}".strip()[:300]
    except Exception:
        return f"PTV {r.status_code} {r.text[:200]}"


# ─────────────────────────────────────────────
# GÉOCODEUR HORS LIGNE (chargé par chemin : marche aussi quand le paquet
# « modules » est simulé par une page)
# ─────────────────────────────────────────────
_GEO_NOM = "km_geo_offline"
_geo_lock = threading.Lock()


def geo_module():
    """Charge geo_offline.py une seule fois par processus (partagé avec routes_preferentielles)."""
    mod = sys.modules.get(_GEO_NOM)
    if mod is not None:
        return mod
    with _geo_lock:
        mod = sys.modules.get(_GEO_NOM)
        if mod is None:
            chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_offline.py")
            spec = importlib.util.spec_from_file_location(_GEO_NOM, chemin)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)                  # enregistré seulement une fois complet
            mod = sys.modules.setdefault(_GEO_NOM, mod)
    return mod


# ─────────────────────────────────────────────
# RÉSOLUTION GPS FIXE
# ─────────────────────────────────────────────

def resolve_gps_fix(address: str):
    address_lower = address.strip().lower()
    if address_lower in GPS_FIXES:
        return GPS_FIXES[address_lower]
    ville = address_lower.split(",")[0].strip()
    if ville in GPS_FIXES:
        return GPS_FIXES[ville]
    return None


def parse_origin(raw):
    if not raw:
        return None
    raw = str(raw).strip()
    parts = raw.split()
    city_guess = parts[-1].lower() if parts else ""
    if city_guess in GPS_FIXES:
        lat, lon = GPS_FIXES[city_guess]
        return {"lat": lat, "lon": lon, "raw": raw}
    return geocode_address(raw)


# ─────────────────────────────────────────────
# GÉOCODAGE PTV
# ─────────────────────────────────────────────

def geocode_by_postal_code(postal_code, country_code):
    r, _ = _get(f"{GEOCODE_URL}/locations/by-postal-code",
                {"postalCode": postal_code, "countryCode": country_code})
    if r is None or r.status_code != 200:
        return None
    for loc in r.json().get("locations", []):
        ref = loc.get("referencePosition", {})
        lat, lon = ref.get("latitude"), ref.get("longitude")
        if lat is not None and lon is not None:
            return (lat, lon)
    return None


def _geocode_by_text(address):
    r, _ = _get(f"{GEOCODE_URL}/locations/by-text", {"searchText": address})
    if r is None or r.status_code != 200:
        return None
    locs = r.json().get("locations") or []
    if locs:
        ref = locs[0]["referencePosition"]
        return (ref["latitude"], ref["longitude"])
    return None


def _ptv_cp_lieu(iso: str, cp: str, lieu: str, pref: str):
    """Recherche PTV « CP localité » filtrée sur le pays ; on garde le premier
    résultat dont le CP est dans la bonne zone. Retourne (lat, lon, note) ou None."""
    texte = " ".join(x for x in (cp, lieu) if x).strip()
    if not texte or not PTV_API_KEY or PTV_API_KEY == "METS_TA_CLE_ICI":
        return None
    params = {"searchText": texte}
    if iso:
        params["countryFilter"] = iso
    r, _ = _get(f"{GEOCODE_URL}/locations/by-text", params)
    if r is None or r.status_code != 200:
        return None
    locs = r.json().get("locations") or []
    for loc in locs:
        addr = loc.get("address", {}) or {}
        cp_loc = re.sub(r"\s", "", str(addr.get("postalCode", "")))
        if pref and not cp_loc.replace("L-", "").startswith(pref.replace("L-", "")):
            continue
        ref = loc.get("referencePosition", {})
        if ref.get("latitude") is None:
            continue
        return ref["latitude"], ref["longitude"], f"PTV : {addr.get('city', '?')} ({cp_loc})"
    return None


# ─────────────────────────────────────────────
# GÉOCODAGE PRINCIPAL
# ─────────────────────────────────────────────

def geocode_detail(address) -> dict | None:
    """Adresse → {lat, lon, niveau, note, source} ; niveau ∈ « sûr », « approché », « à vérifier »."""
    address = str(address or "").strip()
    if not address:
        return None

    m = re.match(r'^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$', address)
    if m:
        return {"lat": float(m.group(1)), "lon": float(m.group(2)), "niveau": "sûr", "note": "", "source": "GPS"}

    fix = resolve_gps_fix(address)
    if fix:
        return {"lat": fix[0], "lon": fix[1], "niveau": "sûr", "note": "point fixé", "source": "fixe"}

    morceaux = None
    try:
        geo = geo_module()
        morceaux = geo.decouper(address)
    except Exception as e:                       # table absente : on reste sur PTV
        print(f"      ⚠️ géocodeur hors ligne indisponible : {e}", flush=True)
        geo = None

    if geo and morceaux:
        return geocode_parts(*morceaux)

    # Autres formats (rue, texte libre)
    coords = _geocode_by_text(address)
    if coords:
        return {"lat": coords[0], "lon": coords[1], "niveau": "approché", "note": "PTV (texte libre)",
                "source": "PTV"}
    return None


def geocode_parts(pays, cp, lieu) -> dict | None:
    """(pays, CP, localité) bruts → {lat, lon, niveau, note, source} : table CP d'abord,
    PTV (CP + localité + filtre pays) si le lieu est inconnu ou réduit à une zone CP."""
    try:
        geo = geo_module()
    except Exception as e:
        print(f"      ⚠️ géocodeur hors ligne indisponible : {e}", flush=True)
        geo = None
    if geo is None:
        txt = ", ".join(str(x) for x in (lieu, cp, pays) if str(x or "").strip())
        c = _geocode_by_text(txt)
        return {"lat": c[0], "lon": c[1], "niveau": "approché", "note": "PTV (texte)", "source": "PTV"} if c else None

    iso = geo.iso_pays(pays)
    r = geo.localiser(iso, cp, lieu) if iso else None
    zone_seule = r is not None and r["note"].startswith("zone ")
    if r and not zone_seule:
        r["source"] = "table CP"
        return r
    # lieu inconnu de la table, ou seulement la zone CP : PTV avec CP + pays
    zone = geo.cp_est_zone(cp, iso)
    cpn = "" if zone else geo.norm_cp(cp, iso)
    pref = (re.sub(r"\D", "", str(cp)).zfill(2)[:2] if zone else cpn[:2]) if str(cp or "").strip() else ""
    p = _ptv_cp_lieu(iso, cpn, geo.norm_lieu(lieu).title() if lieu else "", pref)
    if p:
        note = p[2] + ("" if str(lieu or "").strip() else " (pas de localité)")
        return {"lat": p[0], "lon": p[1], "niveau": "approché" if lieu else "à vérifier", "note": note,
                "source": "PTV"}
    if r:
        r["source"] = "table CP"
        return r
    if not iso and str(lieu or "").strip():
        c = _geocode_by_text(", ".join(str(x) for x in (lieu, cp, pays) if str(x or "").strip()))
        if c:
            return {"lat": c[0], "lon": c[1], "niveau": "à vérifier", "note": f"pays « {pays} » non reconnu : PTV",
                    "source": "PTV"}
    return None


def geocode_address(address):
    """Adresse → (lat, lon) ou None (signature historique)."""
    d = geocode_detail(address)
    return (d["lat"], d["lon"]) if d else None


# ─────────────────────────────────────────────
# CALCUL ROUTE KM
# ─────────────────────────────────────────────

def decode_polyline(encoded: str) -> list:
    coords = []
    index, lat, lon = 0, 0, 0
    while index < len(encoded):
        for is_lon in [False, True]:
            result, shift = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            value = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lon:
                lon += value
            else:
                lat += value
        coords.append([lat / 1e5, lon / 1e5])
    return coords


def _prix_peage(data: dict) -> float:
    """Total péage en EUR. Trajet sans péage : 0 (plus d'erreur sur une liste vide)."""
    costs = (data.get("toll") or {}).get("costs") or {}
    conv = (costs.get("convertedPrice") or {}).get("price")
    if conv is not None:
        return float(conv)
    total = 0.0
    for p in costs.get("prices") or []:
        if isinstance(p, dict) and p.get("price") is not None:
            total += float(p["price"])
    return total


def _waypoints_coords(waypoints):
    """Étapes → [(lat, lon, rayon_m)]. Formats acceptés : (lat, lon), « lat, lon »,
    « lat, lon;r=8000 » (villes-jalons du mode SUPER), ou une adresse à géocoder."""
    out = []
    for wp in waypoints or []:
        if isinstance(wp, (list, tuple)) and len(wp) == 2:
            try:
                out.append((float(wp[0]), float(wp[1]), 5000))
                continue
            except (TypeError, ValueError):
                pass
        if isinstance(wp, str):
            m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*(?:;\s*r(?:adius)?\s*=\s*(\d+))?\s*$", wp)
            if m:
                out.append((float(m.group(1)), float(m.group(2)), int(m.group(3) or 5000)))
                continue
            c = geocode_address(wp)
            if c:
                out.append((c[0], c[1], 5000))
            else:
                print(f"      ⚠️ Étape ignorée : {wp}", flush=True)
    return out


def calculate_km_route(lat_start, lon_start, lat_end, lon_end, waypoints=None, calculer_peage=False,
                       super_pref=False, prohibited_countries=None, erreurs=None):
    """Itinéraire PL PTV. Retourne {km, travel_time_h, violated, polyline, polyline_coords,
    prix_peage} ou None. Si `erreurs` est une liste, la raison d'un échec y est ajoutée."""
    waypoints_coords = []
    avoid = []
    if super_pref:
        sp_wps, sp_avoids = get_super_pref_logic(lat_start, lon_start, lat_end, lon_end)
        waypoints_coords.extend(_waypoints_coords(sp_wps))
        avoid.extend(sp_avoids)
    waypoints_coords.extend(_waypoints_coords(waypoints))

    results_values = ["POLYLINE"]
    if calculer_peage:
        results_values.append("TOLL_COSTS")
    params = [("profile", VEHICLE_PROFILE), ("results", ",".join(results_values))]
    if calculer_peage:
        params.append(("options[currency]", "EUR"))
    if avoid:
        params.append(("options[avoid]", ",".join(sorted(set(avoid)))))
    if prohibited_countries:
        codes = ",".join(sorted({str(c).strip().upper() for c in prohibited_countries if str(c).strip()}))
        if codes:
            params.append(("options[prohibitedCountries]", codes))

    pts = [(lat_start, lon_start, 0)] + waypoints_coords + [(lat_end, lon_end, 0)]
    for i, (la, lo, rayon) in enumerate(pts):
        if 0 < i < len(pts) - 1:
            params.append(("waypoints", f"{la},{lo};radius={rayon}"))   # étape : tolérance (5 km par défaut)
        else:
            params.append(("waypoints", f"{la},{lo}"))

    r, err = _get(f"{BASE_URL}/routes", params, timeout=30)
    if r is None or r.status_code != 200:
        msg = err or "PTV sans réponse"
        print(f"      ❌ Itinéraire : {msg}", flush=True)
        if erreurs is not None:
            erreurs.append(msg)
        return None

    try:
        data = r.json()
        polyline_raw = data.get("polyline")
        polyline_coords = []
        if polyline_raw:
            g = json.loads(polyline_raw) if isinstance(polyline_raw, str) else polyline_raw
            polyline_coords = [[la, lo] for lo, la in g.get("coordinates", [])]
        return {
            "km":              round(data.get("distance", 0) / 1000, 1),
            "travel_time_h":   round(data.get("travelTime", 0) / 3600, 2),
            "violated":        data.get("violated", False),
            "polyline":        polyline_raw,
            "polyline_coords": polyline_coords,
            "prix_peage":      round(_prix_peage(data), 2) if calculer_peage else 0.0,
        }
    except Exception as e:
        msg = f"réponse PTV illisible : {type(e).__name__}: {e}"
        print(f"      ❌ {msg}", flush=True)
        if erreurs is not None:
            erreurs.append(msg)
        return None


# ─────────────────────────────────────────────
# FONCTION PRINCIPALE
# ─────────────────────────────────────────────

def get_route(origin_address, dest_address):
    origin_coords = geocode_address(origin_address)
    if not origin_coords:
        return None
    dest_coords = geocode_address(dest_address)
    if not dest_coords:
        return None
    return calculate_km_route(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])
