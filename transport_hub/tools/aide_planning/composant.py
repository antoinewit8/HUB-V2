"""Composant Streamlit de la frise (déclaré dans un vrai module : Streamlit l'exige)."""
from pathlib import Path

import streamlit.components.v1 as components

frise = components.declare_component("frise_planning", path=str(Path(__file__).resolve().parent / "frise"))
