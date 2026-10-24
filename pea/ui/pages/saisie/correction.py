"""Saisie › Corriger / supprimer : tableau modifiable, écritures en lot (repo.appliquer_modifs)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea.data import repo
from pea.domain import calculs as C
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash, k
from pea.ui.pages.saisie.versement import LIBELLES_VERS

CLE_VERSION = k("ed", "version")


def colonnes() -> dict:
    return {
        "transactions": {
            "id": None,
            "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
            "isin": st.column_config.TextColumn("ISIN", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=["ACHAT", "VENTE"], required=True),
            "quantite": st.column_config.NumberColumn("Qté", min_value=0.0001, required=True),
            "prix": st.column_config.NumberColumn("Prix €", min_value=0.0, required=True),
            "frais": st.column_config.NumberColumn("Frais €", min_value=0.0),
        },
        "dividendes": {
            "id": None,
            "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
            "isin": st.column_config.TextColumn("ISIN", required=True),
            "montant": st.column_config.NumberColumn("Montant net €", min_value=0.01, required=True),
        },
        "versements": {
            "id": None,
            "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=list(LIBELLES_VERS), required=True),
            "montant": st.column_config.NumberColumn("Montant €", min_value=0.01, required=True),
            "libelle": st.column_config.TextColumn("Libellé"),
        },
    }


TABLES = ("transactions", "dividendes", "versements")


def _verifier(pf: Portefeuille, table: str, n: pd.DataFrame) -> str | None:
    """Contrôles avant écriture ; normalise `n` en place. Retourne l'erreur à afficher, sinon None."""
    requis = [c for c in ("date", "isin", "type", "quantite", "prix", "montant") if c in n]
    if n[requis].isna().any().any():
        return "Des champs obligatoires sont vides."
    n["date"] = pd.to_datetime(n["date"])
    if "isin" in n:
        n["isin"] = n["isin"].str.strip().str.upper()
        inconnus = sorted(set(n["isin"]) - set(pf.tmap.index))
        if inconnus:
            return (f"ISIN inconnu(s) : {', '.join(inconnus)}. "
                    "Ajoutez-les d'abord via la watchlist ou l'action « Transaction ».")
    if "frais" in n:
        n["frais"] = n["frais"].fillna(0.0)
    if table == "transactions":
        try:
            C.calcul_positions(n)
        except ValueError as e:
            return str(e)
    return None


def afficher(pf: Portefeuille) -> None:
    table = st.selectbox("Table", TABLES, format_func=str.capitalize, key=k("ed", "table"))
    version = st.session_state.get(CLE_VERSION, 0)
    df = repo.lire(table)
    edit = st.data_editor(df, key=k("ed", table, version), num_rows="dynamic", hide_index=True,
                          column_config=colonnes()[table])
    if not st.button("💾 Enregistrer les modifications", key=k("ed", "save")):
        return
    n = edit.copy()
    err = _verifier(pf, table, n)
    if err:
        st.error(err)
        return
    a, m, sup = repo.appliquer_modifs(table, df, n)
    st.session_state[CLE_VERSION] = version + 1
    flash(f"{a} ajoutée(s), {m} modifiée(s), {sup} supprimée(s) ✅")
    st.rerun()
