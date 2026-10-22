"""Persistance Supabase cloisonnée par compte utilisateur.

Les secrets Supabase restent côté serveur dans st.secrets. Toute lecture/écriture métier est
filtrée par user_id ; cette règle s'applique aussi aux méthodes appelées directement par app.py.
"""
from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client

import calculs as C
import auth
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


@st.cache_resource
def _versions() -> dict:
    """Compteur de version par (compte, table), partagé entre sessions.

    Une écriture ne change que la version de SA table : les autres tables restent en cache
    (avant, chaque écriture vidait le cache de toutes les tables, d'où des relectures complètes).
    """
    return {}


def _version(user_id: str, table: str) -> int:
    return _versions().get((user_id, table), 0)


def _invalider(table: str) -> None:
    """Rend obsolète le cache de `table` pour le compte courant (les autres tables restent valides)."""
    v, uid = _versions(), _utilisateur_actif()
    v[(uid, table)] = v.get((uid, table), 0) + 1


@st.cache_data(ttl=120, show_spinner=False, max_entries=256)
def _lire_cache(table: str, user_id: str, version: int = 0) -> pd.DataFrame:
    """Lecture paginée. user_id est un argument du cache pour éviter toute fuite inter-comptes.

    `version` n'est pas lu : il ne sert qu'à contourner le cache après une écriture sur la table.
    """
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
    uid = _utilisateur_actif()
    return _lire_cache(table, uid, _version(uid, table))


# Compatibilité : lire.clear() vide tout le cache de lecture (bouton 🔄).
lire.clear = _lire_cache.clear  # type: ignore[attr-defined]


def precharger(tables) -> None:
    """Réchauffe le cache de plusieurs tables EN PARALLÈLE (une requête réseau chacune).

    Ne lève jamais : en cas d'échec, la lecture normale (`lire`) refait la requête et gère l'erreur.
    Sans cela, l'app lit ses ~12 tables l'une après l'autre à chaque expiration du cache.
    """
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

        uid = _utilisateur_actif()
        _client()  # créé une seule fois, ici, avant les threads
        ctx = get_script_run_ctx()
        taches = [(t, _version(uid, t)) for t in tables if t in SCHEMA]

        def lire_une(arg):
            t, v = arg
            if ctx is not None:
                add_script_run_ctx(threading.current_thread(), ctx)
            try:
                _lire_cache(t, uid, v)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lire_une, taches))
    except Exception:
        pass


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
    _invalider(table)
    return res.data[0] if res.data else None


def modifier(table: str, id_, rec: dict, cle: str = "id") -> None:
    """UPDATE par clé, toujours restreint au compte courant."""
    payload = _payload_utilisateur(table, rec)
    payload.pop("user_id", None)  # le tenant d'une ligne ne peut pas être modifié
    q = _client().table(table).update(payload).eq(cle, id_)
    if table in TABLES_PAR_UTILISATEUR:
        q = q.eq("user_id", _utilisateur_actif())
    q.execute()
    _invalider(table)


def supprimer(table: str, valeur, cle: str = "id") -> None:
    """DELETE toujours restreint au compte courant."""
    q = _client().table(table).delete().eq(cle, valeur)
    if table in TABLES_PAR_UTILISATEUR:
        q = q.eq("user_id", _utilisateur_actif())
    q.execute()
    _invalider(table)


def upsert(table: str, recs: list[dict], conflit: str) -> None:
    """Upsert sous le compte courant ; une clé de conflit est automatiquement composée."""
    conflit_db = _conflit_utilisateur(table, conflit)
    for i in range(0, len(recs), 500):
        lot = [_payload_utilisateur(table, r) for r in recs[i:i + 500]]
        _client().table(table).upsert(lot, on_conflict=conflit_db).execute()
    _invalider(table)


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


# -- Partage de la performance entre comptes (SEULE exception au cloisonnement par user_id) -----------
# Règles : jamais le compte demo (ni en lecture ni en écriture) ; seuls les comptes configurés qui ont
# coché « partager » sont lus ; seul l'indice TWR base 100 sort de ce module (jamais valeur ni apports).
PSEUDO_MAX = 30


def enregistrer_partage(partage: bool, pseudo: str) -> None:
    """Enregistre le choix de partage du compte courant (décoché par défaut)."""
    if auth.est_demo():
        raise PermissionError("Le compte demo ne partage pas sa performance.")
    pseudo = " ".join(str(pseudo or "").split())[:PSEUDO_MAX]
    upsert("partage", [{"partage": bool(partage), "pseudo": pseudo or None}], "user_id")


def _comptes_eligibles(uid: str) -> list[str]:
    cfg = auth._config_utilisateurs()
    return [u for u, d in cfg.items() if u != uid and not d.get("demo", u == "demo")]


@st.cache_data(ttl=120, show_spinner=False, max_entries=64)
def _perfs_partagees(uid: str, eligibles: tuple) -> pd.DataFrame:
    """Colonnes pseudo, date, twr (base 100 depuis le 1er point) des AUTRES comptes ayant autorisé le partage."""
    vide = pd.DataFrame(columns=["pseudo", "date", "twr"])
    if not eligibles:
        return vide
    opt = _client().table("partage").select("user_id,pseudo").eq("partage", True).in_("user_id", list(eligibles)) \
        .order("user_id").execute().data
    if not opt:
        return vide
    ids = [o["user_id"] for o in opt]
    rows, debut = [], 0
    while True:
        lot = _client().table("snapshots").select("user_id,date,valeur,apports").in_("user_id", ids) \
            .order("user_id").order("date").range(debut, debut + PAGE - 1).execute().data
        rows += lot
        if len(lot) < PAGE:
            break
        debut += PAGE
    df = pd.DataFrame(rows, columns=["user_id", "date", "valeur", "apports"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("valeur", "apports"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    sorties, pris = [], {}
    for o in opt:
        g = df[df["user_id"] == o["user_id"]].dropna()
        if len(g) < 2:
            continue
        nom = " ".join(str(o.get("pseudo") or "").split())[:PSEUDO_MAX] or "Anonyme"
        pris[nom] = pris.get(nom, 0) + 1
        if pris[nom] > 1:  # pseudos identiques : suffixe pour distinguer les courbes
            nom = f"{nom} ({pris[nom]})"
        t = C.calcul_twr(g[["date", "valeur", "apports"]])
        t["pseudo"] = nom
        sorties.append(t[["pseudo", "date", "twr"]])
    return pd.concat(sorties, ignore_index=True) if sorties else vide


def performances_partagees() -> pd.DataFrame:
    """Performances (TWR base 100) des autres comptes qui ont autorisé le partage. Vide pour le compte demo."""
    if auth.est_demo():
        return pd.DataFrame(columns=["pseudo", "date", "twr"])
    uid = _utilisateur_actif()
    return _perfs_partagees(uid, tuple(sorted(_comptes_eligibles(uid))))


def rafraichir() -> None:
    _lire_cache.clear()
