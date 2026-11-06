"""
tools/affretement/engine.py — Répertoire des prix d'affrètement.

Entrée : le classeur AFFRETEMENTS (.xlsm / .xlsx), onglet « LISTE DES DOSSIERS AFFRETES »
(une ligne par dossier sous-traité : chargement, déchargement, client, sous-traitant,
prix de vente, achats, marge). L'onglet est retrouvé par ses en-têtes, pas par son nom.

Sorties
  • base nettoyée (une ligne par dossier, lieux normalisés, marge %) ;
  • grille des prix par trajet, au niveau ville, zone de code postal ou pays ;
  • comparaison des sous-traitants sur un trajet, et vue globale par sous-traitant ;
  • export Excel.

Conventions
  • Prix d'achat = colonne « Achats » (tout compris : transport, suppléments, gasoil).
  • Marge % d'un groupe = marge totale / ventes totales (ratio des sommes, pas moyenne des %).
  • Un dossier est « à vérifier » si son achat s'écarte fortement du médian du trajet
    (< 50 % ou > 180 %, trajet d'au moins 3 dossiers) ou si sa marge est négative.
"""

from __future__ import annotations

import io
import re
import unicodedata

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PAYS = {
    "F": "France", "B": "Belgique", "NL": "Pays-Bas", "D": "Allemagne", "L": "Luxembourg",
    "I": "Italie", "E": "Espagne", "CH": "Suisse", "P": "Portugal", "A": "Autriche",
    "GB": "Royaume-Uni", "PL": "Pologne", "CZ": "Tchéquie", "DK": "Danemark",
}

# En-tête du fichier → nom interne
COLONNES = {
    "dossier": "dossier", "typedetransport": "type", "reference": "ref",
    "datecharg": "date_c", "cpcharg": "cp_c", "localitecharg": "loc_c",
    "datedecharg": "date_d", "cpdeharg": "cp_d", "cpdecharg": "cp_d", "localitedecharg": "loc_d",
    "client": "client", "statut": "statut", "soustraitant": "st", "groupe": "groupe",
    "prixtransport": "prix", "supplements": "supp", "gasoil": "gasoil", "heuresdattente": "attente",
    "totaldesventes": "vente", "achats": "achat", "marge": "marge",
}
OBLIGATOIRES = ("dossier", "loc_c", "loc_d", "st", "achat")

NIVEAUX = {"ville": "Ville", "zone": "Zone CP", "pays": "Pays"}

ECART_BAS, ECART_HAUT, MIN_DOSSIERS_ECART = 0.5, 1.8, 3


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    v = re.sub(r"\s+", " ", str(v)).strip()
    return "" if v.lower() in ("nan", "none", "nat") else v


def _split_cp(v) -> tuple[str, str]:
    """'F 55100' → ('F', '55100') ; 'NL 3002 AB' → ('NL', '3002 AB') ; '4140' → ('', '4140')."""
    s = _txt(v).upper()
    m = re.match(r"^([A-Z]{1,3})[\s-]+(.+)$", s)
    if m:
        return m.group(1), m.group(2).strip()
    return "", s


def _zone(pays: str, cp: str) -> str:
    """Zone de code postal : 2 premiers chiffres (département en France)."""
    chiffres = re.sub(r"\D", "", cp)
    if not chiffres:
        return pays or "?"
    return f"{pays} {chiffres[:2]}".strip()


