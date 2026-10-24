"""Suivi PEA — interface Streamlit mobile-first multi-utilisateur.

Les comptes sont définis dans .streamlit/secrets.toml. Le compte demo lit un jeu de données fictif
en base, en lecture seule (ses modifications restent dans la session) et n'a pas accès à l'IA.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import logging

from pea import config
from pea.data import marche as D
from pea.data import repo as db
from pea.data.schema import TABLES_COMPTE
from pea.services import auth, partage, quotas, suivi
from pea.domain import calculs as C
from pea.domain import concurrents as CONC
from pea.domain import import_ecran as IE
from pea.domain import technique as TECH
from pea.domain.fondamentaux import GRANDEURS, est_etf, lignes_fondamentaux, valeur_grandeur
from pea.domain.formats import (cellule as _cellule, court as _court, fmt, formater_gros_nombre, lien_actualites,
                                pastille, sans_parentheses)
from pea.domain.textes import echapper_markdown as esc
from pea.domain.textes import nettoyer_sortie_ia, sur_pour_graphique
from pea.services import ia as llm
from pea.ui import style
from pea.data.schema import SCHEMA

journal = logging.getLogger("pea.app")

# layout="wide" : plein écran sur mobile comme avant ; sur tablette / PC, style.py centre le contenu
# (1 320 px max), met les listes de cartes en grille et les graphiques côte à côte.
st.set_page_config(page_title="Suivi PEA", page_icon="📈", layout="wide")
style.appliquer()
db.initialiser()  # client Supabase créé dans le fil principal (avant tout fil d'arrière-plan)
CHRONO = {"debut": time.perf_counter()}  # affiché en bas de page si le secret DEBUG_PERF est activé



def jalon(nom: str) -> None:
    CHRONO[nom] = time.perf_counter()



SEUIL_CONCENTRATION = config.SEUIL_CONCENTRATION
BENCHMARKS = config.BENCHMARKS
PARIS = ZoneInfo("Europe/Paris")
PLOTLY = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False}
NOUVEL_ISIN = "➕ Nouvel ISIN…"
LIBELLES_VERS = {"VERSEMENT": "Versement", "RETRAIT": "Retrait",
                 "PV_ANTERIEURE": "Plus-value antérieure réinvestie (hors apports)"}

CFG = {
    "transactions": {
        "id": None,
        "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
        "isin": st.column_config.TextColumn("ISIN", required=True),
        "type": st.column_config.SelectboxColumn("Type", options=["ACHAT", "VENTE"], required=True),
        "quantite": st.column_config.NumberColumn("Qté", min_value=0.0001, required=True),
        "prix": st.column_config.NumberColumn("Prix €", min_value=0.0, required=True),
        "frais": st.column_config.NumberColumn("Frais €", min_value=0.0),
    },
    "dividendes": {
        "id": None,
        "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
        "isin": st.column_config.TextColumn("ISIN", required=True),
        "montant": st.column_config.NumberColumn("Montant net €", min_value=0.01, required=True),
    },
    "versements": {
        "id": None,
        "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
        "type": st.column_config.SelectboxColumn("Type", options=list(LIBELLES_VERS), required=True),
        "montant": st.column_config.NumberColumn("Montant €", min_value=0.01, required=True),
        "libelle": st.column_config.TextColumn("Libellé"),
    },
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def maintenant() -> datetime:
    return datetime.now(PARIS)


def flash(msg: str) -> None:
    """Message affiché (toast) après le prochain rechargement."""
    st.session_state["flash"] = msg


def nom_de(tmap: pd.DataFrame, isin: str) -> str:
    n = tmap.loc[isin, "nom"] if isin in tmap.index else None
    return isin if n is None or pd.isna(n) else n


def enregistrer_ticker(isin: str, ticker: str, nom: str | None = None, suggerer: bool = True) -> str | None:
    """Valide puis mémorise ISIN -> ticker. Retourne un message d'erreur ou None.

    À la CRÉATION d'un titre (ISIN encore inconnu), propose un concurrent via l'IA (une seule fois) si
    `suggerer` ; les créations en lot (import, maintenance) passent `suggerer=False`.
    """
    v = D.valider_ticker(ticker, nom)
    if v is None:
        return f"Aucun cours trouvé pour « {ticker} »."
    if v["devise"] not in (None, "EUR"):
        return f"« {ticker} » cote en {v['devise']} : indiquez la cotation européenne en € (ex : MC.PA)."
    nouveau = isin not in tmap.index
    db.upsert("tickers", [{"isin": isin, "ticker": ticker, "nom": v["nom"], "dernier_prix": v["prix"],
                           "dernier_prix_at": maintenant().isoformat()}], "isin")
    if suggerer and nouveau:
        suggerer_a_la_creation(isin, ticker, v["nom"])
    return None


# --------------------------------------------------------------------------- #
# Authentification : tout compte connecté utilise Supabase ; seule l'IA est interdite en démo.
# --------------------------------------------------------------------------- #
auth.connecter_demo_par_defaut()  # interrupteur auth.CONNEXION_DEMO_AUTO (ou secret AUTO_CONNEXION_DEMO)
mode_demo = auth.est_demo()

if not auth.connecte():
    with st.container(key="connexion"):
        st.title("📈 Suivi PEA")
        st.info("Connectez-vous pour accéder à un portefeuille. Les identifiants du compte démo "
                "sont préremplis (demo / demo) : « Entrer » suffit pour revenir à la démo.")
        auth.formulaire_connexion()
    st.stop()

# Tous les comptes (demo compris) passent par le même stockage, filtré par db.py sur user_id.
if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))
if "flash_conc" in st.session_state:
    st.toast(st.session_state.pop("flash_conc"), icon="⚖️")

with st.container(key="entete"):
    t1, t2, t3 = st.columns([4, 1, 1], vertical_alignment="center")
    t1.title("📈 Mon PEA")
    t1.caption(f"Compte : {auth.utilisateur()}")
    if t2.button("🔄", help="Actualiser les cours"):
        db.invalider_compte()  # uniquement le compte courant ; le marché suit sa propre fraîcheur
        st.session_state["_actualiser_cours"] = True
        st.rerun()
    # Le verrou fait quitter le compte courant ; en démo, il ouvre le formulaire de connexion.
    if t3.button("🔒", key="btn_verrou",
                 help="Se connecter à un compte personnel" if mode_demo else "Se déconnecter"):
        auth.deconnecter()
        st.rerun()
if mode_demo:
    # Le bandeau est cliquable : même effet que le verrou.
    if st.button("🧪 **Mode démo** : portefeuille fictif · touchez ici pour vous connecter",
                 key="btn_bandeau_demo",
                 help="Vos ajouts et suppressions restent dans votre session : rien n'est enregistré en base "
                      "et les autres visiteurs ne les voient pas. Les cours de marché peuvent être réels. "
                      "Les fonctions IA sont désactivées."):
        auth.deconnecter()
        st.rerun()
    st.caption("Vos modifications ne sont visibles que par vous et disparaissent à la fin de la session. "
               "IA désactivée.")

# --------------------------------------------------------------------------- #
# Chargement des données
# --------------------------------------------------------------------------- #
db.precharger(TABLES_COMPTE)  # un seul aller-retour (fonction SQL) ou lectures parallèles ; rien si cache frais
try:
    trans, div, vers = db.lire("transactions"), db.lire("dividendes"), db.lire("versements")
    tick, sect, snaps = db.lire("tickers"), db.lire("secteurs"), db.lire("snapshots")
except Exception as e:  # pas de détail à l'écran : il pourrait contenir des infos sensibles
    st.error("Connexion à la base impossible. Vérifiez SUPABASE_URL et SUPABASE_KEY dans les "
             "secrets, et que schema.sql a bien été exécuté.")
    st.caption(f"Type d'erreur : {type(e).__name__}")
    st.stop()

tables_manquantes = []


def lire_sur(table: str) -> pd.DataFrame:
    """Tables secondaires : si l'une manque en base, l'app reste utilisable (avertissement affiché)."""
    try:
        return db.lire(table)
    except Exception:
        tables_manquantes.append(table)
        return pd.DataFrame(columns=SCHEMA[table])


wl, scen = lire_sur("watchlist"), lire_sur("scenarios")
scen_tr, analyses = lire_sur("scenario_trades"), lire_sur("analyses_ia")
analyses_scen = lire_sur("analyses_scen")
jalon("base")
if tables_manquantes:
    st.warning("Tables manquantes : " + ", ".join(tables_manquantes)
               + ". Exécutez la version à jour de sql/schema.sql dans Supabase.")

tmap = (tick.set_index("isin") if not tick.empty
        else pd.DataFrame(columns=["ticker", "nom", "dernier_prix", "dernier_prix_at",
                                   "concurrent_isin", "concurrent_ticker", "concurrent_nom"]))
sect_dict = dict(zip(sect["isin"], sect["secteur"]))

# --------------------------------------------------------------------------- #
# Calculs
# --------------------------------------------------------------------------- #
erreur_journal = None
try:
    positions, ventes = C.calcul_positions(trans)
except ValueError as e:
    erreur_journal = str(e)
    positions, ventes = C.calcul_positions(trans.iloc[0:0])

flux = C.flux_tresorerie(trans, div, vers)
div_par_isin = div.groupby("isin")["montant"].sum()


def charger_cours(isins: list[str]):
    """Cours (live > dernier connu > prix de revient) pour une liste d'ISIN."""
    connus = [i for i in isins if i in tmap.index]
    tickers = tuple(dict.fromkeys(tmap.loc[i, "ticker"] for i in connus))
    if st.session_state.pop("_actualiser_cours", False):
        D.actualiser_cours(tickers)
    D.prechauffer(tickers)  # cours + fondamentaux partagés (marche_cache) en une seule requête
    marche, horo = D.cours_batch(tickers) if tickers else ({}, maintenant())
    lignes, maj = [], []
    for isin in isins:
        connu = isin in tmap.index
        ticker = tmap.loc[isin, "ticker"] if connu else None
        dernier = tmap.loc[isin, "dernier_prix"] if connu else None
        dernier = None if dernier is None or pd.isna(dernier) else float(dernier)
        m = marche.get(ticker, {})
        prix, prev, statut = m.get("prix"), m.get("prev"), "live"
        if prix is not None and m.get("age_s", 0) > 2 * config.TTL_COURS_S:
            prev, statut = None, "obsolète"  # Yahoo injoignable : dernier cours connu du cache partagé
        elif prix is None:
            prix, statut = dernier, ("obsolète" if dernier else "estimé")
        if statut == "live" and connu and (dernier is None or abs(dernier - prix) > 1e-9):
            maj.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin),
                        "dernier_prix": prix, "dernier_prix_at": maintenant().isoformat()})
        lignes.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin) if connu else None,
                       "prix": prix, "prev_close": prev, "statut": statut})
    cols = ["isin", "ticker", "nom", "prix", "prev_close", "statut"]
    return pd.DataFrame(lignes, columns=cols), maj, horo, tickers


isins_tous = list(dict.fromkeys(positions["isin"].tolist() + wl["isin"].tolist() + scen_tr["isin"].tolist()))
cours_all, maj_prix, horodatage, tickers_tous = charger_cours(isins_tous)
jalon("cours")
fonds = D.fondamentaux_batch(tickers_tous) if tickers_tous else {}
jalon("fondamentaux")


def secteur_de(isin: str, ticker) -> str:
    return sect_dict.get(isin) or fonds.get(ticker, {}).get("secteur_yahoo") or "Inconnu"


