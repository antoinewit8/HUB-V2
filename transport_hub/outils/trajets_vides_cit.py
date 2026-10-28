"""
Page Streamlit : Trajets vides CIT
« Je viens de décharger en X : où aller recharger ? »

Les calculs sont dans tools/trajets_vides/engine.py (chaînage par citerne repris de
Détour Werbomont). Cette page : fichiers, choix du point et du rayon, classement,
évaluation d'une destination saisie, carte, export.
"""

import hashlib
import html as _html
import io
import os
import sys

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import ptv, ui  # noqa: E402
from core.duree import excel_heures, fmt_h, vers_jours  # noqa: E402
from tools.trajets_vides import engine as T  # noqa: E402
from tools.werbomont import engine as E  # noqa: E402

ui.page("trajets_vides", "Je viens de décharger en X : où aller recharger pour la meilleure renta ?")

st.markdown("""
<style>
.kpi { background:#fff; border-radius:18px; padding:16px 18px; box-shadow:var(--ap-shadow); margin-bottom:.6rem; }
.kpi .val { font-size:28px; font-weight:600; letter-spacing:-0.02em; color:var(--ap-text); line-height:1.1; }
.kpi .lbl { font-size:13px; color:var(--ap-sub); margin-top:4px; }
.reco { background:#fff; border-radius:18px; padding:14px 18px; box-shadow:var(--ap-shadow);
  display:grid; grid-template-columns:3rem 1fr auto; align-items:center; gap:.9rem; margin-bottom:.6rem; }
.reco.r1 { box-shadow:0 0 0 1.5px #34c759, 0 4px 18px rgba(52,199,89,.12); }
.reco-num { font-size:26px; font-weight:600; color:#c7c7cc; text-align:center; line-height:1; }
.reco.r1 .reco-num { color:#248a3d; }
.reco-loc { font-size:19px; font-weight:600; color:var(--ap-text); }
.reco-sub { font-size:13px; color:var(--ap-sub); margin-top:2px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:.6rem; }
.chip { font-size:12px; font-weight:500; padding:3px 10px; border-radius:980px; }
.chip.green { color:#1e7a34; background:#e8f6ec; } .chip.blue { color:#0060c0; background:#e8f1fc; }
.chip.gray { color:#6e6e73; background:#f0f0f3; } .chip.orange { color:#b25000; background:#fff1e0; }
.badge-best { background:#34c759; color:#fff; font-size:11px; font-weight:600; padding:3px 9px; border-radius:980px; }
</style>
""", unsafe_allow_html=True)


def esc(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def nb(x, dec=0) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:,.{dec}f}".replace(",", " ")


# ─── Fichiers (gardés en mémoire quand on change d'outil) ────────────────────
FICHIERS = {
    "missions": ("Liste des missions (LISTES_MISSIONS)",
                 "Recommandé : remorque de chaque dossier, vraies dates de déchargement, lavages."),
    "ca": ("Chiffre d'affaires citernes (CA CIT)", "Prix des dossiers (renta). Seul, il ne permet pas de chaîner."),
    "lavages": ("Fichier Lavages (dépannage)", "Seulement sans LISTES_MISSIONS : donne la remorque des dossiers lavés."),
}
mem = st.session_state.setdefault("tv_fichiers", {})
# Le fichier d'activités d'Aide planning est un export LISTES_MISSIONS : repris s'il n'y en a pas ici
if "missions" not in mem and "ap_fichier" in st.session_state:
    mem["missions"] = st.session_state["ap_fichier"]
    st.caption(f"Liste des missions reprise d'Aide planning : {mem['missions'][0]}")

cols = st.columns(3)
for col, (cle, (titre, aide)) in zip(cols, FICHIERS.items()):
    with col:
        f = st.file_uploader(titre, type=["xlsx", "xls"], key=f"tv_up_{cle}", help=aide)
        if f is not None:
            mem[cle] = (f.name, f.getvalue())
        elif cle in mem:
            st.caption(f"En mémoire : {mem[cle][0]}")
            if st.button("Retirer", key=f"tv_rm_{cle}"):
                mem.pop(cle, None)
                st.rerun()

