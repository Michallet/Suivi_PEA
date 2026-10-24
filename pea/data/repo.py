"""Seule porte d'entrée vers Supabase : toute lecture ou écriture d'un compte est filtrée par `user_id`.

Règles (vérifiées par tests/test_repo_isolation.py) :
* le `user_id` vient de la session authentifiée, jamais des données d'un formulaire ; échec fermé sans compte ;
* lectures en colonnes ciblées, tables en croissance bornées (dernières lignes seulement), cache mémoire
  par (compte, table) invalidé table par table et compte par compte (jamais les autres comptes) ;
* préchargement en UN aller-retour (fonction SQL `pea_charger_compte`) avec repli sur des lectures parallèles ;
* compte démo : lecture seule en base ; ses modifications vivent dans sa session (aucune écriture Supabase) ;
* exceptions explicites et documentées : `marche_*` (table publique `marche_cache`), `compter_global`
  (un nombre, jamais une ligne) et `partages_bruts` (courbes des comptes ayant choisi de partager).

Aucun autre module n'importe `supabase` ni ne touche au client.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pea import config
from pea.data.schema import (CASCADES, CLES_NATURELLES, DERNIERES_LIGNES, NUMERIQUES, ORDRE, SCHEMA,
                             TABLES_COMPTE, TABLES_PAR_UTILISATEUR)

journal = logging.getLogger(__name__)

RPC_CHARGER = "pea_charger_compte"
CLE_DEMO = "_pea_demo_tables"   # clé de session des tables modifiées par un visiteur de la démo
CLE_DEMO_REV = CLE_DEMO + "_rev"  # compteur de modifications de la démo (signature des données)
NOUVEL_ESSAI_ABSENT_S = 600      # table ou fonction absente : on ne réessaie pas avant 10 min


# --------------------------------------------------------------------------------------------------
# Client et contexte (remplaçables par des faux dans les tests)
# --------------------------------------------------------------------------------------------------
_etat: dict = {"client": None, "contexte": None}
_verrou_client = threading.Lock()


def definir_client(client) -> None:
    """Injecte un client (faux Supabase en test). En production, le client est créé à la demande."""
    _etat["client"] = client


def _client():
    if _etat["client"] is None:
        with _verrou_client:
            if _etat["client"] is None:
                from supabase import create_client  # import tardif : seul ce module connaît Supabase
                url, cle = config.secret("SUPABASE_URL"), config.secret("SUPABASE_KEY")
                if not url or not cle:
                    raise RuntimeError("Secrets SUPABASE_URL / SUPABASE_KEY absents.")
                _etat["client"] = create_client(url, cle)
    return _etat["client"]


def initialiser() -> None:
    """Crée le client dans le fil principal (avant tout fil d'arrière-plan)."""
    _client()


@dataclass
class Contexte:
    uid: str | None
    demo: bool
    session: dict = field(default_factory=dict)


def _contexte_streamlit() -> Contexte:
    import streamlit as st
    uid = st.session_state.get("user_id")
    if not isinstance(uid, str) or uid.strip() not in config.comptes():
        return Contexte(None, False, st.session_state)
    uid = uid.strip()
    return Contexte(uid, config.est_demo(uid), st.session_state)


def definir_contexte(fournisseur) -> None:
    """Tests : `fournisseur()` renvoie un Contexte (compte, démo ?, état de session)."""
    _etat["contexte"] = fournisseur


def _ctx() -> Contexte:
    return (_etat["contexte"] or _contexte_streamlit)()


def utilisateur_actif() -> str:
    """Identifiant authentifié. Échec fermé : jamais de requête sans compte."""
    uid = _ctx().uid
    if not uid:
        raise PermissionError("Connexion requise pour accéder aux données Supabase.")
    return uid


def est_demo() -> bool:
    return _ctx().demo


# --------------------------------------------------------------------------------------------------
# Cache mémoire par (compte, table)
# --------------------------------------------------------------------------------------------------
_cache: dict = {}            # (uid, table) -> (version, horodatage, DataFrame)
_versions: dict = {}         # (uid, table) -> int
_absents: dict = {}          # nom de table / fonction -> horodatage de la dernière absence constatée
_verrou = threading.RLock()


def reinitialiser_pour_tests() -> None:
    with _verrou:
        _cache.clear()
        _versions.clear()
        _absents.clear()
    _etat["contexte"] = None


def _version(uid: str, table: str) -> int:
    return _versions.get((uid, table), 0)


def invalider(table: str, uid: str | None = None) -> None:
    """Rend obsolète `table` pour UN compte (le compte courant par défaut)."""
    uid = uid or utilisateur_actif()
    with _verrou:
        _versions[(uid, table)] = _version(uid, table) + 1
        _cache.pop((uid, table), None)


def invalider_compte(uid: str | None = None) -> None:
    """Bouton 🔄 : relit les tables du compte courant, sans toucher aux autres comptes."""
    uid = uid or utilisateur_actif()
    with _verrou:
        for t in SCHEMA:
            _versions[(uid, t)] = _version(uid, t) + 1
            _cache.pop((uid, t), None)


def _frais(uid: str, table: str):
    with _verrou:
        e = _cache.get((uid, table))
        if e and e[0] == _version(uid, table) and time.time() - e[1] < config.DB_TTL_S:
            return e[2]
    return None


def _ranger(uid: str, table: str, df: pd.DataFrame, version: int) -> None:
    with _verrou:
        if version == _version(uid, table):  # une écriture entre-temps : on ne remet pas une lecture périmée
            _cache[(uid, table)] = (version, time.time(), df)


def _absent(nom: str) -> bool:
    t = _absents.get(nom)
    return t is not None and time.time() - t < NOUVEL_ESSAI_ABSENT_S


def _est_absence(e: Exception) -> bool:
    m = str(e).lower()
    return any(k in m for k in ("42p01", "pgrst202", "pgrst205", "does not exist", "inexistante",
                                "could not find", "absente"))


def _noter_erreur(quoi: str, e: Exception) -> None:
    """Journalise le TYPE d'erreur seulement (jamais de données ni de secrets)."""
    if _est_absence(e):
        _absents[quoi] = time.time()
        journal.warning("Supabase : %s absent(e) (migration SQL non exécutée ?)", quoi)
    else:
        journal.warning("Supabase : échec sur %s (%s)", quoi, type(e).__name__)


# --------------------------------------------------------------------------------------------------
# Conversions
# --------------------------------------------------------------------------------------------------
def _clean(v):
    """Valeur pandas/numpy -> valeur JSON."""
    if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, dt.date, dt.datetime)):
        return pd.Timestamp(v).date().isoformat()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _typer(table: str, lignes: list[dict]) -> pd.DataFrame:
    """Lignes JSON -> DataFrame aux colonnes métier (jamais `user_id`), dates et nombres typés."""
    df = pd.DataFrame(lignes, columns=SCHEMA[table])
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], format="ISO8601")
    for c in NUMERIQUES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _verifier_table(table: str) -> None:
    if table not in SCHEMA:
        raise KeyError(f"Table inconnue : {table}")


