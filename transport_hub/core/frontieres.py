"""
Frontières terrestres d'Europe (Natural Earth 10 m, allégées à ~250 m entre points),
partagées par les cartes Lavages citernes, Pompes carburant et Détour Werbomont.

Lues depuis assets/frontieres_europe.json (versionné) : plus de téléchargement de
plusieurs Mo sur GitHub au premier affichage après chaque redémarrage du serveur.
"""

import json
from pathlib import Path

import streamlit as st

FICHIER = Path(__file__).resolve().parent.parent / "assets" / "frontieres_europe.json"


@st.cache_resource(show_spinner=False)
def load_borders() -> dict:
    """GeoJSON (une MultiLineString, coordonnées [lon, lat]). Lève une erreur si le fichier manque."""
    return json.loads(FICHIER.read_text(encoding="utf-8"))
