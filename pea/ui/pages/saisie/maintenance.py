"""Saisie › Maintenance & sauvegarde : reconstitution de l'historique, tickers manquants, exports CSV."""
from __future__ import annotations

import streamlit as st

from pea.data import marche
from pea.data import repo
from pea.domain import calculs as C
from pea.services.portefeuille import Portefeuille
from pea.ui.composants.communs import creer_titre
from pea.ui.etat import flash, k

EXPORTS = ("transactions", "dividendes", "versements", "watchlist")


def _reconstituer(pf: Portefeuille) -> None:
    st.subheader("Historique")
    st.caption("Recalcule la valeur du PEA jour par jour depuis votre 1re opération "
               "(cours de clôture Yahoo) et remplace les points existants.")
    if not st.button("Reconstituer l'historique", disabled=pf.trans.empty, key=k("mt", "reconstituer")):
        return
    with st.spinner("Téléchargement des historiques de cours…"):
        debut = pf.trans["date"].min().strftime("%Y-%m-%d")
        isin_ticker = pf.tmap["ticker"].to_dict()
        prix_hist = marche.historiques_groupes(set(isin_ticker.values()), debut)  # un seul téléchargement
        rec = C.reconstituer_snapshots(pf.trans, pf.flux, prix_hist, isin_ticker)
        repo.upsert("snapshots", [{"date": r.date, "valeur": round(r.valeur, 2), "apports": round(r.apports, 2)}
                                  for r in rec.itertuples()], "date")
    flash(f"{len(rec)} points reconstitués ✅")
    st.rerun()


def _tickers_manquants(pf: Portefeuille) -> None:
    manquants = pf.manquants
    if not manquants:
        return
    st.subheader("Tickers manquants")
    st.warning(f"{len(manquants)} ISIN sans ticker : {', '.join(manquants)}")
    if st.button("Résoudre automatiquement", key=k("mt", "resoudre")):
        echecs = []
        for isin in manquants:
            t = marche.chercher_ticker(isin)
            if not t or creer_titre(pf, isin, t["ticker"], t["nom"], suggerer=False):
                echecs.append(isin)
        flash("Tickers résolus ✅" if not echecs else f"Échec pour : {', '.join(echecs)}")
        st.rerun()
    with st.form(k("f_tk")):
        isin = st.selectbox("ISIN", manquants)
        tk = st.text_input("Ticker Yahoo", placeholder="ex : MC.PA")
        ok = st.form_submit_button("Enregistrer le ticker")
    if ok:
        err = creer_titre(pf, isin, tk.strip().upper(), suggerer=False) if tk.strip() else "Ticker vide."
        if err:
            st.error(err)
        else:
            flash("Ticker enregistré ✅")
            st.rerun()


def afficher(pf: Portefeuille) -> None:
    _reconstituer(pf)
    _tickers_manquants(pf)
    st.subheader("Sauvegarde")
    for table in EXPORTS:  # servis par le cache mémoire de repo : aucune requête si frais
        st.download_button(f"⬇️ {table}.csv", repo.lire(table).to_csv(index=False),
                           file_name=f"{table}.csv", mime="text/csv", key=k("dl", table))
