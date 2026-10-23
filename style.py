"""Apparence : mise en page adaptative (mobile / tablette / PC) et habillage commun des graphiques.

- `appliquer()` injecte le CSS : colonne pleine largeur sur téléphone, contenu élargi et centré sur
  tablette et PC, listes de cartes en grille, bandeau « mode démo » cliquable.
- `habiller(fig)` donne à tous les graphiques Plotly la même palette, la même police, un format
  français des nombres (séparateurs) et des infobulles lisibles.

Aucune donnée ni règle métier ici : uniquement de la présentation.
"""
from __future__ import annotations

import streamlit as st

# Palette douce, calée sur le bleu des courbes (#0068c9) : tons moyens, pas de couleurs criardes.
PALETTE = ["#0068C9", "#2EB6A3", "#7C5CD6", "#83C9FF", "#F0A860",
           "#E0708C", "#9AA7B8", "#7FC49A", "#C9B458", "#4A5A78"]
BLEU, ARDOISE, AMBRE = PALETTE[0], PALETTE[6], PALETTE[4]
COULEURS_AMIS = [PALETTE[i] for i in (1, 2, 5, 3, 7, 8, 9)]  # courbes des autres utilisateurs

POLICE = ("Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', "
          "Arial, sans-serif")

CSS = """
<style>
/* ---- Largeur : plein écran sur mobile, colonne large et centrée sur tablette / PC ---------- */
[data-testid="stMainBlockContainer"], .block-container {
    max-width: 1320px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding-top: 5rem !important;
    padding-left: clamp(1rem, 3vw, 3rem) !important;
    padding-right: clamp(1rem, 3vw, 3rem) !important;
}

/* ---- Listes de cartes : 1 colonne sur mobile, 2 à 3 colonnes selon la largeur disponible -- */
[class*="st-key-grille_"][data-testid="stVerticalBlock"],
[class*="st-key-grille_"] > [data-testid="stVerticalBlock"] {
    display: grid !important;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
    gap: 1rem !important;
    align-items: start;
}

/* ---- Formulaires de saisie : largeur confortable, centrés ---------------------------------- */
[class*="st-key-saisie"] { max-width: 900px; width: 100%; margin-left: auto; margin-right: auto; }
[class*="st-key-connexion"] { max-width: 460px; width: 100%; margin-left: auto; margin-right: auto; }

/* ---- Indicateurs (métriques) en cartes ------------------------------------------------------ */
[data-testid="stMetric"] {
    background: rgba(128, 128, 128, 0.06);
    border: 1px solid rgba(128, 128, 128, 0.18);
    border-radius: 0.75rem;
    padding: 0.6rem 0.9rem;
}

/* ---- Bandeau « mode démo » : un bouton qui a l'apparence d'un bandeau d'information ------- */
.st-key-btn_bandeau_demo, .st-key-btn_bandeau_demo [data-testid="stButton"] { width: 100% !important; }
.st-key-btn_bandeau_demo button {
    width: 100%;
    height: auto;
    min-height: 0;
    justify-content: flex-start;
    text-align: left;
    padding: 0.65rem 0.95rem;
    border-radius: 0.6rem;
    color: inherit;
    background: rgba(28, 131, 225, 0.10);
    border: 1px solid rgba(28, 131, 225, 0.30);
}
.st-key-btn_bandeau_demo button:hover {
    background: rgba(28, 131, 225, 0.18);
    border-color: rgba(28, 131, 225, 0.60);
}
.st-key-btn_bandeau_demo button p { text-align: left; margin: 0; }

/* ---- PC / tablette large : boutons de l'en-tête alignés à droite --------------------------- */
@media (min-width: 900px) {
    .st-key-entete [data-testid="stHorizontalBlock"] { justify-content: flex-end; }
    .st-key-entete [data-testid="stColumn"]:first-child,
    .st-key-entete [data-testid="column"]:first-child { flex: 1 1 auto !important; }
    .st-key-entete [data-testid="stColumn"]:not(:first-child),
    .st-key-entete [data-testid="column"]:not(:first-child) {
        flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
    }
}
</style>
"""


def appliquer() -> None:
    """Injecte le CSS de l'application (à appeler une fois par exécution, après set_page_config)."""
    st.markdown(CSS, unsafe_allow_html=True)


def texte_sur(couleur: str) -> str:
    """Blanc ou bleu nuit selon la luminosité du fond, pour que les étiquettes restent lisibles."""
    r, g, b = (int(couleur[i:i + 2], 16) for i in (1, 3, 5))
    return "#ffffff" if 0.299 * r + 0.587 * g + 0.114 * b < 150 else "#1b2433"


def fond_page() -> str:
    """Couleur de fond (pour les séparateurs de secteurs) ; clair par défaut si le thème est inconnu."""
    try:
        return "#0e1117" if st.context.theme.type == "dark" else "#ffffff"
    except Exception:
        return "#ffffff"


def habiller(fig, **layout):
    """Style commun à tous les graphiques : palette, police, nombres à la française, infobulles."""
    fig.update_layout(
        font=dict(family=POLICE, size=13),
        colorway=PALETTE,
        separators=", ",  # 1 234,5 : virgule décimale, espace insécable pour les milliers
        hoverlabel=dict(font=dict(family=POLICE, size=13), namelength=-1, align="left"),
    )
    if layout:
        fig.update_layout(**layout)
    return fig
