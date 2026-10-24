"""Données de marché (Yahoo Finance via yfinance) : publiques, partagées entre tous les comptes.

* Cache L1 en mémoire (processus) puis L2 dans la table publique Supabase `marche_cache` (survit à la mise en
  veille de Streamlit Cloud) ; sans la migration SQL, L1 seul (repli silencieux).
* Cours : UN téléchargement groupé (`yf.download`) pour tous les titres périmés, en arrière-plan. La page
  attend au plus quelques secondes puis affiche le dernier cours connu ; `rafraichissement_en_cours()` dit
  s'il faut relancer l'affichage plus tard.
* Cache négatif (un échec est mémorisé 1 à 5 min) et recul exponentiel après une limitation (429).
* Les durées de vie sont dans pea.config (cours 5 min, fondamentaux 6 h, bougies 1 h).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance

from pea import config
from pea.data import repo
from pea.domain.nombres import positif

journal = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
SUFFIXES_EUR = (".PA", ".AS", ".BR", ".MI", ".DE", ".MC", ".LS", ".HE", ".IR", ".VI")  # places en €

yf = yfinance  # remplaçable par un faux (definir_yahoo)

# catégorie -> (durée de validité, durée d'un échec, partagé en L2 ?)
DUREES = {
    "cours": (config.TTL_COURS_S, config.TTL_ECHEC_COURS_S, True),
    "fonds": (config.TTL_FONDS_S, config.TTL_ECHEC_FONDS_S, True),
    "ohlc": (config.TTL_OHLC_S, config.TTL_ECHEC_OHLC_S, False),
    "hist": (config.TTL_HISTORIQUE_S, config.TTL_ECHEC_HISTORIQUE_S, False),
}

_l1: dict = {c: {} for c in DUREES}   # catégorie -> {clé: (valeur, horodatage, ok)}
_l2_vu: dict = {}                     # (catégorie, clé) -> dernière consultation de L2 sans succès
_en_cours: dict = {}                  # (catégorie, clé) -> Future
_recul = {"jusqu": 0.0, "pas": float(config.RECUL_429_INITIAL_S)}
_verrou = threading.RLock()
_executeur = ThreadPoolExecutor(max_workers=2, thread_name_prefix="marche")
compteurs = {"telechargements_groupes": 0, "appels_unitaires": 0}


def definir_yahoo(module) -> None:
    global yf
    yf = module


def reinitialiser_pour_tests() -> None:
    with _verrou:
        for c in _l1.values():
            c.clear()
        _l2_vu.clear()
        _en_cours.clear()
        _recul.update(jusqu=0.0, pas=float(config.RECUL_429_INITIAL_S))
        compteurs.update(telechargements_groupes=0, appels_unitaires=0)


# --------------------------------------------------------------------------------------------------
# Recul après une limitation de Yahoo (429)
# --------------------------------------------------------------------------------------------------
def _est_limitation(e: Exception) -> bool:
    m = f"{type(e).__name__} {e}".lower()
    return "ratelimit" in m or "too many requests" in m or "429" in m


def _noter_limitation() -> None:
    with _verrou:
        _recul["jusqu"] = time.time() + _recul["pas"]
        journal.warning("Yahoo : limitation (429), pause de %.0f s", _recul["pas"])
        _recul["pas"] = min(_recul["pas"] * 2, config.RECUL_429_MAX_S)


def _noter_succes() -> None:
    with _verrou:
        _recul["pas"] = float(config.RECUL_429_INITIAL_S)


def en_recul() -> bool:
    return time.time() < _recul["jusqu"]


# --------------------------------------------------------------------------------------------------
# Moteur commun : L1 -> L2 -> rafraîchissement (arrière-plan, dédoublonné)
# --------------------------------------------------------------------------------------------------
def _frais(categorie: str, e) -> bool:
    ttl, ttl_echec, _ = DUREES[categorie]
    return e is not None and time.time() - e[1] < (ttl if e[2] else ttl_echec)


def _depuis_l2(categorie: str, cles: list) -> None:
    """Complète L1 avec les valeurs partagées en base (une seule requête), si elles sont plus récentes."""
    if not DUREES[categorie][2]:
        return
    maintenant = time.time()
    with _verrou:
        a_voir = [c for c in cles if maintenant - _l2_vu.get((categorie, c), 0) > DUREES[categorie][1]]
        for c in a_voir:
            _l2_vu[(categorie, c)] = maintenant
    if not a_voir:
        return
    trouves = repo.marche_lire([f"{categorie}:{c}" for c in a_voir])
    with _verrou:
        for cle_l2, (valeur, horo) in trouves.items():
            c = cle_l2.split(":", 1)[1]
            e = _l1[categorie].get(c)
            if e is None or horo > e[1]:
                _l1[categorie][c] = (valeur, horo, True)


def _vers_l2(categorie: str, resultats: dict) -> None:
    if not DUREES[categorie][2]:
        return
    maj = datetime.now(PARIS).isoformat()
    repo.marche_ecrire([{"cle": f"{categorie}:{c}", "categorie": categorie, "valeur": v, "maj": maj}
                        for c, (v, ok) in resultats.items() if ok])


def _tache(categorie: str, cles: list, fonction) -> None:
    """Exécutée en arrière-plan : aucune fonction Streamlit ici."""
    try:
        if en_recul():
            return
        try:
            resultats = fonction(cles)
            _noter_succes()
        except Exception as e:
            if _est_limitation(e):
                _noter_limitation()
                return  # on garde les anciennes valeurs, sans cache négatif
            journal.warning("Yahoo : échec %s (%s)", categorie, type(e).__name__)
            resultats = {c: (None, False) for c in cles}
        maintenant = time.time()
        with _verrou:
            for c in cles:
                v, ok = resultats.get(c, (None, False))
                ancien = _l1[categorie].get(c)
                if ok or ancien is None or not ancien[2]:
                    _l1[categorie][c] = (v, maintenant, ok)
                else:  # échec : on garde la dernière bonne valeur, on la considère encore périmée
                    _l1[categorie][c] = (ancien[0], ancien[1], True)
                    _l1[categorie][f"!{c}"] = (None, maintenant, False)
        try:
            _vers_l2(categorie, {c: r for c, r in resultats.items() if r[1]})
        except Exception as e:
            journal.warning("marche_cache : écriture impossible (%s)", type(e).__name__)
    finally:
        with _verrou:
            for c in cles:
                _en_cours.pop((categorie, c), None)


def _a_rafraichir(categorie: str, c: str) -> bool:
    e = _l1[categorie].get(c)
    if _frais(categorie, e):
        return False
    echec = _l1[categorie].get(f"!{c}")  # cache négatif d'un rafraîchissement raté
    return not _frais(categorie, (None, echec[1], False) if echec else None)


def _obtenir(categorie: str, cles, fonction, attente: float | None) -> dict:
    """{clé: (valeur, horodatage)} des valeurs connues (fraîches ou non), après au plus `attente` s."""
    cles = list(dict.fromkeys(c for c in cles if c))
    if not cles:
        return {}
    with _verrou:
        perimes = [c for c in cles if _a_rafraichir(categorie, c)]
    if perimes:
        _depuis_l2(categorie, perimes)
    futurs = []
    with _verrou:
        perimes = [c for c in cles if _a_rafraichir(categorie, c)]
        nouveaux = [c for c in perimes if (categorie, c) not in _en_cours]
        if nouveaux and not en_recul():
            f = _executeur.submit(_tache, categorie, nouveaux, fonction)
            for c in nouveaux:
                _en_cours[(categorie, c)] = f
        futurs = list({id(_en_cours[(categorie, c)]): _en_cours[(categorie, c)]
                       for c in perimes if (categorie, c) in _en_cours}.values())
    if futurs and (attente is None or attente > 0):
        wait(futurs, timeout=attente)
    with _verrou:
        return {c: (e[0], e[1]) for c in cles if (e := _l1[categorie].get(c)) is not None and e[2]}


def prechauffer(tickers) -> None:
    """Lit en UNE requête les cours et fondamentaux partagés (L2) des titres absents ou périmés en L1."""
    with _verrou:
        manquants = {cat: [t for t in dict.fromkeys(tickers) if t and _a_rafraichir(cat, t)] for cat in ("cours", "fonds")}
    cles = [(cat, t) for cat, ts in manquants.items() for t in ts]
    if not cles:
        return
    maintenant = time.time()
    with _verrou:
        cles = [(cat, t) for cat, t in cles if maintenant - _l2_vu.get((cat, t), 0) > DUREES[cat][1]]
        for c in cles:
            _l2_vu[c] = maintenant
    trouves = repo.marche_lire([f"{cat}:{t}" for cat, t in cles])
    with _verrou:
        for cle_l2, (valeur, horo) in trouves.items():
            cat, t = cle_l2.split(":", 1)
            e = _l1[cat].get(t)
            if e is None or horo > e[1]:
                _l1[cat][t] = (valeur, horo, True)


def rafraichissement_en_cours() -> bool:
    with _verrou:
        return any(not f.done() for f in _en_cours.values())


# --------------------------------------------------------------------------------------------------
# Cours (téléchargement groupé)
# --------------------------------------------------------------------------------------------------
def _serie(df: pd.DataFrame, ticker: str, champ: str) -> pd.Series | None:
    """Colonne d'un téléchargement groupé, quel que soit l'ordre des niveaux (ticker, champ)."""
    if df is None or df.empty:
        return None
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        for cle in ((ticker, champ), (champ, ticker)):
            if cle in cols:
                return df[cle].dropna()
        return None
    return df[champ].dropna() if champ in cols else None


def lire_cours(ticker: str) -> dict:
    """Dernier cours d'UN titre (fast_info, repli historique). Valeurs None en cas d'échec (jamais 0)."""
    compteurs["appels_unitaires"] += 1
    out = {"prix": None, "prev": None, "devise": None}
    try:
        fi = yf.Ticker(ticker).fast_info
        out["prix"] = positif(getattr(fi, "last_price", None))
        out["prev"] = positif(getattr(fi, "previous_close", None))
        out["devise"] = getattr(fi, "currency", None)
    except Exception as e:
        if _est_limitation(e):
            raise
    if out["prix"] is None:
        try:
            h = yf.Ticker(ticker).history(period="5d")["Close"].dropna()
            if len(h) >= 1:
                out["prix"] = positif(h.iloc[-1])
            if len(h) >= 2:
                out["prev"] = positif(h.iloc[-2])
        except Exception as e:
            if _est_limitation(e):
                raise
    return out


def _telecharger_cours(tickers: list) -> dict:
    compteurs["telechargements_groupes"] += 1
    df = yf.download(tickers, period="5d", interval="1d", group_by="ticker", auto_adjust=False,
                     progress=False, threads=True)
    sortie = {}
    for t in tickers:
        s = _serie(df, t, "Close")
        prix = positif(s.iloc[-1]) if s is not None and len(s) >= 1 else None
        prev = positif(s.iloc[-2]) if s is not None and len(s) >= 2 else None
        if prix is None:  # absent du lot : un seul essai unitaire pour ce titre
            c = lire_cours(t)
            prix, prev = c["prix"], c["prev"]
        sortie[t] = ({"prix": prix, "prev": prev}, prix is not None)
    return sortie


def cours_batch(tickers, attente: float | None = None) -> tuple[dict, datetime]:
    """({ticker: {prix, prev, age_s}}, horodatage le plus ancien). N'attend Yahoo qu'au plus `attente` s."""
    attente = config.ATTENTE_PREMIER_AFFICHAGE_S if attente is None else attente
    res = _obtenir("cours", tickers, _telecharger_cours, attente)
    maintenant = time.time()
    valeurs = {t: {**v, "age_s": maintenant - h} for t, (v, h) in res.items() if isinstance(v, dict)}
    horo = min((h for _, h in res.values()), default=maintenant)
    return valeurs, datetime.fromtimestamp(horo, PARIS)


def actualiser_cours(tickers) -> None:
    """Bouton 🔄 : seuls les cours plus vieux que ACTUALISER_AGE_MIN_S sont redemandés à Yahoo."""
    with _verrou:
        for t in tickers:
            e = _l1["cours"].get(t)
            if e is not None and time.time() - e[1] > config.ACTUALISER_AGE_MIN_S:
                _l1["cours"][t] = (e[0], 0.0, e[2])  # périmé : rafraîchi au prochain affichage
                _l1["cours"].pop(f"!{t}", None)
                _l2_vu.pop(("cours", t), None)


# --------------------------------------------------------------------------------------------------
# Fondamentaux (un appel `info` par titre, en arrière-plan) et bougies (téléchargement groupé)
# --------------------------------------------------------------------------------------------------
def _lire_info(ticker: str) -> dict:
    """Fondamentaux Yahoo d'un titre (actions et ETF) ; {} en cas d'échec."""
    compteurs["appels_unitaires"] += 1
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        if _est_limitation(e):
            raise
        return {}
    ebitda = info.get("ebitda")
    # EV/EBITDA : uniquement avec la vraie valeur d'entreprise (marketCap/EBITDA serait un autre ratio)
    ev = positif(info.get("enterpriseValue"))
    ev_ebitda = ev / ebitda if ev and ebitda and ebitda > 0 else None
    return {
        "per": positif(info.get("trailingPE")),
        "per_prev": positif(info.get("forwardPE")),
        "ev": ev,
        "ca": info.get("totalRevenue"),
        "capi": info.get("marketCap"),
        "secteur_yahoo": info.get("sector"),  # en anglais : surchargeable dans « Secteurs »
        "industrie": info.get("industry"),
        "devise": info.get("currency"),
        "net_assets": info.get("totalAssets") or info.get("netAssets"),            # ETF
        "expense_ratio": info.get("netExpenseRatio") or info.get("expenseRatio"),  # ETF
        "net_income": info.get("netIncome") or info.get("netIncomeToCommon"),
        "ebitda": ebitda,
        "ev_ebitda": ev_ebitda,
    }


def _telecharger_infos(tickers: list) -> dict:
    with ThreadPoolExecutor(max_workers=4) as ex:
        infos = list(ex.map(_lire_info, tickers))
    return {t: (r, any(v is not None for v in r.values())) for t, r in zip(tickers, infos)}


def fondamentaux_batch(tickers, attente: float | None = None) -> dict:
    """{ticker: fondamentaux} ; un titre sans valeur encore connue n'apparaît pas (affiché « N/A »)."""
    attente = config.ATTENTE_PREMIER_AFFICHAGE_S if attente is None else attente
    return {t: v for t, (v, _) in _obtenir("fonds", tickers, _telecharger_infos, attente).items()}


