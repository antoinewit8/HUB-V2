"""
tools/werbomont/itineraires.py — Itinéraires PTV des lignes chargement → déchargement
et passage par Werbomont.

Une ligne = une séquence d'arrêts chargés identique (C1 → … → Dn), regroupant tous
les dossiers qui la suivent. Pour chaque ligne :
  1. itinéraire PTV poids lourd C1 → … → Dn (km + tracé) ;
  2. distance minimale entre le tracé et Werbomont ;
       ≤ couloir (5 km par défaut)  → « passe par Werbomont », détour nul ;
  3. sinon, si le détour estimé reste plausible, itinéraire PTV avec Werbomont inséré
     au meilleur endroit → détour = km via Werbomont − km direct ;
  4. classement : passe · ≤ 60 km acceptable · 60–80 à vérifier · > 80 trop lourd.
Rentabilité de la ligne = Σ prix transport ÷ Σ km chargés (direct puis via Werbomont).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from .engine import COEF_ROUTE, SEUILS, WERBOMONT, hav

PTV_URL = "https://api.myptv.com/routing/v1/routes"
PTV_PROFIL = "EUR_TRAILER_TRUCK"          # même profil que tools/km_calcul/modules/ptv_router_km.py
COULOIR_KM = 5.0                          # tracé à moins de 5 km de Werbomont = « passe par »
MARGE_ESTIMATION = 40.0                   # on calcule le via-W PTV si détour estimé ≤ seuil haut + marge

CAT = {
    "passe": ("Passe par Werbomont", "#0a84ff"),
    "ok": ("Détour acceptable", "#248a3d"),
    "verif": ("Détour à vérifier", "#e8890c"),
    "lourd": ("Détour trop lourd", "#d70015"),
    "na": ("Pas encore calculé", "#8e8e93"),
}


# ─── Lignes ──────────────────────────────────────────────────────────────────
def construire_lignes(d: pd.DataFrame, min_dossiers: int = 5) -> pd.DataFrame:
    """Regroupe les dossiers (statut ok, présents dans le CA) par séquence d'arrêts chargés."""
    x = d[d["statut"].eq("ok") & d["dans_ca"]].copy()
    x = x[x["seq_charge"].map(lambda s: len(s) >= 2 and all(p[0] is not None for p in s))]
    x["ligne"] = x["seq_villes"].map(lambda s: " → ".join(s))
    g = x.groupby("ligne", sort=False)
    L = pd.DataFrame({
        "nb_dossiers": g.size(),
        "client": g["client"].agg(lambda s: s.mode().iat[0] if s.notna().any() else ""),
        "prix_moyen": g["prix"].mean(),
        "ca_total": g["prix"].sum(),
        "multi": g["multi"].first(),
        "deja_relais_W": g["passe_W_charge"].sum().astype(int),
        "premier": g["dt_C1"].min(), "dernier": g["dt_C1"].max(),
        "points": g["seq_charge"].first(),
        "villes": g["seq_villes"].first(),
    }).reset_index()
    L = L[L["nb_dossiers"] >= min_dossiers].sort_values("nb_dossiers", ascending=False).reset_index(drop=True)
    L["cle"] = L["points"].map(cle_points)
    return L


def cle_points(pts) -> str:
    return "|".join(f"{p[0]:.3f},{p[1]:.3f}" for p in pts)


def insertion_estimee(pts, w=WERBOMONT, coef=COEF_ROUTE):
    """Meilleure position d'insertion de W (vol d'oiseau × coef) → (index, détour estimé km)."""
    best, pos = None, 1
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        x = (hav(p[0], p[1], w[0], w[1]) + hav(w[0], w[1], q[0], q[1]) - hav(p[0], p[1], q[0], q[1])) * coef
        if best is None or x < best:
            best, pos = float(x), i + 1
    return pos, best


# ─── PTV ─────────────────────────────────────────────────────────────────────
def _decimer(coords, pas=0.015):
    """Allège un tracé (~1,5 km entre points) pour une carte légère."""
    if len(coords) < 3:
        return [[round(c[0], 3), round(c[1], 3)] for c in coords]
    out = [coords[0]]
    for c in coords[1:-1]:
        if abs(c[0] - out[-1][0]) + abs(c[1] - out[-1][1]) >= pas:
            out.append(c)
    out.append(coords[-1])
    return [[round(c[0], 3), round(c[1], 3)] for c in out]


def _longueur(coords) -> float:
    if len(coords) < 2:
        return 0.0
    a = np.array(coords)
    return float(hav(a[:-1, 0], a[:-1, 1], a[1:, 0], a[1:, 1]).sum())


def ptv_route(points, cle: str, timeout: int = 40):
    """Itinéraire PTV poids lourd passant par tous les points.
    Renvoie (km, tracé [[lat, lon], …], None) ou (None, None, "erreur")."""
    import requests
    params = [("profile", PTV_PROFIL), ("results", "POLYLINE")]
    params += [("waypoints", f"{float(p[0]):.6f},{float(p[1]):.6f}") for p in points]
    err = "aucune réponse"
    for essai in range(5):
        try:
            r = requests.get(PTV_URL, params=params, headers={"apiKey": cle}, timeout=timeout)
        except Exception as e:
            err = f"réseau : {type(e).__name__}"
            time.sleep(1 + essai)
            continue
        if r.status_code == 200:
            data = r.json()
            trace = []
            poly = data.get("polyline")
            if poly:
                try:
                    gj = json.loads(poly) if isinstance(poly, str) else poly
                    trace = [[c[1], c[0]] for c in gj.get("coordinates", [])]
                except Exception:
                    trace = []
            km = data.get("distance")
            km = round(km / 1000, 1) if km else (round(_longueur(trace), 1) if trace else None)
            if not km:
                return None, None, "réponse sans distance (clés : " + ", ".join(sorted(data.keys())[:8]) + ")"
            return km, trace, None
        detail = ""
        try:
            j = r.json()
            detail = j.get("description") or j.get("errorCode") or j.get("message") or ""
        except Exception:
            detail = r.text[:120]
        err = f"HTTP {r.status_code}" + (f" : {detail}" if detail else "")
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                attente = float(r.headers.get("Retry-After", 0))
            except ValueError:
                attente = 0
            time.sleep(max(attente, 2 * (essai + 1)))
            continue
        return None, None, err
    return None, None, err


