"""Harnais AppTest : lance l'application avec faux Supabase et faux Yahoo, avant ou après la refonte."""
from __future__ import annotations

import importlib
import sys
import time

import streamlit as st
from streamlit.testing.v1 import AppTest

import pathlib

from tests.fakes import FauxSupabase, FauxYahoo, base_fictive

RACINE = pathlib.Path(__file__).resolve().parent.parent
SECRETS = {
    "SUPABASE_URL": "https://fictif.invalid", "SUPABASE_KEY": "cle-fictive",
    "AUTO_CONNEXION_DEMO": False,
    "users": {"demo": {"password": "demo", "demo": True},
              "theo": {"password": "mot-de-passe-fictif-1", "demo": False},
              "alice": {"password": "mot-de-passe-fictif-2", "demo": False}},
}


def _mod(*noms):
    for n in noms:
        try:
            return importlib.import_module(n)
        except ImportError:
            continue
    raise ImportError(noms)


def apres_refonte() -> bool:
    try:
        importlib.import_module("pea.data.repo")
        return True
    except ImportError:
        return False


def vider_caches() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()
    if apres_refonte():
        _mod("pea.data.repo").reinitialiser_pour_tests()
        _mod("pea.data.marche").reinitialiser_pour_tests()
        _mod("pea.services.quotas").reinitialiser_pour_tests()
        _mod("pea.services.auth").reinitialiser_pour_tests()
        _mod("pea.services.partage").reinitialiser_pour_tests()
        _mod("pea.services.suivi").reinitialiser_pour_tests()
        _mod("pea.services.ia.client").reinitialiser_pour_tests()


def brancher(base: FauxSupabase, yahoo: FauxYahoo) -> None:
    """Remplace Supabase et Yahoo par les faux, dans les modules réellement utilisés par l'application."""
    if apres_refonte():
        _mod("pea.data.repo").definir_client(base)
        _mod("pea.data.marche").definir_yahoo(yahoo)
    else:
        db, donnees = _mod("db"), _mod("donnees")
        db._client = lambda: base
        donnees.yf = yahoo


def nouvelle_app(uid: str | None, base: FauxSupabase | None = None, yahoo: FauxYahoo | None = None,
                 secrets: dict | None = None, timeout: int = 90, vider: bool = True) -> tuple[AppTest, FauxSupabase, FauxYahoo]:
    if vider:
        vider_caches()
    base = base or base_fictive()
    yahoo = yahoo or FauxYahoo()
    brancher(base, yahoo)
    at = AppTest.from_file(str(RACINE / "app.py"), default_timeout=timeout)
    for k, v in {**SECRETS, **(secrets or {})}.items():
        at.secrets[k] = v
    if uid:
        at.session_state["user_id"] = uid
    return at, base, yahoo


def chronometrer(f):
    t = time.perf_counter()
    r = f()
    return r, time.perf_counter() - t
