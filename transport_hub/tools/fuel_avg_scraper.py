import pandas as pd
import requests
import os
from datetime import datetime
from bs4 import BeautifulSoup


def get_weekly_prices() -> pd.DataFrame:
    """
    Prix diesel hebdomadaires Belgique — GlobalPetrolPrices.com
    Mis à jour chaque lundi.
    """
    url = "https://www.globalpetrolprices.com/Belgium/diesel_prices/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table", {"id": "historical_data_detailed"})
        if not table:
            table = soup.find("table")
        if not table:
            return pd.DataFrame(columns=["date", "diesel_routier"])

        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2:
                try:
                    date = pd.to_datetime(cells[0])
                    price = float(cells[1].replace(",", "."))
                    if 0.5 < price < 5.0:
                        rows.append({"date": date, "diesel_routier": price})
                except Exception:
                    continue

        if rows:
            return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    except Exception as e:
        print(f"⚠️ get_weekly_prices erreur: {e}")

    return pd.DataFrame(columns=["date", "diesel_routier"])


def get_daily_prices(full_history: bool = False) -> pd.DataFrame:
    """
    Prix journaliers depuis Statbel open data.
    """
    url = "https://statbel.fgov.be/sites/default/files/files/opendata/Consumptieprijzen/TH_CPI_BE.xlsx"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        from io import BytesIO
        df = pd.read_excel(BytesIO(resp.content))

        # Chercher colonnes date + diesel
        date_col = next((c for c in df.columns if "date" in str(c).lower() or "datum" in str(c).lower()), None)
        diesel_col = next((c for c in df.columns if "diesel" in str(c).lower() or "gasoil" in str(c).lower()), None)

        if date_col and diesel_col:
            df = df[[date_col, diesel_col]].copy()
            df.columns = ["date", "diesel_routier"]
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna().sort_values("date")
            if not full_history:
                df = df.tail(90)
            return df.reset_index(drop=True)

    except Exception as e:
        print(f"⚠️ get_daily_prices erreur: {e}")

    return pd.DataFrame(columns=["date", "diesel_routier"])


def get_monthly_averages() -> pd.DataFrame:
    """
    Récupère les moyennes mensuelles du gasoil depuis be.STAT (Statbel).
    Fallback sur data/fuel_avg.csv si le site est inaccessible.
    """
    url = "https://bestat.economie.fgov.be/bestat/crosstable.xhtml?view=90a3de47-97fc-4870-9936-f55ed85f15fd"
    csv_path = "data/fuel_avg.csv"
    
    try:
        # Tentative de lecture HTML (pd.read_html gère souvent les tableaux simples même en JSF)
        # On utilise des headers pour éviter d'être bloqué
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            dfs = pd.read_html(response.text, decimal=',', thousands='.')
            if dfs:
                df = dfs[0]
                
                # Nettoyage standard pour be.STAT
                # Colonnes attendues : 0: Période, 2: Gasoil chauffage (>2000L), 3: Diesel routier
                df = df.iloc[:, [0, 2, 3]]
                df.columns = ["date_raw", "gasoil_chauffage", "gasoil_routier"]
                
                # Nettoyage des lignes de total ou vides
                df = df[df["date_raw"].str.contains(r'\d{4}', na=False)].copy()
                
                # Conversion date (Format be.STAT : 2024M01 ou Janvier 2024)
                # On simplifie pour le DataFrame
                df["date"] = pd.to_datetime(df["date_raw"].str.replace('M', '-'), errors='coerce')
                df = df.dropna(subset=["date"]).sort_values("date")
                
                return df[["date", "gasoil_routier", "gasoil_chauffage"]]

    except Exception as e:
        print(f"DEBUG: Erreur scraping be.STAT : {e}")

    # ── FALLBACK SUR CSV LOCAL ──
    if os.path.exists(csv_path):
        try:
            df_local = pd.read_csv(csv_path)
            if "date" in df_local.columns:
                df_local["date"] = pd.to_datetime(df_local["date"])
                return df_local.sort_values("date")
        except Exception as e:
            print(f"DEBUG: Erreur lecture CSV local : {e}")

    # Retourne un DataFrame vide si tout échoue
    return pd.DataFrame(columns=["date", "gasoil_routier", "gasoil_chauffage"])
