"""
run_km.py — Calcul KM PTV d'un fichier Excel (page « Calcul KM PTV »).

Déroulé
  1. Lecture des feuilles (en-têtes détectés, valeurs des formules) ; une feuille
     ignorée est signalée avec la raison.
  2. Géocodage de chaque lieu distinct une seule fois : table CP embarquée
     d'abord, PTV seulement pour les lieux inconnus. Chaque lieu a un niveau de
     confiance (sûr / approché / à vérifier) et une note.
  3. Un calcul PTV par trajet distinct (les lignes identiques ne sont calculées
     qu'une fois), en parallèle. Routes apprises appliquées, mode SUPER = évitement
     des péages + villes-jalons.
  4. Excel rendu : KM PTV, Carte PTV, Péage, Statut (OK / À vérifier / Erreur) et
     Contrôle (raison lisible) ; colonnes réutilisées si le fichier a déjà été traité.

Cache des trajets (cache_trajets.json, format v2) : clé = points + étapes + options,
sans le tracé ; entrées datées (péages revus après 180 jours, km après 365 jours).
"""

import datetime as _dt
import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

KM_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(KM_DIR, "cache_trajets.json")
GEOCODE_CACHE_FILE = os.path.join(KM_DIR, "cache_geocode.json")

VERSION = 4                     # lu par la page : version en mémoire périmée → rechargement
MAX_WORKERS = 6
CACHE_VERSION = 2
DUREE_CACHE_JOURS = {"peage": 180, "km": 365}
ECART_REFERENCE = 0.05          # écart toléré avec le km de référence d'une route apprise
RATIO_VOL_OISEAU = 2.2          # au-delà : tracé suspect (détour, mauvais point)

_lock = threading.Lock()


def _inject_path():
    if KM_DIR not in sys.path:
        sys.path.insert(0, KM_DIR)


