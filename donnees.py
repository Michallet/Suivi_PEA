"""Données de marché (Yahoo Finance via yfinance), avec caches séparés :
cours = 5 min, fondamentaux = 6 h, historiques = 1 h.

Cours et fondamentaux sont mis en cache TITRE PAR TITRE : ajouter une ligne à la watchlist ne
re-télécharge plus tous les autres titres. Un échec n'est mémorisé que quelques minutes (avant : 6 h).
Ces données sont publiques (aucune donnée utilisateur) : le cache est partagé entre comptes.
"""
from __future__ import annotations

import threading
import time
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
TTL_COURS, TTL_FONDS, TTL_ECHEC_COURS, TTL_ECHEC_FONDS = 300, 6 * 3600, 60, 300
TTL_OHLC, TTL_ECHEC_OHLC = 3600, 300  # historiques journaliers (indicateurs techniques)


@st.cache_resource
def _magasin() -> dict:
    """{catégorie: {ticker: (horodatage, valeur, durée de validité)}} + verrou, partagé entre sessions."""
    return {"cours": {}, "fonds": {}, "ohlc": {}, "verrou": threading.Lock()}


def _par_titre(categorie: str, tickers: tuple, lire, ttl: int, ttl_echec: int, ok, spinner: str | None = None):
    """({ticker: valeur}, horodatage le plus ancien). Seuls les titres absents/périmés sont téléchargés,
    en parallèle. `ok(valeur)` dit si la lecture a réussi (sinon durée de validité courte)."""
    m = _magasin()
    maintenant = time.time()
    with m["verrou"]:
        a_lire = [t for t in dict.fromkeys(tickers)
                  if t not in m[categorie] or maintenant - m[categorie][t][0] > m[categorie][t][2]]
    if a_lire:
        with st.spinner(spinner) if spinner else _sans_spinner():
            with ThreadPoolExecutor(max_workers=5) as ex:
                res = list(ex.map(lire, a_lire))
        with m["verrou"]:
            for t, r in zip(a_lire, res):
                m[categorie][t] = (time.time(), r, ttl if ok(r) else ttl_echec)
    with m["verrou"]:
        valeurs = {t: m[categorie][t][1] for t in tickers if t in m[categorie]}
        horo = min((m[categorie][t][0] for t in tickers if t in m[categorie]), default=time.time())
    return valeurs, horo


class _sans_spinner:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def cours_batch(tickers: tuple) -> tuple[dict, datetime]:
    valeurs, horo = _par_titre("cours", tuple(tickers), lire_cours, TTL_COURS, TTL_ECHEC_COURS,
                               lambda r: r.get("prix") is not None,
                               spinner="Mise à jour des cours…")
    return valeurs, datetime.fromtimestamp(horo, ZoneInfo("Europe/Paris"))


def _vider(categorie: str) -> None:
    m = _magasin()
    with m["verrou"]:
        m[categorie].clear()


cours_batch.clear = lambda: _vider("cours")  # type: ignore[attr-defined]  (bouton 🔄)


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
        "industrie": info.get("industry"),
        "devise": info.get("currency"),  # devise de cotation (capitalisation)
        "net_assets": net_assets,
        "expense_ratio": expense_ratio,
        "net_income": net_income,
        "ebitda": ebitda,
        "ev_ebitda": ev_ebitda,
    }


def lire_ohlc(ticker: str):
    """Bougies journalières (High, Low, Close) sur ~1 an, ajustées des dividendes ; None en cas d'échec."""
    try:
        h = yf.Ticker(ticker).history(period="1y")
        h = h[["High", "Low", "Close"]].dropna()
        if h.empty:
            return None
        if getattr(h.index, "tz", None) is not None:
            h.index = h.index.tz_localize(None)
        return h
    except Exception:
        return None


def ohlc_batch(tickers: tuple) -> dict:
    """{ticker: DataFrame | None}, un téléchargement par titre (parallèle, cache 1 h, échec 5 min)."""
    valeurs, _ = _par_titre("ohlc", tuple(tickers), lire_ohlc, TTL_OHLC, TTL_ECHEC_OHLC,
                            lambda r: r is not None and len(r) >= 20,
                            spinner="Calcul des indicateurs techniques…")
    return valeurs


ohlc_batch.clear = lambda: _vider("ohlc")  # type: ignore[attr-defined]


def fondamentaux_batch(tickers: tuple) -> dict:
    valeurs, _ = _par_titre("fonds", tuple(tickers), _lire_info, TTL_FONDS, TTL_ECHEC_FONDS,
                            lambda r: any(v is not None for v in r.values()))  # {} ou tout à None = échec
    return valeurs


fondamentaux_batch.clear = lambda: _vider("fonds")  # type: ignore[attr-defined]  (bouton 🔄)


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
