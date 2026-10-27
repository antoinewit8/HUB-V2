"""
Carte Manuelle — la carte s'ouvre dans un nouvel onglet, en plein écran.

La page du HUB ne sert plus qu'à lancer la carte : un bouton ouvre map.html
seul dans un nouvel onglet, sans rien de Streamlit autour (même système que
l'Optimisateur Lavages CIT). Le départ, l'arrivée, les étapes et les options
se définissent toujours directement dans map.html.

Option « Pompes Total (ma liste) » : la liste de la page Pompes carburant
(tools/pompes/favorites.py) est injectée dans la carte, avec le prix du gazole
officiel en France quand il répond ; la carte affiche celles le long du trajet.
"""

import json
import os
import threading
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from jinja2 import Template

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
MAP_SERVER_URL = os.environ.get("MAP_SERVER_URL", "https://cartes-bot.onrender.com").rstrip("/")

from core import parallele as par
from core import ui
from tools.pompes.favorites import fichier_favorites, favorites_depuis, prix_france, lier_prix_france

ui.page_config(ui.TOOLS_BY_KEY["carte_manuelle"]["title"])


def reveiller_serveur(url: str):
    """Render endort le serveur carte sur le plan gratuit. On le réveille en
    tâche de fond : la page s'affiche tout de suite au lieu d'attendre jusqu'à
    une minute derrière un sablier. La carte relance aussi ce réveil à
    l'ouverture et le garde éveillé tant qu'elle est ouverte."""
    def _ping():
        try:
            requests.get(f"{url}/health", timeout=60)
        except requests.RequestException:
            pass
    threading.Thread(target=_ping, daemon=True).start()


def bouton_ouvrir(page_html: str):
    """Bouton qui ouvre la carte seule dans un nouvel onglet (page autonome, sans Streamlit autour)."""
    contenu = json.dumps(page_html).replace("</", "<\\/")
    components.html(f"""
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif; }}
  button {{ height: 48px; padding: 0 28px; border: none; border-radius: 980px; background: #0071e3; color: #fff;
           font: 500 17px -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif;
           cursor: pointer; transition: background .15s, transform .1s; }}
  button:hover {{ background: #0077ed; }}
  button:active {{ transform: scale(.98); }}
  p {{ margin: 10px 0 0 4px; font-size: 13px; color: #6e6e73; }}
</style>
<button id="ouvrir">Ouvrir la carte plein écran</button>
<p id="msg">S’ouvre dans un nouvel onglet.</p>
<script>
const PAGE = {contenu};
document.getElementById('ouvrir').addEventListener('click', () => {{
  const url = URL.createObjectURL(new Blob([PAGE], {{ type: 'text/html' }}));
  const w = window.open(url, '_blank');
  document.getElementById('msg').textContent = w
    ? 'Carte ouverte dans un nouvel onglet. Recliquez pour en ouvrir une autre.'
    : 'Le navigateur a bloqué l’ouverture : autorisez les fenêtres pop-up pour le HUB, ou téléchargez la carte ci-dessous.';
}});
</script>
""", height=90)


@st.cache_resource(show_spinner=False)
def _limites_admin() -> str:
    """Limites et numéros des départements français (GeoJSON compact, ~350 Ko).
    Injecté tel quel dans map.html : la carte est ouverte depuis un blob,
    elle ne peut pas charger de fichier relatif. "null" si le fichier manque."""
    p = Path(__file__).parent.parent / "assets" / "limites_admin.geojson"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "null"


def _pompes(avec_prix: bool) -> tuple[list, str]:
    """Ma liste de pompes (compacte) pour l'option de la carte, et une remarque éventuelle."""
    src = fichier_favorites()
    if src is None:
        return [], ""
    try:
        stations, _ = favorites_depuis(str(src), src.stat().st_mtime)
    except Exception as e:  # noqa: BLE001
        return [], f"Liste de pompes illisible ({e})."
    note = ""
    if avec_prix:
        try:
            lier_prix_france(stations, prix_france())
        except Exception:  # noqa: BLE001
            note = "Prix du gazole indisponibles pour le moment : les pompes s’affichent sans prix."
    cles = ("n", "e", "a", "cp", "v", "p", "la", "lo", "pl", "pln", "code", "px", "pxm")
    return [{k: s.get(k) for k in cles if s.get(k) not in (None, "")} for s in stations], note


