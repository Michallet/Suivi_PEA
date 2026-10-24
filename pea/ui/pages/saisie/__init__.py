"""Onglet Saisie : une sous-page par action (tous les comptes connectés ; la démo écrit dans sa session)."""
from __future__ import annotations

import streamlit as st

from pea.services.portefeuille import Portefeuille
from pea.ui.etat import k
from pea.ui.pages.saisie import (captures, correction, dividende, maintenance, secteurs, transaction,
                                 versement)

ACTIONS = {
    "Transaction": transaction.afficher,
    "Import par captures": captures.afficher,
    "Dividende": dividende.afficher,
    "Versement / retrait": versement.afficher,
    "Secteurs": secteurs.afficher,
    "Corriger / supprimer": correction.afficher,
    "Maintenance & sauvegarde": maintenance.afficher,
}


@st.fragment
def afficher(pf: Portefeuille) -> None:
    action = st.selectbox("Action", list(ACTIONS), key=k("saisie", "action"))
    ACTIONS[action](pf)
