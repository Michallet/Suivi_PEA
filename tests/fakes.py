"""Faux Supabase et faux Yahoo Finance : en mémoire, déterministes, qui COMPTENT les appels réseau.

Servent aux tests d'isolation, aux tests AppTest et aux mesures de performance (budgets du README).
Rien de réel : toutes les données sont fictives.
"""
from __future__ import annotations

import copy
import datetime as dt
import threading
import types
from collections import Counter

import numpy as np
import pandas as pd

from tests import fictives as F

TABLES_ID = {"transactions", "dividendes", "versements", "scenarios", "scenario_trades", "analyses_ia",
             "analyses_scen", "chat_log", "usage_ia"}
CLES = {"secteurs": ("user_id", "isin"), "tickers": ("user_id", "isin"), "snapshots": ("user_id", "date"),
        "watchlist": ("user_id", "isin"), "partage": ("user_id",), "marche_cache": ("cle",)}
CASCADES = {"scenarios": [("scenario_trades", "scenario_id"), ("analyses_scen", "scenario_id")]}


def _comparable(x, v):
    """Dates ISO avec fuseaux différents : comparées comme horodatages, pas comme chaînes."""
    if isinstance(x, str) and isinstance(v, str) and len(x) >= 10 and len(v) >= 10 and x[4] == "-" and v[4] == "-":
        try:
            a, b = pd.Timestamp(x), pd.Timestamp(v)
            if (a.tzinfo is None) != (b.tzinfo is None):
                a = a.tz_localize("UTC") if a.tzinfo is None else a
                b = b.tz_localize("UTC") if b.tzinfo is None else b
            return a, b
        except Exception:
            pass
    return x, v


class Reponse:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class Requete:
    """Imite la chaîne de construction de postgrest-py (sous-ensemble utilisé par l'application)."""

    def __init__(self, base: "FauxSupabase", table: str):
        self.base, self.table = base, table
        self.op, self.cols, self.payload, self.filtres = "select", "*", None, []
        self.tris, self.plage, self.limite, self.compte, self.tete, self.conflit = [], None, None, None, False, None

    # -- construction -----------------------------------------------------------------------------
    def select(self, cols="*", count=None, head=False):
        self.op, self.cols, self.compte, self.tete = "select", cols, count, head
        return self

    def insert(self, payload, **_):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload, **_):
        self.op, self.payload = "update", payload
        return self

    def delete(self, **_):
        self.op = "delete"
        return self

    def upsert(self, payload, on_conflict=None, **_):
        self.op, self.payload, self.conflit = "upsert", payload, on_conflict
        return self

    def eq(self, c, v):
        self.filtres.append((c, "eq", v)); return self

    def neq(self, c, v):
        self.filtres.append((c, "neq", v)); return self

    def in_(self, c, vs):
        self.filtres.append((c, "in", list(vs))); return self

    def gte(self, c, v):
        self.filtres.append((c, "gte", v)); return self

    def gt(self, c, v):
        self.filtres.append((c, "gt", v)); return self

    def lt(self, c, v):
        self.filtres.append((c, "lt", v)); return self

    def lte(self, c, v):
        self.filtres.append((c, "lte", v)); return self

    def order(self, c, desc=False, **_):
        self.tris.append((c, bool(desc))); return self

    def range(self, a, b):
        self.plage = (a, b); return self

    def limit(self, n):
        self.limite = n; return self

    # -- exécution --------------------------------------------------------------------------------
    def _garde(self, ligne) -> bool:
        for c, o, v in self.filtres:
            x = ligne.get(c)
            if x is not None and isinstance(v, str) and not isinstance(x, str):
                x = str(x)
            if o == "eq" and x != v: return False
            if o == "neq" and x == v: return False
            if o == "in" and x not in v: return False
            if o in ("gte", "gt", "lt", "lte"):
                if x is None:
                    return False
                a, b = _comparable(x, v)
                if o == "gte" and not a >= b: return False
                if o == "gt" and not a > b: return False
                if o == "lt" and not a < b: return False
                if o == "lte" and not a <= b: return False
        return True

    def execute(self):
        return self.base._executer(self)


