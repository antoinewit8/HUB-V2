# Transport Hub · CB Groupe

Outils internes Streamlit (cartes, citernes, planning, rentabilité, utilitaires).

## Lancer

```bash
pip install -r transport_hub/requirements.txt
streamlit run transport_hub/app.py
```

Paquets système (OCR) : `transport_hub/packages.txt`. Thème : `.streamlit/config.toml`.

## Structure

| Chemin | Rôle |
|---|---|
| `transport_hub/app.py` | Point d'entrée : déclare les pages, navigation latérale masquée |
| `transport_hub/accueil.py` | Page d'accueil : tous les outils regroupés par catégorie |
| `transport_hub/core/ui.py` | Registre des outils + habillage commun (typo Apple, cartes, boutons, en-têtes) |
| `transport_hub/outils/` | Un fichier par outil |
| `transport_hub/tools/` | Moteurs de calcul (PTV / KM, TX-FLEX, scrapers gasoil) |
| `transport_hub/map.html` | Carte manuelle (ouverte en plein écran) |
| `transport_hub/assets/` | Logo CB Groupe et photo d'accueil |

## Ajouter un outil

1. Créer `transport_hub/outils/mon_outil.py`, commencer par :
   ```python
   from core import ui
   ui.page("mon_outil")
   ```
2. Ajouter une entrée dans `TOOLS` (`core/ui.py`) : clé, fichier, titre, description, icône, catégorie.
   Il apparaît automatiquement sur l'accueil.

## Secrets / variables d'environnement

`PTV_API_KEY`, `MAP_SERVER_URL` (serveur carte), `FIREBASE_URL` (base des routes du serveur carte).
