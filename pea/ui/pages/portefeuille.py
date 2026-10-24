"""Onglet Portefeuille : synthèse, cartes des lignes, graphiques et matrice de notes.

Trois fragments frères : basculer « Fondamentaux / Indicateurs techniques » ne relance que les cartes
(ni synthèse, ni IA, ni chat, ni graphiques).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.domain import calculs as C
from pea.domain.fondamentaux import GRANDEURS, est_etf, valeur_grandeur
from pea.domain.formats import cellule, fmt, sans_parentheses
from pea.services.portefeuille import Portefeuille
from pea.ui.composants import graphiques
from pea.ui.composants.cartes import carte_ligne
from pea.ui.composants.communs import calculer_techniques, selecteur_vue
from pea.ui.composants.ia import bloc_analyse, bloc_chat, cible_portefeuille
from pea.ui.etat import k

SEUIL = config.SEUIL_CONCENTRATION


def afficher(pf: Portefeuille) -> None:
    synthese(pf)
    lignes(pf)
    analyses(pf)


@st.fragment
def synthese(pf: Portefeuille) -> None:
    s = pf.synthese
    if pf.erreur_journal:
        st.error(f"Journal incohérent : {pf.erreur_journal} Corrigez-le dans Saisie › Corriger / supprimer.")
    if pf.manquants:
        st.warning("Ticker manquant pour : " + ", ".join(pf.manquants)
                   + " (Saisie › Maintenance). Ces lignes sont valorisées à leur prix de revient.")
    if pf.trans.empty:
        st.info("Aucune transaction pour l'instant. Rendez-vous dans l'onglet « Saisie ».")
        return

    c1, c2, c3, c4 = st.columns(4)  # 4 en ligne sur PC, 2 × 2 sur mobile
    c1.metric("Valeur du PEA", f"{fmt(s['valeur_totale'])} €",
              f"{fmt(s['var_jour_eur'], 2, True)} € ({fmt(s['var_jour_pct'], 2, True)} %) auj.")
    c2.metric("Plus-value globale", f"{fmt(s['pv_globale'])} €", f"{fmt(s['perf_pct'], 2, True)} %")
    c3.metric("Apports nets", f"{fmt(s['apports'])} €")
    c4.metric("Cash disponible", f"{fmt(s['cash'])} €")
    st.progress(min(s["plafond_pct"] / 100, 1.0),
                text=f"Plafond de versements : {fmt(s['versements_cumules'], 0)} / 150 000 € "
                     f"({fmt(s['plafond_pct'], 1)} %)")

    # Bandeau IA replié par défaut : un clic le déplie ; sur PC / tablette, analyse et chat côte à côte.
    with st.expander("✨ Assistant IA · Analyse & Chat"):
        col_analyse, col_chat = st.columns(2)
        with col_analyse:
            bloc_analyse(pf, cible_portefeuille(pf), cadre=False)
        with col_chat:
            bloc_chat(pf, cadre=False)

    if s["cash"] < -0.01:
        st.warning("Cash négatif : il manque des versements dans le journal (Saisie › Versement / retrait).")
    pos = pf.pos
    if pos.empty:
        return
    for r in pos.itertuples():
        if r.poids_pct > SEUIL:
            st.warning(f"⚠️ Concentration : {r.nom} pèse {fmt(r.poids_pct, 0)} % des titres (seuil {SEUIL:.0f} %).")
    hors_ligne = pos[pos["statut"] != "live"]
    if not hors_ligne.empty:
        st.warning("Cours indisponibles pour " + ", ".join(hors_ligne["nom"])
                   + " : dernier cours connu ou prix de revient utilisé.")
    st.caption(f"Cours Yahoo différés · actualisés à {pf.horodatage:%H:%M} (cache 5 min)")


@st.fragment
def lignes(pf: Portefeuille) -> None:
    """Une carte par ligne (lisible sur téléphone)."""
    if pf.pos.empty:
        return
    vue = selecteur_vue("pf")
    techs = calculer_techniques(pf.pos["ticker"]) if vue == "Techniques" else {}
    with st.container(key="grille_pf"):  # grille de cartes (CSS) : 1 colonne sur mobile, 2-3 sur PC
        for r in pf.pos.sort_values("valeur", ascending=False).itertuples():
            carte_ligne(pf, r, "pf", vue, techs)


def _lignes_matrice(pf: Portefeuille, avec_wl: bool) -> list[dict]:
    lignes_ = [{"isin": r.isin, "nom": r.nom, "ticker": r.ticker, "poids": r.poids_pct,
                "perf": r.perf_pct, "wl": False} for r in pf.pos.itertuples()]
    if avec_wl:
        detenus = set(pf.pos["isin"])
        lignes_ += [{"isin": i, "nom": pf.nom_de(i), "ticker": pf.ticker_de(i), "poids": None, "perf": None,
                     "wl": True} for i in pf.wl["isin"] if i not in detenus]
    # les ETF n'ont pas de fondamentaux : écartés de la matrice
    return [l for l in lignes_ if not est_etf(l["nom"], pf.fondamentaux(l["ticker"]))]


def matrice_notes(pf: Portefeuille) -> None:
    """Nuage de points : deux grandeurs au choix, chacune notée de 1 à 10 par rang dans le portefeuille
    (10 = le meilleur, 1 = sans valeur, ex. PER d'une société déficitaire). Jamais de ligne écartée."""
    st.subheader("Matrice de notes")
    cles = list(GRANDEURS)
    c_x, c_y, c_wl = st.columns(3, vertical_alignment="bottom")
    cx = c_x.selectbox("Axe horizontal", cles, index=cles.index("net_income"), key=k("qd", "x"),
                       format_func=lambda c: GRANDEURS[c][0])
    cy = c_y.selectbox("Axe vertical", cles, index=cles.index("per"), key=k("qd", "y"),
                       format_func=lambda c: GRANDEURS[c][0])
    avec_wl = c_wl.checkbox("Inclure la watchlist", key=k("qd", "wl"))
    lignes_ = _lignes_matrice(pf, avec_wl)
    if len(lignes_) < 3:
        st.info("Au moins 3 actions (hors ETF) sont nécessaires pour comparer des notes.")
        return

    df = pd.DataFrame(lignes_)
    df["vx"] = [valeur_grandeur(pf.fondamentaux(tk), cx) for tk in df["ticker"]]
    df["vy"] = [valeur_grandeur(pf.fondamentaux(tk), cy) for tk in df["ticker"]]
    df["nx"] = C.note_relative(df["vx"], GRANDEURS[cx][1])
    df["ny"] = C.note_relative(df["vy"], GRANDEURS[cy][1])
    df["px"], df["py"] = df["nx"], df["ny"]
    for _, g in df.groupby([df["nx"].round(2), df["ny"].round(2)]):  # points identiques : léger décalage
        if len(g) > 1:
            df.loc[g.index, "px"] = [df.at[i, "nx"] + (j - (len(g) - 1) / 2) * 0.28 for j, i in enumerate(g.index)]

    def info(_l, cle, v, n):
        v = None if v is None or pd.isna(v) else v
        return f"{GRANDEURS[cle][0]} : {cellule(v, GRANDEURS[cle][2])} → note {n:.1f}/10"

    graphiques.matrice(df, GRANDEURS, cx, cy, info)
    st.caption("Chaque ligne reçoit, sur chaque axe, une **note de 1 à 10 relative à ce portefeuille** : 10 = le "
               "meilleur du lot, 1 = pas de valeur (ex. société déficitaire, sans PER). Les écarts entre notes "
               "sont des écarts de classement, pas de valeur. Taille = poids, couleur = performance"
               + (", ◆ = watchlist" if df["wl"].any() else "") + ".")


@st.fragment
def analyses(pf: Portefeuille) -> None:
    if pf.trans.empty:
        return
    pos, s = pf.pos, pf.synthese
    if not pos.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Concentration max", f"{fmt(pos['poids_pct'].max(), 0)} %")
        col2.metric("Lignes actives", len(pos))
        total_dividendes = pos["dividendes"].sum()
        rendement_div = total_dividendes / s["valeur_totale"] * 100 if s["valeur_totale"] > 0 else 0.0
        col3.metric("Rendement dividendes", f"{fmt(rendement_div, 1)} %", f"{fmt(total_dividendes)} €")

        pos_fig = pos.assign(nom=sans_parentheses(pos["nom"]))
        st.subheader("Répartition")
        g_secteurs, g_treemap = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
        with g_secteurs:
            st.markdown("**Par secteur**")
            graphiques.secteurs(pos.groupby("secteur")["valeur"].sum().reset_index())
        with g_treemap:
            st.markdown("**Par ligne** · couleur = performance")
            graphiques.treemap(pos_fig)

        g_perf, g_contrib = st.columns(2)
        with g_perf:
            st.subheader("Performance latente par ligne")
            graphiques.barres(pos_fig.sort_values("perf_pct", ascending=False), "perf_pct",
                              {"perf_pct": "Performance %", "nom": ""}, "Performance latente (vs PRM)")
        with g_contrib:
            st.subheader("Contribution à la performance (€)")
            contrib = pos_fig.assign(contrib=pos["pv_latente"] + pos["dividendes"]).sort_values("contrib")
            graphiques.barres(contrib, "contrib", {"contrib": "PV latente + dividendes (€)", "nom": ""},
                              valeur_infobulle="%{x:+,.0f} €")
        matrice_notes(pf)

    if not pf.ventes.empty or not pf.div.empty:
        with st.expander("Plus-values réalisées & dividendes"):
            st.markdown(f"- Plus-values réalisées : **{fmt(pf.ventes['pv'].sum(), 2, True)} €**\n"
                        f"- Dividendes nets perçus : **{fmt(pf.div['montant'].sum())} €**")