class FauxSupabase:
    def __init__(self, donnees: dict | None = None):
        self.tables: dict[str, list[dict]] = {t: [] for t in (*TABLES_ID, *CLES)}
        for t, lignes in (donnees or {}).items():
            self.tables[t] = copy.deepcopy(lignes)
        self.suites = Counter()
        for t in TABLES_ID:
            self.suites[t] = max([l.get("id", 0) for l in self.tables[t]] or [0])
        self.appels: list[tuple] = []
        self.verrou = threading.Lock()
        self.rpc_disponibles: dict = {}
        self.tables_absentes: set[str] = set()
        self.maintenant = lambda: dt.datetime.now(dt.timezone.utc).isoformat()

    # API postgrest -------------------------------------------------------------------------------
    def table(self, nom: str) -> Requete:
        return Requete(self, nom)

    def rpc(self, nom: str, params: dict | None = None):
        base = self

        class _R:
            def execute(self_inner):
                with base.verrou:
                    base.appels.append(("rpc", nom, None))
                if nom not in base.rpc_disponibles:
                    raise RuntimeError(f"fonction {nom} absente (PGRST202)")
                return Reponse(base.rpc_disponibles[nom](base, **(params or {})))
        return _R()

    # compteurs -----------------------------------------------------------------------------------
    def nb(self, op: str | None = None, table: str | None = None) -> int:
        return sum(1 for a in self.appels if (op is None or a[0] == op) and (table is None or a[1] == table))

    def remise_a_zero(self) -> None:
        self.appels.clear()

    def resume(self) -> dict:
        return dict(Counter(f"{a[0]}:{a[1]}" for a in self.appels))

    # exécution -----------------------------------------------------------------------------------
    def _executer(self, q: Requete):
        with self.verrou:
            self.appels.append((q.op, q.table, q.cols if q.op == "select" else None))
            if q.table in self.tables_absentes:
                raise RuntimeError(f"relation « {q.table} » inexistante (42P01)")
            lignes = self.tables.setdefault(q.table, [])
            if q.op == "select":
                sel = [l for l in lignes if q._garde(l)]
                for c, desc in reversed(q.tris):
                    sel.sort(key=lambda l: (l.get(c) is None, l.get(c)), reverse=desc)
                total = len(sel)
                if q.plage:
                    sel = sel[q.plage[0]:q.plage[1] + 1]
                if q.limite is not None:
                    sel = sel[:q.limite]
                if q.cols not in ("*", None):
                    cols = [c.strip() for c in q.cols.split(",")]
                    sel = [{c: l.get(c) for c in cols} for l in sel]
                else:
                    sel = [dict(l) for l in sel]
                if q.tete:
                    return Reponse([], total if q.compte else None)
                return Reponse(copy.deepcopy(sel), total if q.compte else None)
            if q.op == "insert":
                recs = q.payload if isinstance(q.payload, list) else [q.payload]
                sortie = [self._inserer(q.table, dict(r)) for r in recs]
                return Reponse(copy.deepcopy(sortie))
            if q.op == "update":
                touches = [l for l in lignes if q._garde(l)]
                for l in touches:
                    l.update(q.payload)
                return Reponse(copy.deepcopy(touches))
            if q.op == "delete":
                supprimes = [l for l in lignes if q._garde(l)]
                self.tables[q.table] = [l for l in lignes if l not in supprimes]
                for enfant, col in CASCADES.get(q.table, []):
                    ids = {l["id"] for l in supprimes}
                    self.tables[enfant] = [l for l in self.tables[enfant]
                                           if not (l.get(col) in ids and l["user_id"] in {s["user_id"] for s in supprimes})]
                return Reponse(copy.deepcopy(supprimes))
            if q.op == "upsert":
                recs = q.payload if isinstance(q.payload, list) else [q.payload]
                cles = tuple(c.strip() for c in q.conflit.split(",")) if q.conflit else CLES.get(q.table, ("id",))
                sortie = []
                for r in recs:
                    r = dict(r)
                    ex = next((l for l in lignes if all(l.get(c) == r.get(c) for c in cles)), None)
                    if ex is None:
                        sortie.append(self._inserer(q.table, r))
                    else:
                        ex.update(r)
                        sortie.append(ex)
                return Reponse(copy.deepcopy(sortie))
        raise NotImplementedError(q.op)

    def _inserer(self, table: str, r: dict) -> dict:
        if table in TABLES_ID and "id" not in r:
            self.suites[table] += 1
            r["id"] = self.suites[table]
        if table in {"scenarios", "scenario_trades", "analyses_ia", "analyses_scen", "chat_log", "usage_ia"}:
            r.setdefault("cree_le", self.maintenant())
        if table == "watchlist":
            r.setdefault("ajoute_le", self.maintenant())
        self.tables.setdefault(table, []).append(r)
        return r

    def lignes(self, table: str, user_id: str | None = None) -> list[dict]:
        return [l for l in self.tables.get(table, []) if user_id is None or l.get("user_id") == user_id]


