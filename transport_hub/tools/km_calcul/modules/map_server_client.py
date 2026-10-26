# map_server_client.py — liens « Voir carte » vers le serveur Cartes-bot- (Render)

import math
import os
import threading
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

# Même adresse par défaut que la page Carte manuelle
MAP_SERVER_URL = os.environ.get("MAP_SERVER_URL", "https://cartes-bot.onrender.com").rstrip("/")

MAX_RETRIES = 3
TIMEOUT     = 30

# 1 seule création de carte à la fois (Render gratuit)
_map_semaphore = threading.Semaphore(1)

# État du serveur : None = inconnu, True = répond, False = injoignable (on n'insiste plus)
_etat = {"ok": None}
_etat_lock = threading.Lock()


_reveil = {"thread": None}


def _ensure_server_awake(max_essais: int = 6) -> bool:
    """Réveille le serveur ; mémorise l'échec pour ne pas réattendre à chaque trajet.
    Render gratuit endormi : la 1re requête reste en attente 30 à 60 s le temps du
    démarrage, d'où un délai long par essai (6 × 30 s au plus)."""
    for attempt in range(1, max_essais + 1):
        try:
            r = httpx.get(f"{MAP_SERVER_URL}/health", timeout=30)
            if r.status_code == 200:
                print(f"      ✅ Serveur cartes prêt ({attempt} essai(s))", flush=True)
                with _etat_lock:
                    _etat["ok"] = True
                return True
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError):
            pass
        print(f"      ⏳ Réveil serveur cartes... ({attempt}/{max_essais})", flush=True)
        time.sleep(5)
    print("      ❌ Serveur cartes injoignable : les liens carte seront vides", flush=True)
    with _etat_lock:
        _etat["ok"] = False
    return False


def warm_up_server() -> bool:
    print("\n🔌 Réveil du serveur de cartes...", flush=True)
    return _ensure_server_awake()


def warm_up_async() -> threading.Thread:
    """Réveil en tâche de fond : le calcul des km démarre sans attendre.
    L'état est remis à « inconnu » : un échec d'un calcul précédent ne bloque pas celui-ci."""
    with _etat_lock:
        _etat["ok"] = None
        _etat["erreur"] = ""
    t = threading.Thread(target=_ensure_server_awake, daemon=True)
    t.start()
    _reveil["thread"] = t
    return t


def serveur_disponible():
    return _etat["ok"]


def derniere_erreur() -> str:
    return _etat.get("erreur", "")


def _simplifier(points: list, tol_m: float = 2.0) -> list:
    """Douglas-Peucker (tolérance en mètres) : un tracé de 18 000 points passe à
    quelques centaines, la carte est identique à l'œil et l'envoi bien plus léger."""
    n = len(points)
    if n < 3:
        return points
    lat0 = math.radians(sum(p[0] for p in points[:: max(1, n // 50)]) / len(points[:: max(1, n // 50)]))
    kx, ky = 111_320 * math.cos(lat0), 110_540
    xy = [(p[1] * kx, p[0] * ky) for p in points]
    garder = [False] * n
    garder[0] = garder[-1] = True
    pile = [(0, n - 1)]
    while pile:
        a, b = pile.pop()
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        dmax, imax = 0.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if l2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol_m and imax > 0:
            garder[imax] = True
            pile.append((a, imax))
            pile.append((imax, b))
    return [[round(points[i][0], 5), round(points[i][1], 5)] for i in range(n) if garder[i]]


def create_route_url(
    origin_name: str,
    dest_name:   str,
    km:          float,
    duration_h:  float,
    polyline:    list,
    prix_peage:  float = 0.0,
) -> str:
    # Réveil en cours : on attend sa fin plutôt que de conclure trop tôt que le serveur est absent
    t = _reveil["thread"]
    if _etat["ok"] is None and t is not None and t.is_alive():
        t.join(timeout=200)
    if _etat["ok"] is False:
        return ""
    payload = {
        "origin":      origin_name,
        "dest":        dest_name,
        "distance_km": km,
        "duration_h":  duration_h,
        "polyline":    _simplifier(polyline or []),
        "prix_peage":  prix_peage,
    }

    with _map_semaphore:
        if _etat["ok"] is False:
            return ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = httpx.post(f"{MAP_SERVER_URL}/api/create_route", json=payload, timeout=TIMEOUT)
                r.raise_for_status()
                with _etat_lock:
                    _etat["ok"] = True
                return r.json().get("url", "")
            except (httpx.TimeoutException, httpx.ConnectError):
                print(f"      ⏳ Serveur cartes lent ou endormi ({attempt}/{MAX_RETRIES})", flush=True)
                if not _ensure_server_awake(max_essais=3):
                    return ""
            except httpx.HTTPStatusError as e:
                print(f"      ⚠️ Serveur cartes HTTP {e.response.status_code} : {e.response.text[:200]}", flush=True)
                with _etat_lock:
                    _etat["erreur"] = f"HTTP {e.response.status_code}"
                return ""
            except Exception as e:
                print(f"      ⚠️ Serveur cartes : {e}", flush=True)
                return ""
        return ""
