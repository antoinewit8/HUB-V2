"""
Villes-jalons automatiques pour forcer les axes routiers PL.
Si le trajet passe à moins de 35km d'une ville-jalon, elle devient waypoint.
"""
import math

# ==========================================
# VILLES-JALONS (lat, lon)
# ==========================================

VILLES_JALONS = {
    # Sud / Massif Central (points sur N88, A75, RN)
    "Puy-en-Velay":     (45.0430,  3.9020),   # N88 échangeur est (D103)
    "Mende":            (44.5290,  3.4980),   # N88 nord Mende
    "Rodez":            (44.3580,  2.5420),   # RN88 échangeur Onet-le-Château
    "Issoire":          (45.5440,  3.2490),   # A75 - ancre axe Massif Central → Nord

    # Ouest (points sur N171, N162, A81)
    "Châteaubriant":    (47.7050, -1.4020),   # N171 échangeur ouest
    "Mayenne":          (48.3010, -0.6580),   # N162 échangeur nord
    "Laval":            (48.0640, -0.8020),   # A81 échangeur Laval ouest
    "Le Mans":          (48.0180,  0.1650),   # A11 échangeur ouest (sortie 8)
    "Tours":            (47.3750,  0.7050),   # A10/A85 échangeur
    "Angers":           (47.5100, -0.5350),   # A11 échangeur nord

    # Normandie / N12
    "Alençon":          (48.4250,  0.0650),   # N12 échangeur ouest
    "Argentan":         (48.7380, -0.0050),   # N26 échangeur
    "Dreux":            (48.7250,  1.3900),   # N12 contournement sud

    # Nord (points sur A1, A26, N2, N44)
    "Amiens":           (49.8920,  2.2650),   # A16/A29 Amiens-ouest
    "Albert":           (50.0050,  2.6350),   # D929/N29 contournement
    "Bapaume":          (50.1100,  2.8550),   # A1 sortie Bapaume
    "Cambrai":          (50.1900,  3.2100),   # A26 échangeur
    "Laon":             (49.5780,  3.6450),   # N2 contournement est
    "Soissons":         (49.3700,  3.3450),   # N2 contournement sud

    # Axe Vosges/Lorraine → Sud-Ouest (A6/Saône puis N des Massifs)
    "Chalon-sur-Saône": (46.7810,  4.8520),   # A6/N6 carrefour Bourgogne→Sud
    "Aurillac":         (44.9280,  2.4400),   # N122 Cantal→Quercy axe gratuit

    # Normandie → Nord-Est (axes gratuits N154/N31 pour éviter autoroutes Paris)
    "Évreux":           (49.0050,  1.1520),   # N154 échangeur sud
    "Beauvais":         (49.4330,  2.1200),   # N31 échangeur est
    "Compiègne":        (49.3900,  2.8650),   # N31/A1 échangeur
    "Chartres":         (48.4800,  1.5050),   # N10 échangeur nord
    "Nogent-le-Rotrou": (48.3220,  0.8260),   # N23 entre Chartres et Le Mans

    # Ardennes / Avesnois
    "Vouziers":         (49.3850,  4.6850),   # D946 contournement
    "Hirson":           (49.9230,  4.0830),   # N2/D1029 - évite A26 pour Ardennes
    "Avesnes-sur-Helpe":(50.1240,  3.9310),   # D932 Avesnois - axe direct Cambrai→Ardennes
    "Maubeuge":         (50.2790,  3.9730),   # N2 - axe Belgique évite A26
    "Sedan":            (49.7030,  4.9400),   # N43 - axe Lorraine→Ardennes

    # Est (points sur A31, A4, N4)
    "Commercy":         (48.7550,  5.5700),   # N4 contournement
    "Nancy":            (48.6580,  6.1730),   # A31 échangeur Nancy-sud
    "Metz":             (49.1050,  6.1900),   # A31/A4 échangeur Metz-sud
    "Verdun":           (49.1750,  5.3650),   # N3/A4 échangeur
    "Épinal":           (48.1850,  6.4350),   # N57 contournement
    "Chaumont":         (48.1050,  5.1200),   # N67 contournement

    # Centre / Champagne
    "Troyes":           (48.2450,  4.0620),   # A26/A5 échangeur Troyes-sud
    "Orléans":          (47.9690,  1.9090),   # A10 sortie 15 Saran
    "Châlons-en-Champagne": (48.9580, 4.3660), # A26/A4 carrefour Champagne

    # ── AJOUTS : axes Vosges ↔ ouest (N57/N4) ──
    "Vesoul":           (47.6240,  6.1550),   # N57/N19 contournement
    "Langres":          (47.8650,  5.3350),   # N19/A31 échangeur

    # ── AJOUTS : axes Champagne / nord-est ──
    "Reims-sud":        (49.2000,  4.0500),   # A4/A26 échangeur Reims-sud
    "Saint-Quentin":    (49.8400,  3.2800),   # A26/A29 échangeur

    # ── AJOUTS : axe nord ↔ ouest via Normandie (A29/A28) ──
    "Rouen":            (49.4430,  1.0990),   # A28/A29/A13 échangeur

    # ── AJOUTS : Bretagne / N12-N137 ──
    "Rennes":           (48.0830, -1.6800),   # N12/N137/N157 échangeur
    "Vitré":            (48.1240, -1.2100),   # A81 sortie

    # ── AJOUTS : axe N145/A20 (Cantal/Limousin ↔ ouest) ──
    "Limoges":          (45.8800,  1.2650),   # A20 échangeur nord
    "La Souterraine":   (46.2250,  1.4820),   # N145 échangeur
    "Bellac":           (46.1230,  1.0480),   # N147 contournement
    "Tulle":            (45.2700,  1.7750),   # A89 échangeur

    # ── AJOUTS : axe N10/N137 (Bretagne ↔ sud-ouest) ──
    "Poitiers":         (46.6050,  0.3550),   # A10 échangeur nord
    "Niort":            (46.3230, -0.4640),   # A83/A10 échangeur
    "Angoulême":        (45.6480,  0.1560),   # N10 contournement

    # ── AJOUTS : axe N20/A20 (sud-ouest) ──
    "Cahors":           (44.4600,  1.4500),   # A20 échangeur
    "Brive":            (45.1700,  1.5450),   # A20/A89 échangeur

    # ── AJOUTS : axe Jura (N5/N57) Haute-Savoie ↔ Vosges ──
    "Champagnole":      (46.7450,  5.9130),   # N5 jurassienne
    "Pontarlier":       (46.9050,  6.3550),   # N57 contournement
}

