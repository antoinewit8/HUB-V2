"""
tools/renta_dept/engine.py
──────────────────────────────────────────────────────────────────
Rentabilité et km à vide par département — moteur
──────────────────────────────────────────────────────────────────
Ne recalcule rien : part des résultats du moteur Renta Plateau
(`calculer` → trajets, dossiers) et les ventile par zone :
département pour la France, pays ailleurs.

Définitions
  • Repositionnement : suite de trajets à vide d'un même tracteur, du dernier
    déchargement d'un dossier au chargement suivant (arrêts intermédiaires
    — parking, garage, dépôt — compris). Statut :
      complet           — déchargement et rechargement vus dans la période ;
      début de période  — le camion est à vide dès le début du fichier ;
      fin de période    — aucun rechargement vu après le déchargement.
  • Vide de sortie (zone X) : repositionnements complets qui partent de X
    (lieu du déchargement). « Combien coûte une livraison dans X. »
  • Vide d'entrée (zone Y) : repositionnements complets qui arrivent en Y
    (lieu du rechargement). « Combien coûte d'aller charger dans Y. »
  • Rechargement local : repositionnement complet ≤ seuil km (réglable).
  • Délai avant rechargement : départ du déchargement → arrivée au chargement.
  • Zone d'un dossier : celle de ses déchargements (un dossier livré dans
    plusieurs zones est réparti au nombre d'arrêts). Chargement : idem.
  • Renta (ratio des sommes, jamais la moyenne des rentas) :
      chargée             CA / km chargés
      convention          CA / (km chargés + km à vide imputés par Renta Plateau)
      livraison + sortie  CA / (km chargés + km des repositionnements qui partent
                          de la zone, complets ou fin de période)
  • Affrétés (AFF-xxx) : comptés à part (dossiers, CA) et sortis des km à vide
    et des rentas, sauf si on demande de les inclure.
──────────────────────────────────────────────────────────────────
"""

import re

import numpy as np
import pandas as pd

SCHEMA = "dept-v1"

PAYS_FRANCE = {"F", "FR", "FRA", "FRANCE"}
PAYS_NOMS = {
    "B": "Belgique", "BE": "Belgique", "L": "Luxembourg", "LU": "Luxembourg",
    "D": "Allemagne", "DE": "Allemagne", "NL": "Pays-Bas", "I": "Italie", "IT": "Italie",
    "E": "Espagne", "ES": "Espagne", "CH": "Suisse", "A": "Autriche", "AT": "Autriche",
    "P": "Portugal", "PT": "Portugal", "GB": "Royaume-Uni", "PL": "Pologne", "CZ": "Tchéquie",
}
PAYS_ISO = {"B": "BE", "L": "LU", "D": "DE", "I": "IT", "E": "ES", "A": "AT", "P": "PT"}

DEPT_NOMS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze",
    "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne",
    "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne",
    "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise",
    "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin",
    "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe",
    "73": "Savoie", "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime",
    "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme",
    "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges",
    "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
}

STATUT_COMPLET, STATUT_DEBUT, STATUT_FIN = "complet", "début de période", "fin de période"


# ══════════════════════════════════════════════════════════════════
#  ZONES
# ══════════════════════════════════════════════════════════════════

