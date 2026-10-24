"""Authentification par mots de passe déclarés dans les secrets Streamlit ([users.*]).

Choix du propriétaire : pas d'OIDC Google (AUTH_MODE = "password", seul adaptateur). Conséquence connue :
la session vit dans st.session_state, un rechargement de la page oblige à se reconnecter.

Durcissement :
* mots de passe en clair dans les secrets Streamlit (`password`), choix du propriétaire : les secrets ne sont
  jamais dans le dépôt ;
* blocage par couple (identifiant, session) : un tiers ne peut plus verrouiller le compte d'un autre ;
* ralentissement progressif par identifiant (au plus 5 s) contre les essais en rafale depuis plusieurs sessions ;
* comparaison en temps constant, même pour un identifiant inconnu.
"""
from __future__ import annotations

import hmac
import secrets as _alea
import threading
import time

import streamlit as st

from pea import config
from pea.data import repo

AUTH_MODE = "password"
CLE_SESSION = "user_id"
CLE_CONNEXION_DEMANDEE = "connexion_demandee"
CLE_ECHECS = "_auth_echecs"
RALENTISSEMENT_MAX_S = 5.0

# Clés de session propres à un compte : tout l'espace de noms `c.` (widgets, brouillons, chat, contexte)
# et les tables de la démo. Une seule purge, à la connexion comme à la déconnexion.
PREFIXES_ETAT_COMPTE = (config.PREFIXE_COMPTE, repo.CLE_DEMO)
CLES_FORMULAIRE = ("login_user", "login_password")

_echecs_identifiant: dict = {}   # identifiant -> [horodatages] (ralentissement, jamais blocage)
_verrou = threading.Lock()


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _echecs_identifiant.clear()


def verifier_identifiants(identifiant: str, mot_de_passe: str) -> bool:
    """Vrai si le couple est valide. Comparaison en temps constant, même pour un identifiant inconnu."""
    cfg = config.comptes().get(identifiant)
    attendu = (cfg or {}).get("password")
    reference = attendu if attendu is not None else _alea.token_urlsafe(16)
    egal = hmac.compare_digest(str(mot_de_passe).encode("utf-8"), str(reference).encode("utf-8"))
    return attendu is not None and egal


# --------------------------------------------------------------------------------------------------
# Limitation des essais
# --------------------------------------------------------------------------------------------------
def _recents(liste: list) -> list:
    return [t for t in liste if time.time() - t < config.FENETRE_ECHECS_S]


def attente_session(identifiant: str, session) -> int:
    """Secondes avant un nouvel essai pour ce couple (identifiant, session) ; 0 si permis."""
    echecs = _recents(session.get(CLE_ECHECS, {}).get(identifiant, []))
    if len(echecs) >= config.MAX_ECHECS_SESSION:
        return int(config.FENETRE_ECHECS_S - (time.time() - echecs[0])) + 1
    return 0


def ralentissement(identifiant: str) -> float:
    with _verrou:
        n = len(_recents(_echecs_identifiant.get(identifiant, [])))
    return min(RALENTISSEMENT_MAX_S, 0.5 * max(0, n - 2))


def noter_echec(identifiant: str, session) -> None:
    par_id = dict(session.get(CLE_ECHECS, {}))
    par_id[identifiant] = _recents(par_id.get(identifiant, [])) + [time.time()]
    session[CLE_ECHECS] = par_id
    with _verrou:
        _echecs_identifiant[identifiant] = _recents(_echecs_identifiant.get(identifiant, [])) + [time.time()]


def effacer_echecs(identifiant: str, session) -> None:
    par_id = dict(session.get(CLE_ECHECS, {}))
    par_id.pop(identifiant, None)
    session[CLE_ECHECS] = par_id


# --------------------------------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------------------------------
def connecte() -> bool:
    uid = st.session_state.get(CLE_SESSION)
    return isinstance(uid, str) and uid in config.comptes()


def utilisateur() -> str | None:
    return st.session_state.get(CLE_SESSION) if connecte() else None


def est_demo() -> bool:
    return config.est_demo(utilisateur())


def secret(nom: str):
    """Compatibilité : lit un secret global (voir pea.config)."""
    return config.secret(nom)


def connexion_demo_auto_active() -> bool:
    return config.secret_bool("AUTO_CONNEXION_DEMO", config.CONNEXION_DEMO_AUTO)


def connecter_demo_par_defaut() -> None:
    """À l'ouverture de la session, connecte la démo (lecture seule en base) si l'interrupteur est actif."""
    if connecte() or st.session_state.get(CLE_CONNEXION_DEMANDEE) or not connexion_demo_auto_active():
        return
    if config.comptes().get("demo", {}).get("demo", False):
        vider_etat_compte(inclure_formulaire=False)
        st.session_state[CLE_SESSION] = "demo"


def vider_etat_compte(inclure_formulaire: bool = True) -> None:
    """Purge unique : retire les données et sélections UI pouvant provenir du compte précédent."""
    for cle in list(st.session_state.keys()):
        if str(cle).startswith(PREFIXES_ETAT_COMPTE) or (inclure_formulaire and cle in CLES_FORMULAIRE):
            st.session_state.pop(cle, None)


def tenter_connexion(identifiant: str, mot_de_passe: str) -> str | None:
    """Ouvre la session si le couple est valide. Retourne le message d'erreur à afficher, sinon None."""
    identifiant = identifiant.strip()
    cfg = config.comptes().get(identifiant)
    compte_prive = cfg is not None and not cfg.get("demo", False)
    if compte_prive and (attente := attente_session(identifiant, st.session_state)):
        return f"Trop de tentatives pour cet identifiant. Réessayez dans {attente // 60 + 1} min."
    if compte_prive:
        time.sleep(ralentissement(identifiant))
    if not (cfg is not None and verifier_identifiants(identifiant, mot_de_passe)):
        if compte_prive:
            noter_echec(identifiant, st.session_state)
        return "Identifiant ou mot de passe incorrect."
    if compte_prive:
        effacer_echecs(identifiant, st.session_state)
    vider_etat_compte(inclure_formulaire=False)
    st.session_state[CLE_SESSION] = identifiant
    st.session_state.pop(CLE_CONNEXION_DEMANDEE, None)
    return None


def deconnecter() -> None:
    """Efface l'identité de session et les éléments UI d'un compte ; affiche ensuite le formulaire."""
    st.session_state.pop(CLE_SESSION, None)
    vider_etat_compte(inclure_formulaire=True)
    st.session_state[CLE_CONNEXION_DEMANDEE] = True