# --------------------------------------------------------------------------------------------------
# Lectures
# --------------------------------------------------------------------------------------------------
def _requete_lecture(table: str, uid: str):
    q = _client().table(table).select(",".join(SCHEMA[table])).eq("user_id", uid)
    dernieres = DERNIERES_LIGNES.get(table)
    if dernieres:
        return q.order("id", desc=True).limit(dernieres), True
    for col in ORDRE.get(table, []):
        q = q.order(col)
    return q, False


def _lire_reseau(table: str, uid: str) -> pd.DataFrame:
    """Lecture paginée (ou bornée aux dernières lignes) des colonnes métier d'un compte."""
    q, borne = _requete_lecture(table, uid)
    if borne:
        lignes = list(reversed(q.execute().data))
    else:
        lignes, debut = [], 0
        while True:
            lot = _requete_lecture(table, uid)[0].range(debut, debut + config.DB_PAGE - 1).execute().data
            lignes += lot
            if len(lot) < config.DB_PAGE:
                break
            debut += config.DB_PAGE
    return _typer(table, lignes)


def lire(table: str) -> pd.DataFrame:
    """Lignes du compte courant (copie : l'appelant peut la modifier sans risque)."""
    _verifier_table(table)
    ctx = _ctx()
    if not ctx.uid:
        raise PermissionError("Connexion requise pour accéder aux données Supabase.")
    if ctx.demo:
        locales = ctx.session.get(CLE_DEMO, {})
        if table in locales:
            return locales[table].copy()
    df = _frais(ctx.uid, table)
    if df is None:
        v = _version(ctx.uid, table)
        try:
            df = _lire_reseau(table, ctx.uid)
        except Exception as e:
            _noter_erreur(table, e)
            raise
        _ranger(ctx.uid, table, df, v)
    return df.copy()


