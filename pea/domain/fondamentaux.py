"""Fondamentaux d'un titre : lignes affichées, détection des ETF, grandeurs de la matrice de notes.

Logique pure (aucune dépendance à Streamlit ni au réseau).
"""
from __future__ import annotations

import pandas as pd

from pea.domain.formats import fmt, formater_gros_nombre
from pea.domain.nombres import nombre

# clé -> (libellé, « bas = bon » ?, unité pour l'affichage, ce que signifie une note haute)
GRANDEURS = {
    "per": ("PER", True, "x", "PER bas"),
    "per_prev": ("PER prévisionnel", True, "x", "PER prévisionnel bas"),
    "ev_ebitda": ("EV/EBITDA", True, "x", "EV/EBITDA bas"),
    "p_ca": ("Capitalisation / CA", True, "x", "valorisation basse"),
    "marge": ("Marge nette", False, "%", "forte marge"),
    "net_income": ("Bénéfice net", False, "", "gros bénéfice"),
    "ebitda": ("EBITDA", False, "", "gros EBITDA"),
    "ca": ("Chiffre d'affaires", False, "", "gros chiffre d'affaires"),
    "capi": ("Capitalisation", False, "", "grosse capitalisation"),
}
RATIOS_POSITIFS = {"per", "per_prev", "ev_ebitda", "p_ca"}  # ≤ 0 = société déficitaire = sans valeur


def present(x) -> bool:
    return x is not None and not pd.isna(x) and x != 0


def lignes_fondamentaux(f: dict) -> list[tuple[str, str]]:
    """Fondamentaux Yahoo disponibles, dans le même ordre partout ; les valeurs absentes sont omises."""
    f = f or {}
    defs = [
        ("PER", "per", lambda x: fmt(x, 1)),
        ("PER prévisionnel", "per_prev", lambda x: fmt(x, 1)),
        ("Chiffre d'affaires", "ca", formater_gros_nombre),
        ("Bénéfice net", "net_income", formater_gros_nombre),
        ("EBITDA", "ebitda", formater_gros_nombre),
        ("Capitalisation", "capi", formater_gros_nombre),
        ("Valeur d'entreprise", "ev", formater_gros_nombre),
        ("EV/EBITDA", "ev_ebitda", lambda x: f"{fmt(x, 1)}x"),
        ("Actifs sous gestion", "net_assets", formater_gros_nombre),
        ("Frais annuels", "expense_ratio", lambda x: f"{fmt(x, 2)} %"),
    ]
    return [(lbl, fn(f[k])) for lbl, k, fn in defs if present(f.get(k))]


def est_etf(nom, f: dict | None) -> bool:
    """Un ETF n'a pas de concurrent à comparer : détecté par le nom, ou par des actifs sous gestion sans CA."""
    n = str(nom or "").upper()
    if "ETF" in n or "UCITS" in n:
        return True
    f = f or {}
    return bool((present(f.get("net_assets")) or present(f.get("expense_ratio")))
                and not present(f.get("ca")) and not present(f.get("per")) and not present(f.get("capi")))


def valeur_grandeur(f: dict | None, cle: str):
    """Valeur brute d'une grandeur pour une ligne (None si absente ou inexploitable)."""
    f = f or {}
    if cle == "marge":
        ni, ca = nombre(f.get("net_income")), nombre(f.get("ca"))
        v = ni / ca * 100 if ni is not None and ca else None
    elif cle == "p_ca":
        capi, ca = nombre(f.get("capi")), nombre(f.get("ca"))
        v = capi / ca if capi is not None and ca and ca > 0 else None
    else:
        v = nombre(f.get(cle))
    return None if v is not None and cle in RATIOS_POSITIFS and v <= 0 else v
