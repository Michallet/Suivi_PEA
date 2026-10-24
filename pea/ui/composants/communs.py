"""Petits composants partagés : choix d'ISIN, bascule de vue, indicateurs techniques, création de titre."""
from __future__ import annotations

import streamlit as st

from pea import config
from pea.data import marche
from pea.domain import technique as TECH
from pea.domain.formats import fmt
from pea.services import titres
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash_concurrent, k

PLOTLY = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False}
NOUVEL_ISIN = "➕ Nouvel ISIN…"
VUES = ("Fondamentaux", "Techniques")
TXT_AVERTISSEMENT_TECH = ("Note = moyenne pondérée des 4 indicateurs ; ≥ 6 acheter, ≤ 4 vendre. "
                          "Signal indicatif, pas un conseil en investissement.")


def puces(details: list) -> str:
    return "\n".join(f"- {cle} : **{v}**" for cle, v in details)


def choisir_isin(pf: Portefeuille, label: str, options: list[str], cle: str, nouveau: bool = True) -> str:
    """Liste déroulante (recherche au clavier) + saisie d'un nouvel ISIN si besoin."""
    opts = list(options) + ([NOUVEL_ISIN] if nouveau else [])
    if not opts:
        return ""
    choix = st.selectbox(label, opts, key=k(cle, "sel"),
                         format_func=lambda i: i if i == NOUVEL_ISIN else f"{pf.nom_de(i)} ({i})")
    if choix == NOUVEL_ISIN:
        return st.text_input("ISIN", key=k(cle, "new"), placeholder="FR0000121014").strip().upper()
    return choix


def selecteur_vue(ctx: str) -> str:
    """Bascule « Fondamentaux / Techniques » des cartes (le téléchargement des historiques n'a lieu
    que si « Techniques » est choisi)."""
    return st.radio("Affichage des détails", VUES, horizontal=True, key=k("vue", ctx),
                    label_visibility="collapsed",
                    format_func=lambda v: "Indicateurs techniques" if v == "Techniques" else v)


def calculer_techniques(tickers) -> dict:
    """{ticker: analyse technique}. Un téléchargement groupé, cache 1 h."""
    valides = tuple(dict.fromkeys(t for t in tickers if isinstance(t, str) and t))
    return {t: TECH.analyser(df) for t, df in marche.ohlc_batch(valides).items()} if valides else {}


def afficher_technique(res: dict | None) -> None:
    if not res or not res.get("ok"):
        st.caption((res or {}).get("raison") or "Historique de cours indisponible pour ce titre.")
        return
    st.markdown(f"**{res['emoji']} {res['verdict']}** · note technique **{fmt(res['note'], 1)}/10** · "
                f"séance du {res['date']:%d/%m/%Y}")
    st.markdown("\n".join(f"- {i['emoji']} **{i['label']}** : {i['detail']}" for i in res["indicateurs"]))
    st.caption(TXT_AVERTISSEMENT_TECH)


def creer_titre(pf: Portefeuille, isin: str, ticker: str, nom: str | None = None, suggerer: bool = True) -> str | None:
    """Valide et mémorise ISIN -> ticker ; à la CRÉATION d'un titre, propose un concurrent (une fois) si
    `suggerer`. Les créations en lot (import, maintenance) passent `suggerer=False`. Retourne l'erreur."""
    nouveau = isin not in pf.tmap.index
    err, nom_valide = titres.enregistrer_ticker(isin, ticker, nom)
    if err is None and suggerer and nouveau and not pf.demo and config.cle_gemini():
        with st.spinner("Recherche d'un concurrent…"):
            msg = titres.suggerer_a_la_creation(isin, ticker, nom_valide)
        if msg:
            flash_concurrent(msg)
    return err
