"""
Préchauffage du hub : au premier affichage après un démarrage du serveur, un fil
en tâche de fond charge ce que les cartes demandent à l'ouverture (ma liste de pompes,
prix du gazole France et Belgique, liste officielle Circle K, frontières) et réveille
le serveur carte (Render). Quand on clique sur Carte manuelle ou Pompes carburant,
tout est déjà en cache : la page s'affiche sans attendre les sites extérieurs.

Le prix France (cache de 15 min) est ensuite rafraîchi toutes les 14 min tant que
le serveur tourne, pour qu'une ouverture ne tombe jamais sur un cache expiré.
"""

import os
import threading
import time

import requests
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

MAP_SERVER_URL = os.environ.get("MAP_SERVER_URL", "https://cartes-bot.onrender.com").rstrip("/")
RAFRAICHIR_PRIX_S = 14 * 60


def _essayer(fn, *args):
    try:
        fn(*args)
    except Exception:  # noqa: BLE001  (chaque page gère et affiche ses propres erreurs)
        pass


def _taches():
    from core.frontieres import load_borders
    from tools.pompes import favorites as P

    _essayer(lambda: requests.get(f"{MAP_SERVER_URL}/health", timeout=60))
    _essayer(load_borders)
    src = P.fichier_favorites()
    if src is not None:
        _essayer(P.favorites_depuis, str(src), src.stat().st_mtime)
    for fn in (P.prix_france, P.prix_max_belgique, P.circlek_officiel, P.circlek_lu_services):
        _essayer(fn)


def _boucle(ctx):
    add_script_run_ctx(threading.current_thread(), ctx)
    _taches()
    from tools.pompes import favorites as P
    while True:
        time.sleep(RAFRAICHIR_PRIX_S)
        _essayer(P.prix_france)


@st.cache_resource(show_spinner=False)
def lancer() -> bool:
    """Une seule fois par processus serveur (cache_resource), quel que soit le nombre de visiteurs."""
    threading.Thread(target=_boucle, args=(get_script_run_ctx(),), daemon=True, name="hub-prechauffage").start()
    return True
