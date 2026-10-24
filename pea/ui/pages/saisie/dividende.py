"""Saisie › Dividende."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import repo
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash, k


def afficher(pf: Portefeuille) -> None:
    if pf.tmap.empty:
        st.info("Enregistrez d'abord une transaction.")
        return
    with st.form(k("f_div"), clear_on_submit=True):
        d = st.date_input("Date", config.maintenant().date(), format="DD/MM/YYYY")
        isin = st.selectbox("Ligne", pf.ordre_isins(), format_func=lambda i: f"{pf.nom_de(i)} ({i})")
        m = st.number_input("Montant net perçu (€)", min_value=0.01, value=10.0, step=0.5)
        ok = st.form_submit_button("Enregistrer")
    if ok:
        repo.inserer("dividendes", {"date": pd.Timestamp(d), "isin": isin, "montant": m})
        flash("Dividende enregistré ✅")
        st.rerun()
