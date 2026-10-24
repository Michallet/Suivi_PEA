"""Clés de session de l'interface, par espace de noms, et messages différés.

Toute clé propre à un compte s'écrit `k("wl", "isin")` -> "c.wl.isin" : la déconnexion purge l'espace
`c.` en une fois (pea.services.auth.vider_etat_compte), sans liste de préfixes à tenir à jour.
"""
from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitAPIException

from pea import config

FLASH = config.PREFIXE_COMPTE + "flash"
FLASH_CONC = config.PREFIXE_COMPTE + "flash_conc"


def k(*morceaux) -> str:
    """Clé de session d'un compte : k("sc", "typ") -> "c.sc.typ"."""
    return config.PREFIXE_COMPTE + ".".join(str(m) for m in morceaux)


def flash(msg: str) -> None:
    """Message affiché (toast) après le prochain rechargement."""
    st.session_state[FLASH] = msg


def flash_concurrent(msg: str) -> None:
    st.session_state[FLASH_CONC] = msg


def afficher_flash() -> None:
    if FLASH in st.session_state:
        st.toast(st.session_state.pop(FLASH))
    if FLASH_CONC in st.session_state:
        st.toast(st.session_state.pop(FLASH_CONC), icon="⚖️")


def relancer_zone() -> None:
    """Relance seulement le fragment courant (rien n'a changé en base) ; tout le script sinon."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()