def enrichir_complet(pos_brutes: pd.DataFrame) -> pd.DataFrame:
    """Positions + cours, poids, dividendes, secteur (colonnes présentes même sans aucune ligne)."""
    p = C.enrichir_positions(pos_brutes, cours_all, div_par_isin)
    p["secteur"] = [secteur_de(i, t) for i, t in zip(p["isin"], p["ticker"])]
    return p


def prix_courant(isin: str):
    r = cours_all[cours_all["isin"] == isin]
    return None if r.empty or pd.isna(r.iloc[0]["prix"]) else float(r.iloc[0]["prix"])


pos = enrichir_complet(positions)
s = C.synthese(pos, flux, vers)
jalon("calculs")



def memoriser_cours_et_snapshot() -> None:
    """Mémorise les derniers cours et le point de courbe du jour, en FIN de script (après l'affichage).
    Écritures limitées par compte (voir pea.services.suivi) ; jamais pour la démo."""
    estimes = (not pos.empty) and (pos["statut"] == "estimé").any()
    suivi.memoriser(maj_prix, snaps, pd.Timestamp(maintenant().date()), s["valeur_totale"], s["apports"],
                    autorise_snapshot=not trans.empty and not estimes and maintenant().weekday() < 5)


manquants = sorted(set(trans["isin"]) - set(tmap.index))


def ordre_isins() -> list[str]:
    """ISIN proposés dans les formulaires : détenus, puis watchlist, puis les autres connus."""
    detenus = positions["isin"].tolist()
    suivis = [i for i in wl["isin"] if i not in detenus]
    return detenus + suivis + [i for i in tmap.index if i not in detenus and i not in suivis]


def choisir_isin(label: str, options: list[str], cle: str, nouveau: bool = True) -> str:
    """Liste déroulante (recherche au clavier) + saisie d'un nouvel ISIN si besoin."""
    opts = list(options) + ([NOUVEL_ISIN] if nouveau else [])
    if not opts:
        return ""
    choix = st.selectbox(label, opts, key=cle + "_sel",
                         format_func=lambda i: i if i == NOUVEL_ISIN else f"{nom_de(tmap, i)} ({i})")
    if choix == NOUVEL_ISIN:
        return st.text_input("ISIN", key=cle + "_new", placeholder="FR0000121014").strip().upper()
    return choix


# --------------------------------------------------------------------------- #
# Fiches de lignes communes à Portefeuille, Projet et Watchlist
# --------------------------------------------------------------------------- #
VUES = ("Fondamentaux", "Techniques")
TXT_AVERTISSEMENT_TECH = ("Note = moyenne pondérée des 4 indicateurs ; ≥ 6 acheter, ≤ 4 vendre. "
                          "Signal indicatif, pas un conseil en investissement.")


def selecteur_vue(ctx: str) -> str:
    """Bascule « Fondamentaux / Techniques » des cartes (le téléchargement des historiques n'a lieu
    que si « Techniques » est choisi)."""
    return st.radio("Affichage des détails", VUES, horizontal=True, key=f"vue_{ctx}",
                    label_visibility="collapsed",
                    format_func=lambda v: "Indicateurs techniques" if v == "Techniques" else v)


def calculer_techniques(tickers) -> dict:
    """{ticker: analyse technique}. Un téléchargement par titre, en parallèle, cache 1 h."""
    valides = tuple(dict.fromkeys(t for t in tickers if isinstance(t, str) and t))
    return {t: TECH.analyser(df) for t, df in D.ohlc_batch(valides).items()} if valides else {}


def afficher_technique(res: dict | None) -> None:
    if not res or not res.get("ok"):
        st.caption((res or {}).get("raison") or "Historique de cours indisponible pour ce titre.")
        return
    st.markdown(f"**{res['emoji']} {res['verdict']}** · note technique **{fmt(res['note'], 1)}/10** · "
                f"séance du {res['date']:%d/%m/%Y}")
    st.markdown("\n".join(f"- {i['emoji']} **{i['label']}** : {i['detail']}"
                          for i in res["indicateurs"]))
    st.caption(TXT_AVERTISSEMENT_TECH)


def _puces(details: list) -> str:
    return "\n".join(f"- {k} : **{v}**" for k, v in details)


def concurrent_de(isin: str) -> dict | None:
    if isin not in tmap.index or "concurrent_ticker" not in tmap.columns:
        return None
    r = tmap.loc[isin]
    texte = lambda x: x.strip() if isinstance(x, str) and x.strip() else ""
    ticker = texte(r.get("concurrent_ticker"))
    if not ticker:
        return None
    return {"isin": texte(r.get("concurrent_isin")), "ticker": ticker,
            "nom": texte(r.get("concurrent_nom")) or ticker}


def resoudre_concurrent(isin: str, ticker: str | None = None) -> dict | None:
    """Yahoo : ticker validé (ou trouvé à partir de l'ISIN) -> {ticker, nom}, sinon None."""
    if ticker:
        v = D.valider_ticker(ticker)
        return {"ticker": ticker, "nom": v["nom"]} if v else None
    t = D.chercher_ticker(isin) if isin else None
    if not t or D.valider_ticker(t["ticker"], t["nom"]) is None:
        return None
    return {"ticker": t["ticker"], "nom": t["nom"]}


def enregistrer_concurrent(isin: str, conc: dict | None) -> str | None:
    """Écrit (ou efface si None) le concurrent du titre. Retourne un message d'erreur ou None."""
    rec = {"concurrent_isin": (conc or {}).get("isin") or None,
           "concurrent_ticker": (conc or {}).get("ticker"), "concurrent_nom": (conc or {}).get("nom")}
    try:
        db.modifier("tickers", isin, rec, cle="isin")
    except Exception:
        return ("Enregistrement impossible : exécutez d'abord la migration SQL du concurrent "
                "(3 colonnes « concurrent_* » de la table tickers, voir schema.sql).")
    return None


def suggerer_a_la_creation(isin: str, ticker: str, nom: str) -> None:
    """Une seule suggestion IA, à la création du titre. Ne bloque jamais l'enregistrement."""
    cle_api = config.cle_gemini()
    if mode_demo or not cle_api:
        return
    try:
        with st.spinner("Recherche d'un concurrent…"):
            f = D.fondamentaux_batch((ticker,), attente=10).get(ticker, {})
            if est_etf(nom, f):
                return
            quotas.verifier("concurrent")
            conc = llm.suggerer(nom, isin, f, cle_api, config.modele_gemini(), resoudre_concurrent)
            quotas.enregistrer("concurrent")
        if conc and enregistrer_concurrent(isin, conc) is None:
            st.session_state["flash_conc"] = (f"Concurrent suggéré : {conc['nom']} "
                                              "(modifiable dans Détails › Fondamentaux)")
    except Exception as e:  # la suggestion est un confort : l'erreur est journalisée, jamais affichée
        journal.info("Suggestion de concurrent abandonnée (%s)", type(e).__name__)


def afficher_comparaison(nom: str, conc: dict, lignes: list) -> None:
    if not lignes:
        st.caption(f"Fondamentaux indisponibles pour comparer avec {conc['nom']}.")
        return
    tab = [f"| | {esc(_court(nom))} | {esc(_court(conc['nom']))} |", "|---|--:|--:|"]
    tab += [f"| {l['label']} | {_cellule(l['vt'], l['unite'])} | {_cellule(l['vc'], l['unite'])} |"
            for l in lignes]
    st.markdown("\n".join(tab))
    st.caption("Marges = résultat ÷ chiffre d'affaires. Données Yahoo, indicatives.")


def bloc_concurrent(isin: str, nom: str, f: dict | None, ctx: str) -> None:
    """Sous les fondamentaux d'une action : comparaison avec son concurrent (à la demande) et édition."""
    if est_etf(nom, f):
        return
    k = f"{ctx}_{isin}"
    conc = concurrent_de(isin)
    comparer = False
    if conc:
        c1, c2 = st.columns([4, 1])
        comparer = c1.toggle(f"⚖️ Comparer à {esc(conc['nom'])}", key=f"cmp_{k}")
        edition = c2.toggle("✏️", key=f"cedit_{k}", help="Modifier ou retirer le concurrent")
    else:
        edition = st.toggle("➕ Ajouter un concurrent", key=f"cedit_{k}")

    if comparer:  # les fondamentaux du concurrent ne sont téléchargés que sur demande
        fc = D.fondamentaux_batch((conc["ticker"],), attente=10).get(conc["ticker"], {})
        afficher_comparaison(nom, conc, CONC.lignes_comparaison(f, fc))
    if not edition:
        return

    sug = st.session_state.pop(f"csug_{k}", None)  # suggestion IA : à injecter AVANT de créer les champs
    if sug:
        st.session_state[f"cisin_{k}"], st.session_state[f"ctk_{k}"] = sug["isin"], sug["ticker"]
        st.info(f"💡 Suggestion IA : **{esc(sug['nom'])}**" + (f" — {esc(sug['raison'])}" if sug["raison"] else "")
                + ". À enregistrer pour la conserver.")
    st.session_state.setdefault(f"cisin_{k}", (conc or {}).get("isin", ""))
    st.session_state.setdefault(f"ctk_{k}", (conc or {}).get("ticker", ""))
    isin_c = st.text_input("ISIN du concurrent", key=f"cisin_{k}", placeholder="DE0007236101")
    tk_c = st.text_input("Ticker Yahoo (facultatif)", key=f"ctk_{k}", placeholder="ex : SIE.DE")
    cle_api = config.cle_gemini()
    ia_ok = bool(cle_api) and not mode_demo and not quotas.limite_atteinte("concurrent")
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 Enregistrer", key=f"csave_{k}", type="primary"):
        c, err = CONC.preparer_concurrent(isin_c, tk_c, isin, resoudre_concurrent)
        err = err or enregistrer_concurrent(isin, c)
        if err:
            st.error(err)
        else:
            flash(f"Concurrent enregistré : {c['nom']} ✅")
            st.rerun()
    if b2.button("💡 IA", key=f"csugbtn_{k}", disabled=not ia_ok,
                 help="Suggestion par l'IA" if ia_ok else "IA indisponible (compte démo, clé absente ou limite atteinte)"):
        try:
            quotas.verifier("concurrent")
            with st.spinner("Recherche d'un concurrent…"):
                prop = llm.suggerer(nom, isin, f, cle_api, config.modele_gemini(), resoudre_concurrent)
        except (llm.ErreurIA, quotas.QuotaDepasse) as e:
            st.error(str(e))
        else:
            quotas.enregistrer("concurrent")
            if prop:
                st.session_state[f"csug_{k}"] = prop
                st.rerun()
            st.warning("Aucun concurrent fiable trouvé : saisissez-le à la main.")
    if conc and b3.button("🗑 Retirer", key=f"cdel_{k}"):
        err = enregistrer_concurrent(isin, None)
        if err:
            st.error(err)
        else:
            for suffixe in ("cisin", "ctk", "cedit", "cmp"):
                st.session_state.pop(f"{suffixe}_{k}", None)
            flash("Concurrent retiré")
            st.rerun()


