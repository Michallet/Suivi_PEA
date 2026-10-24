"""Analyse IA de la structure du portefeuille ou d'un scénario : un seul appel, réponse JSON validée."""
from __future__ import annotations

from pea import config
from pea.services.ia import client
from pea.services.ia.prompts import SCHEMA_JSON, SCHEMA_JSON_SCENARIO, SYSTEME, SYSTEME_SCENARIO
from pea.services.ia.validation import valider_resultat


def analyser(texte: str, cle: str, modele: str | None = None, timeout: int = 60,
             scenario: bool = False) -> dict:
    """Un appel (un seul nouvel essai si la réponse est invalide). Lève ErreurIA.

    Avec `scenario=True` : schéma étendu (avantages/inconvénients) et prompt comparatif.
    """
    modele = modele or config.MODELE_GEMINI_DEFAUT
    schema, systeme = (SCHEMA_JSON_SCENARIO, SYSTEME_SCENARIO) if scenario else (SCHEMA_JSON, SYSTEME)

    def une_analyse() -> dict:
        res = valider_resultat(
            client.appeler_json(systeme, [{"text": texte}], schema, cle, modele, timeout), comparer=scenario)
        res["modele"] = modele
        return res

    return client.avec_reessai(une_analyse)
