"""
Page Streamlit : Détour Werbomont
Quels dossiers CIT peuvent passer par le centre logistique de Werbomont
(lavage, parking, pompe) et à quel coût en km et en rentabilité ?

Fichiers : LISTES_MISSIONS (activités par dossier) + CA CIT (prix par dossier).
Calcul : tools/werbomont/engine.py (méthode détaillée dans son en-tête).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ui  # noqa: E402
from tools.werbomont import engine as E  # noqa: E402

ui.page("werbomont", "Les dossiers CIT qui peuvent passer par Werbomont, le détour en km et l’effet sur la rentabilité.")

CAT_COUL = {"ok": "#248a3d", "verif": "#e8890c", "lourd": "#d70015", "deja": "#003087", "na": "#8e8e93"}
CAT_FOND = {"ok": "#e8f6ec", "verif": "#fff1e0", "lourd": "#fdecee", "deja": "#e6ecf7", "na": "#f2f2f7"}

st.markdown("""
<style>
.wb-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: .4rem 0 1rem; }
.wb-kpi { background: #fff; border-radius: 18px; padding: 16px 18px; box-shadow: var(--ap-shadow); }
.wb-kpi .v { font-size: 30px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.1; color: var(--ap-text); }
.wb-kpi .l { font-size: 13px; color: var(--ap-sub); margin-top: 4px; }
.wb-kpi .s { font-size: 12px; color: var(--ap-sub); margin-top: 2px; }
.wb-kpi.ok .v { color: #248a3d; } .wb-kpi.verif .v { color: #e8890c; } .wb-kpi.lourd .v { color: #d70015; }
.wb-bar { display: flex; height: 10px; border-radius: 980px; overflow: hidden; background: #e8e8ed; margin: .2rem 0 .3rem; }
.wb-bar i { display: block; height: 100%; }
.wb-leg { font-size: 12px; color: var(--ap-sub); display: flex; gap: 16px; flex-wrap: wrap; }
.wb-leg b { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; vertical-align: 0; }
@media (max-width: 760px) { .wb-kpis { grid-template-columns: repeat(2, 1fr); } }
</style>
""", unsafe_allow_html=True)


# ─── Chargement et calcul (mis en cache) ─────────────────────────────────────
@st.cache_resource(show_spinner=False)
def geocodeur():
    return E.Geocodeur()


@st.cache_resource(show_spinner=False)
def cache_ptv() -> dict:
    """km PTV partagés entre sessions tant que le serveur tourne (Render : pas d'écriture disque)."""
    return {}


@st.cache_data(show_spinner=False, max_entries=3)
def lire_excel(contenu: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(contenu), dtype={"Code postal": str, "Département": str})


@st.cache_data(show_spinner=False, max_entries=3)
def preparer(h_mis: str, h_ca: str, _mis: bytes, _ca: bytes, ecart_jours: float, w: tuple):
    geo = geocodeur()
    m = E.preparer_missions(lire_excel(_mis), geo)
    ca = E.preparer_ca(lire_excel(_ca))
    d = E.construire_dossiers(m, ca)
    d = E.chainer(d, ecart_jours)
    non_geo = (m[m["geo"].isin(["introuvable"])]
               .groupby(["iso", "cp", "localite"], dropna=False).size().reset_index(name="lignes")
               .sort_values("lignes", ascending=False))
    precision = m["geo"].value_counts()
    ca_seul = sorted(set(ca["dossier"]) - set(m["dossier"]))
    return d, non_geo, precision, ca_seul


BORDER_URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_boundary_lines_land.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_boundary_lines_land.geojson",
]
EUROPE_BBOX = (-11.0, 35.0, 32.0, 62.0)  # ouest, sud, est, nord


def _decimer(ligne, pas=0.003):
    if len(ligne) < 3:
        return [[round(p[0], 4), round(p[1], 4)] for p in ligne]
    out = [ligne[0]]
    for p in ligne[1:-1]:
        if abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= pas:
            out.append(p)
    out.append(ligne[-1])
    return [[round(p[0], 4), round(p[1], 4)] for p in out]


@st.cache_data(ttl=30 * 86400, show_spinner="Chargement des frontières…")
def load_borders():
    """Frontières Natural Earth limitées à l'Europe (même source que la carte des lavages)."""
    import urllib.request as ureq
    w, s_, e, n = EUROPE_BBOX
    for url in BORDER_URLS:
        try:
            req = ureq.Request(url, headers={"User-Agent": "CB-Transport-Hub/1.0"})
            with ureq.urlopen(req, timeout=40) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        lignes = []
        for f in data.get("features", []):
            g = f.get("geometry") or {}
            parts = [g["coordinates"]] if g.get("type") == "LineString" else (
                g["coordinates"] if g.get("type") == "MultiLineString" else [])
            for li in parts:
                if any(w <= p[0] <= e and s_ <= p[1] <= n for p in li):
                    lignes.append(_decimer(li))
        if lignes:
            return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                    "geometry": {"type": "MultiLineString", "coordinates": lignes}}]}
    raise RuntimeError("frontières indisponibles")