if "missions" not in mem and "ca" not in mem:
    st.info("Chargez LISTES_MISSIONS et le CA CIT (ou, à défaut, le CA CIT et le fichier Lavages).")
    st.stop()


def _empreinte(b: bytes | None) -> str:
    return hashlib.md5(b).hexdigest() if b else ""


@st.cache_data(show_spinner=False, max_entries=6)
def _lire(contenu: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(contenu), dtype={"Code postal": str, "C.P. chargement": str,
                                                     "C.P. déchargement": str, "Département": str})


@st.cache_data(show_spinner=False, max_entries=3)
def _dossiers(cles: tuple, _mis: bytes | None, _ca: bytes | None, _lav: bytes | None) -> pd.DataFrame:
    geo = T.adapter_geo(ptv.localiser)
    if _mis:
        return T.dossiers_missions(_lire(_mis), _lire(_ca) if _ca else None, geo)
    return T.dossiers_ca(_lire(_ca), _lire(_lav) if _lav else None, geo)


b_mis = mem.get("missions", (None, None))[1]
b_ca = mem.get("ca", (None, None))[1]
b_lav = mem.get("lavages", (None, None))[1] if not b_mis else None

try:
    with st.spinner("Lecture des fichiers et localisation des lieux…"):
        dossiers = _dossiers((_empreinte(b_mis), _empreinte(b_ca), _empreinte(b_lav)), b_mis, b_ca, b_lav)
except ValueError as e:                     # colonnes manquantes : message lisible
    st.error(f"Fichier non reconnu : {e}")
    st.stop()

mode_missions = bool(b_mis)

# ─── Paramètres ──────────────────────────────────────────────────────────────
ui.section("Point de déchargement")
p1, p2, p3 = st.columns([1, 1, 1])
fenetre = p1.slider("Rechargement dans les (jours)", 1, 14, 3,
                    help="Écart maximal entre le déchargement et le chargement du dossier suivant de la citerne.")
weekend = p2.checkbox("+2 jours si déchargé vendredi ou samedi", value=True)
rayon = p3.slider("Rayon autour du point (km)", 0, 100, 25,
                  help="Tous les déchargements à moins de ce rayon sont pris en compte (Lille, Lomme, Villeneuve-d'Ascq…).")

ench = T.enchainements(dossiers, E.Distances(), fenetre, 2 if weekend else 0)
bilan = T.bilan_chainage(dossiers, ench)

if not mode_missions:
    if not b_lav:
        st.error("Sans LISTES_MISSIONS ni fichier Lavages, aucun véhicule n'est connu : impossible de savoir "
                 "quel dossier suit quel autre. Chargez LISTES_MISSIONS (recommandé).")
        st.stop()
    st.warning(f"Mode dépannage CA + Lavages : seuls les dossiers lavés ont une remorque "
               f"({bilan['dossiers_ok'] - bilan['sans_vehicule']} sur {bilan['dossiers_ok']}). "
               "Un dossier non lavé manque dans la chaîne de sa citerne, et le délai est l'écart entre deux "
               "dates de chargement. Chargez LISTES_MISSIONS pour un résultat fiable.")

if ench.empty:
    st.warning("Aucun enchaînement trouvé avec ces fichiers et cette fenêtre.")
    st.stop()

lieux = T.lieux_dechargement(ench)
point_ext = st.session_state.get("tv_point")          # envoyé par Aide planning
index_defaut = 0
if point_ext and not lieux.empty:
    dist = E.hav(point_ext["lat"], point_ext["lon"], lieux["lat"].to_numpy(), lieux["lon"].to_numpy())
    i = int(np.argmin(dist))
    if dist[i] <= 40:
        index_defaut = i + 1
        st.caption(f"Point repris d'Aide planning : {point_ext.get('nom', '')}")

