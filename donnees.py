"""Données de marché (Yahoo Finance via yfinance), avec caches séparés :
cours = 5 min, fondamentaux = 6 h, historiques = 1 h.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, urlparse
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


def _url_depuis_ddg(html: str) -> str | None:
    """Premier résultat organique d'une page DuckDuckGo « html » (les publicités sont ignorées)."""
    from bs4 import BeautifulSoup

    for a in BeautifulSoup(html, "html.parser").select("a.result__a"):
        href = a.get("href", "")
        if href.startswith("//"):
            href = "https:" + href
        cible = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        hote = urlparse(cible).netloc.lower()
        if cible.startswith(("http://", "https://")) and "duckduckgo.com" not in hote:
            return cible
    return None


def _recherche_url(nom: str, ticker: str | None) -> str | None:
    """1) recherche web « {nom} Financial report » ; 2) repli : site de l'émetteur indiqué par Yahoo."""
    import requests

    try:
        r = requests.get("https://html.duckduckgo.com/html/?q=" + quote_plus(f"{nom} Financial report"),
                         headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                         timeout=8)
        if r.status_code == 200:
            url = _url_depuis_ddg(r.text)
            if url:
                return url
    except Exception:
        pass  # bloqué / hors ligne : on tente le repli
    if ticker:
        try:
            site = (yf.Ticker(ticker).info or {}).get("website")
            if site and str(site).startswith(("http://", "https://")):
                return str(site)
        except Exception:
            pass
    return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _url_en_cache(nom: str, ticker: str | None) -> str:
    url = _recherche_url(nom, ticker)
    if not url:
        raise LookupError(nom)  # une exception n'est jamais mise en cache : on réessaiera plus tard
    return url


def chercher_url_publication(nom: str, ticker: str | None = None) -> str | None:
    """URL de la publication financière d'un titre (recherche web, sans clé API), ou None.

    Résultat mis en cache 24 h ; ne lève jamais d'exception.
    """
    if not nom or not str(nom).strip():
        return None
    try:
        return _url_en_cache(str(nom).strip(), ticker)
    except Exception:
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
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}

    # KPIs pour ETF
    net_assets = info.get("totalAssets") or info.get("netAssets")
    expense_ratio = info.get("netExpenseRatio") or info.get("expenseRatio")
    
    # KPIs pour actions individuelles
    net_income = info.get("netIncome") or info.get("netIncomeToCommon")
    ebitda = info.get("ebitda") or info.get("EBITDA")
    
    # EV/EBITDA : uniquement avec la vraie valeur d'entreprise (marketCap/EBITDA serait un autre ratio)
    ev_ebitda = None
    enterprise_value = _positif(info.get("enterpriseValue"))
    if enterprise_value and ebitda and ebitda > 0:
        ev_ebitda = enterprise_value / ebitda

    return {
        "per": _positif(info.get("trailingPE")),
        "per_prev": _positif(info.get("forwardPE")),
        "ev": enterprise_value,
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
