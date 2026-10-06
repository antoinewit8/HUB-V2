# core/fuel_scraper.py
"""
Scraper prix gasoil officiel Belgique — SPF Economie
Source : https://economie.fgov.be/fr/themes/energie/prix-de-lenergie/prix-maximum-des-produits/tarif-officiel-des-produits
"""

import re
import requests
import pdfplumber
import pandas as pd
from pathlib import Path
from datetime import datetime
from io import BytesIO
from bs4 import BeautifulSoup

BASE_URL  = "https://economie.fgov.be"
PAGE_URL  = f"{BASE_URL}/fr/themes/energie/prix-de-lenergie/prix-maximum-des-produits/tarif-officiel-des-produits"
CACHE_DIR = Path("data/fuel_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Mois FR → numéro ─────────────────────────────────────────
MOIS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12
}


def get_pdf_links() -> list[dict]:
    """
    Scrape la page SPF Economie et récupère :
    - Les liens PDF des prix moyens mensuels
    - Le lien PDF du tarif officiel en vigueur
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(PAGE_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    pdfs = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).lower()

        if ".pdf" not in href.lower():
            continue

        full_url = href if href.startswith("http") else BASE_URL + href

        # ── Prix moyens mensuels ──
        if "pmax-moyens" in href.lower() or "prix moyens" in text:
            # Extraire mois/année depuis le texte ou l'URL
            month, year = _extract_month_year(text, href)
            pdfs.append({
                "type":  "prix_moyens",
                "url":   full_url,
                "mois":  month,
                "annee": year,
                "label": link.get_text(strip=True),
            })

        # ── Tarif officiel en vigueur ──
        elif "tarifs-officiels" in href.lower() or "tarif n°" in text:
            pdfs.append({
                "type":  "tarif_officiel",
                "url":   full_url,
                "mois":  None,
                "annee": None,
                "label": link.get_text(strip=True),
            })

    return pdfs


def _extract_month_year(text: str, url: str) -> tuple[int, int]:
    """Extrait mois et année depuis le texte du lien ou l'URL."""
    # Essayer depuis le texte : "prix moyens maximaux officiels mars 2026"
    for mois_name, mois_num in MOIS_FR.items():
        if mois_name in text:
            year_match = re.search(r"20\d{2}", text)
            if year_match:
                return mois_num, int(year_match.group())

    # Essayer depuis l'URL : Pmax-moyens-03-2026.pdf
    url_match = re.search(r"(\d{2})-(\d{4})\.pdf", url, re.IGNORECASE)
    if url_match:
        return int(url_match.group(1)), int(url_match.group(2))

    return 0, 0


def download_pdf(url: str) -> bytes:
    """Télécharge un PDF et le met en cache local."""
    filename = CACHE_DIR / url.split("/")[-1]

    if filename.exists():
        return filename.read_bytes()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    filename.write_bytes(resp.content)
    return resp.content


def parse_prix_moyens_pdf(pdf_bytes: bytes) -> dict:
    """
    Parse un PDF 'Prix moyens maximaux' et extrait les prix du gasoil.
    Retourne un dict avec les différents types de gasoil trouvés.
    """
    results = {}

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        full_text = ""
        all_tables = []

        for page in pdf.pages:
            # Extraire le texte
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"

            # Extraire les tableaux
            tables = page.extract_tables()
            for table in tables:
                all_tables.append(table)

        # ── Méthode 1 : Chercher dans les tableaux ──
        for table in all_tables:
            for row in table:
                if row is None:
                    continue
                row_text = " ".join([str(c) for c in row if c]).lower()

                # Chercher les lignes contenant "gasoil" ou "diesel"
                if any(kw in row_text for kw in ["gasoil", "diesel", "gas-oil"]):
                    # Chercher un prix (nombre avec virgule ou point)
                    for cell in row:
                        if cell is None:
                            continue
                        price = _extract_price(str(cell))
                        if price and 0.5 < price < 5.0:  # Prix réaliste €/litre
                            # Identifier le type
                            if "chauffage" in row_text or "50s" in row_text:
                                results["gasoil_chauffage"] = price
                            elif "routier" in row_text or "10s" in row_text or "b7" in row_text:
                                results["diesel_routier"] = price
                            elif "extra" in row_text:
                                results["gasoil_extra"] = price
                            else:
                                results["diesel"] = price

        # ── Méthode 2 : Regex sur le texte brut ──
        if not results:
            lines = full_text.split("\n")
            for i, line in enumerate(lines):
                line_lower = line.lower()
                if any(kw in line_lower for kw in ["gasoil", "diesel", "gas-oil"]):
                    # Chercher prix sur cette ligne et les 2 suivantes
                    search_zone = " ".join(lines[i:i+3])
                    prices = re.findall(r"(\d+[.,]\d{2,4})", search_zone)
                    for p_str in prices:
                        price = _extract_price(p_str)
                        if price and 0.5 < price < 5.0:
                            if "chauffage" in line_lower:
                                results["gasoil_chauffage"] = price
                            elif "routier" in line_lower or "10" in line_lower:
                                results["diesel_routier"] = price
                            else:
                                results.setdefault("diesel", price)

    return results


def parse_tarif_officiel_pdf(pdf_bytes: bytes) -> dict:
    """Parse le tarif officiel en vigueur."""
    return parse_prix_moyens_pdf(pdf_bytes)  # Même logique de parsing


def _extract_price(text: str) -> float | None:
    """Extrait un prix depuis une chaîne."""
    text = text.strip().replace(",", ".").replace("€", "").replace(" ", "")
    try:
        val = float(text)
        return val
    except ValueError:
        match = re.search(r"(\d+\.\d{2,4})", text)
        if match:
            return float(match.group(1))
    return None


def get_all_prices() -> pd.DataFrame:
    """
    Fonction principale : scrape, télécharge, parse tous les PDFs
    et retourne un DataFrame avec l'historique des prix.
    """
    links = get_pdf_links()
    records = []

    for link in links:
        if link["type"] != "prix_moyens" or link["mois"] == 0:
            continue

        try:
            pdf_bytes = download_pdf(link["url"])
            prices = parse_prix_moyens_pdf(pdf_bytes)

            for fuel_type, price in prices.items():
                records.append({
                    "date":   datetime(link["annee"], link["mois"], 1),
                    "mois":   link["mois"],
                    "annee":  link["annee"],
                    "type":   fuel_type,
                    "prix":   price,
                    "source": link["url"],
                })
        except Exception as e:
            print(f"⚠️ Erreur parsing {link['label']}: {e}")
            continue

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def get_tarif_en_vigueur() -> dict:
    """Récupère le tarif officiel actuellement en vigueur."""
    links = get_pdf_links()
    for link in links:
        if link["type"] == "tarif_officiel":
            try:
                pdf_bytes = download_pdf(link["url"])
                prices = parse_tarif_officiel_pdf(pdf_bytes)
                return {"prices": prices, "label": link["label"], "url": link["url"]}
            except Exception as e:
                return {"error": str(e)}
    return {"error": "Aucun tarif officiel trouvé"}


