"""
tools/groupage/optimiseur.py — Associer des commandes en camions groupés (version test).

Entrée : une liste de commandes. Pour tester, l'export d'une période :
  • LISTES_MISSIONS (arrêts réels par dossier) et/ou
  • export CA (une adresse de chargement et de déchargement par dossier, prix, client).
Chaque dossier devient une commande : ses chargements, ses déchargements, sa date,
sa taille (part de remorque) et son prix.

Méthode : algorithme des économies (Clarke & Wright) adapté au groupage plateau.
  1. Au départ, une commande = un camion.
  2. Pour chaque paire de camions compatibles, on calcule la tournée commune :
     tous les chargements, puis tous les déchargements, chaque bloc dans le meilleur
     ordre (plus proche voisin, puis amélioration 2-opt). Économie = km séparés − km ensemble.
  3. On fusionne la paire qui économise le plus, on recalcule les économies du nouveau
     camion avec les autres, et on recommence tant qu'une fusion fait gagner des km.
  Contraintes à chaque fusion : remplissage ≤ 100 %, nombre de lots, de chargements et
  de déchargements, écart de dates, et allongement du trajet de chaque lot (du premier
  chargement au dernier déchargement de la commande) par rapport à son trajet direct.

Km = vol d'oiseau × 1,30. Trajets à vide non comptés (identiques avant/après au premier ordre).
"""

from __future__ import annotations

import heapq
import itertools

import numpy as np
import pandas as pd

from tools.crossdock import engine as X
from tools.werbomont import engine as W

COEF = X.COEF_ROUTE
CAPACITE = 100.0                 # % de remorque

# Colonnes de quantité reconnues (missions ou CA) → conversion en % de remorque
QUANTITES = [
    ("mpl", ["Mètres plancher", "Metres plancher", "MPL", "LDM", "Métrage", "Metrage", "Mètres linéaires"], 13.6),
    ("palettes", ["Palettes", "Nb palettes", "Nombre de palettes", "Nb. palettes"], 33.0),
    ("poids", ["Poids", "Poids (kg)", "Poids brut", "Poids kg", "Poids total"], 24000.0),
]
COLS_CA_ADR = {
    "dossier": ["N° Dossier", "N° dossier", "N°Dossier", "Dossier"],
    "date": ["Date chargement"],
    "client": ["Client facturation", "Client"],
    "type_transport": ["Type de transport"],
    "loc_ch": ["Localité chargement", "Localite chargement"], "cp_ch": ["C.P. chargement", "CP chargement"],
    "pays_ch": ["Pays chargement"],
    "loc_de": ["Localité déchargement", "Localite dechargement"], "cp_de": ["C.P. déchargement", "CP dechargement"],
    "pays_de": ["Pays déchargement", "Pays dechargement"],
    "prix": ["Prix transport"], "ventes": ["Total des ventes", "Total ventes"],
}


# ─── Lecture des commandes ───────────────────────────────────────────────────
def quantite_pct(raw: pd.DataFrame, cle_dossier: str = "N° Dossier") -> tuple[pd.Series | None, str]:
    """Taille en % de remorque par dossier si l'export contient une quantité (MPL, palettes, poids)."""
    low = {W.norm_txt(c): c for c in raw.columns}
    kd = low.get(W.norm_txt(cle_dossier)) or low.get("DOSSIER")
    if not kd:
        return None, ""
    for nom, cands, plein in QUANTITES:
        for c in cands:
            if W.norm_txt(c) in low:
                col = low[W.norm_txt(c)]
                v = pd.to_numeric(raw[col].astype(str).str.replace("\xa0", "").str.replace(" ", "")
                                  .str.replace(",", "."), errors="coerce")
                s = pd.DataFrame({"d": raw[kd].map(W.norm_dossier), "v": v}).dropna()
                if s.empty or s["v"].sum() <= 0:
                    continue
                return (s.groupby("d")["v"].sum() / plein * 100).clip(upper=CAPACITE), f"{col} ({nom})"
    return None, ""


