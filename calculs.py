"""Calculs financiers purs : aucune dépendance à Streamlit ni au réseau (testable avec pytest).

Conventions
-----------
* PRM = coût moyen pondéré, frais d'achat inclus.
* Une vente réduit le coût de la position au PRM (et non au prix de vente) ;
  la plus-value réalisée = produit net de la vente - PRM x quantité.
* Cash du PEA = versements - retraits - achats + ventes + dividendes (frais déduits).
* Apports nets = versements - retraits. Les « plus-values antérieures réinvesties »
  alimentent le cash mais ne sont PAS des apports.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

PLAFOND_PEA = 150_000.0

COLS_POSITIONS = ["isin", "quantite", "cout", "prm"]
COLS_VENTES = ["date", "isin", "quantite", "prm", "pv"]


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def isin_valide(isin: str) -> bool:
    """Format ISIN (2 lettres + 9 alphanumériques + 1 chiffre) et clé de contrôle (Luhn)."""
    isin = (isin or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    chiffres = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, c in enumerate(reversed(chiffres)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def formater_gros_nombre(x) -> str:
    """CA / capitalisation lisibles : M € (million), Md € (milliard), T € (millier de milliards)."""
    if x is None or pd.isna(x) or x == 0:
        return "N/A"
    for seuil, suffixe in ((1e12, "T €"), (1e9, "Md €"), (1e6, "M €")):
        if abs(x) >= seuil:
            return f"{x / seuil:,.2f} {suffixe}".replace(",", "\u202f").replace(".", ",")
    return f"{x:,.0f} €".replace(",", "\u202f")


# --------------------------------------------------------------------------- #
# Positions, PRM, plus-values réalisées
# --------------------------------------------------------------------------- #
def calcul_positions(trans: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rejoue le journal dans l'ordre chronologique.

    Retourne (positions ouvertes, ventes avec plus-value réalisée).
    Lève ValueError si une vente dépasse la quantité détenue.
    """
    etat: dict[str, dict[str, float]] = {}
    ventes: list[dict] = []

    if trans is not None and not trans.empty:
        for r in trans.sort_values("date", kind="stable").itertuples(index=False):
            e = etat.setdefault(r.isin, {"q": 0.0, "c": 0.0})
            frais = getattr(r, "frais", 0.0)
            frais = 0.0 if frais is None or pd.isna(frais) else float(frais)

            if r.type == "ACHAT":
                e["q"] += r.quantite
                e["c"] += r.quantite * r.prix + frais
            else:  # VENTE
                if r.quantite > e["q"] + 1e-9:
                    jour = pd.Timestamp(r.date).strftime("%d/%m/%Y")
                    raise ValueError(
                        f"Vente de {r.quantite:g} × {r.isin} le {jour} : "
                        f"seulement {e['q']:g} en portefeuille à cette date."
                    )
                prm = e["c"] / e["q"] if e["q"] > 0 else 0.0
                cout_cede = prm * r.quantite
                produit_net = r.quantite * r.prix - frais
                ventes.append(
                    {"date": r.date, "isin": r.isin, "quantite": r.quantite,
                     "prm": prm, "pv": produit_net - cout_cede}
                )
                e["q"] -= r.quantite
                e["c"] -= cout_cede
                if e["q"] < 1e-9:  # ligne soldée : on repart de zéro
                    e["q"], e["c"] = 0.0, 0.0

    positions = pd.DataFrame(
        [{"isin": i, "quantite": e["q"], "cout": e["c"], "prm": e["c"] / e["q"]}
         for i, e in etat.items() if e["q"] > 1e-9],
        columns=COLS_POSITIONS,
    )
    return positions, pd.DataFrame(ventes, columns=COLS_VENTES)


def enrichir_positions(positions: pd.DataFrame, cours: pd.DataFrame,
                       div_par_isin: pd.Series) -> pd.DataFrame:
    """Ajoute valeur, +/- value, variation du jour, poids, dividendes.

    `cours` : colonnes isin, ticker, nom, prix, prev_close, statut
    (statut = « live » | « obsolète » | « estimé »).
    Sans cours du tout, la ligne est valorisée à son PRM (statut « estimé »).
    """
    df = positions.merge(cours, on="isin", how="left")
    for c in ("prix", "prev_close"):  # None -> NaN, dtype numérique garanti
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["statut"] = df["statut"].fillna("estimé")
    df["nom"] = df["nom"].fillna(df["isin"])
    df["prix_eff"] = df["prix"].fillna(df["prm"])
    df["valeur"] = df["quantite"] * df["prix_eff"]
    df["pv_latente"] = df["valeur"] - df["cout"]
    df["perf_pct"] = (df["pv_latente"] / df["cout"].replace(0, np.nan) * 100).fillna(0.0)

    # Variation du jour : uniquement si le cours est en direct
    veille = df["prev_close"].where(df["statut"] == "live").fillna(df["prix_eff"])
    df["var_jour_eur"] = df["quantite"] * (df["prix_eff"] - veille)
    df["var_jour_pct"] = ((df["prix_eff"] / veille.replace(0, np.nan) - 1) * 100).fillna(0.0)

    df["dividendes"] = df["isin"].map(div_par_isin).fillna(0.0)
    total = df["valeur"].sum()
    df["poids_pct"] = df["valeur"] / total * 100 if total > 0 else 0.0
    return df


