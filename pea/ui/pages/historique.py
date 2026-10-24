"""Onglet Historique : valeur du PEA, performance pondérée par le temps vs indice et autres utilisateurs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import marche
from pea.data import repo
from pea.domain import calculs as C
from pea.domain.formats import fmt
from pea.domain.textes import echapper_markdown as esc
from pea.domain.textes import sur_pour_graphique
from pea.services import partage
from pea.services.portefeuille import Portefeuille
from pea.ui import style
from pea.ui.composants import graphiques
from pea.ui.etat import flash, k

PERIODES = {"1M": 1, "3M": 3, "6M": 6, "1A": 12, "Tout": None}


def _indice(choix: str, twr: pd.DataFrame, debut: str):
    """Indice de référence base 100 aligné sur les dates du TWR, ou None s'il est indisponible."""
    try:
        h = marche.historique_cloture(config.BENCHMARKS[choix], debut)
        bench = h.reindex(h.index.union(twr["date"])).ffill().reindex(twr["date"]).bfill()
        return bench / bench.iloc[0] * 100
    except Exception:
        st.caption("Indice indisponible pour le moment.")
        return None


def _amis() -> pd.DataFrame:
    try:  # table « partage » absente (migration non faite) ou base indisponible : pas d'amis
        return partage.performances_partagees()
    except Exception:
        return pd.DataFrame(columns=["pseudo", "date", "twr"])


def _courbe_valeur(sn: pd.DataFrame) -> None:
    st.subheader("Valeur du PEA")
    graphiques.courbes([
        dict(x=sn["date"], y=sn["valeur"], name="Valeur du PEA", line=dict(color=style.BLEU, width=2.5),
             hovertemplate="%{y:,.0f} €"),
        dict(x=sn["date"], y=sn["apports"], name="Apports nets",
             line=dict(shape="hv", dash="dot", color=style.ARDOISE, width=2), hovertemplate="%{y:,.0f} €")])


def _courbe_performance(sn: pd.DataFrame) -> None:
    st.subheader("Performance vs indice")
    st.caption("Performance pondérée par le temps : neutralise vos versements, base 100.")
    choix = st.selectbox("Comparer à", list(config.BENCHMARKS), label_visibility="collapsed", key=k("hist", "indice"))
    amis = _amis()
    noms = sorted(amis["pseudo"].unique())
    choisis = st.multiselect("Comparer aux autres utilisateurs", noms, default=noms, key=k("hist", "amis"),
                             placeholder="Utilisateurs à afficher", label_visibility="collapsed") if noms else []
    twr = C.calcul_twr(sn)
    bench = _indice(choix, twr, sn["date"].min().strftime("%Y-%m-%d"))
    series = [dict(x=twr["date"], y=twr["twr"], name="Mon PEA", line=dict(color=style.BLEU, width=2.5),
                   hovertemplate="%{y:.1f}")]
    if bench is not None:
        series.append(dict(x=twr["date"], y=bench.to_numpy(), name=choix, line=dict(color=style.ARDOISE, width=2),
                           hovertemplate="%{y:.1f}"))
    perf_amis = {}
    for n, p in enumerate(choisis):
        s = amis[amis["pseudo"] == p].set_index("date")["twr"]
        s = s.reindex(s.index.union(twr["date"])).ffill().reindex(twr["date"])  # pas de bfill
        if s.notna().sum() < 2:
            continue  # pas de données sur la période
        s = s / s.dropna().iloc[0] * 100
        perf_amis[p] = s.iloc[-1] - 100
        series.append(dict(x=twr["date"], y=s.to_numpy(), name=sur_pour_graphique(p), connectgaps=False,
                           line=dict(width=1.5, color=style.COULEURS_AMIS[n % len(style.COULEURS_AMIS)]),
                           hovertemplate="%{y:.1f}"))
    graphiques.courbes(series)
    resume = f"Mon PEA : **{fmt(twr['twr'].iloc[-1] - 100, 2, True)} %**"
    if bench is not None:
        resume += f" · {choix} : **{fmt(bench.iloc[-1] - 100, 2, True)} %**"
    st.markdown(resume)
    if perf_amis:
        st.markdown(" · ".join(f"{esc(p)} : **{fmt(v, 2, True)} %**" for p, v in perf_amis.items()))
        st.caption("Courbes des autres utilisateurs : base 100 au début de la période (ou à leur "
                   "1er point s'il est plus récent).")


def bloc_partage() -> None:
    """Case de partage de la performance (décochée par défaut) + pseudo. Seul l'indice base 100 est partagé."""
    try:
        cfg = repo.lire("partage")
    except Exception:
        st.caption("Partage indisponible : exécutez d'abord la migration SQL (table « partage », voir schema.sql).")
        return
    actif = bool(cfg["partage"].iloc[0]) if not cfg.empty and pd.notna(cfg["partage"].iloc[0]) else False
    pseudo = (cfg["pseudo"].iloc[0] if not cfg.empty else None) or ""
    pseudo = "" if pd.isna(pseudo) else str(pseudo)
    cle_actif, cle_pseudo = k("part", "actif"), k("part", "pseudo")

    def sauver() -> None:
        try:
            repo.enregistrer_partage(st.session_state.get(cle_actif, False), st.session_state.get(cle_pseudo, pseudo))
        except Exception as e:
            flash(f"Enregistrement du partage impossible : {type(e).__name__}")

    st.divider()
    st.checkbox("Partager ma performance avec les autres utilisateurs", value=actif, key=cle_actif, on_change=sauver,
                help="Seule votre courbe de performance (base 100, sans montant ni position) est visible, "
                     "sous le pseudo ci-dessous. Décochez pour cesser immédiatement le partage.")
    if st.session_state.get(cle_actif, actif):
        st.text_input("Pseudo affiché", value=pseudo, key=cle_pseudo, max_chars=repo.PSEUDO_MAX,
                      placeholder="Anonyme", on_change=sauver, help="Laissez vide pour apparaître comme « Anonyme ».")


@st.fragment
def afficher(pf: Portefeuille) -> None:
    snaps = pf.snaps
    if len(snaps) < 2:
        st.info("Pas encore d'historique : un point est enregistré à chaque visite en semaine. "
                "Vous pouvez aussi le reconstituer depuis vos transactions (Saisie › Maintenance & sauvegarde).")
    else:
        periode = st.radio("Période", list(PERIODES), horizontal=True, index=4, key=k("hist", "periode"))
        mois = PERIODES[periode]
        sn = snaps if mois is None else snaps[
            snaps["date"] >= pd.Timestamp(config.maintenant().date()) - pd.DateOffset(months=mois)]
        if len(sn) < 2:
            st.info("Pas assez de points sur cette période.")
        else:
            g_valeur, g_indice = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
            with g_valeur:
                _courbe_valeur(sn)
            with g_indice:
                _courbe_performance(sn)
    if not pf.demo:
        bloc_partage()
