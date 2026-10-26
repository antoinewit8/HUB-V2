import os
import re
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# ============================================================
# CONSTANTES
# ============================================================

PAYS_MAP = {
    "FR": "France", "BE": "Belgium", "DE": "Germany", "NL": "Netherlands",
    "LU": "Luxembourg", "IT": "Italy", "ES": "Spain", "PT": "Portugal",
    "GB": "United Kingdom", "CH": "Switzerland", "AT": "Austria",
    "PL": "Poland", "CZ": "Czech Republic", "HU": "Hungary",
    "RO": "Romania", "BG": "Bulgaria", "SK": "Slovakia", "SI": "Slovenia",
    "HR": "Croatia", "DK": "Denmark", "SE": "Sweden", "NO": "Norway",
    "FI": "Finland", "IE": "Ireland", "GR": "Greece",
    "F": "France", "B": "Belgium", "D": "Germany", "I": "Italy",
    "E": "Spain", "L": "Luxembourg", "A": "Austria", "P": "Portugal",
    # Noms en clair
    "FRANCE": "France", "BELGIQUE": "Belgium", "BELGIË": "Belgium",
    "ALLEMAGNE": "Germany", "DEUTSCHLAND": "Germany",
    "PAYS-BAS": "Netherlands", "NEDERLAND": "Netherlands",
    "LUXEMBOURG": "Luxembourg", "ITALIE": "Italy", "ITALIA": "Italy",
    "ESPAGNE": "Spain", "ESPAÑA": "Spain", "SUISSE": "Switzerland",
    "SCHWEIZ": "Switzerland", "AUTRICHE": "Austria", "ÖSTERREICH": "Austria",
    "ROYAUME-UNI": "United Kingdom", "POLOGNE": "Poland", "POLSKA": "Poland",
    "PORTUGAL": "Portugal", "GRÈCE": "Greece", "NETHERLANDS": "Netherlands",
    "GERMANY": "Germany", "SPAIN": "Spain", "ITALY": "Italy",
    "AUSTRIA": "Austria", "SWITZERLAND": "Switzerland", "POLAND": "Poland",
    # Noms anglais / variantes absents jusqu'ici : « 4020, BELGIUM » devenait « 40200 »
    "BELGIUM": "Belgium", "BELGIE": "Belgium", "BELGIEN": "Belgium",
    "LUXEMBURG": "Luxembourg", "FRANKREICH": "France", "NIEDERLANDE": "Netherlands",
    "UNITED KINGDOM": "United Kingdom", "UK": "United Kingdom",
    "CZECH REPUBLIC": "Czech Republic", "CZ": "Czech Republic", "DENMARK": "Denmark",
    "SWEDEN": "Sweden", "HUNGARY": "Hungary", "ROMANIA": "Romania", "BULGARIA": "Bulgaria",
    "CROATIA": "Croatia", "IRELAND": "Ireland", "GREECE": "Greece", "IRL": "Ireland",
    "NL": "Netherlands", "CH": "Switzerland", "GB": "United Kingdom", "S": "Sweden",
}

CP_LENGTHS = {
    "FR": 5, "F": 5, "BE": 4, "B": 4, "DE": 5, "D": 5,
    "IT": 5, "I": 5, "ES": 5, "E": 5, "PL": 5, "CZ": 5,
    "HR": 5, "SK": 5, "GR": 5, "SE": 5, "FI": 5, "NL": 4,
    "AT": 4, "A": 4, "CH": 4, "HU": 4, "DK": 4, "SI": 4,
    "NO": 4, "LU": 4, "L": 4, "PT": 7, "P": 7, "RO": 6,
}

CITY_CORRECTIONS = {
    "Basse Indre":    ("Indre", "44610", "FR"),
    "Saint Herblain": ("Saint-Herblain", "44800", "FR"),
    "Montataire":     ("Montataire", "60160", "FR"),
}

