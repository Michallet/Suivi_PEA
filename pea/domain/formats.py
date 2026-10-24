"""Formats d'affichage purs : nombres à la française, pastilles de couleur, liens d'actualités.

Aucune dépendance à Streamlit ni au réseau. Un seul formateur de nombres pour toute l'application.
"""
from __future__ import annotations

from urllib.parse import quote_plus

import pandas as pd

VERT, ROUGE = "#16a34a", "#dc2626"
ESPACE_FINE = " "


def fmt(x, dec: int = 2, signe: bool = False) -> str:
    """Nombre au format français : 12 345,67 (signe optionnel) ; « N/A » si absent."""
    if x is None or pd.isna(x):
        return "N/A"
    s = f"{x:+,.{dec}f}" if signe else f"{x:,.{dec}f}"
    return s.replace(",", ESPACE_FINE).replace(".", ",")


def pastille(v: float, texte: str) -> str:
    """Texte coloré (vert si v >= 0, rouge sinon) : HTML à n'utiliser qu'avec des nombres déjà formatés."""
    return f"<span style='color:{VERT if v >= 0 else ROUGE}'>{texte}</span>"


def formater_gros_nombre(x) -> str:
    """CA / capitalisation lisibles : M € (million), Md € (milliard), T € (millier de milliards)."""
    if x is None or pd.isna(x) or x == 0:
        return "N/A"
    for seuil, suffixe in ((1e12, "T €"), (1e9, "Md €"), (1e6, "M €")):
        if abs(x) >= seuil:
            return f"{x / seuil:,.2f} {suffixe}".replace(",", ESPACE_FINE).replace(".", ",")
    return f"{x:,.0f} €".replace(",", ESPACE_FINE)


def sans_parentheses(series: pd.Series) -> pd.Series:
    """Noms épurés pour les axes : retrait de TOUS les groupes entre parenthèses
    (souvent au milieu des noms d'ETF, ex. « Amundi PEA Monde (MSCI World) UCITS ETF »)."""
    return (series.astype(str).str.replace(r"\s*\([^)]*\)", "", regex=True)
            .str.replace(r"\s{2,}", " ", regex=True).str.strip())


def court(nom: str, n: int = 14) -> str:
    """Nom raccourci pour une étiquette de graphique ou une colonne de tableau."""
    nom = str(sans_parentheses(pd.Series([nom])).iloc[0])
    return nom if len(nom) <= n else nom[:n - 1] + "…"


def cellule(v, unite: str) -> str:
    """Valeur de comparaison : « x » (multiple), « % » (marge) ou montant en €."""
    if v is None:
        return "—"
    return f"{fmt(v, 1)}x" if unite == "x" else f"{fmt(v, 1)} %" if unite == "%" else formater_gros_nombre(v)


def url_google_actualites(nom: str) -> str:
    """Lien Google Actualités (recherche « nom bourse »), calculé à l'affichage : rien n'est stocké en base."""
    requete = quote_plus(f"{nom.strip()} bourse")
    return f"https://news.google.com/search?q={requete}&hl=fr&gl=FR&ceid=FR%3Afr"


def lien_actualites(nom: str) -> str:
    """Lien Markdown vers la recherche Google Actualités du titre."""
    if not isinstance(nom, str) or not nom.strip():
        return ""
    return f"  \n[📰 Google Actualités]({url_google_actualites(nom)})"