def _telecharger_ohlc(tickers: list) -> dict:
    compteurs["telechargements_groupes"] += 1
    df = yf.download(tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=True,
                     progress=False, threads=True)
    sortie = {}
    for t in tickers:
        cols = {c: _serie(df, t, c) for c in ("High", "Low", "Close")}
        if any(s is None for s in cols.values()):
            sortie[t] = (None, False)
            continue
        h = pd.DataFrame(cols).dropna()
        if getattr(h.index, "tz", None) is not None:
            h.index = h.index.tz_localize(None)
        sortie[t] = (h if not h.empty else None, len(h) >= 20)
    return sortie


def ohlc_batch(tickers) -> dict:
    """{ticker: DataFrame High/Low/Close ~1 an | None} : un seul téléchargement groupé (demande explicite)."""
    res = _obtenir("ohlc", tickers, _telecharger_ohlc, attente=60)
    valides = [t for t in dict.fromkeys(tickers) if t]
    return {t: res.get(t, (None, 0))[0] for t in valides}


# --------------------------------------------------------------------------------------------------
# Historiques de clôtures (indices de référence, reconstitution)
# --------------------------------------------------------------------------------------------------
def historique_cloture(ticker: str, debut: str) -> pd.Series:
    """Clôtures brutes depuis `debut` (AAAA-MM-JJ). Lève ValueError si indisponible (échec mémorisé 5 min)."""
    cle = f"{ticker}|{debut}"

    def lire(cles):
        sortie = {}
        for c in cles:
            t, d = c.split("|", 1)
            compteurs["appels_unitaires"] += 1
            h = yf.Ticker(t).history(start=d, auto_adjust=False)["Close"].dropna()
            if not h.empty and getattr(h.index, "tz", None) is not None:
                h.index = h.index.tz_localize(None)
            if not h.empty:
                h.index = h.index.normalize()
            sortie[c] = (h if not h.empty else None, not h.empty)
        return sortie

    res = _obtenir("hist", [cle], lire, attente=30)
    if cle not in res or res[cle][0] is None:
        raise ValueError(f"Aucun historique pour {ticker}")
    return res[cle][0]


