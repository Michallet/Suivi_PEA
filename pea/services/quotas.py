"""Quotas d'IA : compteurs en base (table `usage_ia`), plafond journalier global, limiteur par minute.

* `verifier(nature)` avant un appel (lève QuotaDepasse avec un message affichable) ;
  `enregistrer(nature)` après un appel réussi (comme avant : un appel en échec ne consomme pas le quota).
* Le compte démo n'appelle jamais l'IA : refus ici, côté serveur, en plus de l'interface.
* Sans la migration SQL (`usage_ia` absente) : repli sur les anciennes tables (analyses, chat_log) puis sur
  un compteur en mémoire du processus — toujours mieux que l'ancien compteur de session.
* Les nombres lus en base sont gardés 60 s en mémoire : un simple affichage ne refait pas de requête.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from pea import config
from pea.data import repo

journal = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
TTL_COMPTE_S = 60

LIMITES = {"analyse": config.MAX_APPELS_PAR_JOUR, "chat": config.MAX_CHAT_PAR_JOUR,
           "capture": config.MAX_IMPORTS_PAR_JOUR, "concurrent": config.MAX_SUGGESTIONS_PAR_JOUR}
LIBELLES = {"analyse": "analyses", "chat": "messages", "capture": "lectures", "concurrent": "suggestions"}
# Repli avant migration : anciennes tables qui comptaient déjà ces usages.
ANCIENNES_TABLES = {"analyse": ("analyses_ia", "analyses_scen"), "chat": ("chat_log",)}


class QuotaDepasse(Exception):
    """Message affichable tel quel."""


_verrou = threading.Lock()
_comptes: dict = {}       # (uid | "*", nature | "*", jour) -> (nombre, horodatage lecture)
_memoire: dict = {}       # repli sans base : (uid, nature, jour) -> nombre
_minute: dict = {}        # uid | "*" -> deque d'horodatages


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _comptes.clear()
        _memoire.clear()
        _minute.clear()


def _jour() -> str:
    return datetime.now(PARIS).date().isoformat()


def _debut_jour_iso() -> str:
    d = datetime.now(PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.isoformat()


def _compter_base(uid: str | None, nature: str) -> int:
    depuis = _debut_jour_iso()
    if repo.table_disponible("usage_ia"):
        try:
            filtres = {} if nature == "*" else {"nature": nature}
            return repo.compter_global("usage_ia", depuis, filtres) if uid is None \
                else repo.compter("usage_ia", depuis, filtres)
        except Exception as e:  # déjà journalisé par repo ; repli ci-dessous
            journal.debug("usage_ia illisible (%s) : repli", type(e).__name__)
    if uid is None:
        return sum(v for (u, n, j), v in _memoire.items() if j == _jour())
    if nature in ANCIENNES_TABLES:
        try:
            return sum(repo.compter(t, depuis) for t in ANCIENNES_TABLES[nature])
        except Exception as e:
            journal.debug("anciennes tables illisibles (%s) : repli mémoire", type(e).__name__)
    return _memoire.get((uid, nature, _jour()), 0)


def _nombre(uid: str | None, nature: str) -> int:
    cle = (uid or "*", nature, _jour())
    with _verrou:
        e = _comptes.get(cle)
        if e and time.time() - e[1] < TTL_COMPTE_S:
            return e[0]
    n = _compter_base(uid, nature)
    with _verrou:
        _comptes[cle] = (n, time.time())
    return n


def utilises(nature: str) -> int:
    return _nombre(repo.utilisateur_actif(), nature)


def restant(nature: str) -> int:
    return max(0, LIMITES[nature] - utilises(nature))


def limite_atteinte(nature: str) -> bool:
    return repo.est_demo() or restant(nature) <= 0


def message_limite(nature: str) -> str:
    return f"Limite de {LIMITES[nature]} {LIBELLES[nature]} par jour atteinte."


def _par_minute(cle: str, maximum: int) -> bool:
    maintenant = time.time()
    with _verrou:
        q = _minute.setdefault(cle, deque())
        while q and maintenant - q[0] > 60:
            q.popleft()
        return len(q) < maximum


def verifier(nature: str) -> None:
    """Lève QuotaDepasse si l'appel IA n'est pas permis maintenant. Note la tentative pour le limiteur."""
    if repo.est_demo():
        raise QuotaDepasse("IA désactivée sur le compte démo.")
    uid = repo.utilisateur_actif()
    if _nombre(uid, nature) >= LIMITES[nature]:
        raise QuotaDepasse(message_limite(nature))
    if _nombre(None, "*") >= config.quota_ia_global():
        raise QuotaDepasse("Plafond journalier d'appels IA de l'application atteint. Réessayez demain.")
    if not _par_minute(uid, config.IA_MAX_PAR_MINUTE_COMPTE) or not _par_minute("*", config.IA_MAX_PAR_MINUTE_GLOBAL):
        raise QuotaDepasse("Trop de demandes IA en une minute. Patientez un instant.")
    maintenant = time.time()
    with _verrou:
        _minute[uid].append(maintenant)
        _minute["*"].append(maintenant)


def enregistrer(nature: str) -> None:
    """Compte un appel réussi (en base si possible, sinon en mémoire du processus)."""
    uid = repo.utilisateur_actif()
    ecrit = False
    if repo.table_disponible("usage_ia"):
        try:
            repo.inserer("usage_ia", {"nature": nature})
            ecrit = True
        except Exception as e:
            journal.warning("usage_ia : écriture impossible (%s)", type(e).__name__)
    if not ecrit and nature == "chat":  # repli d'avant migration : une ligne par message, comme avant
        try:
            repo.inserer("chat_log", {})
            ecrit = True
        except Exception as e:
            journal.warning("chat_log : écriture impossible (%s)", type(e).__name__)
    with _verrou:
        if not ecrit and nature != "analyse":  # une analyse est déjà comptée par sa ligne analyses_*
            cle = (uid, nature, _jour())
            _memoire[cle] = _memoire.get(cle, 0) + 1
        for c in ((uid, nature, _jour()), ("*", "*", _jour())):
            if c in _comptes:
                n, t = _comptes[c]
                _comptes[c] = (n + 1, t)
