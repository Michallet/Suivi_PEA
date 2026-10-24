"""Contexte portefeuille : données, cours, positions, synthèse et fondamentaux d'UN compte.

Construit une fois par rerun et passé explicitement aux pages (plus aucune variable globale).
Mémoïsé dans la session par (compte, signature des données, horodatage marché, fondamentaux connus) :
un rerun à caches chauds ne relit ni ne recalcule rien.

Premier affichage avec les derniers cours connus ; le rafraîchissement Yahoo se fait en arrière-plan.
Statuts des cours : `live` (cache marché frais), `obsolète` (dernier cours connu), `estimé` (prix de revient).
"""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field

import pandas as pd

from pea import config
from pea.data import marche
from pea.data import repo
from pea.data.schema import SCHEMA, TABLES_COMPTE
from pea.domain import calculs as C
from pea.services import suivi

CLE_MEMO = config.PREFIXE_COMPTE + "portefeuille"
CLE_ACTUALISER = config.PREFIXE_COMPTE + "actualiser_cours"
TABLES_SECONDAIRES = ("watchlist", "scenarios", "scenario_trades", "analyses_ia", "analyses_scen")
COLS_TICKERS = ["ticker", "nom", "dernier_prix", "dernier_prix_at",
                "concurrent_isin", "concurrent_ticker", "concurrent_nom"]
COLS_COURS = ["isin", "ticker", "nom", "prix", "prev_close", "statut"]


class BaseIndisponible(Exception):
    """Lecture des tables principales impossible (secrets, schéma ou réseau)."""


