"""
core/ptv.py — accès partagé au géocodage et aux km PTV pour les pages du hub.

Remplace le chargeur « paquet modules simulé » copié dans Trajets vides CIT et
Aide planning. Tout passe par tools/km_calcul/modules :
  • localiser(pays, cp, lieu) : table CP embarquée d'abord, PTV si le lieu est
    inconnu (même logique que Calcul KM) ;
  • km_ptv(a, b)             : distance routière PL entre deux points, en cache.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading

KM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "km_calcul"))

_cache_km: dict = {}
_cache_geo: dict = {}
_verrou = threading.Lock()


def routeur():
    """Module tools/km_calcul/modules/ptv_router_km (importé une fois)."""
    if KM_DIR not in sys.path:
        sys.path.insert(0, KM_DIR)
    return importlib.import_module("modules.ptv_router_km")


def erreur_chargement() -> str:
    try:
        routeur()
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def cle_presente() -> bool:
    try:
        k = routeur().PTV_API_KEY
    except Exception:
        return False
    return bool(k) and k != "METS_TA_CLE_ICI"


def geo():
    """Module geo_offline (table CP)."""
    return routeur().geo_module()


def localiser(pays, cp, lieu) -> dict | None:
    """(pays, CP, localité) → {lat, lon, niveau, note, source} ou None. Résultats gardés en mémoire."""
    cle = (str(pays or "").strip().upper(), str(cp or "").strip(), str(lieu or "").strip().upper())
    with _verrou:
        if cle in _cache_geo:
            return _cache_geo[cle]
    try:
        r = routeur().geocode_parts(pays, cp, lieu)
    except Exception as e:
        print(f"⚠️ localiser {cle} : {e}", flush=True)
        r = None
    with _verrou:
        _cache_geo[cle] = r
    return r


def km_ptv(a, b) -> float | None:
    """km routiers PL entre a et b (lat, lon) ; None si PTV indisponible ou en erreur."""
    if a is None or b is None or a[0] is None or b[0] is None:
        return None
    k = (round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4))
    with _verrou:
        if k in _cache_km:
            return _cache_km[k]
    if not cle_presente():
        return None
    try:
        r = routeur().calculate_km_route(a[0], a[1], b[0], b[1], calculer_peage=False)
    except Exception as e:
        print(f"⚠️ km_ptv : {e}", flush=True)
        r = None
    km = float(r["km"]) if r and r.get("km") else None
    if km is not None:
        with _verrou:
            _cache_km[k] = km
    return km


def km_ptv_lot(paires, workers: int = 6) -> dict:
    """{(a, b): km} pour une liste de paires, en parallèle."""
    from concurrent.futures import ThreadPoolExecutor
    paires = list(dict.fromkeys(paires))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(zip(paires, ex.map(lambda p: km_ptv(*p), paires)))