choix = st.selectbox("Je viens de décharger à…", [""] + lieux["label"].tolist(), index=index_defaut)
if not choix:
    st.info("Choisissez un lieu de déchargement.")
    st.stop()
lieu = lieux.iloc[lieux["label"].tolist().index(choix)]
centre = (float(lieu["lat"]), float(lieu["lon"]))

zone = T.autour(ench, centre, rayon)

with st.expander("Filtres et classement"):
    f1, f2, f3, f4 = st.columns(4)
    pays_dispo = sorted(zone["B_ville"].str.extract(r"\((\w+)\)$", expand=False).dropna().unique())
    pays = f1.multiselect("Pays de rechargement", pays_dispo)
    prix_min = f2.number_input("Prix min. du dossier suivant (€)", value=0, step=50)
    tri = f3.selectbox("Classer par", list(T.TRIS))
    min_freq = f4.number_input("Fréquence min.", 1, 20, 1)
    g1, g2 = st.columns(2)
    nb_recos = g1.selectbox("Nombre de propositions", [5, 10, 15, 20], index=1)
    use_ptv = g2.checkbox("Km à vide routiers PTV pour les 10 premiers", value=ptv.cle_presente(),
                          disabled=not ptv.cle_presente(),
                          help="Distance routière PL depuis le point choisi. Sinon : vol d'oiseau × 1,3.")

cand0 = T.candidats(zone, centre, {"pays": pays, "prix_min": prix_min})
if tri.startswith("Renta") and not cand0.empty and cand0["renta"].isna().all():
    tri = "Fréquence"
    st.caption("Pas de prix (CA absent ou sans correspondance) : classement par fréquence.")
cand = T.classer(cand0, tri, int(min_freq))
if cand.empty:
    st.warning("Aucun rechargement connu depuis cette zone avec ces filtres. Élargissez le rayon ou la fenêtre.")
    st.stop()
top = cand.head(nb_recos).copy()

if use_ptv:
    with st.spinner("Distances routières PTV…"):
        res = ptv.km_ptv_lot([(centre, (la, lo)) for la, lo in zip(top["lat"].head(10), top["lon"].head(10))])
    top["km_ptv"] = [res.get((centre, (la, lo))) if i < 10 else np.nan
                     for i, (la, lo) in enumerate(zip(top["lat"], top["lon"]))]
else:
    top["km_ptv"] = np.nan

# ─── Synthèse ───────────────────────────────────────────────────────────────
ui.section(f"Après un déchargement à {lieu['A_ville']} (± {rayon} km)")
tot = zone["km_vide"].fillna(0) + zone["km_charge_suivant"].fillna(0)
okp = zone["prix_suivant"].notna() & (tot > 0)
renta_zone = zone.loc[okp, "prix_suivant"].sum() / tot[okp].sum() if okp.any() else np.nan
k1, k2, k3, k4 = st.columns(4)
for col, (val, lbl) in zip((k1, k2, k3, k4), (
        (nb(len(zone)), "Enchaînements dans la zone"),
        (nb(zone["citerne"].nunique()), "Citernes"),
        (f"{nb(zone['km_vide'].median())} km", "Km à vide médian"),
        (f"{nb(renta_zone, 2)} €/km" if pd.notna(renta_zone) else "—", "Renta moyenne de la zone"))):
    col.markdown(f'<div class="kpi"><div class="val">{val}</div><div class="lbl">{lbl}</div></div>',
                 unsafe_allow_html=True)
st.caption("Renta = prix du dossier suivant ÷ (km à vide, lavage compris + km chargés), rapport des sommes. "
           "Km estimés au vol d'oiseau × 1,3" + (", km à vide PTV affiché en plus pour les 10 premiers." if use_ptv else "."))

