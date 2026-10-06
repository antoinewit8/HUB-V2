import os
import json
import math
import html
import unicodedata
import re
import requests
from modules.villes_jalons import detecter_villes_jalons

# ==========================================
# CONFIG
# ==========================================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
JSON_PATH  = os.path.join(BASE_DIR, "..", "routes_preferentielles.json")
CACHE_PATH = os.path.join(BASE_DIR, "..", "cache_geocodage.json")

# routes_apprises.json peut se trouver à différents niveaux selon le déploiement
# (Streamlit Cloud, repo, local) → on teste plusieurs emplacements.
ROUTES_APPRISES_NAME = "routes_apprises.json"
def _candidate_apprises_paths() -> list:
    return [
        os.path.join(BASE_DIR, "..", ROUTES_APPRISES_NAME),                  # km_calcul/
        os.path.join(BASE_DIR, "..", "..", ROUTES_APPRISES_NAME),            # tools/
        os.path.join(BASE_DIR, "..", "..", "..", ROUTES_APPRISES_NAME),      # transport_hub/
        os.path.join(BASE_DIR, "..", "..", "..", "..", ROUTES_APPRISES_NAME),# racine repo
        os.path.join(os.getcwd(), ROUTES_APPRISES_NAME),
    ]

PTV_API_KEY = os.environ.get("PTV_API_KEY", "")
PTV_GEO_URL = "https://api.myptv.com/geocoding/v1/locations/by-text"
RAYON_KM    = 50

# ==========================================
# CACHE PERSISTANT
# ==========================================
def charger_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def sauvegarder_cache(cache: dict) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"⚠️ Impossible de sauvegarder le cache : {e}")

_geocache: dict = charger_cache()

# ==========================================
# CHARGEMENT JSON (une seule fois)
# ==========================================
_routes_cache: list | None = None

