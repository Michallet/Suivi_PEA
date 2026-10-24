"""Saisie › Transaction (achat ou vente, création du titre si l'ISIN est nouveau)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import repo
from pea.domain import calculs as C
from pea.domain.formats import fmt
from pea.services import titres
from pea.services.portefeuille import Portefeuille
from pea.ui.composants.communs import choisir_isin, creer_titre
from pea.ui.etat import flash, k


def _formulaire(pf: Portefeuille, typ: str, isin: str):
    px_ = pf.prix_courant(isin) if isin in pf.tmap.index else None
    with st.form(k("f_trans"), clear_on_submit=True):
        d = st.date_input("Date", config.maintenant().date(), format="DD/MM/YYYY")
        q = st.number_input("Quantité", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
        p = st.number_input("Prix unitaire (€)", min_value=0.0, value=float(px_ or 100.0), step=0.1, format="%.4f")
        fr = st.number_input("Frais (€)", min_value=0.0, value=0.0, step=0.1, format="%.2f")
        tk = st.text_input("Ticker Yahoo (facultatif)",
                           placeholder="ex : MC.PA — seulement si l'ISIN n'est pas reconnu")
        ok = st.form_submit_button("Enregistrer")
    return ok, d, q, p, fr, tk.strip().upper()


def afficher(pf: Portefeuille) -> None:
    typ = st.radio("Type", ["ACHAT", "VENTE"], horizontal=True, key=k("tx", "typ"))
    options = pf.positions["isin"].tolist() if typ == "VENTE" else pf.ordre_isins()
    isin = choisir_isin(pf, "Ligne (détenue, watchlist ou autre)" if typ == "ACHAT" else "Ligne à vendre",
                        options, "tx", nouveau=(typ == "ACHAT"))
    ok, d, q, p, fr, tk = _formulaire(pf, typ, isin)
    if not ok:
        return
    if not C.isin_valide(isin):
        st.error("ISIN invalide (12 caractères, clé de contrôle incorrecte).")
        return
    nouvelle = pd.DataFrame([{"date": pd.Timestamp(d), "isin": isin, "type": typ, "quantite": q, "prix": p,
                              "frais": fr}])
    try:
        _, v_apres = C.calcul_positions(pd.concat([pf.trans, nouvelle], ignore_index=True))
    except ValueError as e:
        st.error(str(e))
        return
    if isin not in pf.tmap.index or tk:
        ticker, nom, err = titres.resoudre_ticker(isin, tk)
        if err:
            st.error("Ticker introuvable pour cet ISIN : renseignez-le dans le champ dédié.")
            return
        err = creer_titre(pf, isin, ticker, nom)
        if err:
            st.error(err)
            return
    repo.inserer("transactions", nouvelle.iloc[0].to_dict())
    msg = "Transaction enregistrée ✅"
    if typ == "VENTE":
        msg += f" — plus-value réalisée : {fmt(v_apres['pv'].sum() - pf.ventes['pv'].sum(), 2, True)} €"
    flash(msg)
    st.rerun()
