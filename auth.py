"""Authentification simple pour 2–3 comptes, configurés dans les secrets Streamlit.

Exemple : [users.demo] password = "demo", demo = true ; [users.theo] password = "...".
Les mots de passe ne sont jamais stockés dans Supabase ni dans le dépôt Git.
"""
from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Mapping

import streamlit as st

CLE_SESSION = "user_id"
MAX_ECHECS = 8
FENETRE_S = 15 * 60


@st.cache_resource
def _tentatives_connexion() -> dict:
    """Compteur partagé entre sessions Streamlit, afin de freiner les essais de mots de passe."""
    return {"echecs": {}, "lock": threading.Lock()}


def _attente_restante(identifiant: str) -> int:
    now = time.time()
    registre = _tentatives_connexion()
    cle = identifiant.strip().casefold()
    with registre["lock"]:
        echecs = [t for t in registre["echecs"].get(cle, []) if now - t < FENETRE_S]
        registre["echecs"][cle] = echecs
        if len(echecs) >= MAX_ECHECS:
            return int(FENETRE_S - (now - echecs[0])) + 1
    return 0


def _noter_echec(identifiant: str) -> None:
    registre = _tentatives_connexion()
    cle = identifiant.strip().casefold()
    now = time.time()
    with registre["lock"]:
        echecs = [t for t in registre["echecs"].get(cle, []) if now - t < FENETRE_S]
        echecs.append(now)
        registre["echecs"][cle] = echecs


def _effacer_echecs(identifiant: str) -> None:
    registre = _tentatives_connexion()
    with registre["lock"]:
        registre["echecs"].pop(identifiant.strip().casefold(), None)


def _config_utilisateurs() -> dict[str, dict]:
    """Lit [users.*] depuis st.secrets. APP_PASSWORD est accepté en transition pour theo."""
    config: dict[str, dict] = {"demo": {"password": "demo", "demo": True}}
    try:
        brut = st.secrets.get("users", {})
        if isinstance(brut, Mapping):
            for identifiant, details in brut.items():
                if isinstance(details, Mapping) and details.get("password") is not None:
                    config[str(identifiant)] = {
                        "password": str(details.get("password", "")),
                        "demo": bool(details.get("demo", str(identifiant) == "demo")),
                    }
        ancien = st.secrets.get("APP_PASSWORD")
        if ancien and "theo" not in config:
            config["theo"] = {"password": str(ancien), "demo": False}
    except Exception:
        # L'absence de secrets ne doit pas empêcher d'afficher le formulaire de connexion.
        pass
    return config


def connecte() -> bool:
    """True si un identifiant de session correspond toujours à un compte configuré."""
    uid = st.session_state.get(CLE_SESSION)
    return isinstance(uid, str) and uid in _config_utilisateurs()


def utilisateur() -> str | None:
    return st.session_state.get(CLE_SESSION) if connecte() else None


def est_demo() -> bool:
    uid = utilisateur()
    return bool(uid is not None and _config_utilisateurs().get(uid, {}).get("demo", uid == "demo"))


def secret(nom: str):
    """Lit un secret global (par ex. GEMINI_API_KEY)."""
    try:
        return st.secrets.get(nom)
    except Exception:
        return None


# Préfixes des clés de session propres à un compte (relevé d'import, chat, sélections, brouillons…).
PREFIXES_ETAT_COMPTE = ("chat_", "wl_", "scenario_", "ed_", "imp", "vue_", "cmp_", "cedit_", "csug_",
                        "cisin_", "ctk_", "conc_", "flash")


def _vider_etat_compte(inclure_formulaire: bool = True) -> None:
    """Retire les données et sélections UI pouvant provenir du compte précédent."""
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
    utilisateurs = _config_utilisateurs()
    utilisateur_cfg = utilisateurs.get(identifiant)
    # Le compte démo a un mot de passe public par conception : ne pas bloquer tous les visiteurs
    # après quelques erreurs de frappe. Les tentatives des comptes privés, elles, sont limitées.
    compte_prive = utilisateur_cfg is not None and not utilisateur_cfg.get("demo", False)
    if compte_prive and (attente := _attente_restante(identifiant)):
        st.error(f"Trop de tentatives pour cet identifiant. Réessayez dans {attente // 60 + 1} min.")
        return

    attendu = str(utilisateur_cfg.get("password", "")) if utilisateur_cfg else "mot-de-passe-inconnu"
    valide = hmac.compare_digest(str(mot_de_passe).encode("utf-8"), attendu.encode("utf-8")) \
        and utilisateur_cfg is not None
    if not valide:
        if compte_prive:
            _noter_echec(identifiant)
        st.error("Identifiant ou mot de passe incorrect.")
        return
    if compte_prive:
        _effacer_echecs(identifiant)

    # Les clés de widgets d'un autre compte ne doivent pas survivre à un changement de session.
    # On conserve login_user/login_password pendant ce rerun (widgets de ce formulaire actifs).
    _vider_etat_compte(inclure_formulaire=False)
    st.session_state[CLE_SESSION] = identifiant
    st.rerun()


def deconnecter() -> None:
    """Efface l'identité de session et les éléments UI pouvant contenir une conversation."""
    st.session_state.pop(CLE_SESSION, None)
    _vider_etat_compte(inclure_formulaire=True)