def _clean(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    v = str(v).strip()
    return "" if v.lower() in ("nan", "none", "nat") else v


def departement(cp, pays) -> str:
    """Code département français ('57', '2A', '06') — '' si l'arrêt n'est pas en France."""
    p = _clean(pays).upper()
    s = re.sub(r"\.0+$", "", _clean(cp)).upper()
    s = re.sub(r"^(F|FR)[\s\-]*(?=\d)", "", s)
    s = re.sub(r"[^0-9AB]", "", s)
    if p and p not in PAYS_FRANCE:
        return ""
    if not s:
        return ""
    if s.isdigit() and len(s) == 4:
        if not p:                         # 4 chiffres sans pays : plutôt belge / luxembourgeois
            return ""
        s = "0" + s
    if s[:2] in ("2A", "2B"):
        return s[:2]
    if not (s.isdigit() and len(s) == 5):
        return ""
    if s.startswith("20"):
        return "2A" if int(s) < 20200 else "2B"
    if s[:2] in ("97", "98"):
        return ""                         # outre-mer : hors périmètre
    return s[:2]


def zone(lieu) -> str:
    """(ville, cp, pays) → 'FR-57' pour la France, 'BE' / 'LU'… ailleurs, '' si inconnu."""
    if not lieu or not isinstance(lieu, (tuple, list)):
        return ""
    _, cp, pays = (list(lieu) + ["", "", ""])[:3]
    d = departement(cp, pays)
    if d:
        return f"FR-{d}"
    p = _clean(pays).upper()
    if p in PAYS_FRANCE:
        return "FR-?"
    return PAYS_ISO.get(p, p)


def zone_label(z: str) -> str:
    if not z:
        return "Inconnu"
    if z.startswith("FR-"):
        d = z[3:]
        return f"{d} — {DEPT_NOMS.get(d, 'France, CP illisible' if d == '?' else '')}".rstrip(" —")
    return PAYS_NOMS.get(z, z)


def est_france(z: str) -> bool:
    return z.startswith("FR-") and z != "FR-?"


# ══════════════════════════════════════════════════════════════════
#  REPOSITIONNEMENTS (suites de trajets à vide)
# ══════════════════════════════════════════════════════════════════

def _km(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return np.nan
    return v


def repositionnements(df_traj: pd.DataFrame, affretes: set) -> pd.DataFrame:
    """Une ligne par repositionnement, tous tracteurs (affrétés marqués)."""
    cols = ["tracteur", "affrete", "statut", "dossier_prec", "dossier_suiv", "de_nom", "de", "a_nom", "a",
            "zone_de", "zone_a", "km", "km_incomplet", "nb_trajets", "de_ts", "a_ts", "delai_h"]
    if df_traj is None or df_traj.empty:
        return pd.DataFrame(columns=cols)
    out = []
    for tr, g in df_traj.groupby("tracteur", sort=True):
        g = g.sort_values("ordre").to_dict("records")
        cur = None

        def _fermer(fin_ok: bool):
            if cur is None:
                return
            cur["statut"] = (STATUT_DEBUT if not cur["dossier_prec"]
                             else STATUT_COMPLET if fin_ok else STATUT_FIN)
            out.append(cur)

        for t in g:
            if t["type"] == "À vide":
                k = _km(t.get("km"))
                if cur is None:
                    cur = dict(tracteur=tr, affrete=tr in affretes, dossier_prec=t.get("dossier_prec", ""),
                               de_nom=t.get("de_nom", ""), de=t["de"], de_ts=t.get("de_ts"),
                               km=0.0, km_incomplet=False, nb_trajets=0)
                cur["km"] += 0.0 if np.isnan(k) else k
                cur["km_incomplet"] |= bool(np.isnan(k))
                cur["nb_trajets"] += 1
                cur.update(a_nom=t.get("a_nom", ""), a=t["a"], a_ts=t.get("a_ts"),
                           dossier_suiv=t.get("dossier_suiv", ""))
            else:
                # Un trajet chargé / groupage / reconstitué suit : le camion a rechargé
                # au point de départ de ce trajet, qui est l'arrivée du dernier trajet à vide.
                _fermer(fin_ok=True)
                cur = None
        _fermer(fin_ok=False)

    df = pd.DataFrame(out)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["zone_de"] = df["de"].map(zone)
    df["zone_a"] = df["a"].map(zone)
    de_ts = pd.to_datetime(df["de_ts"], errors="coerce")
    a_ts = pd.to_datetime(df["a_ts"], errors="coerce")
    df["delai_h"] = ((a_ts - de_ts).dt.total_seconds() / 3600).round(1)
    df.loc[df["delai_h"] < 0, "delai_h"] = np.nan
    df["km"] = df["km"].round(1)
    return df[cols]


# ══════════════════════════════════════════════════════════════════
#  DOSSIERS → ZONES
# ══════════════════════════════════════════════════════════════════

def _repartition(stops: pd.DataFrame, role: str, prefix: str) -> dict:
    """dossier → {zone: poids} d'après ses arrêts CH ou DECH ; à défaut Origine / Destination."""
    rep = {}
    s = stops[stops["role"] == role]
    for d, g in s.groupby("dossier"):
        zs = [zone((r["ville"], r["cp"], r["pays"])) for r in g.to_dict("records")]
        zs = [z for z in zs if z]
        if zs:
            n = len(zs)
            rep[d] = {z: zs.count(z) / n for z in dict.fromkeys(zs)}
    for d, g in stops.groupby("dossier"):
        if d in rep:
            continue
        r = g.iloc[0]
        z = zone((r.get(f"ville_{prefix}", ""), _clean(r.get(f"cp_{prefix}", "")).split(".")[0],
                  _clean(r.get(f"pays_{prefix}", ""))))
        if z:
            rep[d] = {z: 1.0}
    return rep


def dossiers_par_zone(dt: pd.DataFrame, stops: pd.DataFrame, affretes: set) -> pd.DataFrame:
    """
    Une ligne par (tracteur, dossier, zone de déchargement), montants pondérés.
    dt = tableau dossiers de Renta Plateau (une ligne par tracteur × dossier).
    """
    rep_dech = _repartition(stops, "DECH", "dest")
    rep_ch = _repartition(stops, "CH", "orig")
    rows = []
    for r in dt.to_dict("records"):
        d = r["dossier"]
        zones = rep_dech.get(d) or {"": 1.0}
        ch = rep_ch.get(d) or {}
        z_ch = max(ch, key=ch.get) if ch else ""
        for z, w in zones.items():
            rows.append(dict(
                tracteur=r["tracteur"], dossier=d, affrete=r["tracteur"] in affretes,
                zone=z, zone_ch=z_ch, poids=w,
                km_charge=float(r.get("km_charge") or 0) * w,
                km_vide_conv=float(r.get("km_vide") or 0) * w,
                ca=float(r.get("ca") or 0) * w,
                ca_trouve=bool(r.get("ca_trouve")),
                groupage=bool(r.get("groupage")),
                client=r.get("client", ""),
                chargement=r.get("chargement", ""), dechargement=r.get("dechargement", "")))
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════
#  SYNTHÈSE PAR ZONE
# ══════════════════════════════════════════════════════════════════

def _ratio(a, b):
    return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)


def synthese_zones(dz: pd.DataFrame, rep: pd.DataFrame, stops: pd.DataFrame, affretes: set,
                   seuil_local_km: float = 50.0, min_livraisons: int = 5,
                   inclure_affretes: bool = False) -> pd.DataFrame:
    """Tableau par zone (département FR ou pays)."""
    propres = dz if inclure_affretes else dz[~dz["affrete"]]
    aff = dz[dz["affrete"]]
    rp = rep if inclure_affretes else rep[~rep["affrete"]]
    rc = rp[rp["statut"] == STATUT_COMPLET]

    # Livraisons, CA, km chargés (dossiers dont le CA est connu pour la renta)
    g = propres.groupby("zone").agg(
        livraisons=("poids", "sum"),
        dossiers=("dossier", "nunique"),
        clients=("client", lambda s: s[s != ""].nunique()),
        km_charge=("km_charge", "sum"),
        km_vide_conv=("km_vide_conv", "sum"),
        ca=("ca", "sum"),
        groupage=("poids", lambda s: float(s[propres.loc[s.index, "groupage"]].sum())),
    )
    avec_ca = propres[propres["ca_trouve"]]
    g2 = avec_ca.groupby("zone").agg(ca_r=("ca", "sum"), km_ch_r=("km_charge", "sum"),
                                     km_vc_r=("km_vide_conv", "sum"))
    ga = aff.groupby("zone").agg(livraisons_aff=("poids", "sum"), ca_aff=("ca", "sum"))

    # Vide de sortie (complets) et tous repositionnements qui partent de la zone
    gs = rc.groupby("zone_de").agg(
        sorties=("km", "size"), km_sortie=("km", "sum"), km_sortie_med=("km", "median"),
        local=("km", lambda s: int((s <= seuil_local_km).sum())),
        meme_zone=("zone_a", lambda s: int((s == rc.loc[s.index, "zone_de"]).sum())),
        delai_h=("delai_h", "mean"))
    gs_tous = rp[rp["statut"] != STATUT_DEBUT].groupby("zone_de")["km"].sum().rename("km_sortie_tous")
    # Vide d'entrée (complets)
    ge = rc.groupby("zone_a").agg(entrees=("km", "size"), km_entree=("km", "sum"))

    # Chargements dans la zone (tracteurs propres sauf demande)
    ch = stops[(stops["role"] == "CH")]
    if not inclure_affretes:
        ch = ch[~ch["tracteur"].isin(affretes)]
    zc = ch.apply(lambda r: zone((r["ville"], r["cp"], r["pays"])), axis=1) if not ch.empty else pd.Series(dtype=str)
    gc = (ch.assign(zone=zc).drop_duplicates(["tracteur", "dossier", "zone"]).groupby("zone").size()
          .rename("chargements")) if not ch.empty else pd.Series(dtype=float, name="chargements")

    t = (g.join([g2, ga, gs, gs_tous, ge, gc], how="outer").fillna(
        {c: 0 for c in ["livraisons", "dossiers", "clients", "km_charge", "km_vide_conv", "ca", "groupage",
                        "ca_r", "km_ch_r", "km_vc_r", "livraisons_aff", "ca_aff", "sorties", "km_sortie",
                        "local", "meme_zone", "km_sortie_tous", "entrees", "km_entree", "chargements"]}))
    t = t[t.index != ""]
    t.index.name = "zone"
    t = t.reset_index()

    t["vide_sortie_moy"] = _ratio(t["km_sortie"], t["sorties"])
    t["vide_entree_moy"] = _ratio(t["km_entree"], t["entrees"])
    t["pct_local"] = _ratio(t["local"] * 100, t["sorties"])
    t["pct_meme_zone"] = _ratio(t["meme_zone"] * 100, t["sorties"])
    t["renta_chargee"] = _ratio(t["ca_r"], t["km_ch_r"])
    t["renta_conv"] = _ratio(t["ca_r"], t["km_ch_r"] + t["km_vc_r"])
    # km de sortie rapportés aux seules livraisons avec CA (même proportion)
    part_ca = _ratio(t["km_ch_r"], t["km_charge"])
    t["renta_sortie"] = _ratio(t["ca_r"], t["km_ch_r"] + t["km_sortie_tous"] * np.nan_to_num(part_ca, nan=1.0))
    t["km_ch_moy"] = _ratio(t["km_charge"], t["livraisons"])
    t["pct_groupage"] = _ratio(t["groupage"] * 100, t["livraisons"])
    t["representatif"] = t["livraisons"] >= min_livraisons
    t["france"] = t["zone"].map(est_france)
    t["libelle"] = t["zone"].map(zone_label)
    t["dept"] = np.where(t["france"], t["zone"].str[3:], "")

    tot_ca = t["ca"].sum()
    t["pct_ca"] = _ratio(t["ca"] * 100, pd.Series(tot_ca, index=t.index)) if tot_ca else np.nan

    for c in ["livraisons", "groupage", "livraisons_aff"]:
        t[c] = t[c].round(1)
    for c in ["km_charge", "km_vide_conv", "km_sortie", "km_sortie_tous", "km_entree", "vide_sortie_moy",
              "vide_entree_moy", "km_sortie_med", "km_ch_moy"]:
        t[c] = pd.to_numeric(t[c], errors="coerce").round(0)
    for c in ["ca", "ca_aff", "ca_r"]:
        t[c] = t[c].round(2)
    for c in ["renta_chargee", "renta_conv", "renta_sortie"]:
        t[c] = pd.to_numeric(t[c], errors="coerce").round(3)
    for c in ["pct_local", "pct_meme_zone", "pct_groupage", "pct_ca", "delai_h"]:
        t[c] = pd.to_numeric(t[c], errors="coerce").round(1)
    return t.sort_values(["france", "ca"], ascending=[False, False]).reset_index(drop=True)


def totaux(t: pd.DataFrame) -> dict:
    """Moyennes flotte (ratio des sommes) pour comparer chaque zone."""
    s = t.sum(numeric_only=True)
    def r(a, b):
        return float(a / b) if b else np.nan
    return dict(
        livraisons=float(s.get("livraisons", 0)), ca=float(s.get("ca", 0)),
        km_charge=float(s.get("km_charge", 0)),
        renta_chargee=r(s.get("ca_r", 0), s.get("km_ch_r", 0)),
        renta_conv=r(s.get("ca_r", 0), s.get("km_ch_r", 0) + s.get("km_vc_r", 0)),
        vide_sortie_moy=r(s.get("km_sortie", 0), s.get("sorties", 0)),
        pct_local=r(100 * s.get("local", 0), s.get("sorties", 0)),
        sorties=float(s.get("sorties", 0)),
    )


def controles_dept(dz: pd.DataFrame, rep: pd.DataFrame, t: pd.DataFrame, min_livraisons: int) -> pd.DataFrame:
    rows = []
    for r in dz[dz["zone"] == ""].drop_duplicates("dossier").itertuples():
        rows.append(dict(type="Zone de déchargement inconnue", zone="", dossier=r.dossier,
                         detail="Ni arrêt DECH, ni Destination exploitable : dossier hors tableau."))
    for r in dz[dz["zone"] == "FR-?"].drop_duplicates("dossier").itertuples():
        rows.append(dict(type="Code postal français illisible", zone="FR-?", dossier=r.dossier,
                         detail=f"Déchargement : {r.dechargement}"))
    for r in rep[rep["statut"] == STATUT_FIN].itertuples():
        rows.append(dict(type="Repositionnement sans rechargement", zone=r.zone_de, dossier=r.dossier_prec,
                         detail=f"{r.tracteur} : à vide depuis {r.de[0]} ({r.km:.0f} km vus), pas de chargement "
                                f"dans la période — exclu des moyennes de vide, compté dans la renta « livraison + sortie »."))
    for r in rep[rep["km_incomplet"]].itertuples():
        rows.append(dict(type="Km à vide incomplets", zone=r.zone_de, dossier=r.dossier_prec,
                         detail=f"{r.tracteur} : un trajet sans km PTV (géocodage échoué) entre {r.de[0]} et {r.a[0]}."))
    for r in t[t["france"] & ~t["representatif"] & (t["livraisons"] > 0)].itertuples():
        rows.append(dict(type="Peu de livraisons", zone=r.zone, dossier="",
                         detail=f"{r.libelle} : {r.livraisons:g} livraison(s) < {min_livraisons} — chiffres indicatifs."))
    return pd.DataFrame(rows, columns=["type", "zone", "dossier", "detail"])


def analyser(stops: pd.DataFrame, df_traj: pd.DataFrame, dt: pd.DataFrame, seuil_local_km: float = 50.0,
             min_livraisons: int = 5, inclure_affretes: bool = False) -> dict:
    """Point d'entrée : résultats de Renta Plateau → tableaux par zone."""
    affretes = set(stops.loc[stops.get("affrete", pd.Series(False, index=stops.index)).fillna(False).astype(bool),
                             "tracteur"])
    rep = repositionnements(df_traj, affretes)
    dz = dossiers_par_zone(dt, stops, affretes)
    t = synthese_zones(dz, rep, stops, affretes, seuil_local_km, min_livraisons, inclure_affretes)
    ctrl = controles_dept(dz, rep, t, min_livraisons)
    return dict(zones=t, repositionnements=rep, dossiers=dz, controles=ctrl, totaux=totaux(t[t["france"]]),
                totaux_tous=totaux(t), affretes=sorted(affretes))