def commandes_depuis_ca(raw: pd.DataFrame, geo: W.Geocodeur) -> pd.DataFrame:
    """Une commande par dossier, à partir des adresses de l'export CA."""
    c = W._mapper(raw, COLS_CA_ADR, ["dossier", "pays_ch", "cp_ch", "pays_de", "cp_de"])
    c["dossier"] = c["dossier"].map(W.norm_dossier)
    c = c[c["dossier"] != ""].copy()
    for k in ("prix", "ventes"):
        if k in c:
            c[k] = pd.to_numeric(c[k].astype(str).str.replace("\xa0", "").str.replace(" ", "")
                                 .str.replace(",", "."), errors="coerce")
    if "prix" not in c:
        c["prix"] = c.get("ventes", np.nan)
    agg = {k: "first" for k in c.columns if k not in ("dossier", "prix", "ventes")}
    agg["prix"] = "sum"
    c = c.groupby("dossier", as_index=False).agg(agg)
    cache, lignes = {}, []

    def pt(pays, cp, loc):
        iso = W.norm_iso(pays)
        k = (iso, W.norm_cp(cp, iso), W.norm_txt(loc))
        if k not in cache:
            cache[k] = X.geolocaliser(geo, *k)
        return (cache[k][0], cache[k][1]), iso, k[1]

    for r in c.itertuples(index=False):
        pc, iso_c, _ = pt(r.pays_ch, r.cp_ch, getattr(r, "loc_ch", ""))
        pd_, iso_d, cp_d = pt(r.pays_de, r.cp_de, getattr(r, "loc_de", ""))
        ok = pc[0] is not None and pd_[0] is not None
        lignes.append({
            "dossier": r.dossier, "statut": "ok" if ok else "non géolocalisé",
            "dt": pd.to_datetime(getattr(r, "date", None), errors="coerce", dayfirst=True),
            "client": str(getattr(r, "client", "") or ""), "prix": r.prix,
            "type_transport": str(getattr(r, "type_transport", "") or ""),
            "C": [pc], "D": [pd_], "seq": [pc, pd_],
            "villes_C": [f"{str(getattr(r, 'loc_ch', '')).title()} ({iso_c})"],
            "villes_D": [f"{str(getattr(r, 'loc_de', '')).title()} ({iso_d})"],
            "type": "Lot sec", "zone_livraison": X.zone(iso_d, cp_d), "tracteur": "",
        })
    return pd.DataFrame(lignes)


def commandes_depuis_missions(m: pd.DataFrame, ca: pd.DataFrame | None) -> pd.DataFrame:
    """Une commande par dossier, avec ses arrêts réels (missions) et son prix (CA)."""
    d = X.construire_dossiers(m, ca)
    villes = {}
    for dos, g in m.groupby("dossier", sort=False):
        villes[dos] = (_dedoublonner(g.loc[g["activite"] == "CHARGER", "ville"].tolist()),
                       _dedoublonner(g.loc[g["activite"] == "DECHARGER", "ville"].tolist()))
    d["villes_C"] = d["dossier"].map(lambda x: villes.get(x, ([], []))[0])
    d["villes_D"] = d["dossier"].map(lambda x: villes.get(x, ([], []))[1])
    return d


def _dedoublonner(lst):
    out = []
    for v in lst:
        if not out or out[-1] != v:
            out.append(v)
    return out


# ─── Tournées ────────────────────────────────────────────────────────────────
def _dm(points):
    a = np.array(points, float)
    return W.hav(a[:, None, 0], a[:, None, 1], a[None, :, 0], a[None, :, 1]) * COEF


