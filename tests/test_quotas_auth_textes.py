"""Quotas d'IA, authentification durcie et nettoyage des textes externes."""
import pytest

from pea import config
from pea.data import repo
from pea.domain import textes
from pea.services import auth, quotas
from tests.fakes import base_fictive
from tests.harnais import SECRETS


@pytest.fixture
def base():
    config.definir_secrets_pour_tests(SECRETS)
    for m in (repo, quotas, auth):
        m.reinitialiser_pour_tests()
    b = base_fictive()
    repo.definir_client(b)
    yield b
    config.definir_secrets_pour_tests(None)
    repo.reinitialiser_pour_tests()


def en_tant_que(uid):
    repo.definir_contexte(lambda: repo.Contexte(uid, config.est_demo(uid), {}))


def test_demo_refusee_cote_serveur(base):
    en_tant_que("demo")
    with pytest.raises(quotas.QuotaDepasse):
        quotas.verifier("chat")
    assert quotas.limite_atteinte("analyse")


def test_quota_journalier_compte_en_base(base, monkeypatch):
    monkeypatch.setitem(quotas.LIMITES, "chat", 2)
    en_tant_que("theo")
    for _ in range(2):
        quotas.verifier("chat")
        quotas.enregistrer("chat")
    with pytest.raises(quotas.QuotaDepasse, match="Limite de 2 messages"):
        quotas.verifier("chat")
    assert len(base.lignes("usage_ia", "theo")) == 2
    en_tant_que("alice")
    quotas.verifier("chat")  # le quota est par compte


def test_quota_survit_a_une_nouvelle_session(base, monkeypatch):
    monkeypatch.setitem(quotas.LIMITES, "capture", 1)
    en_tant_que("theo")
    quotas.verifier("capture")
    quotas.enregistrer("capture")
    quotas.reinitialiser_pour_tests()  # nouveau processus / nouvelle session : le compteur est en base
    with pytest.raises(quotas.QuotaDepasse):
        quotas.verifier("capture")


def test_plafond_global_et_limiteur(base, monkeypatch):
    monkeypatch.setattr(config, "QUOTA_IA_GLOBAL_PAR_JOUR", 3)
    en_tant_que("alice")
    for _ in range(3):
        quotas.verifier("analyse")
        quotas.enregistrer("analyse")
    en_tant_que("theo")
    with pytest.raises(quotas.QuotaDepasse, match="Plafond journalier"):
        quotas.verifier("chat")
    monkeypatch.setattr(config, "QUOTA_IA_GLOBAL_PAR_JOUR", 1000)
    quotas.reinitialiser_pour_tests()
    with pytest.raises(quotas.QuotaDepasse, match="une minute"):
        for _ in range(config.IA_MAX_PAR_MINUTE_COMPTE + 1):
            quotas.verifier("chat")


def test_quota_sans_migration_repli(base):
    base.tables_absentes.add("usage_ia")
    en_tant_que("theo")
    quotas.verifier("chat")
    quotas.enregistrer("chat")  # repli : une ligne chat_log, comme avant
    assert len(base.lignes("chat_log", "theo")) == 1
    quotas.reinitialiser_pour_tests()
    assert quotas.utilises("chat") == 1


def test_verification_mot_de_passe_en_clair(base):
    assert auth.verifier_identifiants("theo", "mot-de-passe-fictif-1")
    assert not auth.verifier_identifiants("theo", "faux")
    assert not auth.verifier_identifiants("inconnu", "x")
    assert not auth.verifier_identifiants("inconnu", "")


def test_blocage_par_session_et_non_par_compte(base):
    s_attaquant, s_theo = {}, {}
    for _ in range(config.MAX_ECHECS_SESSION):
        auth.noter_echec("theo", s_attaquant)
    assert auth.attente_session("theo", s_attaquant) > 0
    assert auth.attente_session("theo", s_theo) == 0  # le vrai propriétaire n'est pas bloqué
    assert 0 < auth.ralentissement("theo") <= auth.RALENTISSEMENT_MAX_S


@pytest.mark.parametrize("entree,interdit", [
    ("Voir [ici](https://pirate.example) !", "pirate"),
    ("![x](https://img.example/a.png) ok", "img.example"),
    ("<a href='https://x.example'>clic</a>", "x.example"),
    ("va sur www.exemple.com maintenant", "exemple.com"),
    ("[a][1]\n[1]: https://ref.example", "ref.example"),
])
def test_sortie_ia_sans_lien(entree, interdit):
    assert interdit not in textes.nettoyer_sortie_ia(entree)


def test_texte_ia_mise_en_forme_conservee():
    assert textes.nettoyer_sortie_ia("**Fort** :\n- point 1\n- point 2") == "**Fort** :\n- point 1\n- point 2"


def test_echappement_des_noms():
    t = textes.echapper_markdown("[clic](https://x) *gras* <b>")
    assert "[" not in t.replace("\\[", "") and "<" not in t.replace("\\<", "")
    assert textes.sur_pour_graphique("<a href='x'>p</a>") == "&lt;a href='x'&gt;p&lt;/a&gt;"
