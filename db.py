"""Persistance Supabase (Postgres gratuit). Les identifiants viennent de st.secrets, jamais du dépôt."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client

from schema import NUMERIQUES, ORDRE, SCHEMA  # noqa: E402

PAGE = 1000  # limite par requête côté Supabase


@st.cache_resource
def _client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def _clean(v):
    """Valeur pandas/numpy -> valeur JSON."""
    if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, dt.date, dt.datetime)):
        return pd.Timestamp(v).date().isoformat()
    if isinstance(v, np.generic):
        return v.item()
    return v


@st.cache_data(ttl=120, show_spinner=False)
def lire(table: str) -> pd.DataFrame:
    """Lit une table entière (paginée). Cache 2 min ; vidé automatiquement à chaque écriture."""
    rows, debut = [], 0
    while True:
        q = _client().table(table).select("*")
        for col in ORDRE.get(table, []):
            q = q.order(col)
        lot = q.range(debut, debut + PAGE - 1).execute().data
        rows += lot
        if len(lot) < PAGE:
            break
        debut += PAGE
    df = pd.DataFrame(rows, columns=SCHEMA[table])
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    for c in NUMERIQUES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def inserer(table: str, rec: dict) -> dict | None:
    """Insère une ligne et la renvoie (avec son id)."""
    res = _client().table(table).insert({k: _clean(v) for k, v in rec.items()}).execute()
    lire.clear()
    return res.data[0] if res.data else None


def modifier(table: str, id_: int, rec: dict) -> None:
    _client().table(table).update({k: _clean(v) for k, v in rec.items()}).eq("id", id_).execute()
    lire.clear()


def supprimer(table: str, valeur, cle: str = "id") -> None:
    _client().table(table).delete().eq(cle, valeur).execute()
    lire.clear()


def upsert(table: str, recs: list[dict], conflit: str) -> None:
    for i in range(0, len(recs), 500):
        lot = [{k: _clean(v) for k, v in r.items()} for r in recs[i:i + 500]]
        _client().table(table).upsert(lot, on_conflict=conflit).execute()
    lire.clear()


def appliquer_modifs(table: str, avant: pd.DataFrame, apres: pd.DataFrame) -> tuple[int, int, int]:
    """Répercute les modifications d'un st.data_editor : (ajoutées, modifiées, supprimées)."""
    cols = [c for c in SCHEMA[table] if c != "id"]
    ids_apres = set(apres["id"].dropna().astype(int))
    a_supprimer = set(avant["id"].astype(int)) - ids_apres
    for i in a_supprimer:
        supprimer(table, i)

    avant_idx = avant.set_index(avant["id"].astype(int))
    ajoutes = modifies = 0
    for _, r in apres.iterrows():
        rec = {c: _clean(r[c]) for c in cols}
        if pd.isna(r["id"]):
            inserer(table, rec)
            ajoutes += 1
        else:
            i = int(r["id"])
            ancien = {c: _clean(avant_idx.loc[i, c]) for c in cols}
            if ancien != rec:
                modifier(table, i, rec)
                modifies += 1
    return ajoutes, modifies, len(a_supprimer)


def rafraichir() -> None:
    lire.clear()
