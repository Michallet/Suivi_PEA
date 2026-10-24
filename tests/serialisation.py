"""Mise en forme déterministe des résultats pour les comparer à des valeurs de référence (JSON)."""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd


def norm(x, dec: int = 9):
    if isinstance(x, pd.DataFrame):
        return {"__df__": True, "colonnes": [str(c) for c in x.columns],
                "lignes": [[norm(v, dec) for v in r] for r in x.itertuples(index=False, name=None)]}
    if isinstance(x, pd.Series):
        return {"__serie__": True, "index": [norm(i, dec) for i in x.index],
                "valeurs": [norm(v, dec) for v in x.tolist()]}
    if isinstance(x, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(x).isoformat()
    if x is pd.NaT:
        return "NaT"
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        f = float(x)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "inf" if f > 0 else "-inf"
        return round(f, dec)
    if isinstance(x, dict):
        return {str(k): norm(v, dec) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [norm(v, dec) for v in x]
    if isinstance(x, set):
        return sorted(norm(v, dec) for v in x)
    if x is None or isinstance(x, (int, str)):
        return x
    return repr(x)
