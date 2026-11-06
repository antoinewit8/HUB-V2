"""
outils/prix_affretement.py — Répertoire des prix d'affrètement.

Charge le classeur AFFRETEMENTS (onglet « LISTE DES DOSSIERS AFFRETES ») et répond à
« combien avons-nous payé un sous-traitant pour ce trajet ? » :
  • recherche d'un trajet (ville, zone de code postal ou pays) → fiche : dernier prix,
    médian, fourchette, marge, comparaison des sous-traitants, historique, dossiers ;
  • grille complète des trajets (clic sur une ligne = ouvre sa fiche) ;
  • vue par sous-traitant ;
  • export Excel de la sélection.
Le fichier reste en session (pas d'écriture sur Render).
"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import ui  # noqa: E402
from tools.affretement import engine as eng  # noqa: E402

ui.page("affretements")

st.markdown("""
<style>
.aff-fiche { background:#fff; border-radius:18px; padding:20px 22px 6px; box-shadow:var(--ap-shadow); margin:.4rem 0 1rem; }
.aff-trajet { display:flex; align-items:center; gap:14px; flex-wrap:wrap; font-size:26px; font-weight:600;
  letter-spacing:-0.02em; color:var(--ap-text); line-height:1.2; }
.aff-trajet .fl { color:var(--ap-sub); font-weight:400; }
.aff-sous { font-size:14px; color:var(--ap-sub); margin:6px 0 16px; }
.aff-kpis { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin-bottom:14px; }
.aff-kpi { background:var(--ap-bg); border-radius:14px; padding:14px 16px; }
.aff-kpi .l { font-size:13px; color:var(--ap-sub); }
.aff-kpi .v { font-size:28px; font-weight:600; letter-spacing:-0.02em; color:var(--ap-text); line-height:1.15; margin-top:2px; }
.aff-kpi .s { font-size:13px; color:var(--ap-sub); margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.aff-kpi.main { background:#0071e3; }
.aff-kpi.main .l, .aff-kpi.main .s { color:rgba(255,255,255,.82); }
.aff-kpi.main .v { color:#fff; }
.aff-fichier { display:flex; align-items:center; gap:10px; font-size:14px; color:var(--ap-sub); }
.aff-fichier b { color:var(--ap-text); font-weight:600; }
.aff-fichier i { width:8px; height:8px; border-radius:50%; background:#34c759; flex:none; }
@media (max-width: 760px) { .aff-kpis { grid-template-columns:repeat(2, minmax(0,1fr)); } }
</style>
""", unsafe_allow_html=True)

SCHEMA = "aff-v1"          # change → base en session recalculée
NB_COULEURS = 7            # sous-traitants colorés sur le graphique, les autres en gris
COULEURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
GRIS = "#aeaeb2"


# ─── Formats ─────────────────────────────────────────────────────────────────
def eur(v, dec=0) -> str:
    return "—" if pd.isna(v) else f"{v:,.{dec}f} €".replace(",", " ")


def pct(v) -> str:
    return "—" if pd.isna(v) else f"{v * 100:.1f} %".replace(".", ",")


def jour(v) -> str:
    return "—" if pd.isna(v) else pd.Timestamp(v).strftime("%d/%m/%Y")


def styler(d: pd.DataFrame):
    fmt = {}
    for c in d.columns:
        if "%" in c:
            fmt[c] = pct
        elif c in ("Date", "Dernier dossier", "Date charg."):
            fmt[c] = jour
        elif pd.api.types.is_float_dtype(d[c]):
            fmt[c] = eur
    return d.style.format(fmt, na_rep="—")


# ─── Fichier ─────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Lecture du classeur…", max_entries=3)
def charger(data: bytes, _schema: str = SCHEMA) -> pd.DataFrame:
    return eng.lire(data)


ss = st.session_state
if ss.get("aff_schema") != SCHEMA:
    for k in [k for k in ss if str(k).startswith("aff_")]:
        del ss[k]
    ss["aff_schema"] = SCHEMA

ui.section("Fichier")
if "aff_data" not in ss or ss.get("aff_changer"):
    up = st.file_uploader("Classeur AFFRETEMENTS (.xlsm ou .xlsx)", type=["xlsm", "xlsx"],
                          help="Onglet « LISTE DES DOSSIERS AFFRETES » : une ligne par dossier sous-traité.")
    if up is None:
        st.markdown('<div class="ap-note">Dépose le relevé des affrètements. Il reste chargé tant que '
                    'l’onglet du hub est ouvert, même en passant par d’autres outils.</div>',
                    unsafe_allow_html=True)
        st.stop()
    ss["aff_data"], ss["aff_nom"], ss["aff_changer"] = up.getvalue(), up.name, False
    st.rerun()

try:
    base = charger(ss["aff_data"])
except ValueError as e:
    st.warning(str(e))
    if st.button("Choisir un autre fichier"):
        del ss["aff_data"]
        st.rerun()
    st.stop()

c1, c2 = st.columns([5, 1.3], vertical_alignment="center")
c1.markdown(f'<div class="aff-fichier"><i></i><b>{ss["aff_nom"]}</b> · {len(base):,} dossiers · '
            f'du {jour(base["date"].min())} au {jour(base["date"].max())}</div>'.replace(",", " "),
            unsafe_allow_html=True)
if c2.button("Changer de fichier", width="stretch"):
    ss["aff_changer"] = True
    st.rerun()

# ─── Filtres ─────────────────────────────────────────────────────────────────
ui.section("Filtres")
f1, f2, f3 = st.columns([1.1, 1.6, 1.3])
with f1:
    typ = st.segmented_control("Type", ["Tous", "CIT", "PLA"], default="Tous", key="aff_type") or "Tous"
with f2:
    dmin, dmax = base["date"].min().date(), base["date"].max().date()
    periode = st.date_input("Période (date de chargement)", value=(dmin, dmax), min_value=dmin,
                            max_value=dmax, format="DD/MM/YYYY", key="aff_periode")
with f3:
    niveau = st.segmented_control("Regrouper par", list(eng.NIVEAUX), default="ville",
                                  format_func=eng.NIVEAUX.get, key="aff_niveau",
                                  help="Ville : localité + zone CP. Zone CP : 2 premiers chiffres du code "
                                       "postal (département en France). Pays : pays de chargement et de "
                                       "déchargement.") or "ville"

g1, g2, g3 = st.columns([1.5, 1.5, 1.3])
with g1:
    clients = st.multiselect("Client", sorted(base["client"].unique()), placeholder="Tous les clients",
                             key="aff_clients")
with g2:
    sts = st.multiselect("Sous-traitant", base["st"].value_counts().index.tolist(),
                         placeholder="Tous les sous-traitants", key="aff_sts")
with g3:
    st.write("")
    sans_zero = st.toggle("Ignorer les achats à 0 €", value=True, key="aff_zero",
                          help="Dossiers dont l’achat n’est pas encore saisi.")
    factures = st.toggle("Dossiers facturés seulement", value=False, key="aff_fact",
                         help="Écarte « Pas confirmé », « Confirmé » et « Pas à facturer ».")

df = base
if typ != "Tous":
    df = df[df["type"] == typ]
if isinstance(periode, (tuple, list)) and len(periode) == 2:
    d0, d1 = pd.Timestamp(periode[0]), pd.Timestamp(periode[1]) + pd.Timedelta(days=1)
    df = df[(df["date"] >= d0) & (df["date"] < d1)]
if clients:
    df = df[df["client"].isin(clients)]
if sts:
    df = df[df["st"].isin(sts)]
if sans_zero:
    df = df[df["achat"].fillna(0) > 0]
if factures:
    df = df[df["statut"].str.startswith(("Facturé", "Partiellement"))]
df = df.copy()
df["verif"] = eng.signaler(df, niveau)
kc, kd = eng.cles(niveau)

if df.empty:
    st.info("Aucun dossier avec ces filtres.")
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Dossiers", f"{len(df):,}".replace(",", " "))
m2.metric("Trajets différents", f"{df.groupby([kc, kd]).ngroups:,}".replace(",", " "))
m3.metric("Sous-traitants", df["st"].nunique())
m4.metric("Marge globale", pct(eng._ratio(df["marge"], df["vente"])),
          help="Marge totale ÷ ventes totales de la sélection.")


# ─── Recherche d'un trajet ───────────────────────────────────────────────────
def _options(col: str, d: pd.DataFrame) -> list[str]:
    return d[col].value_counts().index.tolist()


def _choisir_ligne():
    """Clic dans la grille → la fiche du trajet s'ouvre (sélecteurs du haut remplis)."""
    sel = ss.get(f"aff_grille_{niveau}_{ss.get('aff_c')}_{ss.get('aff_d')}")
    rows = (sel or {}).get("selection", {}).get("rows", [])
    g = ss.get("aff_grille_df")
    if rows and g is not None and rows[0] < len(g):
        ss["aff_c"], ss["aff_d"] = g.iloc[rows[0]]["Chargement"], g.iloc[rows[0]]["Déchargement"]


# Les valeurs gardées doivent exister dans les options (changement de niveau ou de filtre)
opts_c = _options(kc, df)
if ss.get("aff_c") not in opts_c:
    ss["aff_c"] = None
d_c = df[df[kc] == ss["aff_c"]] if ss.get("aff_c") else df
opts_d = _options(kd, d_c)
if ss.get("aff_d") not in opts_d:
    ss["aff_d"] = None

ui.section("Rechercher un trajet")
nb_c = df[kc].value_counts()
nb_d = d_c[kd].value_counts()
s1, s2, s3 = st.columns([1, 1, .32], vertical_alignment="bottom")
with s1:
    choix_c = st.selectbox("Chargement", opts_c, index=None, key="aff_c", placeholder="Tape une ville…",
                           format_func=lambda v: f"{v}  ·  {nb_c.get(v, 0)}")
with s2:
    choix_d = st.selectbox("Déchargement", opts_d, index=None, key="aff_d", placeholder="Tape une ville…",
                           format_func=lambda v: f"{v}  ·  {nb_d.get(v, 0)}")
with s3:
    st.button("Effacer", width="stretch", disabled=not (choix_c or choix_d),
              on_click=lambda: ss.update(aff_c=None, aff_d=None))
st.caption("Le nombre à droite de chaque lieu = dossiers affrétés. Choisis un chargement pour ne voir "
           "que ses déchargements, ou clique une ligne de la grille plus bas.")


def graphique(t: pd.DataFrame, mediane: float) -> go.Figure:
    ordre = t["st"].value_counts().index.tolist()
    couleur = {s: COULEURS[i] for i, s in enumerate(ordre[:NB_COULEURS])}
    fig = go.Figure()
    fig.add_hline(y=mediane, line=dict(color="#8e8e93", width=1.2, dash="dot"),
                  annotation_text=f"médian {eur(mediane)}", annotation_position="top left",
                  annotation_font=dict(size=12, color="#6e6e73"))
    groupes = [(s, t[t["st"] == s], couleur[s]) for s in ordre[:NB_COULEURS]]
    autres = t[~t["st"].isin(couleur)]
    if len(autres):
        groupes.append((f"Autres ({autres['st'].nunique()})", autres, GRIS))
    for nom, d, c in groupes:
        fig.add_trace(go.Scatter(
            x=d["date"], y=d["achat"], mode="markers", name=nom,
            marker=dict(size=10, color=c, line=dict(width=1.5, color="#fff")),
            customdata=np.stack([d["dossier"], d["st"], d["client"], d["vente"].fillna(0),
                                 d["marge_pct"].fillna(0) * 100], axis=1),
            hovertemplate="<b>%{y:,.0f} €</b> · %{x|%d/%m/%Y}<br>%{customdata[1]}<br>"
                          "Dossier %{customdata[0]} · %{customdata[2]}<br>"
                          "Vente %{customdata[3]:,.0f} € · marge %{customdata[4]:.1f} %<extra></extra>"))
    fig.update_layout(
        height=360, margin=dict(l=8, r=8, t=10, b=8), plot_bgcolor="#fff", paper_bgcolor="#fff",
        font=dict(family=ui.FONT, size=13, color="#1d1d1f"), hovermode="closest",
        separators=", ", legend=dict(orientation="h", y=-0.16, x=0, font=dict(size=12)),
        hoverlabel=dict(bgcolor="#fff", bordercolor="#d2d2d7", font=dict(family=ui.FONT, size=13)),
    )
    fig.update_xaxes(showgrid=False, linecolor="#d2d2d7", tickformat="%m/%Y")
    fig.update_yaxes(gridcolor="#f0f0f2", zeroline=False, ticksuffix=" €", rangemode="tozero")
    return fig


def fiche(t: pd.DataFrame, depart: str, arrivee: str):
    dern = t.iloc[0]
    med = t["achat"].median()
    recents = t[t["date"] >= t["date"].max() - pd.Timedelta(days=90)]
    types = " / ".join(sorted(set(t["type"]) - {""}))
    st.markdown(
        f'<div class="aff-fiche"><div class="aff-trajet">{depart}<span class="fl">→</span>{arrivee}</div>'
        f'<div class="aff-sous">{types} · {len(t)} dossier{"s" * (len(t) > 1)} · {t["st"].nunique()} '
        f'sous-traitant{"s" * (t["st"].nunique() > 1)} · du {jour(t["date"].min())} au {jour(t["date"].max())}</div>'
        f'<div class="aff-kpis">'
        f'<div class="aff-kpi main"><div class="l">Dernier prix d’achat</div><div class="v">{eur(dern["achat"])}</div>'
        f'<div class="s">{jour(dern["date"])} · {dern["st"].title()}</div></div>'
        f'<div class="aff-kpi"><div class="l">Achat médian</div><div class="v">{eur(med)}</div>'
        f'<div class="s">3 derniers mois : {eur(recents["achat"].median())} ({len(recents)})</div></div>'
        f'<div class="aff-kpi"><div class="l">Fourchette habituelle</div><div class="v" style="font-size:22px;padding-top:4px">'
        f'{eur(t["achat"].quantile(.1))} – {eur(t["achat"].quantile(.9))}</div>'
        f'<div class="s">min {eur(t["achat"].min())} · max {eur(t["achat"].max())}</div></div>'
        f'<div class="aff-kpi"><div class="l">Vente médiane · marge</div><div class="v">{eur(t["vente"].median())}</div>'
        f'<div class="s">marge {pct(eng._ratio(t["marge"], t["vente"]))} du CA</div></div>'
        f'</div></div>', unsafe_allow_html=True)

    st.markdown("#### Sous-traitants sur ce trajet")
    comp = eng.comparer_sous_traitants(t)
    st.dataframe(styler(comp), hide_index=True, width="stretch", height=min(35 * (len(comp) + 1) + 3, 320),
                 column_config={"Sous-traitant": st.column_config.Column(width="medium")})
    st.markdown("#### Historique des achats")
    st.plotly_chart(graphique(t, med), width="stretch", config={"displayModeBar": False})

    nb_v = int((t["verif"] != "").sum())
    with st.expander(f"Les {len(t)} dossiers" + (f" · {nb_v} à vérifier" if nb_v else "")):
        cols = ["verif", "dossier", "type", "date_c", "client", "st", "statut", "vente", "achat", "marge",
                "marge_pct", "ref"]
        d = t[cols].rename(columns=eng.COLS_DOSSIERS)
        st.dataframe(styler(d), hide_index=True, width="stretch", height=min(36 * (len(d) + 1) + 3, 460),
                     column_config={"À vérifier": st.column_config.Column(width="medium")})
        if nb_v:
            st.caption("À vérifier : achat < 50 % ou > 180 % du médian du trajet (dès 3 dossiers), ou marge négative.")


if choix_c and choix_d:
    fiche(df[(df[kc] == choix_c) & (df[kd] == choix_d)], choix_c, choix_d)
elif choix_c or choix_d:
    st.markdown(f'<div class="ap-note">Tous les trajets {"au départ de" if choix_c else "à destination de"} '
                f'<b>{choix_c or choix_d}</b> sont dans la grille ci-dessous. Choisis '
                f'{"un déchargement" if choix_c else "un chargement"} ou clique une ligne pour ouvrir sa fiche.</div>',
                unsafe_allow_html=True)

# ─── Grille + sous-traitants ─────────────────────────────────────────────────
vue = df
if choix_c:
    vue = vue[vue[kc] == choix_c]
if choix_d:
    vue = vue[vue[kd] == choix_d]

ui.section("Grille des prix")
tab_g, tab_s = st.tabs(["Par trajet", "Par sous-traitant"])
with tab_g:
    g = eng.grille(vue, niveau)
    q = st.text_input("Filtrer la grille", placeholder="Ville, zone CP (« F 59 ») ou sous-traitant…",
                      key="aff_q", label_visibility="collapsed")
    if q:
        m = (g["Chargement"].str.contains(q, case=False, regex=False)
             | g["Déchargement"].str.contains(q, case=False, regex=False)
             | g["Dernier sous-traitant"].str.contains(q, case=False, regex=False))
        g = g[m].reset_index(drop=True)
    ss["aff_grille_df"] = g
    st.caption(f"{len(g):,} trajets · trié par nombre de dossiers · clique une ligne pour ouvrir sa fiche."
               .replace(",", " "))
    st.dataframe(styler(g), hide_index=True, width="stretch", height=min(35 * (len(g) + 1) + 3, 560), on_select=_choisir_ligne,
                 selection_mode="single-row", key=f"aff_grille_{niveau}_{choix_c}_{choix_d}",
                 column_config={"Chargement": st.column_config.Column(width="medium"),
                                "Déchargement": st.column_config.Column(width="medium"),
                                "Dernier sous-traitant": st.column_config.Column(width="medium"),
                                "Dossiers": st.column_config.NumberColumn(width="small"),
                                "Sous-traitants": st.column_config.NumberColumn(width="small")})
with tab_s:
    p = eng.par_sous_traitant(vue, niveau)
    st.dataframe(styler(p), hide_index=True, width="stretch", height=min(35 * (len(p) + 1) + 3, 560),
                 column_config={"Sous-traitant": st.column_config.Column(width="medium"),
                                "Trajets principaux": st.column_config.Column(width="large"),
                                "CIT": st.column_config.NumberColumn(width="small"),
                                "PLA": st.column_config.NumberColumn(width="small")})

# ─── Export ──────────────────────────────────────────────────────────────────
dossiers = vue[list(eng.COLS_DOSSIERS)].rename(columns=eng.COLS_DOSSIERS)
st.download_button(
    "Exporter la sélection en Excel",
    data=eng.excel({"Trajets": eng.grille(vue, niveau), "Sous-traitants": eng.par_sous_traitant(vue, niveau),
                    "Dossiers": dossiers}),
    file_name=f"prix_affretement_{date.today():%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