def carte_ligne(r, ctx: str, vue: str = "Fondamentaux", techs: dict | None = None) -> None:
    """Carte d'une ligne détenue (réelle ou projetée) : synthèse, lien, détails (fondamentaux OU techniques)."""
    badge = "" if r.statut == "live" else f" ⚠️ {r.statut}"
    jour = pastille(r.var_jour_pct, f"{fmt(r.var_jour_pct, 2, True)} % auj.")
    total = pastille(r.perf_pct, f"{fmt(r.perf_pct, 1, True)} % total")
    res_t = (techs or {}).get(r.ticker) if vue == "Techniques" else None
    resume_t = TECH.resume(res_t)
    with st.container(border=True):
        g, d = st.columns([3, 2])
        g.markdown(f"**{esc(r.nom)}**{badge}  \n{esc(r.secteur)} · {fmt(r.poids_pct, 0)} %"
                   + (f"  \nTechnique : {resume_t}" if resume_t else "") + lien_actualites(r.nom))
        d.markdown(f"<div style='text-align:right'><b>{fmt(r.valeur)} €</b><br>"
                   f"{jour}<br>{total}</div>", unsafe_allow_html=True)
        with st.expander("Détails"):
            f = fonds.get(r.ticker, {})
            position = [("Quantité", f"{r.quantite:g}"),
                        ("PRM", f"{fmt(r.prm)} €"),
                        ("Cours", f"{fmt(r.prix_eff)} €"),
                        ("+/- value latente", f"{fmt(r.pv_latente, 2, True)} €"),
                        ("Dividendes perçus", f"{fmt(r.dividendes)} €")]
            ident = [("ISIN · ticker", f"{r.isin} · {r.ticker}")]
            if vue == "Techniques":
                st.markdown(_puces(position + ident))
                afficher_technique(res_t)
            else:
                st.markdown(_puces(position + lignes_fondamentaux(f) + ident))
                bloc_concurrent(r.isin, r.nom, f, ctx)


# --------------------------------------------------------------------------- #
# Analyse IA
# --------------------------------------------------------------------------- #
def afficher_analyse(res: dict, quand, perime: bool, scenario: bool = False) -> None:
    c1, c2 = st.columns([1, 2])
    c1.metric("Note globale", f"{llm.note_globale(res):.1f}/10")
    c2.markdown(f"_{nettoyer_sortie_ia(res['conclusion'])}_")
    for c in res["criteres"]:
        st.markdown(f"**{c['label']}** · {c['note']}/10")
        st.progress(c["note"] / 10)
        st.caption(nettoyer_sortie_ia(c["synthese"]))
        if scenario:  # avantages / inconvénients du scénario par rapport à l'actuel
            for a in c.get("avantages", []):
                st.markdown(f"🟢 {nettoyer_sortie_ia(a)}")
            for i in c.get("inconvenients", []):
                st.markdown(f"🔴 {nettoyer_sortie_ia(i)}")
    suite = " · ⚠️ scénario modifié depuis" if (perime and scenario) else \
        (" · ⚠️ portefeuille modifié depuis" if perime else "")
    st.caption(f"Analysé le {quand:%d/%m/%Y à %H:%M} · {res.get('modele', '')}{suite}")
    st.caption(llm.AVERTISSEMENT)


def bloc_ia(cadre: bool = True) -> None:
    with st.container(border=cadre):
        st.markdown("#### ✨ Analyse IA")
        derniere = None if analyses.empty else analyses.sort_values("id").iloc[-1]

        if mode_demo:
            st.button("✨ Analyser mon portefeuille", disabled=True, key="ia_btn_demo")
            st.caption("Exemple fictif : aucun appel IA en mode démo. Passez sur un compte personnel pour analyser votre portefeuille.")
            afficher_analyse(llm.EXEMPLE, maintenant(), False)
            return
        if pos.empty:
            st.caption("Aucune ligne à analyser.")
            return

        cle_api = config.cle_gemini()
        modele = config.modele_gemini()
        per_isin = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, empreinte = llm.construire_contexte(pos, s["cash"], per_isin, modele)
        limite = quotas.limite_atteinte("analyse")
        a_jour = derniere is not None and derniere["empreinte"] == empreinte

        label = "✨ Relancer l'analyse" if a_jour else "✨ Analyser mon portefeuille"
        clic = st.button(label, key="ia_btn", disabled=(not cle_api) or limite)
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer l'analyse.")
        elif limite:
            st.caption(quotas.message_limite("analyse"))
        else:
            st.caption("Envoie à Gemini uniquement les poids en % (aucun montant en €).")

        if clic:
            try:
                quotas.verifier("analyse")
                with st.spinner("Analyse en cours…"):
                    res = llm.analyser(texte, cle_api, modele)
            except (llm.ErreurIA, quotas.QuotaDepasse) as e:
                st.error(str(e))
            else:
                quotas.enregistrer("analyse")
                db.inserer("analyses_ia", {"modele": modele, "empreinte": empreinte, "resultat": res})
                flash("Analyse enregistrée ✨")
                st.rerun()

        if derniere is not None:
            quand = pd.to_datetime(derniere["cree_le"], utc=True).tz_convert(PARIS)
            afficher_analyse(derniere["resultat"], quand, not a_jour)


def bloc_ia_scenario(sid: int, pos_p: pd.DataFrame, cash_p: float,
                     operations: str, versement: float, cadre: bool = True) -> None:
    """Analyse IA du scénario : note les 4 critères du projeté + avantages/inconvénients vs actuel."""
    with st.container(border=cadre):
        st.markdown("#### ✨ Analyse IA du scénario")
        if mode_demo:
            st.button("✨ Analyser ce scénario", disabled=True, key="ias_btn_demo")
            st.caption("Exemple fictif (aucun appel IA en mode démo).")
            afficher_analyse(llm.EXEMPLE_SCENARIO, maintenant(), False, scenario=True)
            return
        if pos_p.empty:
            st.caption("Aucune ligne à analyser.")
            return

        sel = analyses_scen[analyses_scen["scenario_id"] == sid]
        derniere = None if sel.empty else sel.sort_values("id").iloc[-1]

        cle_api = config.cle_gemini()
        modele = config.modele_gemini()
        per_p = {i: fonds.get(t, {}).get("per") for i, t in zip(pos_p["isin"], pos_p["ticker"])}
        per_a = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, empreinte = llm.construire_contexte_scenario(
            pos_p, cash_p, per_p, pos, s["cash"], per_a, modele, sid, operations, versement)
        limite = quotas.limite_atteinte("analyse")  # quota commun : portefeuille + scénarios
        a_jour = derniere is not None and derniere["empreinte"] == empreinte

        label = "✨ Relancer l'analyse" if a_jour else "✨ Analyser ce scénario"
        clic = st.button(label, key=f"ias_btn_{sid}", disabled=(not cle_api) or limite)
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer l'analyse.")
        elif limite:
            st.caption(quotas.message_limite("analyse"))
        else:
            st.caption("Envoie à Gemini uniquement les poids en % (aucun montant en €).")

        if clic:
            try:
                quotas.verifier("analyse")
                with st.spinner("Analyse en cours…"):
                    res = llm.analyser(texte, cle_api, modele, scenario=True)
            except (llm.ErreurIA, quotas.QuotaDepasse) as e:
                st.error(str(e))
            else:
                quotas.enregistrer("analyse")
                db.inserer("analyses_scen", {"scenario_id": sid, "modele": modele,
                                             "empreinte": empreinte, "resultat": res})
                flash("Analyse du scénario enregistrée ✨")
                st.rerun()

        if derniere is not None:
            quand = pd.to_datetime(derniere["cree_le"], utc=True).tz_convert(PARIS)
            afficher_analyse(derniere["resultat"], quand, not a_jour, scenario=True)


def fondamentaux_block(p: pd.DataFrame) -> str:
    """Une ligne de fondamentaux par ligne détenue (données Yahoo, indicatives)."""
    lignes = ["Fondamentaux des lignes détenues (Yahoo, indicatifs) :"]
    for r in p.sort_values("valeur", ascending=False).itertuples():
        f = fonds.get(r.ticker, {})
        lignes.append(f"- {r.nom} | {r.secteur} | poids {r.poids_pct:.1f} % des titres | "
                      f"PER {fmt(f.get('per'), 1)} | cap. {formater_gros_nombre(f.get('capi'))} | "
                      f"CA {formater_gros_nombre(f.get('ca'))} | dividendes perçus {fmt(r.dividendes)} €")
    return "\n".join(lignes)


def contexte_chat(modele: str, scenario: bool = False, sid=None, pos_p=None, cash_p: float = 0.0,
                  operations: str = "", versement: float = 0.0) -> str:
    """Contexte injecté dans chaque message du chat : structure (poids en %, jamais de €
    de position), dernière analyse IA et fondamentaux. En mode scénario, on parle du
    portefeuille PROJETÉ, en précisant que c'est une simulation."""
    parties = []
    if scenario:
        per_p = {i: fonds.get(t, {}).get("per") for i, t in zip(pos_p["isin"], pos_p["ticker"])}
        per_a = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, _ = llm.construire_contexte_scenario(pos_p, cash_p, per_p, pos, s["cash"], per_a,
                                                    modele, sid, operations, versement)
        nom_s = scen.loc[scen["id"].astype(int) == int(sid), "nom"]
        parties.append(f"Tu discutes du scénario « {nom_s.iloc[0] if len(nom_s) else sid} » "
                       "(SIMULATION de répartition), pas du portefeuille actuel : "
                       "précise-le si une question est ambiguë.")
        parties.append(texte)
        sel = analyses_scen[analyses_scen["scenario_id"] == sid]
        if not sel.empty:
            d = sel.sort_values("id").iloc[-1]
            notes = " ; ".join(f"{c['label']} {c['note']}/10" for c in d["resultat"]["criteres"])
            parties.append(f"Dernière analyse IA de ce scénario : {notes}. "
                           f"Conclusion : {d['resultat']['conclusion']}")
        parties.append(fondamentaux_block(pos_p))
    else:
        per_isin = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, _ = llm.construire_contexte(pos, s["cash"], per_isin, modele)
        parties.append(texte)
        if not analyses.empty:
            d = analyses.sort_values("id").iloc[-1]
            notes = " ; ".join(f"{c['label']} {c['note']}/10" for c in d["resultat"]["criteres"])
            parties.append(f"Dernière analyse IA de la structure : {notes}. "
                           f"Conclusion : {d['resultat']['conclusion']}")
        parties.append(fondamentaux_block(pos))
    return "\n\n".join(parties)


def bloc_chat(scenario: bool = False, sid=None, pos_p=None, cash_p: float = 0.0,
              operations: str = "", versement: float = 0.0, cadre: bool = True) -> None:
    """Chatbot : discussion libre sur le portefeuille actuel ou sur un scénario projeté.
    Une conversation distincte par scénario (clé de session dédiée)."""
    uid = auth.utilisateur() or "inconnu"
    cle_session = f"chat_{uid}_scen_{sid}" if scenario else f"chat_{uid}_msgs"
    titre = "#### 💬 Discuter de ce scénario" if scenario else "#### 💬 Discuter de mon portefeuille"
    with st.container(border=cadre):
        st.markdown(titre)
        if mode_demo:
            st.caption("Chat IA désactivé sur le compte démo pour éviter toute consommation de tokens.")
            return
        if pos.empty:
            st.caption("Aucune ligne dans le portefeuille.")
            return
        cle_api = config.cle_gemini()
        modele = config.modele_gemini()
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer le chat.")
            return

        if cle_session not in st.session_state:
            st.session_state[cle_session] = []
        for m in st.session_state[cle_session]:
            with st.chat_message(m["role"]):
                st.markdown(nettoyer_sortie_ia(m["content"]) if m["role"] == "model" else esc(m["content"]))

        if st.session_state[cle_session] and st.button("🧹 Effacer la conversation", key=cle_session + "_reset"):
            st.session_state[cle_session] = []
            st.rerun()

        if quotas.limite_atteinte("chat"):
            st.caption(quotas.message_limite("chat"))
            return

        # clé propre à chaque conversation : bloc_chat() est appelé 2 fois par page (Portefeuille + Projet)
        question = (st.chat_input("Posez une question…", key=f"chat_in_{cle_session}") or "").strip()
        if question:
            ctx = contexte_chat(modele, scenario, sid, pos_p, cash_p, operations, versement)
            try:
                quotas.verifier("chat")
                with st.spinner("Réponse en cours…"):
                    rep = llm.discuter(ctx, st.session_state[cle_session], question, cle_api, modele)
            except (llm.ErreurIA, quotas.QuotaDepasse) as e:
                st.error(str(e))
            else:
                quotas.enregistrer("chat")
                st.session_state[cle_session] = (st.session_state[cle_session]
                                                 + [{"role": "user", "content": question},
                                                    {"role": "model", "content": rep}])[-12:]
                st.rerun()