def _chemin_ouvert(idx, D, depart=None):
    """Ordre de visite d'un bloc d'arrêts : plus proche voisin puis 2-opt (chemin ouvert).
    `depart` : arrêt précédent (hors bloc) d'où l'on arrive, ou None."""
    idx = list(idx)
    if len(idx) <= 1:
        return idx
    if depart is None:
        meilleur = None
        for s in idx:                       # bloc de chargement : on essaie chaque point de départ
            o = _nn(idx, D, s)
            o = _deux_opt(o, D, None)
            L = _long(o, D, None)
            if meilleur is None or L < meilleur[0]:
                meilleur = (L, o)
        return meilleur[1]
    s = min(idx, key=lambda i: D[depart, i])
    return _deux_opt(_nn(idx, D, s), D, depart)


def _nn(idx, D, s):
    reste = [i for i in idx if i != s]
    o = [s]
    while reste:
        n = min(reste, key=lambda i: D[o[-1], i])
        o.append(n)
        reste.remove(n)
    return o


def _long(o, D, depart):
    L = sum(D[o[i], o[i + 1]] for i in range(len(o) - 1))
    return L + (D[depart, o[0]] if depart is not None else 0.0)


def _deux_opt(o, D, depart):
    if len(o) < 3:
        return o
    best, Lb = o, _long(o, D, depart)
    ameliore = True
    while ameliore:
        ameliore = False
        for i in range(0, len(best) - 1):
            for j in range(i + 1, len(best)):
                c = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                Lc = _long(c, D, depart)
                if Lc < Lb - 1e-6:
                    best, Lb, ameliore = c, Lc, True
    return best


def tournee(cmds: list[dict]):
    """Tournée d'un camion : tous les chargements puis tous les déchargements.
    Renvoie (km, arrêts [(type, n° dossier, point, ville)], trajet par commande en km)."""
    arrets = []
    for c in cmds:
        for p, v in zip(c["C"], c["villes_C"] or [""] * len(c["C"])):
            arrets.append(("C", c["dossier"], p, v))
        for p, v in zip(c["D"], c["villes_D"] or [""] * len(c["D"])):
            arrets.append(("D", c["dossier"], p, v))
    D = _dm([a[2] for a in arrets])
    ic = [i for i, a in enumerate(arrets) if a[0] == "C"]
    idd = [i for i, a in enumerate(arrets) if a[0] == "D"]
    oc = _chemin_ouvert(ic, D)
    od = _chemin_ouvert(idd, D, oc[-1])
    ordre = oc + od
    cum = np.concatenate([[0.0], np.cumsum([D[ordre[k], ordre[k + 1]] for k in range(len(ordre) - 1)])])
    pos = {}
    for k, i in enumerate(ordre):
        pos.setdefault(arrets[i][1], []).append(k)
    trajet = {dos: float(cum[max(ks)] - cum[min(ks)]) for dos, ks in pos.items()}
    return float(cum[-1]), [arrets[i] for i in ordre], trajet


