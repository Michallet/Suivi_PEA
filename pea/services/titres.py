"""Titres : création d'un ticker (ISIN -> cotation Yahoo en €) et concurrent d'une action.

Aucune fonction d'affichage ici : l'interface compose ces appels (sablier, messages, rechargement).
"""
from __future__ import annotations

import logging

from pea import config
from pea.data import marche
from pea.data import repo
from pea.domain import concurrents as CONC
from pea.domain.fondamentaux import est_etf
from pea.services import ia, quotas

journal = logging.getLogger(__name__)
ERREUR_MIGRATION_CONCURRENT = ("Enregistrement impossible : exécutez d'abord la migration SQL du concurrent "
                               "(3 colonnes « concurrent_* » de la table tickers, voir schema.sql).")


def enregistrer_ticker(isin: str, ticker: str, nom: str | None = None) -> tuple[str | None, str | None]:
    """Valide puis mémorise ISIN -> ticker. Retourne (message d'erreur, nom validé)."""
    v = marche.valider_ticker(ticker, nom)
    if v is None:
        return f"Aucun cours trouvé pour « {ticker} ».", None
    if v["devise"] not in (None, "EUR"):
        return f"« {ticker} » cote en {v['devise']} : indiquez la cotation européenne en € (ex : MC.PA).", None
    repo.upsert("tickers", [{"isin": isin, "ticker": ticker, "nom": v["nom"], "dernier_prix": v["prix"],
                             "dernier_prix_at": config.maintenant().isoformat()}], "isin")
    return None, v["nom"]


def resoudre_ticker(isin: str, tk: str) -> tuple[str | None, str | None, str | None]:
    """Ticker saisi, sinon trouvé à partir de l'ISIN : (ticker, nom proposé, erreur)."""
    trouve = None if tk else marche.chercher_ticker(isin)
    ticker = tk or (trouve or {}).get("ticker")
    if not ticker:
        return None, None, "Ticker introuvable : renseignez-le dans le champ dédié."
    return ticker, (trouve or {}).get("nom"), None


def resoudre_concurrent(isin: str, ticker: str | None = None) -> dict | None:
    """Yahoo : ticker validé (ou trouvé à partir de l'ISIN) -> {ticker, nom}, sinon None."""
    if ticker:
        v = marche.valider_ticker(ticker)
        return {"ticker": ticker, "nom": v["nom"]} if v else None
    t = marche.chercher_ticker(isin) if isin else None
    if not t or marche.valider_ticker(t["ticker"], t["nom"]) is None:
        return None
    return {"ticker": t["ticker"], "nom": t["nom"]}


def enregistrer_concurrent(isin: str, conc: dict | None) -> str | None:
    """Écrit (ou efface si None) le concurrent du titre. Retourne un message d'erreur ou None."""
    rec = {"concurrent_isin": (conc or {}).get("isin") or None,
           "concurrent_ticker": (conc or {}).get("ticker"), "concurrent_nom": (conc or {}).get("nom")}
    try:
        repo.modifier("tickers", isin, rec, cle="isin")
    except Exception as e:
        journal.info("Concurrent non enregistré (%s)", type(e).__name__)
        return ERREUR_MIGRATION_CONCURRENT
    return None


def preparer_concurrent(isin_c: str, tk_c: str, isin: str):
    """Saisie manuelle -> (concurrent, erreur)."""
    return CONC.preparer_concurrent(isin_c, tk_c, isin, resoudre_concurrent)


def ia_concurrent_disponible() -> bool:
    return bool(config.cle_gemini()) and not repo.est_demo() and not quotas.limite_atteinte("concurrent")


def proposer_concurrent(nom: str, isin: str, f: dict | None) -> dict | None:
    """Bouton « 💡 IA » : une suggestion, comptée dans le quota. Lève ia.ErreurIA ou quotas.QuotaDepasse."""
    quotas.verifier("concurrent")
    prop = ia.suggerer(nom, isin, f, config.cle_gemini(), config.modele_gemini(), resoudre_concurrent)
    quotas.enregistrer("concurrent")
    return prop


def suggerer_a_la_creation(isin: str, ticker: str, nom: str) -> str | None:
    """Une seule suggestion IA, à la création du titre. Retourne le message à afficher, sinon None.
    Ne bloque jamais l'enregistrement : toute erreur est journalisée, jamais affichée."""
    if repo.est_demo() or not config.cle_gemini():
        return None
    try:
        f = marche.fondamentaux_batch((ticker,), attente=10).get(ticker, {})
        if est_etf(nom, f):
            return None
        conc = proposer_concurrent(nom, isin, f)
        if conc and enregistrer_concurrent(isin, conc) is None:
            return f"Concurrent suggéré : {conc['nom']} (modifiable dans Détails › Fondamentaux)"
    except Exception as e:
        journal.info("Suggestion de concurrent abandonnée (%s)", type(e).__name__)
    return None