# ─── Lecture ─────────────────────────────────────────────────────────────────
def lire(data: bytes) -> pd.DataFrame:
    """Lit le classeur et renvoie la base nettoyée. Lève ValueError si l'onglet est introuvable."""
    xl = pd.ExcelFile(io.BytesIO(data))
    brut = None
    for feuille in xl.sheet_names:
        apercu = xl.parse(feuille, header=None, nrows=15)
        for i, ligne in apercu.iterrows():
            noms = {_norm(v) for v in ligne.tolist()}
            if {"dossier", "achats", "soustraitant"} <= noms:
                brut = xl.parse(feuille, header=i)
                break
        if brut is not None:
            break
    if brut is None:
        raise ValueError("Onglet introuvable : il faut des colonnes Dossier, Sous-traitant et Achats "
                         "(onglet « LISTE DES DOSSIERS AFFRETES »).")

    ren = {}
    for c in brut.columns:
        k = COLONNES.get(_norm(c))
        if k and k not in ren.values():
            ren[c] = k
    df = brut[list(ren)].rename(columns=ren)
    manque = [c for c in OBLIGATOIRES if c not in df.columns]
    if manque:
        raise ValueError(f"Colonnes manquantes : {', '.join(manque)}")
    for c in COLONNES.values():
        if c not in df.columns:
            df[c] = np.nan

    # Lignes vides du bas du tableau (année 1900, rien d'autre)
    df = df[df["loc_c"].map(_txt).ne("") & df["st"].map(_txt).ne("")].copy()

    df["dossier"] = df["dossier"].map(lambda v: _txt(v).removesuffix(".0"))
    for c in ("type", "ref", "loc_c", "loc_d", "client", "statut", "st", "groupe"):
        df[c] = df[c].map(_txt)
    for c in ("loc_c", "loc_d", "client", "st"):
        df[c] = df[c].str.upper()
    for c in ("date_c", "date_d"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("prix", "supp", "gasoil", "attente", "vente", "achat", "marge"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df[["pays_c", "cp_c"]] = df["cp_c"].map(_split_cp).tolist()
    df[["pays_d", "cp_d"]] = df["cp_d"].map(_split_cp).tolist()
    df["zone_c"] = [_zone(p, c) for p, c in zip(df["pays_c"], df["cp_c"])]
    df["zone_d"] = [_zone(p, c) for p, c in zip(df["pays_d"], df["cp_d"])]
    df["ville_c"] = df["loc_c"] + " (" + df["zone_c"] + ")"
    df["ville_d"] = df["loc_d"] + " (" + df["zone_d"] + ")"
    df["pays_lib_c"] = df["pays_c"].map(lambda p: PAYS.get(p, p or "?"))
    df["pays_lib_d"] = df["pays_d"].map(lambda p: PAYS.get(p, p or "?"))
    df["marge"] = df["marge"].fillna(df["vente"] - df["achat"])
    df["marge_pct"] = np.where(df["vente"] > 0, df["marge"] / df["vente"], np.nan)
    df["date"] = df["date_c"].fillna(df["date_d"])
    return df.sort_values("date", ascending=False, na_position="last").reset_index(drop=True)


def cles(niveau: str) -> tuple[str, str]:
    return {"ville": ("ville_c", "ville_d"), "zone": ("zone_c", "zone_d"),
            "pays": ("pays_lib_c", "pays_lib_d")}[niveau]


# ─── Agrégations ─────────────────────────────────────────────────────────────
def _ratio(m, v):
    v = v.sum()
    return m.sum() / v if v else np.nan


def grille(df: pd.DataFrame, niveau: str) -> pd.DataFrame:
    """Une ligne par trajet (chargement → déchargement). df déjà trié du plus récent au plus ancien."""
    kc, kd = cles(niveau)
    if df.empty:
        return pd.DataFrame()
    g = df.groupby([kc, kd], sort=False)
    out = pd.DataFrame({
        "Chargement": g[kc].first(),
        "Déchargement": g[kd].first(),
        "Type": g["type"].agg(lambda s: " / ".join(sorted(set(s) - {""}))),
        "Dossiers": g.size(),
        "Dernier achat": g["achat"].first(),
        "Date": g["date"].first(),
        "Dernier sous-traitant": g["st"].first(),
        "Achat médian": g["achat"].median(),
        "Achat min": g["achat"].min(),
        "Achat max": g["achat"].max(),
        "Vente médiane": g["vente"].median(),
        "Marge %": g.apply(lambda x: _ratio(x["marge"], x["vente"]), include_groups=False),
        "Sous-traitants": g["st"].nunique(),
    }).reset_index(drop=True)
    return out.sort_values(["Dossiers", "Date"], ascending=False).reset_index(drop=True)


def comparer_sous_traitants(df: pd.DataFrame) -> pd.DataFrame:
    """Sous-traitants d'un même trajet (ou de n'importe quelle sélection)."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("st", sort=False)
    out = pd.DataFrame({
        "Sous-traitant": g["st"].first(),
        "Dossiers": g.size(),
        "Dernier achat": g["achat"].first(),
        "Date": g["date"].first(),
        "Achat médian": g["achat"].median(),
        "Achat min": g["achat"].min(),
        "Achat max": g["achat"].max(),
        "Marge %": g.apply(lambda x: _ratio(x["marge"], x["vente"]), include_groups=False),
    }).reset_index(drop=True)
    return out.sort_values(["Dossiers", "Date"], ascending=False).reset_index(drop=True)


def par_sous_traitant(df: pd.DataFrame, niveau: str) -> pd.DataFrame:
    """Vue globale : volume, achats, marge et trajets principaux de chaque sous-traitant."""
    if df.empty:
        return pd.DataFrame()
    kc, kd = cles(niveau)
    tr = df[kc] + " → " + df[kd]
    g = df.assign(_tr=tr).groupby("st", sort=False)

    def principaux(s):
        vc = s.value_counts()
        return " · ".join(f"{k} ({v})" for k, v in vc.head(3).items())

    out = pd.DataFrame({
        "Sous-traitant": g["st"].first(),
        "Dossiers": g.size(),
        "CIT": g["type"].agg(lambda s: int((s == "CIT").sum())),
        "PLA": g["type"].agg(lambda s: int((s == "PLA").sum())),
        "Achats totaux": g["achat"].sum(),
        "Achat moyen": g["achat"].mean(),
        "Marge %": g.apply(lambda x: _ratio(x["marge"], x["vente"]), include_groups=False),
        "Dernier dossier": g["date"].max(),
        "Trajets principaux": g["_tr"].agg(principaux),
    }).reset_index(drop=True)
    return out.sort_values("Dossiers", ascending=False).reset_index(drop=True)


def signaler(df: pd.DataFrame, niveau: str) -> pd.Series:
    """Motif « à vérifier » par dossier (chaîne vide si rien)."""
    kc, kd = cles(niveau)
    med = df.groupby([kc, kd])["achat"].transform("median")
    nb = df.groupby([kc, kd])["achat"].transform("size")
    motif = pd.Series("", index=df.index)
    assez = nb >= MIN_DOSSIERS_ECART
    motif[assez & (df["achat"] < ECART_BAS * med)] = "Achat très bas pour ce trajet"
    motif[assez & (df["achat"] > ECART_HAUT * med)] = "Achat très haut pour ce trajet"
    neg = df["marge"] < 0
    motif[neg] = np.where(motif[neg] != "", motif[neg] + " · marge négative", "Marge négative")
    return motif


# ─── Export ──────────────────────────────────────────────────────────────────
COLS_DOSSIERS = {
    "dossier": "Dossier", "type": "Type", "date_c": "Date charg.", "loc_c": "Localité charg.",
    "zone_c": "Zone charg.", "date_d": "Date décharg.", "loc_d": "Localité décharg.", "zone_d": "Zone décharg.",
    "client": "Client", "st": "Sous-traitant", "statut": "Statut", "vente": "Vente", "achat": "Achat",
    "marge": "Marge", "marge_pct": "Marge %", "ref": "Référence", "verif": "À vérifier",
}


def excel(feuilles: dict[str, pd.DataFrame]) -> bytes:
    bleu = PatternFill("solid", fgColor="003087")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom, d in feuilles.items():
            d.to_excel(xw, sheet_name=nom[:31], index=False)
            ws = xw.sheets[nom[:31]]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for j, col in enumerate(d.columns, 1):
                cell = ws.cell(1, j)
                cell.font, cell.fill = Font(bold=True, color="FFFFFF"), bleu
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                largeur = max([len(str(col))] + [len(str(v)) for v in d[col].head(300)]) + 2
                ws.column_dimensions[get_column_letter(j)].width = min(max(largeur, 9), 48)
                if "%" in str(col):
                    fmt = "0.0%"
                elif pd.api.types.is_datetime64_any_dtype(d[col]):
                    fmt = "dd/mm/yyyy"
                elif pd.api.types.is_float_dtype(d[col]):
                    fmt = '#,##0.00 "€"'
                else:
                    continue
                for i in range(2, len(d) + 2):
                    ws.cell(i, j).number_format = fmt
    return buf.getvalue()