# --------------------------------------------------------------------------- #
# Onglet Watchlist
# --------------------------------------------------------------------------- #
@st.fragment
def onglet_watchlist() -> None:
    if wl.empty:
        st.info("Votre watchlist est vide. Ajoutez des valeurs : elles seront proposées dans les "
                "formulaires de saisie et dans les scénarios.")
    vue = selecteur_vue("wl") if not wl.empty else "Fondamentaux"
    techs = {}
    if vue == "Techniques":
        techs = calculer_techniques([tmap.loc[i, "ticker"] for i in wl["isin"] if i in tmap.index])
    with st.container(key="grille_wl"):  # grille de cartes (CSS)
        for r in wl.itertuples():
            c = cours_all[cours_all["isin"] == r.isin]
            prix = prev = None
            if not c.empty:
                prix, prev = c.iloc[0]["prix"], c.iloc[0]["prev_close"]
            var = (prix / prev - 1) * 100 if prix and prev and not pd.isna(prev) else None
            note = "" if r.note is None or pd.isna(r.note) else f"  \n_{esc(r.note)}_"
            ticker = tmap.loc[r.isin, "ticker"] if r.isin in tmap.index else None
            f = fonds.get(ticker, {}) if ticker else {}
            res_t = techs.get(ticker) if vue == "Techniques" else None
            resume_t = TECH.resume(res_t)

            with st.container(border=True):
                g, d = st.columns([3, 2])
                g.markdown(f"**{esc(nom_de(tmap, r.isin))}**  \n{esc(secteur_de(r.isin, ticker))}{note}"
                           + (f"  \nTechnique : {resume_t}" if resume_t else "")
                           + lien_actualites(nom_de(tmap, r.isin)))
                txt = f"<b>{fmt(prix)} €</b>" if prix and not pd.isna(prix) else "N/A"
                if var is not None:
                    txt += "<br>" + pastille(var, f"{fmt(var, 2, True)} % auj.")
                d.markdown(f"<div style='text-align:right'>{txt}</div>", unsafe_allow_html=True)
                with st.expander("Détails"):
                    ident = [("ISIN · ticker", f"{r.isin} · {ticker or '—'}")]
                    if vue == "Techniques":
                        st.markdown(_puces([("Cours", f"{fmt(prix)} €")] + ident))
                        afficher_technique(res_t)
                    else:
                        st.markdown(_puces([("Cours", f"{fmt(prix)} €")] + lignes_fondamentaux(f) + ident))
                        bloc_concurrent(r.isin, nom_de(tmap, r.isin), f, "wl")
                    if st.button("🗑 Retirer de la watchlist", key=f"wl_del_{r.isin}"):
                        db.supprimer("watchlist", r.isin, cle="isin")
                        flash("Retiré de la watchlist")
                        st.rerun()

    with st.expander("➕ Ajouter une action / un ETF"):
        # Remise à zéro des champs après un ajout, avant la création des widgets.
        if st.session_state.pop("wl_reset", False):
            for k in ("wl_isin", "wl_tk", "wl_note"):
                st.session_state[k] = ""
        st.text_input("ISIN", placeholder="FR0000121014", key="wl_isin")
        st.text_input("Ticker Yahoo (facultatif)", key="wl_tk",
                      placeholder="ex : MC.PA — si l'ISIN n'est pas reconnu")
        st.text_input("Note (facultatif)", key="wl_note")
        ajouter = st.button("Ajouter", key="wl_add", type="primary")

        if ajouter:
            isin = st.session_state.get("wl_isin", "").strip().upper()
            tk = st.session_state.get("wl_tk", "").strip().upper()
            note = st.session_state.get("wl_note", "").strip()
            if not C.isin_valide(isin):
                st.error("ISIN invalide (12 caractères, clé de contrôle incorrecte).")
            elif isin in wl["isin"].tolist():
                st.info("Déjà dans la watchlist.")
            else:
                trouve = None
                if isin not in tmap.index or tk:
                    trouve = None if tk else D.chercher_ticker(isin)
                    ticker = tk or (trouve or {}).get("ticker")
                    err = (enregistrer_ticker(isin, ticker, (trouve or {}).get("nom"))
                           if ticker else "Ticker introuvable : renseignez-le dans le champ dédié.")
                    if err:
                        st.error(err)
                        return
                db.upsert("watchlist", [{"isin": isin, "note": note or None}], "isin")
                flash("Ajouté à la watchlist ✅")
                st.session_state["wl_reset"] = True
                st.rerun()


# --------------------------------------------------------------------------- #
# Onglet Projet (scénarios)
# --------------------------------------------------------------------------- #
def graphique_compare(df: pd.DataFrame, cle: str) -> None:
    d = df.iloc[::-1].copy()  # le plus gros en haut
    d[cle] = sans_parentheses(d[cle])  # noms épurés
    fig = go.Figure()
    fig.add_bar(y=d[cle], x=d["reel"], name="Actuel", orientation="h", marker_color=style.ARDOISE,
                hovertemplate="<b>%{y}</b><br>Actuel : %{x:.1f} %<extra></extra>")
    fig.add_bar(y=d[cle], x=d["projete"], name="Projeté", orientation="h", marker_color=style.BLEU,
                hovertemplate="<b>%{y}</b><br>Projeté : %{x:.1f} %<extra></extra>")
    style.habiller(fig)
    fig.update_layout(barmode="group", margin=dict(l=0, r=0, t=10, b=0), height=max(240, 52 * len(d) + 70),
                      legend=dict(orientation="h", y=-0.12), xaxis_title="% du PEA")
    fig.update_xaxes(fixedrange=True)  # pas de zoom tactile
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=PLOTLY)