# ==========================================
# AXES STRATÉGIQUES
# ==========================================

AXE_N12 = ["Dreux", "Alençon", "Mayenne", "Laval"]
AXE_N2  = ["Soissons", "Laon", "Cambrai"]

# Nouveaux axes : ordre = sens de parcours géographique
AXE_NORD_OUEST    = ["Saint-Quentin", "Amiens", "Rouen", "Alençon", "Mayenne"]
AXE_VOSGES_OUEST  = ["Vesoul", "Langres", "Troyes", "Orléans", "Chartres", "Nogent-le-Rotrou", "Le Mans"]
AXE_VOSGES_SUD_OUEST = ["Chalon-sur-Saône", "Issoire", "Aurillac"]
AXE_LIMOUSIN      = ["Tulle", "Limoges", "La Souterraine", "Poitiers"]
AXE_N88           = ["Puy-en-Velay", "Mende", "Rodez", "Cahors"]

# Axe Massif Central est (Aveyron/Cantal) → Grand Ouest Bretagne/Vendée : force A75 + Tours/Angers
AXE_MASSIF_CENTRAL_OUEST     = ["Issoire", "Tours", "Angers"]

# Axe Massif Central est (Aveyron/Cantal) → Normandie : force A75 + Orléans/Le Mans/Alençon
# Évite le détour absurde via Tours→Rennes pour les destinations Manche/Calvados/Orne
AXE_MASSIF_CENTRAL_NORMANDIE = ["Issoire", "Orléans", "Le Mans", "Alençon"]

# Axe Ardennes/Avesnois : force les routes locales pour les Ardennes et le Hainaut
AXE_ARDENNES_AVESNOIS = ["Hirson", "Avesnes-sur-Helpe", "Maubeuge"]

