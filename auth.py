"""Authentification mono-utilisateur : un mot de passe (secret Streamlit) débloque les données réelles.

* Sans connexion : mode démo uniquement (aucun accès à la base).
* Si aucun mot de passe n'est configuré : démo uniquement (échec fermé).
* Verrou GLOBAL en mémoire : trop d'échecs récents (toutes sessions confondues) => tentatives bloquées
  quelques minutes. Le verrou se réinitialise au redémarrage de l'app.
"""
from __future__ import annotations

import hmac
import threading
import time

import streamlit as st

MAX_ECHECS = 8
FENETRE_S = 15 * 60


def secret(nom: str):
    try:
        return st.secrets[nom]
    except Exception:
        return None


def mot_de_passe_configure() -> str | None:
    """APP_PASSWORD, ou ADMIN_PASSWORD (ancien nom) pour rester compatible."""
    return secret("APP_PASSWORD") or secret("ADMIN_PASSWORD")


@st.cache_resource
def _verrou() -> dict:
    return {"echecs": [], "lock": threading.Lock()}


def _attente_restante(v: dict) -> int:
    """Secondes avant la prochaine tentative autorisée (0 = autorisé)."""
    now = time.time()
    with v["lock"]:
        v["echecs"] = [t for t in v["echecs"] if now - t < FENETRE_S]
        if len(v["echecs"]) >= MAX_ECHECS:
            return int(FENETRE_S - (now - v["echecs"][0])) + 1
    return 0


def connecte() -> bool:
    return bool(st.session_state.get("auth_ok"))


def deconnecter() -> None:
    st.session_state["auth_ok"] = False


def formulaire_connexion() -> None:
    """Affiche le formulaire ; en cas de succès, ouvre la session et relance l'app."""
    attendu = mot_de_passe_configure()
    if attendu is None:
        st.warning("Aucun mot de passe configuré (secret `APP_PASSWORD`) : mode démo uniquement.")
        return
    v = _verrou()
    attente = _attente_restante(v)
    if attente:
        st.error(f"Trop de tentatives échouées. Réessayez dans {attente // 60 + 1} min.")
        return
    with st.form("form_connexion"):
        saisi = st.text_input("Mot de passe", type="password")
        valide = st.form_submit_button("Déverrouiller")
    if not valide:
        return
    if hmac.compare_digest(saisi.encode(), str(attendu).encode()):
        st.session_state["auth_ok"] = True
        st.rerun()
    with v["lock"]:
        v["echecs"].append(time.time())
    time.sleep(1)  # freine les essais enchaînés
    st.error("Mot de passe incorrect.")
