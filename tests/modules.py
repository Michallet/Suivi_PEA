"""Résolution des modules testés : avant la refonte (modules à la racine) ou après (paquet `pea`).

Les mêmes scénarios de caractérisation tournent ainsi AVANT et APRÈS le déplacement du code ;
les valeurs attendues (tests/golden/) ont été produites par le code d'origine.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import types

import numpy as np
import pandas as pd

RACINE = pathlib.Path(__file__).resolve().parent.parent


def _essayer(*noms):
    for n in noms:
        try:
            return importlib.import_module(n)
        except ImportError:
            continue
    raise ImportError(noms)


def calculs():
    return _essayer("pea.domain.calculs", "calculs")


def technique():
    return _essayer("pea.domain.technique", "technique")


def import_ecran():
    return _essayer("pea.domain.import_ecran", "import_ecran")


def concurrents():
    """Partie pure des concurrents (après refonte : pea.domain.concurrents ; avant : concurrents.py)."""
    return _essayer("pea.domain.concurrents", "concurrents")


def formats():
    """fmt, pastille, formater_gros_nombre, sans_parentheses…

    Avant la refonte ces fonctions vivent dans app.py (impossible à importer : il lance Streamlit) :
    on en extrait les définitions par `ast` pour figer le comportement d'origine.
    """
    try:
        f = importlib.import_module("pea.domain.formats")
        g = importlib.import_module("pea.domain.fondamentaux")
        return types.SimpleNamespace(
            fmt=f.fmt, pastille=f.pastille, sans_parentheses=f.sans_parentheses, _court=f.court, _cellule=f.cellule,
            url_google_actualites=f.url_google_actualites, lien_actualites=f.lien_actualites,
            formater_gros_nombre=f.formater_gros_nombre, lignes_fondamentaux=g.lignes_fondamentaux,
            est_etf=g.est_etf, valeur_grandeur=g.valeur_grandeur)
    except ImportError:
        pass
    src = (RACINE / "app.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    voulus = {"fmt", "pastille", "sans_parentheses", "_present", "_court", "_cellule", "est_etf",
              "valeur_grandeur", "lignes_fondamentaux", "url_google_actualites", "lien_actualites"}
    ns: dict = {"pd": pd, "np": np, "C": calculs(), "quote_plus": __import__("urllib.parse", fromlist=["x"]).quote_plus,
                "VERT": "#16a34a", "ROUGE": "#dc2626",
                "RATIOS_POSITIFS": {"per", "per_prev", "ev_ebitda", "p_ca"}}
    for noeud in arbre.body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name in voulus:
            exec(compile(ast.Module([noeud], []), "app.py", "exec"), ns)
    m = types.SimpleNamespace(**{k: v for k, v in ns.items() if k in voulus})
    m.formater_gros_nombre = calculs().formater_gros_nombre
    return m


def ia_pure():
    """Fonctions pures de llm.py (avant) ou du paquet pea.services.ia (après)."""
    try:
        return importlib.import_module("pea.services.ia")
    except ImportError:
        return importlib.import_module("llm")
