"""
geo_offline.py — Localisation hors ligne par pays + code postal + localité.

Table GeoNames embarquée (tools/werbomont/cp_geo.csv.gz, la même que Renta Plateau,
Renta Citerne et Werbomont) : aucun appel réseau, réponse immédiate.

Ordre de recherche
  1. CP connu + localité reconnue dans ce CP (exacte, incluse, mots communs,
     orthographe proche)                                        → « sûr »
  2. CP inconnu dans le pays saisi mais CP + localité trouvés tels quels
     dans un pays voisin (ex. « F 6840 NEUFCHATEAU »)          → « à vérifier »
  3. Localité trouvée ailleurs dans le département / la zone CP
     (CP cedex, CP faux)                                         → « approché »
                                                                 ou « à vérifier »
  4. CP connu, localité non reconnue (lieu-dit, centre commercial) → centre du CP,
                                                                 « approché »
  5. Localité seule, unique dans le pays                        → « à vérifier »
  6. Zone CP (2 premiers chiffres) / département seul           → « à vérifier »

Chaque résultat porte une note lisible qui explique ce qui a été retenu.
Ce module n'importe rien d'autre du hub : il peut être chargé seul par les pages
qui simulent le paquet « modules ».
"""

from __future__ import annotations

import csv
import difflib
import gzip
import math
import os
import re
import threading
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
CP_FILE = os.path.abspath(os.path.join(_HERE, "..", "..", "werbomont", "cp_geo.csv.gz"))

SUR, APPROCHE, A_VERIFIER = "sûr", "approché", "à vérifier"

# ─── Pays ────────────────────────────────────────────────────────────────────
_PAYS = {
    "FR": ["F", "FR", "FRA", "FRANCE"],
    "BE": ["B", "BE", "BEL", "BELGIUM", "BELGIQUE", "BELGIE", "BELGIEN"],
    "LU": ["L", "LU", "LUX", "LUXEMBOURG", "LUXEMBURG", "LUXEMBURGO"],
    "DE": ["D", "DE", "DEU", "GERMANY", "ALLEMAGNE", "DEUTSCHLAND"],
    "NL": ["NL", "NLD", "NETHERLANDS", "PAYS BAS", "NEDERLAND", "HOLLANDE", "THE NETHERLANDS"],
    "IT": ["I", "IT", "ITA", "ITALY", "ITALIE", "ITALIA"],
    "ES": ["E", "ES", "ESP", "SPAIN", "ESPAGNE", "ESPANA"],
    "PT": ["P", "PT", "PRT", "PORTUGAL"],
    "CH": ["CH", "CHE", "SWITZERLAND", "SUISSE", "SCHWEIZ"],
    "AT": ["A", "AT", "AUT", "AUSTRIA", "AUTRICHE", "OSTERREICH"],
    "GB": ["GB", "UK", "GBR", "UNITED KINGDOM", "ROYAUME UNI", "GREAT BRITAIN"],
    "PL": ["PL", "POL", "POLAND", "POLOGNE", "POLSKA"],
    "CZ": ["CZ", "CZE", "CZECH REPUBLIC", "CZECHIA", "TCHEQUIE", "REPUBLIQUE TCHEQUE"],
    "DK": ["DK", "DNK", "DENMARK", "DANEMARK"],
    "SE": ["S", "SE", "SWE", "SWEDEN", "SUEDE"],
    "HU": ["H", "HU", "HUN", "HUNGARY", "HONGRIE"],
    "HR": ["HR", "HRV", "CROATIA", "CROATIE"],
    "RO": ["RO", "ROU", "ROMANIA", "ROUMANIE"],
    "BG": ["BG", "BGR", "BULGARIA", "BULGARIE"],
    "IE": ["IRL", "IE", "IRELAND", "IRLANDE"],
}
_PAYS_ALIAS = {alias: iso for iso, l in _PAYS.items() for alias in l}

# Pays voisins essayés quand le CP n'existe pas dans le pays saisi
_VOISINS = ["BE", "FR", "LU", "DE", "NL", "CH", "IT", "ES", "AT"]

# Noms usuels → nom GeoNames
_ALIAS_LIEU = {
    "BRUSSELS": "BRUXELLES", "BRUSSEL": "BRUXELLES", "BRUXELLE": "BRUXELLES",
    "ANTWERP": "ANTWERPEN", "ANVERS": "ANTWERPEN",
    "LUIK": "LIEGE", "GAND": "GENT", "GHENT": "GENT", "MALINES": "MECHELEN",
    "LOUVAIN": "LEUVEN", "COURTRAI": "KORTRIJK", "BRUGES": "BRUGGE", "OSTENDE": "OOSTENDE",
    "COLOGNE": "KOLN", "COLOGNE AM RHEIN": "KOLN", "AIX LA CHAPELLE": "AACHEN",
    "TREVES": "TRIER", "MAYENCE": "MAINZ", "MUNICH": "MUNCHEN", "FRANCFORT": "FRANKFURT AM MAIN",
    "MILAN": "MILANO", "TURIN": "TORINO", "GENES": "GENOVA",
}