def historiques_groupes(tickers, debut: str) -> dict:
    """{ticker: Series de clôtures} depuis `debut`, en UN téléchargement (reconstitution de l'historique)."""
    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers or en_recul():
        return {}
    compteurs["telechargements_groupes"] += 1
    try:
        df = yf.download(tickers, start=debut, interval="1d", group_by="ticker", auto_adjust=False,
                         progress=False, threads=True)
    except Exception as e:
        if _est_limitation(e):
            _noter_limitation()
        journal.warning("Yahoo : historiques indisponibles (%s)", type(e).__name__)
        return {}
    sortie = {}
    for t in tickers:
        s = _serie(df, t, "Close")
        if s is not None and not s.empty:
            if getattr(s.index, "tz", None) is not None:
                s.index = s.index.tz_localize(None)
            s.index = s.index.normalize()
            sortie[t] = s
    return sortie


# --------------------------------------------------------------------------------------------------
# Résolution ISIN -> ticker et validation (actions explicites de l'utilisateur)
# --------------------------------------------------------------------------------------------------
def chercher_ticker(isin: str) -> dict | None:
    """Ticker Yahoo d'un ISIN, en privilégiant les places européennes en €."""
    if en_recul():
        return None
    try:
        compteurs["appels_unitaires"] += 1
        quotes = [q for q in yf.Search(isin, max_results=8).quotes if q.get("symbol")]
    except Exception as e:
        if _est_limitation(e):
            _noter_limitation()
        return None
    preferes = [q for q in quotes if q["symbol"].upper().endswith(SUFFIXES_EUR)]
    choix = (preferes or quotes or [None])[0]
    if not choix:
        return None
    return {"ticker": choix["symbol"],
            "nom": choix.get("shortname") or choix.get("longname") or choix["symbol"]}


def valider_ticker(ticker: str, nom: str | None = None) -> dict | None:
    """Vérifie qu'un ticker répond. Retourne {ticker, nom, devise, prix} ou None."""
    try:
        c = lire_cours(ticker)
    except Exception as e:
        if _est_limitation(e):
            _noter_limitation()
        return None
    if c["prix"] is None:
        return None
    if not nom:
        try:
            info = yf.Ticker(ticker).info
            nom = info.get("shortName") or info.get("longName")
        except Exception:
            nom = None
    with _verrou:  # le cours validé sert aussi de cours en cache
        _l1["cours"][ticker] = ({"prix": c["prix"], "prev": c["prev"]}, time.time(), True)
    return {"ticker": ticker, "nom": nom or ticker, "devise": c["devise"], "prix": c["prix"]}