def signature(tables=TABLES_COMPTE) -> tuple:
    """Version des données du compte courant : change à chaque écriture, invalidation ou relecture.

    Sert à mémoïser le contexte portefeuille sans relire ni recopier les tables."""
    ctx = _ctx()
    with _verrou:
        base = tuple((t, _version(ctx.uid, t), (_cache.get((ctx.uid, t)) or (0, 0))[1]) for t in tables)
    return ctx.uid, (ctx.session.get(CLE_DEMO_REV, 0) if ctx.demo else 0), base


def _charger_par_rpc(uid: str, tables: list[str]) -> bool:
    """Un seul aller-retour : la fonction SQL renvoie toutes les tables du compte. False si indisponible."""
    if _absent(RPC_CHARGER):
        return False
    versions = {t: _version(uid, t) for t in tables}
    try:
        res = _client().rpc(RPC_CHARGER, {"p_user": uid}).execute().data
    except Exception as e:
        _noter_erreur(RPC_CHARGER, e)
        return False
    if not isinstance(res, dict):
        return False
    for t in tables:
        if t in res and isinstance(res[t], list):
            lignes = res[t]
            if t in DERNIERES_LIGNES:
                lignes = sorted(lignes, key=lambda l: l.get("id") or 0)[-DERNIERES_LIGNES[t]:]
            _ranger(uid, t, _typer(t, lignes), versions[t])
    return True


def precharger(tables=TABLES_COMPTE) -> None:
    """Réchauffe le cache des tables périmées : 1 aller-retour (RPC) ou lectures parallèles. Ne lève jamais."""
    try:
        uid = utilisateur_actif()
        a_lire = [t for t in tables if t in SCHEMA and _frais(uid, t) is None]
        if not a_lire:
            return
        _client()
        if len(a_lire) > 1 and _charger_par_rpc(uid, a_lire):
            return

        def lire_une(t):
            v = _version(uid, t)
            try:
                _ranger(uid, t, _lire_reseau(t, uid), v)
            except Exception as e:
                _noter_erreur(t, e)

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lire_une, a_lire))
    except Exception as e:
        journal.warning("Préchargement impossible (%s)", type(e).__name__)


# --------------------------------------------------------------------------------------------------
# Écritures (compte courant uniquement ; démo : dans la session)
# --------------------------------------------------------------------------------------------------
def _payload(table: str, rec: dict, uid: str) -> dict:
    p = {k: _clean(v) for k, v in rec.items() if k != "user_id"}
    if table in TABLES_PAR_UTILISATEUR:
        p["user_id"] = uid  # jamais celui d'un formulaire
    return p


def _conflit(table: str, conflit: str) -> str:
    cols = [c.strip() for c in conflit.split(",") if c.strip() and c.strip() != "user_id"]
    return ",".join(["user_id", *cols])


def inserer(table: str, rec: dict) -> dict | None:
    """Insère une ligne sous le compte courant et la renvoie (avec son id)."""
    _verifier_table(table)
    ctx = _ctx()
    uid = utilisateur_actif()
    if ctx.demo:
        return _demo_inserer(ctx, table, [rec])[0]
    res = _client().table(table).insert(_payload(table, rec, uid)).execute()
    invalider(table, uid)
    return {k: v for k, v in res.data[0].items() if k != "user_id"} if res.data else None


