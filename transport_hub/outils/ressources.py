import streamlit as st
import json
import os

RESSOURCES_FILE = "ressources.json"

CATEGORIES = {
    "📊 Excel / Google Sheets": "📊",
    "📄 PDF / Word":            "📄",
}

def load():
    if os.path.exists(RESSOURCES_FILE):
        with open(RESSOURCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save(data):
    with open(RESSOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

from core import ui

ui.page("ressources", "Accès rapide aux fichiers et documents partagés.")

st.markdown("""
<style>
.res-card { background: #fff; border-radius: 18px; padding: 16px 18px; box-shadow: var(--ap-shadow);
  transition: transform .18s ease, box-shadow .18s ease; margin-bottom: .5rem; }
.res-card:hover { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(0,0,0,.08), 0 0 0 .5px rgba(0,0,0,.06); }
.res-card a { text-decoration: none; }
.res-title { color: var(--ap-blue) !important; font-size: 17px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
.res-desc  { color: var(--ap-sub) !important; font-size: 14px; margin: .25rem 0 0 0; }
.res-cat   { color: var(--ap-sub); font-size: 12px; font-weight: 500; margin-bottom: .35rem; }
</style>
""", unsafe_allow_html=True)

ressources = load()

# ── Filtres ───────────────────────────────────────────────────
cats_dispo = sorted(set(r["categorie"] for r in ressources)) if ressources else []
filtre = st.selectbox("Filtrer par catégorie", ["Toutes"] + cats_dispo, label_visibility="collapsed") if cats_dispo else "Toutes"

affichees = ressources if filtre == "Toutes" else [r for r in ressources if r["categorie"] == filtre]

# ── Affichage des liens ───────────────────────────────────────
if not affichees:
    st.markdown('<div class="ap-note">Aucune ressource pour le moment : ajoutez-en ci-dessous.</div>', unsafe_allow_html=True)
else:
    cols = st.columns(3)
    for i, r in enumerate(affichees):
        with cols[i % 3]:
            icon = CATEGORIES.get(r["categorie"], "🔗")
            st.markdown(f"""
            <div class="res-card">
                <div class="res-cat">{r['categorie']}</div>
                <a href="{r['url']}" target="_blank">
                    <p class="res-title">{r['nom']}</p>
                </a>
                <p class="res-desc">{r['description']}</p>
            </div>""", unsafe_allow_html=True)
            if st.button("Supprimer", key=f"del_{i}"):
                ressources.remove(r)
                save(ressources)
                st.rerun()

# ── Ajouter une ressource ─────────────────────────────────────
ui.section("Ajouter une ressource")

a1, a2 = st.columns(2)
with a1:
    nom  = st.text_input("Nom du fichier / document", placeholder="ex: Tarif CBS Béton BE")
    url  = st.text_input("Lien URL", placeholder="https://...")
with a2:
    desc = st.text_input("Description courte", placeholder="ex: Grille tarifaire Belgique 2025")
    cat  = st.selectbox("Catégorie", list(CATEGORIES.keys()))

if st.button("Ajouter", use_container_width=False):
    if nom and url:
        ressources.append({"nom": nom, "url": url, "description": desc, "categorie": cat})
        save(ressources)
        st.success(f"« {nom} » ajouté !")
        st.rerun()
    else:
        st.warning("Nom et URL obligatoires.")