# --------------------------------------------------------------------------------------------------
# Données fictives de comptes
# --------------------------------------------------------------------------------------------------
def donnees_compte(uid: str, facteur: float = 1.0) -> dict:
    """Jeu complet fictif pour un compte (le facteur change les quantités pour distinguer les comptes)."""
    j, d, v = F.journal(), F.dividendes(), F.versements()
    out = {
        "transactions": [{"id": 0, "user_id": uid, "date": r.date.date().isoformat(), "isin": r.isin, "type": r.type,
                          "quantite": r.quantite * facteur, "prix": r.prix, "frais": r.frais} for r in j.itertuples()],
        "dividendes": [{"id": 0, "user_id": uid, "date": r.date.date().isoformat(), "isin": r.isin, "montant": r.montant}
                       for r in d.itertuples()],
        "versements": [{"id": 0, "user_id": uid, "date": r.date.date().isoformat(), "type": r.type,
                        "montant": r.montant * facteur, "libelle": r.libelle} for r in v.itertuples()],
        "tickers": [{"user_id": uid, "isin": i, "ticker": t, "nom": F.NOMS[i], "dernier_prix": 100.0,
                     "dernier_prix_at": "2025-06-01T00:00:00+00:00", "concurrent_isin": None,
                     "concurrent_ticker": None, "concurrent_nom": None} for i, t in F.TICKERS.items()],
        "secteurs": [{"user_id": uid, "isin": i, "secteur": s} for i, s in F.SECTEURS.items()],
        "snapshots": [{"user_id": uid, "date": f"2025-{m:02d}-{k:02d}", "valeur": 3000.0 * facteur + 40 * m + k, "apports": 3000.0 * facteur}
                      for m in range(1, 6) for k in (3, 10)],
        "watchlist": [{"user_id": uid, "isin": F.BETA, "note": f"note de {uid}", "ajoute_le": "2025-02-01T00:00:00+00:00"}],
        "scenarios": [{"id": 0, "user_id": uid, "nom": f"Scénario de {uid}", "versement": 0, "cree_le": "2025-03-01T00:00:00+00:00"}],
        "scenario_trades": [], "analyses_ia": [], "analyses_scen": [], "chat_log": [],
        "partage": [{"user_id": uid, "partage": True, "pseudo": f"pseudo-{uid}"}],
    }
    for t in ("transactions", "dividendes", "versements", "scenarios"):
        for n, l in enumerate(out[t], 1):
            l["id"] = n + {"theo": 0, "alice": 1000, "demo": 2000}.get(uid, 5000)
    return out


ORDRE_RPC = {"transactions": ("date", "id"), "dividendes": ("date", "id"), "versements": ("date", "id"),
             "secteurs": ("isin",), "tickers": ("isin",), "snapshots": ("date",), "watchlist": ("ajoute_le",),
             "partage": (), "scenarios": ("id",), "scenario_trades": ("id",)}


def rpc_charger_compte(base: "FauxSupabase", p_user: str) -> dict:
    """Imite la fonction SQL pea_charger_compte de sql/migrations/001."""
    out = {}
    for t, ordre in ORDRE_RPC.items():
        lignes = [{k: v for k, v in l.items() if k != "user_id"} for l in base.tables.get(t, []) if l.get("user_id") == p_user]
        out[t] = sorted(lignes, key=lambda l: tuple(str(l.get(c)) for c in ordre))
    for t, n in (("analyses_ia", 1), ("analyses_scen", 200)):
        lignes = [{k: v for k, v in l.items() if k != "user_id"} for l in base.tables.get(t, []) if l.get("user_id") == p_user]
        out[t] = sorted(lignes, key=lambda l: -l["id"])[:n]
    return copy.deepcopy(out)


