import os
import sys
import tempfile
import threading
import time
import traceback

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import ui

ui.page("calcul_km", "Déposez un fichier Excel : les distances poids lourds sont calculées via PTV, ligne par ligne.")

# Après une mise à jour du dépôt, Streamlit relit la page mais garde en mémoire les
# modules déjà importés (run_km, modules.*) : on les recharge si la version ne suit pas.
VERSION_MOTEUR = 3


def _moteur():
    import importlib
    nom = "tools.km_calcul.run_km"
    mod = sys.modules.get(nom)
    if mod is not None and getattr(mod, "VERSION", 0) >= VERSION_MOTEUR:
        return mod
    for k in [k for k in sys.modules if k == nom or k == "modules" or k.startswith("modules.")
              or k == "km_geo_offline"]:
        del sys.modules[k]
    return importlib.import_module(nom)


# Clés de session propres à la page (les autres outils partagent le même session_state)
K_BYTES, K_NOM, K_JOB = "km_upload_bytes", "km_upload_nom", "km_job"
K_RES, K_RES_NOM, K_STATS = "km_result_bytes", "km_result_name", "km_stats"

# === Fichier et options ===
uploaded_file = st.file_uploader("Fichier Excel (pays, CP et ville de départ et d'arrivée)", type=["xlsx"],
                                 key="km_uploader")
c1, c2, c3 = st.columns(3)
calculer_peage = c1.checkbox("Calculer les frais de péage", value=False)
super_pref = c2.checkbox("Mode SUPER PRÉFÉRENTIEL (évite les péages + villes-jalons)", value=False,
                         help="PTV évite les routes à péage et des villes-jalons orientent le tracé sur les axes PL habituels.")
avec_cartes = c3.checkbox("Lien carte par trajet", value=True,
                          help="Crée un lien « Voir carte » par trajet sur le serveur cartes. Décocher accélère les gros fichiers.")

if uploaded_file is not None:
    st.session_state[K_BYTES] = uploaded_file.getvalue()
    st.session_state[K_NOM] = uploaded_file.name
else:
    # fichier retiré de la zone de dépôt : on ne relance pas l'ancien
    st.session_state.pop(K_BYTES, None)
    st.session_state.pop(K_NOM, None)

job = st.session_state.get(K_JOB)

# === Lancement ===
if st.session_state.get(K_BYTES) and not (job and job["en_cours"]) and st.button("Lancer le calcul", type="primary"):
    for key in (K_RES, K_RES_NOM, K_STATS):
        st.session_state.pop(key, None)

    nom = os.path.splitext(os.path.basename(st.session_state.get(K_NOM) or "fichier"))[0]
    dossier = tempfile.mkdtemp(prefix="km_")
    tmp_path = os.path.join(dossier, f"{nom}.xlsx")
    with open(tmp_path, "wb") as f:
        f.write(st.session_state[K_BYTES])

    job = {"en_cours": True, "progress": (0, 1, "Démarrage..."), "result": None, "error": None,
           "tmp_path": tmp_path, "debut": time.time()}
    st.session_state[K_JOB] = job

    moteur = _moteur()                      # chargé ici (fil principal), pas dans le fil de calcul

    def run_in_thread(job, tmp_path, calculer_peage, super_pref, avec_cartes):
        try:
            run_calcul_km = moteur.run_calcul_km

            def on_progress(current, total, message):
                job["progress"] = (current, total, message)

            job["result"] = run_calcul_km(tmp_path, calculer_peage, super_pref=super_pref,
                                          progress_callback=on_progress, avec_cartes=avec_cartes)
        except Exception:
            job["error"] = traceback.format_exc()
        finally:
            job["en_cours"] = False

    threading.Thread(target=run_in_thread, args=(job, tmp_path, calculer_peage, super_pref, avec_cartes),
                     daemon=True).start()
    st.rerun()


# === Pendant le calcul ===
def _nettoyer(job):
    for p in (job.get("tmp_path"), (job.get("result") or {}).get("output_path")):
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass
    try:
        os.rmdir(os.path.dirname(job.get("tmp_path") or ""))
    except OSError:
        pass


if job and job["en_cours"]:
    current, total, message = job["progress"]
    pct = current / total if total > 0 else 0
    st.info("Calcul en cours. Vous pouvez changer d'outil et revenir : le calcul continue.")
    st.progress(min(pct, 1.0), text=f"{current}/{total} — {message}")
    st.caption(f"Écoulé : {time.time() - job['debut']:.0f} s")
    time.sleep(1)
    st.rerun()

