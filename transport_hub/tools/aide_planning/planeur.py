"""
tools/aide_planning/planeur.py — données de la frise « planeur » d'Aide planning.

Entrée : les activités préparées par la page (colonnes dossier, type C/D/A, _act_raw,
date, _hval, _dt, localite, cp, pays, site, chauffeur, immat, remorque, produit,
type_tr, is_tra, lieu_cle). Sortie : jours (en-tête), lignes (une par ressource,
segments en fraction de la période) et le détail de chaque dossier.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MAX_LIGNES = 40
DUREE_AUTRE_H = 1.5            # largeur affichée d'un lavage / décrochage
LAVAGE = ("LAV", "NETT", "WASH", "REIN", "SPOEL", "CLEAN")


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
    """Colonnes de la grille : heures pour un jour, jours sinon (au-delà de 31 jours : semaines)."""
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


def details_dossier(h: pd.DataFrame, coords: dict, coef: float = 1.30) -> dict:
    """Fiche d'un dossier (ses activités triées)."""
    c = h[h["type"] == "C"]
    d = h[h["type"] == "D"]
    a = h[h["type"] == "A"]
    c0 = c.iloc[0] if len(c) else None
    d1 = d.iloc[-1] if len(d) else None
    seq = [coords.get(k) for k in h.loc[h["type"].isin(["C", "D"]), "lieu_cle"]]
    seq = [p for p in seq if p]
    km = sum(_vol(seq[i], seq[i + 1]) for i in range(len(seq) - 1)) * coef if len(seq) > 1 else float("nan")
    base = c0 if c0 is not None else (d1 if d1 is not None else h.iloc[0])
    return {
        "dossier": str(base["dossier"]),
        "charg": _court(c0["localite"]) if c0 is not None else "",
        "charg_pays": c0["pays"] if c0 is not None else "",
        "charg_site": c0["site"] if c0 is not None else "",
        "charg_quand": _heure(c0["_dt"]) if c0 is not None else "",
        "nb_charg": len(c), "nb_dech": len(d),
        "dech": _court(d1["localite"]) if d1 is not None else "",
        "dech_pays": d1["pays"] if d1 is not None else "",
        "dech_site": d1["site"] if d1 is not None else "",
        "dech_quand": _heure(d1["_dt"]) if d1 is not None else "",
        "dech_point": coords.get(d1["lieu_cle"]) if d1 is not None else None,
        "autres": ", ".join(f'{str(x).title()} ({_court(l)})' for x, l in zip(a["_act_raw"], a["localite"])),
        "chauffeur": base["chauffeur"], "tracteur": base["immat"], "remorque": base["remorque"],
        "produit": next((p for p in h["produit"] if str(p).strip()), ""),
        "metier": base.get("type_tr", ""), "tra": bool(h["is_tra"].any()),
        "km_charge": None if np.isnan(km) else round(km),
    }


