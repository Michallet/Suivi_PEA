"""Chatbot : conversation libre avec le contexte du portefeuille injecté à chaque message."""
from __future__ import annotations

from pea import config
from pea.domain.erreurs import ErreurIA
from pea.domain.textes import nettoyer_sortie_ia
from pea.services.ia import client
from pea.services.ia.prompts import MAX_MOTS_REPONSE, SYSTEME_CHAT
from pea.services.ia.validation import _tronquer_mots

MAX_TOURS_CHAT = 5  # filet de sécurité : le prompt demande des réponses courtes
MAX_TOKENS_CHAT = 2048


def discuter(contexte: str, historique: list, question: str, cle: str,
             modele: str | None = None, timeout: int = 60) -> str:
    """Répond à une question de chat. `historique` : [{"role": "user"|"model", "content": str}].

    Le contexte du portefeuille (poids en %, dernière analyse IA) est injecté en instruction
    systématique à chaque message : la conversation n'a pas besoin d'historique long.
    La réponse est nettoyée (aucun lien, image ni balise HTML : voir domain.textes).
    """
    modele = modele or config.MODELE_GEMINI_DEFAUT
    contenus = ([{"role": m["role"], "parts": [{"text": m["content"]}]}
                 for m in historique[-2 * MAX_TOURS_CHAT:]]
                + [{"role": "user", "parts": [{"text": question}]}])
    payload = {"systemInstruction": {"parts": [{"text": SYSTEME_CHAT + "\n\n" + contexte}]},
               "contents": contenus,
               "generationConfig": {"maxOutputTokens": MAX_TOKENS_CHAT,
                                    "thinkingConfig": {"thinkingLevel": "low"}}}
    texte = nettoyer_sortie_ia(client.appeler_texte(payload, cle, modele, timeout))
    if not texte:
        raise ErreurIA("Gemini n'a renvoyé aucune réponse exploitable (contenu bloqué ou vide).")
    return _tronquer_mots(texte, MAX_MOTS_REPONSE)