@st.fragment
def onglet_projet() -> None:
    st.caption("Simulez une répartition future à partir de votre PEA actuel, **sans le modifier**. "
               "Les opérations sont fictives, au dernier cours connu.")
    if st.session_state.pop("scenario_reset", False):
        st.session_state.pop("scenario_id", None)
    if "scenario_pending" in st.session_state:
        st.session_state["scenario_id"] = st.session_state.pop("scenario_pending")

    noms = dict(zip(scen["id"].astype(int), scen["nom"]))
    with st.expander("➕ Nouveau scénario", expanded=scen.empty):
        with st.form("f_scen", clear_on_submit=True):
            nom = st.text_input("Nom", placeholder="ex : Renforcer la santé")
            ok = st.form_submit_button("Créer")
        if ok:
            nom = nom.strip()
            if not nom:
                st.error("Donnez un nom au scénario.")
            elif nom in noms.values():
                st.error("Ce nom existe déjà.")
            else:
                row = db.inserer("scenarios", {"nom": nom, "versement": 0})
                st.session_state["scenario_pending"] = int(row["id"])
                flash("Scénario créé ✅")
                st.rerun()
    if scen.empty:
        return

    sid = st.selectbox("Scénario", list(noms), format_func=noms.get, key="scenario_id")
    sim = scen_tr[scen_tr["scenario_id"] == sid]
    versement = float(scen.loc[scen["id"] == sid, "versement"].iloc[0])

    try:
        brutes, _, cash_p = C.appliquer_scenario(trans, sim, div, vers, versement, maintenant().date())
    except ValueError as e:
        st.error(f"Scénario incohérent : {e}")
        return
    pos_p = enrichir_complet(brutes)

    # --- Opérations fictives et actions rapides ----------------------------- #
    st.markdown("**Opérations fictives**")
    if sim.empty and versement == 0:
        st.caption("Aucune opération pour l'instant.")
    for r in sim.itertuples():
        st.markdown(f"- {r.type} {r.quantite:g} × {esc(nom_de(tmap, r.isin))} @ {fmt(r.prix)} € "
                    f"(≈ {fmt(r.quantite * r.prix, 0)} €)")
    if versement:
        st.markdown(f"- Versement fictif : {fmt(versement, 0)} €")
    b1, b2, b3 = st.columns(3)
    if b1.button("↩️ Annuler", disabled=sim.empty, key="sc_undo", help="Annule la dernière opération"):
        db.supprimer("scenario_trades", int(sim["id"].max()))
        st.rerun()
    if b2.button("🧹 Vider", disabled=sim.empty and versement == 0, key="sc_clear",
                 help="Repart du PEA actuel"):
        db.supprimer("scenario_trades", sid, cle="scenario_id")
        db.modifier("scenarios", sid, {"versement": 0})
        st.rerun()
    if b3.button("🗑 Supprimer", key="sc_del", help="Supprime le scénario"):
        db.supprimer("scenarios", sid)
        st.session_state["scenario_reset"] = True
        flash("Scénario supprimé")
        st.rerun()

    # --- Ajouter une opération ---------------------------------------------- #
    with st.expander("➕ Ajouter une opération", expanded=sim.empty):
        typ = st.radio("Opération", ["ACHAT", "VENTE"], horizontal=True, key="sc_typ")
        detenus = brutes["isin"].tolist()
        options = detenus if typ == "VENTE" else ordre_isins()
        if not options:
            st.info("Aucune ligne à vendre." if typ == "VENTE" else "Ajoutez d'abord des valeurs en watchlist.")
        else:
            isin = st.selectbox("Ligne", options, key="sc_isin",
                                format_func=lambda i: f"{nom_de(tmap, i)} ({i})")
            px_ = prix_courant(isin)
            modes = ["Montant (€)", "Quantité"] + (["Tout"] if typ == "VENTE" else [])
            mode = st.radio("Saisie", modes, horizontal=True, key="sc_mode")
            st.caption(f"Cours : {fmt(px_)} €" if px_ else "Cours indisponible pour cette ligne.")
            val = None
            if mode != "Tout":
                val = st.number_input(mode, min_value=0.0, value=500.0 if mode.startswith("Montant") else 1.0,
                                      step=50.0 if mode.startswith("Montant") else 1.0, key=f"sc_val_{mode}")
            if st.button("Ajouter à ce scénario", key="sc_add"):
                if not px_:
                    st.error("Cours indisponible : opération impossible.")
                else:
                    if mode == "Tout":
                        qte = float(brutes.loc[brutes["isin"] == isin, "quantite"].iloc[0])
                    elif mode.startswith("Montant"):
                        qte = float(int(val // px_))
                    else:
                        qte = float(val)
                    if qte <= 0:
                        st.error(f"Montant inférieur au prix d'une part ({fmt(px_)} €).")
                    else:
                        cand = pd.concat([sim[["isin", "type", "quantite", "prix"]], pd.DataFrame(
                            [{"isin": isin, "type": typ, "quantite": qte, "prix": px_}])], ignore_index=True)
                        try:
                            C.appliquer_scenario(trans, cand, div, vers, versement, maintenant().date())
                        except ValueError as e:
                            st.error(str(e))
                        else:
                            db.inserer("scenario_trades", {"scenario_id": sid, "isin": isin, "type": typ,
                                                           "quantite": qte, "prix": px_})
                            st.rerun()
        v = st.number_input("Versement fictif (€)", min_value=0.0, value=versement, step=100.0,
                            key=f"sc_vers_{sid}")
        if st.button("Appliquer le versement", key="sc_vers_btn", disabled=(v == versement)):
            db.modifier("scenarios", sid, {"versement": float(v)})
            st.rerun()

    # --- Comparaison actuel vs projeté --------------------------------------- #
    st.subheader("Actuel vs projeté")
    if cash_p < -0.01:
        st.warning(f"Cash insuffisant : il manquerait {fmt(-cash_p)} € (ajoutez un versement fictif).")
    if not pos_p.empty:
        for r in pos_p.itertuples():
            if r.poids_pct > SEUIL_CONCENTRATION:
                st.warning(f"⚠️ {r.nom} pèserait {fmt(r.poids_pct, 0)} % des titres.")
    k1, k2 = st.columns(2)
    k1.metric("Cash", f"{fmt(cash_p)} €", f"{fmt(cash_p - s['cash'], 0, True)} €")
    k2.metric("Lignes", len(pos_p), len(pos_p) - len(pos))

    rep_r, rep_p = C.repartition(pos, s["cash"]), C.repartition(pos_p, cash_p)
    par_ligne = C.comparer_repartitions(rep_r, rep_p, "label")
    par_secteur = C.comparer_repartitions(rep_r, rep_p, "secteur")
    g_ligne, g_secteur = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
    with g_ligne:
        st.markdown("**Par ligne**")
        graphique_compare(par_ligne, "label")
    with g_secteur:
        st.markdown("**Par secteur**")
        graphique_compare(par_secteur, "secteur")
    with st.expander("Détail des écarts (points de %)"):
        tableau = par_ligne.rename(columns={"label": "Ligne", "reel": "Actuel %", "projete": "Projeté %",
                                            "ecart": "Écart"}).round(1)
        st.dataframe(tableau, hide_index=True)
    st.subheader("Lignes du scénario")
    vue = selecteur_vue("pj")
    techs = calculer_techniques(pos_p["ticker"]) if vue == "Techniques" and not pos_p.empty else {}
    with st.container(key="grille_pj"):
        for r in pos_p.sort_values("valeur", ascending=False).itertuples():
            carte_ligne(r, "pj", vue, techs)
    ops = "; ".join(f"{r.type} {r.quantite:g} × {nom_de(tmap, r.isin)}" for r in sim.itertuples())
    with st.expander("✨ Assistant IA du scénario · Analyse & Chat"):
        col_analyse, col_chat = st.columns(2)
        with col_analyse:
            bloc_ia_scenario(sid, pos_p, cash_p, ops, versement, cadre=False)
        with col_chat:
            bloc_chat(scenario=True, sid=sid, pos_p=pos_p, cash_p=cash_p, operations=ops,
                      versement=versement, cadre=False)
    st.caption("Simulation de répartition uniquement : aucune prévision de rendement.")


# --------------------------------------------------------------------------- #
# Import par captures d'écran du courtier (Gemini vision) — compte démo exclu
# --------------------------------------------------------------------------- #
SOURCES_ISIN = {"capture": "lu à l'écran", "nom": "reconnu dans votre base",
                "position": "même quantité et PRM qu'une ligne détenue",
                "ia": "⚠️ proposé par l'IA, à vérifier", None: "❓ introuvable"}


def _oublier_import() -> None:
    for k in [k for k in st.session_state if k == "imp" or k.startswith("imp_f")]:
        del st.session_state[k]


def _lire_captures(files, cle_api: str, modele: str) -> None:
    """Gemini lit les images, puis la différence avec la base est calculée (rien n'est écrit)."""
    if mode_demo:  # défense en profondeur : l'UI désactive déjà le bouton (et quotas.verifier refuse)
        return
    images = []
    for f in files:
        octets = f.getvalue()
        mime = IE.type_image_reel(octets)  # on ne se fie pas au type annoncé par le navigateur
        if mime is None:
            st.error(f"« {f.name} » n'est pas une image PNG, JPEG ou WebP valide.")
            return
        images.append((octets, mime))
    try:
        quotas.verifier("capture")
        with st.spinner("Lecture des captures par Gemini…"):
            brut = llm.extraire_capture(images, cle_api, modele)
    except (llm.ErreurIA, quotas.QuotaDepasse) as e:
        st.error(str(e))
        return
    quotas.enregistrer("capture")
    lignes, avert = IE.normaliser_releve(brut)
    if not lignes:
        st.error("Aucune ligne de portefeuille lisible sur ces captures.")
        for a in avert:
            st.caption(a)
        return
    noms = {i: n for i, n in tmap["nom"].items() if isinstance(n, str)} if not tmap.empty else {}
    cours = {i: float(p) for i, p in tmap["dernier_prix"].dropna().items()} if not tmap.empty else {}
    cours.update({r.isin: float(r.prix) for r in cours_all.itertuples() if pd.notna(r.prix)})
    releve = IE.resoudre_isins(lignes, noms, positions)
    ops = IE.proposer_operations(releve, positions, cours, maintenant().date())
    ver = st.session_state.get("imp", {}).get("ver", 0) + 1
    st.session_state["imp"] = {"releve": releve, "ops": ops, "avert": avert, "ver": ver,
                               "n_trans": len(trans)}
    st.session_state["imp_upn"] = st.session_state.get("imp_upn", 0) + 1  # vide le chargeur d'images
    st.rerun()


def _carte_operation(i: int, ver: int, r) -> dict:
    """Une opération proposée = une carte modifiable (mobile-first). Retourne les valeurs saisies."""
    k = f"imp_f{ver}_{i}"
    with st.container(border=True):
        valider = st.checkbox(f"**{r.type}** · {r.nom}", value=bool(r.valider), key=k + "v")
        c1, c2, c3 = st.columns(3)
        q = c1.number_input("Quantité", min_value=0.0, value=float(r.quantite), step=1.0,
                            format="%.4f", key=k + "q")
        p = c2.number_input("Prix (€)", min_value=0.0, value=float(r.prix), step=0.1,
                            format="%.4f", key=k + "p")
        fr = c3.number_input("Frais (€)", min_value=0.0, value=float(r.frais), step=0.1,
                             format="%.2f", key=k + "f")
        d = st.date_input("Date", r.date, format="DD/MM/YYYY", key=k + "d")
        isin = st.text_input("ISIN", value=r.isin, key=k + "i")
        if r.note:
            st.caption(r.note)
    return {"valider": valider, "date": d, "isin": isin.strip().upper(), "nom": r.nom, "type": r.type,
            "quantite": q, "prix": p, "frais": fr, "note": r.note}


def import_captures() -> None:
    """Captures du courtier -> relevé (Gemini) -> écarts avec la base -> opérations à valider."""
    st.caption("Chargez une ou plusieurs captures de votre portefeuille chez le courtier : "
               "l'app propose les achats / ventes qui alignent votre suivi sur la réalité. "
               "Rien n'est enregistré avant votre validation.")
    cle_api = config.cle_gemini()
    modele = config.modele_gemini()
    if mode_demo:
        st.file_uploader("Captures", disabled=True, key="imp_demo_up")
        st.button("🔍 Lire les captures", disabled=True, key="imp_demo_btn")
        st.caption("Indisponible en mode démo (utilise l'API Gemini).")
        return

    limite = quotas.limite_atteinte("capture")
    files = st.file_uploader(f"Captures (PNG/JPEG, {llm.MAX_CAPTURES} max)", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True, key=f"imp_up{st.session_state.get('imp_upn', 0)}")
    if not cle_api:
        st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer l'import.")
    elif limite:
        st.caption(quotas.message_limite("capture"))
    else:
        st.caption("🔐 Les images sont envoyées telles quelles à Gemini : quantités et montants y sont "
                   "lisibles (contrairement à l'analyse IA). Cadrez sans nom ni numéro de compte. "
                   "Sur le palier gratuit, Google peut réutiliser les contenus envoyés. "
                   "Les images ne sont pas conservées.")
    if st.button("🔍 Lire les captures", key="imp_lire", disabled=(not cle_api) or limite or not files):
        if len(files) > llm.MAX_CAPTURES:
            st.error(f"Maximum {llm.MAX_CAPTURES} captures par import.")
        else:
            _lire_captures(files, cle_api, modele)

    imp = st.session_state.get("imp")
    if not imp:
        return
    if imp["n_trans"] != len(trans):
        _oublier_import()
        st.warning("Le journal a changé depuis la lecture : relancez la lecture des captures.")
        return

    releve, ops, ver = imp["releve"], imp["ops"], imp["ver"]
    for a in imp["avert"]:
        st.caption("• " + a)
    with st.expander(f"📋 {len(releve)} ligne(s) lue(s) chez le courtier"):
        for l in releve:
            st.markdown(f"- **{esc(l['nom'])}** : {l['quantite']:g} @ {fmt(l['prm'], 4)} € · "
                        f"{l['isin'] or '?'} ({SOURCES_ISIN[l['source_isin']]})")

    if ops.empty:
        st.success("✅ Les quantités de votre suivi correspondent déjà aux captures.")
    else:
        st.markdown(f"#### {len(ops)} opération(s) proposée(s)")
        st.caption("Cochez, corrigez ou complétez (prix, date, frais, ISIN), puis enregistrez. "
                   "Le prix d'un achat est déduit du PRM du courtier ; celui d'une vente est le cours "
                   "actuel par défaut.")
    with st.form(f"f_imp_{ver}"):
        saisies = [_carte_operation(i, ver, r) for i, r in enumerate(ops.itertuples())]
        c1, c2 = st.columns(2)
        controler = c1.form_submit_button("🔎 Contrôler")
        enregistrer = c2.form_submit_button("✅ Enregistrer", type="primary")
    if st.button("✖ Annuler l'import", key="imp_annuler"):
        _oublier_import()
        st.rerun()
    if not (controler or enregistrer):
        return

    edites = pd.DataFrame(saisies, columns=IE.COLS_OPERATIONS)
    nouvelles, erreurs = IE.preparer_insertions(edites)
    if erreurs:
        for e in erreurs:
            st.error(e)
        return
    try:
        apres, _ = C.calcul_positions(pd.concat([trans, nouvelles], ignore_index=True))
    except ValueError as e:
        st.error(str(e))
        return

    if controler:
        ecarts = IE.ecarts_apres(releve, apres)
        if ecarts.empty:
            st.success("✅ Après ces opérations, quantités et PRM correspondent aux captures.")
        else:
            st.warning("Écarts restants avec les captures après ces opérations :")
            for r in ecarts.itertuples():
                prm = ("" if pd.isna(r.prm_courtier) or pd.isna(r.prm_base) else
                       f" · PRM {fmt(r.prm_base, 4)} (suivi) / {fmt(r.prm_courtier, 4)} (courtier)")
                st.markdown(f"- **{esc(r.nom)}** : quantité {r.qte_base:g} (suivi) / {r.qte_courtier:g} (courtier){prm}")
        return

    if nouvelles.empty:
        st.info("Aucune opération cochée.")
        return
    for isin in nouvelles["isin"].unique():  # tickers résolus AVANT toute écriture
        if isin not in tmap.index:
            trouve = D.chercher_ticker(isin)
            if not trouve:
                st.error(f"Ticker introuvable pour {isin} : ajoutez-le via Saisie › Transaction, "
                         "puis relancez l'import.")
                return
            err = enregistrer_ticker(isin, trouve["ticker"], trouve.get("nom"), suggerer=False)
            if err:
                st.error(err)
                return
    db.inserer_lot("transactions", [r._asdict() for r in nouvelles.itertuples(index=False)])  # une requête
    _oublier_import()
    flash(f"{len(nouvelles)} transaction(s) enregistrée(s) ✅")
    st.rerun()


# --------------------------------------------------------------------------- #
# Onglet Saisie (tous les comptes connectés)
# --------------------------------------------------------------------------- #
@st.fragment
def onglet_saisie() -> None:
    action = st.selectbox("Action", ["Transaction", "Import par captures", "Dividende",
                                     "Versement / retrait", "Secteurs", "Corriger / supprimer",
                                     "Maintenance & sauvegarde"])

    # -- Import par captures du courtier ------------------------------------ #
    if action == "Import par captures":
        import_captures()
        return

    # -- Transaction ------------------------------------------------------- #
    if action == "Transaction":
        typ = st.radio("Type", ["ACHAT", "VENTE"], horizontal=True, key="tx_typ")
        options = positions["isin"].tolist() if typ == "VENTE" else ordre_isins()
        isin = choisir_isin("Ligne (détenue, watchlist ou autre)" if typ == "ACHAT" else "Ligne à vendre",
                            options, "tx", nouveau=(typ == "ACHAT"))
        px_ = prix_courant(isin) if isin in tmap.index else None
        with st.form("f_trans", clear_on_submit=True):
            d = st.date_input("Date", maintenant().date(), format="DD/MM/YYYY")
            q = st.number_input("Quantité", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
            p = st.number_input("Prix unitaire (€)", min_value=0.0, value=float(px_ or 100.0),
                                step=0.1, format="%.4f")
            fr = st.number_input("Frais (€)", min_value=0.0, value=0.0, step=0.1, format="%.2f")
            tk = st.text_input("Ticker Yahoo (facultatif)",
                               placeholder="ex : MC.PA — seulement si l'ISIN n'est pas reconnu")
            ok = st.form_submit_button("Enregistrer")
        if not ok:
            return

        tk = tk.strip().upper()
        if not C.isin_valide(isin):
            st.error("ISIN invalide (12 caractères, clé de contrôle incorrecte).")
            return
        nouvelle = pd.DataFrame([{"date": pd.Timestamp(d), "isin": isin, "type": typ,
                                  "quantite": q, "prix": p, "frais": fr}])
        try:
            _, v_apres = C.calcul_positions(pd.concat([trans, nouvelle], ignore_index=True))
        except ValueError as e:
            st.error(str(e))
            return
        if isin not in tmap.index or tk:
            trouve = None if tk else D.chercher_ticker(isin)
            ticker = tk or (trouve or {}).get("ticker")
            if not ticker:
                st.error("Ticker introuvable pour cet ISIN : renseignez-le dans le champ dédié.")
                return
            err = enregistrer_ticker(isin, ticker, (trouve or {}).get("nom"))
            if err:
                st.error(err)
                return
        db.inserer("transactions", nouvelle.iloc[0].to_dict())
        msg = "Transaction enregistrée ✅"
        if typ == "VENTE":
            msg += f" — plus-value réalisée : {fmt(v_apres['pv'].sum() - ventes['pv'].sum(), 2, True)} €"
        flash(msg)
        st.rerun()

    # -- Dividende --------------------------------------------------------- #
    elif action == "Dividende":
        if tmap.empty:
            st.info("Enregistrez d'abord une transaction.")
            return
        with st.form("f_div", clear_on_submit=True):
            d = st.date_input("Date", maintenant().date(), format="DD/MM/YYYY")
            isin = st.selectbox("Ligne", ordre_isins(), format_func=lambda i: f"{nom_de(tmap, i)} ({i})")
            m = st.number_input("Montant net perçu (€)", min_value=0.01, value=10.0, step=0.5)
            ok = st.form_submit_button("Enregistrer")
        if ok:
            db.inserer("dividendes", {"date": pd.Timestamp(d), "isin": isin, "montant": m})
            flash("Dividende enregistré ✅")
            st.rerun()

    # -- Versement / retrait ----------------------------------------------- #
    elif action == "Versement / retrait":
        st.caption("Les versements alimentent le cash du PEA et comptent dans le plafond de "
                   "150 000 €. Une « plus-value antérieure » alimente le cash sans compter comme apport.")
        with st.form("f_vers", clear_on_submit=True):
            d = st.date_input("Date", maintenant().date(), format="DD/MM/YYYY")
            typ = st.selectbox("Type", list(LIBELLES_VERS), format_func=LIBELLES_VERS.get)
            m = st.number_input("Montant (€)", min_value=0.01, value=100.0, step=10.0)
            lib = st.text_input("Libellé (facultatif)")
            ok = st.form_submit_button("Enregistrer")
        if ok:
            db.inserer("versements", {"date": pd.Timestamp(d), "type": typ, "montant": m,
                                      "libelle": lib.strip() or None})
            flash("Opération enregistrée ✅")
            st.rerun()

    # -- Secteurs ---------------------------------------------------------- #
    elif action == "Secteurs":
        if tmap.empty:
            st.info("Enregistrez d'abord une transaction.")
            return
        st.caption("Laissez vide pour utiliser le secteur fourni par Yahoo (en anglais).")
        with st.form("f_sect"):
            saisies = {i: st.text_input(f"{nom_de(tmap, i)} ({i})", value=sect_dict.get(i, ""))
                       for i in ordre_isins()}
            ok = st.form_submit_button("Enregistrer")
        if ok:
            db.upsert("secteurs", [{"isin": i, "secteur": v.strip()} for i, v in saisies.items() if v.strip()],
                      "isin")
            for i, v in saisies.items():
                if not v.strip() and i in sect_dict:
                    db.supprimer("secteurs", i, cle="isin")
            flash("Secteurs enregistrés ✅")
            st.rerun()

    # -- Corriger / supprimer ---------------------------------------------- #
    elif action == "Corriger / supprimer":
        table = st.selectbox("Table", list(CFG), format_func=str.capitalize)
        version = st.session_state.get("ed_version", 0)
        df = db.lire(table)
        edit = st.data_editor(df, key=f"ed_{table}_{version}", num_rows="dynamic",
                              hide_index=True, column_config=CFG[table])
        if not st.button("💾 Enregistrer les modifications"):
            return
        n = edit.copy()
        requis = [c for c in ("date", "isin", "type", "quantite", "prix", "montant") if c in n]
        if n[requis].isna().any().any():
            st.error("Des champs obligatoires sont vides.")
            return
        n["date"] = pd.to_datetime(n["date"])
        if "isin" in n:
            n["isin"] = n["isin"].str.strip().str.upper()
            inconnus = sorted(set(n["isin"]) - set(tmap.index))
            if inconnus:
                st.error(f"ISIN inconnu(s) : {', '.join(inconnus)}. "
                         "Ajoutez-les d'abord via la watchlist ou l'action « Transaction ».")
                return
        if "frais" in n:
            n["frais"] = n["frais"].fillna(0.0)
        if table == "transactions":
            try:
                C.calcul_positions(n)
            except ValueError as e:
                st.error(str(e))
                return
        a, m, sup = db.appliquer_modifs(table, df, n)
        st.session_state["ed_version"] = version + 1
        flash(f"{a} ajoutée(s), {m} modifiée(s), {sup} supprimée(s) ✅")
        st.rerun()

    # -- Maintenance ------------------------------------------------------- #
    else:
        st.subheader("Historique")
        st.caption("Recalcule la valeur du PEA jour par jour depuis votre 1re opération "
                   "(cours de clôture Yahoo) et remplace les points existants.")
        if st.button("Reconstituer l'historique", disabled=trans.empty):
            with st.spinner("Téléchargement des historiques de cours…"):
                debut = trans["date"].min().strftime("%Y-%m-%d")
                isin_ticker = tmap["ticker"].to_dict()
                prix_hist = D.historiques_groupes(set(isin_ticker.values()), debut)  # un seul téléchargement
                rec = C.reconstituer_snapshots(trans, flux, prix_hist, isin_ticker)
                db.upsert("snapshots", [{"date": r.date, "valeur": round(r.valeur, 2),
                                         "apports": round(r.apports, 2)} for r in rec.itertuples()],
                          "date")
            flash(f"{len(rec)} points reconstitués ✅")
            st.rerun()

        if manquants:
            st.subheader("Tickers manquants")
            st.warning(f"{len(manquants)} ISIN sans ticker : {', '.join(manquants)}")
            if st.button("Résoudre automatiquement"):
                echecs = []
                for isin in manquants:
                    t = D.chercher_ticker(isin)
                    if not t or enregistrer_ticker(isin, t["ticker"], t["nom"], suggerer=False):
                        echecs.append(isin)
                flash("Tickers résolus ✅" if not echecs else f"Échec pour : {', '.join(echecs)}")
                st.rerun()
            with st.form("f_tk"):
                isin = st.selectbox("ISIN", manquants)
                tk = st.text_input("Ticker Yahoo", placeholder="ex : MC.PA")
                ok = st.form_submit_button("Enregistrer le ticker")
            if ok:
                err = enregistrer_ticker(isin, tk.strip().upper(), suggerer=False) if tk.strip() else "Ticker vide."
                if err:
                    st.error(err)
                else:
                    flash("Ticker enregistré ✅")
                    st.rerun()

        st.subheader("Sauvegarde")
        for table in list(CFG) + ["watchlist"]:
            st.download_button(f"⬇️ {table}.csv", db.lire(table).to_csv(index=False),
                               file_name=f"{table}.csv", mime="text/csv", key=f"dl_{table}")


# --------------------------------------------------------------------------- #
# Mise en page : 5 onglets
# --------------------------------------------------------------------------- #
# Onglets paresseux (P1) : seul l'onglet ouvert s'exécute ; changer d'onglet relance le script.
tab_pf, tab_hist, tab_proj, tab_wl, tab_saisie = st.tabs(
    ["📊 Portefeuille", "📈 Historique", "🔭 Projet", "👀 Watchlist", "➕ Saisie"], on_change="rerun", key="onglet")

def graphique_secteurs(df: pd.DataFrame) -> None:
    """Anneau de répartition par secteur : palette douce commune à tous les graphiques, pourcentages
    arrondis sur l'anneau (masqués si la part est trop petite), détail arrondi au toucher / survol."""
    d = df.sort_values("valeur", ascending=False)
    total = float(d["valeur"].sum())
    couleurs = [style.PALETTE[i % len(style.PALETTE)] for i in range(len(d))]
    fig = go.Figure(go.Pie(
        labels=d["secteur"].tolist(), values=d["valeur"].tolist(), hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=couleurs, line=dict(color=style.fond_page(), width=2)),
        texttemplate="%{percent:.0%}", textposition="inside", insidetextorientation="horizontal",
        textfont=dict(color=[style.texte_sur(c) for c in couleurs], size=13),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>%{percent:.1%}<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=360, showlegend=True,
        uniformtext=dict(minsize=11, mode="hide"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.02, yanchor="top", font=dict(size=12)),
        annotations=[dict(text=f"<b>{fmt(total, 0)} €</b><br>en titres", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=16))])
    st.plotly_chart(fig, config=PLOTLY)


def graphique_treemap(d: pd.DataFrame) -> go.Figure:
    """Treemap PEA › secteur › ligne ; couleur = performance (moyenne pondérée par la valeur pour les niveaux
    supérieurs). Construit directement avec Plotly (listes simples), sans plotly.express."""
    ids, labels, parents, valeurs, perfs = ["PEA"], ["PEA"], [""], [], []
    v_tot = float(d["valeur"].sum())
    perfs.append(float((d["valeur"] * d["perf_pct"]).sum() / v_tot) if v_tot else 0.0)
    valeurs.append(v_tot)
    for secteur, g in d.groupby("secteur"):
        v_s = float(g["valeur"].sum())
        ids.append(f"S|{secteur}")
        labels.append(str(secteur))
        parents.append("PEA")
        valeurs.append(v_s)
        perfs.append(float((g["valeur"] * g["perf_pct"]).sum() / v_s) if v_s else 0.0)
        for r in g.itertuples():
            ids.append(f"L|{r.isin}")
            labels.append(str(r.nom))
            parents.append(f"S|{secteur}")
            valeurs.append(float(r.valeur))
            perfs.append(float(r.perf_pct))
    lim = max(abs(p) for p in perfs) or 1.0
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=valeurs, branchvalues="total",
        marker=dict(colors=perfs, colorscale="RdYlGn", cmin=-lim, cmax=lim, showscale=False),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>Performance : %{color:+.1f} %<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=360)
    return fig


def graphique_barres(df: pd.DataFrame, x: str, labels: dict, titre: str | None = None,
                     valeur_infobulle: str = "%{x:+.1f} %") -> None:
    """Barres horizontales (une par ligne), colorées du rouge au vert autour de 0.

    `valeur_infobulle` : format (arrondi) de la valeur affichée au toucher / au survol.
    """
    valeurs = [float(v) for v in df[x]]
    lim = max(abs(v) for v in valeurs) if valeurs else 1.0
    fig = go.Figure(go.Bar(
        x=valeurs, y=[str(n) for n in df["nom"]], orientation="h",
        marker=dict(color=valeurs, colorscale="RdYlGn", cmin=-lim, cmax=lim, showscale=False),
        hovertemplate="<b>%{y}</b><br>" + valeur_infobulle + "<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(margin=dict(l=0, r=0, t=30 if titre else 10, b=0), height=max(220, 44 * len(df)),
                      title=dict(text=titre) if titre else None,
                      xaxis_title=labels.get(x) or None, yaxis_title=labels.get("nom") or None)
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=PLOTLY)


# L'onglet Portefeuille est découpé en 3 fragments frères : basculer « Fondamentaux / Indicateurs
# techniques » ne relance que les cartes (ni synthèse, ni IA, ni chat, ni graphiques).
@st.fragment
def pf_synthese() -> None:
    if erreur_journal:
        st.error(f"Journal incohérent : {erreur_journal} Corrigez-le dans Saisie › Corriger / supprimer.")
    if manquants:
        st.warning("Ticker manquant pour : " + ", ".join(manquants)
                   + " (Saisie › Maintenance). Ces lignes sont valorisées à leur prix de revient.")
    if trans.empty:
        st.info("Aucune transaction pour l'instant. Rendez-vous dans l'onglet « Saisie ».")
        return

    c1, c2, c3, c4 = st.columns(4)  # 4 en ligne sur PC, 2 × 2 sur mobile
    c1.metric("Valeur du PEA", f"{fmt(s['valeur_totale'])} €",
              f"{fmt(s['var_jour_eur'], 2, True)} € ({fmt(s['var_jour_pct'], 2, True)} %) auj.")
    c2.metric("Plus-value globale", f"{fmt(s['pv_globale'])} €", f"{fmt(s['perf_pct'], 2, True)} %")
    c3.metric("Apports nets", f"{fmt(s['apports'])} €")
    c4.metric("Cash disponible", f"{fmt(s['cash'])} €")
    st.progress(min(s["plafond_pct"] / 100, 1.0),
                text=f"Plafond de versements : {fmt(s['versements_cumules'], 0)} / 150 000 € "
                     f"({fmt(s['plafond_pct'], 1)} %)")

    # Bandeau IA replié par défaut : un clic le déplie ; sur PC / tablette, analyse et chat côte à côte.
    with st.expander("✨ Assistant IA · Analyse & Chat"):
        col_analyse, col_chat = st.columns(2)
        with col_analyse:
            bloc_ia(cadre=False)
        with col_chat:
            bloc_chat(cadre=False)

    if s["cash"] < -0.01:
        st.warning("Cash négatif : il manque des versements dans le journal "
                   "(Saisie › Versement / retrait).")
    if pos.empty:
        return
    for r in pos.itertuples():
        if r.poids_pct > SEUIL_CONCENTRATION:
            st.warning(f"⚠️ Concentration : {r.nom} pèse {fmt(r.poids_pct, 0)} % des titres "
                       f"(seuil {SEUIL_CONCENTRATION:.0f} %).")
    hors_ligne = pos[pos["statut"] != "live"]
    if not hors_ligne.empty:
        st.warning("Cours indisponibles pour " + ", ".join(hors_ligne["nom"])
                   + " : dernier cours connu ou prix de revient utilisé.")
    st.caption(f"Cours Yahoo différés · actualisés à {horodatage:%H:%M} (cache 5 min)")


@st.fragment
def pf_lignes() -> None:
    """Une carte par ligne (lisible sur téléphone)."""
    if pos.empty:
        return
    vue = selecteur_vue("pf")
    techs = calculer_techniques(pos["ticker"]) if vue == "Techniques" else {}
    with st.container(key="grille_pf"):  # grille de cartes (CSS) : 1 colonne sur mobile, 2-3 sur PC
        for r in pos.sort_values("valeur", ascending=False).itertuples():
            carte_ligne(r, "pf", vue, techs)


# -- Matrice de notes : deux grandeurs notées de 1 à 10 (relatives au portefeuille), croisées --------
def matrice_notes() -> None:
    """Nuage de points : deux grandeurs au choix, chacune notée de 1 à 10 par rang dans le portefeuille
    (10 = le meilleur, 1 = sans valeur, ex. PER d'une société déficitaire). Jamais de ligne écartée."""
    st.subheader("Matrice de notes")
    cles = list(GRANDEURS)
    c_x, c_y, c_wl = st.columns(3, vertical_alignment="bottom")
    cx = c_x.selectbox("Axe horizontal", cles, index=cles.index("net_income"), key="qd_x",
                       format_func=lambda k: GRANDEURS[k][0])
    cy = c_y.selectbox("Axe vertical", cles, index=cles.index("per"), key="qd_y",
                       format_func=lambda k: GRANDEURS[k][0])
    avec_wl = c_wl.checkbox("Inclure la watchlist", key="qd_wl")

    lignes = [{"isin": r.isin, "nom": r.nom, "ticker": r.ticker, "poids": r.poids_pct,
               "perf": r.perf_pct, "wl": False} for r in pos.itertuples()]
    if avec_wl:
        detenus = set(pos["isin"])
        for isin in wl["isin"]:
            if isin not in detenus:
                tk = tmap.loc[isin, "ticker"] if isin in tmap.index else None
                lignes.append({"isin": isin, "nom": nom_de(tmap, isin), "ticker": tk,
                               "poids": None, "perf": None, "wl": True})
    for l in lignes:
        l["etf"] = est_etf(l["nom"], fonds.get(l["ticker"], {}))
    lignes = [l for l in lignes if not l["etf"]]  # les ETF n'ont pas de fondamentaux : écartés de la matrice
    if len(lignes) < 3:
        st.info("Au moins 3 actions (hors ETF) sont nécessaires pour comparer des notes.")
        return

    df = pd.DataFrame(lignes)
    df["vx"] = [valeur_grandeur(fonds.get(tk, {}), cx) for tk in df["ticker"]]
    df["vy"] = [valeur_grandeur(fonds.get(tk, {}), cy) for tk in df["ticker"]]
    df["nx"] = C.note_relative(df["vx"], GRANDEURS[cx][1])
    df["ny"] = C.note_relative(df["vy"], GRANDEURS[cy][1])
    df["px"], df["py"] = df["nx"], df["ny"]
    for _, g in df.groupby([df["nx"].round(2), df["ny"].round(2)]):  # points identiques : léger décalage
        if len(g) > 1:
            df.loc[g.index, "px"] = [df.at[i, "nx"] + (j - (len(g) - 1) / 2) * 0.28 for j, i in enumerate(g.index)]

    def ligne_info(l, cle, v, n):
        v = None if v is None or pd.isna(v) else v
        return f"{GRANDEURS[cle][0]} : {_cellule(v, GRANDEURS[cle][2])} → note {n:.1f}/10"

    def trace(d, **marqueur):
        info = [[l.nom, ligne_info(l, cx, l.vx, l.nx), ligne_info(l, cy, l.vy, l.ny),
                 "Watchlist" if l.wl else f"Poids : {fmt(l.poids, 0)} %"] for l in d.itertuples()]
        return go.Scatter(x=d["px"].tolist(), y=d["py"].tolist(), mode="markers+text" if len(df) <= 12 else "markers",
                          text=[_court(n, 12) for n in d["nom"]], textposition="top center",
                          textfont=dict(size=11), customdata=info, showlegend=False,
                          hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                                        "%{customdata[2]}<br>%{customdata[3]}<extra></extra>",
                          marker=marqueur)

    fig = go.Figure()
    detenus_df, suivis_df = df[~df["wl"]], df[df["wl"]]
    if not detenus_df.empty:
        lim = max(5.0, float(detenus_df["perf"].abs().max()))
        fig.add_trace(trace(detenus_df, size=[min(46, 14 + 4.5 * max(p, 0) ** 0.5) for p in detenus_df["poids"]],
                            color=detenus_df["perf"].tolist(), colorscale="RdYlGn", cmin=-lim, cmax=lim,
                            showscale=False, opacity=0.92, line=dict(color="rgba(255,255,255,0.85)", width=1.5)))
    if not suivis_df.empty:
        fig.add_trace(trace(suivis_df, size=15, symbol="diamond", color=style.ARDOISE, opacity=0.9,
                            line=dict(color="rgba(255,255,255,0.85)", width=1.5)))
    fig.add_shape(type="rect", x0=5.5, x1=10.5, y0=5.5, y1=10.5, fillcolor="rgba(22,163,74,0.06)",
                  line_width=0, layer="below")
    fig.add_shape(type="rect", x0=0.5, x1=5.5, y0=0.5, y1=5.5, fillcolor="rgba(220,38,38,0.05)",
                  line_width=0, layer="below")
    gris = "rgba(128,128,128,0.6)"
    fig.add_vline(x=5.5, line=dict(dash="dot", color=gris, width=1))
    fig.add_hline(y=5.5, line=dict(dash="dot", color=gris, width=1))
    for x, y, xa, ya, txt in ((10.4, 10.4, "right", "top", "Fort sur les deux"),
                              (0.6, 0.6, "left", "bottom", "Faible sur les deux"),
                              (0.6, 10.4, "left", "top", f"Fort : {GRANDEURS[cy][3]}"),
                              (10.4, 0.6, "right", "bottom", f"Fort : {GRANDEURS[cx][3]}")):
        fig.add_annotation(x=x, y=y, xanchor=xa, yanchor=ya, text=txt, showarrow=False,
                           font=dict(size=11, color="rgba(128,128,128,0.95)"))
    style.habiller(fig)
    axe = dict(range=[0.5, 10.5], tickmode="array", tickvals=list(range(1, 11)), fixedrange=True,
               zeroline=False)
    fig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis=dict(title=f"{GRANDEURS[cx][0]} — note /10 (10 = {GRANDEURS[cx][3]})", **axe),
                      yaxis=dict(title=f"{GRANDEURS[cy][0]} — note /10 (10 = {GRANDEURS[cy][3]})", **axe))
    st.plotly_chart(fig, config=PLOTLY)

    st.caption("Chaque ligne reçoit, sur chaque axe, une **note de 1 à 10 relative à ce portefeuille** : 10 = le "
               "meilleur du lot, 1 = pas de valeur (ex. société déficitaire, sans PER). Les écarts entre notes "
               "sont des écarts de classement, pas de valeur. Taille = poids, couleur = performance"
               + (", ◆ = watchlist" if not suivis_df.empty else "") + ".")


