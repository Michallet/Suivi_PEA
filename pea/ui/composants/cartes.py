"""Cartes de lignes (Portefeuille, Projet, Watchlist) et bloc « concurrent » sous les fondamentaux."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea.data import marche
from pea.data import repo
from pea.domain import concurrents as CONC
from pea.domain import technique as TECH
from pea.domain.fondamentaux import est_etf, lignes_fondamentaux
from pea.domain.formats import cellule, court, fmt, lien_actualites, pastille
from pea.domain.textes import echapper_markdown as esc
from pea.services import ia, quotas, titres
from pea.services.portefeuille import Portefeuille
from pea.ui.composants.communs import afficher_technique, puces
from pea.ui.etat import flash, k, relancer_zone


def afficher_comparaison(nom: str, conc: dict, lignes: list) -> None:
    if not lignes:
        st.caption(f"Fondamentaux indisponibles pour comparer avec {conc['nom']}.")
        return
    tab = [f"| | {esc(court(nom))} | {esc(court(conc['nom']))} |", "|---|--:|--:|"]
    tab += [f"| {l['label']} | {cellule(l['vt'], l['unite'])} | {cellule(l['vc'], l['unite'])} |" for l in lignes]
    st.markdown("\n".join(tab))
    st.caption("Marges = résultat ÷ chiffre d'affaires. Données Yahoo, indicatives.")


def _edition_concurrent(pf: Portefeuille, isin: str, nom: str, f: dict | None, conc: dict | None, cle: str) -> None:
    sug = st.session_state.pop(k("csug", cle), None)  # suggestion IA : à injecter AVANT de créer les champs
    if sug:
        st.session_state[k("cisin", cle)], st.session_state[k("ctk", cle)] = sug["isin"], sug["ticker"]
        st.info(f"💡 Suggestion IA : **{esc(sug['nom'])}**" + (f" — {esc(sug['raison'])}" if sug["raison"] else "")
                + ". À enregistrer pour la conserver.")
    st.session_state.setdefault(k("cisin", cle), (conc or {}).get("isin", ""))
    st.session_state.setdefault(k("ctk", cle), (conc or {}).get("ticker", ""))
    isin_c = st.text_input("ISIN du concurrent", key=k("cisin", cle), placeholder="DE0007236101")
    tk_c = st.text_input("Ticker Yahoo (facultatif)", key=k("ctk", cle), placeholder="ex : SIE.DE")
    ia_ok = titres.ia_concurrent_disponible()
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 Enregistrer", key=k("csave", cle), type="primary"):
        c, err = titres.preparer_concurrent(isin_c, tk_c, isin)
        err = err or titres.enregistrer_concurrent(isin, c)
        if err:
            st.error(err)
        else:
            flash(f"Concurrent enregistré : {c['nom']} ✅")
            st.rerun()
    if b2.button("💡 IA", key=k("csugbtn", cle), disabled=not ia_ok,
                 help="Suggestion par l'IA" if ia_ok else "IA indisponible (compte démo, clé absente ou limite atteinte)"):
        try:
            with st.spinner("Recherche d'un concurrent…"):
                prop = titres.proposer_concurrent(nom, isin, f)
        except (ia.ErreurIA, quotas.QuotaDepasse) as e:
            st.error(str(e))
        else:
            if prop:
                st.session_state[k("csug", cle)] = prop
                relancer_zone()  # rien n'est écrit : seule la zone change
            st.warning("Aucun concurrent fiable trouvé : saisissez-le à la main.")
    if conc and b3.button("🗑 Retirer", key=k("cdel", cle)):
        err = titres.enregistrer_concurrent(isin, None)
        if err:
            st.error(err)
        else:
            for suffixe in ("cisin", "ctk", "cedit", "cmp"):
                st.session_state.pop(k(suffixe, cle), None)
            flash("Concurrent retiré")
            st.rerun()


def bloc_concurrent(pf: Portefeuille, isin: str, nom: str, f: dict | None, ctx: str) -> None:
    """Sous les fondamentaux d'une action : comparaison avec son concurrent (à la demande) et édition."""
    if est_etf(nom, f):
        return
    cle = f"{ctx}_{isin}"
    conc = pf.concurrent_de(isin)
    comparer = False
    if conc:
        c1, c2 = st.columns([4, 1])
        comparer = c1.toggle(f"⚖️ Comparer à {esc(conc['nom'])}", key=k("cmp", cle))
        edition = c2.toggle("✏️", key=k("cedit", cle), help="Modifier ou retirer le concurrent")
    else:
        edition = st.toggle("➕ Ajouter un concurrent", key=k("cedit", cle))
    if comparer:  # les fondamentaux du concurrent ne sont téléchargés que sur demande
        fc = marche.fondamentaux_batch((conc["ticker"],), attente=10).get(conc["ticker"], {})
        afficher_comparaison(nom, conc, CONC.lignes_comparaison(f, fc))
    if edition:
        _edition_concurrent(pf, isin, nom, f, conc, cle)


