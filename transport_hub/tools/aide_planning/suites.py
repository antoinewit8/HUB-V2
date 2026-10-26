"""
tools/aide_planning/suites.py — « et après ? » pour Aide planning.

À partir de la table des dossiers (planeur.table_dossiers) :
  • creneaux()     : pour chaque ressource, ses moments libres — après chaque dossier,
                     jusqu'au dossier suivant (trou) ou sans fin (dernier dossier connu) —
                     avec le lieu où elle se trouve (dernier déchargement, puis lavage /
                     décrochage éventuels) ;
  • historique()   : tous les enchaînements passés « déchargé en A → rechargé en B »
                     de la même remorque (à défaut tracteur ; affrétés exclus) ;
  • suggestions()  : depuis un point, les rechargements qui ont le mieux marché ;
  • a_placer()     : dossiers sans remorque ni tracteur, et les ressources libres qui
                     peuvent les prendre (arrivée à l'heure, km à vide ajoutés).

Km = vol d'oiseau × 1,30 ; temps de route = km ÷ 60 km/h.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

COEF_ROUTE = 1.30
VITESSE_KMH = 60.0
DUREE_AUTRE_H = 1.5
ECART_MAX_JOURS = 5          # au-delà, le dossier suivant n'est plus « la suite »
LIBRE_MAX_JOURS = 7          # ressource libre depuis plus longtemps : sans doute active hors export
RAYON_KM = 25


def _vol(a, b) -> float:
    if not a or not b:
        return float("nan")
    r = math.pi / 180
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def km(a, b) -> float:
    return _vol(a, b) * COEF_ROUTE


def _court(lieu) -> str:
    s = str(lieu or "").strip()
    return s.title() if s.isupper() else s


def _vide(v) -> bool:
    return str(v or "").strip().upper() in ("", "NAN", "NONE")


def metier(type_tr) -> str:
    s = str(type_tr or "").upper()
    return "CIT" if "CIT" in s else ("PLA" if "PLA" in s else "")


def non_attribues(t: pd.DataFrame) -> pd.DataFrame:
    """Dossiers sans remorque ni tracteur : commandes à placer."""
    return t[t["remorque"].map(_vide) & t["immat"].map(_vide)]


def _fin_reelle(r, autres, coords):
    """(heure, point, libellé) où la ressource est libre après le dossier r."""
    fin, pt, lieu = r.fin, coords.get(r.dlieu_cle) if r.dlieu_cle else None, _court(r.dlocalite)
    for w, act, loc, cle in autres.get(r.Index, []):
        if pd.notna(r.d_dt) and w < r.d_dt:
            continue
        fin = max(fin, w + pd.Timedelta(hours=DUREE_AUTRE_H))
        if coords.get(cle):
            pt, lieu = coords.get(cle), f"{_court(loc)} ({str(act).title()})"
    return fin, pt, lieu


# ─── Créneaux libres ────────────────────────────────────────────────────────
def creneaux(t: pd.DataFrame, autres: dict, coords: dict, col: str) -> pd.DataFrame:
    """Une ligne par moment libre d'une ressource (col = remorque, immat ou chauffeur)."""
    x = t[~t[col].map(_vide)].sort_values("debut")
    lignes = []
    for res, g in x.groupby(col, sort=False):
        rows = list(g.itertuples())
        met = pd.Series([metier(r.type_tr) for r in rows]).mode()
        met = met.iat[0] if len(met) else ""
        tra = any(bool(r.is_tra) for r in rows)
        for i, r in enumerate(rows):
            libre, pt, lieu = _fin_reelle(r, autres, coords)
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            lignes.append({
                "ressource": res, "apres": r.Index, "libre": libre, "point": pt, "lieu": lieu,
                "jusqua": nxt.debut if nxt else pd.NaT,
                "point_suivant": (coords.get(nxt.clieu_cle) if nxt and nxt.clieu_cle else None),
                "suivant": nxt.Index if nxt else "", "lieu_suivant": _court(nxt.clocalite) if nxt else "",
                "metier": met, "tra": tra, "chauffeur": r.chauffeur, "remorque": r.remorque, "tracteur": r.immat,
            })
    return pd.DataFrame(lignes)