@st.fragment
def pf_graphiques() -> None:
    if trans.empty:
        return
    if not pos.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Concentration max", f"{fmt(pos['poids_pct'].max(), 0)} %")
        col2.metric("Lignes actives", len(pos))
        total_dividendes = pos["dividendes"].sum()
        rendement_div = total_dividendes / s["valeur_totale"] * 100 if s["valeur_totale"] > 0 else 0.0
        col3.metric("Rendement dividendes", f"{fmt(rendement_div, 1)} %", f"{fmt(total_dividendes)} €")

        pos_fig = pos.assign(nom=sans_parentheses(pos["nom"]))
        st.subheader("Répartition")
        g_secteurs, g_treemap = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
        with g_secteurs:
            st.markdown("**Par secteur**")
            graphique_secteurs(pos.groupby("secteur")["valeur"].sum().reset_index())
        with g_treemap:
            st.markdown("**Par ligne** · couleur = performance")
            fig = graphique_treemap(pos_fig)
            st.plotly_chart(fig, config=PLOTLY)

        g_perf, g_contrib = st.columns(2)
        with g_perf:
            st.subheader("Performance latente par ligne")
            graphique_barres(pos_fig.sort_values("perf_pct", ascending=False), "perf_pct",
                             {"perf_pct": "Performance %", "nom": ""}, "Performance latente (vs PRM)")
        with g_contrib:
            st.subheader("Contribution à la performance (€)")
            contrib = pos_fig.assign(contrib=pos["pv_latente"] + pos["dividendes"]).sort_values("contrib")
            graphique_barres(contrib, "contrib", {"contrib": "PV latente + dividendes (€)", "nom": ""},
                             valeur_infobulle="%{x:+,.0f} €")

        matrice_notes()

    if not ventes.empty or not div.empty:
        with st.expander("Plus-values réalisées & dividendes"):
            st.markdown(f"- Plus-values réalisées : **{fmt(ventes['pv'].sum(), 2, True)} €**\n"
                        f"- Dividendes nets perçus : **{fmt(div['montant'].sum())} €**")


