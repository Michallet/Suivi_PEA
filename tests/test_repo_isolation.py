"""Isolation des comptes : aucune donnée d'un compte n'est lisible ni modifiable depuis un autre."""
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


def en_tant_que(uid, session=None):
    session = {} if session is None else session
    repo.definir_contexte(lambda: repo.Contexte(uid, config.est_demo(uid), session))
    return session


def test_sans_compte_aucune_requete(base):
    en_tant_que(None)
    with pytest.raises(PermissionError):
        repo.lire("transactions")
    with pytest.raises(PermissionError):
        repo.inserer("transactions", {"isin": "X"})
    assert base.nb() == 0


@pytest.mark.parametrize("table", ["transactions", "versements", "tickers", "snapshots", "watchlist", "scenarios"])
def test_lecture_limitee_au_compte(base, table):
    en_tant_que("theo")
    df = repo.lire(table)
    attendu = len(base.lignes(table, "theo"))
    assert len(df) == attendu > 0 and "user_id" not in df.columns
    requetes = [a for a in base.appels if a[1] == table]
    assert requetes  # chaque requête porte le filtre user_id (vérifié par le faux : sinon il renverrait tout)


def test_precharger_un_aller_retour_puis_cache(base):
    en_tant_que("theo")
    repo.precharger()
    assert base.resume() == {"rpc:pea_charger_compte": 1}
    a = repo.lire("transactions")
    repo.lire("watchlist")
    assert base.nb() == 1  # servi par le cache
    en_tant_que("alice")
    b = repo.lire("transactions")
    assert not set(a["id"]) & set(b["id"])  # le cache ne mélange jamais deux comptes


def test_precharger_sans_migration_lectures_paralleles(base):
    base.rpc_disponibles.clear()
    en_tant_que("theo")
    repo.precharger()
    assert base.nb("rpc") == 1 and base.nb("select") == 12
    repo.precharger()
    assert base.nb() == 13  # cache frais : rien de plus


def test_ecritures_forcent_le_compte(base):
    en_tant_que("theo")
    row = repo.inserer("versements", {"date": pd.Timestamp("2025-06-01"), "type": "VERSEMENT", "montant": 5.0,
                                      "user_id": "alice"})  # tentative d'usurpation ignorée
    assert row["id"] and [l["user_id"] for l in base.tables["versements"] if l["id"] == row["id"]] == ["theo"]


def test_impossible_de_modifier_ou_supprimer_la_ligne_d_un_autre(base):
    id_alice = base.lignes("transactions", "alice")[0]["id"]
    en_tant_que("theo")
    repo.modifier("transactions", id_alice, {"prix": 0.01})
    repo.supprimer("transactions", id_alice)
    repo.supprimer_plusieurs("transactions", [id_alice, id_alice + 1])
    lignes = [l for l in base.tables["transactions"] if l["id"] == id_alice]
    assert lignes and lignes[0]["prix"] != 0.01


def test_upsert_cle_composee_avec_le_compte(base):
    en_tant_que("theo")
    repo.upsert("secteurs", [{"isin": "FR0000000001", "secteur": "Test"}], "isin")
    en_tant_que("alice")
    repo.upsert("secteurs", [{"isin": "FR0000000001", "secteur": "Autre"}], "isin")
    assert {(l["user_id"], l["secteur"]) for l in base.tables["secteurs"] if l["isin"] == "FR0000000001"} == \
        {("theo", "Test"), ("alice", "Autre")}


def test_invalidation_limitee_au_compte(base):
    en_tant_que("theo")
    repo.lire("transactions")
    en_tant_que("alice")
    repo.lire("transactions")
    n = base.nb()
    en_tant_que("theo")
    repo.invalider_compte()
    repo.lire("transactions")
    en_tant_que("alice")
    repo.lire("transactions")
    assert base.nb() == n + 1  # seul le compte de theo a été relu


def test_ecriture_invalide_sa_table(base):
    en_tant_que("theo")
    avant = len(repo.lire("dividendes"))
    repo.inserer("dividendes", {"date": pd.Timestamp("2025-06-01"), "isin": "X", "montant": 1.0})
    assert len(repo.lire("dividendes")) == avant + 1


def test_tables_en_croissance_bornees(base):
    en_tant_que("theo")
    for i in range(5):
        repo.inserer("analyses_ia", {"modele": "m", "empreinte": str(i), "resultat": {}})
    df = repo.lire("analyses_ia")
    assert len(df) == 1 and df.iloc[0]["empreinte"] == "4"


def test_appliquer_modifs_en_lot(base):
    en_tant_que("theo")
    avant = repo.lire("versements")
    apres = avant.copy()
    apres = apres[apres["id"] != apres["id"].iloc[0]]               # 1 suppression
    apres.loc[apres.index[0], "montant"] = 999.0                    # 1 modification
    neuf = pd.DataFrame([{"id": None, "date": pd.Timestamp("2025-06-01"), "type": "VERSEMENT", "montant": 1.0, "libelle": None}] * 2)
    apres = pd.concat([apres, neuf], ignore_index=True)
    base.remise_a_zero()
    assert repo.appliquer_modifs("versements", avant, apres) == (2, 1, 1)
    assert base.resume() == {"delete:versements": 1, "update:versements": 1, "insert:versements": 1}


def test_compter_par_compte_et_global(base):
    en_tant_que("theo")
    repo.inserer("usage_ia", {"nature": "chat"})
    en_tant_que("alice")
    repo.inserer("usage_ia", {"nature": "chat"})
    repo.inserer("usage_ia", {"nature": "analyse"})
    assert repo.compter("usage_ia", "2000-01-01T00:00:00+00:00", {"nature": "chat"}) == 1
    assert repo.compter_global("usage_ia", "2000-01-01T00:00:00+00:00") == 3


def test_table_absente_signalee_sans_boucle(base):
    base.tables_absentes.add("usage_ia")
    en_tant_que("theo")
    with pytest.raises(RuntimeError):
        repo.compter("usage_ia", "2000-01-01")
    assert not repo.table_disponible("usage_ia")
    n = base.nb()
    with pytest.raises(RuntimeError):
        repo.compter("usage_ia", "2000-01-01")
    assert base.nb() == n  # pas de nouvelle requête pendant 10 min


def test_partage_ne_sort_que_les_comptes_volontaires(base):
    from pea.services import partage
    partage.reinitialiser_pour_tests()
    for l in base.tables["partage"]:
        if l["user_id"] == "alice":
            l["partage"] = False
    en_tant_que("theo")
    df = partage.performances_partagees()
    assert set(df.columns) == {"pseudo", "date", "twr"}
    assert set(df["pseudo"]) == set()  # alice ne partage plus, demo est exclu
    for l in base.tables["partage"]:
        l["partage"] = True
    partage.reinitialiser_pour_tests()
    df = partage.performances_partagees()
    assert set(df["pseudo"]) == {"pseudo-alice"} and df["twr"].iloc[0] == pytest.approx(100.0)
    en_tant_que("demo")
    assert partage.performances_partagees().empty
    with pytest.raises(PermissionError):
        repo.enregistrer_partage(True, "x")
