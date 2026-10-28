"""
Stations de lavage citerne pour l'option « Stations de lavage » de la Carte manuelle.

Source, par ordre de priorité :
1. data/lavages/stations.json : base enregistrée automatiquement par la page Optimisateur Lavages
   (dernier calcul) ou chargée depuis la page Carte manuelle. Disque éphémère sur le cloud :
   perdue au redémarrage.
2. assets/lavages_stations.xlsx : base géocodée versionnée dans le dépôt (le fichier
   « base_stations_lavage.xlsx » téléchargé depuis la page Lavages, renommé).

Seuls les lieux de type « station » sont gardés : les « laiteries » (lavage fait chez le
client, « Nom 2 » vide dans le fichier lavages) ne sont pas des stations où passer.
"""

from __future__ import annotations

import json
import math
import unicodedata
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HUB_DIR = Path(__file__).resolve().parents[2]
ASSET = HUB_DIR / "assets" / "lavages_stations.xlsx"
LOCAL = HUB_DIR / "data" / "lavages" / "stations.json"

# Colonnes de la base géocodée (page Lavages) et alias tolérés
COLS = {
    "n": ["NOM", "NOM 1", "STATION", "NAME"],
    "a": ["ADRESSE", "ADRESSE 1", "RUE"],
    "cp": ["CP", "CODE POSTAL"],
    "v": ["LOCALITE", "VILLE", "COMMUNE"],
    "p": ["PAYS", "COUNTRY"],
    "la": ["LAT", "LATITUDE"],
    "lo": ["LON", "LONGITUDE", "LNG"],
    "t": ["TYPE"],
    "nb": ["NB", "NOMBRE", "NB LAVAGES"],
    "pm": ["PRIX MED", "PRIX MEDIAN"],
    "pd": ["DERNIER PRIX"],
    "dl": ["DERNIER LAVAGE"],
    "tel": ["TELEPHONE", "TEL"],
    "st": ["STATUT"],
}


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").upper().replace("_", " "))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


def _date(v) -> str:
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return "" if pd.isna(v) else v.strftime("%Y-%m-%d")
    s = _txt(v)
    if not s:
        return ""
    d = pd.to_datetime(s, errors="coerce", dayfirst=not re.match(r"\d{4}-", s))
    return "" if pd.isna(d) else d.strftime("%Y-%m-%d")


def compacter(df: pd.DataFrame) -> list[dict]:
    """Base géocodée (colonnes de la page Lavages ou alias) → liste compacte pour la carte."""
    noms = {_norm(c): c for c in df.columns}
    col = {k: next((noms[a] for a in alias if a in noms), None) for k, alias in COLS.items()}
    if not col["la"] or not col["lo"] or not col["n"]:
        raise ValueError("colonnes nom, lat et lon introuvables")
    out = []
    for r in df.to_dict("records"):
        la, lo = _num(r.get(col["la"])), _num(r.get(col["lo"]))
        if la is None or lo is None or not (-90 <= la <= 90 and -180 <= lo <= 180):
            continue
        typ = _txt(r.get(col["t"])).lower() if col["t"] else ""
        if typ == "laiterie":
            continue
        s = {"n": _txt(r.get(col["n"])), "la": round(la, 5), "lo": round(lo, 5)}
        for k in ("a", "cp", "v", "p", "tel", "st"):
            if col[k]:
                v = _txt(r.get(col[k]))
                if k == "cp" and v.endswith(".0"):
                    v = v[:-2]
                if v:
                    s[k] = v
        if col["nb"]:
            nb = _num(r.get(col["nb"]))
            if nb:
                s["nb"] = int(nb)
        for k in ("pm", "pd"):
            if col[k]:
                x = _num(r.get(col[k]))
                if x:
                    s[k] = round(x, 2)
        if col["dl"]:
            d = _date(r.get(col["dl"]))
            if d:
                s["dl"] = d
        if s["n"]:
            out.append(s)
    # Les plus utilisées d'abord (dessinées au-dessus)
    out.sort(key=lambda s: s.get("nb", 0))
    return out


def enregistrer(df: pd.DataFrame) -> int:
    """Enregistre la base pour la carte (appelé par la page Lavages). Renvoie le nombre de stations."""
    stations = compacter(df)
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL.with_suffix(".tmp")
    tmp.write_text(json.dumps({"maj": datetime.now().strftime("%Y-%m-%d %H:%M"), "stations": stations},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(LOCAL)
    return len(stations)


def lire_excel(contenu: bytes) -> list[dict]:
    return compacter(pd.read_excel(__import__("io").BytesIO(contenu)))


def source() -> tuple[Path | None, float]:
    """Fichier à lire (le plus récent des deux) et sa date de modification (clé de cache)."""
    cands = [p for p in (LOCAL, ASSET) if p.exists()]
    if not cands:
        return None, 0.0
    p = max(cands, key=lambda x: x.stat().st_mtime)
    return p, p.stat().st_mtime


def charger(chemin: str, mtime: float) -> tuple[list[dict], str]:
    """(stations, libellé de la source). mtime sert de clé de cache à l'appelant."""
    p = Path(chemin)
    if p.suffix == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("stations", []), f"base de la page Lavages du {d.get('maj', '?')}"
    return compacter(pd.read_excel(p)), "base du dépôt (assets/lavages_stations.xlsx)"
