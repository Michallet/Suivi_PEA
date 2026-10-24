"""Règles métier du README vérifiées avec des chiffres calculés À LA MAIN (données fictives)."""
import pandas as pd
import pytest

from tests import fictives as F
from tests import modules as M

C = M.calculs()


def _journal(*lignes):
    df = pd.DataFrame(lignes, columns=["date", "isin", "type", "quantite", "prix", "frais"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_prm_inclut_les_frais_d_achat():
    # 10 × 100 + 10 de frais = 1 010 ; PRM = 101
    pos, _ = C.calcul_positions(_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 10.0)))
    assert pos.iloc[0]["cout"] == pytest.approx(1010.0)
    assert pos.iloc[0]["prm"] == pytest.approx(101.0)


def test_vente_au_prm_et_plus_value_realisee():
    # achat 10 @ 100 (+10) puis vente 4 @ 120 (frais 5) : produit net 475, coût cédé 404, PV 71 ; reste 6 × 101
    pos, ventes = C.calcul_positions(_journal(
        ("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 10.0), ("2025-02-02", F.ALPHA, "VENTE", 4.0, 120.0, 5.0)))
    assert ventes.iloc[0]["pv"] == pytest.approx(71.0)
    assert pos.iloc[0]["quantite"] == 6.0 and pos.iloc[0]["cout"] == pytest.approx(606.0)
    assert pos.iloc[0]["prm"] == pytest.approx(101.0)  # la vente ne change pas le PRM


def test_vente_superieure_a_la_quantite_est_refusee():
    with pytest.raises(ValueError, match="seulement 10 en portefeuille"):
        C.calcul_positions(_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 0.0),
                                    ("2025-01-03", F.ALPHA, "VENTE", 11.0, 100.0, 0.0)))


def test_ligne_soldee_repart_de_zero():
    pos, _ = C.calcul_positions(_journal(
        ("2025-01-02", F.ALPHA, "ACHAT", 5.0, 100.0, 0.0), ("2025-01-03", F.ALPHA, "VENTE", 5.0, 110.0, 0.0),
        ("2025-01-04", F.ALPHA, "ACHAT", 2.0, 50.0, 0.0)))
    assert pos.iloc[0]["prm"] == pytest.approx(50.0)


def test_cash_apports_et_pv_anterieure():
    # versement 1000, PV antérieure 200 (cash, pas apport), retrait 100, achat 5 × 100 + 5 de frais, dividende 20
    j = _journal(("2025-01-03", F.ALPHA, "ACHAT", 5.0, 100.0, 5.0))
    v = pd.DataFrame({"date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-10"]),
                      "type": ["VERSEMENT", "PV_ANTERIEURE", "RETRAIT"], "montant": [1000.0, 200.0, 100.0], "libelle": None})
    d = pd.DataFrame({"date": pd.to_datetime(["2025-01-20"]), "isin": [F.ALPHA], "montant": [20.0]})
    flux = C.flux_tresorerie(j, d, v)
    assert flux["delta_cash"].sum() == pytest.approx(1000 + 200 - 100 - 505 + 20)  # 615
    assert flux["delta_apports"].sum() == pytest.approx(900.0)  # 1000 - 100, sans la PV antérieure
    pos, _ = C.calcul_positions(j)
    cours = pd.DataFrame([{"isin": F.ALPHA, "ticker": "A", "nom": "Alpha", "prix": 110.0, "prev_close": 100.0, "statut": "live"}])
    s = C.synthese(C.enrichir_positions(pos, cours, pd.Series({F.ALPHA: 20.0})), flux, v)
    assert s["valeur_titres"] == pytest.approx(550.0) and s["valeur_totale"] == pytest.approx(1165.0)
    assert s["pv_globale"] == pytest.approx(265.0) and s["perf_pct"] == pytest.approx(265 / 900 * 100)
    assert s["versements_cumules"] == pytest.approx(1000.0)  # PV antérieure et retrait exclus du plafond
    assert s["plafond_pct"] == pytest.approx(1000 / 150_000 * 100)
    assert s["var_jour_eur"] == pytest.approx(50.0)


def test_statuts_de_cours_et_variation_du_jour():
    pos, _ = C.calcul_positions(_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 0.0),
                                         ("2025-01-02", F.BETA, "ACHAT", 10.0, 50.0, 0.0),
                                         ("2025-01-02", F.DELTA, "ACHAT", 10.0, 20.0, 0.0)))
    cours = pd.DataFrame([
        {"isin": F.ALPHA, "ticker": "A", "nom": "A", "prix": 110.0, "prev_close": 100.0, "statut": "live"},
        {"isin": F.BETA, "ticker": "B", "nom": "B", "prix": 55.0, "prev_close": 50.0, "statut": "obsolète"}])
    p = C.enrichir_positions(pos, cours, pd.Series(dtype=float)).set_index("isin")
    assert p.loc[F.ALPHA, "var_jour_eur"] == pytest.approx(100.0)       # live : variation du jour calculée
    assert p.loc[F.BETA, "var_jour_eur"] == pytest.approx(0.0)          # obsolète : aucune variation
    assert p.loc[F.DELTA, "statut"] == "estimé" and p.loc[F.DELTA, "valeur"] == pytest.approx(200.0)  # prix de revient
    assert p["poids_pct"].sum() == pytest.approx(100.0)