ZONE_CORRECTIONS = {
    "02000, Italy": "Rieti, 02100, Italy",
    "06000, Italy": "Perugia, 06100, Italy",
    "10000, Italy": "Torino, 10100, Italy",
    "16000, Italy": "Genova, 16100, Italy",
    "20000, Italy": "Milano, 20100, Italy",
    "21000, Italy": "Varese, 21100, Italy",
    "23000, Italy": "Sondrio, 23100, Italy",
    "24000, Italy": "Bergamo, 24100, Italy",
    "25000, Italy": "Brescia, 25100, Italy",
    "30000, Italy": "Mestre, 30170, Italy",
    "31000, Italy": "Treviso, 31100, Italy",
    "33000, Italy": "Udine, 33100, Italy",
    "36000, Italy": "Vicenza, 36100, Italy",
    "00000, Italy": "Roma, 00133, Italy",
    "50000, Italy": "Firenze, 50127, Italy",
    "80000, Italy": "Napoli, 80146, Italy",
    "6000, Netherlands": "Weert, 6000, Netherlands",
    "6200, Netherlands": "Maastricht, 6221, Netherlands",
    "6600, Netherlands": "Wijchen, 6602, Netherlands",
    "1000, Netherlands": "Amsterdam, 1043, Netherlands",
    "3000, Netherlands": "Rotterdam, 3089, Netherlands",
    "8800, Belgium": "Roeselare, 8800, Belgium",
    "1000, Belgium": "Bruxelles, 1120, Belgium",
    "2000, Belgium": "Antwerpen, 2030, Belgium",
    "4000, Belgium": "Liège, 4020, Belgium",
    "50000, Germany": "Köln, 50769, Germany",
    "58000, Germany": "Hagen, 58099, Germany",
    "59000, Germany": "Hamm, 59067, Germany",
    "10000, Germany": "Berlin, 13405, Germany",
    "20000, Germany": "Hamburg, 21129, Germany",
    "80000, Germany": "München, 80939, Germany",
    "60000, Germany": "Frankfurt, 60549, Germany",
    "75000, France": "Paris, 75012, France",
    "69000, France": "Vénissieux, 69200, France",
    "13000, France": "Marseille, 13015, France",
    "33000, France": "Bordeaux, 33300, France",
    "59000, France": "Lille, 59160, France",
    "67000, France": "Strasbourg, 67100, France",
    "28000, Spain": "Madrid, 28052, Spain",
    "08000, Spain": "Barcelona, 08040, Spain",
    "46000, Spain": "Valencia, 46024, Spain",
    "01000, Spain": "Vitoria-Gasteiz, 01015, Spain",
    "03000, Spain": "Alicante, 03008, Spain",
    "06000, Spain": "Badajoz, 06006, Spain",
    "09000, Spain": "Burgos, 09007, Spain",
    "30000, Spain": "Murcia, 30169, Spain",
    "36000, Spain": "Pontevedra, 36158, Spain",
    "1000, Austria": "Wien, 1110, Austria",
    "3400, Luxembourg": "Dudelange, 3400, Luxembourg",
    "1000, Luxembourg": "Luxembourg, 1000, Luxembourg",
    "15000, Bulgaria": "Sofia, 1528, Bulgaria",
}
# Chefs-lieux belges par préfixe 2 chiffres du CP
# Utilisé automatiquement quand destination = CP seul, sans ville
BE_CHEFS_LIEUX = {
    "10": ("Bruxelles",    "1000"),
    "11": ("Bruxelles",    "1080"),
    "12": ("Bruxelles",    "1200"),
    "13": ("Wavre",        "1300"),
    "14": ("Nivelles",     "1400"),
    "15": ("Ottignies",    "1340"),
    "16": ("Rixensart",    "1330"),
    "17": ("Hal",          "1700"),
    "18": ("Vilvoorde",    "1800"),
    "19": ("Zaventem",     "1930"),
    "20": ("Antwerpen",    "2000"),
    "21": ("Antwerpen",    "2100"),
    "22": ("Antwerpen",    "2200"),
    "23": ("Turnhout",     "2300"),
    "24": ("Herentals",    "2200"),
    "25": ("Lier",         "2500"),
    "26": ("Mechelen",     "2600"),
    "27": ("Mechelen",     "2800"),
    "28": ("Mechelen",     "2800"),
    "29": ("Schoten",      "2900"),
    "30": ("Leuven",       "3001"),
    "31": ("Leuven",       "3010"),
    "32": ("Aarschot",     "3200"),
    "33": ("Tienen",       "3300"),
    "34": ("Diest",        "3290"),
    "35": ("Hasselt",      "3500"),
    "36": ("Genk",         "3600"),
    "37": ("Tongeren",     "3700"),
    "38": ("Sint-Truiden", "3800"),
    "39": ("Overpelt",     "3900"),
    "40": ("Liège",        "4000"),
    "41": ("Liège",        "4100"),
    "42": ("Liège",        "4020"),
    "43": ("Liège",        "4300"),
    "44": ("Waremme",      "4300"),
    "45": ("Huy",          "4500"),
    "46": ("Nandrin",      "4550"),
    "47": ("Eupen",        "4700"),
    "48": ("Malmedy",      "4960"),
    "49": ("Stavelot",     "4970"),
    "50": ("Namur",        "5000"),
    "51": ("Gembloux",     "5030"),
    "52": ("Namur",        "5020"),
    "53": ("Andenne",      "5300"),
    "54": ("Dinant",       "5500"),
    "55": ("Philippeville", "5600"),
    "56": ("Charleroi",    "5600"),
    "57": ("Nismes",       "5670"),
    "58": ("Philippeville", "5600"),
    "59": ("Ciney",        "5590"),
    "60": ("Charleroi",    "6000"),
    "61": ("Charleroi",    "6110"),
    "62": ("Châtelet",     "6200"),
    "63": ("Charleroi",    "6230"),
    "64": ("Chimay",       "6460"),
    "65": ("Mons",         "6500"),
    "66": ("Mons",         "6600"),
    "67": ("La Louvière",  "7100"),
    "68": ("Tournai",      "7500"),
    "69": ("Ath",          "7800"),
    "70": ("Mons",         "7000"),
    "71": ("La Louvière",  "7100"),
    "72": ("Mons",         "7000"),
    "73": ("Soignies",     "7060"),
    "74": ("Tournai",      "7500"),
    "75": ("Tournai",      "7500"),
    "76": ("Ath",          "7800"),
    "77": ("Enghien",      "7850"),
    "78": ("Lessines",     "7860"),
    "79": ("Péruwelz",     "7600"),
    "80": ("Bruges",       "8000"),
    "81": ("Bruges",       "8200"),
    "82": ("Ostende",      "8400"),
    "83": ("Roeselare",    "8800"),
    "84": ("Ieper",        "8900"),
    "85": ("Kortrijk",     "8500"),
    "86": ("Waregem",      "8790"),
    "87": ("Wielsbeke",    "8710"),
    "88": ("Roeselare",    "8800"),
    "89": ("Diksmuide",    "8600"),
    "90": ("Gent",         "9000"),
    "91": ("Gent",         "9100"),
    "92": ("Aalst",        "9200"),
    "93": ("Oudenaarde",   "9700"),
    "94": ("Ninove",       "9400"),
    "95": ("Geraardsbergen","9500"),
    "96": ("Dendermonde",  "9200"),
    "97": ("Ronse",        "9600"),
    "98": ("Eeklo",        "9900"),
    "99": ("Gent",         "9990"),
}