def suite_du_dossier(cren: pd.DataFrame, dossier: str) -> dict | None:
    """Ce que fait la ressource après ce dossier."""
    if cren.empty:
        return None
    c = cren[cren["apres"] == dossier]
    if c.empty:
        return None
    r = c.iloc[0]
    return r.to_dict()


# ─── Historique des rechargements ───────────────────────────────────────────
def historique(t: pd.DataFrame, autres: dict, coords: dict, prix: dict | None = None) -> pd.DataFrame:
    """Enchaînements passés A → B de la même citerne / remorque (à défaut tracteur)."""
    prix = prix or {}
    x = t.copy()
    rem = x["remorque"].map(lambda v: "" if _vide(v) else str(v))
    tra = x["immat"].map(lambda v: "" if _vide(v) else str(v))
    x["_veh"] = np.where(rem.ne(""), "R:" + rem, np.where(tra.ne("") & ~tra.str.upper().str.startswith("AFF"),
                                                          "T:" + tra, ""))
    x = x[x["_veh"].ne("")].sort_values("debut")
    rows = []
    for _, g in x.groupby("_veh", sort=False):
        rr = list(g.itertuples())
        for a, b in zip(rr[:-1], rr[1:]):
            fin, pa, _ = _fin_reelle(a, autres, coords)
            pd_ = coords.get(a.dlieu_cle) if a.dlieu_cle else None
            pb = coords.get(b.clieu_cle) if b.clieu_cle else None
            if not pd_ or not pb:
                continue
            ecart = (b.debut - a.fin).total_seconds() / 3600
            if ecart < -12 or ecart > ECART_MAX_JOURS * 24:
                continue
            kv = km(pd_, pa) + km(pa, pb) if pa and pa != pd_ else km(pd_, pb)
            p = prix.get(str(b.Index))
            kc = b.km_charge if b.km_charge == b.km_charge else np.nan
            pf = pa or pd_
            rows.append({"A_lat": pd_[0], "A_lon": pd_[1], "F_lat": pf[0], "F_lon": pf[1],
                         "B_lat": pb[0], "B_lon": pb[1],
                         "B_lieu": f"{_court(b.clocalite)} ({b.cpays})", "B_cle": b.clieu_cle,
                         "ecart_h": ecart, "km_vide": kv, "km_charge": kc, "prix": p,
                         "metier": metier(b.type_tr), "B_dossier": b.Index, "B_dt": b.debut})
    return pd.DataFrame(rows)


def suggestions(hist: pd.DataFrame, point, rayon_km: float = RAYON_KM, n: int = 3, metier_: str = "") -> list:
    """Rechargements les plus porteurs après un déchargement près de `point`."""
    if hist is None or hist.empty or not point:
        return []
    r = math.pi / 180

    def dist(la, lo):
        h = (np.sin((la - point[0]) * r / 2) ** 2 + np.cos(point[0] * r) * np.cos(la * r) * np.sin((lo - point[1]) * r / 2) ** 2)
        return 12742 * np.arcsin(np.sqrt(np.minimum(1, h)))
    # point = lieu où le camion est libre (déchargement, ou lavage / décrochage ensuite) :
    # on compare aux deux lieux de chaque enchaînement passé
    d = np.minimum(dist(hist["A_lat"].to_numpy(), hist["A_lon"].to_numpy()),
                   dist(hist["F_lat"].to_numpy(), hist["F_lon"].to_numpy()))
    z = hist[d <= rayon_km]
    if metier_:
        z = z[z["metier"].isin([metier_, ""])]
    if z.empty:
        return []
    z = z.assign(_tot=z["km_vide"] + z["km_charge"].fillna(0))
    out = []
    for cle, g in z.groupby("B_cle"):
        okp = g["prix"].notna() & (g["_tot"] > 0)
        out.append({
            "lieu": g["B_lieu"].iat[0], "frequence": len(g),
            "km_vide": float(g["km_vide"].mean()), "ecart_h": float(g["ecart_h"].median()),
            "renta": float(g.loc[okp, "prix"].sum() / g.loc[okp, "_tot"].sum()) if okp.any() else None,
            "lat": float(g["B_lat"].mean()), "lon": float(g["B_lon"].mean()),
            "dernier": g["B_dt"].max(),
        })
    avec_renta = any(o["renta"] is not None for o in out)
    # une recharge vue au moins deux fois passe avant un coup isolé, puis renta (ou fréquence sans CA)
    out.sort(key=lambda o: (o["frequence"] < 2, -(o["renta"] or 0), -o["frequence"]) if avec_renta
             else (-o["frequence"], o["km_vide"]))
    return out[:n]


