"""Partage de la performance entre comptes : seul l'indice TWR base 100 sort d'ici (jamais valeur, apports
ni positions). Le compte démo ne voit rien et ne partage rien ; soi-même et les comptes absents des secrets
sont exclus. Pseudo vide = « Anonyme » ; pseudos identiques suffixés (2)… Cache 2 min.
"""
from __future__ import annotations

import threading
import time

import pandas as pd

from pea import config
from pea.data import repo
from pea.domain import calculs as C

TTL_S = 120
_cache: dict = {}
_verrou = threading.Lock()
VIDE = ("pseudo", "date", "twr")


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _cache.clear()


def _eligibles(uid: str) -> tuple:
    return tuple(sorted(u for u, d in config.comptes().items() if u != uid and not d.get("demo", u == "demo")))


def courbes(choix: list[dict], points: pd.DataFrame) -> pd.DataFrame:
    """Pur : (choix de partage, points bruts) -> colonnes pseudo, date, twr (base 100 au 1er point)."""
    sorties, pris = [], {}
    for o in choix:
        g = points[points["user_id"] == o["user_id"]].dropna()
        if len(g) < 2:
            continue
        nom = " ".join(str(o.get("pseudo") or "").split())[:repo.PSEUDO_MAX] or "Anonyme"
        pris[nom] = pris.get(nom, 0) + 1
        if pris[nom] > 1:  # pseudos identiques : suffixe pour distinguer les courbes
            nom = f"{nom} ({pris[nom]})"
        t = C.calcul_twr(g[["date", "valeur", "apports"]])
        t["pseudo"] = nom
        sorties.append(t[["pseudo", "date", "twr"]])
    return pd.concat(sorties, ignore_index=True) if sorties else pd.DataFrame(columns=list(VIDE))


def performances_partagees() -> pd.DataFrame:
    """Courbes TWR des AUTRES comptes ayant autorisé le partage ; vide pour la démo."""
    if repo.est_demo():
        return pd.DataFrame(columns=list(VIDE))
    uid = repo.utilisateur_actif()
    cle = (uid, _eligibles(uid))
    with _verrou:
        e = _cache.get(cle)
        if e and time.time() - e[0] < TTL_S:
            return e[1].copy()
    df = courbes(*repo.partages_bruts(cle[1]))
    with _verrou:
        _cache[cle] = (time.time(), df)
    return df.copy()
