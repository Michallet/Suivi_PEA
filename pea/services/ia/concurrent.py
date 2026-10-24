"""Suggestion d'un concurrent par l'IA (la logique de choix et de contrôle est pure : domain.concurrents)."""
from __future__ import annotations

from pea import config
from pea.domain import concurrents as CONC
from pea.services.ia import client
from pea.services.ia.prompts import SCHEMA_JSON_CONCURRENT, SYSTEME_CONCURRENT


def demander_candidats(texte: str, cle: str, modele: str | None = None, timeout: int = 45) -> list[dict]:
    """Un appel Gemini (un nouvel essai si la réponse est illisible). Lève ErreurIA."""
    modele = modele or config.MODELE_GEMINI_DEFAUT
    return client.avec_reessai(lambda: CONC.normaliser_candidats(
        client.appeler_json(SYSTEME_CONCURRENT, [{"text": texte}], SCHEMA_JSON_CONCURRENT, cle, modele,
                            timeout, max_tokens=2048)))


def suggerer(nom: str, isin: str, f: dict | None, cle: str, modele: str | None, resoudre) -> dict | None:
    """Pipeline complet (1 appel Gemini + au plus 3 résolutions Yahoo). Lève ErreurIA."""
    candidats = demander_candidats(CONC.construire_contexte(nom, isin, f), cle, modele)
    return CONC.choisir_concurrent(candidats, isin, resoudre)