def texte_suggestion(s: dict) -> str:
    bits = [f'{s["frequence"]}×', f'~{s["km_vide"]:.0f} km à vide', f'rechargé en {s["ecart_h"]:.0f} h']
    if s.get("renta") is not None:
        bits.insert(0, f'{s["renta"]:.2f} €/km'.replace(".", ","))
    return f'{s["lieu"]} · ' + " · ".join(bits)


# ─── Commandes à placer ─────────────────────────────────────────────────────
def a_placer(t: pd.DataFrame, cren: pd.DataFrame, coords: dict, t0, t1, n: int = 3,
             inclure_tra: bool = True) -> list:
    """Dossiers non attribués chargés dans [t0, t1[ et les ressources qui peuvent les prendre."""
    na = non_attribues(t)
    na = na[(na["debut"] >= t0) & (na["debut"] < t1)].sort_values("debut")
    if na.empty:
        return []
    c = cren.dropna(subset=["libre"]).copy() if not cren.empty else cren
    if c is not None and not c.empty:
        c = c[c["point"].notna()]
        if not inclure_tra:
            c = c[~c["tra"]]
    res = []
    for r in na.itertuples():
        pc = coords.get(r.clieu_cle) if r.clieu_cle else None
        pdch = coords.get(r.dlieu_cle) if r.dlieu_cle else None
        met = metier(r.type_tr)
        cands = []
        if pc is not None and c is not None and not c.empty:
            for s in c.itertuples():
                if s.libre > r.debut:
                    continue
                if pd.isna(s.jusqua) and s.libre < r.debut - pd.Timedelta(days=LIBRE_MAX_JOURS):
                    continue
                if met and s.metier and met != s.metier:
                    continue
                kv = km(s.point, pc)
                arrivee = s.libre + pd.Timedelta(hours=kv / VITESSE_KMH)
                if arrivee > r.debut + pd.Timedelta(hours=1):
                    continue
                ajout = kv
                if pd.notna(s.jusqua):
                    # il faut finir ce dossier et rejoindre le suivant à temps
                    if pdch is None or s.point_suivant is None:
                        continue
                    retour = km(pdch, s.point_suivant)
                    if r.fin + pd.Timedelta(hours=retour / VITESSE_KMH) > s.jusqua:
                        continue
                    ajout = kv + retour - km(s.point, s.point_suivant)
                cands.append({
                    "ressource": s.ressource, "lieu": s.lieu, "libre": s.libre, "km_vide": kv,
                    "km_ajoutes": ajout, "marge_h": (r.debut - arrivee).total_seconds() / 3600,
                    "trou": pd.notna(s.jusqua), "suivant": s.lieu_suivant, "jusqua": s.jusqua,
                    "chauffeur": s.chauffeur, "tra": bool(s.tra),
                })
        cands.sort(key=lambda x: (x["km_ajoutes"], -x["marge_h"]))
        # une ressource n'apparaît qu'une fois (son meilleur créneau)
        vus, uniques = set(), []
        for x in cands:
            if x["ressource"] in vus:
                continue
            vus.add(x["ressource"])
            uniques.append(x)
        res.append({
            "dossier": r.Index, "charg": _court(r.clocalite), "charg_pays": r.cpays, "debut": r.debut,
            "dech": _court(r.dlocalite), "dech_pays": r.dpays, "fin": r.fin, "produit": r.produit,
            "metier": met, "km_charge": None if r.km_charge != r.km_charge else round(r.km_charge),
            "localise": pc is not None, "candidats": uniques[:n], "nb_candidats": len(uniques),
        })
    return res
