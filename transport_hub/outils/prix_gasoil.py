# outils/prix_gasoil.py
"""
Module Prix Gasoil Belgique — Données officielles SPF Economie
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

from core import ui

ui.page("gasoil", "Données officielles SPF Economie, mises à jour automatiquement.")

st.markdown("""
<style>
.price-card { background: #fff; border-radius: 18px; padding: 20px; text-align: center; box-shadow: var(--ap-shadow);
  transition: transform .18s ease, box-shadow .18s ease; margin-bottom: .6rem; }
.price-card:hover { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(0,0,0,.08), 0 0 0 .5px rgba(0,0,0,.06); }
.price-card .label { color: var(--ap-sub); font-size: 13px; font-weight: 500; }
.price-card .price { color: var(--ap-text); font-size: 34px; font-weight: 600; letter-spacing: -0.02em; margin: .35rem 0; }
.price-card .unit { color: var(--ap-sub); font-size: 13px; }
.price-card .trend-up   { color: #d70015; }
.price-card .trend-down { color: #248a3d; }
.price-card .trend-flat { color: var(--ap-sub); }
.info-box { background: #fff; border-radius: 14px; padding: 12px 16px; color: var(--ap-sub); margin: 1rem 0;
  box-shadow: var(--ap-shadow); font-size: 14px; }
.info-box b, .info-box strong { color: var(--ap-text); }
.stat-row { display: flex; justify-content: space-between; padding: .55rem 0; border-bottom: .5px solid var(--ap-hair);
  font-size: 15px; }
.stat-row .stat-label { color: var(--ap-sub); }
.stat-row .stat-value { color: var(--ap-text); font-weight: 600; }
.source-badge { display: inline-block; background: var(--ap-soft); border-radius: 980px; padding: .35rem 1rem;
  color: var(--ap-sub); font-size: 12px; margin-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# ── Chargement des données ────────────────────────────────────
from tools.fuel_scraper import get_all_prices, get_tarif_en_vigueur
from tools.fuel_avg_scraper import get_monthly_averages, get_daily_prices, get_weekly_prices

with st.spinner("Récupération des prix officiels..."):
    tarif  = get_tarif_en_vigueur()
    df     = get_all_prices()

# ── Affichage tarif en vigueur ────────────────────────────────
if "prices" in tarif and tarif["prices"]:
    st.markdown("""
    <div class="info-box">
        📋 <strong>Tarif en vigueur</strong> — {label}
    </div>
    """.format(label=tarif.get("label", "N/A")), unsafe_allow_html=True)

    cols = st.columns(len(tarif["prices"]))
    for col, (fuel_type, price) in zip(cols, tarif["prices"].items()):
        nice_name = fuel_type.replace("_", " ").title()
        with col:
            st.markdown(f"""
            <div class="price-card">
                <div class="label">{nice_name}</div>
                <div class="price">{price:.4f}</div>
                <div class="unit">€ / litre (TTC)</div>
            </div>
            """, unsafe_allow_html=True)
else:
    st.warning("Impossible de lire le tarif en vigueur. Vérifiez la connexion.")

# ── Historique & Graphiques ───────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)

if not df.empty:
    tab_week, tab_daily, tab_monthly, tab_statbel_daily = st.tabs([
        "Cette semaine", "Historique mensuel", "Moyennes be.STAT", "Journalier Statbel"
    ])

    # ── Onglet Cette semaine ──────────────────────────────────
    with tab_week:
        with st.spinner("Chargement prix hebdomadaires..."):
            df_week = get_weekly_prices()

        if not df_week.empty:
            last = df_week.iloc[-1]
            prev = df_week.iloc[-2] if len(df_week) >= 2 else last
            diff = last["diesel_routier"] - prev["diesel_routier"]

            trend_icon  = "📈" if diff > 0.001 else ("📉" if diff < -0.001 else "➡️")
            trend_class = "trend-up" if diff > 0.001 else ("trend-down" if diff < -0.001 else "trend-flat")

            st.markdown(f"""
            <div class="price-card" style="max-width:340px; margin:1.5rem auto 2rem auto;">
                <div class="label">Diesel Routier — semaine du {last['date'].strftime('%d/%m/%Y')}</div>
                <div class="price">{last['diesel_routier']:.4f} €</div>
                <div class="unit">€ / litre (TTC)</div>
                <div class="{trend_class}" style="margin-top:0.5rem; font-size:1rem;">
                    {trend_icon} {diff:+.4f} vs semaine précédente
                </div>
            </div>""", unsafe_allow_html=True)

            # Graphique 3 derniers mois
            df_3m = df_week[df_week["date"] >= pd.Timestamp.now() - pd.DateOffset(months=3)].copy()
            if not df_3m.empty:
                fig_w = go.Figure()
                fig_w.add_trace(go.Scatter(
                    x=df_3m["date"], y=df_3m["diesel_routier"],
                    mode="lines+markers",
                    line=dict(color="#0071e3", width=2),
                    fill="tozeroy", fillcolor="rgba(0,113,227,0.08)",
                    hovertemplate="%{x|%d/%m/%Y} — %{y:.4f} €/L<extra></extra>",
                ))
                fig_w.add_hline(
                    y=df_3m["diesel_routier"].mean(),
                    line_dash="dash", line_color="rgba(0,0,0,0.25)",
                    annotation_text=f"Moy. 3 mois: {df_3m['diesel_routier'].mean():.4f}€",
                    annotation_font_color="#6e6e73",
                )
                fig_w.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#1d1d1f"),
                    xaxis=dict(gridcolor="rgba(0,0,0,0.06)", title=""),
                    yaxis=dict(gridcolor="rgba(0,0,0,0.06)", title="€/L TTC", tickformat=".4f"),
                    margin=dict(l=60, r=20, t=20, b=40), height=350,
                    hovermode="x unified",
                )
                st.plotly_chart(fig_w, use_container_width=True)

            # Tableau 8 dernières semaines
            with st.expander("8 dernières semaines"):
                df_disp = df_week.tail(8).copy()
                df_disp["date"] = df_disp["date"].dt.strftime("%d/%m/%Y")
                df_disp.columns = ["Semaine", "€/L (TTC)"]
                st.dataframe(df_disp.sort_values("Semaine", ascending=False),
                             use_container_width=True, hide_index=True)
        else:
            st.warning("Prix hebdomadaires non disponibles pour le moment.")
            st.info("Source : GlobalPetrolPrices.com — mise à jour chaque lundi.")

    # ── Onglet Historique mensuel ─────────────────────────────
    with tab_daily:
        # ── Filtre type de carburant ──
        fuel_types = df["type"].unique().tolist()
        selected_fuel = st.selectbox(
            "Type de carburant",
            fuel_types,
            index=fuel_types.index("diesel_routier") if "diesel_routier" in fuel_types else 0
        )

        df_fuel = df[df["type"] == selected_fuel].copy()

        if not df_fuel.empty:
            # ── KPIs ──
            st.markdown("<br>", unsafe_allow_html=True)
            k1, k2, k3, k4 = st.columns(4)

            prix_actuel = df_fuel.iloc[-1]["prix"]
            prix_moyen  = df_fuel["prix"].mean()
            prix_min    = df_fuel["prix"].min()
            prix_max    = df_fuel["prix"].max()

            # Tendance
            if len(df_fuel) >= 2:
                diff = df_fuel.iloc[-1]["prix"] - df_fuel.iloc[-2]["prix"]
                if diff > 0.005:
                    trend_icon, trend_class = "📈", "trend-up"
                    trend_text = f"+{diff:.4f}"
                elif diff < -0.005:
                    trend_icon, trend_class = "📉", "trend-down"
                    trend_text = f"{diff:.4f}"
                else:
                    trend_icon, trend_class = "➡️", "trend-flat"
                    trend_text = "stable"
            else:
                trend_icon, trend_class, trend_text = "➡️", "trend-flat", "N/A"

            with k1:
                st.markdown(f"""
                <div class="price-card">
                    <div class="label">Dernier prix</div>
                    <div class="price">{prix_actuel:.4f}€</div>
                    <div class="{trend_class}">{trend_icon} {trend_text}</div>
                </div>""", unsafe_allow_html=True)

            with k2:
                st.markdown(f"""
                <div class="price-card">
                    <div class="label">Moyenne</div>
                    <div class="price">{prix_moyen:.4f}€</div>
                    <div class="unit">sur {len(df_fuel)} mois</div>
                </div>""", unsafe_allow_html=True)

            with k3:
                st.markdown(f"""
                <div class="price-card">
                    <div class="label">Minimum</div>
                    <div class="price" style="color:#248a3d">{prix_min:.4f}€</div>
                    <div class="unit">/litre</div>
                </div>""", unsafe_allow_html=True)

            with k4:
                st.markdown(f"""
                <div class="price-card">
                    <div class="label">Maximum</div>
                    <div class="price" style="color:#d70015">{prix_max:.4f}€</div>
                    <div class="unit">/litre</div>
                </div>""", unsafe_allow_html=True)

            # ── Graphique évolution ──
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("""
            <div class="info-box">
                📊 <strong>Évolution du prix</strong> — {fuel}
            </div>
            """.format(fuel=selected_fuel.replace("_", " ").title()), unsafe_allow_html=True)

            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=df_fuel["date"],
                y=df_fuel["prix"],
                mode="lines+markers",
                name=selected_fuel.replace("_", " ").title(),
                line=dict(color="#0071e3", width=3),
                marker=dict(size=8, color="#0071e3", line=dict(width=2, color="#FFFFFF")),
                fill="tozeroy",
                fillcolor="rgba(0,113,227,0.1)",
                hovertemplate="<b>%{x|%B %Y}</b><br>Prix: %{y:.4f} €/L<extra></extra>",
            ))

            # Ligne moyenne
            fig.add_hline(
                y=prix_moyen,
                line_dash="dash",
                line_color="rgba(0,0,0,0.25)",
                annotation_text=f"Moyenne: {prix_moyen:.4f}€",
                annotation_font_color="#6e6e73",
            )

            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1d1d1f"),
                xaxis=dict(
                    gridcolor="rgba(0,0,0,0.06)",
                    title="",
                ),
                yaxis=dict(
                    gridcolor="rgba(0,0,0,0.06)",
                    title="€ / litre (TTC)",
                    tickformat=".4f",
                ),
                margin=dict(l=60, r=20, t=20, b=40),
                height=400,
                hovermode="x unified",
            )

            st.plotly_chart(fig, use_container_width=True)

            # ── Tableau détaillé ──
            with st.expander("Données détaillées"):
                df_display = df_fuel[["date", "prix", "source"]].copy()
                df_display["date"] = df_display["date"].dt.strftime("%B %Y")
                df_display.columns = ["Période", "Prix €/L", "Source PDF"]
                st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ── Comparaison tous types ──
    if len(fuel_types) > 1:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("""
        <div class="info-box">
            🔄 <strong>Comparaison tous types de gasoil</strong>
        </div>
        """, unsafe_allow_html=True)

        fig2 = px.line(
            df,
            x="date",
            y="prix",
            color="type",
            markers=True,
            labels={"prix": "€/L (TTC)", "date": "", "type": "Type"},
            color_discrete_sequence=["#0071e3", "#248a3d", "#c93400", "#d70015"],
        )
        fig2.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#1d1d1f"),
            xaxis=dict(gridcolor="rgba(0,0,0,0.06)"),
            yaxis=dict(gridcolor="rgba(0,0,0,0.06)", tickformat=".4f"),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=60, r=20, t=20, b=40),
            height=350,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Analyse sur période personnalisée ──
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("Moyenne des prix (Analyse par période)"):
        today = datetime.now().date()
        start_default = today - timedelta(days=30)
        
        date_range = st.date_input(
            "Choisir une plage de dates",
            value=(start_default, today),
            max_value=today,
            help="Filtrer l'historique pour calculer les moyennes sur une période donnée"
        )

        if isinstance(date_range, tuple) and len(date_range) == 2:
            d_start, d_end = date_range
            # Filtrage sur la période sélectionnée pour le carburant choisi
            df_period = df_fuel[(df_fuel["date"].dt.date >= d_start) & (df_fuel["date"].dt.date <= d_end)].copy()
            
            if not df_period.empty:
                pmoy = df_period["prix"].mean()
                pmin = df_period["prix"].min()
                pmax = df_period["prix"].max()
                n_obs = len(df_period)
                
                st.markdown(f"**Analyse pour :** {selected_fuel.replace('_', ' ').title()}")
                c_k1, c_k2, c_k3, c_k4 = st.columns(4)
                c_k1.metric("Prix moyen", f"{pmoy:.4f} €/L")
                c_k2.metric("Minimum", f"{pmin:.4f} €/L")
                c_k3.metric("Maximum", f"{pmax:.4f} €/L")
                c_k4.metric("Relevés", n_obs)
                
                st.area_chart(df_period.set_index("date")["prix"], color="#0071e3")
            else:
                st.warning(f"Aucune donnée n'existe pour la période du {d_start} au {d_end} ({selected_fuel.replace('_', ' ').title()}).")

    with tab_monthly:
        with st.spinner("Calcul des moyennes mensuelles..."):
            df_avg = get_monthly_averages()
            
        if not df_avg.empty:
            # KPIs pour le Gasoil Routier (le plus pertinent pour CB Groupe)
            avg_glob = df_avg["gasoil_routier"].mean()
            max_row = df_avg.loc[df_avg["gasoil_routier"].idxmax()]
            min_row = df_avg.loc[df_avg["gasoil_routier"].idxmin()]
            
            st.markdown("### 📈 Analyse Long Terme (Routier)")
            mk1, mk2, mk3 = st.columns(3)
            mk1.metric("Moyenne Globale", f"{avg_glob:.4f} €/L")
            mk2.metric("Mois le plus cher", f"{max_row['gasoil_routier']:.4f} €/L", max_row["date"].strftime("%b %Y"), delta_color="inverse")
            mk3.metric("Mois le moins cher", f"{min_row['gasoil_routier']:.4f} €/L", min_row["date"].strftime("%b %Y"))
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Graphique d'évolution
            st.markdown("**Évolution de toutes les catégories be.STAT (€/L)**")
            # Préparation données pour le chart
            chart_data = df_avg.copy()
            chart_data["date"] = chart_data["date"].dt.strftime("%Y-%m")
            
            # On affiche toutes les colonnes sauf 'date'
            st.line_chart(chart_data.set_index("date"))
            
            # Tableau
            with st.expander("Voir le tableau complet des moyennes"):
                df_avg_disp = df_avg.copy()
                df_avg_disp["date"] = df_avg_disp["date"].dt.strftime("%B %Y")
                st.dataframe(df_avg_disp, use_container_width=True, hide_index=True)
        else:
            st.warning("Impossible de charger les moyennes mensuelles. Assurez-vous que 'data/fuel_avg.csv' existe.")

    with tab_statbel_daily:
        st.markdown("### 📊 Prix Quotidiens Officiels (Statbel)")
        hist_mode = st.toggle("Afficher l'historique complet (plus lent)", value=False)
        
        with st.spinner("Téléchargement des données journalières..."):
            df_stat_daily = get_daily_prices(full_history=hist_mode)
            
        if not df_stat_daily.empty:
            st.markdown(f"Dernière mise à jour : **{df_stat_daily['date'].max().strftime('%d/%m/%Y')}**")
            
            # Graphique multi-colonnes
            st.area_chart(df_stat_daily.set_index("date"), use_container_width=True)
            
            with st.expander("Voir le tableau des relevés"):
                st.dataframe(df_stat_daily.sort_values("date", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.error("Impossible de récupérer les données journalières de Statbel pour le moment.")

else:
    st.error("Aucune donnée récupérée. Le site est peut-être temporairement indisponible.")

# ── Calculateur coût trajet ───────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
<div class="info-box">
    🧮 <strong>Calculateur coût carburant par trajet</strong>
</div>
""", unsafe_allow_html=True)

cc1, cc2, cc3 = st.columns(3)

with cc1:
    distance_km = st.number_input("Distance (km)", min_value=0, value=500, step=10)
with cc2:
    conso_100 = st.number_input("Consommation (L/100km)", min_value=0.0, value=32.0, step=0.5)
with cc3:
    if not df.empty and "diesel_routier" in df["type"].values:
        default_price = df[df["type"] == "diesel_routier"].iloc[-1]["prix"]
    elif "prices" in tarif and tarif["prices"]:
        default_price = list(tarif["prices"].values())[0]
    else:
        default_price = 1.70
    prix_litre = st.number_input("Prix gasoil (€/L)", min_value=0.0, value=round(default_price, 4), step=0.01, format="%.4f")

litres_needed = (distance_km / 100) * conso_100
cout_total    = litres_needed * prix_litre
cout_par_km   = cout_total / distance_km if distance_km > 0 else 0

r1, r2, r3 = st.columns(3)
with r1:
    st.markdown(f"""
    <div class="price-card">
        <div class="label">Litres nécessaires</div>
        <div class="price" style="font-size:2rem">{litres_needed:.1f}L</div>
    </div>""", unsafe_allow_html=True)
with r2:
    st.markdown(f"""
    <div class="price-card">
        <div class="label">Coût total</div>
        <div class="price" style="font-size:2rem;color:#c93400">{cout_total:.2f}€</div>
    </div>""", unsafe_allow_html=True)
with r3:
    st.markdown(f"""
    <div class="price-card">
        <div class="label">Coût / km</div>
        <div class="price" style="font-size:2rem;color:#0071e3">{cout_par_km:.4f}€</div>
    </div>""", unsafe_allow_html=True)

# ── Source ────────────────────────────────────────────────────
st.markdown("""
<br>
<div style="text-align:center">
    <span class="source-badge">
        📡 Source : SPF Economie — economie.fgov.be
    </span>
</div>
""", unsafe_allow_html=True)
