"""
app.py — Transport Hub CB Groupe (point d'entrée Streamlit).

Routeur : déclare toutes les pages et masque la navigation latérale.
On navigue depuis la page d'accueil (accueil.py), qui regroupe les outils.
Lancement : streamlit run transport_hub/app.py
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ui  # noqa: E402

st.set_page_config(page_title="Transport Hub · CB Groupe", page_icon=str(ui.ASSETS / "logo_cb.jpg"),
                   layout="wide", initial_sidebar_state="collapsed")

pages = [st.Page(ui.HOME_FILE, title="Accueil", default=True)]
pages += [st.Page(t["file"], title=t["title"], url_path=t["key"]) for t in ui.TOOLS]
# Les liens (accueil ↔ outils) pointent vers ces objets plutôt que vers des chemins de fichier.
st.session_state["_hub_pages"] = {ui.HOME_FILE: pages[0], **{t["file"]: p for t, p in zip(ui.TOOLS, pages[1:])}}

st.navigation(pages, position="hidden").run()