for _, r in top.iterrows():
    rang = int(r["rang"])
    cls = "r1" if rang == 1 else ""
    vide_txt = f"{nb(r['km_vide_moyen'])} km à vide"
    if pd.notna(r.get("km_ptv")):
        vide_txt += f" · {nb(r['km_ptv'])} km PTV depuis le point"
    lav = f" · lavage {nb(r['part_lavage'] * 100)} %" if r["part_lavage"] > 0 else ""
    sous = " · ".join(v for v in (r["clients"], r["produits"]) if v) or "—"
    st.markdown(f"""
    <div class="reco {cls}">
      <div class="reco-num">{rang:02d}</div>
      <div>
        <div class="reco-loc">{esc(r['lieu'])}</div>
        <div class="reco-sub">{esc(sous)}</div>
        <div class="chips">
          <span class="chip green">{nb(r['renta'], 2)} €/km</span>
          <span class="chip blue">{esc(vide_txt)}{esc(lav)}</span>
          <span class="chip gray">rechargé en {fmt_h(r['ecart_h_median'])} (médiane)</span>
          <span class="chip orange">{int(r['frequence'])}× · {int(r['citernes'])} citerne(s)</span>
          <span class="chip gray">prix moyen {nb(r['prix_moyen'])} €</span>
        </div>
      </div>
      {'<span class="badge-best">MEILLEURE RENTA</span>' if rang == 1 and tri.startswith("Renta") else ''}
    </div>""", unsafe_allow_html=True)

# ─── Destination saisie ─────────────────────────────────────────────────────
ui.section("Évaluer une destination")
st.caption("Le chauffeur doit recharger ailleurs ? Saisissez le lieu : km à vide depuis le point choisi, "
           "historique de ce rechargement, et renta si vous connaissez le prix et la livraison.")
m1, m2, m3 = st.columns([3, 1, 1])
dest = m1.text_input("Lieu de rechargement", placeholder="ex. Béziers, Rouen, Liège…")
dest_cp = m2.text_input("Code postal", key="tv_dest_cp")
dest_pays = m3.selectbox("Pays", ["F", "B", "NL", "D", "L", "E", "I", "CH", "A", "GB", "PL"])
n1, n2, n3, n4 = st.columns([1, 2, 1, 1])
prix_saisi = n1.number_input("Prix proposé (€)", value=0, step=50)
liv = n2.text_input("Livraison prévue (facultatif)", placeholder="ville")
liv_cp = n3.text_input("CP livraison")
liv_pays = n4.selectbox("Pays livraison", ["F", "B", "NL", "D", "L", "E", "I", "CH", "A", "GB", "PL"], key="tv_liv_pays")

if dest:
    pB = ptv.localiser(dest_pays, dest_cp, dest)
    if not pB:
        st.warning(f"Lieu « {dest} » introuvable : vérifiez le code postal et le pays.")
    else:
        pL = ptv.localiser(liv_pays, liv_cp, liv) if liv else None
        B, L = (pB["lat"], pB["lon"]), ((pL["lat"], pL["lon"]) if pL else None)
        kv = ptv.km_ptv(centre, B) if ptv.cle_presente() else None
        kc = ptv.km_ptv(B, L) if (L and ptv.cle_presente()) else None
        ev = T.evaluer(zone, centre, B, prix=prix_saisi or None, point_livraison=L, km_vide_ptv=kv, km_charge_ptv=kc)
        if pB.get("note"):
            st.caption(f"Localisation : {pB['note']}")
        e1, e2, e3 = st.columns(3)
        e1.metric("Km à vide depuis le point", f"{nb(ev['km_vide'])} km", help=ev["source_km"])
        e2.metric("Déjà fait depuis cette zone", f"{ev['historique']} fois")
        if "renta_estimee" in ev:
            e3.metric("Renta estimée", f"{nb(ev['renta_estimee'], 2)} €/km",
                      help=f"{nb(prix_saisi)} € ÷ ({nb(ev['km_vide'])} km à vide + {nb(ev['km_charge'])} km chargés)")
        elif ev["historique"]:
            e3.metric("Renta historique", f"{nb(ev.get('renta_hist'), 2)} €/km")
        if ev["historique"]:
            st.caption(f"Historique : prix moyen {nb(ev.get('prix_moyen'))} €, rechargé en "
                       f"{fmt_h(ev.get('ecart_h_median'))} (médiane).")
        ref = ev.get("renta_estimee", ev.get("renta_hist"))
        if ref is not None and pd.notna(ref) and cand["renta"].notna().any():
            rang = int((cand["renta"] > ref).sum()) + 1
            st.info(f"Avec cette renta, la destination serait au rang **{rang}** sur {len(cand)} "
                    "rechargements connus depuis la zone.")
        elif not ev["historique"]:
            st.info("Pas d'historique depuis cette zone : indiquez le prix et la livraison pour estimer la renta.")

