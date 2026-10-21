"""Indicateurs techniques et note technique pondérée : calculs purs (aucune dépendance à Streamlit/réseau).

Entrée : un DataFrame de bougies JOURNALIÈRES avec colonnes High, Low, Close (index = dates, ordre croissant).

Chaque indicateur produit un SCORE entre -1 (vendre) et +1 (acheter), puis un verdict :
score >= +0,5 « Acheter » · score <= -0,5 « Vendre » · sinon « Neutre ».
Les oscillateurs ont une « zone neutre » (score 0) et leurs seuils classiques valent ±0,5 :
RSI 30 / 70, Stochastique 20 / 80, Bollinger = bande basse / haute ; au-delà le score monte vers ±1.

La NOTE TECHNIQUE (0 à 10) = 5 + 5 × moyenne pondérée des scores des indicateurs disponibles.
Filtre de tendance : quand les moyennes mobiles donnent une tendance nette (score >= +0,5 ou <= -0,5),
les signaux d'oscillateurs CONTRAIRES à cette tendance (« surachat » en tendance haussière, « survente »
en tendance baissière) comptent pour moitié dans la note : être suracheté en pleine hausse est normal.
L'affichage de chaque indicateur reste son signal brut.
Verdict global : note >= 6 « Acheter », note <= 4 « Vendre », sinon « Neutre ».
Ce sont des signaux indicatifs, pas un conseil en investissement : les oscillateurs (RSI, Stochastique,
Bollinger) jouent le retour à la moyenne et peuvent contredire la tendance des moyennes mobiles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POIDS = {"mm": 0.40, "rsi": 0.20, "stoch": 0.20, "bb": 0.20}
LIBELLES = {"mm": "Moyennes mobiles", "rsi": "RSI", "stoch": "Stochastique", "bb": "Bollinger"}
ATTENUATION_CONTRE_TENDANCE = 0.5
SEUIL_INDICATEUR = 0.5            # |score| à partir duquel un indicateur dit Acheter / Vendre
NOTE_ACHAT, NOTE_VENTE = 6.0, 4.0  # seuils du verdict global sur la note /10
MIN_BOUGIES = 20                   # en dessous : pas d'analyse
EMOJI = {"Acheter": "🟢", "Neutre": "🟡", "Vendre": "🔴"}


def _n(x: float, dec: int = 1) -> str:
    """Nombre au format français (virgule décimale, espace fine pour les milliers)."""
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def _verdict(score: float) -> str:
    return "Acheter" if score >= SEUIL_INDICATEUR else "Vendre" if score <= -SEUIL_INDICATEUR else "Neutre"


def _courbe(x: float, points: list[tuple[float, float]]) -> float:
    """Score par interpolation linéaire entre points (valeur, score) ; constant au-delà des extrémités."""
    xs, ys = zip(*points)
    return float(np.interp(x, xs, ys))


# (valeur de l'indicateur, score) : zone neutre au centre, ±0,5 aux seuils classiques, ±1 aux extrêmes
COURBE_RSI = [(10, 1), (30, 0.5), (40, 0), (60, 0), (70, -0.5), (90, -1)]
COURBE_STOCH = [(0, 1), (20, 0.5), (40, 0), (60, 0), (80, -0.5), (100, -1)]
COURBE_PB = [(-0.5, 1), (0, 0.5), (0.2, 0), (0.8, 0), (1, -0.5), (1.5, -1)]


# --------------------------------------------------------------------------- #
# Indicateurs (séries complètes ; la dernière valeur sert à la décision)
# --------------------------------------------------------------------------- #
def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder : moyennes des n premières hausses/baisses, puis lissage (n-1)/n + 1/n."""
    c = close.to_numpy(dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return pd.Series(out, index=close.index)
    delta = np.diff(c)
    gain, perte = np.where(delta > 0, delta, 0.0), np.where(delta < 0, -delta, 0.0)
    g, p = gain[:n].mean(), perte[:n].mean()
    for i in range(n, len(c)):
        if i > n:
            g = (g * (n - 1) + gain[i - 1]) / n
            p = (p * (n - 1) + perte[i - 1]) / n
        out[i] = 100.0 if p == 0 and g > 0 else (np.nan if p == 0 else 100 - 100 / (1 + g / p))
    return pd.Series(out, index=close.index)


def stochastique(high: pd.Series, low: pd.Series, close: pd.Series,
                 n: int = 14, lissage_k: int = 3, lissage_d: int = 3) -> tuple[pd.Series, pd.Series]:
    """(%K lent, %D) : %K brut sur n jours, lissé sur 3 ; %D = moyenne 3 jours de %K."""
    bas, haut = low.rolling(n).min(), high.rolling(n).max()
    brut = 100 * (close - bas) / (haut - bas).replace(0, np.nan)
    k = brut.rolling(lissage_k).mean()
    return k, k.rolling(lissage_d).mean()


def bollinger(close: pd.Series, n: int = 20, ecarts: float = 2.0) -> pd.DataFrame:
    """Bandes de Bollinger et %B (0 = bande basse, 1 = bande haute)."""
    milieu = close.rolling(n).mean()
    sigma = close.rolling(n).std(ddof=0)
    haut, bas = milieu + ecarts * sigma, milieu - ecarts * sigma
    pb = (close - bas) / (haut - bas).replace(0, np.nan)
    return pd.DataFrame({"milieu": milieu, "haut": haut, "bas": bas, "pb": pb})


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #
def _score_mm(close: pd.Series) -> dict | None:
    """Prix face à MM20/50/200 et croisement MM50/MM200 : chaque test vaut +1 (haussier) ou -1."""
    dernier = float(close.iloc[-1])
    tests, jours = [], []
    valeurs = {n: sma(close, n).iloc[-1] for n in (20, 50, 200)}
    for n, v in valeurs.items():
        if pd.notna(v):
            tests.append(1.0 if dernier > v else -1.0)
            jours.append(str(n))
    au_dessus, total = sum(1 for t in tests if t > 0), len(tests)
    if pd.notna(valeurs[50]) and pd.notna(valeurs[200]):
        tests.append(1.0 if valeurs[50] > valeurs[200] else -1.0)
    if not tests:
        return None
    score = float(np.mean(tests))
    return {"cle": "mm", "score": score,
            "detail": f"cours au-dessus de {au_dessus} moyenne{'s' if au_dessus > 1 else ''} sur {total} "
                      f"({', '.join(jours)} jours)"}


def _score_rsi(close: pd.Series) -> dict | None:
    v = rsi(close).iloc[-1]
    if pd.isna(v):
        return None
    return {"cle": "rsi", "score": _courbe(v, COURBE_RSI),
            "detail": f"{_n(v, 0)} (survente < 30, surachat > 70)"}


def _score_stoch(df: pd.DataFrame) -> dict | None:
    k, d = stochastique(df["High"], df["Low"], df["Close"])
    if pd.isna(k.iloc[-1]):
        return None
    return {"cle": "stoch", "score": _courbe(k.iloc[-1], COURBE_STOCH),
            "detail": f"{_n(k.iloc[-1], 0)} (survente < 20, surachat > 80)"}


def _score_bb(close: pd.Series) -> dict | None:
    pb = bollinger(close)["pb"].iloc[-1]
    if pd.isna(pb):
        return None
    return {"cle": "bb", "score": _courbe(pb, COURBE_PB),
            "detail": f"{_n(pb * 100, 0)} % (survente < 0 %, surachat > 100 %)"}


# --------------------------------------------------------------------------- #
# Analyse complète
# --------------------------------------------------------------------------- #
def analyser(df: pd.DataFrame | None) -> dict:
    """Résultat prêt à afficher. ``ok`` = False (avec ``raison``) si l'historique est insuffisant.

    Retour : {ok, date, dernier, note, score, verdict, emoji, indicateurs: [{cle, label, score,
    verdict, emoji, poids, detail, attenue}]}
    """
    if df is None or len(df) < MIN_BOUGIES or not {"High", "Low", "Close"} <= set(df.columns):
        return {"ok": False, "raison": f"Historique insuffisant (au moins {MIN_BOUGIES} séances requises)."}
    d = df[["High", "Low", "Close"]].astype(float).dropna().sort_index()
    if len(d) < MIN_BOUGIES:
        return {"ok": False, "raison": f"Historique insuffisant (au moins {MIN_BOUGIES} séances requises)."}
    close = d["Close"]
    brut = [_score_mm(close), _score_rsi(close), _score_stoch(d), _score_bb(close)]
    inds = []
    for r in brut:
        if r is None:
            continue
        v = _verdict(r["score"])
        inds.append({**r, "label": LIBELLES[r["cle"]], "poids": POIDS[r["cle"]], "verdict": v,
                     "emoji": EMOJI[v]})
    if not inds:
        return {"ok": False, "raison": "Indicateurs non calculables sur cet historique."}
    mm = next((i["score"] for i in inds if i["cle"] == "mm"), 0.0)
    for i in inds:  # filtre de tendance sur les oscillateurs
        contre = i["cle"] != "mm" and ((mm >= SEUIL_INDICATEUR and i["score"] < 0)
                                       or (mm <= -SEUIL_INDICATEUR and i["score"] > 0))
        i["attenue"] = bool(contre)
        i["score_note"] = i["score"] * (ATTENUATION_CONTRE_TENDANCE if contre else 1.0)
    poids_total = sum(i["poids"] for i in inds)
    score = sum(i["poids"] * i["score_note"] for i in inds) / poids_total  # absents : poids redistribué
    note = 5 + 5 * score
    verdict = "Acheter" if note >= NOTE_ACHAT else "Vendre" if note <= NOTE_VENTE else "Neutre"
    return {"ok": True, "date": pd.Timestamp(d.index[-1]), "dernier": float(close.iloc[-1]),
            "note": float(note), "score": float(score), "verdict": verdict, "emoji": EMOJI[verdict],
            "indicateurs": inds}


def resume(res: dict | None) -> str:
    """« 🟢 Acheter · 6,8/10 » pour l'en-tête d'une carte ; chaîne vide si indisponible."""
    if not res or not res.get("ok"):
        return ""
    return f"{res['emoji']} {res['verdict']} · {_n(res['note'])}/10"