def fr2(x) -> str:
    return f"{x:.2f}".replace(".", ",")


def empreinte(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


# ─── Fichiers ────────────────────────────────────────────────────────────────
ui.section("Fichiers")
c1, c2 = st.columns(2)
with c1:
    f_mis = st.file_uploader("Liste des missions (LISTES_MISSIONS)", type=["xlsx", "xls"], key="wb_mis",
                             help="Une ligne par activité : CHARGER, DECHARGER, LAVAGE, DECROCHER…")
with c2:
    f_ca = st.file_uploader("Chiffre d’affaires citernes (CA CIT)", type=["xlsx", "xls"], key="wb_ca",
                            help="Une ligne par dossier avec le prix transport.")

with st.expander("Paramètres"):
    p1, p2, p3 = st.columns(3)
    with p1:
        w_lat = st.number_input("Werbomont — latitude", value=E.WERBOMONT[0], format="%.4f", step=0.001)
        w_lon = st.number_input("Werbomont — longitude", value=E.WERBOMONT[1], format="%.4f", step=0.001)
    with p2:
        s_ok = st.number_input("Acceptable jusqu’à (km)", value=E.SEUILS[0], min_value=0, step=5)
        s_verif = st.number_input("À vérifier jusqu’à (km)", value=E.SEUILS[1], min_value=0, step=5)
    with p3:
        coef = st.number_input("Coefficient vol d’oiseau → route", value=E.COEF_ROUTE, min_value=1.0, max_value=2.0,
                               step=0.05, help="Utilisé tant que PTV n’a pas calculé le tronçon. 1,30 = médiane "
                                               "des routes de référence du hub.")
        ecart = st.number_input("Écart max avant le dossier suivant (jours)", value=float(E.ECART_MAX_JOURS),
                                min_value=0.5, step=0.5,
                                help="Au-delà, la citerne est considérée à l’arrêt : pas de trajet à vide calculé.")
    exclure_aff = st.toggle("Exclure les affrétés (tracteur AFF)", value=True)

if not (f_mis and f_ca):
    st.markdown("""
<div class="ap-card"><h4>Comment le détour est calculé</h4>
<ul class="ap-list">
<li><b>À vide</b> <span>— lavage, plein, parking. Après le dernier déchargement, la citerne va laver puis recharger
pour le dossier suivant (même remorque). Détour = km(déchargement → Werbomont → rechargement) −
km(déchargement → lavage utilisé → rechargement). Le lavage se fait de toute façon : on compare au trajet réel.</span></li>
<li><b>En charge</b> <span>— parking, pompe, relais chauffeur. Meilleure insertion de Werbomont entre deux arrêts
consécutifs du dossier : km(A → Werbomont → B) − km(A → B). Les dossiers multi-points sont testés à chaque tronçon.</span></li>
<li><b>Rentabilité</b> <span>— prix transport ÷ (km chargés + km à vide du dossier), avant et après détour.
Par ligne : Σ prix ÷ Σ km.</span></li>
<li><b>Km</b> <span>— estimés au vol d’oiseau × 1,30, puis remplacés par PTV (poids lourd) sur les candidats.</span></li>
</ul></div>""", unsafe_allow_html=True)
    st.stop()

b_mis, b_ca = f_mis.getvalue(), f_ca.getvalue()
W = (float(w_lat), float(w_lon))
seuils = (float(s_ok), float(max(s_verif, s_ok)))

try:
    with st.spinner("Lecture, géolocalisation et chaînage des dossiers… (≈ 30 s la première fois)"):
        dossiers, non_geo, precision, ca_seul = preparer(empreinte(b_mis), empreinte(b_ca), b_mis, b_ca,
                                                         float(ecart), W)
except ValueError as e:
    st.error(str(e))
    st.stop()

# Période
dmin, dmax = dossiers["dt_C1"].min(), dossiers["dt_C1"].max()
f1, f2 = st.columns([2, 1])
with f1:
    periode = st.date_input("Période (date de chargement)", value=(dmin.date(), dmax.date()),
                            min_value=dmin.date(), max_value=dmax.date(), format="DD/MM/YYYY")
with f2:
    mode_lbl = st.segmented_control("Passage à Werbomont", ["À vide", "En charge"], default="À vide",
                                    help="À vide : lavage, plein, parking après déchargement. "
                                         "En charge : parking, pompe ou relais pendant le transport.")
mode = "charge" if mode_lbl == "En charge" else "vide"
col_det, col_cat = ("detour_vide", "cat_vide") if mode == "vide" else ("detour_charge", "cat_charge")

d = dossiers
if exclure_aff:
    d = d[~d["tracteur"].fillna("").str.upper().str.startswith("AFF")]
if isinstance(periode, tuple) and len(periode) == 2:
    d = d[(d["dt_C1"] >= pd.Timestamp(periode[0])) & (d["dt_C1"] < pd.Timestamp(periode[1]) + pd.Timedelta(days=1))]

dist = E.Distances(coef=float(coef), cache=cache_ptv())
d = E.calculer(d, dist, W, seuils)

# ─── PTV sur les candidats ───────────────────────────────────────────────────
ui.section("Km routiers PTV")
cle = E.cle_ptv()
paires = E.paires_a_calculer(d, W, mode, filtre_km=seuils[1] + 40)
manquantes = [p for p in paires if E.Distances.cle(*p) not in dist.cache]
st.markdown(
    (f'<div class="ap-statut"><i></i>PTV disponible — {len(dist.cache):_} tronçons déjà calculés</div>'
     if cle else '<div class="ap-statut off"><i></i>Clé PTV non configurée : km estimés au vol d’oiseau × '
                 f'{fr2(coef)}</div>').replace("_", " "),
    unsafe_allow_html=True)
st.caption(f"Candidats : dossiers dont le détour estimé est ≤ {seuils[1] + 40:.0f} km. "
           f"{len(paires):_} tronçons, dont {len(manquantes):_} à calculer.".replace("_", " "))
if cle and manquantes:
    cA, cB = st.columns([1, 2])
    with cA:
        lot = st.number_input("Tronçons par lancement", min_value=50, max_value=5000,
                              value=min(1500, len(manquantes)), step=50)
    with cB:
        st.write("")
        st.write("")
        go = st.button(f"Calculer {min(lot, len(manquantes)):_} tronçons avec PTV".replace("_", " "), type="primary")
    if go:
        barre = st.progress(0.0, text="PTV…")
        ok, ko = E.ptv_lot(manquantes[: int(lot)], cle, dist.cache,
                           progression=lambda n, t: barre.progress(n / t, text=f"PTV… {n}/{t}"))
        barre.empty()
        st.toast(f"{ok} tronçons calculés" + (f", {ko} en échec" if ko else ""))
        st.rerun()

# ─── Synthèse ────────────────────────────────────────────────────────────────
ok_d = d[d["statut"].eq("ok")]
deja = ok_d[ok_d[col_cat].eq("deja")]
calc = ok_d[ok_d[col_det].notna() & ~ok_d[col_cat].eq("deja")]
n = len(calc)
cnt = calc[col_cat].value_counts()
tot = n + len(deja)
pct = lambda k: ((len(deja) if k == "deja" else cnt.get(k, 0)) / tot * 100) if tot else 0  # noqa: E731

ui.section("Synthèse")
ptv_part = calc["ptv_vide" if mode == "vide" else "ptv_charge"].mean() * 100 if n else 0
quand = "après déchargement" if mode == "vide" else "pendant le transport"
st.markdown(f"""
<div class="wb-kpis">
  <div class="wb-kpi"><div class="v">{n:_}</div><div class="l">dossiers calculés</div>
       <div class="s">sur {len(ok_d):_} · {ptv_part:.0f} % en km PTV</div></div>
  <div class="wb-kpi ok"><div class="v">{cnt.get('ok', 0):_}</div><div class="l">acceptables ≤ {seuils[0]:.0f} km</div>
       <div class="s">{cnt.get('ok', 0) / n * 100 if n else 0:.1f} %</div></div>
  <div class="wb-kpi verif"><div class="v">{cnt.get('verif', 0):_}</div><div class="l">à vérifier ≤ {seuils[1]:.0f} km</div>
       <div class="s">{cnt.get('verif', 0) / n * 100 if n else 0:.1f} %</div></div>
  <div class="wb-kpi lourd"><div class="v">{cnt.get('lourd', 0):_}</div><div class="l">trop lourds</div>
       <div class="s">{cnt.get('lourd', 0) / n * 100 if n else 0:.1f} %</div></div>
</div>
<div class="wb-bar">{''.join(f'<i style="width:{pct(k)}%;background:{CAT_COUL[k]}"></i>' for k in ("deja", "ok", "verif", "lourd"))}</div>
<div class="wb-leg">{''.join(f'<span><b style="background:{CAT_COUL[k]}"></b>{E.CAT_LABELS[k]}</span>' for k in ("deja", "ok", "verif", "lourd"))}</div>
<div class="ap-note">{len(deja):_} dossiers passent déjà par Werbomont {quand} (hors calcul).
{int(ok_d['multi'].sum()):_} dossiers multi-points. {int(ok_d[col_det].isna().sum()):_} non calculés, voir Contrôles.</div>
""".replace("_", " "), unsafe_allow_html=True)

acc = calc[calc[col_cat].eq("ok") & calc["dans_ca"]]
if len(acc):
    ca_acc = acc["prix"].sum()
    km_av, km_ap = acc["km_total"].sum(), (acc["km_total"] + acc[col_det]).sum()
    gains = acc[acc[col_det] < 0]
    txt_gain = (f" Dans {len(gains):_} cas, Werbomont est même <b>plus court</b> que le lavage utilisé "
                f"({-gains[col_det].sum():_.0f} km économisés)." if mode == "vide" and len(gains) else "")
    st.markdown(
        f'<div class="ap-note">Dossiers acceptables : <b>{len(acc):_}</b>, {ca_acc:_.0f} € de prix transport. '
        f'Détour médian <b>{acc[col_det].median():.0f} km</b>, {acc[col_det].clip(lower=0).sum():_.0f} km ajoutés au total.'
        f'{txt_gain} Rentabilité {fr2(ca_acc / km_av)} €/km → <b>{fr2(ca_acc / km_ap)} €/km</b> via Werbomont.</div>'
        .replace("_", " "), unsafe_allow_html=True)

# ─── Lignes ──────────────────────────────────────────────────────────────────
lignes = E.agreger_lignes(d, mode, seuils)
lignes_autre = E.agreger_lignes(d, "charge" if mode == "vide" else "vide", seuils)

ui.section("Carte")
min_dos = st.slider("Lignes d’au moins … dossiers sur la carte", 1, 50, 3)


def _v(x, nd=2):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return round(float(x), nd)
    return x


def payload_carte() -> dict:
    autres = lignes_autre.set_index("ligne")
    sel = lignes[(lignes["nb_dossiers"] >= min_dos) & lignes[["C1_lat", "Dn_lat"]].notna().all(axis=1)]
    rows = []
    for r in sel.itertuples(index=False):
        o = autres.loc[r.ligne] if r.ligne in autres.index else None
        rows.append({
            "l": r.ligne, "dep": r.depart, "arr": r.arrivee, "cli": r.client, "n": int(r.nb_dossiers),
            "nc": int(r.nb_calcules), "multi": int(r.multi_points),
            "prix": _v(r.prix_moyen, 0), "ca": _v(r.ca_total, 0), "kmc": _v(r.km_charge_moy, 0), "kmv": _v(r.km_vide_moy, 0),
            "a": [_v(r.C1_lat, 4), _v(r.C1_lon, 4)], "b": [_v(r.Dn_lat, 4), _v(r.Dn_lon, 4)],
            mode: {"dejaW": int(r.deja_W), "det": _v(r.detour_median, 0), "ok": _v(r.part_acceptable), "ra": _v(r.renta_actuelle),
                   "rw": _v(r.renta_via_W), "dp": _v(r.delta_renta_pct, 1), "cat": r.categorie},
            ("charge" if mode == "vide" else "vide"): None if o is None else {
                "dejaW": int(o.deja_W), "det": _v(o.detour_median, 0), "ok": _v(o.part_acceptable), "ra": _v(o.renta_actuelle),
                "rw": _v(o.renta_via_W), "dp": _v(o.delta_renta_pct, 1), "cat": o.categorie},
        })
    return {"lignes": rows, "w": list(W), "seuils": list(seuils), "mode": mode,
            "periode": f"{pd.Timestamp(periode[0]).strftime('%d/%m/%Y')} – {pd.Timestamp(periode[1]).strftime('%d/%m/%Y')}"
            if isinstance(periode, tuple) and len(periode) == 2 else "",
            "genere": datetime.now().strftime("%d/%m/%Y à %H:%M")}


MAP_HTML = open(os.path.join(os.path.dirname(E.__file__), "carte.html"), encoding="utf-8").read()
try:
    frontieres = load_borders()
except Exception:
    frontieres = None
carte = (MAP_HTML.replace("__DATA__", json.dumps(payload_carte(), ensure_ascii=False).replace("</", "<\\/"), 1)
         .replace("__BORDERS__", json.dumps(frontieres, separators=(",", ":")) if frontieres else "null", 1))
contenu = json.dumps(carte).replace("</", "<\\/")
components.html(f"""
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif; }}
  button {{ height: 48px; padding: 0 28px; border: none; border-radius: 980px; background: #0071e3; color: #fff;
           font: 500 17px -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif;
           cursor: pointer; transition: background .15s, transform .1s; }}
  button:hover {{ background: #0077ed; }} button:active {{ transform: scale(.98); }}
  p {{ margin: 10px 0 0 4px; font-size: 13px; color: #6e6e73; }}
</style>
<button id="ouvrir">Ouvrir la carte plein écran</button>
<p id="msg">S’ouvre dans un nouvel onglet.</p>
<script>
const PAGE = {contenu};
document.getElementById('ouvrir').addEventListener('click', () => {{
  const url = URL.createObjectURL(new Blob([PAGE], {{ type: 'text/html' }}));
  const w = window.open(url, '_blank');
  document.getElementById('msg').textContent = w ? 'Carte ouverte dans un nouvel onglet.'
    : 'Le navigateur a bloqué l’ouverture : autorisez les pop-up pour le HUB, ou téléchargez la carte ci-dessous.';
}});
</script>""", height=90)
st.download_button("Télécharger la carte (HTML)", carte.encode("utf-8"), "carte_werbomont.html", "text/html")

# ─── Tableaux ────────────────────────────────────────────────────────────────
ui.section("Détail")
CAT_TXT = {k: v for k, v in E.CAT_LABELS.items()}

t_l, t_d, t_c = st.tabs(["Lignes", "Dossiers", "Contrôles"])
with t_l:
    cats = st.multiselect("Catégories", [CAT_TXT[k] for k in ("ok", "verif", "lourd", "na")],
                          default=[CAT_TXT["ok"], CAT_TXT["verif"]], key="wb_cats")
    vue = lignes[lignes["categorie"].map(CAT_TXT).isin(cats)].copy()
    vue["categorie"] = vue["categorie"].map(CAT_TXT)
    st.dataframe(vue[["ligne", "client", "nb_dossiers", "multi_points", "deja_W", "prix_moyen", "km_charge_moy",
                      "km_vide_moy", "detour_median", "part_acceptable", "renta_actuelle", "renta_via_W",
                      "delta_renta_pct", "categorie"]],
                 hide_index=True, width="stretch", height=480,
                 column_config={
                     "ligne": st.column_config.TextColumn("Ligne", width="large"),
                     "client": "Client", "nb_dossiers": st.column_config.NumberColumn("Dossiers"),
                     "multi_points": st.column_config.NumberColumn("Multi-pts"),
                     "deja_W": st.column_config.NumberColumn("Déjà via W"),
                     "prix_moyen": st.column_config.NumberColumn("Prix moy.", format="%.0f €"),
                     "km_charge_moy": st.column_config.NumberColumn("Km chargés", format="%.0f"),
                     "km_vide_moy": st.column_config.NumberColumn("Km vide", format="%.0f"),
                     "detour_median": st.column_config.NumberColumn("Détour médian", format="%.0f km"),
                     "part_acceptable": st.column_config.ProgressColumn("Part ≤ seuil", format="percent",
                                                                        min_value=0, max_value=1),
                     "renta_actuelle": st.column_config.NumberColumn("Renta", format="%.2f €/km"),
                     "renta_via_W": st.column_config.NumberColumn("Renta via W", format="%.2f €/km"),
                     "delta_renta_pct": st.column_config.NumberColumn("Écart", format="%.1f %%"),
                     "categorie": "Catégorie"})

COLS_DOS = ["dossier", "dt_C1", "client", "ville_C1", "ville_Dn", "multi", "lavage_noms", "ville_B", "dossier_suivant",
            "remorque", "chauffeur", "prix", "km_charge", "km_vide_actuel", "km_vide_W", "detour_vide",
            "detour_vide_vs_direct", "detour_charge", "insertion_charge", "passe_W_quoi", "vide_atypique",
            "renta_actuelle", "renta_W_vide", "renta_W_charge", "cat_vide", "cat_charge", "ptv_vide", "ptv_charge"]
with t_d:
    q = st.text_input("Rechercher (dossier, ville, client, remorque…)", key="wb_q")
    vd = ok_d[ok_d[col_det].notna() | ok_d[col_cat].eq("deja")].sort_values(col_det)
    if q:
        txt = vd[["dossier", "ville_C1", "ville_Dn", "client", "remorque", "chauffeur", "lavage_noms"]].astype(str) \
            .agg(" ".join, axis=1).str.upper()
        vd = vd[txt.str.contains(q.upper(), regex=False)]
    vd = vd[COLS_DOS].copy()
    vd["cat_vide"] = vd["cat_vide"].map(CAT_TXT)
    vd["cat_charge"] = vd["cat_charge"].map(CAT_TXT)
    st.dataframe(vd.head(5000), hide_index=True, width="stretch", height=480,
                 column_config={
                     "dossier": "Dossier", "dt_C1": st.column_config.DatetimeColumn("Chargement", format="DD/MM/YYYY"),
                     "client": "Client", "ville_C1": "Départ", "ville_Dn": "Arrivée", "multi": "Multi-pts",
                     "lavage_noms": "Lavage utilisé", "ville_B": "Rechargement suivant", "dossier_suivant": "Dossier suivant",
                     "remorque": "Remorque", "chauffeur": "Chauffeur",
                     "prix": st.column_config.NumberColumn("Prix", format="%.0f €"),
                     "km_charge": st.column_config.NumberColumn("Km chargés", format="%.0f"),
                     "km_vide_actuel": st.column_config.NumberColumn("Km vide actuel", format="%.0f"),
                     "km_vide_W": st.column_config.NumberColumn("Km vide via W", format="%.0f"),
                     "detour_vide": st.column_config.NumberColumn("Détour à vide", format="%.0f km"),
                     "detour_vide_vs_direct": st.column_config.NumberColumn("Détour vs direct", format="%.0f km"),
                     "detour_charge": st.column_config.NumberColumn("Détour en charge", format="%.0f km"),
                     "insertion_charge": "Tronçon d’insertion", "passe_W_quoi": "Activité à W",
                     "vide_atypique": "Vide atypique",
                     "renta_actuelle": st.column_config.NumberColumn("Renta", format="%.2f"),
                     "renta_W_vide": st.column_config.NumberColumn("Renta W vide", format="%.2f"),
                     "renta_W_charge": st.column_config.NumberColumn("Renta W charge", format="%.2f"),
                     "cat_vide": "Cat. vide", "cat_charge": "Cat. charge",
                     "ptv_vide": "PTV vide", "ptv_charge": "PTV charge"})
    if len(vd) > 5000:
        st.caption(f"5 000 premières lignes sur {len(vd):_} — toutes sont dans l’export Excel.".replace("_", " "))

sans_suivant = ok_d[ok_d["detour_vide"].isna()]
with t_c:
    st.markdown(f"""<ul class="ap-list">
<li><b>{len(ca_seul)}</b> <span>dossiers du CA absents des missions</span></li>
<li><b>{int((~ok_d['dans_ca']).sum())}</b> <span>dossiers des missions absents du CA (pas de prix)</span></li>
<li><b>{int((~d['statut'].eq('ok')).sum())}</b> <span>dossiers sans chargement ou sans déchargement</span></li>
<li><b>{len(sans_suivant):_}</b> <span>dossiers sans dossier suivant pour la même citerne dans les {ecart:g} jours
(fin de période, arrêt, citerne inconnue) : pas de détour à vide calculé</span></li>
<li><b>{int(ok_d['vide_atypique'].sum()):_}</b> <span>trajets à vide atypiques (lavage à plus de 2 × le trajet direct
+ 300 km, souvent une saisie douteuse) : comparés au trajet direct, sans gain compté</span></li>
<li><b>{int(non_geo['lignes'].sum()) if len(non_geo) else 0}</b> <span>lignes de mission non géolocalisées</span></li>
</ul>""".replace("_", " "), unsafe_allow_html=True)
    st.caption("Précision de géolocalisation des arrêts : " + " · ".join(f"{k} {v:_}".replace("_", " ")
                                                                        for k, v in precision.items()))
    if len(non_geo):
        st.dataframe(non_geo, hide_index=True, width="stretch", height=240)


# ─── Export Excel ────────────────────────────────────────────────────────────
def export_excel() -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    navy, blue = "003087", "0057A8"
    fill_cat = {v: PatternFill("solid", fgColor=CAT_FOND[k].lstrip("#")) for k, v in CAT_TXT.items()}
    font_cat = {v: Font(color=CAT_COUL[k].lstrip("#"), bold=True) for k, v in CAT_TXT.items()}

    synth = pd.DataFrame([
        ("Période", payload_carte()["periode"]),
        ("Mode", "À vide (lavage, plein, parking)" if mode == "vide" else "En charge (parking, pompe, relais)"),
        ("Werbomont (lat, lon)", f"{W[0]:.4f}, {W[1]:.4f}"),
        ("Seuils", f"acceptable ≤ {seuils[0]:.0f} km · à vérifier ≤ {seuils[1]:.0f} km · au-delà trop lourd"),
        ("Km", f"PTV quand calculé, sinon vol d'oiseau × {coef:.2f}"),
        ("Affrétés", "exclus" if exclure_aff else "inclus"),
        ("Dossiers calculés", n), ("Acceptables", cnt.get("ok", 0)), ("À vérifier", cnt.get("verif", 0)),
        ("Trop lourds", cnt.get("lourd", 0)), ("Déjà passés par Werbomont", len(deja)),
        ("Méthode à vide", "km(déchargement → W → rechargement suivant même remorque) − km(déchargement → lavage utilisé → rechargement)"),
        ("Méthode en charge", "meilleure insertion de W entre deux arrêts consécutifs du dossier"),
        ("Rentabilité", "prix transport ÷ (km chargés + km à vide du dossier) ; par ligne Σ prix ÷ Σ km"),
        ("Généré le", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], columns=["Élément", "Valeur"])
    L = lignes.drop(columns=["C1_lat", "C1_lon", "Dn_lat", "Dn_lon"]).copy()
    L["categorie"] = L["categorie"].map(CAT_TXT)
    L.columns = ["Ligne", "Départ", "Arrivée", "Client", "Dossiers", "Dossiers calculés", "Multi-points",
                 "Déjà via W", "Prix moyen €", "CA total €", "Km chargés moy.", "Km vide moy.", "Détour médian km",
                 "Détour min km", "Part acceptable", "Renta €/km", "Renta via W €/km", "Écart renta %", "Catégorie"]
    D = ok_d[COLS_DOS].copy()
    D["cat_vide"] = D["cat_vide"].map(CAT_TXT)
    D["cat_charge"] = D["cat_charge"].map(CAT_TXT)
    D.columns = ["Dossier", "Date chargement", "Client", "Départ", "Arrivée", "Multi-points", "Lavage utilisé",
                 "Rechargement suivant", "Dossier suivant", "Remorque", "Chauffeur", "Prix €", "Km chargés",
                 "Km vide actuel", "Km vide via W", "Détour à vide km", "Détour vs direct km", "Détour en charge km",
                 "Tronçon d'insertion", "Activité à W", "Vide atypique", "Renta €/km", "Renta W vide", "Renta W charge",
                 "Cat. à vide", "Cat. en charge", "Km PTV (vide)", "Km PTV (charge)"]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        synth.to_excel(xw, "Synthèse", index=False)
        L.to_excel(xw, "Lignes", index=False)
        D.to_excel(xw, "Dossiers", index=False)
        if len(non_geo):
            non_geo.to_excel(xw, "Non géolocalisés", index=False)
        for ws in xw.book.worksheets:
            for c in ws[1]:
                c.font = Font(color="FFFFFF", bold=True)
                c.fill = PatternFill("solid", fgColor=navy if ws.title != "Synthèse" else blue)
                c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.freeze_panes = "B2" if ws.title in ("Lignes", "Dossiers") else "A2"
            ws.row_dimensions[1].height = 30
            for i, col in enumerate(ws.iter_cols(min_row=1, max_row=min(ws.max_row, 300)), 1):
                larg = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[get_column_letter(i)].width = min(max(10, larg + 2), 60)
            entetes = [c.value for c in ws[1]]
            for j, h in enumerate(entetes, 1):
                h = str(h)
                fmt = ("0.0%" if h == "Part acceptable" else "0.00" if "Renta" in h else
                       "0.0" if "%" in h else "#,##0" if ("km" in h.lower() or "€" in h) else None)
                if h == "Date chargement":
                    fmt = "DD/MM/YYYY"
                if fmt:
                    for row in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                        row[0].number_format = fmt
                if h.startswith("Cat"):
                    for row in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                        v = row[0].value
                        if v in fill_cat:
                            row[0].fill, row[0].font = fill_cat[v], font_cat[v]
            if ws.max_row > 1 and ws.title != "Synthèse":
                ws.auto_filter.ref = ws.dimensions
        xw.book["Synthèse"].column_dimensions["B"].width = 110
    return out.getvalue()


ui.section("Export")
if st.button("Préparer l’export Excel"):
    with st.spinner("Mise en forme du classeur…"):
        st.session_state["wb_xlsx"] = export_excel()
if st.session_state.get("wb_xlsx"):
    st.download_button("Télécharger l’analyse Excel", st.session_state["wb_xlsx"],
                       f"detour_werbomont_{datetime.now():%Y%m%d}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
