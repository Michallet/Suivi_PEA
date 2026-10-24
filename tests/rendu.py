"""Empreinte du rendu (types et textes des éléments, dans l'ordre) de chaque écran, par compte.

La référence `tests/golden/rendu.json` a été produite avec l'`app.py` de l'étape 1 (avant découpage en pages) :
le test vérifie que l'application découpée affiche exactement les mêmes éléments.
Régénérer : python -m tests.rendu <fichier_app> (seulement si un changement visible est voulu).
"""
from __future__ import annotations

import json
import re
import sys
import warnings

from streamlit.testing.v1 import AppTest

from tests.fakes import FauxYahoo, base_fictive
from tests.harnais import RACINE, SECRETS, brancher, vider_caches

GOLDEN = RACINE / "tests" / "golden" / "rendu.json"
ONGLETS = ["📊 Portefeuille", "📈 Historique", "🔭 Projet", "👀 Watchlist", "➕ Saisie"]
ACTIONS = ["Import par captures", "Dividende", "Versement / retrait", "Secteurs", "Corriger / supprimer",
           "Maintenance & sauvegarde"]
COMPTES = ("theo", "alice", "demo")
_DATES = [(re.compile(r"\d{4}-\d{2}-\d{2}"), "AAAA-MM-JJ"), (re.compile(r"\d{2}/\d{2}/\d{4}"), "JJ/MM/AAAA"),
          (re.compile(r"\b\d{2}:\d{2}\b"), "HH:MM")]


def _texte(v) -> str:
    s = str(v)[:160]
    for motif, remplacement in _DATES:
        s = motif.sub(remplacement, s)
    return s


def elements(at) -> list:
    sortie = []

    def parcourir(n):
        t = type(n).__name__
        v = None
        for attribut in ("value", "label", "body"):
            if hasattr(n, attribut):
                try:
                    v = None if (attribut == "value" and t == "PlotlyChart") else getattr(n, attribut)
                except Exception:
                    v = None
                break
        if t not in ("Block", "ElementTree"):
            sortie.append([t, _texte(v)])
        enfants = getattr(n, "children", None)
        for c in (enfants.values() if isinstance(enfants, dict) else []):
            parcourir(c)

    parcourir(at._tree)
    return sortie


def rendu(fichier: str, uid: str) -> dict:
    vider_caches()
    brancher(base_fictive(), FauxYahoo())
    at = AppTest.from_file(str(RACINE / fichier), default_timeout=90)
    for cle, v in SECRETS.items():
        at.secrets[cle] = v
    at.session_state["user_id"] = uid
    res = {}
    for onglet in ONGLETS:
        at.session_state["onglet"] = onglet
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        res[onglet] = elements(at)
    for action in ACTIONS:
        next(x for x in at.selectbox if x.label == "Action").set_value(action).run()
        assert not at.exception, [e.value for e in at.exception]
        res[action] = elements(at)
    return res


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    fichier = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    GOLDEN.write_text(json.dumps({u: rendu(fichier, u) for u in COMPTES}, ensure_ascii=False, indent=0),
                      encoding="utf-8")
    print("écrit :", GOLDEN)
