"""Tests des calculs purs (aucun réseau, aucune dépendance à Streamlit)."""
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calculs as C  # noqa: E402


def _trans(rows):
    return pd.DataFrame(rows, columns=["date", "isin", "type", "quantite", "prix", "frais"]).assign(
        date=lambda d: pd.to_datetime(d["date"]))


def test_isin_valide():
    assert C.isin_valide("FR0013412012")
    assert C.isin_valide("fr001400u5q4")          # insensible à la casse
    assert not C.isin_valide("FR0013412013")      # clé de contrôle fausse
    assert not C.isin_valide("")
    assert not C.isin_valide(None)


def test_prm_inclut_les_frais():
    pos, ventes = C.calcul_positions(_trans([
        ("2026-01-02", "FR0013412012", "ACHAT", 10, 10.0, 2.0),
        ("2026-01-03", "FR0013412012", "ACHAT", 10, 12.0, 0.0)]))
    assert ventes.empty
    assert math.isclose(pos.iloc[0]["prm"], (100 + 2 + 120) / 20)


def test_vente_reduit_le_cout_au_prm_et_calcule_la_pv():
    pos, ventes = C.calcul_positions(_trans([
        ("2026-01-02", "FR0013412012", "ACHAT", 10, 10.0, 0.0),
        ("2026-01-03", "FR0013412012", "VENTE", 4, 15.0, 0.0)]))
    assert math.isclose(ventes.iloc[0]["pv"], 4 * 15 - 4 * 10)
    assert math.isclose(pos.iloc[0]["prm"], 10.0)  # le PRM ne bouge pas après une vente
    assert math.isclose(pos.iloc[0]["quantite"], 6)


def test_vente_superieure_a_la_quantite_detenue():
    try:
        C.calcul_positions(_trans([
            ("2026-01-02", "FR0013412012", "ACHAT", 1, 10.0, 0.0),
            ("2026-01-03", "FR0013412012", "VENTE", 2, 10.0, 0.0)]))
    except ValueError:
        return
    raise AssertionError("ValueError attendue")


def test_cash_et_apports():
    trans = _trans([("2026-01-02", "FR0013412012", "ACHAT", 10, 10.0, 1.0)])
    div = pd.DataFrame({"date": pd.to_datetime(["2026-02-01"]), "isin": ["FR0013412012"], "montant": [5.0]})
    vers = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                         "type": ["VERSEMENT", "PV_ANTERIEURE"], "montant": [1000.0, 200.0],
                         "libelle": [None, None]})
    flux = C.flux_tresorerie(trans, div, vers)
    assert math.isclose(flux["delta_cash"].sum(), 1000 + 200 - 101 + 5)
    assert math.isclose(flux["delta_apports"].sum(), 1000)  # la PV antérieure n'est pas un apport


def test_nettoyer_url():
    assert C.nettoyer_url(None) is None
    assert C.nettoyer_url(float("nan")) is None          # NaN renvoyé par pandas
    assert C.nettoyer_url("   ") is None
    assert C.nettoyer_url("javascript:alert(1)") is None
    assert C.nettoyer_url("ftp://exemple.com") is None
    assert C.nettoyer_url(" https://exemple.com/a ") == "https://exemple.com/a"
    assert ")" not in C.nettoyer_url("https://exemple.com/a_(b)")  # ne casse pas le lien Markdown


def test_twr_neutralise_les_versements():
    snap = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
                         "valeur": [1000.0, 2000.0, 2200.0], "apports": [1000.0, 2000.0, 2000.0]})
    twr = C.calcul_twr(snap)
    assert math.isclose(twr["twr"].iloc[1], 100.0)        # +1000 € de versement, aucune performance
    assert math.isclose(twr["twr"].iloc[2], 110.0)        # +10 % sur 2000 €


def test_formater_gros_nombre():
    assert C.formater_gros_nombre(None) == "N/A"
    assert C.formater_gros_nombre(1.54e9).endswith("Md €")
    assert C.formater_gros_nombre(14.6e6).endswith("M €")