def inserer_lot(table: str, recs: list[dict]) -> int:
    """Insère plusieurs lignes en une requête par lot de 500. Retourne le nombre de lignes."""
    _verifier_table(table)
    if not recs:
        return 0
    ctx = _ctx()
    uid = utilisateur_actif()
    if ctx.demo:
        _demo_inserer(ctx, table, recs)
        return len(recs)
    for i in range(0, len(recs), 500):
        _client().table(table).insert([_payload(table, r, uid) for r in recs[i:i + 500]]).execute()
    invalider(table, uid)
    return len(recs)


def modifier(table: str, id_, rec: dict, cle: str = "id") -> None:
    """UPDATE par clé, toujours restreint au compte courant ; le compte d'une ligne ne change jamais."""
    _verifier_table(table)
    ctx = _ctx()
    uid = utilisateur_actif()
    if ctx.demo:
        return _demo_modifier(ctx, table, id_, rec, cle)
    p = _payload(table, rec, uid)
    p.pop("user_id", None)
    _client().table(table).update(p).eq(cle, id_).eq("user_id", uid).execute()
    invalider(table, uid)


def supprimer(table: str, valeur, cle: str = "id") -> None:
    """DELETE toujours restreint au compte courant."""
    supprimer_plusieurs(table, [valeur], cle)


def supprimer_plusieurs(table: str, valeurs, cle: str = "id") -> None:
    _verifier_table(table)
    valeurs = list(valeurs)
    if not valeurs:
        return
    ctx = _ctx()
    uid = utilisateur_actif()
    if ctx.demo:
        return _demo_supprimer(ctx, table, valeurs, cle)
    q = _client().table(table).delete()
    q = q.eq(cle, valeurs[0]) if len(valeurs) == 1 else q.in_(cle, valeurs)
    q.eq("user_id", uid).execute()
    invalider(table, uid)
    for enfant, _ in CASCADES.get(table, ()):
        invalider(enfant, uid)


def upsert(table: str, recs: list[dict], conflit: str) -> None:
    """Upsert sous le compte courant ; la clé de conflit commence toujours par user_id."""
    _verifier_table(table)
    if not recs:
        return
    ctx = _ctx()
    uid = utilisateur_actif()
    if ctx.demo:
        return _demo_upsert(ctx, table, recs, conflit)
    cible = _conflit(table, conflit)
    for i in range(0, len(recs), 500):
        _client().table(table).upsert([_payload(table, r, uid) for r in recs[i:i + 500]], on_conflict=cible).execute()
    invalider(table, uid)


def appliquer_modifs(table: str, avant: pd.DataFrame, apres: pd.DataFrame) -> tuple[int, int, int]:
    """Répercute un st.data_editor : suppressions et ajouts en lot, modifications ligne par ligne
    (chacune restreinte au compte). Retourne (ajoutées, modifiées, supprimées)."""
    cols = [c for c in SCHEMA[table] if c != "id"]
    ids_apres = set(apres["id"].dropna().astype(int))
    a_supprimer = sorted(set(avant["id"].astype(int)) - ids_apres)
    supprimer_plusieurs(table, a_supprimer)
    avant_idx = avant.set_index(avant["id"].astype(int))
    nouveaux, modifies = [], 0
    for _, r in apres.iterrows():
        rec = {c: _clean(r[c]) for c in cols}
        if pd.isna(r["id"]):
            nouveaux.append(rec)
        else:
            i = int(r["id"])
            if {c: _clean(avant_idx.loc[i, c]) for c in cols} != rec:
                modifier(table, i, rec)
                modifies += 1
    inserer_lot(table, nouveaux)
    return len(nouveaux), modifies, len(a_supprimer)


