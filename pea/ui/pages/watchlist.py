"""Onglet Watchlist : valeurs suivies (non détenues), ajout par ISIN ou ticker."""
from __future__ import annotations

import streamlit as st

from pea.data import repo
from pea.domain import calculs as C
from pea.services import titres
from pea.services.portefeuille import Portefeuille
from pea.ui.composants.cartes import carte_suivi
from pea.ui.composants.communs import calculer_techniques, creer_titre, selecteur_vue
from pea.ui.etat import flash, k

CLE_ISIN, CLE_TK, CLE_NOTE, CLE_RESET = k("wl", "isin"), k("wl", "tk"), k("wl", "note"), k("wl", "reset")


def _ajouter(pf: Portefeuille) -> None:
    with st.expander("➕ Ajouter une action / un ETF"):
        if st.session_state.pop(CLE_RESET, False):  # remise à zéro après un ajout, avant les widgets
            for cle in (CLE_ISIN, CLE_TK, CLE_NOTE):
                st.session_state[cle] = ""
        st.text_input("ISIN", placeholder="FR0000121014", key=CLE_ISIN)
        st.text_input("Ticker Yahoo (facultatif)", key=CLE_TK, placeholder="ex : MC.PA — si l'ISIN n'est pas reconnu")
        st.text_input("Note (facultatif)", key=CLE_NOTE)
        if st.button("Ajouter", key=k("wl", "add"), type="primary"):
            _enregistrer(pf)


def _enregistrer(pf: Portefeuille) -> None:
    isin = st.session_state.get(CLE_ISIN, "").strip().upper()
    tk = st.session_state.get(CLE_TK, "").strip().upper()
    note = st.session_state.get(CLE_NOTE, "").strip()
    if not C.isin_valide(isin):
        st.error("ISIN invalide (12 caractères, clé de contrôle incorrecte).")
        return
    if isin in pf.wl["isin"].tolist():
        st.info("Déjà dans la watchlist.")
        return
    if isin not in pf.tmap.index or tk:
        ticker, nom, err = titres.resoudre_ticker(isin, tk)
        err = err or creer_titre(pf, isin, ticker, nom)
        if err:
            st.error(err)
            return
    repo.upsert("watchlist", [{"isin": isin, "note": note or None}], "isin")
    flash("Ajouté à la watchlist ✅")
    st.session_state[CLE_RESET] = True
    st.rerun()


@st.fragment
def afficher(pf: Portefeuille) -> None:
    wl = pf.wl
    if wl.empty:
        st.info("Votre watchlist est vide. Ajoutez des valeurs : elles seront proposées dans les "
                "formulaires de saisie et dans les scénarios.")
    vue = selecteur_vue("wl") if not wl.empty else "Fondamentaux"
    techs = calculer_techniques([pf.ticker_de(i) for i in wl["isin"] if i in pf.tmap.index]) \
        if vue == "Techniques" else {}
    with st.container(key="grille_wl"):  # grille de cartes (CSS)
        for r in wl.itertuples():
            carte_suivi(pf, r, vue, techs)
    _ajouter(pf)
