"""Porte de connexion, en-tête (compte, 🔄, 🔒) et bandeau du mode démo."""
from __future__ import annotations

import streamlit as st

from pea.data import repo
from pea.services import auth
from pea.services.portefeuille import CLE_ACTUALISER


def formulaire_connexion() -> None:
    """Formulaire dont les champs sont préremplis avec les identifiants de démonstration."""
    with st.form("form_connexion"):
        identifiant = st.text_input("Identifiant", value="demo", key="login_user")
        mot_de_passe = st.text_input("Mot de passe", value="demo", type="password", key="login_password")
        soumis = st.form_submit_button("Entrer", type="primary", use_container_width=True)
    if soumis:
        erreur = auth.tenter_connexion(identifiant, mot_de_passe)
        if erreur:
            st.error(erreur)
        else:
            st.rerun()


def porte() -> None:
    """Connecte la démo par défaut si l'interrupteur est actif ; sinon arrête le script sur le formulaire."""
    auth.connecter_demo_par_defaut()  # interrupteur CONNEXION_DEMO_AUTO (ou secret AUTO_CONNEXION_DEMO)
    if auth.connecte():
        return
    with st.container(key="connexion"):
        st.title("📈 Suivi PEA")
        st.info("Connectez-vous pour accéder à un portefeuille. Les identifiants du compte démo "
                "sont préremplis (demo / demo) : « Entrer » suffit pour revenir à la démo.")
        formulaire_connexion()
    st.stop()


def entete(demo: bool) -> None:
    with st.container(key="entete"):
        t1, t2, t3 = st.columns([4, 1, 1], vertical_alignment="center")
        t1.title("📈 Mon PEA")
        t1.caption(f"Compte : {auth.utilisateur()}")
        if t2.button("🔄", help="Actualiser les cours"):
            repo.invalider_compte()  # uniquement le compte courant ; le marché suit sa propre fraîcheur
            st.session_state[CLE_ACTUALISER] = True
            st.rerun()
        # Le verrou fait quitter le compte courant ; en démo, il ouvre le formulaire de connexion.
        if t3.button("🔒", key="btn_verrou", help="Se connecter à un compte personnel" if demo else "Se déconnecter"):
            auth.deconnecter()
            st.rerun()
    if demo:
        # Le bandeau est cliquable : même effet que le verrou.
        if st.button("🧪 **Mode démo** : portefeuille fictif · touchez ici pour vous connecter",
                     key="btn_bandeau_demo",
                     help="Vos ajouts et suppressions restent dans votre session : rien n'est enregistré en base "
                          "et les autres visiteurs ne les voient pas. Les cours de marché peuvent être réels. "
                          "Les fonctions IA sont désactivées."):
            auth.deconnecter()
            st.rerun()
        st.caption("Vos modifications ne sont visibles que par vous et disparaissent à la fin de la session. "
                   "IA désactivée.")