# --------------------------------------------------------------------------------------------------
# Mode démo : copie de la table dans la session au premier changement, jamais d'écriture en base
# --------------------------------------------------------------------------------------------------
def _demo_table(ctx: Contexte, table: str) -> pd.DataFrame:
    locales = ctx.session.setdefault(CLE_DEMO, {})
    if table not in locales:
        df = _frais(ctx.uid, table)
        if df is None:
            df = _lire_reseau(table, ctx.uid)
        locales[table] = df.copy()
    return locales[table]


def _demo_ranger(ctx: Contexte, table: str, df: pd.DataFrame) -> None:
    lignes = [{k: _clean(v) if k in ("date",) else v for k, v in r.items()} for r in df.to_dict("records")]
    ctx.session.setdefault(CLE_DEMO, {})[table] = _typer(table, lignes)
    ctx.session[CLE_DEMO_REV] = ctx.session.get(CLE_DEMO_REV, 0) + 1


def _maintenant_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _demo_inserer(ctx: Contexte, table: str, recs: list[dict]) -> list[dict]:
    df = _demo_table(ctx, table)
    sorties = []
    prochain = int(pd.to_numeric(df["id"], errors="coerce").max()) + 1 if "id" in df and len(df) else 1
    lignes = df.to_dict("records")
    for rec in recs:
        r = {k: _clean(v) for k, v in rec.items() if k in SCHEMA[table]}
        if "id" in SCHEMA[table]:
            r["id"], prochain = prochain, prochain + 1
        for c in ("cree_le", "ajoute_le"):
            if c in SCHEMA[table]:
                r.setdefault(c, _maintenant_iso())
        lignes.append(r)
        sorties.append(dict(r))
    _demo_ranger(ctx, table, pd.DataFrame(lignes, columns=SCHEMA[table]))
    return sorties


def _demo_modifier(ctx: Contexte, table: str, id_, rec: dict, cle: str) -> None:
    df = _demo_table(ctx, table).copy()
    masque = df[cle].astype(str) == str(id_)
    for k, v in rec.items():
        if k in df.columns and k != cle:
            df[k] = df[k].astype(object)
            df.loc[masque, k] = _clean(v)
    _demo_ranger(ctx, table, df)


def _demo_supprimer(ctx: Contexte, table: str, valeurs: list, cle: str) -> None:
    df = _demo_table(ctx, table)
    cibles = {str(v) for v in valeurs}
    masque = df[cle].astype(str).isin(cibles)
    ids = set(df.loc[masque, "id"].astype(str)) if "id" in df else cibles
    _demo_ranger(ctx, table, df[~masque])
    for enfant, col in CASCADES.get(table, ()):
        d = _demo_table(ctx, enfant)
        cle_parent = ids if col == "scenario_id" else cibles
        _demo_ranger(ctx, enfant, d[~d[col].astype(str).isin(cle_parent)])


def _demo_upsert(ctx: Contexte, table: str, recs: list[dict], conflit: str) -> None:
    cles = [c.strip() for c in conflit.split(",") if c.strip() and c.strip() != "user_id"] \
        or list(CLES_NATURELLES.get(table, ()))
    df = _demo_table(ctx, table)
    lignes = df.to_dict("records")
    for rec in recs:
        r = {k: _clean(v) for k, v in rec.items() if k in SCHEMA[table]}
        ex = next((l for l in lignes if all(str(_clean(l.get(c))) == str(r.get(c)) for c in cles)), None)
        if ex is None:
            lignes.append(r)
        else:
            ex.update(r)
    _demo_ranger(ctx, table, pd.DataFrame(lignes, columns=SCHEMA[table]))


# --------------------------------------------------------------------------------------------------
# Comptages (quotas) : `count` filtré par date, jamais de relecture des tables
# --------------------------------------------------------------------------------------------------
def compter(table: str, depuis_iso: str, filtres: dict | None = None, colonne: str = "cree_le") -> int:
    """Nombre de lignes du compte courant depuis `depuis_iso`. Lève si la table est absente."""
    uid = utilisateur_actif()
    return _compter(table, depuis_iso, filtres, colonne, uid)


