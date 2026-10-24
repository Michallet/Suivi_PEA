"""Authentification par mots de passe déclarés dans les secrets Streamlit ([users.*]).

Choix du propriétaire : pas d'OIDC Google (AUTH_MODE = "password", seul adaptateur). Conséquence connue :
la session vit dans st.session_state, un rechargement de la page oblige à se reconnecter.

Durcissement :
* mots de passe HACHÉS (`password_hash`, scrypt de la bibliothèque standard) ; `password` en clair reste lu
  pour la transition ;
* blocage par couple (identifiant, session) : un tiers ne peut plus verrouiller le compte d'un autre ;
* ralentissement progressif par identifiant (au plus 5 s) contre les essais en rafale depuis plusieurs sessions ;
* comparaison en temps constant, même pour un identifiant inconnu.
"""
from __future__ import annotations

import base64
import hashlib
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

# Préfixes des clés de session propres à un compte (relevé d'import, chat, sélections, brouillons…).
PREFIXES_ETAT_COMPTE = ("chat_", "wl_", "scenario_", "ed_", "imp", "vue_", "cmp_", "cedit_", "csug_",
                        "cisin_", "ctk_", "conc_", "part_", "qd_", "flash", repo.CLE_DEMO)

_echecs_identifiant: dict = {}   # identifiant -> [horodatages] (ralentissement, jamais blocage)
_verrou = threading.Lock()


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _echecs_identifiant.clear()


# --------------------------------------------------------------------------------------------------
# Hachage
# --------------------------------------------------------------------------------------------------
def hacher(mot_de_passe: str) -> str:
    sel = _alea.token_bytes(16)
    h = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel, n=config.SCRYPT_N, r=config.SCRYPT_R,
                       p=config.SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${config.SCRYPT_N}${config.SCRYPT_R}${config.SCRYPT_P}${b64(sel)}${b64(h)}"


def _verifier_hache(mot_de_passe: str, empreinte: str) -> bool:
    try:
        algo, n, r, p, sel, attendu = empreinte.split("$")
        if algo != "scrypt":
            return False
        attendu_b = base64.b64decode(attendu)
        h = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=base64.b64decode(sel), n=int(n), r=int(r),
                           p=int(p), dklen=len(attendu_b), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(h, attendu_b)
    except Exception:
        return False


_FACTICE = None


def verifier_identifiants(identifiant: str, mot_de_passe: str) -> bool:
    """Vrai si le couple est valide. Même coût pour un identifiant inconnu (empreinte factice)."""
    global _FACTICE
    cfg = config.comptes().get(identifiant)
    if cfg and cfg.get("password_hash"):
        return _verifier_hache(mot_de_passe, cfg["password_hash"])
    if cfg and cfg.get("password") is not None:
        return hmac.compare_digest(str(mot_de_passe).encode("utf-8"), cfg["password"].encode("utf-8"))
    if _FACTICE is None:
        _FACTICE = hacher(_alea.token_urlsafe(16))
    _verifier_hache(mot_de_passe, _FACTICE)
    return False


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
        if str(cle).startswith(PREFIXES_ETAT_COMPTE):
            st.session_state.pop(cle, None)
        elif inclure_formulaire and cle in {"login_user", "login_password"}:
            st.session_state.pop(cle, None)


def formulaire_connexion() -> None:
    """Formulaire dont les champs sont préremplis avec les identifiants de démonstration."""
    with st.form("form_connexion"):
        identifiant = st.text_input("Identifiant", value="demo", key="login_user")
        mot_de_passe = st.text_input("Mot de passe", value="demo", type="password", key="login_password")
        soumis = st.form_submit_button("Entrer", type="primary", use_container_width=True)
    if not soumis:
        return
    identifiant = identifiant.strip()
    cfg = config.comptes().get(identifiant)
    compte_prive = cfg is not None and not cfg.get("demo", False)
    if compte_prive and (attente := attente_session(identifiant, st.session_state)):
        st.error(f"Trop de tentatives pour cet identifiant. Réessayez dans {attente // 60 + 1} min.")
        return
    if compte_prive:
        time.sleep(ralentissement(identifiant))
    if not (cfg is not None and verifier_identifiants(identifiant, mot_de_passe)):
        if compte_prive:
            noter_echec(identifiant, st.session_state)
        st.error("Identifiant ou mot de passe incorrect.")
        return
    if compte_prive:
        effacer_echecs(identifiant, st.session_state)
    vider_etat_compte(inclure_formulaire=False)
    st.session_state[CLE_SESSION] = identifiant
    st.session_state.pop(CLE_CONNEXION_DEMANDEE, None)
    st.rerun()


def deconnecter() -> None:
    """Efface l'identité de session et les éléments UI d'un compte ; affiche ensuite le formulaire."""
    st.session_state.pop(CLE_SESSION, None)
    vider_etat_compte(inclure_formulaire=True)
    st.session_state[CLE_CONNEXION_DEMANDEE] = True