# Axe Ouest (Bretagne/Normandie) → Nord-Est (Ardennes/Hainaut) : force N154/N31 gratuits
AXE_OUEST_NORD_EST = ["Évreux", "Beauvais", "Compiègne"]

RAYON_DETECTION_KM = 10        # détection auto par projection : strict pour éviter les faux positifs
RAYON_AXE_FORCE_KM = 45        # axes forcés : large pour couvrir les corridors qui font détour
MAX_WAYPOINTS      = 6         # max waypoints retournés (PTV gère mal les longues listes)


# ==========================================
# HAVERSINE
# ==========================================
def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ==========================================
# DISTANCE POINT → SEGMENT
# ==========================================
def _distance_point_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _haversine(px, py, ax, ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    proj_lat = ax + t * dx
    proj_lon = ay + t * dy
    return _haversine(px, py, proj_lat, proj_lon)


# ==========================================
# DÉTECTION AXES
# ==========================================
def _is_east_west(lat_start, lon_start, lat_end, lon_end) -> bool:
    lat_moy = (lat_start + lat_end) / 2
    delta_lon = abs(lon_end - lon_start)
    delta_lat = abs(lat_end - lat_start)
    return (47.5 <= lat_moy <= 49.5
            and delta_lon > 2.0
            and delta_lon > delta_lat * 1.5)


def _is_north_axis(lat_start, lon_start, lat_end, lon_end) -> bool:
    """
    Trajet à composante nord ET nettement vers l'ouest.
    Resserré pour ne plus se déclencher sur Lille→Strasbourg ou PETIT FAYT→Italie.
    """
    lat_max = max(lat_start, lat_end)
    delta_lon = lon_end - lon_start  # signé : positif = vers l'est, négatif = vers l'ouest
    return lat_max >= 49.0 and abs(delta_lon) > 2.0 and (
        min(lon_start, lon_end) <= 0.5
    )


def _is_nord_to_ouest(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_nord_est(lat, lon):
        return lat >= 49.0 and lon >= 3.5

    def is_ouest(lat, lon):
        if not (lon <= -0.5 and 47.0 <= lat <= 49.5): return False
        if lat > 48.5 and lon > -1.5: return False
        return True

    if not (is_ouest(lat_start, lon_start) and is_nord_est(lat_end, lon_end)):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 350


def _is_vosges_to_ouest(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_est(lat, lon):
        return lon >= 5.8 and 47.0 <= lat <= 49.0

    def is_ouest(lat, lon):
        return lon <= -0.5 and 47.0 <= lat <= 49.5

    if not ((is_est(lat_start, lon_start) and is_ouest(lat_end, lon_end))
            or (is_est(lat_end, lon_end) and is_ouest(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 350


def _is_limousin_axis(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_sud(lat, lon):
        return 44.0 <= lat <= 45.7 and 1.5 <= lon <= 3.5

    def is_nord_ouest(lat, lon):
        return lat >= 47.5 and lon <= 0.0

    if not ((is_sud(lat_start, lon_start) and is_nord_ouest(lat_end, lon_end))
            or (is_sud(lat_end, lon_end) and is_nord_ouest(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 350


def _is_massif_central_to_ouest(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_massif_est(lat, lon):
        return 44.0 <= lat <= 46.0 and 2.0 <= lon <= 4.5

    def is_grand_ouest(lat, lon):
        return lon <= 0.5 and lat >= 47.0

    if not ((is_massif_est(lat_start, lon_start) and is_grand_ouest(lat_end, lon_end))
            or (is_massif_est(lat_end, lon_end) and is_grand_ouest(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 350


def _is_ouest_to_nord_est(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_ouest_sud(lat, lon):
        return lon < -0.5 and 47.0 <= lat <= 49.0

    def is_nord_est(lat, lon):
        return lat >= 49.5 and lon >= 3.0

    depart_ouest = is_ouest_sud(lat_start, lon_start) and is_nord_est(lat_end, lon_end)
    depart_nord_est = is_nord_est(lat_start, lon_start) and is_ouest_sud(lat_end, lon_end)
    if not (depart_ouest or depart_nord_est):
        return False
    if depart_nord_est:
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 300


def _is_ardennes_avesnois(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_ardennes(lat, lon):
        return 49.5 <= lat <= 50.6 and 3.5 <= lon <= 5.5

    def is_outside_ardennes(lat, lon):
        return not is_ardennes(lat, lon)

    if not ((is_ardennes(lat_start, lon_start) and is_outside_ardennes(lat_end, lon_end))
            or (is_ardennes(lat_end, lon_end) and is_outside_ardennes(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 80


def _is_vosges_to_sud_ouest(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_vosges_est(lat, lon):
        return lon >= 6.3 and 47.0 <= lat <= 49.0

    def is_sud_ouest(lat, lon):
        return 41.0 <= lat <= 46.5 and lon <= 3.5

    if not ((is_vosges_est(lat_start, lon_start) and is_sud_ouest(lat_end, lon_end))
            or (is_vosges_est(lat_end, lon_end) and is_sud_ouest(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 400


def _is_n88_axis(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_loire_auvergne(lat, lon):
        return 45.0 <= lat <= 46.2 and 3.5 <= lon <= 5.0

    def is_sud_ouest(lat, lon):
        return 43.5 <= lat <= 44.8 and 0.5 <= lon <= 2.5

    if not ((is_loire_auvergne(lat_start, lon_start) and is_sud_ouest(lat_end, lon_end))
            or (is_loire_auvergne(lat_end, lon_end) and is_sud_ouest(lat_start, lon_start))):
        return False
    return _haversine(lat_start, lon_start, lat_end, lon_end) >= 250


# ==========================================
# DESTINATION NORMANDIE ?
# ==========================================
def _dest_is_normandie(lat_start, lon_start, lat_end, lon_end) -> bool:
    """
    Retourne True si l'extrémité côté grand-ouest est en Normandie
    (Manche 50, Calvados 14, Orne 61, Eure 27, Seine-Maritime 76).
    On identifie la Normandie par lon > -1.5 et lat >= 47.5.
    Permet de distinguer Normandie (→ Le Mans/Alençon)
    vs Bretagne/Vendée (→ Tours/Angers).
    """
    # Identifier quel bout est le "grand ouest" (lon <= 0.5)
    if lon_start <= 0.5 and lon_end > 0.5:
        lat_arr, lon_arr = lat_start, lon_start
    elif lon_end <= 0.5 and lon_start > 0.5:
        lat_arr, lon_arr = lat_end, lon_end
    else:
        # Les deux sont à l'ouest — prendre le plus au nord
        if lat_start >= lat_end:
            lat_arr, lon_arr = lat_start, lon_start
        else:
            lat_arr, lon_arr = lat_end, lon_end

    return lon_arr > -1.5 and lat_arr >= 47.5


# ==========================================
# JALONS CONDITIONNELS
# ==========================================
def _jalon_autorise(ville, lon_start, lon_end, lat_start=None, lat_end=None) -> bool:
    lon_min = min(lon_start, lon_end)
    lon_max = max(lon_start, lon_end)

    if ville in ("Amiens", "Albert", "Rouen"):
        if lon_min < 0.0:
            return False

    if ville == "Saint-Quentin":
        if lat_start is not None and lat_end is not None:
            neither_is_north_east = (
                not (lon_start > 4.0 and lat_start > 49.5) and
                not (lon_end   > 4.0 and lat_end   > 49.5)
            )
            if neither_is_north_east and lon_min < 0.0:
                return False
            if max(lat_start, lat_end) < 50.2 and lon_max < 4.0:
                return False

    if ville == "Dreux":
        if lon_max > 4.0:
            return False

    return True


def _is_lorraine_to_belgique(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_lorraine(lat, lon):
        return lon >= 6.0 and 47.5 <= lat <= 49.5

    def is_belgique(lat, lon):
        return lat >= 49.5 and lon >= 5.0

    return ((is_lorraine(lat_start, lon_start) and is_belgique(lat_end, lon_end))
            or (is_lorraine(lat_end, lon_end) and is_belgique(lat_start, lon_start)))


def _is_idf_to_ouest(lat_start, lon_start, lat_end, lon_end) -> bool:
    def is_idf_nord(lat, lon):
        return 1.5 <= lon <= 5.0 and 48.0 <= lat <= 49.5

    def is_ouest(lat, lon):
        return lon < -0.5 and 47.0 <= lat <= 49.5

    return is_idf_nord(lat_start, lon_start) and is_ouest(lat_end, lon_end)


# Axes pour les nouveaux détecteurs
AXE_LORRAINE_BELGIQUE = ["Nancy", "Metz", "Sedan"]
AXE_IDF_OUEST         = ["Le Mans"]


# ==========================================
# FONCTION PRINCIPALE
# ==========================================
def _appliquer_axe_force(nom_axe, liste_villes, villes_proches,
                         lat_start, lon_start, lat_end, lon_end,
                         rayon=None):
    if rayon is None:
        rayon = RAYON_AXE_FORCE_KM
    lon_min = min(lon_start, lon_end)
    lon_max = max(lon_start, lon_end)
    lat_min = min(lat_start, lat_end)
    lat_max = max(lat_start, lat_end)
    marge = 0.5

    for ville in liste_villes:
        if any(v[0] == ville for v in villes_proches):
            continue
        if ville not in VILLES_JALONS:
            print(f"      ⚠️  {nom_axe} : ville '{ville}' inconnue dans VILLES_JALONS")
            continue
        if not _jalon_autorise(ville, lon_start, lon_end, lat_start, lat_end):
            print(f"      🚫 {nom_axe} bloqué (zone): {ville}")
            continue
        vlat, vlon = VILLES_JALONS[ville]

        if vlon < lon_min - marge or vlon > lon_max + marge:
            print(f"      🚷 {nom_axe} hors zone : {ville} (lon {vlon:.2f} hors [{lon_min:.2f},{lon_max:.2f}])")
            continue
        if vlat < lat_min - marge or vlat > lat_max + marge:
            print(f"      🚷 {nom_axe} hors zone : {ville} (lat {vlat:.2f} hors [{lat_min:.2f},{lat_max:.2f}])")
            continue

        dist_seg = _distance_point_to_segment(
            vlat, vlon,
            lat_start, lon_start,
            lat_end, lon_end
        )
        if dist_seg <= rayon:
            dist_from_start = _haversine(lat_start, lon_start, vlat, vlon)
            villes_proches.append((ville, vlat, vlon, dist_from_start, dist_seg))
            print(f"      🛣️  {nom_axe} forcé : {ville} ({dist_seg:.0f}km du segment)")
        else:
            print(f"      🛣️  {nom_axe} ignoré : {ville} ({dist_seg:.0f}km > {rayon}km)")


def detecter_villes_jalons(lat_start, lon_start, lat_end, lon_end) -> list:
    print(f"      🧭 Jalons: ({lat_start:.4f}, {lon_start:.4f}) → ({lat_end:.4f}, {lon_end:.4f})")
    villes_proches = []

    # 1. Calcul des flags d'axes
    use_nord_ouest          = _is_nord_to_ouest(lat_start, lon_start, lat_end, lon_end)
    use_vosges_ouest        = _is_vosges_to_ouest(lat_start, lon_start, lat_end, lon_end)
    use_limousin            = _is_limousin_axis(lat_start, lon_start, lat_end, lon_end)
    use_massif_central      = _is_massif_central_to_ouest(lat_start, lon_start, lat_end, lon_end)
    use_ouest_nord_est      = _is_ouest_to_nord_est(lat_start, lon_start, lat_end, lon_end)
    use_ardennes            = _is_ardennes_avesnois(lat_start, lon_start, lat_end, lon_end)
    use_vosges_sud_ouest    = _is_vosges_to_sud_ouest(lat_start, lon_start, lat_end, lon_end)
    use_n88                 = _is_n88_axis(lat_start, lon_start, lat_end, lon_end)
    use_lorraine_belgique   = _is_lorraine_to_belgique(lat_start, lon_start, lat_end, lon_end)
    use_idf_ouest           = _is_idf_to_ouest(lat_start, lon_start, lat_end, lon_end)

    JALONS_EXCLUS_AUTO = set()

    if use_massif_central:
        JALONS_EXCLUS_AUTO.update({"Tulle", "Limoges", "Bellac", "La Souterraine", "Poitiers", "Niort"})

    def _is_nord_est_pt(lat, lon): return lat >= 49.5 and lon >= 3.0
    def _is_ouest_pt(lat, lon): return lon < -0.5 and 47.0 <= lat <= 49.5
    if ((_is_nord_est_pt(lat_start, lon_start) and _is_ouest_pt(lat_end, lon_end))
            or (_is_nord_est_pt(lat_end, lon_end) and _is_ouest_pt(lat_start, lon_start))):
        JALONS_EXCLUS_AUTO.update({"Évreux", "Beauvais", "Compiègne", "Chartres", "Alençon",
                                    "Argentan", "Dreux", "Laval", "Le Mans", "Mayenne",
                                    "Châteaubriant", "Angers", "Tours"})

    # 2. Detection auto par proximite au segment direct
    lon_min = min(lon_start, lon_end)
    lon_max = max(lon_start, lon_end)
    lat_min = min(lat_start, lat_end)
    lat_max = max(lat_start, lat_end)
    marge = 0.5

    for ville, (vlat, vlon) in VILLES_JALONS.items():
        if ville in JALONS_EXCLUS_AUTO:
            continue
        if not _jalon_autorise(ville, lon_start, lon_end, lat_start, lat_end):
            continue
        if vlon < lon_min - marge or vlon > lon_max + marge:
            continue
        if vlat < lat_min - marge or vlat > lat_max + marge:
            continue
        dist = _distance_point_to_segment(
            vlat, vlon,
            lat_start, lon_start,
            lat_end, lon_end
        )
        if dist <= RAYON_DETECTION_KM:
            dist_from_start = _haversine(lat_start, lon_start, vlat, vlon)
            villes_proches.append((ville, vlat, vlon, dist_from_start, dist))

    # 3. Axes forces
    if use_nord_ouest:
        _appliquer_axe_force("NORD-OUEST", AXE_NORD_OUEST, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    if use_vosges_ouest:
        _appliquer_axe_force("VOSGES-OUEST", AXE_VOSGES_OUEST, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    if use_vosges_sud_ouest:
        _appliquer_axe_force("VOSGES-SUD-OUEST", AXE_VOSGES_SUD_OUEST, villes_proches,
                             lat_start, lon_start, lat_end, lon_end, rayon=60)

    if use_limousin and not use_massif_central:
        _appliquer_axe_force("LIMOUSIN", AXE_LIMOUSIN, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    if use_massif_central:
        # Branchement selon la destination :
        # - Normandie (Manche, Calvados, Orne...) → axe Orléans/Le Mans/Alençon
        # - Bretagne / Vendée / Pays de la Loire  → axe Tours/Angers (ancien comportement)
        if _dest_is_normandie(lat_start, lon_start, lat_end, lon_end):
            print(f"      🗺️  MASSIF-CENTRAL → destination Normandie détectée : axe Orléans/Le Mans/Alençon")
            _appliquer_axe_force("MASSIF-CENTRAL-NORMANDIE", AXE_MASSIF_CENTRAL_NORMANDIE,
                                 villes_proches, lat_start, lon_start, lat_end, lon_end)
        else:
            print(f"      🗺️  MASSIF-CENTRAL → destination Bretagne/Vendée : axe Tours/Angers")
            _appliquer_axe_force("MASSIF-CENTRAL-OUEST", AXE_MASSIF_CENTRAL_OUEST,
                                 villes_proches, lat_start, lon_start, lat_end, lon_end)

    if use_ouest_nord_est:
        _appliquer_axe_force("OUEST-NORD-EST", AXE_OUEST_NORD_EST, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    if use_ardennes:
        _appliquer_axe_force("ARDENNES-AVESNOIS", AXE_ARDENNES_AVESNOIS, villes_proches,
                             lat_start, lon_start, lat_end, lon_end, rayon=30)

    if use_n88:
        _appliquer_axe_force("N88", AXE_N88, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    if use_lorraine_belgique:
        _appliquer_axe_force("LORRAINE-BELGIQUE", AXE_LORRAINE_BELGIQUE, villes_proches,
                             lat_start, lon_start, lat_end, lon_end, rayon=70)

    if use_idf_ouest:
        _appliquer_axe_force("IDF-OUEST", AXE_IDF_OUEST, villes_proches,
                             lat_start, lon_start, lat_end, lon_end)

    # N12/N2 : seulement si aucun axe spécifique ne s'est déclenché
    if not (use_nord_ouest or use_vosges_ouest or use_vosges_sud_ouest or use_limousin or use_massif_central
            or use_ouest_nord_est or use_ardennes or use_n88 or use_lorraine_belgique or use_idf_ouest):
        lat_max_traj = max(lat_start, lat_end)
        lon_min_traj = min(lon_start, lon_end)
        n12_n2_safe = (lat_max_traj < 49.0) and (lon_min_traj > -0.3)
        if n12_n2_safe:
            if _is_east_west(lat_start, lon_start, lat_end, lon_end):
                _appliquer_axe_force("N12", AXE_N12, villes_proches,
                                     lat_start, lon_start, lat_end, lon_end)
            if _is_north_axis(lat_start, lon_start, lat_end, lon_end):
                _appliquer_axe_force("N2", AXE_N2, villes_proches,
                                     lat_start, lon_start, lat_end, lon_end)
        else:
            print(f"      ⏭️  N12/N2 désactivés (lat_max={lat_max_traj:.2f}, lon_min={lon_min_traj:.2f})")

    # 4. Anti-retour-en-arriere + anti-doublon-extremite
    dist_total = _haversine(lat_start, lon_start, lat_end, lon_end)
    villes_filtrees = []
    for v in villes_proches:
        ville, vlat, vlon, dist_start, dist_seg = v
        dist_to_end = _haversine(vlat, vlon, lat_end, lon_end)
        if dist_start + dist_to_end > dist_total * 1.2:
            print(f"      🚫 {ville} écarté (hors corridor : {dist_start:.0f}+{dist_to_end:.0f} > {dist_total*1.2:.0f})")
            continue
        seuil_extremite = max(60, dist_total * 0.08)
        if dist_start < seuil_extremite:
            print(f"      🚫 {ville} écarté (trop proche du départ : {dist_start:.0f}km)")
            continue
        if dist_to_end < seuil_extremite:
            print(f"      🚫 {ville} écarté (trop proche de l'arrivée : {dist_to_end:.0f}km)")
            continue
        villes_filtrees.append(v)

    # 5. Tri par distance depuis le depart
    villes_filtrees.sort(key=lambda x: x[3])

    # 6. Anti-zigzag
    if len(villes_filtrees) >= 2:
        cleaned = [villes_filtrees[0]]
        for i in range(1, len(villes_filtrees)):
            prev = cleaned[-1]
            curr = villes_filtrees[i]
            saut_progression = curr[3] - prev[3]
            dist_inter = _haversine(prev[1], prev[2], curr[1], curr[2])
            if saut_progression > 200 and dist_inter > saut_progression * 1.3:
                print(f"      🌀 {prev[0]} retiré (zigzag : saut {dist_inter:.0f}km vs progression {saut_progression:.0f}km)")
                cleaned[-1] = curr
            else:
                cleaned.append(curr)
        villes_filtrees = cleaned

    # 7. Elagage
    if len(villes_filtrees) > MAX_WAYPOINTS:
        villes_filtrees.sort(key=lambda x: x[4])
        villes_filtrees = villes_filtrees[:MAX_WAYPOINTS]
        villes_filtrees.sort(key=lambda x: x[3])
        print(f"      ✂️  Élagage : limité à {MAX_WAYPOINTS} waypoints")

    # 8. Conversion en strings "lat, lon;r=RADIUS"
    JALON_RADIUS = 8000  # 8km — assez large pour couvrir un échangeur, assez serré pour guider
    waypoints = []
    for ville, vlat, vlon, dist_start, dist_seg in villes_filtrees:
        waypoints.append(f"{vlat}, {vlon};r={JALON_RADIUS}")
        print(f"      📌 Jalon retenu : {ville} ({dist_seg:.0f}km du trajet, {dist_start:.0f}km du départ, radius={JALON_RADIUS}m)")

    return waypoints
