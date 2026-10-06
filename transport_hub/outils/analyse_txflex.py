import streamlit as st
import pandas as pd
import io
import os
 
from tools.txflex.analyzer import (
    compute_empty_km,
    compute_total_km,
    detect_friday_anomalies
)
 
from core import ui
 
# ─── Détection vrai format par magic bytes ─────────────
def _is_real_xls(data: bytes) -> bool:
    return data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
 
def read_uploaded_file(file) -> pd.DataFrame:
    name = file.name
    ext  = os.path.splitext(name)[1].lower()
 
    if ext == ".csv":
        return pd.read_csv(file)
 
    data = file.read()
 
    if _is_real_xls(data):
        # Vrai .xls (OLE2) — moteur xlrd
        return pd.read_excel(io.BytesIO(data), engine="xlrd")
    else:
        # Vrai .xlsx (ZIP) — moteur openpyxl
        return pd.read_excel(io.BytesIO(data), engine="openpyxl")
 
# ─── Header ────────────────────────────────────────────
ui.page("txflex", "Analysez vos fichiers TX-FLEX : km à vide, alertes du vendredi et rapport Excel.")
 
uploaded_files = st.file_uploader(
    "Chargez vos fichiers TX-FLEX (Excel ou CSV)",
    type=["csv", "xls", "xlsx"],
    accept_multiple_files=True,
    help="Sélectionnez plusieurs fichiers d'un coup"
)
 
if not uploaded_files:
    st.info("Chargez au moins un fichier pour démarrer l'analyse")
    st.stop()
 
if not st.button("Lancer l'Analyse", type="primary"):
    st.stop()
 
# ─── Traitement ────────────────────────────────────────
resultats_globaux = []
details_trajets   = []
alertes_vendredi  = []
 
progress = st.progress(0, text="Initialisation...")
 
for i, file in enumerate(uploaded_files):
    camion_nom = file.name.split(".")[0].upper()
    progress.progress(
        int((i / len(uploaded_files)) * 100),
        text=f"Analyse de {camion_nom}..."
    )
 
    try:
        df             = read_uploaded_file(file)
        trajets_vides  = compute_empty_km(df)
        total_vide     = sum(t["km_vide"] for t in trajets_vides)
        stats_totales  = compute_total_km(df)
        total_parcouru = stats_totales["total"]
        pct_vide       = (total_vide / total_parcouru * 100) if total_parcouru > 0 else 0
 
        resultats_globaux.append({
            "Camion"              : camion_nom,
            "KM Totaux Parcourus" : total_parcouru,
            "KM Total à Vide"     : total_vide,
            "% à Vide"            : round(pct_vide, 2)
        })
 
        for trajet in trajets_vides:
            trajet["Camion"] = camion_nom
            details_trajets.append(trajet)
 
        for anomalie in detect_friday_anomalies(df):
            if anomalie["alerte"]:
                alertes_vendredi.append({
                    "Camion"      : camion_nom,
                    "Date"        : anomalie["date"],
                    "Heure Fin"   : anomalie["heure_fin"],
                    "KM Totaux"   : anomalie["km_parcourus"],
                    "KM à Vide"   : anomalie["km_vide"],
                    "Nb Activités": anomalie["nb_activites"],
                    "Alerte"      : " + ".join(anomalie["raisons"]),
                    "Villes"      : " -> ".join(anomalie["villes_visitees"])
                })
 
    except Exception as e:
        st.error(f"Erreur sur **{file.name}** : {e}")
 
progress.progress(100, text="Analyse terminée")
 
# ─── DataFrames ────────────────────────────────────────
df_resume    = pd.DataFrame(resultats_globaux)
df_vendredi  = pd.DataFrame(alertes_vendredi)
df_details   = pd.DataFrame(details_trajets)
 
if not df_details.empty:
    df_details = df_details[[
        "Camion", "date_depart", "ville_depart",
        "date_arrivee", "ville_arrivee", "km_vide"
    ]]
 
st.success("Analyse terminée avec succès !")
st.divider()
 
if not df_resume.empty:
    col1, col2, col3 = st.columns(3)
    col1.metric("Camions analysés", len(df_resume))
    col2.metric("KM Totaux",        f"{int(df_resume['KM Totaux Parcourus'].sum()):,}")
    col3.metric("KM à Vide",        f"{int(df_resume['KM Total à Vide'].sum()):,}")
 
st.divider()
 
tab1, tab2, tab3 = st.tabs([
    "Résumé par camion",
    "Alertes Vendredis",
    "Détails KM à Vide"
])
 
with tab1:
    st.dataframe(df_resume, use_container_width=True)
 
with tab2:
    if not df_vendredi.empty:
        st.dataframe(df_vendredi, use_container_width=True)
    else:
        st.info("Aucune anomalie détectée les vendredis")
 
with tab3:
    if not df_details.empty:
        st.dataframe(df_details, use_container_width=True)
    else:
        st.info("Aucun trajet à vide détecté")
 
st.divider()
 
output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    df_resume.to_excel(writer, sheet_name="Résumé", index=False)
    if not df_vendredi.empty:
        df_vendredi.to_excel(writer, sheet_name="Vendredis", index=False)
    if not df_details.empty:
        df_details.to_excel(writer, sheet_name="Détails KM Vide", index=False)
 
st.download_button(
    label     = "Télécharger le rapport Excel",
    data      = output.getvalue(),
    file_name = "Resultats_Flotte_TXFLEX.xlsx",
    mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
