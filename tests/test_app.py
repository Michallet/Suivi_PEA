"""Application complète (AppTest) avec faux Supabase et faux Yahoo : parité, isolation, budgets."""
import time
import warnings

import pytest

from tests.fakes import base_fictive
from tests.harnais import nouvelle_app

warnings.filterwarnings("ignore")
ONGLETS = ["📊 Portefeuille", "📈 Historique", "🔭 Projet", "👀 Watchlist", "➕ Saisie"]

# Valeurs affichées par l'application D'ORIGINE avec les mêmes faux (tests/mesures.py avant refonte).
METRIQUES_ORIGINE_THEO = [("Valeur du PEA", "8 109,17 €"), ("Plus-value globale", "4 709,17 €"),
                          ("Apports nets", "3 400,00 €"), ("Cash disponible", "423,20 €"),
                          ("Concentration max", "91 %"), ("Lignes actives", "4")]


def _textes(at) -> str:
    morceaux = []
    for groupe in (at.markdown, at.caption, at.metric, at.warning, at.info, at.subheader):
        for e in groupe:
            morceaux.append(str(getattr(e, "value", "")) + str(getattr(e, "label", "")))
    return "\n".join(morceaux)


def test_parite_des_chiffres_avec_l_application_d_origine():
    at, _, _ = nouvelle_app("theo")
    at.run()
    assert not at.exception
    assert [(m.label, m.value) for m in at.metric][:6] == METRIQUES_ORIGINE_THEO


@pytest.mark.parametrize("uid", ["theo", "alice", "demo"])
def test_tous_les_onglets_sans_erreur_et_sans_fuite(uid):
    at, base, _ = nouvelle_app(uid)
    autres = {"theo", "alice", "demo"} - {uid}
    for onglet in ONGLETS:
        at.session_state["onglet"] = onglet
        at.run()
        assert not at.exception, (onglet, [e.value for e in at.exception])
        texte = _textes(at)
        for autre in autres:  # notes de watchlist et noms de scénario portent le nom du compte
            assert f"note de {autre}" not in texte and f"Scénario de {autre}" not in texte, (onglet, autre)


def test_demo_n_ecrit_jamais_en_base():
    at, base, _ = nouvelle_app("demo")
    for onglet in ONGLETS:
        at.session_state["onglet"] = onglet
        at.run()
    ecritures = [a for a in base.appels if a[0] in ("insert", "update", "delete", "upsert") and a[1] != "marche_cache"]
    assert not ecritures
    assert "Vos modifications ne sont visibles que par vous" in _textes(at)


def test_budget_rerun_a_chaud_et_onglet_paresseux():
    at, base, yahoo = nouvelle_app("theo")
    at.run()
    time.sleep(0.2)
    at.run()  # les écritures de suivi du 1er passage sont faites
    base.remise_a_zero()
    yahoo.appels.clear()
    t = time.perf_counter()
    at.run()
    assert base.nb() <= 1 and yahoo.total() == 0
    assert time.perf_counter() - t < 1  # budget : moins de 1 s (contexte mémoïsé)
    # onglet Portefeuille ouvert : l'historique (indice Yahoo, partage) ne s'exécute pas
    assert yahoo.appels.get("history", 0) == 0 and base.nb("select", "partage") == 0


def test_budget_premiere_session_a_froid():
    at, base, yahoo = nouvelle_app("theo")
    at.run()
    lectures = [a for a in base.appels if a[0] in ("select", "rpc")]
    assert base.nb("rpc") == 1 and len(lectures) <= 2  # budget : RPC + cache marché partagé
    assert yahoo.appels["download"] == 1 and yahoo.appels.get("fast_info", 0) == 0


def test_dix_sessions_un_seul_telechargement():
    base = base_fictive()
    at, base, yahoo = nouvelle_app("theo", base)
    at.run()
    for n in range(9):
        a, _, _ = nouvelle_app(("theo", "alice", "demo")[n % 3], base, yahoo, vider=False)
        a.run()
        assert not a.exception
    assert yahoo.appels["download"] == 1


def test_application_sans_migration_sql():
    at, base, yahoo = nouvelle_app("theo", base_fictive(migration=False))
    at.run()
    assert [(m.label, m.value) for m in at.metric][:6] == METRIQUES_ORIGINE_THEO
    for onglet in ONGLETS[1:]:
        at.session_state["onglet"] = onglet
        at.run()
        assert not at.exception, onglet


def test_actualiser_n_invalide_que_le_compte_courant():
    base = base_fictive()
    at_t, base, yahoo = nouvelle_app("theo", base)
    at_t.run()
    at_a, _, _ = nouvelle_app("alice", base, yahoo, vider=False)
    at_a.run()
    base.remise_a_zero()
    yahoo.appels.clear()
    next(b for b in at_t.button if b.label == "🔄").click().run()
    at_a.run()
    assert yahoo.total() == 0  # cours de moins de 60 s : Yahoo n'est pas relancé
    relus = {a[2] for a in base.appels if a[0] in ("select", "rpc")}
    assert base.nb("rpc") == 1  # seul theo est relu ; alice reste servie par le cache