def construire(dfx: pd.DataFrame, dim_col: str, t0, t1, coords: dict, vides: dict, synthese: pd.DataFrame | None,
               maintenant=None, couverture=None) -> tuple[list, list, dict]:
    """(jours, lignes, détails) pour la frise. `couverture` = (1er jour, dernier jour) de l'export :
    hors de ces dates, une journée vide n'est pas « sans activité », elle est hors fichier."""
    total = (t1 - t0).total_seconds()
    marge = pd.Timedelta(days=3)

    def f(t):
        return min(max((t - t0).total_seconds() / total, 0.0), 1.0)

    def dans(a, b):
        return b > t0 and a < t1

    jours = en_tete(t0, t1, (maintenant or pd.Timestamp.now()).date() if maintenant is not None else None)
    zone = dfx[(dfx["_dt"] >= t0 - marge) & (dfx["_dt"] < t1 + marge)]
    zone = zone[zone[dim_col].astype(str).str.strip().ne("")]
    actifs_periode = zone[(zone["_dt"] >= t0) & (zone["_dt"] < t1)]
    ordre = actifs_periode.groupby(dim_col).size().sort_values(ascending=False).index.tolist()[:MAX_LIGNES]
    info = synthese.set_index("Ressource") if synthese is not None and not synthese.empty else pd.DataFrame()
    ouvres = [d.date() for d in pd.bdate_range(t0, t1 - pd.Timedelta(seconds=1))]
    if couverture:
        ouvres = [d for d in ouvres if couverture[0] <= d <= couverture[1]]

    lignes, details = [], {}
    for r in ordre:
        g = zone[zone[dim_col] == r].sort_values(["_dt", "_hval"], kind="stable")
        segs = []
        fin_prec = None
        for dos, h in sorted(g.groupby("dossier", sort=False), key=lambda x: x[1]["_dt"].min()):
            h = h.sort_values(["_dt", "_hval"], kind="stable")
            details[str(dos)] = details_dossier(h, coords)
            c = h[h["type"] == "C"]
            d = h[h["type"] == "D"]
            debut = c["_dt"].iloc[0] if len(c) else h["_dt"].iloc[0]
            fin = d["_dt"].iloc[-1] if len(d) else h["_dt"].iloc[-1]
            if fin <= debut:
                fin = debut + pd.Timedelta(hours=2)
            # à vide depuis la fin du dossier précédent
            if fin_prec is not None and debut - fin_prec > pd.Timedelta(minutes=30) and dans(fin_prec, debut):
                km = vides.get((r, dos))
                segs.append({"k": "v", "a": f(fin_prec), "b": f(debut),
                             "label": f"~{km:.0f} km" if km else "",
                             "titre": (f"À vide : ~{km:.0f} km estimés" if km else "Entre deux dossiers")
                                      + f"\n{_heure(fin_prec)} → {_heure(debut)}"})
            if dans(debut, fin):
                det = details[str(dos)]
                lab = f'{det["charg"] or "?"} → {det["dech"] or "?"}'
                titre = (f'Dossier {dos}\nChargement {det["charg_quand"]} · {det["charg"]}'
                         f'\nDéchargement {det["dech_quand"]} · {det["dech"]}'
                         + (f'\n{det["chauffeur"]}' if det["chauffeur"] else "")
                         + (f' · {det["produit"]}' if det["produit"] else ""))
                segs.append({"k": "c", "a": f(debut), "b": f(fin), "label": lab, "titre": titre, "id": str(dos)})
            fin_prec = fin
            for _, x in h[h["type"] == "A"].iterrows():
                a = x["_dt"]
                if a < debut:
                    continue
                b = a + pd.Timedelta(hours=DUREE_AUTRE_H)
                if dans(a, b):
                    lav = any(m in str(x["_act_raw"]).upper() for m in LAVAGE)
                    segs.append({"k": "l" if lav else "a", "a": f(a), "b": f(b),
                                 "label": str(x["_act_raw"]).title(),
                                 "titre": f'{str(x["_act_raw"]).title()} · {_court(x["localite"])}\n{_heure(a)}'})
                fin_prec = max(fin_prec, b)
        actifs = set(g["date"].dropna().dt.date)
        for j in ouvres:
            if j not in actifs and len(jours) > 1:
                a = pd.Timestamp(j)
                segs.append({"k": "o", "a": f(a), "b": f(a + pd.Timedelta(days=1)), "label": "sans activité",
                             "titre": f"Aucune activité le {JOURS[a.dayofweek].lower()} {a:%d/%m}"})
        sous = []
        if dim_col != "chauffeur":
            ch = sorted({x for x in g["chauffeur"] if str(x).strip()})
            if ch:
                sous.append(", ".join(ch[:2]) + ("…" if len(ch) > 2 else ""))
        if r in info.index and info.loc[r, "Km à vide estimés"]:
            sous.append(f'~{int(info.loc[r, "Km à vide estimés"])} km à vide')
        lignes.append({"nom": str(r), "sous": " · ".join(sous), "tra": bool(g["is_tra"].any()),
                       "segs": sorted(segs, key=lambda s: {"o": 0, "v": 1, "a": 2, "l": 2, "c": 3}[s["k"]])})
    return jours, lignes, details


def position_maintenant(t0, t1, maintenant=None):
    m = maintenant or pd.Timestamp.now()
    if t0 <= m < t1:
        return (m - t0).total_seconds() / (t1 - t0).total_seconds()
    return None