def test_twr_neutralise_les_versements():
    # J1 1 000 ; J2 : versement 1 000 investi dès l'ouverture, base 2 000 → 2 100 (+5 %) ; J3 : 2 100 → 2 310 (+10 %)
    snap = pd.DataFrame({"date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
                         "valeur": [1000.0, 2100.0, 2310.0], "apports": [1000.0, 2000.0, 2000.0]})
    assert C.calcul_twr(snap)["twr"].tolist() == pytest.approx([100.0, 105.0, 115.5])
    # +10 % sur 1 000, puis versement de 1 000 (base 2 100) → 2 310 (+10 %) : 100 × 1,1 × 1,1
    snap2 = snap.assign(valeur=[1000.0, 1100.0, 2310.0], apports=[1000.0, 1000.0, 2000.0])
    assert C.calcul_twr(snap2)["twr"].tolist() == pytest.approx([100.0, 110.0, 121.0])


def test_scenario_ne_modifie_pas_le_reel():
    j = F.journal()
    avant = j.copy()
    sim = pd.DataFrame([{"isin": F.ALPHA, "type": "VENTE", "quantite": 3.0, "prix": 150.0}])
    pos, _, cash = C.appliquer_scenario(j, sim, F.dividendes(), F.versements(), 0.0, "2025-06-30")
    pd.testing.assert_frame_equal(j, avant)
    reel_cash = C.flux_tresorerie(j, F.dividendes(), F.versements())["delta_cash"].sum()
    assert cash == pytest.approx(reel_cash + 450.0)
    assert pos.set_index("isin").loc[F.ALPHA, "quantite"] == 8.0


def test_notes_relatives():
    n = C.note_relative(pd.Series([10.0, 20.0, 30.0]), bas_est_bon=True)
    assert n.tolist() == [10.0, 5.5, 1.0]  # PER bas = 10
    n = C.note_relative(pd.Series([10.0, None, 30.0]), bas_est_bon=False)
    assert n.tolist() == [2.0, 1.0, 10.0]  # valeur absente = 1, les autres sur 2 → 10
    assert C.note_relative(pd.Series([float("nan")] * 2), True).tolist() == [1.0, 1.0]
    assert C.note_relative(pd.Series([4.0]), True).tolist() == [5.5]


def test_technique_note_et_verdict():
    T = M.technique()
    res = T.analyser(F.serie_prix(1, derive=0.002, vol=0.006))
    assert res["ok"] and 0 <= res["note"] <= 10
    assert res["verdict"] == ("Acheter" if res["note"] >= 6 else "Vendre" if res["note"] <= 4 else "Neutre")
    assert abs(sum(i["poids"] for i in res["indicateurs"]) - 1.0) < 1e-9
    assert not T.analyser(F.serie_prix(5, n=10))["ok"]
    # filtre de tendance : un oscillateur contraire à une tendance nette compte pour moitié
    for i in res["indicateurs"]:
        if i["attenue"]:
            assert i["score_note"] == pytest.approx(i["score"] * 0.5)


def test_import_prix_deduit_du_prm_du_courtier():
    IE = M.import_ecran()
    pos, _ = C.calcul_positions(_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 10.0)))  # coût 1 010
    releve = [{"nom": "Alpha SA", "isin": F.ALPHA, "source_isin": "capture", "quantite": 15.0, "prm": 104.0, "valeur": None}]
    ops = IE.proposer_operations(releve, pos, {F.ALPHA: 105.0}, pd.Timestamp("2025-06-02").date())
    # Δ = 5 ; prix = (104 × 15 − 1 010) / 5 = 110 : le PRM de l'app redevient 104
    assert ops.iloc[0]["type"] == "ACHAT" and ops.iloc[0]["quantite"] == 5.0 and ops.iloc[0]["prix"] == pytest.approx(110.0)
    nouvelle = pd.concat([_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 10.0)),
                          _journal(("2025-06-02", F.ALPHA, "ACHAT", 5.0, ops.iloc[0]["prix"], 0.0))], ignore_index=True)
    assert C.calcul_positions(nouvelle)[0].iloc[0]["prm"] == pytest.approx(104.0)


def test_import_ligne_absente_est_decochee():
    IE = M.import_ecran()
    pos, _ = C.calcul_positions(_journal(("2025-01-02", F.ALPHA, "ACHAT", 10.0, 100.0, 0.0)))
    ops = IE.proposer_operations([], pos, {}, pd.Timestamp("2025-06-02").date())
    assert ops.iloc[0]["type"] == "VENTE" and not ops.iloc[0]["valider"]


def test_isin_fictifs_valides():
    assert all(C.isin_valide(i) for i in (F.ALPHA, F.BETA, F.GAMMA, F.DELTA, F.EPSILON))