def bloc_partage() -> None:
    """Case de partage de la performance (décochée par défaut) + pseudo. Seul l'indice base 100 est partagé."""
    try:
        cfg = db.lire("partage")
    except Exception:
        st.caption("Partage indisponible : exécutez d'abord la migration SQL (table « partage », voir schema.sql).")
        return
    actif = bool(cfg["partage"].iloc[0]) if not cfg.empty and pd.notna(cfg["partage"].iloc[0]) else False
    pseudo = (cfg["pseudo"].iloc[0] if not cfg.empty else None) or ""
    pseudo = "" if pd.isna(pseudo) else str(pseudo)

    def sauver() -> None:
        try:
            db.enregistrer_partage(st.session_state.get("part_actif", False),
                                   st.session_state.get("part_pseudo", pseudo))
        except Exception as e:
            flash(f"Enregistrement du partage impossible : {e}")

    st.divider()
    st.checkbox("Partager ma performance avec les autres utilisateurs", value=actif, key="part_actif",
                on_change=sauver,
                help="Seule votre courbe de performance (base 100, sans montant ni position) est visible, "
                     "sous le pseudo ci-dessous. Décochez pour cesser immédiatement le partage.")
    if st.session_state.get("part_actif", actif):
        st.text_input("Pseudo affiché", value=pseudo, key="part_pseudo", max_chars=db.PSEUDO_MAX,
                      placeholder="Anonyme", on_change=sauver,
                      help="Laissez vide pour apparaître comme « Anonyme ».")


