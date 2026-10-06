import streamlit as st
import os
import tempfile
import sys
import traceback
import pandas as pd
import time
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import ui

ui.page("calcul_km", "Déposez un fichier Excel : les distances poids lourds sont calculées via PTV, ligne par ligne.")

# === Upload ===
uploaded_file = st.file_uploader("Dépose ton fichier Excel", type=["xlsx"])
calculer_peage = st.checkbox("Calculer les frais de péage", value=False)
super_pref = st.checkbox("Mode SUPER PRÉFÉRENTIEL (évite tunnels/péages)", value=False)

if uploaded_file:
    st.session_state["uploaded_bytes"] = uploaded_file.read()
    uploaded_file.seek(0)

# === Lancement ===
if st.session_state.get("uploaded_bytes") and st.button("Lancer le calcul", type="primary"):
    for key in ["km_result_bytes", "km_result_name", "km_stats"]:
        st.session_state.pop(key, None)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(st.session_state["uploaded_bytes"])
        tmp_path = tmp.name

    # Objet partagé mutable — le thread écrit dedans, Streamlit lit dedans
    shared = {
        "en_cours": True,
        "progress": (0, 1, "Démarrage..."),
        "result": None,
        "error": None,
    }
    st.session_state["shared"] = shared
    st.session_state["tmp_path"] = tmp_path

    def run_in_thread(shared, tmp_path, calculer_peage, super_pref):
        try:
            from tools.km_calcul.run_km import run_calcul_km

            def on_progress(current, total, message):
                shared["progress"] = (current, total, message)

            result = run_calcul_km(
                tmp_path,
                calculer_peage,
                super_pref=super_pref,
                progress_callback=on_progress,
            )
            shared["result"] = result
        except Exception:
            shared["error"] = traceback.format_exc()
        finally:
            shared["en_cours"] = False

    t = threading.Thread(
        target=run_in_thread,
        args=(shared, tmp_path, calculer_peage, super_pref),
        daemon=True,
    )
    t.start()
    st.rerun()

# === Affichage pendant le calcul ===
shared = st.session_state.get("shared")

if shared and shared["en_cours"]:
    current, total, message = shared["progress"]
    pct = current / total if total > 0 else 0

    st.info("Calcul en cours... Ne fermez pas cette page.")
    st.progress(min(pct, 1.0))
    st.markdown(f"**Progression : {current}/{total}** — {message}")

    time.sleep(1)
    st.rerun()

# === Post-traitement quand terminé ===
elif shared and not shared["en_cours"] and (shared["result"] is not None or shared["error"]):
    tmp_path = st.session_state.pop("tmp_path", None)
    st.session_state.pop("shared", None)

    if shared["error"]:
        st.error("Une erreur critique est survenue.")
        st.code(shared["error"])
    elif shared["result"] and shared["result"]["success"]:
        result = shared["result"]
        try:
            with open(result["output_path"], "rb") as f:
                result_bytes = f.read()

            if not result_bytes:
                st.error("Le fichier de sortie est vide ou corrompu.")
            else:
                st.session_state["km_result_bytes"] = result_bytes
                st.session_state["km_result_name"]  = os.path.basename(result["output_path"])
                st.session_state["km_stats"]        = result.get("stats", {})

                if os.path.exists(result["output_path"]):
                    os.unlink(result["output_path"])

                st.rerun()
        except Exception as e:
            st.error(f"Erreur lecture résultat : {e}")
    else:
        result = shared["result"]
        st.error(f"Le calcul a été interrompu : {result.get('error') if result else 'inconnu'}")
        if result:
            st.code(result.get("error", ""))

    if tmp_path and os.path.exists(tmp_path):
        os.unlink(tmp_path)


# === Résultats ===
if "km_result_bytes" in st.session_state:
    data  = st.session_state["km_result_bytes"]
    stats = st.session_state.get("km_stats", {})

    if isinstance(data, bytes) and len(data) > 0:
        st.success("Calcul terminé !")

        if stats:
            st.markdown("### 📊 Résumé")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Trajets OK",   stats.get("trajets_calcules", 0))
            col2.metric("Erreurs",      stats.get("trajets_erreur", 0))
            col3.metric("Total KM",     f"{stats.get('total_km', 0):,.0f} km")
            col4.metric("Total Péage",  f"{stats.get('total_peage', 0):,.2f} €")

            st.markdown(f"**{stats.get('from_cache', 0)}** trajets depuis le cache")

            if stats.get("erreurs_detail"):
                with st.expander("Détail des erreurs"):
                    for err in stats["erreurs_detail"]:
                        st.text(err)

            resultats = stats.get("resultats", [])
            if resultats:
                st.markdown("### 🔍 Aperçu des résultats")
                df = pd.DataFrame(resultats)
                st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.download_button(
            label="Télécharger le fichier KM",
            data=data,
            file_name=st.session_state["km_result_name"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        if st.button("Nouveau calcul"):
            for key in ["km_result_bytes", "km_result_name", "km_stats"]:
                st.session_state.pop(key, None)
            st.rerun()