@dataclass
class Portefeuille:
    uid: str
    demo: bool
    trans: pd.DataFrame
    div: pd.DataFrame
    vers: pd.DataFrame
    snaps: pd.DataFrame
    wl: pd.DataFrame
    scen: pd.DataFrame
    scen_tr: pd.DataFrame
    analyses: pd.DataFrame
    analyses_scen: pd.DataFrame
    tmap: pd.DataFrame                    # tickers indexés par ISIN
    sect_dict: dict
    positions: pd.DataFrame               # positions brutes (calculs.calcul_positions)
    ventes: pd.DataFrame
    flux: pd.DataFrame
    div_par_isin: pd.Series
    cours: pd.DataFrame                   # COLS_COURS, une ligne par ISIN connu
    horodatage: object
    tickers: tuple
    fonds: dict
    pos: pd.DataFrame = field(default=None)   # positions enrichies (cours, poids, secteur)
    synthese: dict = field(default_factory=dict)
    maj_prix: list = field(default_factory=list)
    erreur_journal: str | None = None
    tables_manquantes: list = field(default_factory=list)

    # ---------------------------------------------------------------------------------------------
    # Lectures dérivées
    # ---------------------------------------------------------------------------------------------
    @property
    def manquants(self) -> list[str]:
        return sorted(set(self.trans["isin"]) - set(self.tmap.index))

    @property
    def cash(self) -> float:
        return self.synthese["cash"]

    def nom_de(self, isin: str) -> str:
        n = self.tmap.loc[isin, "nom"] if isin in self.tmap.index else None
        return isin if n is None or pd.isna(n) else n

    def ticker_de(self, isin: str):
        return self.tmap.loc[isin, "ticker"] if isin in self.tmap.index else None

    def secteur_de(self, isin: str, ticker) -> str:
        return self.sect_dict.get(isin) or self.fonds.get(ticker, {}).get("secteur_yahoo") or "Inconnu"

    def fondamentaux(self, ticker) -> dict:
        return self.fonds.get(ticker, {}) if ticker else {}

    def per_par_isin(self, p: pd.DataFrame | None = None) -> dict:
        """{ISIN: PER} des lignes de `p` (positions actuelles par défaut) : source unique pour l'IA."""
        p = self.pos if p is None else p
        return {i: self.fonds.get(t, {}).get("per") for i, t in zip(p["isin"], p["ticker"])}

    def enrichir(self, pos_brutes: pd.DataFrame) -> pd.DataFrame:
        """Positions + cours, poids, dividendes, secteur (colonnes présentes même sans aucune ligne)."""
        p = C.enrichir_positions(pos_brutes, self.cours, self.div_par_isin)
        p["secteur"] = [self.secteur_de(i, t) for i, t in zip(p["isin"], p["ticker"])]
        return p

    def prix_courant(self, isin: str):
        r = self.cours[self.cours["isin"] == isin]
        return None if r.empty or pd.isna(r.iloc[0]["prix"]) else float(r.iloc[0]["prix"])

    def cours_et_veille(self, isin: str):
        c = self.cours[self.cours["isin"] == isin]
        return (None, None) if c.empty else (c.iloc[0]["prix"], c.iloc[0]["prev_close"])

    def ordre_isins(self) -> list[str]:
        """ISIN proposés dans les formulaires : détenus, puis watchlist, puis les autres connus."""
        detenus = self.positions["isin"].tolist()
        suivis = [i for i in self.wl["isin"] if i not in detenus]
        return detenus + suivis + [i for i in self.tmap.index if i not in detenus and i not in suivis]

    def concurrent_de(self, isin: str) -> dict | None:
        if isin not in self.tmap.index or "concurrent_ticker" not in self.tmap.columns:
            return None
        r = self.tmap.loc[isin]
        texte = lambda x: x.strip() if isinstance(x, str) and x.strip() else ""
        ticker = texte(r.get("concurrent_ticker"))
        if not ticker:
            return None
        return {"isin": texte(r.get("concurrent_isin")), "ticker": ticker,
                "nom": texte(r.get("concurrent_nom")) or ticker}

    def derniere_analyse(self, scenario_id=None):
        """Dernière analyse IA du portefeuille (ou du scénario `scenario_id`), sinon None."""
        df = self.analyses if scenario_id is None else \
            self.analyses_scen[self.analyses_scen["scenario_id"] == scenario_id]
        return None if df.empty else df.sort_values("id").iloc[-1]

    def nom_scenario(self, sid) -> str:
        n = self.scen.loc[self.scen["id"].astype(int) == int(sid), "nom"]
        return str(n.iloc[0]) if len(n) else str(sid)

    def scenario(self, sid: int):
        """(opérations fictives, versement, positions brutes, cash) du scénario. Lève ValueError."""
        sim = self.scen_tr[self.scen_tr["scenario_id"] == sid]
        versement = float(self.scen.loc[self.scen["id"] == sid, "versement"].iloc[0])
        brutes, _, cash_p = C.appliquer_scenario(self.trans, sim, self.div, self.vers, versement,
                                                 config.maintenant().date())
        return sim, versement, brutes, cash_p

    def memoriser_suivi(self) -> None:
        """Derniers cours et point de courbe du jour, en FIN de script (après l'affichage)."""
        estimes = (not self.pos.empty) and (self.pos["statut"] == "estimé").any()
        jour = config.maintenant()
        suivi.memoriser(self.maj_prix, self.snaps, pd.Timestamp(jour.date()), self.synthese["valeur_totale"],
                        self.synthese["apports"],
                        autorise_snapshot=not self.trans.empty and not estimes and jour.weekday() < 5)


# --------------------------------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------------------------------
def _lire_secondaire(table: str, manquantes: list) -> pd.DataFrame:
    """Tables secondaires : si l'une manque en base, l'app reste utilisable (avertissement affiché)."""
    try:
        return repo.lire(table)
    except Exception:
        manquantes.append(table)
        return pd.DataFrame(columns=SCHEMA[table])


