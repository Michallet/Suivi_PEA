"""Scénarios de caractérisation : chaque entrée appelle du code pur sur des données fictives.

`python -m tests.generer_golden` écrit les résultats dans tests/golden/caracterisation.json
(à ne faire QUE sur le code d'origine) ; tests/test_caracterisation.py les rejoue après chaque changement.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from tests import fictives as F
from tests import modules as M

SCENARIOS: dict = {}


def scenario(f):
    SCENARIOS[f.__name__] = f
    return f


def capter(fonction, *a, **k):
    try:
        return fonction(*a, **k)
    except Exception as e:  # on fige aussi les messages d'erreur affichés à l'utilisateur
        return {"__erreur__": type(e).__name__, "message": str(e)}


# --------------------------------------------------------------------------- #
# calculs
# --------------------------------------------------------------------------- #
@scenario
def calculs_isin_valide():
    C = M.calculs()
    cas = [F.ALPHA, F.BETA, F.ALPHA.lower(), " " + F.DELTA + " ", F.ALPHA[:-1] + "0" if F.ALPHA[-1] != "0" else F.ALPHA[:-1] + "1",
           "", None, "FR0000121014", "US0378331005", "XX", "FR00ALPHA01", "1R00ALPHA011"]
    return {str(c): C.isin_valide(c) for c in cas}


@scenario
def calculs_gros_nombres():
    f = M.formats().formater_gros_nombre
    cas = [None, float("nan"), 0, 999, 1234.5, 1_500_000, -2_300_000_000, 4.2e12, 999_999.9, 1e9]
    return {str(c): f(c) for c in cas}


@scenario
def calculs_positions_journal():
    C = M.calculs()
    pos, ventes = C.calcul_positions(F.journal())
    return {"positions": pos, "ventes": ventes}


@scenario
def calculs_positions_vide():
    C = M.calculs()
    pos, ventes = C.calcul_positions(F.journal().iloc[0:0])
    pos2, ventes2 = C.calcul_positions(None)
    return {"v": [pos, ventes], "n": [pos2, ventes2]}


@scenario
def calculs_vente_excessive():
    C = M.calculs()
    j = pd.concat([F.journal(), pd.DataFrame([{"date": pd.Timestamp("2025-06-02"), "isin": F.ALPHA, "type": "VENTE",
                                                "quantite": 50.0, "prix": 1.0, "frais": 0.0}])], ignore_index=True)
    return capter(C.calcul_positions, j)


@scenario
def calculs_enrichir_positions():
    C = M.calculs()
    pos, _ = C.calcul_positions(F.journal())
    div = F.dividendes().groupby("isin")["montant"].sum()
    return C.enrichir_positions(pos, F.cours(), div)


@scenario
def calculs_flux_et_synthese():
    C = M.calculs()
    j, d, v = F.journal(), F.dividendes(), F.versements()
    pos, _ = C.calcul_positions(j)
    enr = C.enrichir_positions(pos, F.cours(), d.groupby("isin")["montant"].sum())
    flux = C.flux_tresorerie(j, d, v)
    return {"flux": flux, "synthese": C.synthese(enr, flux, v),
            "synthese_vide": C.synthese(enr.iloc[0:0], C.flux_tresorerie(j.iloc[0:0], d.iloc[0:0], v.iloc[0:0]), v.iloc[0:0])}


@scenario
def calculs_twr():
    C = M.calculs()
    snap = pd.DataFrame({"date": pd.bdate_range("2025-01-02", periods=8),
                         "valeur": [1000.0, 1010, 1520, 1500, 1525, 1450, 0.0, 800.0],
                         "apports": [1000.0, 1000, 1500, 1500, 1500, 1500, 0.0, 800.0]})
    return C.calcul_twr(snap)


@scenario
def calculs_reconstitution():
    C = M.calculs()
    j, d, v = F.journal(), F.dividendes(), F.versements()
    flux = C.flux_tresorerie(j, d, v)
    res = C.reconstituer_snapshots(j, flux, F.historique_prix(), F.TICKERS, fin="2025-06-30")
    return {"n": len(res), "tete": res.head(6), "queue": res.tail(6),
            "vide": C.reconstituer_snapshots(j.iloc[0:0], flux, {}, {})}


@scenario
def calculs_scenario():
    C = M.calculs()
    j, d, v = F.journal(), F.dividendes(), F.versements()
    sim = pd.DataFrame([{"isin": F.ALPHA, "type": "VENTE", "quantite": 3.0, "prix": 150.0},
                        {"isin": F.BETA, "type": "ACHAT", "quantite": 10.0, "prix": 31.0}])
    pos, ventes, cash = C.appliquer_scenario(j, sim, d, v, 250.0, "2025-06-30")
    sim_ko = pd.DataFrame([{"isin": F.ALPHA, "type": "VENTE", "quantite": 99.0, "prix": 150.0}])
    return {"pos": pos, "ventes": ventes, "cash": cash,
            "sans_sim": C.appliquer_scenario(j, None, d, v, 0.0, "2025-06-30")[2],
            "erreur": capter(C.appliquer_scenario, j, sim_ko, d, v, 0.0, "2025-06-30")}


@scenario
def calculs_repartitions():
    C = M.calculs()
    pos, _ = C.calcul_positions(F.journal())
    enr = C.enrichir_positions(pos, F.cours(), pd.Series(dtype=float))
    enr["secteur"] = [F.SECTEURS[i] for i in enr["isin"]]
    reel = C.repartition(enr, 321.0)
    proj = C.repartition(enr.iloc[:-1], 50.0)
    return {"reel": reel, "proj": proj, "cmp_label": C.comparer_repartitions(reel, proj, "label"),
            "cmp_sect": C.comparer_repartitions(reel, proj, "secteur"),
            "vide": C.repartition(enr.iloc[0:0], 0.0)}


@scenario
def calculs_notes_relatives():
    C = M.calculs()
    nan = float("nan")
    cas = {
        "tous": [10.0, 20.0, 15.0, 5.0],
        "egalites": [10.0, 10.0, 20.0, 5.0, 5.0],
        "absents": [10.0, nan, 20.0, None, 15.0],
        "un_seul": [12.0, nan, nan],
        "un_seul_plein": [12.0],
        "aucun": [nan, nan],
        "inf": [10.0, float("inf"), 20.0],
        "texte": ["10", "abc", "20"],
    }
    return {k + sens: C.note_relative(pd.Series(v), bas) for k, v in cas.items()
            for sens, bas in (("_bas", True), ("_haut", False))}


# --------------------------------------------------------------------------- #
# formats et petites aides d'affichage (extraites d'app.py avant la refonte)
# --------------------------------------------------------------------------- #
@scenario
def formats_nombres():
    m = M.formats()
    cas = [(1234.567, 2, False), (-1234.567, 2, True), (0, 0, True), (None, 2, False),
           (float("nan"), 1, True), (1_000_000, 0, False), (0.005, 2, False), (np.float64(12.3456), 3, False)]
    return {"fmt": [m.fmt(*c) for c in cas],
            "pastille": [m.pastille(1.0, "x"), m.pastille(0.0, "y"), m.pastille(-0.1, "z")]}


@scenario
def formats_noms_et_liens():
    m = M.formats()
    noms = pd.Series(["Amundi PEA Monde (MSCI World) UCITS ETF", "Alpha  (A) (B)  SA", "Simple", "  Espaces  "])
    return {"sans_parentheses": m.sans_parentheses(noms),
            "court": [m._court("Amundi PEA Monde (MSCI World) UCITS ETF"), m._court("Court", 10)],
            "url": m.url_google_actualites("L'Oréal & Cie"),
            "lien": [m.lien_actualites("Alpha SA"), m.lien_actualites(""), m.lien_actualites(None)],
            "cellules": [m._cellule(None, "x"), m._cellule(12.34, "x"), m._cellule(12.34, "%"), m._cellule(2.5e9, "montant")]}


@scenario
def formats_fondamentaux_et_etf():
    m = M.formats()
    f1 = {"per": 18.2, "per_prev": 15.0, "ca": 2.5e9, "net_income": 3.1e8, "ebitda": 5e8, "capi": 8e9,
          "ev": 9e9, "ev_ebitda": 18.0, "net_assets": None, "expense_ratio": None}
    f_etf = {"net_assets": 1.2e9, "expense_ratio": 0.0015}
    return {"lignes": m.lignes_fondamentaux(f1), "lignes_etf": m.lignes_fondamentaux(f_etf),
            "vide": m.lignes_fondamentaux(None),
            "est_etf": [m.est_etf("Gamma Monde UCITS ETF", None), m.est_etf("Alpha SA", f1),
                        m.est_etf("Autre", f_etf), m.est_etf(None, {}), m.est_etf("Etf quelque chose", {})],
            "grandeurs": {k: m.valeur_grandeur(f1, k) for k in ("per", "per_prev", "ev_ebitda", "p_ca", "marge", "net_income", "ca", "capi")},
            "deficitaire": {k: m.valeur_grandeur({"per": -3.0, "ev_ebitda": 0.0, "net_income": -5.0, "ca": 10.0, "capi": 4.0}, k)
                            for k in ("per", "ev_ebitda", "marge", "net_income", "p_ca")}}


# --------------------------------------------------------------------------- #
# technique
# --------------------------------------------------------------------------- #
@scenario
def technique_series():
    T = M.technique()
    hausse = F.serie_prix(1, derive=0.002, vol=0.006)
    baisse = F.serie_prix(2, derive=-0.002, vol=0.006)
    plat = F.serie_prix(3, derive=0.0, vol=0.01)
    court = F.serie_prix(4, n=30)
    trop_court = F.serie_prix(5, n=10)
    return {"hausse": T.analyser(hausse), "baisse": T.analyser(baisse), "plat": T.analyser(plat),
            "court": T.analyser(court), "trop_court": T.analyser(trop_court), "none": T.analyser(None),
            "colonnes": T.analyser(hausse[["Close"]]),
            "resume": [T.resume(T.analyser(hausse)), T.resume(None), T.resume({"ok": False})]}


@scenario
def technique_indicateurs():
    T = M.technique()
    d = F.serie_prix(11)
    k, dd = T.stochastique(d["High"], d["Low"], d["Close"])
    return {"rsi_fin": T.rsi(d["Close"]).tail(5), "sma20_fin": T.sma(d["Close"], 20).tail(3),
            "stoch_k": k.tail(4), "stoch_d": dd.tail(4), "bb": T.bollinger(d["Close"]).tail(3),
            "rsi_court": T.rsi(d["Close"].iloc[:10]),
            "constante": T.rsi(pd.Series([5.0] * 40)).tail(2)}


@scenario
def technique_courbes():
    T = M.technique()
    pts = [-10, 0, 10, 25, 30, 35, 40, 50, 60, 65, 70, 80, 90, 120]
    return {"rsi": [T._courbe(p, T.COURBE_RSI) for p in pts],
            "stoch": [T._courbe(p, T.COURBE_STOCH) for p in pts],
            "pb": [T._courbe(p / 50, T.COURBE_PB) for p in pts],
            "poids": T.POIDS, "seuils": [T.NOTE_ACHAT, T.NOTE_VENTE, T.SEUIL_INDICATEUR, T.MIN_BOUGIES]}


# --------------------------------------------------------------------------- #
# import par captures
# --------------------------------------------------------------------------- #
def _releve_brut():
    return {"lignes": [
        {"nom": "Alpha SA", "isin_capture": F.ALPHA, "isin_ia": "", "quantite": 11, "prm": "107,50", "valeur": "1 540,00"},
        {"nom": "Beta Industries AG", "isin_capture": "", "isin_ia": F.BETA, "quantite": 20, "prm": 30.25, "valeur": 600},
        {"nom": "Alpha SA", "isin_capture": F.ALPHA, "isin_ia": "", "quantite": 11, "prm": 107.5, "valeur": 1540},
        {"nom": "Gamma Monde UCITS…", "isin_capture": "", "isin_ia": "", "quantite": 5, "prm": 50.0, "valeur": 260},
        {"nom": "Inconnue Corp", "isin_capture": "XX0000000000", "isin_ia": "", "quantite": 3, "prm": 9.9, "valeur": 30},
        {"nom": "Illisible", "isin_capture": "", "isin_ia": "", "quantite": 0, "prm": 5.0, "valeur": 5},
        "pas un dict",
        {"nom": "Delta Santé NV", "isin_capture": "", "isin_ia": "", "quantite": 8, "prm": 75.75, "valeur": 640},
        {"nom": "Machin", "isin_capture": "", "isin_ia": F.EPSILON, "quantite": 150, "prm": 12.5, "valeur": 1900},
    ]}


@scenario
def import_normaliser():
    IE = M.import_ecran()
    lignes, avert = IE.normaliser_releve(_releve_brut())
    return {"lignes": lignes, "avert": avert, "mauvais": IE.normaliser_releve({"x": 1}),
            "none": IE.normaliser_releve(None), "image": [
                IE.type_image_reel(b"\x89PNG\r\n\x1a\nxxxx"), IE.type_image_reel(b"\xff\xd8\xff\xe0"),
                IE.type_image_reel(b"RIFF1234WEBPzzz"), IE.type_image_reel(b"GIF89a"), IE.type_image_reel(b"")],
            "nombre": [(getattr(IE, "_nombre", None) or IE.nombre)(x) for x in ("1 859,86", "1859.86", " 12 € ", True, None, "abc", 3, float("nan"), "")]}


@scenario
def import_noms():
    IE = M.import_ecran()
    return {"normaliser_nom": [IE._normaliser_nom(n) for n in ("Amundi PEA Monde UCITS ETF Acc", "Société Générale…", "")],
            "proches": [IE.noms_proches("Siemens", "SIEMENS AG"), IE.noms_proches("Siemens Energy", "SIEMENS AG"),
                        IE.noms_proches("", "x"), IE.noms_proches("Alpha SA", "Alpha SA Holding", 0.9)],
            "score": IE._score_nom(["alpha", "monde"], False, ["alpha", "monde", "etf"])}


def _suite_import():
    IE, C = M.import_ecran(), M.calculs()
    lignes, _ = IE.normaliser_releve(_releve_brut())
    pos, _ = C.calcul_positions(F.journal())
    noms = dict(F.NOMS)
    releve = IE.resoudre_isins(lignes, noms, pos)
    return IE, C, releve, pos


@scenario
def import_resoudre_et_proposer():
    IE, C, releve, pos = _suite_import()
    cours = {F.ALPHA: 140.0, F.GAMMA: 52.0, F.BETA: 31.0}
    ops = IE.proposer_operations(releve, pos, cours, dt.date(2025, 6, 2))
    return {"releve": releve, "ops": ops}


@scenario
def import_preparer_et_ecarts():
    IE, C, releve, pos = _suite_import()
    ops = IE.proposer_operations(releve, pos, {F.ALPHA: 140.0}, dt.date(2025, 6, 2))
    ops = ops.copy()
    ops["valider"] = True
    ops.loc[ops["isin"] == "", "isin"] = "ZZ"  # ISIN invalide volontaire
    ops.loc[ops.index[-1], "date"] = dt.date(2099, 1, 1)
    nouvelles, erreurs = IE.preparer_insertions(ops)
    ok = IE.proposer_operations(releve, pos, {F.ALPHA: 140.0}, dt.date(2025, 6, 2))
    ok = ok[ok["isin"] != ""].copy()
    ok["valider"] = True
    ins, err2 = IE.preparer_insertions(ok)
    apres, _ = C.calcul_positions(pd.concat([F.journal(), ins.assign(frais=ins["frais"].fillna(0.0))], ignore_index=True))
    return {"erreurs": erreurs, "n_nouvelles": len(nouvelles), "ins": ins, "err2": err2,
            "ecarts_avant": IE.ecarts_apres(releve, pos), "ecarts_apres": IE.ecarts_apres(releve, apres)}


@scenario
def import_controle_lecture():
    IE = M.import_ecran()
    base = {"quantite": 10.0, "prm": 100.0}
    return [IE.controle_lecture({**base, "valeur": 1000.0}, 100.0), IE.controle_lecture({**base, "valeur": 1500.0}, 100.0),
            IE.controle_lecture({**base, "valeur": 1500.0}, None), IE.controle_lecture({**base, "valeur": 4000.0}, None),
            IE.controle_lecture({**base, "valeur": None}, 100.0), IE.controle_lecture({"quantite": 0.0, "prm": 1.0, "valeur": 5.0}, 1.0)]


# --------------------------------------------------------------------------- #
# concurrents (partie pure)
# --------------------------------------------------------------------------- #
@scenario
def concurrents_candidats_et_choix():
    CO = M.concurrents()
    brut = {"candidats": [
        {"nom": "Beta  Industries AG", "isin": F.BETA.lower(), "raison": "  même   métier "},
        {"nom": "Faux", "isin": "FR0000000000", "raison": ""},
        {"nom": "Beta bis", "isin": F.BETA, "raison": "doublon"},
        {"nom": "Delta Santé NV", "isin": F.DELTA, "raison": "x"},
        {"nom": "Epsilon", "isin": F.EPSILON, "raison": "y"},
        {"nom": "Alpha SA", "isin": F.ALPHA, "raison": "z"}, "bizarre"]}
    cands = CO.normaliser_candidats(brut)

    def resoudre(isin):
        if isin == F.BETA:
            return {"ticker": "BET.DE", "nom": "Entreprise totalement différente"}
        if isin == F.DELTA:
            return {"ticker": "DEL.AS", "nom": "DELTA SANTE NV"}
        raise RuntimeError("réseau")

    return {"candidats": cands, "choix": CO.choisir_concurrent(cands, F.ALPHA, resoudre),
            "choix_aucun": CO.choisir_concurrent(cands, F.ALPHA, lambda i: None),
            "memetitre": CO.choisir_concurrent(cands[:1], F.BETA, resoudre),
            "invalide": capter(CO.normaliser_candidats, {"candidats": "x"})}


@scenario
def concurrents_manuel_et_comparaison():
    CO = M.concurrents()
    res = lambda isin, tk=None: {"ticker": tk or "XXX.PA", "nom": "Nom Yahoo"} if (tk or isin) != "RIEN" else None
    f1 = {"per": 20.0, "per_prev": 18.0, "ev_ebitda": 12.0, "net_income": 100.0, "ebitda": 300.0, "ca": 1000.0, "capi": 5e9, "devise": "EUR"}
    f2 = {"per": 15.0, "per_prev": None, "ev_ebitda": 9.0, "net_income": 50.0, "ebitda": 200.0, "ca": 0, "capi": 2e9, "devise": "EUR"}
    return {"manuel": [CO.preparer_concurrent(F.DELTA, "", F.ALPHA, res), CO.preparer_concurrent("", "sie.de", F.ALPHA, res),
                       CO.preparer_concurrent("", "", F.ALPHA, res), CO.preparer_concurrent("FR12", "", F.ALPHA, res),
                       CO.preparer_concurrent(F.ALPHA, "", F.ALPHA, res), CO.preparer_concurrent("", "RIEN", F.ALPHA, res)],
            "lignes": CO.lignes_comparaison(f1, f2), "lignes_usd": CO.lignes_comparaison({**f1, "devise": "USD"}, f2),
            "lignes_vide": CO.lignes_comparaison(None, None),
            "contexte": CO.construire_contexte("Alpha SA", F.ALPHA, {"secteur_yahoo": "Consumer", "industrie": "Luxury", "capi": 5e9}),
            "contexte_min": CO.construire_contexte("X", F.BETA, None)}


# --------------------------------------------------------------------------- #
# IA : fonctions pures (aucun appel réseau)
# --------------------------------------------------------------------------- #
def _pos_ia():
    C = M.calculs()
    pos, _ = C.calcul_positions(F.journal())
    enr = C.enrichir_positions(pos, F.cours(), pd.Series(dtype=float))
    enr["secteur"] = [F.SECTEURS[i] for i in enr["isin"]]
    return enr


@scenario
def ia_contextes():
    L = M.ia_pure()
    p = _pos_ia()
    per = {F.ALPHA: 18.5, F.GAMMA: None}
    t1, h1 = L.construire_contexte(p, 321.0, per, "modele-x")
    t2, h2 = L.construire_contexte(p, 321.0, per, "modele-y")
    ts, hs = L.construire_contexte_scenario(p.iloc[:-1], 10.0, per, p, 321.0, per, "modele-x", 3, "ACHAT 1 × Alpha", 250.0)
    return {"ctx": [t1, h1], "autre_modele": h2, "scen": [ts, hs],
            "vide": capter(L.construire_contexte, p.iloc[0:0], 0.0, {}, "m")}


def _critere(cle, note, synthese="ok", **x):
    return {"cle": cle, "note": note, "synthese": synthese, **x}


@scenario
def ia_validation():
    L = M.ia_pure()
    cles = L.CLES
    bon = {"criteres": [_critere(c, 7.4 + i, "mot " * 40, avantages=["a " * 30, "", "b", "c"], inconvenients=["z"])
                        for i, c in enumerate(cles)], "conclusion": "phrase " * 50}
    manquant = {"criteres": bon["criteres"][:2], "conclusion": "x"}
    note_ko = {"criteres": [_critere(cles[0], "abc")], "conclusion": ""}
    res = L.valider_resultat(bon, comparer=True)
    return {"res": res, "simple": L.valider_resultat(bon), "manquant": capter(L.valider_resultat, manquant),
            "note_ko": capter(L.valider_resultat, note_ko), "pas_dict": capter(L.valider_resultat, []),
            "note_globale": L.note_globale(res),
            "bornes": [c["note"] for c in L.valider_resultat({"criteres": [_critere(c, v) for c, v in zip(cles, (-5, 99, 3.5, 4.5))],
                                                              "conclusion": ""})["criteres"]]}


@scenario
def ia_json_et_reponses():
    L = M.ia_pure()
    class R:  # fausse réponse HTTP
        def __init__(self, code, corps=None):
            self.status_code, self._c = code, corps
        def json(self):
            if self._c is None:
                raise ValueError("pas de json")
            return self._c
    ok = R(200, {"candidates": [{"content": {"parts": [{"text": "a", "thought": True}, {"text": "b"}, {"text": "c"}]}}]})
    return {"parser": [L._parser_json('```json\n{"a": 1}\n```'), capter(L._parser_json, "rien"), capter(L._parser_json, "{pas json}")],
            "tronquer": [L._tronquer_mots("un deux trois quatre", 2), L._tronquer_mots("  un   deux ", 5)],
            "majuscules": L._en_majuscules({"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "array", "items": {"type": "number"}}}}),
            "payload": L._payload_json("sys", [{"text": "q"}], {"type": "object"}, "response_schema", 123),
            "payload2": L._payload_json("sys", [{"text": "q"}], {"type": "object"}, "json_schema", 123),
            "reponses": {str(c): capter(L._texte_reponse, R(c, {"error": {"message": "détail"}}), "m") for c in (401, 403, 404, 429, 500, 503, 400)},
            "texte_ok": L._texte_reponse(ok, "m"),
            "texte_vide": capter(L._texte_reponse, R(200, {"candidates": []}), "m")}


@scenario
def ia_reessai_et_limites():
    L = M.ia_pure()
    essais = {"n": 0}
    def instable():
        essais["n"] += 1
        if essais["n"] < 2:
            raise L.ErreurIA("illisible")
        return "bon"
    def definitif():
        essais["n"] += 100
        raise L.ErreurIA("Clé API refusée")
    r1 = L.avec_reessai(instable)
    n1 = essais["n"]
    essais["n"] = 0
    r2 = capter(L.avec_reessai, definitif)
    return {"instable": [r1, n1], "definitif": [r2, essais["n"]],
            "limites": [L.MAX_APPELS_PAR_JOUR, L.MAX_CHAT_PAR_JOUR, L.MAX_SUGGESTIONS_PAR_JOUR, L.MAX_IMPORTS_PAR_JOUR,
                        L.MAX_CAPTURES, L.MAX_OCTETS_CAPTURES, L.MODELE_DEFAUT, L.VERSION_PROMPT],
            "captures": [capter(L.extraire_capture, [], "k"), capter(L.extraire_capture, [(b"x", "image/gif")], "k"),
                         capter(L.extraire_capture, [(b"x", "image/png")] * 9, "k"),
                         capter(L.extraire_capture, [(b"x" * (16 * 1024 * 1024), "image/png")], "k")]}


@scenario
def ia_prompts_fichier():
    L = M.ia_pure()
    p = L.charger_prompts_md()
    return {"sections": sorted(p), "tailles": {k: len(v) for k, v in sorted(p.items())},
            "defaut_analyse": len(L.SYSTEME_DEFAUT), "defaut_scen": len(L.SYSTEME_SCENARIO_DEFAUT),
            "defaut_capture": len(L.SYSTEME_CAPTURE_DEFAUT), "defaut_chat": len(L.SYSTEME_CHAT_DEFAUT),
            "criteres": L.CRITERES, "exemple": L.EXEMPLE, "exemple_scen": L.EXEMPLE_SCENARIO,
            "avertissement": L.AVERTISSEMENT, "schema": L.SCHEMA_JSON, "schema_capture": L.SCHEMA_JSON_CAPTURE}
