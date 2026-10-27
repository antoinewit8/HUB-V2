"""
Chargements en parallèle pour les pages Streamlit.

Les données d'une page (prix, listes officielles…) viennent de sources différentes :
on les demande toutes en même temps au lieu de l'une après l'autre. Le contexte
Streamlit est transmis au fil, pour que les fonctions en st.cache_data fonctionnent
normalement (et sans avertissement).
"""

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hub")


def lancer(fn, *args, **kwargs) -> Future:
    ctx = get_script_run_ctx()

    def _run():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        return fn(*args, **kwargs)

    return _POOL.submit(_run)


def attendre(futures, delai: float | None = None) -> bool:
    """True si tous les résultats sont arrivés dans le délai (None = sans limite)."""
    futures = [f for f in futures if f is not None]
    _, en_cours = wait(futures, timeout=delai)
    return not en_cours


def resultat(f: Future | None, defaut=None):
    """Valeur du chargement, ou `defaut` s'il a échoué (l'erreur reste lisible via f.exception())."""
    if f is None or not f.done() or f.exception() is not None:
        return defaut
    return f.result()