GPS_FIXES_ORIGIN = {
    "rumbek":  "Rumbeke, 8800, Belgium",
    "rumbeke": "Rumbeke, 8800, Belgium",
    "indre":   "Indre, 44610, France",
    "clermont": "Clermont-sur-oise, 60600, France"
}

# ============================================================
# SYNONYMES POUR DÉTECTION INTELLIGENTE
# ============================================================

# Chaque rôle a une liste de synonymes (en minuscule)
ORIG_PAYS_KEYWORDS = [
    "pays", "country", "country of origin", "orig cntry",
    "pays départ", "pays depart", "pays origine",
    "pays chargement", "pays de chargement", "code pays chargement",
]
ORIG_CP_KEYWORDS = [
    "code postal", "cp", "postal code", "postal code origin",
    "orig reg", "cp départ", "cp depart", "code postal origine",
    "cp chargement", "cp charg", "c.p. chargement", "code postal chargement",
]
ORIG_VILLE_KEYWORDS = [
    "ville", "city", "city of origin", "orig zone txt",
    "localité", "localite", "origin", "depart", "départ",
    "origine", "ville départ", "ville depart",
    "ville chargement", "localité chargement", "localite chargement", "lieu chargement",
]
DEST_PAYS_KEYWORDS = [
    "pays", "country", "country of destination", "dest cntry",
    "pays destination", "dest pays",
    "pays déchargement", "pays dechargement", "pays livraison", "code pays déchargement",
]
DEST_CP_KEYWORDS = [
    "département", "departement", "code postal", "cp",
    "postal code", "postal code destination", "dest reg",
    "cp destination", "cp dech", "cp déchargement",
    "cp dechargement", "c.p. déchargement", "cp livraison", "code postal déchargement",
]
DEST_VILLE_KEYWORDS = [
    "ville2", "ville", "city", "city of destination",
    "dest zone txt", "destination", "ville destination",
    "ville dest", "localite", "localité",
    "ville déchargement", "ville dechargement", "localité déchargement", "localite dechargement",
    "ville livraison", "lieu déchargement",
]