elif job and not job["en_cours"]:
    st.session_state.pop(K_JOB, None)
    result = job.get("result") or {}
    if job.get("error"):
        st.error("Une erreur inattendue a arrêté le calcul.")
        st.code(job["error"])
    elif result.get("success"):
        try:
            with open(result["output_path"], "rb") as f:
                st.session_state[K_RES] = f.read()
            st.session_state[K_RES_NOM] = os.path.basename(result["output_path"])
            st.session_state[K_STATS] = result.get("stats", {})
            st.session_state[K_STATS]["duree_s"] = time.time() - job["debut"]
        except OSError as e:
            st.error(f"Lecture du fichier résultat impossible : {e}")
    else:
        st.error(f"Calcul interrompu : {(result.get('error') or 'raison inconnue').splitlines()[0]}")
        stats = result.get("stats") or {}
        if stats.get("feuilles"):
            st.session_state[K_STATS] = stats          # pour afficher le détail des feuilles
        if "\n" in (result.get("error") or ""):
            with st.expander("Détail technique"):
                st.code(result["error"])
    _nettoyer(job)


# === Résultats ===
stats = st.session_state.get(K_STATS) or {}

if stats.get("feuilles"):
    lues = [f for f in stats["feuilles"] if f["lue"]]
    ignorees = [f for f in stats["feuilles"] if not f["lue"]]
    with st.expander(f"Feuilles lues : {len(lues)} / {len(stats['feuilles'])}", expanded=bool(ignorees) and not lues):
        for f in stats["feuilles"]:
            if f["lue"]:
                st.markdown(f"**{f['feuille']}** — {f['trajets']} lignes, en-têtes ligne {f['ligne_entetes']}")
                st.caption(" · ".join(f"{k} : {v}" for k, v in f["colonnes"].items()))
            else:
                st.markdown(f"**{f['feuille']}** — ignorée : {f['raison']}")
                if f["colonnes"]:
                    st.caption("Colonnes reconnues : " + " · ".join(f"{k} : {v}" for k, v in f["colonnes"].items()))

if st.session_state.get(K_RES):
    st.success(f"Calcul terminé en {stats.get('duree_s', 0):.0f} s.")

    c = st.columns(5 if stats.get("total_peage") else 4)
    c[0].metric("Trajets OK", stats.get("trajets_calcules", 0) - stats.get("trajets_a_verifier", 0))
    c[1].metric("À vérifier", stats.get("trajets_a_verifier", 0))
    c[2].metric("Erreurs", stats.get("trajets_erreur", 0))
    c[3].metric("Total KM", f"{stats.get('total_km', 0):,.0f} km".replace(",", " "))
    if stats.get("total_peage"):
        c[4].metric("Total péage", f"{stats.get('total_peage', 0):,.2f} €".replace(",", " "))
    n_lignes = len(stats.get("resultats", []))
    st.caption(f"{n_lignes} lignes, {stats.get('trajets_distincts', 0)} trajets distincts, "
               f"{stats.get('appels_ptv', 0)} calculs PTV, {stats.get('from_cache', 0)} lignes depuis le cache.")

    for a in stats.get("avertissements", []):
        st.warning(a)

    st.download_button(
        "Télécharger le fichier KM",
        data=st.session_state[K_RES],
        file_name=st.session_state.get(K_RES_NOM, "resultat_KM.xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    resultats = stats.get("resultats", [])
    if resultats:
        ui.section("Résultats")
        df = pd.DataFrame(resultats)
        choix = st.radio("Afficher", ["Tout", "À vérifier", "Erreurs"], horizontal=True, key="km_filtre",
                         label_visibility="collapsed")
        if choix == "À vérifier":
            df = df[df["Statut"] == "À vérifier"]
        elif choix == "Erreurs":
            df = df[df["Statut"] == "Erreur"]
        if df["Péage (€)"].isna().all():
            df = df.drop(columns=["Péage (€)"])
        if len(df["Feuille"].unique()) == 1:
            df = df.drop(columns=["Feuille"])
        st.dataframe(
            df, width="stretch", hide_index=True,
            column_config={
                "Carte": st.column_config.LinkColumn("Carte", display_text="Voir"),
                "KM": st.column_config.NumberColumn("KM", format="%.1f"),
                "Contrôle": st.column_config.TextColumn("Contrôle", width="large"),
            },
        )

    if st.button("Nouveau calcul"):
        for key in (K_RES, K_RES_NOM, K_STATS):
            st.session_state.pop(key, None)
        st.rerun()