def _cours(tmap: pd.DataFrame, isins: list[str], actualiser: bool):
    """Cours (live > dernier connu > prix de revient) pour une liste d'ISIN."""
    connus = [i for i in isins if i in tmap.index]
    tickers = tuple(dict.fromkeys(tmap.loc[i, "ticker"] for i in connus))
    if actualiser:
        marche.actualiser_cours(tickers)
    marche.prechauffer(tickers)  # cours + fondamentaux partagés (marche_cache) en une seule requête
    cours, horo = marche.cours_batch(tickers) if tickers else ({}, config.maintenant())
    nom = lambda i: (lambda n: i if n is None or pd.isna(n) else n)(tmap.loc[i, "nom"])
    lignes, maj = [], []
    for isin in isins:
        connu = isin in tmap.index
        ticker = tmap.loc[isin, "ticker"] if connu else None
        dernier = tmap.loc[isin, "dernier_prix"] if connu else None
        dernier = None if dernier is None or pd.isna(dernier) else float(dernier)
        m = cours.get(ticker, {})
        prix, prev, statut = m.get("prix"), m.get("prev"), "live"
        if prix is not None and m.get("age_s", 0) > 2 * config.TTL_COURS_S:
            prev, statut = None, "obsolète"  # Yahoo injoignable : dernier cours connu du cache partagé
        elif prix is None:
            prix, statut = dernier, ("obsolète" if dernier else "estimé")
        if statut == "live" and connu and (dernier is None or abs(dernier - prix) > 1e-9):
            maj.append({"isin": isin, "ticker": ticker, "nom": nom(isin),
                        "dernier_prix": prix, "dernier_prix_at": config.maintenant().isoformat()})
        lignes.append({"isin": isin, "ticker": ticker, "nom": nom(isin) if connu else None,
                       "prix": prix, "prev_close": prev, "statut": statut})
    return pd.DataFrame(lignes, columns=COLS_COURS), maj, horo, tickers


def construire(session: MutableMapping, actualiser: bool = False, jalon=lambda nom: None) -> Portefeuille:
    """Contexte du compte courant. Lève BaseIndisponible si les tables principales sont illisibles."""
    repo.precharger(TABLES_COMPTE)  # un aller-retour (fonction SQL) ou lectures parallèles ; rien si frais
    signature = repo.signature(TABLES_COMPTE)
    memo = session.get(CLE_MEMO)
    if memo is not None and memo[0] == signature and not actualiser:
        pf: Portefeuille = memo[1]
        # Cours : on redemande le marché (cache mémoire, sans réseau) pour suivre son rafraîchissement.
        cours, maj, horo, tickers = _cours(pf.tmap, list(pf.cours["isin"]), False)
        fonds = marche.fondamentaux_batch(tickers) if tickers else {}
        if (horo, tuple(sorted(fonds))) == memo[2]:
            pf.maj_prix = []  # déjà transmis au premier passage
            jalon("contexte (mémo)")
            return pf
    try:
        trans, div, vers = repo.lire("transactions"), repo.lire("dividendes"), repo.lire("versements")
        tick, sect, snaps = repo.lire("tickers"), repo.lire("secteurs"), repo.lire("snapshots")
    except Exception as e:
        raise BaseIndisponible(type(e).__name__) from e
    manquantes: list = []
    wl, scen, scen_tr, analyses, analyses_scen = (_lire_secondaire(t, manquantes) for t in TABLES_SECONDAIRES)
    jalon("base")

    tmap = tick.set_index("isin") if not tick.empty else pd.DataFrame(columns=COLS_TICKERS)
    erreur = None
    try:
        positions, ventes = C.calcul_positions(trans)
    except ValueError as e:
        erreur = str(e)
        positions, ventes = C.calcul_positions(trans.iloc[0:0])
    isins = list(dict.fromkeys(positions["isin"].tolist() + wl["isin"].tolist() + scen_tr["isin"].tolist()))
    cours, maj, horo, tickers = _cours(tmap, isins, actualiser)
    jalon("cours")
    fonds = marche.fondamentaux_batch(tickers) if tickers else {}
    jalon("fondamentaux")

    pf = Portefeuille(
        uid=repo.utilisateur_actif(), demo=repo.est_demo(), trans=trans, div=div, vers=vers, snaps=snaps,
        wl=wl, scen=scen, scen_tr=scen_tr, analyses=analyses, analyses_scen=analyses_scen, tmap=tmap,
        sect_dict=dict(zip(sect["isin"], sect["secteur"])), positions=positions, ventes=ventes,
        flux=C.flux_tresorerie(trans, div, vers), div_par_isin=div.groupby("isin")["montant"].sum(),
        cours=cours, horodatage=horo, tickers=tickers, fonds=fonds, maj_prix=maj,
        erreur_journal=erreur, tables_manquantes=manquantes)
    pf.pos = pf.enrichir(positions)
    pf.synthese = C.synthese(pf.pos, pf.flux, vers)
    jalon("calculs")
    session[CLE_MEMO] = (signature, pf, (horo, tuple(sorted(fonds))))
    return pf