# --------------------------------------------------------------------------- #
# Trésorerie, apports, synthèse
# --------------------------------------------------------------------------- #
def flux_tresorerie(trans: pd.DataFrame, div: pd.DataFrame, vers: pd.DataFrame) -> pd.DataFrame:
    """Un flux par ligne : date, delta_cash, delta_apports."""
    blocs = []
    if not trans.empty:
        brut = trans["quantite"] * trans["prix"]
        frais = trans["frais"].fillna(0.0) if "frais" in trans else 0.0
        cash = np.where(trans["type"] == "ACHAT", -(brut + frais), brut - frais)
        blocs.append(pd.DataFrame({
            "date": pd.to_datetime(trans["date"]).dt.normalize(),
            "delta_cash": cash, "delta_apports": 0.0}))
    if not div.empty:
        blocs.append(pd.DataFrame({
            "date": pd.to_datetime(div["date"]).dt.normalize(),
            "delta_cash": div["montant"], "delta_apports": 0.0}))
    if not vers.empty:
        m, t = vers["montant"], vers["type"]
        blocs.append(pd.DataFrame({
            "date": pd.to_datetime(vers["date"]).dt.normalize(),
            "delta_cash": np.where(t == "RETRAIT", -m, m),
            "delta_apports": np.where(t == "VERSEMENT", m, np.where(t == "RETRAIT", -m, 0.0))}))
    if not blocs:
        return pd.DataFrame({"date": pd.to_datetime([]), "delta_cash": [], "delta_apports": []})
    return pd.concat(blocs, ignore_index=True)


def synthese(pos: pd.DataFrame, flux: pd.DataFrame, vers: pd.DataFrame) -> dict:
    """Indicateurs clés du tableau de bord."""
    cash = float(flux["delta_cash"].sum())
    apports = float(flux["delta_apports"].sum())
    valeur_titres = float(pos["valeur"].sum()) if not pos.empty else 0.0
    var_eur = float(pos["var_jour_eur"].sum()) if not pos.empty else 0.0
    base_veille = valeur_titres - var_eur
    versements_cumules = (float(vers.loc[vers["type"] == "VERSEMENT", "montant"].sum())
                          if not vers.empty else 0.0)
    valeur_totale = valeur_titres + cash
    pv_globale = valeur_totale - apports
    return {
        "valeur_titres": valeur_titres,
        "cash": cash,
        "valeur_totale": valeur_totale,
        "apports": apports,
        "pv_globale": pv_globale,
        "perf_pct": pv_globale / apports * 100 if apports > 0 else 0.0,
        "var_jour_eur": var_eur,
        "var_jour_pct": var_eur / base_veille * 100 if base_veille > 0 else 0.0,
        "versements_cumules": versements_cumules,
        "plafond_pct": versements_cumules / PLAFOND_PEA * 100,
    }


# --------------------------------------------------------------------------- #
# Historique : performance pondérée par le temps (TWR) et reconstitution
# --------------------------------------------------------------------------- #
def calcul_twr(snap: pd.DataFrame) -> pd.DataFrame:
    """Indice base 100 neutralisant les versements/retraits.

    snap : colonnes date, valeur (PEA total), apports (apports nets cumulés).
    Hypothèse : un flux du jour est investi dès l'ouverture.
    """
    s = snap.sort_values("date").reset_index(drop=True)
    flux = s["apports"].diff().fillna(0.0)
    base = (s["valeur"].shift(1) + flux).replace(0, np.nan)
    r = (s["valeur"] / base - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return pd.DataFrame({"date": s["date"], "twr": (1 + r).cumprod() * 100})


def reconstituer_snapshots(trans: pd.DataFrame, flux: pd.DataFrame,
                           prix_hist: dict, isin_ticker: dict, fin=None) -> pd.DataFrame:
    """Valeur quotidienne du PEA depuis la 1re opération.

    prix_hist : {ticker: Series de clôtures indexée par date}.
    Sans historique pour une ligne, on retombe sur le dernier prix de transaction.
    """
    vide = pd.DataFrame(columns=["date", "valeur", "apports"])
    if trans.empty:
        return vide
    debut = min(pd.to_datetime(trans["date"]).min(), flux["date"].min()).normalize()
    fin = pd.Timestamp(fin if fin is not None else pd.Timestamp.today()).normalize()
    jours = pd.bdate_range(debut, fin)
    if len(jours) == 0:
        return vide

    valeur = pd.Series(0.0, index=jours)
    for isin, g in trans.groupby("isin"):
        dates = pd.to_datetime(g["date"]).dt.normalize()
        sens = np.where(g["type"] == "ACHAT", g["quantite"], -g["quantite"])
        delta = pd.Series(sens, index=dates.to_numpy()).groupby(level=0).sum()
        qte = delta.reindex(jours.union(delta.index)).fillna(0.0).cumsum().reindex(jours)

        px = prix_hist.get(isin_ticker.get(isin))
        if px is None or len(px) == 0:
            px = pd.Series(g["prix"].to_numpy(), index=dates.to_numpy()).groupby(level=0).last()
        px = px.reindex(jours.union(px.index)).ffill().bfill().reindex(jours)
        valeur = valeur + (qte * px).fillna(0.0)

    f = flux.groupby("date")[["delta_cash", "delta_apports"]].sum()
    cum = f.reindex(jours.union(f.index)).fillna(0.0).cumsum().reindex(jours)
    return pd.DataFrame({
        "date": jours,
        "valeur": valeur.to_numpy() + cum["delta_cash"].to_numpy(),
        "apports": cum["delta_apports"].to_numpy(),
    })