# ─── Optimisation ────────────────────────────────────────────────────────────
def optimiser(cmds: pd.DataFrame, p: dict, progression=None) -> tuple[list[dict], pd.DataFrame]:
    """cmds : une ligne par commande (dossier, dt, client, prix, C, D, villes_C, villes_D, taille).
    p : fenetre_jours, rayon_ch, max_lots, max_ch, max_de, allong_pct, allong_km, capacite.
    Renvoie la liste des camions et le journal des fusions."""
    c = cmds.reset_index(drop=True)
    jours = ((pd.to_datetime(c["dt"]) - pd.to_datetime(c["dt"]).min()).dt.total_seconds() / 86400).fillna(0).to_numpy()
    recs = []
    for i, r in c.iterrows():
        km, arr, _ = tournee([r.to_dict()])
        recs.append({"dossier": r["dossier"], "C": r["C"], "D": r["D"], "villes_C": r["villes_C"],
                     "villes_D": r["villes_D"], "km_seul": km, "j": jours[i], "taille": float(r["taille"])})
    camions = {i: {"cmd": [i], "km": recs[i]["km_seul"], "arrets": None, "v": 0} for i in range(len(recs))}
    c1 = np.array([recs[i]["C"][0] for i in range(len(recs))], float)

    def proches(cm_a, cm_b):
        pts_a = np.array([q for i in cm_a for q in recs[i]["C"]], float)
        pts_b = np.array([q for i in cm_b for q in recs[i]["C"]], float)
        return W.hav(pts_a[:, None, 0], pts_a[:, None, 1], pts_b[None, :, 0], pts_b[None, :, 1]).min() <= p["rayon_ch"]

    def faisable(cm):
        """Camion formé des commandes cm : (km, arrêts) s'il respecte toutes les contraintes, sinon None."""
        if not cm:
            return 0.0, []
        if sum(recs[i]["taille"] for i in cm) > p["capacite"] + 1e-9 or len(cm) > p["max_lots"]:
            return None
        js = [recs[i]["j"] for i in cm]
        if max(js) - min(js) > p["fenetre_jours"]:
            return None
        if sum(len(recs[i]["C"]) for i in cm) > p["max_ch"] or sum(len(recs[i]["D"]) for i in cm) > p["max_de"]:
            return None
        km, arr, trajet = tournee([recs[i] for i in cm])
        for i in cm:
            if len(cm) > 1 and trajet[recs[i]["dossier"]] > recs[i]["km_seul"] * (1 + p["allong_pct"] / 100) + p["allong_km"]:
                return None
        return km, arr

    def essai(a, b):
        """Fusion de deux camions si faisable et rentable : (économie, km, arrêts) ou None."""
        if not proches(camions[a]["cmd"], camions[b]["cmd"]):
            return None
        f = faisable(camions[a]["cmd"] + camions[b]["cmd"])
        if not f:
            return None
        eco = camions[a]["km"] + camions[b]["km"] - f[0]
        return (eco, f[0], f[1]) if eco > 0 else None

    tas = []
    ids = list(camions)
    ordre_j = np.argsort(jours)
    # paires initiales : fenêtre de dates glissante + chargements proches
    j0 = 0
    for k, i in enumerate(ordre_j):
        while jours[i] - jours[ordre_j[j0]] > p["fenetre_jours"]:
            j0 += 1
        cand = ordre_j[j0:k]
        if not len(cand):
            continue
        dist = W.hav(c1[i, 0], c1[i, 1], c1[cand, 0], c1[cand, 1])
        for j in cand[dist <= p["rayon_ch"] * 1.5]:
            e = essai(int(j), int(i))
            if e:
                heapq.heappush(tas, (-e[0], int(j), int(i), 0, 0))
    journal, suivant = [], len(recs)
    n_init = len(tas)
    while tas:
        neg, a, b, va, vb = heapq.heappop(tas)
        if a not in camions or b not in camions or camions[a]["v"] != va or camions[b]["v"] != vb:
            continue
        e = essai(a, b)                       # recalcul (l'état a pu changer)
        if not e:
            continue
        eco, km, arr = e
        nid = suivant
        suivant += 1
        camions[nid] = {"cmd": camions[a]["cmd"] + camions[b]["cmd"], "km": km, "arrets": arr, "v": 0}
        journal.append({"etape": len(journal) + 1, "fusion": f"{len(camions[a]['cmd'])} + {len(camions[b]['cmd'])} lots",
                        "km_gagnes": eco})
        del camions[a], camions[b]
        for o in list(camions):
            if o == nid:
                continue
            e2 = essai(nid, o)
            if e2:
                heapq.heappush(tas, (-e2[0], nid, o, 0, camions[o]["v"]))
        if progression:
            progression(len(journal), n_init)

    # Amélioration : déplacer une commande d'un camion à un autre si le total de km baisse
    # (y compris vers un camion seul, ou hors d'un groupage devenu moins bon).
    for _ in range(p.get("passes", 3)):
        deplace = 0
        for a in list(camions):
            if a not in camions:
                continue
            for i in list(camions[a]["cmd"]):
                if a not in camions or len(camions[a]["cmd"]) < 1:
                    break
                reste = [k for k in camions[a]["cmd"] if k != i]
                fa = faisable(reste)
                if fa is None:
                    continue
                meilleur = None
                for b in camions:
                    if b == a or not proches([i], camions[b]["cmd"]):
                        continue
                    fb = faisable(camions[b]["cmd"] + [i])
                    if not fb:
                        continue
                    delta = fa[0] + fb[0] - camions[a]["km"] - camions[b]["km"]
                    if delta < -1 and (meilleur is None or delta < meilleur[0]):
                        meilleur = (delta, b, fb)
                if meilleur:
                    delta, b, fb = meilleur
                    camions[b].update(cmd=camions[b]["cmd"] + [i], km=fb[0], arrets=fb[1])
                    if reste:
                        camions[a].update(cmd=reste, km=fa[0], arrets=fa[1])
                    else:
                        del camions[a]
                    journal.append({"etape": len(journal) + 1, "fusion": "déplacement d'une commande",
                                    "km_gagnes": -delta})
                    deplace += 1
        if not deplace:
            break

    res = []
    for cid, cam in camions.items():
        cm = cam["cmd"]
        if cam["arrets"] is None:
            _, cam["arrets"], _ = tournee([recs[i] for i in cm])
        res.append({"cmd": [int(i) for i in cm], "km": cam["km"], "km_seuls": sum(recs[i]["km_seul"] for i in cm),
                    "taille": sum(recs[i]["taille"] for i in cm), "arrets": cam["arrets"]})
    res.sort(key=lambda r: (-len(r["cmd"]), -(r["km_seuls"] - r["km"])))
    return res, pd.DataFrame(journal)