def _load_json_list(path: str):
    """Charge un fichier JSON attendu comme liste. None si absent, [] si illisible."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ Erreur lecture {path} : {e}")
        return []

def _normalize_route_entry(r: dict):
    if not isinstance(r, dict):
        return None
    origine = r.get("origine") or r.get("origin")   or r.get("depart")  or ""
    dest    = r.get("destination") or r.get("dest") or r.get("arrivee") or ""
    wps     = r.get("waypoints") or r.get("wps")    or []
    if not origine or not dest:
        return None
    # Conserver tous les champs supplémentaires (prohibited_countries, km_reference, etc.)
    entry = {"origine": origine, "destination": dest, "waypoints": wps}
    for k, v in r.items():
        if k not in entry:
            entry[k] = v
    return entry

def charger_routes() -> list:
    global _routes_cache
    if _routes_cache is not None:
        return _routes_cache

    routes: list = []

    # ── 1. routes_apprises.json (PRIORITÉ : corrections explicites de l'utilisateur) ──
    apprises_raw, apprises_path = None, None
    for p in _candidate_apprises_paths():
        abs_p = os.path.abspath(p)
        data = _load_json_list(abs_p)
        if data is not None:
            apprises_raw, apprises_path = data, abs_p
            break
    if apprises_raw is not None:
        n = 0
        for r in apprises_raw:
            norm = _normalize_route_entry(r)
            if norm:
                routes.append(norm)
                n += 1
        print(f"   📚 routes_apprises.json : {n} routes chargées ({apprises_path})")
    else:
        print(f"   ⚠️ routes_apprises.json introuvable. Cherché : "
              f"{[os.path.abspath(p) for p in _candidate_apprises_paths()]}")

    # ── 2. routes_preferentielles.json (fallback) ──
    pref_raw = _load_json_list(os.path.abspath(JSON_PATH))
    if pref_raw is None:
        print(f"⚠️ routes_preferentielles.json introuvable : {os.path.abspath(JSON_PATH)}")
    else:
        n = 0
        for r in pref_raw:
            norm = _normalize_route_entry(r)
            if norm:
                routes.append(norm)
                n += 1
        print(f"   📋 routes_preferentielles.json : {n} routes chargées")

    _routes_cache = routes
    return routes

# ==========================================
# NORMALISATION
# ==========================================
def normalize(text: str) -> str:
    text = html.unescape(text)          # &#39; → ' , &amp; → & , etc.
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"['\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ==========================================
# GÉOCODAGE PTV
# ==========================================
def geocoder_ville(ville: str) -> tuple[float, float] | None:
    ville_clean = ville
    ville_clean = re.sub(r'\bST\b', 'SAINT', ville_clean, flags=re.IGNORECASE)
    ville_clean = re.sub(r'\bSTE\b', 'SAINTE', ville_clean, flags=re.IGNORECASE)

    key = normalize(ville_clean)

    if key in _geocache:
        coords = _geocache[key]
        print(f"      📦 Cache hit '{ville}' → ({coords[0]:.4f}, {coords[1]:.4f})")
        return (coords[0], coords[1])

    if not PTV_API_KEY:
        print("⚠️ PTV_API_KEY manquante")
        return None

    try:
        # ── Parser ville, CP, pays ──
        parts = [p.strip() for p in ville_clean.split(',')]

        if len(parts) >= 2:
            city_name = parts[0]
            cp = parts[1].strip() if parts[1].strip().isdigit() else ""
            pays = parts[-1].strip() if len(parts) >= 3 else ""

            # ── Recherche 1 : ville seule (plus fiable que ville+CP) ──
            params = {"searchText": city_name}

            country_filter = ""
            if pays:
                country_map = {
                    "france": "FR", "belgium": "BE", "germany": "DE",
                    "netherlands": "NL", "luxembourg": "LU", "italy": "IT",
                    "spain": "ES", "switzerland": "CH", "austria": "AT",
                }
                country_filter = country_map.get(pays.lower(), "")
            if country_filter:
                params["countryFilter"] = country_filter
        else:
            city_name = ville_clean
            cp = ""
            params = {"searchText": ville_clean, "countryFilter": "FR"}

        response = requests.get(
            PTV_GEO_URL,
            headers={"apiKey": PTV_API_KEY},
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        locations = data.get("locations", [])

        if not locations:
            print(f"      ⚠️ Aucun résultat géocodage pour '{ville}'")
            return None

        ville_nom_norm = normalize(city_name)
        cp_dept = cp[:2] if cp else ""
        best = None

        # ── 1) Match ville + département (CP) exact, sans rue parasite ──
        if cp_dept:
            for loc in locations:
                addr = loc.get("address", {})
                city_norm = normalize(addr.get("city", ""))
                loc_cp = addr.get("postalCode", "")
                loc_dept = loc_cp[:2] if loc_cp else ""
                street = addr.get("street", "")
                street_norm = normalize(street)

                city_match = (ville_nom_norm in city_norm or city_norm in ville_nom_norm)
                dept_match = (loc_dept == cp_dept)
                not_street = (ville_nom_norm not in street_norm)

                if city_match and dept_match and not_street:
                    best = loc
                    break

        # ── 2) Match ville + département, même avec rue ──
        if not best and cp_dept:
            for loc in locations:
                addr = loc.get("address", {})
                city_norm = normalize(addr.get("city", ""))
                loc_cp = addr.get("postalCode", "")
                loc_dept = loc_cp[:2] if loc_cp else ""

                city_match = (ville_nom_norm in city_norm or city_norm in ville_nom_norm)
                dept_match = (loc_dept == cp_dept)

                if city_match and dept_match:
                    best = loc
                    break

        # ── 3) Match ville seul, sans rue parasite ──
        if not best:
            for loc in locations:
                addr = loc.get("address", {})
                city_norm = normalize(addr.get("city", ""))
                street_norm = normalize(addr.get("street", ""))

                if (ville_nom_norm in city_norm or city_norm in ville_nom_norm):
                    if ville_nom_norm not in street_norm:
                        best = loc
                        break

        # ── 4) Match ville même avec rue ──
        if not best:
            for loc in locations:
                addr = loc.get("address", {})
                city_norm = normalize(addr.get("city", ""))
                if ville_nom_norm in city_norm or city_norm in ville_nom_norm:
                    best = loc
                    break

        # ── 5) Résultat sans rue ──
        if not best:
            for loc in locations:
                if not loc.get("address", {}).get("street"):
                    best = loc
                    break

        # ── 6) Dernier fallback ──
        if not best:
            best = locations[0]
            addr = best.get("address", {})
            print(f"      ⚠️ Fallback: '{ville}' → {addr.get('city', '?')}, "
                  f"CP={addr.get('postalCode', '?')}, rue={addr.get('street', '')}")

        # ── Log résultat choisi ──
        addr = best.get("address", {})
        print(f"      🧪 RAW PTV '{ville}': city={addr.get('city')}, "
              f"CP={addr.get('postalCode')}, street={addr.get('street', '')}"
              f" | {json.dumps(best.get('referencePosition', {}))}")

        ref_pos = best.get("referencePosition", {})
        lat = ref_pos.get("lat") or ref_pos.get("latitude")
        lon = ref_pos.get("lon") or ref_pos.get("longitude")

        if lat is None or lon is None:
            print(f"      ⚠️ Structure inattendue: {ref_pos}")
            return None

        _geocache[key] = [lat, lon]
        sauvegarder_cache(_geocache)
        print(f"      📍 Géocodé '{ville}' → ({lat:.4f}, {lon:.4f})")
        return (lat, lon)

    except requests.RequestException as e:
        print(f"      ⚠️ Erreur géocodage PTV '{ville}' : {e}")
        return None




# ==========================================
# DISTANCE HAVERSINE
# ==========================================
def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat/2)**2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# ==========================================
# FONCTION PRINCIPALE (remplace l'ancienne)
# ==========================================
def _extract_prohibited(route: dict) -> list:
    """Récupère les pays interdits d'une route (tolère plusieurs noms de clés)."""
    raw = (route.get("prohibited_countries")
           or route.get("prohibitedCountries")
           or route.get("avoid_countries")
           or route.get("pays_interdits")
           or [])
    if isinstance(raw, str):
        raw = [c for c in raw.replace(";", ",").split(",")]
    return [str(c).strip().upper() for c in raw if str(c).strip()]