# Mots-clés des lignes de groupe (ligne au-dessus des headers)
ORIGIN_GROUP_KEYWORDS = ["depart", "départ", "origin", "origine", "chargement", "loading"]
DEST_GROUP_KEYWORDS   = ["destination", "dest", "arrivée", "arrivee", "livraison", "delivery", "unloading"]

# Mots-clés d'en-tête parasite
HEADER_KEYWORDS = {
    "depart", "départ", "origin", "pays", "country", "cp", "code postal",
    "postal code", "destination", "dest", "city", "ville", "zone",
    "country of destination", "dest cntry", "dest zone txt", "dest reg",
    "postal code destination", "city of destination",
}


# ============================================================
# UTILITAIRES
# ============================================================

def normalize(val):
    if val is None:
        return ""
    return re.sub(r'\s+', ' ', str(val).strip().lower())


# Pays dont le CP compte 5 chiffres avec un 0 initial possible (perdu quand Excel stocke un nombre)
_CP5_ZERO = {"FR", "F", "DE", "D", "IT", "I", "ES", "E"}


def cp_texte(cp) -> str:
    """Valeur de cellule → texte du CP : 2100 → '2100', 59000.0 → '59000', ' L-1234 ' → 'L-1234'."""
    if cp is None:
        return ""
    if isinstance(cp, float):
        if cp != cp:                                   # NaN
            return ""
        if cp.is_integer():
            cp = int(cp)
    s = str(cp).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def split_cp_pays(cp: str):
    """« L-1234 » → ('L', '1234') ; « F-59000 » → ('F', '59000') ; « 4020 » → ('', '4020')."""
    m = re.match(r"^\s*([A-Za-z]{1,3})\s*-\s*(\d.*)$", cp or "")
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return "", (cp or "").strip()


def pad_postal_code(cp, country_prefix):
    """Complète un CP numérique.
    - 4 chiffres en France / Allemagne / Italie / Espagne : 0 initial perdu → à gauche (2100 → 02100)
    - 1 à 3 chiffres : département ou zone → à droite (13 → 13000), comportement historique
    """
    cp = cp_texte(cp)
    if not cp:
        return ""
    prefix = str(country_prefix or "").upper()
    target_len = CP_LENGTHS.get(prefix, 5)
    if target_len == 0 or not cp.isdigit():
        return cp
    if len(cp) == target_len - 1 and target_len == 5 and prefix in _CP5_ZERO:
        return cp.zfill(target_len)
    if len(cp) < target_len:
        cp = cp + "0" * (target_len - len(cp))
    return cp


def is_header_row_data(values):
    """Retourne True si la ligne ressemble à une ligne d'en-tête parasite."""
    return any(str(v).strip().lower() in HEADER_KEYWORDS for v in values if v)


def find_first_empty_column(ws, header_row=1, data_start=2):
    col = 1
    while col < 100:
        if ws.cell(row=header_row, column=col).value is not None:
            col += 1
            continue
        has_data = False
        for row in range(data_start, min(data_start + 10, ws.max_row + 1)):
            if ws.cell(row=row, column=col).value is not None:
                has_data = True
                break
        if not has_data:
            return col
        col += 1
    return col


# ============================================================
# DÉTECTION INTELLIGENTE DES EN-TÊTES
# ============================================================

