"""Suivi PEA — interface Streamlit mobile-first multi-utilisateur.

Ce fichier ne fait que l'assemblage : configuration de page, porte de connexion, contexte du compte,
onglets paresseux. Le code vit dans le paquet `pea/` (domain ← data ← services ← ui).
Les comptes sont définis dans les secrets Streamlit ([users.*]). Le compte demo lit un jeu de données
fictif en base, en lecture seule (ses modifications restent dans la session) et n'a pas accès à l'IA.
"""
from __future__ import annotations

import time

import streamlit as st

from pea import config
from pea.data import marche
from pea.data import repo
from pea.services import auth, portefeuille
from pea.ui import entete, style
from pea.ui.etat import afficher_flash
from pea.ui.pages import historique, projet, saisie, watchlist
from pea.ui.pages import portefeuille as page_portefeuille

# layout="wide" : plein écran sur mobile ; sur tablette / PC, style.py centre le contenu (1 320 px max),
# met les listes de cartes en grille et les graphiques côte à côte.
st.set_page_config(page_title="Suivi PEA", page_icon="📈", layout="wide")
style.appliquer()
repo.initialiser()  # client Supabase créé dans le fil principal (avant tout fil d'arrière-plan)
CHRONO = {"debut": time.perf_counter()}  # affiché en bas de page si le secret DEBUG_PERF est activé


def jalon(nom: str) -> None:
    CHRONO[nom] = time.perf_counter()


entete.porte()
afficher_flash()
entete.entete(auth.est_demo())

try:
    pf = portefeuille.construire(st.session_state, st.session_state.pop(portefeuille.CLE_ACTUALISER, False), jalon)
except portefeuille.BaseIndisponible as e:  # pas de détail à l'écran : il pourrait contenir des infos sensibles
    st.error("Connexion à la base impossible. Vérifiez SUPABASE_URL et SUPABASE_KEY dans les "
             "secrets, et que schema.sql a bien été exécuté.")
    st.caption(f"Type d'erreur : {e}")
    st.stop()
if pf.tables_manquantes:
    st.warning("Tables manquantes : " + ", ".join(pf.tables_manquantes)
               + ". Exécutez la version à jour de sql/schema.sql dans Supabase.")

# Onglets paresseux : seul l'onglet ouvert s'exécute ; changer d'onglet relance le script.
ONGLETS = {"📊 Portefeuille": page_portefeuille.afficher, "📈 Historique": historique.afficher,
           "🔭 Projet": projet.afficher, "👀 Watchlist": watchlist.afficher, "➕ Saisie": saisie.afficher}
for onglet, page in zip(st.tabs(list(ONGLETS), on_change="rerun", key="onglet"), ONGLETS.values()):
    if onglet.open is not False:  # None : version de Streamlit qui ne suit pas l'onglet actif (tout s'exécute)
        with onglet:
            if page is saisie.afficher:
                with st.container(key="saisie"):  # largeur limitée par le CSS : formulaires lisibles
                    page(pf)
            else:
                page(pf)
jalon("affichage")

pf.memoriser_suivi()  # après l'affichage : n'allonge pas le temps avant la page


@st.fragment(run_every=2)
def surveiller_marche() -> None:
    """Cours encore en téléchargement (arrière-plan) : relance l'affichage dès qu'ils arrivent (≤ 30 s)."""
    n = st.session_state.get("_attente_marche", 0)
    if not marche.rafraichissement_en_cours() or n > 15:
        st.session_state.pop("_attente_marche", None)
        if n:
            st.rerun()
        return
    st.session_state["_attente_marche"] = n + 1


if marche.rafraichissement_en_cours():
    surveiller_marche()

if config.debug_perf():  # secret facultatif : DEBUG_PERF = true
    prec, morceaux = CHRONO["debut"], []
    for nom, t in ((n, v) for n, v in CHRONO.items() if n != "debut"):
        morceaux.append(f"{nom} {1000 * (t - prec):.0f} ms")
        prec = t
    st.caption("⏱ " + " · ".join(morceaux) + f" · total script {1000 * (time.perf_counter() - CHRONO['debut']):.0f} ms")