def get_waypoints(origin: str, dest: str, auto_jalons: bool = False) -> dict:
    """Retourne {"waypoints": [...], "prohibited_countries": [...]} pour une route apprise.

    - Match exact (texte) et match par proximité GPS : TOUJOURS appliqués.
    - Détection automatique de villes-jalons : UNIQUEMENT si auto_jalons=True
      (mode SUPER), car elle peut introduire des détours.
    """
    routes = charger_routes()
    norm_origin = normalize(origin)
    norm_dest   = normalize(dest)
    print(f"   🔍 Recherche route apprise : '{origin}' → '{dest}'")

    # ── 1. Match texte exact (routes apprises + préférentielles) — sans géocodage ──
    for route in routes:
        origine_ref = route.get("origine", "")
        dest_ref    = route.get("destination", "")
        if normalize(origine_ref) == norm_origin and normalize(dest_ref) == norm_dest:
            waypoints = route.get("waypoints", [])
            prohibited = _extract_prohibited(route)
            print(f"   ✅ Route apprise (match exact) : {origine_ref} → {dest_ref} "
                  f"({len(waypoints)} waypoints, pays interdits: {prohibited or 'aucun'})")
            return {"waypoints": waypoints, "prohibited_countries": prohibited}

    # ── 2. Match par proximité GPS (50 km) — géocodage seulement maintenant ──
    coords_origin = geocoder_ville(origin)
    coords_dest   = geocoder_ville(dest)
    mots_origin   = set(norm_origin.split())
    mots_dest     = set(norm_dest.split())

    for route in routes:
        origine_ref = route.get("origine", "")
        dest_ref    = route.get("destination", "")
        norm_orig_ref = normalize(origine_ref)
        norm_dest_ref = normalize(dest_ref)

        # Pré-filtre : au moins un mot commun d'un côté
        if not (mots_origin & set(norm_orig_ref.split())) \
           and not (mots_dest & set(norm_dest_ref.split())):
            continue

        match_dep = (norm_orig_ref == norm_origin)
        match_arr = (norm_dest_ref == norm_dest)

        if not match_dep and not coords_origin:
            continue
        if not match_arr and not coords_dest:
            continue

        if not match_dep:
            coords_ref_dep = geocoder_ville(origine_ref)
            if not coords_ref_dep:
                continue
            if haversine(coords_origin[0], coords_origin[1],
                         coords_ref_dep[0], coords_ref_dep[1]) > RAYON_KM:
                continue
            match_dep = True

        if not match_arr:
            coords_ref_arr = geocoder_ville(dest_ref)
            if not coords_ref_arr:
                continue
            if haversine(coords_dest[0], coords_dest[1],
                         coords_ref_arr[0], coords_ref_arr[1]) > RAYON_KM:
                continue
            match_arr = True

        if match_dep and match_arr:
            waypoints = route.get("waypoints", [])
            prohibited = _extract_prohibited(route)
            print(f"   ✅ Route apprise (proximité <{RAYON_KM}km) : {origine_ref} → {dest_ref} "
                  f"({len(waypoints)} waypoints, pays interdits: {prohibited or 'aucun'})")
            return {"waypoints": waypoints, "prohibited_countries": prohibited}

    # ── 3. Détection automatique villes-jalons — UNIQUEMENT en mode SUPER ──
    if auto_jalons and coords_origin and coords_dest:
        print(f"   🔄 Mode SUPER : détection villes-jalons...")
        jalons = detecter_villes_jalons(
            coords_origin[0], coords_origin[1],
            coords_dest[0], coords_dest[1]
        )
        if jalons:
            print(f"   ✅ {len(jalons)} villes-jalons détectées automatiquement")
            return {"waypoints": jalons, "prohibited_countries": []}

    print(f"   📍 Aucune route apprise → PTV choisit le trajet")
    return {"waypoints": [], "prohibited_countries": []}