# ─── Caches ──────────────────────────────────────────────────────────────────
def _lire_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
        return json.loads(txt) if txt else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _ecrire_json(path, data) -> str:
    """Écriture atomique ; renvoie un message d'erreur ('' si OK) au lieu de lever."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        return ""
    except OSError as e:
        return f"{type(e).__name__}: {e}"


def charger_cache_trajets() -> dict:
    data = _lire_json(CACHE_FILE)
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}                                      # ancien format (avec tracés, clés sans options) : ignoré
    return data.get("trajets", {})


def charger_cache_lieux() -> dict:
    data = _lire_json(GEOCODE_CACHE_FILE)
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}                                      # ancien format : points pris sans le CP, non fiables
    return data.get("lieux", {})


def _valide(entree: dict, peage: bool) -> bool:
    try:
        age = (_dt.date.today() - _dt.date.fromisoformat(entree.get("date", ""))).days
    except ValueError:
        return False
    return age <= DUREE_CACHE_JOURS["peage" if peage else "km"]


def cle_trajet(o, d, waypoints, prohibited, peage, super_pref) -> str:
    wp = hashlib.md5(json.dumps([waypoints, sorted(prohibited or [])], ensure_ascii=False,
                                default=str).encode()).hexdigest()[:10]
    return (f"{o[0]:.5f},{o[1]:.5f}|{d[0]:.5f},{d[1]:.5f}|wp={wp}"
            f"|peage={int(bool(peage))}|super={int(bool(super_pref))}")


def _vol(a, b):
    import math
    r = math.pi / 180
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


# ─── Point d'entrée ──────────────────────────────────────────────────────────
def run_calcul_km(filepath: str, calculer_peage: bool = False, super_pref: bool = False,
                  progress_callback=None, avec_cartes: bool = True) -> dict:
    _inject_path()
    stats = {
        "trajets_calcules": 0, "trajets_erreur": 0, "trajets_a_verifier": 0,
        "from_cache": 0, "trajets_distincts": 0, "appels_ptv": 0,
        "total_km": 0.0, "total_peage": 0.0,
        "resultats": [], "erreurs_detail": [], "feuilles": [], "avertissements": [],
    }

    def progress(cur, tot, msg):
        if progress_callback:
            progress_callback(cur, tot, msg)

    try:
        from modules.excel_handler_km import read_all_sheets, write_km_results, decouper_lieu
        from modules.ptv_router_km import calculate_km_route, geocode_parts, PTV_API_KEY
        from modules.routes_preferentielles import get_waypoints
        from modules import map_server_client as cartes

        if not PTV_API_KEY or PTV_API_KEY == "METS_TA_CLE_ICI":
            return {"success": False, "output_path": "", "stats": stats,
                    "error": "Clé PTV_API_KEY absente des variables d'environnement."}

        if avec_cartes:
            cartes.warm_up_async()

        # 1. Lecture ───────────────────────────────────────────────────────
        progress(0, 1, "Lecture du fichier Excel...")
        rapport = []
        wb, sheets_data = read_all_sheets(filepath, rapport=rapport)
        stats["feuilles"] = rapport
        lignes = [(nom, r) for nom, (_, routes) in sheets_data.items() for r in routes]
        if not lignes:
            return {"success": False, "output_path": "", "stats": stats,
                    "error": "Aucun trajet lu dans le fichier : voir le détail des feuilles."}

        # 2. Géocodage des lieux distincts ─────────────────────────────────
        lieux_cache = charger_cache_lieux()
        lieux = sorted({r["origin"] for _, r in lignes} | {r["dest"] for _, r in lignes})
        geo: dict[str, dict | None] = {}
        progress(0, len(lieux), f"Localisation de {len(lieux)} lieux...")

        def localiser(txt):
            if txt in lieux_cache:
                return txt, lieux_cache[txt]
            return txt, geocode_parts(*decouper_lieu(txt))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for i, fut in enumerate(as_completed([ex.submit(localiser, l) for l in lieux]), 1):
                txt, res = fut.result()
                geo[txt] = res
                if res and res.get("source") == "PTV":
                    lieux_cache[txt] = res                 # seuls les appels PTV méritent le cache
                if i % 10 == 0 or i == len(lieux):
                    progress(i, len(lieux), f"Localisation des lieux ({i}/{len(lieux)})")

        # 3. Trajets distincts ──────────────────────────────────────────────
        cache = charger_cache_trajets()
        distincts = {}
        for _, r in lignes:
            distincts.setdefault((r["origin"], r["dest"]), None)
        stats["trajets_distincts"] = len(distincts)
        total = len(distincts)
        en_vol: dict = {}

        def calculer(origin, dest):
            o, d = geo.get(origin), geo.get(dest)
            if not o or not d:
                manque = " et ".join(x for x, g in (("origine", o), ("destination", d)) if not g)
                return {"erreur": f"lieu introuvable ({manque})"}
            po, pd_ = (o["lat"], o["lon"]), (d["lat"], d["lon"])
            if _vol(po, pd_) < 0.05:
                return {"data": {"km": 0.0, "travel_time_h": 0.0, "prix_peage": 0.0, "map_url": "",
                                 "violated": False}, "cache": False,
                        "notes": ["départ et arrivée au même point"]}
            try:
                wp = get_waypoints(origin, dest, auto_jalons=super_pref, coords_origin=po, coords_dest=pd_)
            except Exception as e:
                wp = {"waypoints": [], "prohibited_countries": []}
                print(f"   ⚠️ routes apprises : {e}", flush=True)
            waypoints, prohibited = wp.get("waypoints", []), wp.get("prohibited_countries", [])
            notes = []
            if wp.get("route"):
                notes.append(f"route apprise : {wp['route']}")

            cle = cle_trajet(po, pd_, waypoints, prohibited, calculer_peage, super_pref)
            # deux libellés au même point (« Beauvais » / « Beauvais Centre ») : un seul appel PTV
            with _lock:
                verrou = en_vol.setdefault(cle, threading.Lock())
            with verrou:
                return _calculer_cle(cle, origin, dest, po, pd_, waypoints, prohibited, wp, notes)

        def _calculer_cle(cle, origin, dest, po, pd_, waypoints, prohibited, wp, notes):
            with _lock:
                en_cache = cache.get(cle)
            # entrée sans lien carte (serveur absent la fois précédente) : recalculée si on veut la carte
            if en_cache and _valide(en_cache, calculer_peage) and (en_cache.get("map_url") or not avec_cartes):
                data, depuis_cache = dict(en_cache), True
            else:
                errs = []
                with _lock:
                    stats["appels_ptv"] += 1
                route = calculate_km_route(po[0], po[1], pd_[0], pd_[1], waypoints=waypoints,
                                           calculer_peage=calculer_peage, super_pref=super_pref,
                                           prohibited_countries=prohibited, erreurs=errs)
                if not route:
                    return {"erreur": errs[0] if errs else "PTV n'a pas renvoyé d'itinéraire"}
                url = ""
                if avec_cartes:
                    try:
                        url = cartes.create_route_url(origin, dest, route["km"], route["travel_time_h"],
                                                      route.get("polyline_coords", []), route["prix_peage"])
                    except Exception as e:
                        print(f"   ⚠️ carte : {e}", flush=True)
                data = {"km": route["km"], "travel_time_h": route["travel_time_h"],
                        "prix_peage": route["prix_peage"], "violated": bool(route.get("violated")),
                        "map_url": url, "date": _dt.date.today().isoformat()}
                with _lock:
                    cache[cle] = data
                depuis_cache = False

            if data.get("violated"):
                notes.append("PTV : restriction PL sur le tracé (souvent l'accès au centre de la commune)")
            ref = wp.get("km_reference")
            if ref and data["km"] and abs(data["km"] - float(ref)) / float(ref) > ECART_REFERENCE:
                notes.append(f"écart {data['km'] - float(ref):+.0f} km avec la route apprise ({float(ref):.0f} km)")
            vol = _vol(po, pd_)
            if vol > 20 and data["km"] > RATIO_VOL_OISEAU * vol:
                notes.append(f"tracé {data['km'] / vol:.1f} × le vol d'oiseau ({vol:.0f} km) : détour suspect")
            return {"data": data, "cache": depuis_cache, "notes": notes}

        resultats_trajets = {}
        progress(0, total, f"{total} trajets distincts à calculer ({len(lignes)} lignes)")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(calculer, o, d): (o, d) for (o, d) in distincts}
            for i, fut in enumerate(as_completed(futs), 1):
                o, d = futs[fut]
                try:
                    resultats_trajets[(o, d)] = fut.result()
                except Exception as e:
                    resultats_trajets[(o, d)] = {"erreur": f"{type(e).__name__}: {e}"}
                progress(i, total, f"{o} → {d}")
                if i % 25 == 0:
                    with _lock:
                        _ecrire_json(CACHE_FILE, {"version": CACHE_VERSION, "trajets": dict(cache)})

        # 4. Lignes, contrôles, écriture ────────────────────────────────────
        progress(total, total, "Écriture du fichier...")
        par_feuille = {}
        for nom, r in lignes:
            res = resultats_trajets.get((r["origin"], r["dest"]), {"erreur": "non calculé"})
            o, d = geo.get(r["origin"]), geo.get(r["dest"])
            notes = []
            a_verifier = False
            for lib, g, txt, sans in (("origine", o, r["origin"], r.get("sans_lieu_origine")),
                                      ("destination", d, r["dest"], r.get("sans_lieu_dest"))):
                if sans and g and not g.get("note"):
                    notes.append(f"{lib} sans localité : point retenu {txt}")
                if g and g.get("note"):
                    notes.append(f"{lib} : {g['note']}")
                if g and g.get("niveau") == "à vérifier":
                    a_verifier = True
            notes += res.get("notes", [])
            # « restriction PL » (violated) reste en note : souvent le dernier tronçon vers le centre de la commune
            if any(("écart" in n) or ("détour suspect" in n) for n in res.get("notes", [])):
                a_verifier = True

            data = res.get("data")
            if not data:
                statut = "Erreur"
                notes.insert(0, res.get("erreur", "échec"))
                stats["trajets_erreur"] += 1
                stats["erreurs_detail"].append(f"Ligne {r['row']} ({nom}) : {r['origin']} → {r['dest']} — {res.get('erreur')}")
            else:
                statut = "À vérifier" if a_verifier else "OK"
                stats["trajets_calcules"] += 1
                stats["trajets_a_verifier"] += int(a_verifier)
                stats["total_km"] += data.get("km", 0) or 0
                stats["total_peage"] += data.get("prix_peage", 0) or 0
                stats["from_cache"] += int(bool(res.get("cache")))

            controle = " | ".join(notes)
            par_feuille.setdefault(nom, []).append(
                {"row": r["row"], "data": data, "statut": statut, "controle": controle})
            stats["resultats"].append({
                "Feuille": nom, "Ligne": r["row"],
                "Saisie départ": r.get("saisie_origine", ""), "Saisie arrivée": r.get("saisie_dest", ""),
                "Départ retenu": r["origin"], "Arrivée retenue": r["dest"],
                "KM": round(data["km"], 1) if data else None,
                "Durée (h)": round(data.get("travel_time_h", 0), 2) if data else None,
                "Péage (€)": round(data.get("prix_peage", 0) or 0, 2) if data and calculer_peage else None,
                "Statut": statut, "Contrôle": controle,
                "Carte": (data or {}).get("map_url", ""),
            })

        for nom, (ws, _) in sheets_data.items():
            info = next((f for f in rapport if f["feuille"] == nom), {})
            write_km_results(ws, par_feuille.get(nom, []), calculer_peage, header_row=info.get("ligne_entetes"))

        output_path = filepath.replace(".xlsx", "_KM.xlsx")
        wb.save(output_path)

        # 5. Caches (un échec d'écriture n'annule pas le calcul) ────────────
        for path, contenu in ((CACHE_FILE, {"version": CACHE_VERSION, "trajets": cache}),
                              (GEOCODE_CACHE_FILE, {"version": CACHE_VERSION, "lieux": lieux_cache})):
            err = _ecrire_json(path, contenu)
            if err:
                stats["avertissements"].append(f"Cache non enregistré ({os.path.basename(path)}) : {err}")
        if avec_cartes and cartes.serveur_disponible() is False:
            stats["avertissements"].append(f"Serveur cartes injoignable ({cartes.MAP_SERVER_URL}) : colonne « Carte PTV » vide pour les nouveaux trajets.")
        elif avec_cartes and cartes.derniere_erreur():
            stats["avertissements"].append(f"Serveur cartes en erreur ({cartes.derniere_erreur()}) : liens carte manquants.")
        n_sans = sum(1 for x in stats["resultats"] if x["KM"] is not None and not x["Carte"])
        if avec_cartes and n_sans:
            stats["avertissements"].append(f"{n_sans} trajets sans lien carte.")

        stats["resultats"].sort(key=lambda x: (x["Feuille"], x["Ligne"]))
        return {"success": True, "output_path": output_path, "error": "", "stats": stats}

    except Exception as e:
        import traceback
        return {"success": False, "output_path": "", "stats": stats,
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}
