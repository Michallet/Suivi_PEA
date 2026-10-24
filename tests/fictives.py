"""Données FICTIVES partagées par les tests (aucune donnée réelle : le dépôt est public).

Les ISIN sont fabriqués avec une clé de contrôle Luhn calculée ici, indépendamment du code testé.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cle_luhn(corps: str) -> str:
    chiffres = "".join(str(int(c, 36)) for c in corps)
    total = 0
    for i, c in enumerate(reversed(chiffres)):
        n = int(c)
        if i % 2 == 0:  # la clé sera ajoutée à droite : le dernier chiffre du corps est doublé
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def isin_fictif(pays: str, corps9: str) -> str:
    base = pays + corps9
    return base + _cle_luhn(base)


ALPHA = isin_fictif("FR", "00ALPHA01")
BETA = isin_fictif("DE", "00BETA002")
GAMMA = isin_fictif("FR", "00GAMMA03")  # ETF
DELTA = isin_fictif("NL", "00DELTA04")
EPSILON = isin_fictif("IT", "EPSILON05")

NOMS = {ALPHA: "Alpha SA", BETA: "Beta Industries AG", GAMMA: "Gamma Monde UCITS ETF",
        DELTA: "Delta Santé NV", EPSILON: "Epsilon Energie SpA"}
TICKERS = {ALPHA: "ALP.PA", BETA: "BET.DE", GAMMA: "GAM.PA", DELTA: "DEL.AS", EPSILON: "EPS.MI"}
SECTEURS = {ALPHA: "Luxe", BETA: "Industrie", GAMMA: "ETF monde", DELTA: "Santé", EPSILON: "Énergie"}


def journal() -> pd.DataFrame:
    """Journal fictif : achats, ventes partielle et totale, frais, deux achats le même jour."""
    lignes = [
        ("2025-01-06", ALPHA, "ACHAT", 10, 100.0, 10.0),
        ("2025-01-06", GAMMA, "ACHAT", 5, 50.0, 0.0),
        ("2025-02-03", BETA, "ACHAT", 20, 30.0, 5.0),
        ("2025-02-17", ALPHA, "ACHAT", 5, 120.0, 5.0),
        ("2025-03-10", ALPHA, "VENTE", 4, 130.0, 5.0),
        ("2025-03-24", DELTA, "ACHAT", 8, 75.5, 2.0),
        ("2025-04-07", BETA, "VENTE", 20, 33.0, 5.0),   # ligne soldée
        ("2025-04-28", EPSILON, "ACHAT", 100, 12.345, 3.0),
        ("2025-05-12", EPSILON, "ACHAT", 50, 13.0, 0.0),
    ]
    df = pd.DataFrame(lignes, columns=["date", "isin", "type", "quantite", "prix", "frais"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("quantite", "prix", "frais"):
        df[c] = df[c].astype(float)
    return df


def dividendes() -> pd.DataFrame:
    df = pd.DataFrame([("2025-03-03", ALPHA, 12.5), ("2025-05-05", DELTA, 4.2)],
                      columns=["date", "isin", "montant"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def versements() -> pd.DataFrame:
    df = pd.DataFrame([
        ("2025-01-02", "VERSEMENT", 3000.0, "Initial"),
        ("2025-03-01", "VERSEMENT", 500.0, None),
        ("2025-04-01", "PV_ANTERIEURE", 800.0, "PV réinvestie"),
        ("2025-05-20", "RETRAIT", 100.0, None),
    ], columns=["date", "type", "montant", "libelle"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def cours() -> pd.DataFrame:
    """Cours fictifs : ALPHA live, BETA absent du portefeuille, DELTA obsolète, EPSILON sans cours."""
    return pd.DataFrame([
        {"isin": ALPHA, "ticker": TICKERS[ALPHA], "nom": NOMS[ALPHA], "prix": 140.0, "prev_close": 138.0, "statut": "live"},
        {"isin": GAMMA, "ticker": TICKERS[GAMMA], "nom": NOMS[GAMMA], "prix": 52.0, "prev_close": 51.0, "statut": "live"},
        {"isin": DELTA, "ticker": TICKERS[DELTA], "nom": NOMS[DELTA], "prix": 80.0, "prev_close": None, "statut": "obsolète"},
    ], columns=["isin", "ticker", "nom", "prix", "prev_close", "statut"])


def serie_prix(graine: int, n: int = 260, depart: float = 100.0, derive: float = 0.0004,
               vol: float = 0.012) -> pd.DataFrame:
    """Bougies journalières fictives (High, Low, Close), reproductibles."""
    rng = np.random.RandomState(graine)
    rend = rng.normal(derive, vol, n)
    close = depart * np.cumprod(1 + rend)
    haut = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    bas = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    idx = pd.bdate_range("2024-06-03", periods=n)
    return pd.DataFrame({"High": haut, "Low": bas, "Close": close}, index=idx)


def historique_prix() -> dict:
    """{ticker: Series de clôtures} pour reconstituer l'historique."""
    jours = pd.bdate_range("2025-01-01", "2025-06-30")
    rng = np.random.RandomState(7)
    out = {}
    for t, p0 in (("ALP.PA", 100.0), ("GAM.PA", 50.0), ("BET.DE", 30.0), ("DEL.AS", 75.0)):
        out[t] = pd.Series(p0 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(jours))), index=jours)
    return out  # EPS.MI absent : repli sur le prix de transaction