def detect_header_row(ws, max_scan=15):
    """
    Parcourt les premières lignes pour trouver celle qui contient
    le plus de headers reconnus parmi tous les synonymes.
    """
    all_keywords = set()
    for kw_list in [ORIG_PAYS_KEYWORDS, ORIG_CP_KEYWORDS, ORIG_VILLE_KEYWORDS,
                    DEST_PAYS_KEYWORDS, DEST_CP_KEYWORDS, DEST_VILLE_KEYWORDS]:
        for kw in kw_list:
            all_keywords.add(kw)

    best_row   = None
    best_score = 0

    for row_idx in range(1, min(max_scan + 1, ws.max_row + 1)):
        score = 0
        for col in range(1, ws.max_column + 1):
            val = normalize(ws.cell(row=row_idx, column=col).value)
            if val in all_keywords:
                score += 1
        if score > best_score:
            best_score = score
            best_row = row_idx

    return best_row if best_score >= 2 else None


def detect_groups(ws, header_row):
    """
    Regarde la ligne juste au-dessus des headers pour détecter
    les groupes DEPART / Destination via cellules fusionnées ou non.
    Retourne un dict {col_index: "origin" | "dest"}.
    """
    if header_row <= 1:
        return {}

    group_row = header_row - 1
    groups = {}
    current_group = None

    # Gérer les cellules fusionnées : mapper chaque colonne à sa valeur de merge
    merge_map = {}
    for merge_range in ws.merged_cells.ranges:
        if merge_range.min_row <= group_row <= merge_range.max_row:
            val = ws.cell(row=merge_range.min_row, column=merge_range.min_col).value
            for c in range(merge_range.min_col, merge_range.max_col + 1):
                merge_map[c] = val

    for col in range(1, ws.max_column + 1):
        val = normalize(merge_map.get(col, ws.cell(row=group_row, column=col).value))

        if any(k in val for k in ORIGIN_GROUP_KEYWORDS):
            current_group = "origin"
        elif any(k in val for k in DEST_GROUP_KEYWORDS):
            current_group = "dest"
        elif val and val not in ("", " "):
            # Un texte non reconnu = on ne sait plus dans quel groupe
            current_group = None

        if current_group:
            groups[col] = current_group

    return groups


def map_columns(ws):
    """
    Détecte la ligne d'en-têtes, les groupes, et mappe chaque rôle
    à un numéro de colonne. Gère les doublons (2x "Pays") via les groupes.
    """
    header_row = detect_header_row(ws)
    if not header_row:
        return None, None, None

    groups = detect_groups(ws, header_row)

    # Lire tous les headers de la ligne détectée
    headers = {}
    for col in range(1, ws.max_column + 1):
        val = normalize(ws.cell(row=header_row, column=col).value)
        if val:
            headers[col] = val

    # Définition des rôles à mapper
    ROLES = {
        "orig_pays":  (ORIG_PAYS_KEYWORDS,  "origin"),
        "orig_cp":    (ORIG_CP_KEYWORDS,     "origin"),
        "orig_ville": (ORIG_VILLE_KEYWORDS,  "origin"),
        "dest_pays":  (DEST_PAYS_KEYWORDS,   "dest"),
        "dest_cp":    (DEST_CP_KEYWORDS,     "dest"),
        "dest_ville": (DEST_VILLE_KEYWORDS,  "dest"),
    }

    mapping = {}
    used_cols = set()

    for role, (keywords, expected_side) in ROLES.items():
        # Passe 1 : avec groupe (résout les doublons "pays", "ville")
        for col, header_val in headers.items():
            if col in used_cols:
                continue
            col_side = groups.get(col)
            if col_side == expected_side and header_val in keywords:
                mapping[role] = col
                used_cols.add(col)
                break

        # Passe 2 : sans groupe (fallback pour fichiers sans ligne de groupe)
        if role not in mapping:
            for col, header_val in headers.items():
                if col in used_cols:
                    continue
                if header_val in keywords:
                    mapping[role] = col
                    used_cols.add(col)
                    break

    data_start_row = header_row + 1
    return mapping, header_row, data_start_row


# ============================================================
# PARSEURS
# ============================================================

