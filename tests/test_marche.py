"""Cache marché : téléchargement groupé, L1/L2, cache négatif, recul après 429, actualisation bornée."""
import time

import pytest

from pea import config
from pea.data import marche, repo
from tests.fakes import FauxYahoo, base_fictive
from tests.harnais import SECRETS

TICKERS = ("ALP.PA", "GAM.PA", "DEL.AS", "EPS.MI")


@pytest.fixture
def env():
    config.definir_secrets_pour_tests(SECRETS)
    repo.reinitialiser_pour_tests()
    marche.reinitialiser_pour_tests()
    b, y = base_fictive(), FauxYahoo()
    repo.definir_client(b)
    marche.definir_yahoo(y)
    yield b, y
    config.definir_secrets_pour_tests(None)
    marche.reinitialiser_pour_tests()


def test_un_seul_telechargement_groupe_puis_cache(env):
    b, y = env
    v, _ = marche.cours_batch(TICKERS, attente=10)
    assert set(v) == set(TICKERS) and all(x["prix"] > 0 for x in v.values())
    assert dict(y.appels) == {"download": 1}
    marche.cours_batch(TICKERS, attente=10)
    assert dict(y.appels) == {"download": 1}  # L1 chaud : aucun appel


def test_l2_partage_entre_processus(env):
    b, y = env
    marche.cours_batch(TICKERS, attente=10)
    time.sleep(0.05)
    assert b.nb("upsert", "marche_cache") == 1
    marche.reinitialiser_pour_tests()  # nouveau processus (réveil de Streamlit Cloud)
    v, _ = marche.cours_batch(TICKERS, attente=10)
    assert set(v) == set(TICKERS) and y.appels["download"] == 1  # servi par marche_cache


def test_sans_migration_repli_memoire(env):
    b, y = env
    b.tables_absentes.add("marche_cache")
    v, _ = marche.cours_batch(TICKERS, attente=10)
    assert len(v) == 4


def test_cache_negatif(env):
    b, y = env
    y.indisponibles = {"KO.PA"}
    v, _ = marche.cours_batch(("KO.PA",), attente=10)
    assert v == {}
    n = y.total()
    marche.cours_batch(("KO.PA",), attente=10)
    assert y.total() == n  # échec mémorisé : pas de nouvel appel immédiat


def test_recul_apres_limitation(env):
    b, y = env
    y.limitation = True
    marche.cours_batch(TICKERS, attente=10)
    assert marche.en_recul()
    n = y.total()
    marche.cours_batch(TICKERS, attente=10)
    assert y.total() == n  # aucune requête pendant le recul


def test_attente_bornee_et_rafraichissement_en_arriere_plan(env):
    b, y = env
    y.latence = 0.5
    t = time.perf_counter()
    v, _ = marche.cours_batch(TICKERS, attente=0.05)
    assert time.perf_counter() - t < 0.4 and v == {}
    assert marche.rafraichissement_en_cours()
    time.sleep(0.8)
    v, _ = marche.cours_batch(TICKERS, attente=0)
    assert len(v) == 4 and not marche.rafraichissement_en_cours()


def test_actualiser_ne_relance_que_les_cours_anciens(env):
    b, y = env
    marche.cours_batch(TICKERS, attente=10)
    marche.actualiser_cours(TICKERS)
    marche.cours_batch(TICKERS, attente=10)
    assert y.appels["download"] == 1  # cours de moins de 60 s : pas de nouvel appel


def test_ohlc_et_historiques_groupes(env):
    b, y = env
    o = marche.ohlc_batch(("ALP.PA", "DEL.AS"))
    assert all(len(df) >= 20 for df in o.values()) and y.appels["download"] == 1
    h = marche.historiques_groupes({"ALP.PA", "GAM.PA"}, "2025-01-01")
    assert set(h) == {"ALP.PA", "GAM.PA"} and y.appels["download"] == 2


def test_historique_cloture_echec_mis_en_cache(env):
    b, y = env
    y.indisponibles = {"^KO"}
    for _ in range(3):
        with pytest.raises(ValueError):
            marche.historique_cloture("^KO", "2025-01-01")
    assert y.appels["history"] == 1