def plan(cmds: pd.DataFrame, camions: list[dict], cout_km: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tableaux du plan : une ligne par camion, une ligne par commande."""
    c = cmds.reset_index(drop=True)
    lignes_cam, lignes_cmd = [], []
    for n, cam in enumerate(camions, 1):
        cc = c.loc[cam["cmd"]]
        prix = cc["prix"].sum(min_count=1)
        etapes = []
        for typ, dos, _, ville in cam["arrets"]:
            mot = "Charger" if typ == "C" else "Livrer"
            if etapes and etapes[-1][0] == mot and etapes[-1][1] == ville:
                etapes[-1][2].append(dos)
            else:
                etapes.append([mot, ville, [dos]])
        itin = " → ".join(f"{m} {v} ({', '.join(ds)})" for m, v, ds in etapes)
        groupe = len(cam["cmd"]) > 1
        lignes_cam.append({
            "camion": n, "groupage": groupe, "lots": len(cam["cmd"]), "dossiers": ", ".join(cc["dossier"]),
            "clients": ", ".join(sorted(set(cc["client"].astype(str)))),
            "date": pd.to_datetime(cc["dt"]).min(), "remplissage": cam["taille"],
            "chargements": sum(1 for e in etapes if e[0] == "Charger"),
            "dechargements": sum(1 for e in etapes if e[0] == "Livrer"),
            "km": cam["km"], "km_seuls": cam["km_seuls"], "km_gagnes": cam["km_seuls"] - cam["km"],
            "gain_eur": (cam["km_seuls"] - cam["km"]) * cout_km, "prix": prix,
            "eur_km": prix / cam["km"] if cam["km"] and pd.notna(prix) else np.nan, "itineraire": itin,
            "arrets_liste": cam["arrets"],
        })
        for i in cam["cmd"]:
            r = c.loc[i]
            lignes_cmd.append({"dossier": r["dossier"], "camion": n, "groupage": groupe, "date": r["dt"],
                               "client": r["client"], "taille": r["taille"],
                               "route": f"{(r['villes_C'] or [''])[0]} → {(r['villes_D'] or [''])[-1]}",
                               "avec": ", ".join(d for d in cc["dossier"] if d != r["dossier"]), "prix": r["prix"]})
    return pd.DataFrame(lignes_cam), pd.DataFrame(lignes_cmd)
