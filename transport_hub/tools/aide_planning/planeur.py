"""
tools/aide_planning/planeur.py — calculs d'Aide planning, pensés pour la vitesse.

Deux étages :
  1. table_dossiers(df, coords) — UNE fois par fichier (mise en cache par la page) :
     une ligne par dossier (début, fin, 1er chargement, dernier déchargement, sites,
     ressources, km chargés) + les autres activités (lavages, décrochages…).
  2. vue(...) — à chaque changement de période ou de filtre : frise, indicateurs et
     tableau des ressources, calculés sur cette table (boucles Python sur quelques
     milliers de dossiers, aucun filtre pandas dans les boucles).

Entrée : activités préparées par la page (dossier, type C/D/A, _act_raw, date, _hval,
_dt, localite, cp, pays, site, chauffeur, immat, remorque, produit, type_tr, is_tra,
lieu_cle).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

import numpy as np
import pandas as pd

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MAX_LIGNES = 40
DUREE_AUTRE_H = 1.5            # largeur affichée d'un lavage / décrochage
LAVAGE = ("LAV", "NETT", "WASH", "REIN", "SPOEL", "CLEAN")
COEF_ROUTE = 1.30
DIMS = {"Remorque": "remorque", "Tracteur": "immat", "Chauffeur": "chauffeur"}


# ─── Période ────────────────────────────────────────────────────────────────
def fenetre(mode: str, pivot: dt.date, plage=None):
    """Période affichée [T0, T1[ : Jour, Semaine (lundi → dimanche), Mois, ou plage libre."""
    if mode == "Jour":
        t0 = pd.Timestamp(pivot)
        return t0, t0 + pd.Timedelta(days=1)
    if mode == "Semaine":
        t0 = pd.Timestamp(pivot) - pd.Timedelta(days=pd.Timestamp(pivot).dayofweek)
        return t0, t0 + pd.Timedelta(days=7)
    if mode == "Mois":
        t0 = pd.Timestamp(pivot).replace(day=1)
        return t0, t0 + pd.offsets.MonthBegin(1)
    a, b = plage
    return pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1)


def decaler(mode: str, pivot: dt.date, sens: int) -> dt.date:
    if mode == "Jour":
        return pivot + dt.timedelta(days=sens)
    if mode == "Semaine":
        return pivot + dt.timedelta(days=7 * sens)
    if mode == "Mois":
        return (pd.Timestamp(pivot) + pd.DateOffset(months=sens)).date()
    return pivot


def libelle_periode(t0, t1) -> str:
    fin = t1 - pd.Timedelta(days=1)
    if (t1 - t0).days == 1:
        return f"{JOURS[t0.dayofweek]} {t0:%d/%m/%Y}"
    return f"du {t0:%d/%m} au {fin:%d/%m/%Y}"


def en_tete(t0, t1, aujourdhui=None):
    """Colonnes de la grille : heures pour un jour, jours jusqu'à 31, semaines au-delà."""
    n = (t1 - t0).days
    aujourdhui = aujourdhui or dt.date.today()
    if n <= 1:
        return [{"label": f"{h:02d}h", "we": False, "auj": False} for h in range(0, 24, 3)]
    if n <= 31:
        out = []
        for i in range(n):
            d = (t0 + pd.Timedelta(days=i)).date()
            out.append({"label": f"{JOURS[d.weekday()]} {d:%d/%m}" if n <= 14 else f"{d:%d}",
                        "we": d.weekday() >= 5, "auj": d == aujourdhui})
        return out
    out, d = [], t0
    while d < t1:
        out.append({"label": f"sem. {d:%d/%m}", "we": False, "auj": False})
        d += pd.Timedelta(days=7)
    return out


def position_maintenant(t0, t1, maintenant=None):
    m = maintenant or pd.Timestamp.now()
    if t0 <= m < t1:
        return (m - t0).total_seconds() / (t1 - t0).total_seconds()
    return None


# ─── Outils ─────────────────────────────────────────────────────────────────
def _court(lieu) -> str:
    s = str(lieu or "").strip()
    return s.title() if s.isupper() else s


def _heure(t) -> str:
    return f"{JOURS[t.dayofweek]} {t:%d/%m %H:%M}" if pd.notna(t) else "—"


def _vol(a, b) -> float:
    if not a or not b:
        return float("nan")
    r = math.pi / 180
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def _chemin(points) -> float:
    pts = [p for p in points if p]
    if len(pts) < 2:
        return float("nan")
    return sum(_vol(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * COEF_ROUTE


# ─── Étage 1 : une ligne par dossier (une fois par fichier) ─────────────────
def table_dossiers(df: pd.DataFrame, coords: dict) -> tuple[pd.DataFrame, dict]:
    """(table des dossiers indexée par n° de dossier, {dossier: [autres activités]})."""
    d = df.sort_values(["dossier", "_dt", "_hval"], kind="stable")
    g = d.groupby("dossier", sort=False)
    t = g.agg(debut_any=("_dt", "min"), fin_any=("_dt", "max"),
              remorque=("remorque", "first"), immat=("immat", "first"), chauffeur=("chauffeur", "first"),
              is_tra=("is_tra", "any"), type_tr=("type_tr", "first"))
    cols = ["_dt", "localite", "cp", "pays", "site", "lieu_cle"]
    c = d[d["type"] == "C"]
    de = d[d["type"] == "D"]
    t = t.join(c.groupby("dossier", sort=False)[cols].first().add_prefix("c")) \
         .join(de.groupby("dossier", sort=False)[cols].last().add_prefix("d"))
    t["nb_c"] = c.groupby("dossier").size().reindex(t.index).fillna(0).astype(int)
    t["nb_d"] = de.groupby("dossier").size().reindex(t.index).fillna(0).astype(int)
    prod = d[d["produit"].astype(str).str.strip().ne("")].groupby("dossier")["produit"].first()
    t["produit"] = prod.reindex(t.index).fillna("")
    for k in ("c_dt", "d_dt"):
        if k not in t:
            t[k] = pd.NaT
    for k in ("clocalite", "ccp", "cpays", "csite", "clieu_cle", "dlocalite", "dcp", "dpays", "dsite", "dlieu_cle"):
        t[k] = t[k].fillna("") if k in t else ""
    t = t.rename(columns={"c_dt": "c_dt", "d_dt": "d_dt"})
    t["debut"] = t["c_dt"].fillna(t["debut_any"])
    t["fin"] = t["d_dt"].fillna(t["fin_any"])
    court = t["fin"] <= t["debut"]
    t.loc[court, "fin"] = t.loc[court, "debut"] + pd.Timedelta(hours=2)

    # km chargés : suite des chargements / déchargements du dossier
    cd = d[d["type"].isin(["C", "D"])].groupby("dossier", sort=False)["lieu_cle"].agg(list)
    t["km_charge"] = [_chemin([coords.get(k) for k in cd.get(dos, [])]) for dos in t.index]

    # autres activités (lavage, décrochage…) : (date, libellé, localité, lieu)
    a = d[d["type"] == "A"]
    autres = defaultdict(list)
    for dos, when, act, loc, cle in zip(a["dossier"], a["_dt"], a["_act_raw"], a["localite"], a["lieu_cle"]):
        autres[dos].append((when, str(act), str(loc), cle))
    return t, dict(autres)


def fiche(t: pd.DataFrame, autres: dict, dossier: str, coords: dict) -> dict | None:
    """Fiche d'un dossier pour le panneau de droite."""
    if dossier not in t.index:
        return None
    r = t.loc[dossier]
    apres = [x for x in autres.get(dossier, []) if pd.isna(r["d_dt"]) or x[0] >= r["d_dt"]]
    return {
        "dossier": str(dossier),
        "charg": _court(r["clocalite"]), "charg_pays": r["cpays"], "charg_site": r["csite"],
        "charg_quand": _heure(r["c_dt"]) if pd.notna(r["c_dt"]) else "",
        "dech": _court(r["dlocalite"]), "dech_pays": r["dpays"], "dech_site": r["dsite"],
        "dech_quand": _heure(r["d_dt"]) if pd.notna(r["d_dt"]) else "",
        "dech_point": coords.get(r["dlieu_cle"]) if r["dlieu_cle"] else None,
        "nb_charg": int(r["nb_c"]), "nb_dech": int(r["nb_d"]),
        "autres": ", ".join(f"{a.title()} ({_court(l)})" for _, a, l, _ in apres),
        "chauffeur": r["chauffeur"], "tracteur": r["immat"], "remorque": r["remorque"],
        "produit": r["produit"], "tra": bool(r["is_tra"]),
        "km_charge": None if pd.isna(r["km_charge"]) else round(r["km_charge"]),
    }


# ─── Étage 2 : une période, une dimension ───────────────────────────────────
def vue(t: pd.DataFrame, autres: dict, activites: pd.DataFrame, dim: str, t0, t1, coords: dict,
        couverture=None, maintenant=None, fins: dict | None = None) -> dict:
    """Frise + tableau des ressources + indicateurs pour [t0, t1[.

    `t` : table des dossiers déjà filtrée (flotte, métier, recherche).
    `activites` : activités des mêmes dossiers (pour les jours actifs et les écarts).
    """
    col = DIMS[dim]
    total = (t1 - t0).total_seconds()
    marge = pd.Timedelta(days=3)

    def f(x):
        return min(max((x - t0).total_seconds() / total, 0.0), 1.0)

    # Dossiers utiles : ceux qui touchent la période (± marge pour les trajets à vide)
    proche = t[(t["fin_any"] >= t0 - marge) & (t["debut_any"] < t1 + marge) & t[col].astype(str).str.strip().ne("")]
    dans = proche[(proche["fin"] > t0) & (proche["debut"] < t1)]
    act_p = activites[(activites["_dt"] >= t0) & (activites["_dt"] < t1)]
    act_p = act_p[act_p[col].astype(str).str.strip().ne("")]

    ouvres = [d.date() for d in pd.bdate_range(t0, t1 - pd.Timedelta(seconds=1))]
    if couverture:
        ouvres = [d for d in ouvres if couverture[0] <= d <= couverture[1]]
    jours_actifs = act_p.groupby(col)["date"].agg(lambda s: set(s.dt.date)).to_dict()
    ecarts = (act_p.sort_values("_dt").groupby(col)["_dt"].agg(lambda s: s.diff().max())
              .map(lambda x: x.total_seconds() / 3600 if pd.notna(x) else np.nan).to_dict())

    dans_set = set(dans.index)
    lignes, synthese = [], []
    ordre = act_p.groupby(col).size().sort_values(ascending=False).index.tolist()
    for r, grp in proche.sort_values("debut").groupby(col, sort=False):
        segs = []
        km_ch = km_vide = 0.0
        n_vide = 0
        prec = None                       # dossier précédent de la ressource
        for dos, x in zip(grp.index, grp.itertuples()):
            # à vide : dernier déchargement → autres activités → 1er chargement de celui-ci
            if prec is not None:
                p_dos, p = prec
                av = [(w, a, l, k) for (w, a, l, k) in autres.get(p_dos, []) if pd.isna(p.d_dt) or w >= p.d_dt]
                pts = [coords.get(p.dlieu_cle)] + [coords.get(k) for *_, k in av] + [coords.get(x.clieu_cle)]
                km = _chemin(pts) if x.clieu_cle and p.dlieu_cle else float("nan")
                fin_p = max([p.fin] + [w + pd.Timedelta(hours=DUREE_AUTRE_H) for w, *_ in av])
                if x.debut - fin_p > pd.Timedelta(minutes=30) and fin_p < t1 and x.debut > t0:
                    segs.append({"k": "v", "a": f(fin_p), "b": f(x.debut),
                                 "label": f"~{km:.0f} km" if km == km else "",
                                 "titre": (f"À vide : ~{km:.0f} km estimés" if km == km else "Entre deux dossiers")
                                          + f"\n{_heure(fin_p)} → {_heure(x.debut)}"})
                if t0 <= x.debut < t1 and km == km:
                    km_vide += km
                    n_vide += 1
            if x.fin > t0 and x.debut < t1:
                lab = f"{_court(x.clocalite) or '?'} → {_court(x.dlocalite) or '?'}"
                titre = (f"Dossier {dos}\nChargement {_heure(x.c_dt)} · {_court(x.clocalite)}"
                         f"\nDéchargement {_heure(x.d_dt)} · {_court(x.dlocalite)}"
                         + (f"\n{x.chauffeur}" if x.chauffeur else "") + (f" · {x.produit}" if x.produit else ""))
                segs.append({"k": "c", "a": f(x.debut), "b": f(x.fin), "label": lab, "titre": titre, "id": str(dos)})
            if t0 <= x.debut < t1 and x.km_charge == x.km_charge:
                km_ch += x.km_charge
            for w, act, loc, _ in autres.get(dos, []):
                if w >= x.debut and w < t1 and w + pd.Timedelta(hours=DUREE_AUTRE_H) > t0:
                    lav = any(m in act.upper() for m in LAVAGE)
                    segs.append({"k": "l" if lav else "a", "a": f(w), "b": f(w + pd.Timedelta(hours=DUREE_AUTRE_H)),
                                 "label": act.title(), "titre": f"{act.title()} · {_court(loc)}\n{_heure(w)}"})
            prec = (dos, x)
        # « Et après ? » : barre fantôme après le dernier dossier connu
        fin = (fins or {}).get(r)
        if fin and t0 - pd.Timedelta(days=1) <= fin["libre"] < t1:
            a = fin["libre"]
            sug = fin.get("sugs") or []
            lab = f"→ {sug[0]['lieu'].split(' (')[0]} ?" if sug else "Libre"
            titre = f"Libre {_heure(a)} à {fin['lieu']}"
            if sug:
                titre += "\nRecharges habituelles d’ici :" + "".join(f"\n• {x}" for x in fin.get("textes", []))
            else:
                titre += "\nPas d’historique de rechargement autour de ce lieu."
            segs.append({"k": "g", "a": f(a), "b": f(min(a + pd.Timedelta(hours=16), t1)), "label": lab,
                         "titre": titre + "\nCliquer pour les détails", "id": str(fin["dossier"])})
        n_dans = sum(1 for d in grp.index if d in dans_set)
        if r not in jours_actifs and not n_dans:
            continue                      # aucune activité sur la période
        actifs = jours_actifs.get(r, set())
        # Jour « sans activité » : aucune activité ce jour-là ET aucun trajet (en charge ou à vide)
        # qui le traverse — un camion qui roule à vide toute la journée n'est pas à l'arrêt.
        couverts = [(s_["a"], s_["b"]) for s_ in segs if s_["k"] in ("c", "v")]

        def _couvert(j):
            a_ = f(pd.Timestamp(j) + pd.Timedelta(hours=6))
            b_ = f(pd.Timestamp(j) + pd.Timedelta(hours=18))
            return any(a1 < b_ and b1 > a_ for a1, b1 in couverts)
        sans = [j for j in ouvres if j not in actifs and not _couvert(j)]
        fantome = [(x_["a"], x_["b"]) for x_ in segs if x_["k"] == "g"]
        if len(ouvres) and (t1 - t0).days > 1:
            for j in sans:
                aj, bj = f(pd.Timestamp(j)), f(pd.Timestamp(j) + pd.Timedelta(days=1))
                if any(a1 < bj and b1 > aj for a1, b1 in fantome):
                    continue
                a = pd.Timestamp(j)
                segs.append({"k": "o", "a": f(a), "b": f(a + pd.Timedelta(days=1)), "label": "sans activité",
                             "titre": f"Aucune activité le {JOURS[a.dayofweek].lower()} {a:%d/%m}"})
        tra = bool(grp["is_tra"].any())
        sous = []
        if col != "chauffeur":
            ch = sorted({c for d, c in zip(grp.index, grp["chauffeur"]) if d in dans_set and str(c).strip()})
            if ch:
                sous.append(", ".join(ch[:2]) + ("…" if len(ch) > 2 else ""))
        if km_vide:
            sous.append(f"~{km_vide:.0f} km à vide")
        lignes.append({"nom": str(r), "sous": " · ".join(sous), "tra": tra,
                       "segs": sorted(segs, key=lambda s: {"o": 0, "v": 1, "a": 2, "l": 2, "g": 3, "c": 4}[s["k"]])})
        synthese.append({
            "Ressource": r, "Dossiers": n_dans, "Jours actifs": len(actifs),
            "Jours ouvrés sans activité": len(sans),
            "Dates sans activité": ", ".join(x.strftime("%d/%m") for x in sans[:8]) + (" …" if len(sans) > 8 else ""),
            "Plus long écart (h)": round(ecarts.get(r, np.nan), 2) if ecarts.get(r) == ecarts.get(r) else np.nan,
            "Km chargés estimés": round(km_ch), "Km à vide estimés": round(km_vide),
            "Part à vide": km_vide / (km_ch + km_vide) if (km_ch + km_vide) > 0 else np.nan,
            "Repositionnements": n_vide,
        })
    rang = {r: i for i, r in enumerate(ordre)}
    lignes.sort(key=lambda l: rang.get(l["nom"], len(rang)))
    tab = pd.DataFrame(synthese)
    if not tab.empty:
        tab = tab.sort_values(["Jours ouvrés sans activité", "Part à vide"], ascending=[False, False])
    return {
        "jours": en_tete(t0, t1),
        "lignes": lignes[:MAX_LIGNES], "n_lignes": len(lignes),
        "synthese": tab,
        "dossiers_periode": dans.index.tolist(),
        "maintenant": position_maintenant(t0, t1, maintenant),
    }
