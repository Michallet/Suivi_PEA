"""Mode démo : portefeuille FICTIF, 100 % en mémoire.

Aucune lecture/écriture en base, aucun appel Yahoo ni Gemini : un visiteur non connecté ne peut
donc jamais atteindre vos données réelles. Les modifications faites en démo (scénarios, etc.)
vivent dans la session du navigateur et disparaissent au rechargement.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

import calculs as C
import llm
from schema import NUMERIQUES, SCHEMA

PARIS = ZoneInfo("Europe/Paris")

# isin: (ticker, nom, secteur perso, cours, veille, PER, CA, capitalisation, secteur Yahoo)
TITRES = {
    "FR001400U5Q4": ("DCAM.PA", "Amundi PEA Monde (MSCI World)", "Monde", 6.31, 6.28, None, None, None, None),
    "FR0000121014": ("MC.PA", "LVMH", "Luxe", 612.4, 608.9, 23.1, 8.0e10, 3.1e11, "Consumer Cyclical"),
    "FR0000120271": ("TTE.PA", "TotalEnergies", "Énergie", 57.9, 58.3, 8.4, 2.1e11, 1.3e11, "Energy"),
    "FR0000120073": ("AI.PA", "Air Liquide", "Industrie", 172.5, 171.2, 27.0, 2.9e10, 1.0e11, "Basic Materials"),
    "FR0000121972": ("SU.PA", "Schneider Electric", "Industrie", 238.0, 236.1, 26.5, 3.8e10, 1.3e11, "Industrials"),
    "FR0000120578": ("SAN.PA", "Sanofi", "Santé", 86.4, 86.9, 15.2, 4.3e10, 1.1e11, "Healthcare"),
    "NL0010273215": ("ASML.AS", "ASML", "Technologie", 702.0, 695.0, 33.4, 2.8e10, 2.8e11, "Technology"),
    "NL0000235190": ("AIR.PA", "Airbus", "Industrie", 168.0, 166.5, 28.9, 6.9e10, 1.3e11, "Industrials"),
    "FR0013412012": ("PAASI.PA", "Amundi PEA Asie Émergente (MSCI EM Asia)", "Asie émergente",
                     37.66, 37.5, None, None, None, None),
    # Watchlist
    "FR0000052292": ("RMS.PA", "Hermès", None, 2380.0, 2365.0, 48.0, 1.5e10, 2.5e11, "Consumer Cyclical"),
    "FR0000120321": ("OR.PA", "L'Oréal", None, 372.0, 370.4, 31.5, 4.4e10, 2.0e11, "Consumer Defensive"),
    "FR0000131104": ("BNP.PA", "BNP Paribas", None, 74.8, 75.3, 8.1, 5.0e10, 8.5e10, "Financial Services"),
}
# (jours avant aujourd'hui, isin, type, quantité, prix)
TRANSACTIONS = [
    (280, "FR001400U5Q4", "ACHAT", 120, 5.90), (270, "FR0000121014", "ACHAT", 4, 590.0),
    (250, "FR0000120271", "ACHAT", 25, 55.2), (230, "FR0000120073", "ACHAT", 8, 168.0),
    (200, "FR0000121972", "ACHAT", 5, 215.0), (170, "FR0000120578", "ACHAT", 14, 89.0),
    (150, "NL0010273215", "ACHAT", 2, 640.0), (120, "FR0013412012", "ACHAT", 20, 36.5),
    (110, "NL0000235190", "ACHAT", 6, 130.0), (40, "NL0000235190", "VENTE", 3, 152.0),
]
WATCHLIST = [("FR0000052292", "Luxe : attendre un meilleur point d'entrée ?"),
             ("FR0000120321", "Défensif, dividende régulier"), ("FR0000131104", "Banque, valorisation basse")]


def _typer(df: pd.DataFrame) -> pd.DataFrame:
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    for c in NUMERIQUES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _tables() -> dict:
    """Construit toutes les tables de démo (fonction pure, déterministe)."""
    auj = pd.Timestamp(date.today())
    maintenant = datetime.now(PARIS).isoformat()
    tr = sorted(((auj - pd.Timedelta(days=j), isin, t, q, p) for j, isin, t, q, p in TRANSACTIONS))
    trans = pd.DataFrame([(i + 1, d, isin, t, q, p, 0.0) for i, (d, isin, t, q, p) in enumerate(tr)],
                         columns=SCHEMA["transactions"])
    div = pd.DataFrame([(1, auj - pd.Timedelta(days=95), "FR0000120073", 22.4),
                        (2, auj - pd.Timedelta(days=60), "FR0000120271", 31.5)],
                       columns=SCHEMA["dividendes"])
    vers = pd.DataFrame([(1, auj - pd.Timedelta(days=300), "VERSEMENT", 9000.0, "Versement initial"),
                         (2, auj - pd.Timedelta(days=125), "VERSEMENT", 2000.0, None),
                         (3, auj - pd.Timedelta(days=300), "PV_ANTERIEURE", 250.0, "Gains antérieurs")],
                        columns=SCHEMA["versements"])
    tickers = pd.DataFrame([(isin, v[0], v[1], v[3], maintenant, None) for isin, v in TITRES.items()],
                           columns=SCHEMA["tickers"])
    secteurs = pd.DataFrame([(isin, v[2]) for isin, v in TITRES.items() if v[2]], columns=SCHEMA["secteurs"])
    watch = pd.DataFrame([(isin, note, None, maintenant) for isin, note in WATCHLIST],
                         columns=SCHEMA["watchlist"])
    scen = pd.DataFrame([(1, "Exemple : renforcer la santé", 0.0, maintenant)], columns=SCHEMA["scenarios"])
    sc_tr = pd.DataFrame([(1, 1, "FR0000120321", "ACHAT", 3.0, TITRES["FR0000120321"][3], maintenant),
                          (2, 1, "NL0010273215", "VENTE", 1.0, TITRES["NL0010273215"][3], maintenant)],
                         columns=SCHEMA["scenario_trades"])
    ia = pd.DataFrame([(1, maintenant, "exemple fictif", "demo", llm.EXEMPLE)], columns=SCHEMA["analyses_ia"])
    ia_scen = pd.DataFrame([(1, 1, maintenant, "exemple fictif", "demo", llm.EXEMPLE_SCENARIO)],
                           columns=SCHEMA["analyses_scen"])
    chat = pd.DataFrame(columns=SCHEMA["chat_log"])

    # Historique synthétique cohérent avec les positions (marche aléatoire qui finit au cours du jour)
    rng = np.random.RandomState(7)
    jours = pd.bdate_range(trans["date"].min(), auj)
    prix_hist, isin_ticker = {}, {isin: v[0] for isin, v in TITRES.items()}
    for isin, v in TITRES.items():
        lp = np.cumsum(rng.normal(0.0003, 0.011, len(jours)))
        prix_hist[v[0]] = pd.Series(v[3] * np.exp(lp - lp[-1]), index=jours)
    flux = C.flux_tresorerie(_typer(trans.copy()), _typer(div.copy()), _typer(vers.copy()))
    snaps = C.reconstituer_snapshots(_typer(trans.copy()), flux, prix_hist, isin_ticker)
    snaps[["valeur", "apports"]] = snaps[["valeur", "apports"]].round(2)

    tables = {"transactions": trans, "dividendes": div, "versements": vers, "tickers": tickers,
              "secteurs": secteurs, "watchlist": watch, "scenarios": scen, "scenario_trades": sc_tr,
              "analyses_ia": ia, "analyses_scen": ia_scen, "chat_log": chat, "snapshots": snaps}
    return {k: _typer(v) for k, v in tables.items()}


@st.cache_data(show_spinner=False)
def _base(jour: str) -> dict:
    return _tables()


# --------------------------------------------------------------------------- #
# Données de marché fictives (mêmes signatures que donnees.cours_batch / fondamentaux_batch)
# --------------------------------------------------------------------------- #
_PAR_TICKER = {v[0]: v for v in TITRES.values()}


def cours_batch(tickers: tuple) -> tuple[dict, datetime]:
    out = {t: {"prix": _PAR_TICKER[t][3], "prev": _PAR_TICKER[t][4], "devise": "EUR"}
           for t in tickers if t in _PAR_TICKER}
    return out, datetime.now(PARIS)


def fondamentaux_batch(tickers: tuple) -> dict:
    """Fondamentaux fictifs (ordres de grandeur plausibles, uniquement pour illustrer l'affichage)."""
    out = {}
    for t in tickers:
        if t not in _PAR_TICKER:
            continue
        _, _, _, _, _, per, ca, capi, sect = _PAR_TICKER[t]
        f = {"per": per, "ca": ca, "capi": capi, "secteur_yahoo": sect}
        if ca and capi:  # action
            f.update(per_prev=per * 0.93 if per else None, net_income=ca * 0.12, ebitda=ca * 0.22,
                     ev=capi * 1.1, ev_ebitda=capi * 1.1 / (ca * 0.22))
        else:            # ETF
            f.update(net_assets=1.5e9, expense_ratio=0.2)
        out[t] = f
    return out


# --------------------------------------------------------------------------- #
# Magasin en mémoire, même interface que db.py
# --------------------------------------------------------------------------- #
class DemoStore:
    def __init__(self):
        if "demo_db" not in st.session_state:
            st.session_state["demo_db"] = {k: v.copy() for k, v in _base(date.today().isoformat()).items()}
        self.t: dict = st.session_state["demo_db"]
        # Mise à niveau : tables ajoutées après la création de la session (cache du navigateur)
        for nom, df in _base(date.today().isoformat()).items():
            self.t.setdefault(nom, df)

    def lire(self, table: str) -> pd.DataFrame:
        if table not in self.t:  # tolère une session créée avant l'ajout de la table
            return pd.DataFrame(columns=SCHEMA.get(table, ["id"]))
        return self.t[table].copy()

    def inserer(self, table: str, rec: dict) -> dict:
        df, cols = self.t[table], SCHEMA[table]
        row = {c: rec.get(c) for c in cols}
        if "id" in cols:
            row["id"] = int(pd.to_numeric(df["id"], errors="coerce").max() + 1) if len(df) else 1
        if row.get("date") is not None:
            row["date"] = pd.Timestamp(row["date"])
        if "cree_le" in cols and row.get("cree_le") is None:
            row["cree_le"] = datetime.now(PARIS).isoformat()
        self.t[table] = _typer(pd.concat([df.astype(object), pd.DataFrame([row], columns=cols).astype(object)],
                                         ignore_index=True))
        return row

    def modifier(self, table: str, id_, rec: dict, cle: str = "id") -> None:
        df = self.t[table]
        for k, v in rec.items():
            df.loc[df[cle] == id_, k] = v

    def supprimer(self, table: str, valeur, cle: str = "id") -> None:
        self.t[table] = self.t[table][self.t[table][cle] != valeur].reset_index(drop=True)
        if table == "scenarios":  # cascade, comme la base
            tr = self.t["scenario_trades"]
            self.t["scenario_trades"] = tr[tr["scenario_id"] != valeur].reset_index(drop=True)
            ans = self.t["analyses_scen"]
            self.t["analyses_scen"] = ans[ans["scenario_id"] != valeur].reset_index(drop=True)

    def upsert(self, table: str, recs: list[dict], conflit: str) -> None:
        for rec in recs:
            df = self.t[table]
            if (df[conflit] == rec[conflit]).any():
                for k, v in rec.items():
                    df.loc[df[conflit] == rec[conflit], k] = v
            else:
                self.inserer(table, rec)

    def rafraichir(self) -> None:
        pass
