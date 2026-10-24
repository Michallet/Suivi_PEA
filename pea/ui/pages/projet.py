"""Onglet Projet : scénarios fictifs comparés au PEA actuel (aucune modification du portefeuille réel)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import repo
from pea.domain import calculs as C
from pea.domain.formats import fmt
from pea.domain.textes import echapper_markdown as esc
from pea.services.portefeuille import Portefeuille
from pea.ui.composants import graphiques
from pea.ui.composants.cartes import carte_ligne
from pea.ui.composants.communs import calculer_techniques, selecteur_vue
from pea.ui.composants.ia import bloc_analyse, bloc_chat, cible_scenario
from pea.ui.etat import flash, k

CLE_ID, CLE_RESET, CLE_EN_ATTENTE = k("scenario", "id"), k("scenario", "reset"), k("scenario", "pending")


def _nouveau_scenario(pf: Portefeuille, noms: dict) -> None:
    with st.expander("➕ Nouveau scénario", expanded=pf.scen.empty):
        with st.form(k("f_scen"), clear_on_submit=True):
            nom = st.text_input("Nom", placeholder="ex : Renforcer la santé")
            ok = st.form_submit_button("Créer")
        if not ok:
            return
        nom = nom.strip()
        if not nom:
            st.error("Donnez un nom au scénario.")
        elif nom in noms.values():
            st.error("Ce nom existe déjà.")
        else:
            row = repo.inserer("scenarios", {"nom": nom, "versement": 0})
            st.session_state[CLE_EN_ATTENTE] = int(row["id"])
            flash("Scénario créé ✅")
            st.rerun()


def _operations(pf: Portefeuille, sid: int, sim: pd.DataFrame, versement: float) -> None:
    st.markdown("**Opérations fictives**")
    if sim.empty and versement == 0:
        st.caption("Aucune opération pour l'instant.")
    for r in sim.itertuples():
        st.markdown(f"- {r.type} {r.quantite:g} × {esc(pf.nom_de(r.isin))} @ {fmt(r.prix)} € "
                    f"(≈ {fmt(r.quantite * r.prix, 0)} €)")
    if versement:
        st.markdown(f"- Versement fictif : {fmt(versement, 0)} €")
    b1, b2, b3 = st.columns(3)
    if b1.button("↩️ Annuler", disabled=sim.empty, key=k("sc", "undo"), help="Annule la dernière opération"):
        repo.supprimer("scenario_trades", int(sim["id"].max()))
        st.rerun()
    if b2.button("🧹 Vider", disabled=sim.empty and versement == 0, key=k("sc", "clear"), help="Repart du PEA actuel"):
        repo.supprimer("scenario_trades", sid, cle="scenario_id")
        repo.modifier("scenarios", sid, {"versement": 0})
        st.rerun()
    if b3.button("🗑 Supprimer", key=k("sc", "del"), help="Supprime le scénario"):
        repo.supprimer("scenarios", sid)
        st.session_state[CLE_RESET] = True
        flash("Scénario supprimé")
        st.rerun()


def _quantite(mode: str, val, px_: float, brutes: pd.DataFrame, isin: str) -> float:
    if mode == "Tout":
        return float(brutes.loc[brutes["isin"] == isin, "quantite"].iloc[0])
    return float(int(val // px_)) if mode.startswith("Montant") else float(val)


def _ajouter_operation(pf: Portefeuille, sid: int, sim: pd.DataFrame, versement: float,
                       brutes: pd.DataFrame) -> None:
    with st.expander("➕ Ajouter une opération", expanded=sim.empty):
        typ = st.radio("Opération", ["ACHAT", "VENTE"], horizontal=True, key=k("sc", "typ"))
        options = brutes["isin"].tolist() if typ == "VENTE" else pf.ordre_isins()
        if not options:
            st.info("Aucune ligne à vendre." if typ == "VENTE" else "Ajoutez d'abord des valeurs en watchlist.")
        else:
            isin = st.selectbox("Ligne", options, key=k("sc", "isin"), format_func=lambda i: f"{pf.nom_de(i)} ({i})")
            px_ = pf.prix_courant(isin)
            modes = ["Montant (€)", "Quantité"] + (["Tout"] if typ == "VENTE" else [])
            mode = st.radio("Saisie", modes, horizontal=True, key=k("sc", "mode"))
            st.caption(f"Cours : {fmt(px_)} €" if px_ else "Cours indisponible pour cette ligne.")
            val = None
            if mode != "Tout":
                montant = mode.startswith("Montant")
                val = st.number_input(mode, min_value=0.0, value=500.0 if montant else 1.0,
                                      step=50.0 if montant else 1.0, key=k("sc", "val", mode))
            if st.button("Ajouter à ce scénario", key=k("sc", "add")):
                _enregistrer_operation(pf, sid, sim, versement, brutes, typ, isin, px_, mode, val)
        v = st.number_input("Versement fictif (€)", min_value=0.0, value=versement, step=100.0, key=k("sc", "vers", sid))
        if st.button("Appliquer le versement", key=k("sc", "vers_btn"), disabled=(v == versement)):
            repo.modifier("scenarios", sid, {"versement": float(v)})
            st.rerun()


def _enregistrer_operation(pf, sid, sim, versement, brutes, typ, isin, px_, mode, val) -> None:
    if not px_:
        st.error("Cours indisponible : opération impossible.")
        return
    qte = _quantite(mode, val, px_, brutes, isin)
    if qte <= 0:
        st.error(f"Montant inférieur au prix d'une part ({fmt(px_)} €).")
        return
    cand = pd.concat([sim[["isin", "type", "quantite", "prix"]],
                      pd.DataFrame([{"isin": isin, "type": typ, "quantite": qte, "prix": px_}])], ignore_index=True)
    try:
        C.appliquer_scenario(pf.trans, cand, pf.div, pf.vers, versement, config.maintenant().date())
    except ValueError as e:
        st.error(str(e))
        return
    repo.inserer("scenario_trades", {"scenario_id": sid, "isin": isin, "type": typ, "quantite": qte, "prix": px_})
    st.rerun()


def _comparaison(pf: Portefeuille, pos_p: pd.DataFrame, cash_p: float) -> None:
    st.subheader("Actuel vs projeté")
    if cash_p < -0.01:
        st.warning(f"Cash insuffisant : il manquerait {fmt(-cash_p)} € (ajoutez un versement fictif).")
    for r in pos_p.itertuples():
        if r.poids_pct > config.SEUIL_CONCENTRATION:
            st.warning(f"⚠️ {r.nom} pèserait {fmt(r.poids_pct, 0)} % des titres.")
    k1, k2 = st.columns(2)
    k1.metric("Cash", f"{fmt(cash_p)} €", f"{fmt(cash_p - pf.cash, 0, True)} €")
    k2.metric("Lignes", len(pos_p), len(pos_p) - len(pf.pos))
    rep_r, rep_p = C.repartition(pf.pos, pf.cash), C.repartition(pos_p, cash_p)
    par_ligne = C.comparer_repartitions(rep_r, rep_p, "label")
    par_secteur = C.comparer_repartitions(rep_r, rep_p, "secteur")
    g_ligne, g_secteur = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
    with g_ligne:
        st.markdown("**Par ligne**")
        graphiques.compare(par_ligne, "label")
    with g_secteur:
        st.markdown("**Par secteur**")
        graphiques.compare(par_secteur, "secteur")
    with st.expander("Détail des écarts (points de %)"):
        tableau = par_ligne.rename(columns={"label": "Ligne", "reel": "Actuel %", "projete": "Projeté %",
                                            "ecart": "Écart"}).round(1)
        st.dataframe(tableau, hide_index=True)


@st.fragment
def afficher(pf: Portefeuille) -> None:
    st.caption("Simulez une répartition future à partir de votre PEA actuel, **sans le modifier**. "
               "Les opérations sont fictives, au dernier cours connu.")
    if st.session_state.pop(CLE_RESET, False):
        st.session_state.pop(CLE_ID, None)
    if CLE_EN_ATTENTE in st.session_state:
        st.session_state[CLE_ID] = st.session_state.pop(CLE_EN_ATTENTE)

    noms = dict(zip(pf.scen["id"].astype(int), pf.scen["nom"]))
    _nouveau_scenario(pf, noms)
    if pf.scen.empty:
        return
    sid = st.selectbox("Scénario", list(noms), format_func=noms.get, key=CLE_ID)
    try:
        sim, versement, brutes, cash_p = pf.scenario(sid)
    except ValueError as e:
        st.error(f"Scénario incohérent : {e}")
        return
    pos_p = pf.enrichir(brutes)

    _operations(pf, sid, sim, versement)
    _ajouter_operation(pf, sid, sim, versement, brutes)
    _comparaison(pf, pos_p, cash_p)

    st.subheader("Lignes du scénario")
    vue = selecteur_vue("pj")
    techs = calculer_techniques(pos_p["ticker"]) if vue == "Techniques" and not pos_p.empty else {}
    with st.container(key="grille_pj"):
        for r in pos_p.sort_values("valeur", ascending=False).itertuples():
            carte_ligne(pf, r, "pj", vue, techs)
    ops = "; ".join(f"{r.type} {r.quantite:g} × {pf.nom_de(r.isin)}" for r in sim.itertuples())
    scenario = {"sid": sid, "pos_p": pos_p, "cash_p": cash_p, "operations": ops, "versement": versement}
    with st.expander("✨ Assistant IA du scénario · Analyse & Chat"):
        col_analyse, col_chat = st.columns(2)
        with col_analyse:
            bloc_analyse(pf, cible_scenario(pf, sid, pos_p, cash_p, ops, versement), cadre=False)
        with col_chat:
            bloc_chat(pf, scenario=scenario, cadre=False)
    st.caption("Simulation de répartition uniquement : aucune prévision de rendement.")
