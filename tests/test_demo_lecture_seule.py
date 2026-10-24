"""Compte démo : lecture seule en base, modifications gardées dans la session du visiteur."""
import pandas as pd
import pytest

from pea import config
from pea.data import repo
from tests.fakes import base_fictive
from tests.harnais import SECRETS


@pytest.fixture
def base():
    config.definir_secrets_pour_tests(SECRETS)
    repo.reinitialiser_pour_tests()
    b = base_fictive()
    repo.definir_client(b)
    yield b
    config.definir_secrets_pour_tests(None)
    repo.reinitialiser_pour_tests()


def session_demo():
    s = {}
    return s, (lambda: repo.Contexte("demo", True, s))


def test_aucune_ecriture_en_base(base):
    s1, f1 = session_demo()
    repo.definir_contexte(f1)
    avant = repo.lire("transactions")
    row = repo.inserer("transactions", {"date": pd.Timestamp("2025-06-02"), "isin": "FR00ALPHA014", "type": "ACHAT",
                                        "quantite": 1.0, "prix": 10.0, "frais": 0.0})
    repo.upsert("watchlist", [{"isin": "FR00ALPHA014", "note": "x"}], "isin")
    repo.modifier("scenarios", repo.lire("scenarios")["id"].iloc[0], {"versement": 50.0})
    repo.inserer_lot("versements", [{"date": pd.Timestamp("2025-06-02"), "type": "VERSEMENT", "montant": 1.0}])
    assert not [a for a in base.appels if a[0] in ("insert", "update", "delete", "upsert")]
    assert len(repo.lire("transactions")) == len(avant) + 1 and row["id"]
    assert float(repo.lire("scenarios")["versement"].iloc[0]) == 50.0

    s2, f2 = session_demo()  # un autre visiteur ne voit rien de ces changements
    repo.definir_contexte(f2)
    assert len(repo.lire("transactions")) == len(avant)
    assert float(repo.lire("scenarios")["versement"].iloc[0]) == 0.0


def test_suppression_en_cascade_dans_la_session(base):
    s, f = session_demo()
    repo.definir_contexte(f)
    sid = int(repo.lire("scenarios")["id"].iloc[0])
    repo.inserer("scenario_trades", {"scenario_id": sid, "isin": "X", "type": "ACHAT", "quantite": 1.0, "prix": 1.0})
    assert len(repo.lire("scenario_trades")) == 1
    repo.supprimer("scenarios", sid)
    assert repo.lire("scenarios").empty and repo.lire("scenario_trades").empty
    assert base.lignes("scenarios", "demo")  # la base n'a pas bougé


def test_types_conserves(base):
    s, f = session_demo()
    repo.definir_contexte(f)
    repo.inserer("dividendes", {"date": pd.Timestamp("2025-06-02"), "isin": "X", "montant": 3.5})
    df = repo.lire("dividendes")
    assert pd.api.types.is_datetime64_any_dtype(df["date"]) and pd.api.types.is_numeric_dtype(df["montant"])