def parse_origin(origin_str):
    if not origin_str:
        return ""
    origin_str = str(origin_str).strip()

    last_word = origin_str.split()[-1].lower() if origin_str.split() else ""
    if last_word in GPS_FIXES_ORIGIN:
        return GPS_FIXES_ORIGIN[last_word]

    if "(" in origin_str and ")" in origin_str:
        ville = origin_str[:origin_str.index("(")].strip()
        code  = origin_str[origin_str.index("(") + 1:origin_str.index(")")].strip()

        pays_prefix = ""
        cp = ""
        for i, c in enumerate(code):
            if c.isdigit():
                pays_prefix = code[:i]
                cp = code[i:]
                break

        cp   = pad_postal_code(cp, pays_prefix)
        pays = PAYS_MAP.get(pays_prefix.upper(), pays_prefix)

        if ville in CITY_CORRECTIONS:
            ville_corr, cp_corr, pays_corr = CITY_CORRECTIONS[ville]
            pays_corr_full = PAYS_MAP.get(pays_corr.upper(), pays_corr)
            return f"{ville_corr}, {cp_corr}, {pays_corr_full}"

        return f"{ville}, {cp}, {pays}"

    return origin_str


def _iso_de(pays_full, defaut):
    return next((k for k, v in PAYS_MAP.items() if v == pays_full and len(k) == 2 and k.isupper()), defaut)


def _pays_complet(country, cp_pays=""):
    country = str(country or "").strip()
    pays_full = PAYS_MAP.get(country.upper(), "")
    if not pays_full and cp_pays:
        pays_full = PAYS_MAP.get(cp_pays.upper(), "")
    return pays_full or country or cp_pays


def parse_origin_from_parts(city, postal_code, country):
    city = str(city or "").strip()
    cp_pays, cp_num = split_cp_pays(cp_texte(postal_code))
    pays_full = _pays_complet(country, cp_pays)
    cp_num = pad_postal_code(cp_num, _iso_de(pays_full, str(country or "").strip() or cp_pays))

    if city:
        return f"{city}, {cp_num}, {pays_full}"
    elif cp_num:
        return f"{cp_num}, {pays_full}"
    else:
        return pays_full


def parse_destination(city, postal_code, country):
    city = str(city or "").strip()
    cp_pays, cp_num = split_cp_pays(cp_texte(postal_code))
    pays_full = _pays_complet(country, cp_pays)
    cp_num = pad_postal_code(cp_num, _iso_de(pays_full, cp_pays or str(country or "").strip()))

    if city.lower() in ("all cities", "all", ""):
        base_zone = f"{cp_num}, {pays_full}"
        # Vérifie ZONE_CORRECTIONS en premier
        if base_zone in ZONE_CORRECTIONS:
            return ZONE_CORRECTIONS[base_zone]
        # Pour la Belgique sans ville : utilise le chef-lieu du préfixe
        if pays_full == "Belgium" and len(cp_num) >= 2:
            prefix = cp_num[:2]
            if prefix in BE_CHEFS_LIEUX:
                chef_lieu, cp_chef = BE_CHEFS_LIEUX[prefix]
                return f"{chef_lieu}, {cp_chef}, Belgium"
        return base_zone
    else:
        return f"{city}, {cp_num}, {pays_full}"


def decouper_lieu(texte: str):
    """« Ville, CP, Pays » / « CP, Pays » / « Pays » → (pays, cp, ville)."""
    morceaux = [m.strip() for m in str(texte or "").rsplit(",", 2)]
    if len(morceaux) == 3:
        return morceaux[2], morceaux[1], morceaux[0]
    if len(morceaux) == 2:
        return morceaux[1], morceaux[0], ""
    return morceaux[0], "", ""


# ============================================================
# LECTURE EXCEL — DÉTECTION INTELLIGENTE
# ============================================================

_NOMS_ROLES = {
    "orig_pays": "Pays départ", "orig_cp": "CP départ", "orig_ville": "Ville départ",
    "dest_pays": "Pays destination", "dest_cp": "CP destination", "dest_ville": "Ville destination",
}