# ─── Carte ──────────────────────────────────────────────────────────────────
ui.section("Carte")
try:
    import pydeck as pdk
    dfm = top.assign(nom=top["lieu"], couleur=[[52, 199, 89, 235] if r == 1 else ([0, 113, 227, 220] if r <= 3
                                                                                   else [142, 142, 147, 190])
                                               for r in top["rang"]],
                     renta_txt=top["renta"].map(lambda v: f"{nb(v, 2)} €/km"),
                     vide_txt=top["km_vide_moyen"].map(lambda v: f"{nb(v)} km"))
    zone_df = pd.DataFrame([{"lat": centre[0], "lon": centre[1], "nom": f"Déchargement : {lieu['A_ville']}",
                             "r": max(rayon, 1) * 1000}])
    deck = pdk.Deck(
        layers=[
            pdk.Layer("ScatterplotLayer", data=zone_df, get_position="[lon, lat]", get_radius="r",
                      get_fill_color=[255, 59, 48, 30], get_line_color=[255, 59, 48, 160], stroked=True,
                      line_width_min_pixels=1),
            pdk.Layer("ScatterplotLayer", data=zone_df, get_position="[lon, lat]", get_radius=2500,
                      get_fill_color=[255, 59, 48, 240], pickable=True),
            pdk.Layer("ScatterplotLayer", data=dfm, get_position="[lon, lat]", get_radius=2200,
                      radius_min_pixels=5, get_fill_color="couleur", get_line_color=[255, 255, 255, 230],
                      stroked=True, line_width_min_pixels=1, pickable=True),
            pdk.Layer("TextLayer", data=dfm, get_position="[lon, lat]", get_text="nom", get_size=12,
                      get_color=[29, 29, 31, 230], get_pixel_offset=[0, -14]),
        ],
        initial_view_state=pdk.ViewState(latitude=centre[0], longitude=centre[1], zoom=5.5),
        tooltip={"html": "<b>{nom}</b><br>{renta_txt} · {vide_txt}"},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )
    st.pydeck_chart(deck, height=520)
except ImportError:
    st.map(top.rename(columns={"lat": "latitude", "lon": "longitude"}))

# ─── Tableaux + export ──────────────────────────────────────────────────────
tab = cand.rename(columns={
    "rang": "Rang", "lieu": "Lieu de rechargement", "frequence": "Fréquence", "citernes": "Citernes",
    "renta": "Renta (€/km)", "km_vide_moyen": "Km à vide moyen", "part_lavage": "Part avec lavage",
    "ecart_h_median": "Rechargé en (médiane)", "prix_moyen": "Prix moyen (€)",
    "km_charge_moyen": "Km chargés moyen", "dernier": "Dernière fois", "clients": "Clients",
    "produits": "Produits", "chauffeurs": "Chauffeurs"})[
    ["Rang", "Lieu de rechargement", "Renta (€/km)", "Fréquence", "Citernes", "Km à vide moyen",
     "Part avec lavage", "Rechargé en (médiane)", "Prix moyen (€)", "Km chargés moyen", "Dernière fois",
     "Clients", "Produits", "Chauffeurs"]]
