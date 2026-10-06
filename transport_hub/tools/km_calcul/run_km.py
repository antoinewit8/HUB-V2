import os
import sys
import json
import threading
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed

KM_DIR = os.path.dirname(os.path.abspath(__file__))

# Locks globaux pour sécuriser les snapshots de cache pendant le multithreading
cache_lock = threading.Lock()
geocode_lock = threading.Lock()


# =============================================================================
# SafeDict — dictionnaire thread-safe avec snapshot profond
# =============================================================================
class SafeDict(dict):
    def __init__(self, *args, **kwargs):
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        with self._lock:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        with self._lock:
            return super().__getitem__(key)

    def __contains__(self, key):
        with self._lock:
            return super().__contains__(key)

    def get(self, key, default=None):
        with self._lock:
            return super().get(key, default)

    def _deep_copy_value(self, v):
        """Copie récursive pure Python sans itérer le dict original pendant l'écriture"""
        if isinstance(v, dict):
            return {k2: self._deep_copy_value(v2) for k2, v2 in list(v.items())}
        elif isinstance(v, list):
            return [self._deep_copy_value(i) for i in list(v)]
        else:
            return v

    def snapshot(self):
        """Retourne une copie profonde complète sous lock — 100% safe"""
        with self._lock:
            return {k: self._deep_copy_value(v) for k, v in list(super().items())}

    def to_json_str(self, indent=4):
        snap = self.snapshot()
        return json.dumps(snap, indent=indent, ensure_ascii=False)


# =============================================================================
# Injection du path
# =============================================================================
def _inject_path():
    if KM_DIR not in sys.path:
        sys.path.insert(0, KM_DIR)