# ─── Page ────────────────────────────────────────────────────────────────────
ui.page("carte_manuelle", "Itinéraires poids lourds, péages et kilomètres par pays, traversées. La carte s’ouvre en plein écran dans un nouvel onglet.")

reveiller_serveur(MAP_SERVER_URL)

@st.cache_resource(show_spinner=False)
def _template(mtime: float) -> Template:
    return Template((Path(__file__).parent.parent / "map.html").read_text(encoding="utf-8"))


try:
    template = _template((Path(__file__).parent.parent / "map.html").stat().st_mtime)
except FileNotFoundError:
    st.error("map.html introuvable à la racine du projet.")
    st.stop()
except Exception as e:
    st.error(f"Erreur chargement map.html : {e}")
    st.stop()

limites = _limites_admin()


def rendre(pompes: list) -> str:
    # Carte vide : map.html gère lui-même départ, arrivée, étapes et options.
    return template.render(
        route={"origin": "", "dest": "", "polyline": []},
        route_id="manual",
        server_url=MAP_SERVER_URL,
        limites_admin=limites,
        pompes=json.dumps(pompes, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    )


# Prix du gazole demandés en parallèle : déjà en cache (cas courant) → une seule carte envoyée.
# Sinon, carte avec mes pompes sans prix tout de suite, remplacée quand les prix arrivent.
zone_bouton = st.empty()
f_prix = par.lancer(_pompes, True)
if par.attendre([f_prix], 1.5):
    pompes, note_pompes = par.resultat(f_prix) or _pompes(avec_prix=False)
else:
    pompes, _ = _pompes(avec_prix=False)
    try:
        with zone_bouton.container():
            bouton_ouvrir(rendre(pompes))
    except Exception as e:
        st.error(f"Erreur chargement map.html : {e}")
        st.stop()
    par.attendre([f_prix])
    pompes_px, note_pompes = par.resultat(f_prix) or ([], "")
    if any("px" in s for s in pompes_px):
        pompes = pompes_px
try:
    html_final = rendre(pompes)
except Exception as e:
    st.error(f"Erreur chargement map.html : {e}")
    st.stop()
with zone_bouton.container():
    bouton_ouvrir(html_final)
if note_pompes:
    st.caption(note_pompes)


st.write("")
c1, _ = st.columns([1, 2])
with c1:
    # fichier préparé seulement au clic (plus de 700 Ko qui ne repartent plus à chaque affichage)
    st.download_button("Télécharger la carte (HTML)", lambda: html_final.encode("utf-8"), on_click="ignore",
                       file_name="carte_manuelle.html", mime="text/html", use_container_width=True)
st.caption("Le fichier HTML s’ouvre dans n’importe quel navigateur, sans le HUB. "
           "Il utilise le même serveur carte pour les calculs.")

st.markdown('<div class="ap-section">Dans la carte</div>', unsafe_allow_html=True)
st.markdown(
    '<ul class="ap-list">'
    '<li><b>Départ et arrivée</b> <span>: tapez une adresse ou des coordonnées, ou cliquez sur la carte.</span></li>'
    '<li><b>Étapes</b> <span>: entre le départ et l’arrivée — « Ajouter une étape », clic droit sur la carte ou recherche d’adresse. Les flèches au survol changent l’ordre ; une étape peut devenir le départ ou l’arrivée.</span></li>'
    '<li><b>Distance et péage</b> <span>: un clic sur la case affiche le détail par pays.</span></li>'
    '<li><b>Traversées</b> <span>: choisissez la ligne de ferry ou de navette dans le bloc dédié.</span></li>'
    '<li><b>Pompes Total</b> <span>: dans Options, « Pompes Total (ma liste) » affiche la liste de la page Pompes carburant ; avec un trajet, celles à moins de 2 à 20 km du tracé sont numérotées dans l’ordre de passage, avec le prix du gazole en France.</span></li>'
    '<li><b>Plan ou Satellite</b> <span>: dans la barre en bas de la carte, avec les types de routes et les restrictions PL.</span></li>'
    '</ul>',
    unsafe_allow_html=True,
)
