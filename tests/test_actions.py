"""Actions de l'utilisateur dans l'application complète (AppTest, faux Supabase et faux Yahoo).

Connexion, déconnexion, transaction, scénario, watchlist, correction : sur un compte privé (écrit en base,
sous SON user_id uniquement) et sur la démo (rien en base, modifications gardées dans la session).
"""
import warnings

import pytest

from pea import config
from tests import fictives as F
from tests.harnais import nouvelle_app

warnings.filterwarnings("ignore")
ECRITURES = ("insert", "update", "delete", "upsert")


def _ecritures(base, table=None):
    return [a for a in base.appels if a[0] in ECRITURES and a[1] != "marche_cache" and (table is None or a[1] == table)]


def _ouvrir(at, onglet, base=None):
    at.session_state["onglet"] = onglet
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    if base is not None:  # écritures de suivi du 1er affichage (derniers cours, point du jour) mises de côté
        base.remise_a_zero()


def _bouton(at, label):
    return next(b for b in at.button if b.label == label)


def test_connexion_par_le_formulaire_puis_deconnexion_purge_la_session():
    at, _, _ = nouvelle_app(None)
    at.run()
    assert at.text_input(key="login_user").value == "demo"
    at.text_input(key="login_user").set_value("theo")
    at.text_input(key="login_password").set_value("faux")
    _bouton(at, "Entrer").click().run()
    assert any("incorrect" in e.value for e in at.error)

    at.text_input(key="login_password").set_value("mot-de-passe-fictif-1")
    _bouton(at, "Entrer").click().run()
    assert not at.exception and at.session_state["user_id"] == "theo"
    assert [m.value for m in at.metric][0] == "8\u202f109,17 €"
    assert any(str(c).startswith(config.PREFIXE_COMPTE) for c in list(at.session_state))

    _bouton(at, "🔒").click().run()
    restantes = [c for c in list(at.session_state) if str(c).startswith(config.PREFIXE_COMPTE)]
    assert not restantes and "user_id" not in at.session_state
    assert at.text_input(key="login_user")  # formulaire affiché


@pytest.mark.parametrize("uid", ["theo", "demo"])
def test_saisie_d_une_transaction(uid):
    at, base, _ = nouvelle_app(uid)
    _ouvrir(at, "➕ Saisie", base)
    avant = len(base.lignes("transactions", uid))
    _bouton(at, "Enregistrer").click().run()  # achat d'1 part de la 1re ligne détenue
    assert not at.exception
    if uid == "demo":
        assert not _ecritures(base)
        assert len(at.session_state["_pea_demo_tables"]["transactions"]) == avant + 1
    else:
        assert len(base.lignes("transactions", uid)) == avant + 1
        assert all(a[1] == "transactions" for a in _ecritures(base))
        assert len(base.lignes("transactions", "alice")) == avant  # aucun autre compte touché
    _ouvrir(at, "📊 Portefeuille")  # le contexte est reconstruit avec la nouvelle ligne


def test_isin_invalide_refuse_sans_ecriture():
    at, base, _ = nouvelle_app("theo")
    _ouvrir(at, "👀 Watchlist", base)
    at.text_input(key="c.wl.isin").set_value("FR0000000000")
    _bouton(at, "Ajouter").click().run()
    assert any("ISIN invalide" in e.value for e in at.error) and not _ecritures(base)


def test_ajout_a_la_watchlist():
    at, base, _ = nouvelle_app("theo")
    _ouvrir(at, "👀 Watchlist")
    at.text_input(key="c.wl.isin").set_value(F.ALPHA)  # titre connu : aucun appel Yahoo de résolution
    at.text_input(key="c.wl.note").set_value("à surveiller")
    _bouton(at, "Ajouter").click().run()
    assert not at.exception
    isins = {l["isin"] for l in base.lignes("watchlist", "theo")}
    assert F.ALPHA in isins and F.ALPHA not in {l["isin"] for l in base.lignes("watchlist", "alice")}
    assert at.text_input(key="c.wl.isin").value == ""  # champs remis à zéro après l'ajout


def test_scenario_creation_et_operation():
    at, base, _ = nouvelle_app("theo")
    _ouvrir(at, "🔭 Projet")
    at.text_input(key=next(t.key for t in at.text_input if t.label == "Nom")).set_value("Test fictif")
    _bouton(at, "Créer").click().run()
    assert not at.exception
    sc = [s for s in base.lignes("scenarios", "theo") if s["nom"] == "Test fictif"]
    assert sc and at.session_state["c.scenario.id"] == sc[0]["id"]
    _bouton(at, "Ajouter à ce scénario").click().run()  # achat fictif de 500 € de la 1re ligne
    assert not at.exception
    ops = [o for o in base.lignes("scenario_trades", "theo") if o["scenario_id"] == sc[0]["id"]]
    assert len(ops) == 1 and ops[0]["type"] == "ACHAT"
    assert not base.lignes("scenario_trades", "alice")
    assert not _ecritures(base, "transactions")  # le portefeuille réel n'est jamais modifié


def test_correction_en_lot():
    at, base, _ = nouvelle_app("theo")
    _ouvrir(at, "➕ Saisie")
    next(x for x in at.selectbox if x.label == "Action").set_value("Corriger / supprimer").run()
    base.remise_a_zero()
    _bouton(at, "💾 Enregistrer les modifications").click().run()  # aucune modification : aucune écriture
    assert not at.exception and not _ecritures(base)
    assert any("0 ajoutée(s), 0 modifiée(s), 0 supprimée(s)" in str(t.value) for t in at.toast)


def test_comptes_successifs_dans_la_meme_session_sans_fuite():
    """Démo, puis theo, puis alice dans le même navigateur : aucune trace du compte précédent."""
    at, _, _ = nouvelle_app("demo")
    _ouvrir(at, "👀 Watchlist")
    for uid, mdp in (("theo", "mot-de-passe-fictif-1"), ("alice", "mot-de-passe-fictif-2")):
        _bouton(at, "🔒").click().run()
        at.text_input(key="login_user").set_value(uid)
        at.text_input(key="login_password").set_value(mdp)
        _bouton(at, "Entrer").click().run()
        _ouvrir(at, "👀 Watchlist")
        texte = "\n".join(m.value for m in at.markdown)
        assert f"note de {uid}" in texte
        assert not [a for a in ("theo", "alice", "demo") if a != uid and f"note de {a}" in texte]