# =============================================================================
# Point d'entrée principal
# =============================================================================
def run_calcul_km(filepath: str, calculer_peage: bool = False, super_pref: bool = False, progress_callback=None) -> dict:
    _inject_path()
    print("DEBUG: DEBUT run_calcul_km")

    stats = {
        "trajets_calcules": 0,
        "trajets_erreur": 0,
        "from_cache": 0,
        "total_km": 0,
        "total_peage": 0,
        "resultats": []
    }

    erreurs_list = []

    try:
        from modules.excel_handler_km import read_all_sheets, write_km_results
        from modules.ptv_router_km import calculate_km_route, geocode_address
        from modules.routes_preferentielles import get_waypoints
        from modules.map_server_client import create_route_url, warm_up_server

        CACHE_FILE = os.path.join(KM_DIR, "cache_trajets.json")
        GEOCODE_CACHE_FILE = os.path.join(KM_DIR, "cache_geocode.json")
        MAX_WORKERS = 2

        # === Cache trajets ===
        def charger_cache():
            if os.path.exists(CACHE_FILE):
                try:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        contenu = f.read().strip()
                        return SafeDict(json.loads(contenu)) if contenu else SafeDict()
                except (json.JSONDecodeError, Exception):
                    return SafeDict()
            return SafeDict()

        def sauvegarder_cache(cache):
            data = {k: v for k, v in cache.items() if isinstance(k, str) and isinstance(v, (str, int, float, dict, list))}
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        # === Cache geocoding ===
        def charger_geocode_cache():
            if os.path.exists(GEOCODE_CACHE_FILE):
                try:
                    with open(GEOCODE_CACHE_FILE, "r", encoding="utf-8") as f:
                        return SafeDict(json.loads(f.read().strip() or "{}"))
                except (json.JSONDecodeError, Exception):
                    return SafeDict()
            return SafeDict()

        def sauvegarder_geocode_cache(gc):
            data = {k: v for k, v in gc.items() if isinstance(k, str) and isinstance(v, (str, int, float, dict, list))}
            with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        # === Geocoding avec cache ===
        def geocode_cached(address, gc):
            print(f"\n--- TEST GEOCODE: {address} ---", flush=True) # DOIT APPARAITRE
            with geocode_lock:
                if address in gc:
                    print(f"Trouvé dans le cache: {gc[address]}", flush=True)
                    return gc[address]
            
            try:
                coords = geocode_address(address)
                print(f"Résultat API pour {address} : {coords}", flush=True)
                if coords:
                    with geocode_lock:
                        gc[address] = coords
                return coords
            except Exception as e:
                print(f"!!! CRASH API GEOCODE pour {address} : {e}", flush=True)
                return None

        # === Warm-up serveur carte ===
        try:
            warm_up_server()
        except Exception:
            pass

        # === Lecture Excel ===
        if progress_callback:
            progress_callback(0, 1, "📂 Lecture du fichier Excel...")

        wb, sheets_data = read_all_sheets(filepath)
        print(f"DEBUG: sheets_data keys = {list(sheets_data.keys())}")

        # === Comptage total ===
        total_global = 0
        for sheet_name, (ws, routes) in sheets_data.items():
            total_global += len(routes)
            print(f"DEBUG: total_global = {total_global}")

        if progress_callback:
            progress_callback(0, total_global, f"📊 {total_global} trajets à calculer...")

        # === Chargement des caches ===
        cache = charger_cache()
        geocode_cache = charger_geocode_cache()

        current_global = 0

        # =================================================================
        # Traitement d'un trajet unique (exécuté dans un thread)
        # =================================================================
        def traiter_trajet(route, cache, geocode_cache):
            origin = route["origin"]
            dest = route["dest"]
            
            # --- DEBUG ---
            print(f"DEBUG GEO: Tentative sur {origin}")
            
            if not origin or not dest:
                return {"row": route["row"], "data": None, "from_cache": False}

            cache_key = f"{origin}|{dest}|peage={calculer_peage}"

            if cache_key in cache:
                return {"row": route["row"], "data": cache[cache_key], "from_cache": True}

            coords_origin = geocode_cached(origin, geocode_cache)
            coords_dest = geocode_cached(dest, geocode_cache)

            # AJOUTE CECI ICI :
            if not coords_origin: print(f"DEBUG: Géocodage échoué pour l'origine: {origin}")
            if not coords_dest: print(f"DEBUG: Géocodage échoué pour la destination: {dest}")

            if not coords_origin or not coords_dest:
                return {"row": route["row"], "data": None, "from_cache": False}

            # Waypoints : routes apprises TOUJOURS appliquées.
            # La détection auto de villes-jalons reste réservée au mode SUPER.
            waypoints = []
            prohibited_countries = []
            try:
                wp_result = get_waypoints(origin, dest, auto_jalons=super_pref)
                waypoints = wp_result.get("waypoints", [])
                prohibited_countries = wp_result.get("prohibited_countries", [])
            except Exception:
                waypoints = []
                prohibited_countries = []

            # Calcul via PTV
            try:
                lat_start, lon_start = coords_origin
                lat_end, lon_end = coords_dest

                data = calculate_km_route(
                    lat_start, lon_start, lat_end, lon_end,
                    calculer_peage=calculer_peage,
                    waypoints=waypoints,
                    prohibited_countries=prohibited_countries
                )
            except Exception as e:
                print(f"!!! CRASH calculate_km_route: {e}", flush=True)
                return {"row": route["row"], "data": None, "from_cache": False}

            if not data:
                return {"row": route["row"], "data": None, "from_cache": False}

            # URL carte
            try:
                data["map_url"] = create_route_url(
                    origin_name = origin,
                    dest_name   = dest,
                    km          = data.get("km", 0),
                    duration_h  = data.get("travel_time_h", 0),
                    polyline    = data.get("polyline_coords", []),
                    prix_peage  = data.get("prix_peage", 0.0),
                )
            except Exception as e:
                print(f"!!! CRASH create_route_url: {e}", flush=True)
                data["map_url"] = ""

            # Stocker en cache
            with cache_lock:
                cache[cache_key] = data

            return {"row": route["row"], "data": data, "from_cache": False}

        # =================================================================
        # Boucle par feuille
        # =================================================================
        print(f"DEBUG SHEETS: {list(sheets_data.keys())}, total={total_global}")
        for sheet_name, (ws, routes) in sheets_data.items():
            if not routes:
                continue

            if progress_callback:
                progress_callback(current_global, total_global, f"📋 Feuille : {sheet_name} ({len(routes)} trajets)")

            results = {}

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_idx = {}
                for idx, route in enumerate(routes):
                    future = executor.submit(traiter_trajet, route, cache, geocode_cache)
                    future_to_idx[future] = idx

                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]

                    try:
                        res = future.result()
                        print(f"DEBUG: idx={idx}, current={current_global}, data={'OK' if res.get('data') else 'NONE'}, cache={res.get('from_cache')}")
                        results[idx] = res

                        if res and res.get("data"):
                            stats["trajets_calcules"] += 1
                            stats["total_km"] += res["data"].get("km", 0) or 0
                            stats["total_peage"] += res["data"].get("prix_peage", 0) or 0
                            if res.get("from_cache"):
                                stats["from_cache"] += 1
                            if len(stats["resultats"]) < 50:
                                stats["resultats"].append({
                                    "Origine": routes[idx]["origin"],
                                    "Destination": routes[idx]["dest"],
                                    "KM": round(res["data"].get("km", 0), 1),
                                    "Durée (h)": round(res["data"].get("travel_time_h", 0), 2),
                                    "Péage (€)": round(res["data"].get("prix_peage", 0) or 0, 2),
                                    "Cache": "✅" if res.get("from_cache") else "❌"
                                })
                        else:
                            stats["trajets_erreur"] += 1
                            erreurs_list.append(f"❌ {routes[idx]['origin']} → {routes[idx]['dest']}: Calcul échoué ou vide")

                    except Exception as e:
                        results[idx] = {"row": routes[idx]["row"], "data": None, "from_cache": False}
                        stats["trajets_erreur"] += 1
                        erreurs_list.append(f"❌ {routes[idx]['origin']} → {routes[idx]['dest']}: {str(e)}")

                    current_global += 1

                    msg = f"📍 {routes[idx]['origin']} → {routes[idx]['dest']}"

                    if current_global % 20 == 0:
                        print(f"--- TENTATIVE SAUVEGARDE CACHE (Trajet {current_global}) ---", flush=True)
                        try:
                            sauvegarder_cache(cache)
                            sauvegarder_geocode_cache(geocode_cache)
                            print("--- SAUVEGARDE REUSSIE ---", flush=True)
                            msg += " 💾 (Cache sauvegardé)"
                        except Exception as e:
                            import traceback
                            print("!!! ERREUR CRITIQUE SAUVEGARDE !!!", flush=True)
                            traceback.print_exc() # <--- CA VA ENFIN DIRE POURQUOI
                            msg += f" ⚠️ Erreur sauvegarde: {e}"

                    if progress_callback:
                        progress_callback(current_global, total_global, msg)

            if progress_callback:
                progress_callback(current_global, total_global, f"💾 Écriture des résultats ({sheet_name})...")
            write_km_results(ws,list(results.values()), calculer_peage)

        stats["erreurs_detail"] = erreurs_list

        # === Sauvegarde finale ===
        sauvegarder_cache(cache)
        sauvegarder_geocode_cache(geocode_cache)

        if progress_callback:
            progress_callback(total_global, total_global, "💾 Sauvegarde du fichier final...")

        output_path = filepath.replace(".xlsx", "_KM.xlsx")
        wb.save(output_path)

        return {"success": True, "output_path": output_path, "error": "", "stats": stats}

    except Exception as e:
        import traceback
        err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        return {"success": False, "output_path": "", "error": err_msg, "stats": stats}
