"""Écritures de suivi faites après l'affichage : dernier prix connu (tickers) et point du jour (snapshots).

Limitées par compte : snapshots au plus une fois par quart d'heure, derniers prix au plus une fois par
30 min (le cours courant vient du cache marché partagé). Jamais pour la démo. Une panne est journalisée,
jamais affichée : elle ne doit pas bloquer la page.
"""
from __future__ import annotations

import logging
import threading
import time

import pandas as pd

from pea import config
from pea.data import repo

journal = logging.getLogger(__name__)
_derniere: dict = {}   # (uid, nature) -> horodatage de la dernière écriture
_verrou = threading.Lock()


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _derniere.clear()


def _permis(uid: str, nature: str, intervalle: float) -> bool:
    with _verrou:
        if time.time() - _derniere.get((uid, nature), 0) < intervalle:
            return False
        _derniere[(uid, nature)] = time.time()
        return True


def memoriser(maj_prix: list[dict], snaps: pd.DataFrame, jour: pd.Timestamp, valeur: float, apports: float,
              autorise_snapshot: bool) -> None:
    """`autorise_snapshot` : jour ouvré, journal non vide et aucun cours estimé (règle d'origine)."""
    try:
        if repo.est_demo():
            return
        uid = repo.utilisateur_actif()
        if maj_prix and _permis(uid, "prix", config.PRIX_ECRITURE_INTERVALLE_S):
            repo.upsert("tickers", maj_prix, "isin")
        if not autorise_snapshot:
            return
        nouveau = {"valeur": round(valeur, 2), "apports": round(apports, 2)}
        ligne = snaps[snaps["date"] == jour]
        change = ligne.empty or any(abs(ligne.iloc[0][k] - v) > 0.01 for k, v in nouveau.items())
        if change and (ligne.empty or _permis(uid, "snapshot", config.SNAPSHOT_INTERVALLE_S)):
            repo.upsert("snapshots", [{"date": jour, **nouveau}], "date")
    except Exception as e:  # un échec d'écriture ne doit jamais bloquer l'affichage
        journal.warning("Écriture de suivi impossible (%s)", type(e).__name__)