def carte_ligne(pf: Portefeuille, r, ctx: str, vue: str = "Fondamentaux", techs: dict | None = None) -> None:
    """Carte d'une ligne détenue (réelle ou projetée) : synthèse, lien, détails (fondamentaux OU techniques)."""
    badge = "" if r.statut == "live" else f" ⚠️ {r.statut}"
    jour = pastille(r.var_jour_pct, f"{fmt(r.var_jour_pct, 2, True)} % auj.")
    total = pastille(r.perf_pct, f"{fmt(r.perf_pct, 1, True)} % total")
    res_t = (techs or {}).get(r.ticker) if vue == "Techniques" else None
    resume_t = TECH.resume(res_t)
    with st.container(border=True):
        g, d = st.columns([3, 2])
        g.markdown(f"**{esc(r.nom)}**{badge}  \n{esc(r.secteur)} · {fmt(r.poids_pct, 0)} %"
                   + (f"  \nTechnique : {resume_t}" if resume_t else "") + lien_actualites(r.nom))
        d.markdown(f"<div style='text-align:right'><b>{fmt(r.valeur)} €</b><br>"
                   f"{jour}<br>{total}</div>", unsafe_allow_html=True)
        with st.expander("Détails"):
            f = pf.fondamentaux(r.ticker)
            position = [("Quantité", f"{r.quantite:g}"), ("PRM", f"{fmt(r.prm)} €"),
                        ("Cours", f"{fmt(r.prix_eff)} €"),
                        ("+/- value latente", f"{fmt(r.pv_latente, 2, True)} €"),
                        ("Dividendes perçus", f"{fmt(r.dividendes)} €")]
            ident = [("ISIN · ticker", f"{r.isin} · {r.ticker}")]
            if vue == "Techniques":
                st.markdown(puces(position + ident))
                afficher_technique(res_t)
            else:
                st.markdown(puces(position + lignes_fondamentaux(f) + ident))
                bloc_concurrent(pf, r.isin, r.nom, f, ctx)


def carte_suivi(pf: Portefeuille, r, vue: str, techs: dict) -> None:
    """Carte d'une valeur de la watchlist (non détenue) : cours, variation du jour, note, détails."""
    prix, prev = pf.cours_et_veille(r.isin)
    var = (prix / prev - 1) * 100 if prix and prev and not pd.isna(prev) else None
    note = "" if r.note is None or pd.isna(r.note) else f"  \n_{esc(r.note)}_"
    ticker = pf.ticker_de(r.isin)
    f = pf.fondamentaux(ticker)
    res_t = techs.get(ticker) if vue == "Techniques" else None
    resume_t = TECH.resume(res_t)
    nom = pf.nom_de(r.isin)
    with st.container(border=True):
        g, d = st.columns([3, 2])
        g.markdown(f"**{esc(nom)}**  \n{esc(pf.secteur_de(r.isin, ticker))}{note}"
                   + (f"  \nTechnique : {resume_t}" if resume_t else "") + lien_actualites(nom))
        txt = f"<b>{fmt(prix)} €</b>" if prix and not pd.isna(prix) else "N/A"
        if var is not None:
            txt += "<br>" + pastille(var, f"{fmt(var, 2, True)} % auj.")
        d.markdown(f"<div style='text-align:right'>{txt}</div>", unsafe_allow_html=True)
        with st.expander("Détails"):
            ident = [("ISIN · ticker", f"{r.isin} · {ticker or '—'}")]
            if vue == "Techniques":
                st.markdown(puces([("Cours", f"{fmt(prix)} €")] + ident))
                afficher_technique(res_t)
            else:
                st.markdown(puces([("Cours", f"{fmt(prix)} €")] + lignes_fondamentaux(f) + ident))
                bloc_concurrent(pf, r.isin, nom, f, "wl")
            if st.button("🗑 Retirer de la watchlist", key=k("wl", "del", r.isin)):
                repo.supprimer("watchlist", r.isin, cle="isin")
                flash("Retiré de la watchlist")
                st.rerun()
