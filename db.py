"""Persistance Supabase cloisonnée par compte utilisateur.

Les secrets Supabase restent côté serveur dans st.secrets. Toute lecture/écriture métier est
filtrée par user_id ; cette règle s'applique aussi aux méthodes appelées directement par app.py.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client

from schema import NUMERIQUES, ORDRE, SCHEMA, TABLES_PAR_UTILISATEUR  # noqa: E402

PAGE = 1000  # limite par requête côté Supabase


@st.cache_resource
def _client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def _utilisateur_actif() -> str:
    """Retourne l'identifiant authentifié. Échec fermé : jamais de requête sans compte."""
    uid = st.session_state.get("user_id")
    if not isinstance(uid, str) or not uid.strip():
        raise PermissionError("Connexion requise pour accéder aux données Supabase.")
    return uid.strip()


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
def _lire_cache(table: str, user_id: str) -> pd.DataFrame:
    """Lecture paginée. user_id est un argument du cache pour éviter toute fuite inter-comptes."""
    if table not in SCHEMA:
        raise KeyError(f"Table inconnue : {table}")
    rows, debut = [], 0
    while True:
        q = _client().table(table).select("*")
        if table in TABLES_PAR_UTILISATEUR:
            if not user_id:
                raise PermissionError("Connexion requise pour accéder aux données Supabase.")
            q = q.eq("user_id", user_id)
        for col in ORDRE.get(table, []):
            q = q.order(col)
        lot = q.range(debut, debut + PAGE - 1).execute().data
        rows += lot
        if len(lot) < PAGE:
            break
        debut += PAGE
    # Ne renvoie jamais la colonne technique user_id à l'UI.
    df = pd.DataFrame(rows, columns=SCHEMA[table])
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    for c in NUMERIQUES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def lire(table: str) -> pd.DataFrame:
    """Lit uniquement les lignes de l'utilisateur courant (cache isolé par user_id)."""
    if table not in SCHEMA:
        raise KeyError(f"Table inconnue : {table}")
    return _lire_cache(table, _utilisateur_actif())


# Compatibilité avec le précédent appel lire.clear() utilisé dans ce module.
lire.clear = _lire_cache.clear  # type: ignore[attr-defined]


def _payload_utilisateur(table: str, rec: dict) -> dict:
    payload = {k: _clean(v) for k, v in rec.items()}
    if table in TABLES_PAR_UTILISATEUR:
        # Ne jamais accepter user_id fourni par les données d'un formulaire.
        payload["user_id"] = _utilisateur_actif()
    return payload


def _conflit_utilisateur(table: str, conflit: str) -> str:
    """Les clés composites des tables multi-comptes commencent par user_id."""
    if table not in TABLES_PAR_UTILISATEUR:
        return conflit
    colonnes = [c.strip() for c in conflit.split(",") if c.strip()]
    if "user_id" not in colonnes:
        colonnes.insert(0, "user_id")
    return ",".join(colonnes)


def inserer(table: str, rec: dict) -> dict | None:
    """Insère une ligne sous le compte courant et la renvoie (avec son id)."""
    res = _client().table(table).insert(_payload_utilisateur(table, rec)).execute()
    lire.clear()
    return res.data[0] if res.data else None


def modifier(table: str, id_, rec: dict, cle: str = "id") -> None:
    """UPDATE par clé, toujours restreint au compte courant."""
    payload = _payload_utilisateur(table, rec)
    payload.pop("user_id", None)  # le tenant d'une ligne ne peut pas être modifié
    q = _client().table(table).update(payload).eq(cle, id_)
    if table in TABLES_PAR_UTILISATEUR:
        q = q.eq("user_id", _utilisateur_actif())
    q.execute()
    lire.clear()


def supprimer(table: str, valeur, cle: str = "id") -> None:
    """DELETE toujours restreint au compte courant."""
    q = _client().table(table).delete().eq(cle, valeur)
    if table in TABLES_PAR_UTILISATEUR:
        q = q.eq("user_id", _utilisateur_actif())
    q.execute()
    lire.clear()


def upsert(table: str, recs: list[dict], conflit: str) -> None:
    """Upsert sous le compte courant ; une clé de conflit est automatiquement composée."""
    conflit_db = _conflit_utilisateur(table, conflit)
    for i in range(0, len(recs), 500):
        lot = [_payload_utilisateur(table, r) for r in recs[i:i + 500]]
        _client().table(table).upsert(lot, on_conflict=conflit_db).execute()
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
    _lire_cache.clear()