detail = zone.rename(columns={
    "dossier": "Dossier déchargé", "A_ville": "Déchargé à", "A_dt": "Déchargé le",
    "dossier_suivant": "Dossier suivant", "B_ville": "Rechargé à", "B_dt": "Rechargé le",
    "ecart_h": "Écart", "km_vide": "Km à vide", "lavage_noms": "Lavage", "prix_suivant": "Prix suivant (€)",
    "km_charge_suivant": "Km chargés suivant", "renta": "Renta (€/km)", "remorque": "Remorque",
    "tracteur": "Tracteur", "chauffeur": "Chauffeur", "client_suivant": "Client suivant"})[
    ["Dossier déchargé", "Déchargé à", "Déchargé le", "Dossier suivant", "Rechargé à", "Rechargé le",
     "Écart", "Km à vide", "Lavage", "Prix suivant (€)", "Km chargés suivant", "Renta (€/km)",
     "Remorque", "Tracteur", "Chauffeur", "Client suivant"]].sort_values("Déchargé le")

with st.expander(f"Tous les rechargements ({len(tab)}) et enchaînements ({len(detail)})"):
    st.dataframe(tab.style.format({"Rechargé en (médiane)": fmt_h}, na_rep="—"), hide_index=True, width="stretch",
                 column_config={"Renta (€/km)": st.column_config.NumberColumn(format="%.2f"),
                                "Part avec lavage": st.column_config.NumberColumn(format="percent"),
                                "Km à vide moyen": st.column_config.NumberColumn(format="%.0f"),
                                "Prix moyen (€)": st.column_config.NumberColumn(format="%.0f"),
                                "Km chargés moyen": st.column_config.NumberColumn(format="%.0f")})
    st.dataframe(detail.style.format({"Écart": fmt_h}, na_rep="—"), hide_index=True, width="stretch")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"Paramètre": ["Déchargement", "Rayon (km)", "Fenêtre (jours)", "+2 j week-end", "Source",
                                    "Km", "Renta"],
                      "Valeur": [lieu["A_ville"], rayon, fenetre, weekend,
                                 "LISTES_MISSIONS + CA" if mode_missions else "CA + Lavages (dépannage)",
                                 "vol d'oiseau × 1,3 (lavages compris)",
                                 "prix suivant ÷ (km vide + km chargés), rapport des sommes"]}
                     ).to_excel(xw, sheet_name="Paramètres", index=False)
        # Durées Excel (format [h] h mm) : triables et calculables, affichées « 7 h 40 »
        for nom, df_x, col in (("Rechargements", tab, "Rechargé en (médiane)"), ("Enchaînements", detail, "Écart")):
            x = df_x.copy()
            x[col] = vers_jours(x[col])
            x.to_excel(xw, sheet_name=nom, index=False)
            excel_heures(xw.sheets[nom], x, [col])
    st.download_button("Exporter Excel", data=buf.getvalue(),
                       file_name=f"rechargements_{E.norm_txt(lieu['A_ville']).replace(' ', '_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("Données utilisées"):
    st.markdown(
        f"- Source : **{'LISTES_MISSIONS' + (' + CA' if b_ca else ' (sans CA : pas de prix)') if mode_missions else 'CA + Lavages (dépannage)'}**\n"
        f"- {nb(bilan['dossiers'])} dossiers, {nb(bilan['enchainements'])} enchaînements "
        f"(dossier suivant de la même citerne dans la fenêtre)\n"
        f"- Exclus du chaînage : {nb(bilan['affretes'])} dossiers affrétés, {nb(bilan['sans_vehicule'])} sans véhicule"
        + (f", {nb(bilan['sans_coord'])} lieux non localisés" if bilan["sans_coord"] else ""))
    if mode_missions and not b_ca:
        st.caption("Sans le CA, les prix manquent : classement par renta impossible, utilisez la fréquence ou les km à vide.")
