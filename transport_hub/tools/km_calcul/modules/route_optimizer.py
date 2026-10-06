"""
Logique d'optimisation de route "Super Préférentielle".
Gère l'injection de waypoints de contournement et les paramètres d'évitement.
 
Priorité appliquée :
  1. Les routes manuelles (routes_preferentielles.json) sont appliquées en amont
     dans main_km.py via get_waypoints() — ce module ne les gère pas.
  2. Ce module demande ensuite à PTV d'éviter les péages sur tous les trajets.
     PTV reste libre de choisir le meilleur itinéraire (Suisse, tunnels, etc.)
"""
 
def get_super_pref_logic(lat_start, lon_start, lat_end, lon_end):
    """
    Détermine les waypoints à ajouter et les éléments à éviter pour le mode Super.
    
    - Aucun waypoint géographique forcé : PTV choisit librement le meilleur trajet.
    - Évitement des péages activé sur tous les trajets.
    """
    extra_waypoints = []
    avoid_features  = ["TOLL"]
 
    return extra_waypoints, avoid_features