@st.fragment
def onglet_historique() -> None:
    if len(snaps) < 2:
        st.info("Pas encore d'historique : un point est enregistré à chaque visite en semaine. "
                "Vous pouvez aussi le reconstituer depuis vos transactions "
                "(Saisie › Maintenance & sauvegarde).")
    else:
        periode = st.radio("Période", ["1M", "3M", "6M", "1A", "Tout"], horizontal=True, index=4)
        mois = {"1M": 1, "3M": 3, "6M": 6, "1A": 12}.get(periode)
        sn = snaps if mois is None else snaps[
            snaps["date"] >= pd.Timestamp(maintenant().date()) - pd.DateOffset(months=mois)]
        if len(sn) < 2:
            st.info("Pas assez de points sur cette période.")
        else:
            g_valeur, g_indice = st.columns(2)  # côte à côte sur PC / tablette, empilés sur mobile
            with g_valeur:
                st.subheader("Valeur du PEA")
                fig = go.Figure()
                fig.add_scatter(x=sn["date"], y=sn["valeur"], name="Valeur du PEA", mode="lines",
                                line=dict(color=style.BLEU, width=2.5), hovertemplate="%{y:,.0f} €")
                fig.add_scatter(x=sn["date"], y=sn["apports"], name="Apports nets", mode="lines",
                                line=dict(shape="hv", dash="dot", color=style.ARDOISE, width=2),
                                hovertemplate="%{y:,.0f} €")
                style.habiller(fig, hovermode="x unified")
                fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340,
                                  legend=dict(orientation="h", y=-0.15))
                fig.update_xaxes(fixedrange=True, hoverformat="%d/%m/%Y")  # pas de zoom tactile
                fig.update_yaxes(fixedrange=True)
                st.plotly_chart(fig, config=PLOTLY)

            with g_indice:
                st.subheader("Performance vs indice")
                st.caption("Performance pondérée par le temps : neutralise vos versements, base 100.")
                choix = st.selectbox("Comparer à", list(BENCHMARKS), label_visibility="collapsed")
                try:  # table « partage » absente (migration non faite) ou base indisponible : pas d'amis
                    amis = partage.performances_partagees()
                except Exception:
                    amis = pd.DataFrame(columns=["pseudo", "date", "twr"])
                noms = sorted(amis["pseudo"].unique())
                choisis = st.multiselect("Comparer aux autres utilisateurs", noms, default=noms,
                                         placeholder="Utilisateurs à afficher",
                                         label_visibility="collapsed") if noms else []
                twr = C.calcul_twr(sn)
                bench = None
                try:  # le compte demo utilise aussi les cours et historiques Yahoo
                    h = D.historique_cloture(BENCHMARKS[choix], sn["date"].min().strftime("%Y-%m-%d"))
                    bench = h.reindex(h.index.union(twr["date"])).ffill().reindex(twr["date"]).bfill()
                    bench = bench / bench.iloc[0] * 100
                except Exception:
                    st.caption("Indice indisponible pour le moment.")
                fig = go.Figure()
                fig.add_scatter(x=twr["date"], y=twr["twr"], name="Mon PEA", mode="lines",
                                line=dict(color=style.BLEU, width=2.5), hovertemplate="%{y:.1f}")
                if bench is not None:
                    fig.add_scatter(x=twr["date"], y=bench.to_numpy(), name=choix, mode="lines",
                                    line=dict(color=style.ARDOISE, width=2), hovertemplate="%{y:.1f}")
                perf_amis = {}
                for n, p in enumerate(choisis):
                    s = amis[amis["pseudo"] == p].set_index("date")["twr"]
                    s = s.reindex(s.index.union(twr["date"])).ffill().reindex(twr["date"])  # pas de bfill
                    if s.notna().sum() < 2:
                        continue  # pas de données sur la période
                    s = s / s.dropna().iloc[0] * 100
                    perf_amis[p] = s.iloc[-1] - 100
                    fig.add_scatter(x=twr["date"], y=s.to_numpy(), name=sur_pour_graphique(p), mode="lines",
                                    line=dict(width=1.5, color=style.COULEURS_AMIS[n % len(style.COULEURS_AMIS)]),
                                    connectgaps=False, hovertemplate="%{y:.1f}")
                style.habiller(fig, hovermode="x unified")
                fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340,
                                  legend=dict(orientation="h", y=-0.15))
                fig.update_xaxes(fixedrange=True, hoverformat="%d/%m/%Y")  # pas de zoom tactile
                fig.update_yaxes(fixedrange=True)
                st.plotly_chart(fig, config=PLOTLY)
                resume = f"Mon PEA : **{fmt(twr['twr'].iloc[-1] - 100, 2, True)} %**"
                if bench is not None:
                    resume += f" · {choix} : **{fmt(bench.iloc[-1] - 100, 2, True)} %**"
                st.markdown(resume)
                if perf_amis:
                    st.markdown(" · ".join(f"{esc(p)} : **{fmt(v, 2, True)} %**" for p, v in perf_amis.items()))
                    st.caption("Courbes des autres utilisateurs : base 100 au début de la période (ou à leur "
                               "1er point s'il est plus récent).")

    if not auth.est_demo():
        bloc_partage()

def ouvert(tab) -> bool:
    """`tab.open` vaut None si la version de Streamlit ne suit pas l'onglet actif : tout s'exécute alors."""
    return tab.open is not False


if ouvert(tab_pf):
    with tab_pf:
        pf_synthese()
        pf_lignes()
        pf_graphiques()

if ouvert(tab_hist):
    with tab_hist:
        onglet_historique()

if ouvert(tab_proj):
    with tab_proj:
        onglet_projet()

if ouvert(tab_wl):
    with tab_wl:
        onglet_watchlist()

if ouvert(tab_saisie):
    with tab_saisie:
        with st.container(key="saisie"):  # largeur limitée par le CSS : formulaires lisibles sur grand écran
            onglet_saisie()

memoriser_cours_et_snapshot()  # après l'affichage : n'allonge pas le temps avant la page


@st.fragment(run_every=2)
def surveiller_marche() -> None:
    """Cours encore en téléchargement (arrière-plan) : relance l'affichage dès qu'ils arrivent (≤ 30 s)."""
    n = st.session_state.get("_attente_marche", 0)
    if not D.rafraichissement_en_cours() or n > 15:
        st.session_state.pop("_attente_marche", None)
        if n:
            st.rerun()
        return
    st.session_state["_attente_marche"] = n + 1


if D.rafraichissement_en_cours():
    surveiller_marche()

if config.debug_perf():  # secret facultatif : DEBUG_PERF = true
    t = [(k, v) for k, v in CHRONO.items() if k != "debut"]
    prec, morceaux = CHRONO["debut"], []
    for k, v in t:
        morceaux.append(f"{k} {1000 * (v - prec):.0f} ms")
        prec = v
    st.caption("⏱ " + " · ".join(morceaux) + f" · total script {1000 * (time.perf_counter() - CHRONO['debut']):.0f} ms")
