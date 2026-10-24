"""Constantes de l'application (source unique) et lecture typée des secrets.

Les valeurs métier (quotas, seuils, durées de cache, indices de référence) sont ici ; aucun secret n'est
écrit dans le dépôt : tout passe par `st.secrets` (voir secrets.toml.example).
"""
from __future__ import annotations

import pathlib
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

RACINE = pathlib.Path(__file__).resolve().parent.parent
PARIS = ZoneInfo("Europe/Paris")

# --- Session ----------------------------------------------------------------------------------------
# Toute clé de session propre à un compte (widgets, brouillons, conversations, contexte) commence par ce
# préfixe : la déconnexion la purge en une fois (voir pea.ui.etat et pea.services.auth).
PREFIXE_COMPTE = "c."


def maintenant() -> datetime:
    return datetime.now(PARIS)

# --- Règles d'affichage ---------------------------------------------------------------------------
SEUIL_CONCENTRATION = 25.0  # % des titres au-delà duquel on alerte
BENCHMARKS = {"MSCI World (CW8)": "CW8.PA", "CAC 40": "^FCHI", "Euro Stoxx 50": "^STOXX50E"}

# --- IA (Gemini) : quotas (palier gratuit). Les vraies limites sont celles de Google : projet + modèle. -------
MODELE_GEMINI_DEFAUT = "gemini-3.6-flash"  # surchargeable par le secret GEMINI_MODEL
MAX_APPELS_PAR_JOUR = 30        # analyses de portefeuille / de scénario, par jour et par compte
MAX_CHAT_PAR_JOUR = 100         # questions au chatbot, par jour et par compte
MAX_SUGGESTIONS_PAR_JOUR = 30   # suggestions de concurrent « à la demande », par jour et par compte
MAX_IMPORTS_PAR_JOUR = 30       # lectures de captures du courtier, par jour et par compte
QUOTA_IA_GLOBAL_PAR_JOUR = 300  # plafond d'appels IA par jour, tous comptes confondus (secret QUOTA_IA_GLOBAL_PAR_JOUR)
IA_MAX_PAR_MINUTE_COMPTE = 6    # limiteur de débit par compte
IA_MAX_PAR_MINUTE_GLOBAL = 20   # limiteur de débit sur la clé Gemini partagée
IA_APPELS_SIMULTANES = 3        # sémaphore : appels Gemini en parallèle, tous comptes confondus

# --- Base de données ------------------------------------------------------------------------------------------
DB_TTL_S = 120                  # durée de validité d'une lecture de table en mémoire
DB_PAGE = 1000                  # limite par requête côté Supabase
SNAPSHOT_INTERVALLE_S = 15 * 60  # écriture du point du jour de `snapshots` : au plus 1 fois par quart d'heure et par compte
PRIX_ECRITURE_INTERVALLE_S = 30 * 60  # écriture de tickers.dernier_prix : au plus 1 fois par 30 min et par compte

# --- Marché (Yahoo Finance) : données publiques, partagées entre comptes ---------------------------------------------
TTL_COURS_S, TTL_FONDS_S, TTL_OHLC_S = 300, 6 * 3600, 3600
TTL_ECHEC_COURS_S, TTL_ECHEC_FONDS_S, TTL_ECHEC_OHLC_S = 60, 300, 300  # cache négatif
TTL_HISTORIQUE_S, TTL_ECHEC_HISTORIQUE_S = 3600, 300
ACTUALISER_AGE_MIN_S = 60       # le bouton 🔄 ne relance Yahoo que si le cours en cache a plus de 60 s
ATTENTE_PREMIER_AFFICHAGE_S = 4  # attente maximale (arrière-plan) des cours avant d'afficher les derniers connus
RECUL_429_INITIAL_S, RECUL_429_MAX_S = 60, 900  # recul exponentiel après une limitation Yahoo

# --- Authentification (mots de passe des secrets Streamlit) -----------------------------------------------------------
CONNEXION_DEMO_AUTO = True      # ouverture directe sur la démo (lecture seule en base) ; secret AUTO_CONNEXION_DEMO
MAX_ECHECS_SESSION = 8          # essais ratés avant blocage d'une session pour un identifiant
FENETRE_ECHECS_S = 15 * 60

_surcharge: dict | None = None  # tests : remplace st.secrets


def definir_secrets_pour_tests(valeurs: dict | None) -> None:
    global _surcharge
    _surcharge = valeurs


def secret(nom: str, defaut=None):
    """Lit un secret global (ex. GEMINI_API_KEY) ; `defaut` si absent ou si les secrets sont illisibles."""
    if _surcharge is not None:
        return _surcharge.get(nom, defaut)
    try:
        import streamlit as st
        v = st.secrets.get(nom)
        return defaut if v is None else v
    except Exception:
        return defaut


def secret_bool(nom: str, defaut: bool) -> bool:
    v = secret(nom)
    if v is None:
        return defaut
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "vrai", "oui", "yes", "on"}
    return bool(v)


def secret_entier(nom: str, defaut: int) -> int:
    try:
        return int(secret(nom, defaut))
    except (TypeError, ValueError):
        return defaut


def modele_gemini() -> str:
    return str(secret("GEMINI_MODEL") or MODELE_GEMINI_DEFAUT)


def cle_gemini() -> str | None:
    return secret("GEMINI_API_KEY") or None


def quota_ia_global() -> int:
    return secret_entier("QUOTA_IA_GLOBAL_PAR_JOUR", QUOTA_IA_GLOBAL_PAR_JOUR)


def debug_perf() -> bool:
    return secret_bool("DEBUG_PERF", False)


def comptes() -> dict[str, dict]:
    """Comptes lus dans [users.*] : {identifiant: {password, demo}}.

    Le compte `demo` existe toujours (mot de passe public « demo »). L'ancien secret APP_PASSWORD reste lu
    comme mot de passe de `theo` si [users.theo] est absent.
    """
    cfg: dict[str, dict] = {"demo": {"password": "demo", "demo": True}}
    brut = secret("users", {})
    if isinstance(brut, Mapping):
        for identifiant, d in brut.items():
            if not isinstance(d, Mapping):
                continue
            mdp = d.get("password")
            if mdp is None:
                continue
            cfg[str(identifiant)] = {"password": str(mdp),
                                     "demo": bool(d.get("demo", str(identifiant) == "demo"))}
    ancien = secret("APP_PASSWORD")
    if ancien and "theo" not in cfg:
        cfg["theo"] = {"password": str(ancien), "demo": False}
    return cfg


def est_demo(uid: str | None) -> bool:
    if not uid:
        return False
    return bool(comptes().get(uid, {}).get("demo", uid == "demo"))