def read_all_sheets(filepath, rapport=None):
    """Retourne (wb, {feuille: (ws, routes)}).

    Les valeurs sont lues dans une copie « data_only » (résultat des formules, pas
    « =A2 ») ; le classeur rendu garde ses formules pour l'écriture.
    Si `rapport` est une liste, chaque feuille y ajoute
    {feuille, lue, raison, colonnes, ligne_entetes, trajets}.
    """
    wb = openpyxl.load_workbook(filepath)
    try:
        wb_val = openpyxl.load_workbook(filepath, data_only=True)
    except Exception:
        wb_val = wb
    sheets_data = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        wv = wb_val[sheet_name]
        info = {"feuille": sheet_name, "lue": False, "raison": "", "colonnes": {},
                "ligne_entetes": None, "trajets": 0}
        if rapport is not None:
            rapport.append(info)

        # ── Détection intelligente ────────────────────────────────────────
        mapping, header_row, data_start_row = map_columns(wv)
        if mapping is None:
            info["raison"] = "en-têtes non reconnus (il faut au moins Pays / CP / Ville ou Localité)"
            print(f"  ⚠️  Feuille '{sheet_name}' ignorée [headers non détectés]")
            continue

        info["ligne_entetes"] = header_row
        info["colonnes"] = {_NOMS_ROLES[k]: f"{get_column_letter(c)} ({wv.cell(row=header_row, column=c).value})"
                            for k, c in mapping.items()}
        has_orig = any(k.startswith("orig_") for k in mapping)
        has_dest = any(k.startswith("dest_") for k in mapping)
        if not has_orig or not has_dest:
            info["raison"] = ("colonnes de départ introuvables" if not has_orig
                              else "colonnes de destination introuvables")
            print(f"  ⚠️  Feuille '{sheet_name}' ignorée [orig={has_orig}, dest={has_dest}] Mapping: {mapping}")
            continue

        print(f"  ✅ Feuille '{sheet_name}' — headers ligne {header_row} Mapping: {mapping}")

        def val(row, role):
            return wv.cell(row=row, column=mapping[role]).value if role in mapping else None

        # ── Lecture des routes ────────────────────────────────────────────
        routes       = []
        lignes_vides = 0

        for row in range(data_start_row, wv.max_row + 6):
            orig_pays_raw, orig_cp_raw, orig_city_raw = val(row, "orig_pays"), val(row, "orig_cp"), val(row, "orig_ville")
            dest_pays_raw, dest_cp_raw, dest_city_raw = val(row, "dest_pays"), val(row, "dest_cp"), val(row, "dest_ville")

            # Ligne vide ? (le CP compte aussi : fichiers « pays + CP » sans ville)
            if not any(v not in (None, "") for v in (orig_pays_raw, orig_cp_raw, orig_city_raw,
                                                      dest_pays_raw, dest_cp_raw, dest_city_raw)):
                lignes_vides += 1
                if lignes_vides >= 3:
                    break
                continue
            lignes_vides = 0

            all_vals = [orig_pays_raw, orig_cp_raw, orig_city_raw,
                        dest_pays_raw, dest_cp_raw, dest_city_raw]
            if is_header_row_data(all_vals):
                print(f"  ⏭️  Ligne {row} ignorée (en-tête parasite)")
                continue

            origin = parse_origin_from_parts(orig_city_raw, orig_cp_raw, orig_pays_raw)
            dest = parse_destination(dest_city_raw, dest_cp_raw, dest_pays_raw)
            if not origin or not dest:
                continue

            label = (f"{orig_city_raw or orig_pays_raw} ({cp_texte(orig_cp_raw)}) "
                     f"→ {dest_city_raw or 'Zone'} ({cp_texte(dest_cp_raw)})")

            routes.append({
                "row":    row,
                "origin": origin,
                "dest":   dest,
                "label":  label,
                # saisie d'origine, pour les contrôles (pays incohérent, CP corrigé…)
                "saisie_origine": " ".join(cp_texte(v) for v in (orig_pays_raw, orig_cp_raw, orig_city_raw) if v not in (None, "")),
                "saisie_dest":    " ".join(cp_texte(v) for v in (dest_pays_raw, dest_cp_raw, dest_city_raw) if v not in (None, "")),
                # pas de localité saisie : le point vient du CP / d'une zone (ZONE_CORRECTIONS, chef-lieu belge)
                "sans_lieu_origine": not str(orig_city_raw or "").strip(),
                "sans_lieu_dest": str(dest_city_raw or "").strip().lower() in ("", "all", "all cities"),
            })

        info["trajets"] = len(routes)
        if routes:
            info["lue"] = True
            sheets_data[sheet_name] = (ws, routes)
            print(f"     → {len(routes)} route(s) extraite(s)")
        else:
            info["raison"] = "aucune ligne exploitable sous les en-têtes"
            print(f"  ⚠️  Feuille '{sheet_name}' : aucune route valide")

    return wb, sheets_data


# ============================================================
# ÉCRITURE RÉSULTATS
# ============================================================

