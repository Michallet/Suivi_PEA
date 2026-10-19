"""Données de marché (Yahoo Finance via yfinance), avec caches séparés :
cours = 5 min, fondamentaux = 6 h, historiques = 1 h.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# Places européennes cotées en € (le PEA impose des titres européens)
SUFFIXES_EUR = (".PA", ".AS", ".BR", ".MI", ".DE", ".MC", ".LS", ".HE", ".IR", ".VI")


def _positif(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) and x > 0 else None


# --------------------------------------------------------------------------- #
# Résolution ISIN -> ticker (à la saisie uniquement, puis stocké en base)
# --------------------------------------------------------------------------- #
def chercher_ticker(isin: str) -> dict | None:
    """Cherche le ticker Yahoo d'un ISIN en privilégiant les places européennes en €."""
    try:
        quotes = [q for q in yf.Search(isin, max_results=8).quotes if q.get("symbol")]
    except Exception:
        return None
    preferes = [q for q in quotes if q["symbol"].upper().endswith(SUFFIXES_EUR)]
    choix = (preferes or quotes or [None])[0]
    if not choix:
        return None
    return {"ticker": choix["symbol"],
            "nom": choix.get("shortname") or choix.get("longname") or choix["symbol"]}


def chercher_url_publication(nom: str) -> str | None:
    """Recherche Web pour trouver l'URL du rapport financier d'une entreprise.
    Retourne le premier résultat de recherche Google pour '{nom} Financial report'.
    """
    try:
        import requests
        from urllib.parse import quote
        
        # Construire l'URL de recherche Google
        query = f"{nom} Financial report"
        encoded_query = quote(query)
        google_url = f"https://www.google.com/search?q={encoded_query}"
        
        # Requête avec headers pour éviter le blocage
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(google_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Extraire le premier lien organique de la page de résultats
            # Note: Google peut bloquer, donc on utilise une approche simple
            # En production, il faudrait utiliser l'API Google Custom Search
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Trouver les liens dans les résultats de recherche
            for link in soup.find_all('a'):
                href = link.get('href')
                if href and href.startswith('/url?q='):
                    # Extraire l'URL réelle
                    url = href.split('/url?q=')[1].split('&')[0]
                    # Filtrer les URLs Google
                    if not url.startswith(('https://www.google.', 'http://www.google.')):
                        # Nettoyer l'URL
                        from urllib.parse import unquote
                        return unquote(url)
    except Exception:
        pass
    
    return None


def lire_cours(ticker: str) -> dict:
    """Dernier cours, clôture précédente, devise. Valeurs None en cas d'échec (jamais 0)."""
    out = {"prix": None, "prev": None, "devise": None}
    try:
        fi = yf.Ticker(ticker).fast_info
        out["prix"] = _positif(getattr(fi, "last_price", None))
        out["prev"] = _positif(getattr(fi, "previous_close", None))
        out["devise"] = getattr(fi, "currency", None)
    except Exception:
        pass
    if out["prix"] is None:  # repli sur l'historique récent
        try:
            h = yf.Ticker(ticker).history(period="5d")["Close"].dropna()
            if len(h) >= 1:
                out["prix"] = _positif(h.iloc[-1])
            if len(h) >= 2:
                out["prev"] = _positif(h.iloc[-2])
        except Exception:
            pass
    return out


def valider_ticker(ticker: str, nom: str | None = None) -> dict | None:
    """Vérifie qu'un ticker répond. Retourne {ticker, nom, devise, prix} ou None."""
    c = lire_cours(ticker)
    if c["prix"] is None:
        return None
    if not nom:
        try:
            info = yf.Ticker(ticker).info
            nom = info.get("shortName") or info.get("longName")
        except Exception:
            nom = None
    return {"ticker": ticker, "nom": nom or ticker, "devise": c["devise"], "prix": c["prix"]}


# --------------------------------------------------------------------------- #
# Cours (cache court) et fondamentaux (cache long), en parallèle
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=300, show_spinner="Mise à jour des cours…")
def cours_batch(tickers: tuple) -> tuple[dict, datetime]:
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(lire_cours, tickers))
    return dict(zip(tickers, res)), datetime.now(ZoneInfo("Europe/Paris"))


def _lire_info(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return {}
    
    # KPIs pour ETF
    net_assets = info.get("totalAssets") or info.get("netAssets")
    expense_ratio = info.get("netExpenseRatio") or info.get("expenseRatio")
    
    # KPIs pour actions individuelles
    net_income = info.get("netIncome") or info.get("netIncomeToCommon")
    ebitda = info.get("ebitda") or info.get("EBITDA")
    
    # Calcul EV/EBITDA si possible
    ev_ebitda = None
    if ebitda and ebitda > 0:
        enterprise_value = info.get("enterpriseValue")
        market_cap = info.get("marketCap")
        if enterprise_value:
            ev_ebitda = enterprise_value / ebitda if ebitda > 0 else None
        elif market_cap:
            # Approximation si EV non disponible
            ev_ebitda = market_cap / ebitda if ebitda > 0 else None
    
    return {
        "per": _positif(info.get("trailingPE")),
        "ca": info.get("totalRevenue"),
        "capi": info.get("marketCap"),
        "secteur_yahoo": info.get("sector"),  # en anglais : surchargeable dans « Secteurs »
        "net_assets": net_assets,
        "expense_ratio": expense_ratio,
        "net_income": net_income,
        "ebitda": ebitda,
        "ev_ebitda": ev_ebitda,
    }


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fondamentaux_batch(tickers: tuple) -> dict:
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(_lire_info, tickers))
    return dict(zip(tickers, res))


# --------------------------------------------------------------------------- #
# Historique de clôtures (benchmark, reconstitution)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=3600, show_spinner=False)
def historique_cloture(ticker: str, debut: str) -> pd.Series:
    """Clôtures brutes depuis `debut` (AAAA-MM-JJ). Lève ValueError si vide (=> pas mis en cache)."""
    h = yf.Ticker(ticker).history(start=debut, auto_adjust=False)["Close"].dropna()
    if h.empty:
        raise ValueError(f"Aucun historique pour {ticker}")
    h.index = h.index.tz_localize(None).normalize()
    return h