def base_fictive(comptes=("theo", "alice", "demo"), migration: bool = True) -> FauxSupabase:
    """Base fictive multi-comptes. `migration=False` : base d'avant la migration 001 (ni RPC, ni tables nouvelles)."""
    fusion: dict[str, list] = {}
    for n, uid in enumerate(comptes, 1):
        for t, lignes in donnees_compte(uid, facteur=float(n)).items():
            fusion.setdefault(t, []).extend(lignes)
    b = FauxSupabase(fusion)
    if migration:
        b.rpc_disponibles["pea_charger_compte"] = rpc_charger_compte
    else:
        b.tables_absentes |= {"usage_ia", "marche_cache"}
    return b


# --------------------------------------------------------------------------------------------------
# Faux Yahoo Finance
# --------------------------------------------------------------------------------------------------
class FauxYahoo:
    """Imite le sous-ensemble de `yfinance` utilisé : Ticker, Search, download. Compte chaque appel."""

    def __init__(self, indisponibles: set | None = None):
        self.appels = Counter()
        self.journal_appels: list[tuple] = []
        self.indisponibles = set(indisponibles or ())
        self.limitation = False      # simule une réponse 429
        self.verrou = threading.Lock()
        self.latence = 0.0

    # -- données déterministes par ticker ---------------------------------------------------------
    @staticmethod
    def _base(ticker: str) -> float:
        return 20.0 + (sum(map(ord, ticker)) % 80)

    def _compter(self, nature: str, cible) -> None:
        with self.verrou:
            self.appels[nature] += 1
            self.journal_appels.append((nature, cible))
        if self.latence:
            import time
            time.sleep(self.latence)
        if self.limitation:
            raise RuntimeError("429 Too Many Requests")

    def historique(self, ticker: str, jours: int = 260) -> pd.DataFrame:
        rng = np.random.RandomState(sum(map(ord, ticker)))
        close = self._base(ticker) * np.cumprod(1 + rng.normal(0.0003, 0.01, jours))
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=jours)
        return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                             "Volume": 1000}, index=idx)

    # -- API yfinance -----------------------------------------------------------------------------
    def Ticker(self, t: str):
        faux = self

        class _T:
            @property
            def fast_info(self_inner):
                faux._compter("fast_info", t)
                if t in faux.indisponibles:
                    return types.SimpleNamespace(last_price=None, previous_close=None, currency=None)
                h = faux.historique(t, 5)["Close"]
                return types.SimpleNamespace(last_price=float(h.iloc[-1]), previous_close=float(h.iloc[-2]), currency="EUR")

            def history(self_inner, period=None, start=None, auto_adjust=True, **_):
                faux._compter("history", t)
                if t in faux.indisponibles:
                    return pd.DataFrame(columns=["High", "Low", "Close"])
                h = faux.historique(t)
                if start:
                    h = h[h.index >= pd.Timestamp(start)]
                if period == "5d":
                    h = h.tail(5)
                h = h.copy()
                h.index = h.index.tz_localize("Europe/Paris")
                return h

            @property
            def info(self_inner):
                faux._compter("info", t)
                if t in faux.indisponibles:
                    return {}
                etf = t.startswith("GAM")
                base = {"shortName": F.NOMS.get(next((i for i, x in F.TICKERS.items() if x == t), ""), t), "currency": "EUR"}
                if etf:
                    return {**base, "totalAssets": 1.2e9, "netExpenseRatio": 0.15}
                return {**base, "trailingPE": 15.0 + faux._base(t) % 10, "forwardPE": 13.0, "enterpriseValue": 5e9,
                        "totalRevenue": 2e9, "marketCap": 4e9, "sector": "Industrials", "industry": "Machinery",
                        "ebitda": 4e8, "netIncome": 2e8}
        return _T()

    def Search(self, isin, max_results=8):
        self._compter("search", isin)
        i = next((k for k in F.NOMS if k == isin), None)
        return types.SimpleNamespace(quotes=[{"symbol": F.TICKERS[i], "shortname": F.NOMS[i]}] if i else [])

    def download(self, tickers, period="5d", group_by="ticker", progress=False, threads=True, auto_adjust=False, **_):
        liste = [tickers] if isinstance(tickers, str) else list(tickers)
        self._compter("download", tuple(liste))
        blocs = {}
        for t in liste:
            if t in self.indisponibles:
                continue
            h = self.historique(t, 260 if period != "5d" else 5)
            blocs[t] = h
        if not blocs:
            return pd.DataFrame()
        return pd.concat(blocs, axis=1)  # colonnes (ticker, champ)

    def total(self) -> int:
        return sum(self.appels.values())
