"""Saisie › Secteurs (surcharge du secteur Yahoo)."""
from __future__ import annotations

import streamlit as st

from pea.data import repo
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash, k


def afficher(pf: Portefeuille) -> None:
    if pf.tmap.empty:
        st.info("Enregistrez d'abord une transaction.")
        return
    st.caption("Laissez vide pour utiliser le secteur fourni par Yahoo (en anglais).")
    with st.form(k("f_sect")):
        saisies = {i: st.text_input(f"{pf.nom_de(i)} ({i})", value=pf.sect_dict.get(i, ""))
                   for i in pf.ordre_isins()}
        ok = st.form_submit_button("Enregistrer")
    if not ok:
        return
    a_ecrire = [{"isin": i, "secteur": v.strip()} for i, v in saisies.items() if v.strip()]
    a_effacer = [i for i, v in saisies.items() if not v.strip() and i in pf.sect_dict]
    repo.upsert("secteurs", a_ecrire, "isin")           # une requête
    repo.supprimer_plusieurs("secteurs", a_effacer, cle="isin")  # une requête
    flash("Secteurs enregistrés ✅")
    st.rerun()