def unmerge_and_write(ws, row, col, value, font=None, fill=None, alignment=None, border=None):
    for merge_range in list(ws.merged_cells.ranges):
        if (merge_range.min_row <= row <= merge_range.max_row and
                merge_range.min_col <= col <= merge_range.max_col):
            ws.unmerge_cells(str(merge_range))
            break
    cell = ws.cell(row=row, column=col)
    cell.value = value            # ws.cell(value=None) n'efface pas : on affecte explicitement
    if font:      cell.font      = font
    if fill:      cell.fill      = fill
    if alignment: cell.alignment = alignment
    if border:    cell.border    = border
    return cell


def find_safe_col(ws, header_row, start_col):
    col = start_col
    while True:
        is_merged = False
        for merge_range in ws.merged_cells.ranges:
            if (merge_range.min_row <= header_row <= merge_range.max_row and
                    merge_range.min_col <= col <= merge_range.max_col):
                col = merge_range.max_col + 1
                is_merged = True
                break
        if not is_merged:
            val = ws.cell(row=header_row, column=col).value
            if val is None:
                return col
            col += 1


COULEURS_STATUT = {"OK": "E2EFDA", "À vérifier": "FFF2CC", "Erreur": "F8CBAD"}


def _colonne_existante(ws, header_row, titre):
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=col).value
        if v is not None and str(v).strip() == titre:
            return col
    return None


def write_km_results(ws, results, calculer_peage=False, header_row=None):
    """Écrit KM PTV / Carte PTV / Péage, plus Statut et Contrôle quand les résultats
    en portent. Relancé sur un fichier déjà traité : les colonnes existantes sont
    réutilisées au lieu d'en ajouter de nouvelles."""
    if header_row is None:
        detected = detect_header_row(ws)
        header_row = detected if detected else 1

    header_font  = Font(bold=True, color="FFFFFF")
    header_fill  = PatternFill("solid", fgColor="2F5496")
    header_align = Alignment(horizontal="center")
    border = Border(
        left=Side(style="thin"),  right=Side(style="thin"),
        top=Side(style="thin"),   bottom=Side(style="thin"),
    )

    avec_statut = any(r and "statut" in r for r in results)
    headers = ["KM PTV", "Carte PTV"]
    if calculer_peage:
        headers.append("Péage (€)")
    if avec_statut:
        headers += ["Statut", "Contrôle"]

    col_map = {}
    prochaine = None
    for h in headers:
        col = _colonne_existante(ws, header_row, h)
        if col is None:
            if prochaine is None:
                raw_start = find_first_empty_column(ws, header_row=header_row)
                prochaine = find_safe_col(ws, header_row, raw_start)
            col = find_safe_col(ws, header_row, prochaine)
            prochaine = col + 1
        unmerge_and_write(ws, header_row, col, h, font=header_font, fill=header_fill,
                          alignment=header_align, border=border)
        col_map[h] = col
    if avec_statut:
        ws.column_dimensions[get_column_letter(col_map["Contrôle"])].width = 70
        ws.column_dimensions[get_column_letter(col_map["Statut"])].width = 12

    link_font = Font(color="0563C1", underline="single")

    for r in results:
        if r is None:
            continue
        row  = r["row"]
        data = r.get("data")

        # on vide d'abord (relance sur un fichier déjà traité)
        for h in headers:
            if h not in ("Statut", "Contrôle"):
                c = unmerge_and_write(ws, row, col_map[h], None, border=border)
                c.hyperlink = None

        if data:
            unmerge_and_write(ws, row, col_map["KM PTV"], data["km"], border=border)
            carte_url = data.get("map_url", "")
            if carte_url:
                cell = unmerge_and_write(ws, row, col_map["Carte PTV"], "Voir carte")
                cell.hyperlink = carte_url
                cell.font = link_font
                cell.border = border
            if calculer_peage:
                unmerge_and_write(ws, row, col_map["Péage (€)"], data.get("prix_peage", 0.0), border=border)

        if avec_statut:
            statut = r.get("statut", "OK" if data else "Erreur")
            c = unmerge_and_write(ws, row, col_map["Statut"], statut, border=border)
            c.fill = PatternFill("solid", fgColor=COULEURS_STATUT.get(statut, "FFFFFF"))
            unmerge_and_write(ws, row, col_map["Contrôle"], r.get("controle", "") or None, border=border,
                              alignment=Alignment(wrap_text=False))