def ptv_test(cle: str):
    """Un appel de contrôle Liège → Werbomont : (km, erreur)."""
    km, _, err = ptv_route([(50.6326, 5.5797), WERBOMONT], cle)
    return km, err


def distance_trace_w(trace, w=WERBOMONT) -> float:
    """Distance minimale (km) entre un tracé et Werbomont."""
    if not trace:
        return float("nan")
    a = np.array(trace)
    return float(hav(a[:, 0], a[:, 1], w[0], w[1]).min())


def calculer_lot(lignes: pd.DataFrame, cle: str, cache: dict, w=WERBOMONT, seuils=SEUILS,
                 couloir=COULOIR_KM, limite: int = 200, workers: int = 2, progression=None):
    """Calcule via PTV les lignes pas encore en cache (direct, puis via Werbomont si utile).
    cache[cle] = {"km": …, "trace": …, "dmin": …, "km_w": …, "trace_w": …}
    Renvoie (nb lignes terminées, {erreur: nb})."""
    a_faire = [r for r in lignes.itertuples(index=False) if not _complet(cache.get(r.cle), seuils, couloir, r.points, w)]
    a_faire = a_faire[:limite]
    ok, erreurs = 0, Counter()

    def traiter(r):
        e = dict(cache.get(r.cle) or {})
        if "km" not in e:
            km, tr, err = ptv_route(r.points, cle)
            if err:
                return r.cle, e, err
            e.update(km=km, trace=_decimer(tr), dmin=round(distance_trace_w(tr, w), 1))
        if _besoin_via_w(e, r.points, seuils, couloir, w) and "km_w" not in e:
            pos, _ = insertion_estimee(r.points, w)
            pts = list(r.points[:pos]) + [w] + list(r.points[pos:])
            km, tr, err = ptv_route(pts, cle)
            if err:
                return r.cle, e, err
            e.update(km_w=km, trace_w=_decimer(tr))
        return r.cle, e, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futurs = [ex.submit(traiter, r) for r in a_faire]
        for n, f in enumerate(as_completed(futurs), 1):
            k, e, err = f.result()
            if e:
                cache[k] = e
            if err:
                erreurs[err] += 1
                if err.startswith(("HTTP 401", "HTTP 403")):
                    for g in futurs:
                        g.cancel()
                    break
            else:
                ok += 1
            if progression:
                progression(n, len(a_faire), ok, sum(erreurs.values()))
    return ok, dict(erreurs)


def _besoin_via_w(e, pts, seuils, couloir, w) -> bool:
    if e.get("dmin") is None or e["dmin"] <= couloir:
        return False
    _, est = insertion_estimee(pts, w)
    return est <= seuils[1] + MARGE_ESTIMATION


def _complet(e, seuils, couloir, pts, w) -> bool:
    if not e or "km" not in e:
        return False
    return "km_w" in e or not _besoin_via_w(e, pts, seuils, couloir, w)


def a_calculer(lignes: pd.DataFrame, cache: dict, w=WERBOMONT, seuils=SEUILS, couloir=COULOIR_KM) -> int:
    return sum(not _complet(cache.get(r.cle), seuils, couloir, r.points, w) for r in lignes.itertuples(index=False))


# ─── Résultats ───────────────────────────────────────────────────────────────
def resultats(lignes: pd.DataFrame, cache: dict, w=WERBOMONT, seuils=SEUILS, couloir=COULOIR_KM) -> pd.DataFrame:
    L = lignes.copy()
    rows = []
    for r in L.itertuples(index=False):
        e = cache.get(r.cle) or {}
        pos, est = insertion_estimee(r.points, w)
        km, dmin, km_w = e.get("km"), e.get("dmin"), e.get("km_w")
        if km is None:
            cat, det, source = "na", None, ""
        elif dmin is not None and dmin <= couloir:
            cat, det, source = "passe", 0.0, "PTV"
        elif km_w is not None:
            det = round(km_w - km, 1)
            cat = "ok" if det <= seuils[0] else ("verif" if det <= seuils[1] else "lourd")
            source = "PTV"
        else:
            det = round(est, 0)                      # trop loin pour valoir un appel PTV
            cat = "ok" if det <= seuils[0] else ("verif" if det <= seuils[1] else "lourd")
            source = "estimé"
        rows.append(dict(km_direct=km, dist_w_km=dmin, km_via_w=km_w, detour_km=det, source_detour=source,
                         categorie=cat, insertion=f"{r.villes[pos - 1]} → {r.villes[pos]}"))
    R = pd.concat([L.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    km_av = R["km_direct"] * R["nb_dossiers"]
    km_ap = (R["km_direct"] + R["detour_km"].fillna(np.nan)) * R["nb_dossiers"]
    R["renta_directe"] = R["ca_total"] / km_av
    R["renta_via_w"] = R["ca_total"] / km_ap
    R["ecart_renta_pct"] = (R["renta_via_w"] / R["renta_directe"] - 1) * 100
    return R