def compter_global(table: str, depuis_iso: str, filtres: dict | None = None, colonne: str = "cree_le") -> int:
    """Nombre de lignes TOUS COMPTES confondus (plafond IA global) : un nombre, jamais une ligne."""
    return _compter(table, depuis_iso, filtres, colonne, None)


def _compter(table, depuis_iso, filtres, colonne, uid) -> int:
    if _absent(table):
        raise RuntimeError(f"table {table} absente")
    q = _client().table(table).select("id", count="exact", head=True).gte(colonne, depuis_iso)
    if uid:
        q = q.eq("user_id", uid)
    for k, v in (filtres or {}).items():
        q = q.eq(k, v)
    try:
        return int(q.execute().count or 0)
    except Exception as e:
        _noter_erreur(table, e)
        raise


def table_disponible(table: str) -> bool:
    return not _absent(table)


# --------------------------------------------------------------------------------------------------
# Cache marché partagé (table publique `marche_cache` : aucune donnée de compte)
# --------------------------------------------------------------------------------------------------
def marche_lire(cles: list[str]) -> dict:
    """{cle: (valeur, horodatage epoch)} ; {} si la table n'existe pas encore (repli mémoire)."""
    if not cles or _absent("marche_cache"):
        return {}
    try:
        lignes = _client().table("marche_cache").select("cle,valeur,maj").in_("cle", list(cles)).execute().data
    except Exception as e:
        _noter_erreur("marche_cache", e)
        return {}
    sortie = {}
    for l in lignes or []:
        try:
            sortie[l["cle"]] = (l["valeur"], pd.Timestamp(l["maj"]).timestamp())
        except Exception:
            continue
    return sortie


def marche_ecrire(lignes: list[dict]) -> None:
    """Upsert de {cle, categorie, valeur, maj} ; silencieux si la table est absente."""
    if not lignes or _absent("marche_cache"):
        return
    try:
        _client().table("marche_cache").upsert(lignes, on_conflict="cle").execute()
    except Exception as e:
        _noter_erreur("marche_cache", e)


# --------------------------------------------------------------------------------------------------
# Partage de la performance (SEULE exception au cloisonnement des données de compte)
# --------------------------------------------------------------------------------------------------
PSEUDO_MAX = 30


def enregistrer_partage(partage: bool, pseudo: str) -> None:
    """Enregistre le choix de partage du compte courant (décoché par défaut). Interdit à la démo."""
    if est_demo():
        raise PermissionError("Le compte demo ne partage pas sa performance.")
    pseudo = " ".join(str(pseudo or "").split())[:PSEUDO_MAX]
    upsert("partage", [{"partage": bool(partage), "pseudo": pseudo or None}], "user_id")


def partages_bruts(eligibles: tuple) -> tuple[list[dict], pd.DataFrame]:
    """(choix [{user_id, pseudo}], points [user_id, date, valeur, apports]) des comptes `eligibles` ayant
    coché « partager ». Ces lignes ne sortent que vers pea.services.partage, qui n'en garde que l'indice TWR."""
    vide = pd.DataFrame(columns=["user_id", "date", "valeur", "apports"])
    if not eligibles:
        return [], vide
    opt = _client().table("partage").select("user_id,pseudo").eq("partage", True) \
        .in_("user_id", list(eligibles)).order("user_id").execute().data
    if not opt:
        return [], vide
    ids, lignes, debut = [o["user_id"] for o in opt], [], 0
    while True:
        lot = _client().table("snapshots").select("user_id,date,valeur,apports").in_("user_id", ids) \
            .order("user_id").order("date").range(debut, debut + config.DB_PAGE - 1).execute().data
        lignes += lot
        if len(lot) < config.DB_PAGE:
            break
        debut += config.DB_PAGE
    df = pd.DataFrame(lignes, columns=["user_id", "date", "valeur", "apports"])
    df["date"] = pd.to_datetime(df["date"], format="ISO8601")
    for c in ("valeur", "apports"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return opt, df
