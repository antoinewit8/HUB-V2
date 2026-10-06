# outils/cache.py — gestion des caches de calcul KM et de la base Firebase du serveur carte
import json
import os
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

from core import ui

load_dotenv()
FIREBASE_URL = os.environ.get("FIREBASE_URL", "").rstrip("/")

KM_DIR = Path(__file__).resolve().parent.parent / "tools" / "km_calcul"
CACHES = {
    "Trajets": KM_DIR / "cache_trajets.json",
    "Géocodage (calcul KM)": KM_DIR / "cache_geocode.json",
    "Géocodage (routes préférentielles)": KM_DIR / "cache_geocodage.json",
}


def afficher_taille(path: Path) -> str:
    if not path.exists():
        return "absent"
    taille = f"{path.stat().st_size / 1024:.1f} Ko"
    try:
        contenu = path.read_text(encoding="utf-8").strip()
        if not contenu:
            return f"vide ({taille})"
        data = json.loads(contenu)
        nb = len(data) if isinstance(data, (dict, list)) else "?"
        return f"{nb} entrées ({taille})"
    except json.JSONDecodeError:
        return f"corrompu ({taille})"


def vider_cache(path: Path) -> bool:
    if path.exists():
        path.write_text("{}", encoding="utf-8")
        return True
    return False


ui.page("cache", "Vider les caches de calcul KM du hub et la base des routes du serveur carte.")

# ── Caches locaux ─────────────────────────────────────────────────────────────
ui.section("Caches locaux")
for nom, path in CACHES.items():
    col1, col2 = st.columns([3, 1], vertical_alignment="center")
    col1.metric(label=nom, value=afficher_taille(path))
    if col2.button("Vider", key=f"clear_{nom}", use_container_width=True):
        vider_cache(path)
        st.success(f"Cache « {nom} » vidé.")
        st.rerun()

st.write("")
if st.button("Vider tous les caches locaux", type="primary"):
    for path in CACHES.values():
        vider_cache(path)
    st.success("Tous les caches ont été vidés.")
    st.rerun()

# ── Firebase ──────────────────────────────────────────────────────────────────
ui.section("Firebase Realtime Database")

if not FIREBASE_URL:
    st.warning("FIREBASE_URL non configurée dans les secrets.")
else:
    st.caption(f"Base : `{FIREBASE_URL}`")

    col_fb1, col_fb2 = st.columns(2)

    with col_fb2:
        if st.button("Vérifier Firebase"):
            try:
                r = httpx.get(
                    f"{FIREBASE_URL}/routes.json?shallow=true",
                    timeout=15
                )
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        nb = len(data)
                        st.success(f"{nb} route(s) en base")
                        st.json(data)
                    else:
                        st.info("Base vide — aucune route.")
                else:
                    st.error(f"Statut: `{r.status_code}`\nRéponse: {r.text[:300]}")
            except Exception as e:
                st.error(f"{e}")

    with col_fb1:
        if st.button("Vider toutes les routes Firebase", type="primary"):
            try:
                # 1. Shallow listing pour récupérer toutes les clés
                r = httpx.get(
                    f"{FIREBASE_URL}/routes.json?shallow=true",
                    timeout=15
                )
                if r.status_code != 200:
                    st.error(f"Impossible de lire Firebase : {r.status_code}")
                    st.stop()

                data = r.json()

                if not data:
                    st.info("Firebase déjà vide — rien à supprimer.")
                else:
                    keys = list(data.keys())
                    st.info(f"Suppression de {len(keys)} route(s) en cours...")
                    progress = st.progress(0)
                    errors = []

                    # 2. Suppression clé par clé
                    for i, key in enumerate(keys):
                        try:
                            resp = httpx.delete(
                                f"{FIREBASE_URL}/routes/{key}.json",
                                timeout=10
                            )
                            if resp.status_code not in (200, 204):
                                errors.append(f"{key}: {resp.status_code}")
                        except Exception as e:
                            errors.append(f"{key}: {e}")
                        progress.progress((i + 1) / len(keys))

                    if errors:
                        st.warning(f"{len(errors)} erreur(s) : {errors[:5]}")
                    else:
                        st.success(f"{len(keys)} route(s) supprimée(s) avec succès !")

            except Exception as e:
                st.error(f"Erreur : {e}")
            st.rerun()
