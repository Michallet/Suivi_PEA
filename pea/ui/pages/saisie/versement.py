"""Saisie › Versement / retrait."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import repo
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash, k

LIBELLES_VERS = {"VERSEMENT": "Versement", "RETRAIT": "Retrait",
                 "PV_ANTERIEURE": "Plus-value antérieure réinvestie (hors apports)"}


def afficher(pf: Portefeuille) -> None:
    st.caption("Les versements alimentent le cash du PEA et comptent dans le plafond de "
               "150 000 €. Une « plus-value antérieure » alimente le cash sans compter comme apport.")
    with st.form(k("f_vers"), clear_on_submit=True):
        d = st.date_input("Date", config.maintenant().date(), format="DD/MM/YYYY")
        typ = st.selectbox("Type", list(LIBELLES_VERS), format_func=LIBELLES_VERS.get)
        m = st.number_input("Montant (€)", min_value=0.01, value=100.0, step=10.0)
        lib = st.text_input("Libellé (facultatif)")
        ok = st.form_submit_button("Enregistrer")
    if ok:
        repo.inserer("versements", {"date": pd.Timestamp(d), "type": typ, "montant": m,
                                    "libelle": lib.strip() or None})
        flash("Opération enregistrée ✅")
        st.rerun()
