"""Client HTTP Gemini : appels directs (`requests`), limités en concurrence, avec repli sur `Retry-After`.

Aucun secret n'est journalisé ni inclus dans un message d'erreur. Le nombre d'appels simultanés est borné
par un sémaphore (la clé Gemini est partagée par tous les comptes) ; après un 429, les appels suivants
échouent aussitôt, sans réseau, jusqu'à la fin de la pause demandée par Google.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from pea import config
from pea.domain.erreurs import ErreurIA
from pea.services.ia.validation import _parser_json

journal = logging.getLogger(__name__)

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
ATTENTE_MAX_SEMAPHORE_S = 20      # au-delà : message clair plutôt qu'une attente interminable
RETRY_AFTER_MAX_S = 8             # on n'attend sur place qu'une courte pause demandée par Google
PAUSE_429_DEFAUT_S = 30

_semaphore = threading.BoundedSemaphore(config.IA_APPELS_SIMULTANES)
_etat = {"pause_jusqu": 0.0}
_verrou = threading.Lock()


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _etat["pause_jusqu"] = 0.0


def _en_majuscules(schema):
    """Schéma JSON -> variante « responseSchema » (types en majuscules)."""
    if isinstance(schema, dict):
        return {k: (v.upper() if k == "type" and isinstance(v, str) else _en_majuscules(v))
                for k, v in schema.items()}
    if isinstance(schema, list):
        return [_en_majuscules(x) for x in schema]
    return schema


def _payload_json(systeme: str, parts: list, schema: dict, variante: str, max_tokens: int) -> dict:
    """Requête Gemini à réponse JSON structurée (`variante` : json_schema | response_schema)."""
    config_gen = {
        "responseMimeType": "application/json",
        # Pas de temperature/top_p/top_k : ignorés (puis refusés) par les modèles Gemini 3.x
        "thinkingConfig": {"thinkingLevel": "low"},
        "maxOutputTokens": max_tokens,  # la réflexion est comptée dans la sortie
    }
    if variante == "json_schema":
        config_gen["responseJsonSchema"] = schema
    else:
        config_gen["responseSchema"] = _en_majuscules(schema)
    return {"systemInstruction": {"parts": [{"text": systeme}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": config_gen}


def _delai_retry_after(r) -> float | None:
    try:
        v = float((getattr(r, "headers", None) or {}).get("Retry-After"))
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _poster_une_fois(payload: dict, cle: str, modele: str, timeout: int):
    try:
        return requests.post(URL.format(modele=modele), json=payload, timeout=timeout,
                             headers={"x-goog-api-key": cle, "Content-Type": "application/json"})
    except requests.Timeout:
        raise ErreurIA("Délai dépassé : Gemini n'a pas répondu à temps. Réessayez.")
    except requests.RequestException:
        raise ErreurIA("Connexion à Gemini impossible. Réessayez plus tard.")


def _post(payload: dict, cle: str, modele: str, timeout: int):
    """POST borné en concurrence ; un 429 déclenche une pause commune (Retry-After) et au plus une reprise."""
    if time.time() < _etat["pause_jusqu"]:
        raise ErreurIA("Quota Gemini atteint. Réessayez plus tard.")
    if not _semaphore.acquire(timeout=ATTENTE_MAX_SEMAPHORE_S):
        raise ErreurIA("Trop de demandes IA en même temps. Réessayez dans un instant.")
    try:
        r = _poster_une_fois(payload, cle, modele, timeout)
        if r.status_code == 429:
            attente = _delai_retry_after(r)
            if attente is not None and attente <= RETRY_AFTER_MAX_S:
                time.sleep(attente)
                r = _poster_une_fois(payload, cle, modele, timeout)
            if r.status_code == 429:
                pause = attente if attente is not None else PAUSE_429_DEFAUT_S
                with _verrou:
                    _etat["pause_jusqu"] = max(_etat["pause_jusqu"], time.time() + min(pause, 600))
                journal.warning("Gemini : 429, appels suspendus %.0f s", min(pause, 600))
        return r
    finally:
        _semaphore.release()


def _message_erreur(r) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except Exception:
        return ""


def _texte_reponse(r, modele: str) -> str:
    """Statut HTTP -> ErreurIA lisible ; sinon texte de la réponse (hors « pensées »)."""
    if r.status_code in (401, 403):
        raise ErreurIA("Clé API Gemini refusée (vérifiez GEMINI_API_KEY).")
    if r.status_code == 404:
        raise ErreurIA(f"Modèle « {modele} » introuvable (vérifiez GEMINI_MODEL).")
    if r.status_code == 429:
        raise ErreurIA("Quota Gemini atteint. Réessayez plus tard.")
    if r.status_code >= 500:
        raise ErreurIA("Service Gemini momentanément indisponible. Réessayez.")
    if r.status_code != 200:
        raise ErreurIA(f"Requête refusée par Gemini ({r.status_code}) : {_message_erreur(r)}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ErreurIA("Gemini n'a renvoyé aucune réponse exploitable (contenu bloqué ou vide).")
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def appeler_json(systeme: str, parts: list, schema: dict, cle: str, modele: str, timeout: int,
                 max_tokens: int = 4096):
    """Un appel Gemini à sortie structurée -> objet JSON déjà décodé. Lève ErreurIA.

    Réutilisé par l'analyse, l'import par captures et la suggestion de concurrent.
    """
    def envoyer(variante: str):
        return _post(_payload_json(systeme, parts, schema, variante, max_tokens), cle, modele, timeout)

    r = envoyer("json_schema")
    if r.status_code == 400 and "schema" in _message_erreur(r).lower():
        r = envoyer("response_schema")  # variante OpenAPI
    return _parser_json(_texte_reponse(r, modele))


def appeler_texte(payload: dict, cle: str, modele: str, timeout: int) -> str:
    """Appel Gemini à réponse libre (chat) -> texte. Lève ErreurIA."""
    return _texte_reponse(_post(payload, cle, modele, timeout), modele)


def avec_reessai(fonction):
    """Exécute `fonction()` ; un seul nouvel essai si la réponse est invalide. Lève ErreurIA."""
    derniere = None
    for _ in range(2):
        try:
            return fonction()
        except ErreurIA as e:
            derniere = e
            if any(m in str(e) for m in ("refusée", "introuvable", "Quota", "Clé", "Maximum", "Trop de demandes")):
                break  # inutile de réessayer
    raise derniere
