# map_server_client.py
 
import httpx
import time
import os
import threading
from dotenv import load_dotenv
 
load_dotenv()
 
MAP_SERVER_URL = os.environ.get("MAP_SERVER_URL", "http://localhost:8000")
 
MAX_RETRIES  = 5
RETRY_DELAY  = 3
TIMEOUT      = 30
 
# 1 seule requête carte à la fois (Render free tier)
_map_semaphore = threading.Semaphore(1)
 
 
def _ensure_server_awake() -> bool:
    """Tente de réveiller le serveur et attend qu'il soit prêt."""
    for attempt in range(1, 7):
        try:
            r = httpx.get(f"{MAP_SERVER_URL}/health", timeout=10)
            if r.status_code == 200:
                print(f"      ✅ Serveur prêt ({attempt * 10}s)", flush=True)
                return True
        except (httpx.TimeoutException, httpx.ConnectError):
            pass
        print(f"      ⏳ Réveil serveur... ({attempt}/6)", flush=True)
        time.sleep(10)
    print(f"      ❌ Serveur inaccessible après 60s", flush=True)
    return False
 
 
def warm_up_server() -> bool:
    print(f"\n🔌 Réveil du serveur de cartes...", flush=True)
    return _ensure_server_awake()
 
 
def create_route_url(
    origin_name: str,
    dest_name:   str,
    km:          float,
    duration_h:  float,
    polyline:    list,
    prix_peage:  float = 0.0,
) -> str:
    payload = {
        "origin":      origin_name,
        "dest":        dest_name,
        "distance_km": km,
        "duration_h":  duration_h,
        "polyline":    polyline,
        "prix_peage":  prix_peage,
    }
 
    with _map_semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if attempt > 1:
                    print(f"      🔄 Tentative {attempt}/{MAX_RETRIES}...", flush=True)
 
                r = httpx.post(
                    f"{MAP_SERVER_URL}/api/create_route",
                    json=payload,
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                url = r.json().get("url", "")
                print(f"      🌐 {url}", flush=True)
                return url
 
            except (httpx.TimeoutException, httpx.ConnectError):
                print(f"      ⏳ Serveur endormi, réveil en cours... ({attempt}/{MAX_RETRIES})", flush=True)
                awake = _ensure_server_awake()
                if not awake:
                    print("      ❌ Impossible de réveiller le serveur, carte ignorée", flush=True)
                    return ""
                # Serveur réveillé → on retente immédiatement
 
            except httpx.HTTPStatusError as e:
                print(f"      ⚠️ HTTP {e.response.status_code}", flush=True)
                return ""
 
            except Exception as e:
                print(f"      ⚠️ Erreur inattendue : {e}", flush=True)
                return ""
 
        print("      ❌ Carte échouée après toutes les tentatives", flush=True)
        return ""
 
