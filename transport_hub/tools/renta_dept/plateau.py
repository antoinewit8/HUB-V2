"""
Accès au moteur de Renta Plateau sans afficher sa page.

renta_plateau.py lance son interface à l'import, sauf si RENTA_PLATEAU_NO_UI=1.
On le charge une seule fois par processus sous un nom de module à part : la page
« Rentabilité plateau » du hub, exécutée par st.navigation, n'est pas concernée.
"""

import importlib.util
import os
import sys
import threading
from pathlib import Path

_NOM = "_hub_renta_plateau_moteur"
_FICHIER = Path(__file__).resolve().parents[2] / "outils" / "renta_plateau.py"
_VERROU = threading.Lock()


def moteur():
    """Module renta_plateau (fonctions charger_plannings, parse_ca, calculer, CONVENTIONS_VIDE…)."""
    if _NOM in sys.modules:
        return sys.modules[_NOM]
    with _VERROU:
        if _NOM in sys.modules:
            return sys.modules[_NOM]
        avant = os.environ.get("RENTA_PLATEAU_NO_UI")
        os.environ["RENTA_PLATEAU_NO_UI"] = "1"
        try:
            spec = importlib.util.spec_from_file_location(_NOM, _FICHIER)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules[_NOM] = mod
        finally:
            if avant is None:
                os.environ.pop("RENTA_PLATEAU_NO_UI", None)
            else:
                os.environ["RENTA_PLATEAU_NO_UI"] = avant
        return mod
