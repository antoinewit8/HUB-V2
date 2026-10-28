"""Durées du hub en heures et minutes, jamais en heures décimales (7,66 h → « 7 h 40 »).

- fmt_h / fmt_s : texte pour l'affichage (pages, info-bulles, cartes).
- Tableaux Streamlit : garder la colonne numérique (en heures) pour que le tri reste juste et
  l'afficher via un Styler : df.style.format({col: fmt_h}).
- Excel : excel_heures(ws, df, colonnes) écrit des durées Excel au format [h] h mm (calculables,
  triables, affichées « 7 h 40 »).
"""

import math

import pandas as pd

FORMAT_EXCEL = '[h]" h "mm'


def _vide(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def fmt_min(minutes, vide: str = "—") -> str:
    """Minutes → « 7 h 40 », « 45 min », « 31 h 05 »."""
    if _vide(minutes):
        return vide
    try:
        m = int(round(float(minutes)))
    except (TypeError, ValueError):
        return vide
    signe = "−" if m < 0 else ""
    m = abs(m)
    h, r = divmod(m, 60)
    return f"{signe}{h} h {r:02d}" if h else f"{signe}{r} min"


def fmt_h(heures, vide: str = "—") -> str:
    """Heures décimales → « 7 h 40 » (7,66 h)."""
    if _vide(heures):
        return vide
    try:
        x = float(heures)
    except (TypeError, ValueError):
        return vide
    if math.isinf(x):
        return vide
    return fmt_min(x * 60, vide)


def fmt_s(secondes, vide: str = "—") -> str:
    """Secondes → « 7 h 40 »."""
    if _vide(secondes):
        return vide
    try:
        return fmt_min(float(secondes) / 60, vide)
    except (TypeError, ValueError):
        return vide


def colonne_txt(serie: pd.Series, vide: str = "—") -> pd.Series:
    """Colonne d'heures décimales → texte « 7 h 40 » (quand le tri numérique n'importe pas)."""
    return serie.map(lambda v: fmt_h(v, vide))


def vers_jours(serie: pd.Series) -> pd.Series:
    """Heures décimales → fraction de jour (valeur d'une durée Excel)."""
    # arrondi à la minute : Excel tronque les secondes à l'affichage (7,66 h → 7 h 40, pas 7 h 39)
    return (pd.to_numeric(serie, errors="coerce") * 60).round() / 1440.0


def excel_heures(ws, df: pd.DataFrame, colonnes, index: bool = False, ligne_entete: int = 1) -> None:
    """Après df.to_excel(...) avec les colonnes déjà converties par vers_jours :
    applique le format durée [h] h mm aux colonnes données (noms tels qu'écrits dans la feuille)."""
    noms = list(df.columns)
    decalage = df.index.nlevels if index else 0
    for c in colonnes:
        if c not in noms:
            continue
        j = noms.index(c) + 1 + decalage
        for i in range(ligne_entete + 1, ligne_entete + 1 + len(df)):
            ws.cell(row=i, column=j).number_format = FORMAT_EXCEL