_MOTS_VIDES = {"LE", "LA", "LES", "L", "D", "DE", "DU", "DES", "EN", "SUR", "SOUS", "AUX", "AU",
               "ET", "LEZ", "LES", "A", "IN", "AM", "AN", "DER", "DIE", "BEI", "VAN", "DEN", "SUD",
               "NORD", "EST", "OUEST", "CENTRE", "CEDEX", "ZI", "ZA", "ZAC", "PARC"}


def iso_pays(pays) -> str:
    """'F', 'France', 'BELGIUM', 'be' → code ISO 2 lettres ('' si vide)."""
    s = norm_lieu(pays)
    if not s:
        return ""
    return _PAYS_ALIAS.get(s, s if len(s) == 2 else "")


def norm_lieu(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    s = re.sub(r"\bSTE\b", "SAINTE", s)
    s = re.sub(r"\bST\b", "SAINT", s)
    return _ALIAS_LIEU.get(s, s)


def norm_cp(cp, iso: str) -> str:
    """CP brut (nombre Excel, texte, « L-1234 », « 6221 AB »…) → format de la table."""
    if cp is None or (isinstance(cp, float) and math.isnan(cp)):
        return ""
    if isinstance(cp, float) and cp.is_integer():
        cp = int(cp)
    s = str(cp).strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    s = re.sub(r"^(?:[A-Z]{1,3})\s*-\s*(?=\d)", "", s)       # F-59000, L-1234, B-4000, D-50769
    if iso == "GB":
        s = s.split()[0] if " " in s else (s[:-3] if len(s) >= 5 else s)
        return s
    s = s.replace(" ", "")
    if iso == "NL":
        return s[:4]
    if iso == "PT":
        return s.split("-")[0][:4]
    if iso == "PL":
        d = re.sub(r"\D", "", s)
        return f"{d[:2]}-{d[2:5]}" if len(d) == 5 else s
    if iso == "LU":
        d = re.sub(r"\D", "", s)
        return f"L-{d.zfill(4)}" if d else ""
    if iso == "RO":
        return s.zfill(6) if s.isdigit() else s
    if s.isdigit():
        if iso in ("FR", "DE", "IT", "ES") and len(s) == 4:
            return s.zfill(5)                                 # 0 initial perdu par Excel
        if iso in ("BE", "CH", "AT", "DK", "HU", "BG") and len(s) == 3:
            return s.zfill(4)
    return s


def cp_est_zone(cp, iso: str) -> bool:
    """CP réduit à un département / une zone (ex. « 13 » en France)."""
    s = re.sub(r"\D", "", str(cp or ""))
    return bool(s) and len(s) <= 2 and iso in ("FR", "DE", "IT", "ES", "BE", "NL", "LU", "CH", "AT")


def _prefixe(cp: str, iso: str) -> str:
    if iso == "LU":
        return cp[2:3]
    return cp[:2]


def _mots(s: str) -> set:
    return {m for m in s.split() if m not in _MOTS_VIDES and not m.isdigit()}


def km_vol(a, b) -> float:
    r = math.pi / 180
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def _moy(points):
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


class _Table:
    """Index construit pays par pays, à la demande : la France seule pèse ~15 Mo,
    la table complète (20 pays) n'est jamais chargée d'un bloc."""

    def __init__(self, path: str = CP_FILE):
        self.path = path
        self.lignes: dict[str, str] | None = None    # iso → lignes brutes « cp,lieu,lat,lon »
        self.par_cp: dict[tuple, list] = {}           # (iso, cp) → [(lieu, cp, lat, lon)]
        self.par_zone: dict[tuple, list] = {}         # (iso, prefixe) → idem
        self.par_lieu: dict[tuple, list] = {}         # (iso, lieu) → idem
        self.prets: set = set()
        self.verrou = threading.Lock()

    def _pays(self, iso: str):
        if iso in self.prets:
            return
        with self.verrou:
            if iso in self.prets:
                return
            if self.lignes is None:
                lignes: dict[str, list] = {}
                with gzip.open(self.path, "rt", encoding="utf-8") as f:
                    next(f)
                    for ligne in f:
                        i, _, reste = ligne.partition(",")
                        lignes.setdefault(i, []).append(reste)
                # un seul texte par pays : ~15 Mo pour toute la table au lieu de ~60 Mo de petites chaînes
                self.lignes = {i: "".join(l) for i, l in lignes.items()}
            for ligne in self.lignes.pop(iso, "").splitlines():
                try:
                    cp, lieu, la, lo = next(csv.reader([ligne]))
                    e = (lieu, cp, float(la), float(lo))
                except (ValueError, StopIteration):
                    continue
                if iso == "FR" and "CEDEX" in cp:
                    continue                          # cedex rares dans la table : on passe par la localité
                self.par_cp.setdefault((iso, cp), []).append(e)
                self.par_zone.setdefault((iso, _prefixe(cp, iso)), []).append(e)
                self.par_lieu.setdefault((iso, lieu), []).append(e)
            self.prets.add(iso)

    # ── Recherche d'une localité parmi des candidats ────────────────────────
    @staticmethod
    def _choisir(lieu: str, candidats: list, flou: float = 0.84):
        """candidats = [(nom, point)] → (points retenus, mode) ; mode ∈ exact, inclus, mots, orthographe."""
        if not lieu or not candidats:
            return [], ""
        ex = [p for n, p in candidats if n == lieu]
        if ex:
            return ex, "exact"
        inc = [p for n, p in candidats if n and (re.search(rf"\b{re.escape(n)}\b", lieu)
                                                  or re.search(rf"\b{re.escape(lieu)}\b", n))]
        if inc:
            return inc, "inclus"
        m_in = _mots(lieu)
        if m_in:
            mots = [p for n, p in candidats if n and (m_in <= set(n.split()) or (_mots(n) and _mots(n) <= m_in))]
            if mots:
                return mots, "mots"
        noms = list({n for n, _ in candidats if n})
        proches = difflib.get_close_matches(lieu, noms, n=1, cutoff=flou)
        if proches:
            return [p for n, p in candidats if n == proches[0]], f"orthographe:{proches[0]}"
        return [], ""

    @staticmethod
    def _groupe(points, rayon=20.0):
        """Points proches entre eux → moyenne ; sinon None (ambigu)."""
        if not points:
            return None
        c = _moy(points)
        return c if all(km_vol(c, p) <= rayon for p in points) else None

    def localiser(self, iso: str, cp_brut, lieu_brut) -> dict | None:
        iso = iso_pays(iso) or iso
        if not iso:
            return None
        self._pays(iso)
        lieu = norm_lieu(lieu_brut)
        zone = cp_est_zone(cp_brut, iso)
        cp = "" if zone else norm_cp(cp_brut, iso)
        if zone:
            d = re.sub(r"\D", "", str(cp_brut))
            pref = d.zfill(2) if iso == "FR" else d[:2]
        else:
            pref = _prefixe(cp, iso) if cp else ""
        lieu_aff = str(lieu_brut or "").strip()

        def res(pt, niveau, note, ref="", iso_r=None, cp_r=None):
            return {"lat": round(pt[0], 6), "lon": round(pt[1], 6), "niveau": niveau, "note": note,
                    "iso": iso_r or iso, "cp": cp if cp_r is None else cp_r, "lieu": lieu, "ref": ref}

        def cands(entrees):
            return [(e[0], (e[2], e[3])) for e in entrees]

        def cp_de(entrees, pts):
            s = sorted({e[1] for e in entrees if (e[2], e[3]) in pts})
            return s[0] if s else ""

        # 1. CP + localité
        dans_cp = self.par_cp.get((iso, cp), []) if cp else []
        if dans_cp and lieu:
            pts, mode = self._choisir(lieu, cands(dans_cp))
            c = self._groupe(pts)
            if c:
                if mode.startswith("orthographe"):
                    nom = mode.split(":", 1)[1]
                    return res(c, SUR, f"orthographe rapprochée : « {lieu_aff} » → {nom} ({cp})", nom)
                return res(c, SUR, "", lieu)

        # 2. CP absent du pays saisi : même CP + même localité chez un voisin
        if lieu and cp and not dans_cp:
            brut = str(cp_brut).strip()
            variantes = [brut] + ([brut.lstrip("0")] if brut.startswith("0") else [])
            for autre, v in ((a, v) for a in _VOISINS if a != iso for v in variantes):
                self._pays(autre)
                cp2 = norm_cp(v, autre)
                pts, mode = self._choisir(lieu, cands(self.par_cp.get((autre, cp2), [])), flou=0.92)
                c = self._groupe(pts)
                if c and mode in ("exact", "inclus"):
                    return res(c, A_VERIFIER, f"pays saisi {iso} mais {cp2} {lieu_aff} trouvé en {autre}",
                               lieu, iso_r=autre, cp_r=cp2)

        centre_cp = _moy([(e[2], e[3]) for e in dans_cp]) if dans_cp else None

        # 3. Localité dans la même zone CP (cedex, CP faux ou incomplet)
        if lieu and pref:
            zone_e = self.par_zone.get((iso, pref), [])
            pts, mode = self._choisir(lieu, cands(zone_e), flou=0.88)
            c = self._groupe(pts)
            if c:
                cp_ref = cp_de(zone_e, pts)
                ortho = mode.startswith("orthographe")
                if centre_cp is None:
                    txt = f"département {pref}" if zone else f"CP {cp_brut} inconnu"
                    note = f"{txt} : localité {lieu_aff} retenue ({cp_ref})"
                    if ortho:
                        note += f", orthographe rapprochée → {mode.split(':', 1)[1]}"
                    return res(c, A_VERIFIER if ortho else APPROCHE, note, lieu)
                d = km_vol(c, centre_cp)
                if d <= 15:
                    return res(c, APPROCHE, f"localité {lieu_aff} retenue ({cp_ref}), proche du CP {cp}", lieu)
                if not ortho:
                    return res(c, A_VERIFIER, f"CP {cp} ne correspond pas à {lieu_aff} ({cp_ref}) : "
                                              f"localité retenue, à {d:.0f} km du CP saisi", lieu)

        # 4. Localité exacte et unique dans le pays (CP d'un autre département)
        if lieu and len(lieu) >= 6:
            ex = self.par_lieu.get((iso, lieu), [])
            pts = [(e[2], e[3]) for e in ex]
            c = self._groupe(pts, rayon=25)
            if c and (centre_cp is None or km_vol(c, centre_cp) > 15):
                txt = (f"CP {cp_brut} ne correspond pas à {lieu_aff} ({ex[0][1]})" if cp_brut not in (None, "")
                       else f"pas de CP : localité {lieu_aff} ({ex[0][1]})")
                if centre_cp is not None:
                    txt += f" : localité retenue, à {km_vol(c, centre_cp):.0f} km du CP saisi"
                return res(c, A_VERIFIER, txt, lieu)

        # 5. Centre du CP
        if centre_cp:
            noms = sorted({e[0] for e in dans_cp})
            apercu = ", ".join(noms[:3]) + ("…" if len(noms) > 3 else "")
            note = (f"localité « {lieu_aff} » non reconnue : centre du CP {cp} ({apercu})" if lieu
                    else f"centre du CP {cp} ({apercu})")
            return res(centre_cp, APPROCHE if lieu else SUR, note)

        # 6. Zone CP / département
        if pref and (iso, pref) in self.par_zone:
            pts = [(e[2], e[3]) for e in self.par_zone[(iso, pref)]]
            return res(_moy(pts), A_VERIFIER, f"zone {pref} seulement (centre de la zone)")
        return None


_table: _Table | None = None
_verrou = threading.Lock()


def table() -> _Table:
    global _table
    if _table is None:
        with _verrou:
            if _table is None:
                _table = _Table()
    return _table


def disponible() -> bool:
    return os.path.exists(CP_FILE)


def localiser(pays, cp, lieu) -> dict | None:
    """(pays, CP, localité) bruts → {lat, lon, niveau, note, iso, cp, lieu} ou None."""
    if not disponible():
        return None
    return table().localiser(iso_pays(pays), cp, lieu)


_RE_ADR = re.compile(r"^\s*(?P<lieu>[^,]*?)\s*,\s*(?P<cp>[A-Za-z]{0,3}-?\s?[0-9][0-9A-Za-z\- ]{1,9})\s*,\s*(?P<pays>[^,]+?)\s*$")
_RE_CP_PAYS = re.compile(r"^\s*(?P<cp>[A-Za-z]{0,3}-?[0-9][0-9A-Za-z\- ]{0,9})\s*,\s*(?P<pays>[^,]+?)\s*$")


def decouper(adresse: str):
    """« Ville, CP, Pays » ou « CP, Pays » → (pays, cp, lieu) ; None si autre format
    (adresse avec rue, coordonnées…)."""
    a = str(adresse or "").strip()
    m = _RE_ADR.match(a)
    if m and not re.search(r"\d", m.group("lieu")):
        return m.group("pays"), m.group("cp"), m.group("lieu")
    m = _RE_CP_PAYS.match(a)
    if m:
        return m.group("pays"), m.group("cp"), ""
    return None
