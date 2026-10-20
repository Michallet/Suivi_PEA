"""Suivi PEA — interface Streamlit mobile-first multi-utilisateur.

Les comptes sont définis dans .streamlit/secrets.toml. Le compte demo partage un jeu de données
fictif persistant et n'a pas accès aux fonctionnalités IA.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import auth
import calculs as C
import db
import donnees as D
import llm
import recherche as R
from schema import SCHEMA

st.set_page_config(page_title="Suivi PEA", page_icon="📈", layout="centered")

SEUIL_CONCENTRATION = 25.0  # % des titres au-delà duquel on alerte
BENCHMARKS = {"MSCI World (CW8)": "CW8.PA", "CAC 40": "^FCHI", "Euro Stoxx 50": "^STOXX50E"}
VERT, ROUGE = "#16a34a", "#dc2626"
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


def fmt(x, dec: int = 2, signe: bool = False) -> str:
    """Nombre au format français : 12 345,67 (signe optionnel)."""
    if x is None or pd.isna(x):
        return "N/A"
    s = f"{x:+,.{dec}f}" if signe else f"{x:,.{dec}f}"
    return s.replace(",", "\u202f").replace(".", ",")


def pastille(v: float, texte: str) -> str:
    return f"<span style='color:{VERT if v >= 0 else ROUGE}'>{texte}</span>"


def sans_parentheses(series: pd.Series) -> pd.Series:
    """Noms épurés pour les axes : retrait de TOUS les groupes entre parenthèses
    (souvent au milieu des noms d'ETF, ex. « Amundi PEA Monde (MSCI World) UCITS ETF »)."""
    return (series.astype(str).str.replace(r"\s*\([^)]*\)", "", regex=True)
            .str.replace(r"\s{2,}", " ", regex=True).str.strip())


def flash(msg: str) -> None:
    """Message affiché (toast) après le prochain rechargement."""
    st.session_state["flash"] = msg


def nom_de(tmap: pd.DataFrame, isin: str) -> str:
    n = tmap.loc[isin, "nom"] if isin in tmap.index else None
    return isin if n is None or pd.isna(n) else n


def enregistrer_ticker(isin: str, ticker: str, nom: str | None = None) -> str | None:
    """Valide puis mémorise ISIN -> ticker. Retourne un message d'erreur ou None."""
    v = D.valider_ticker(ticker, nom)
    if v is None:
        return f"Aucun cours trouvé pour « {ticker} »."
    if v["devise"] not in (None, "EUR"):
        return f"« {ticker} » cote en {v['devise']} : indiquez la cotation européenne en € (ex : MC.PA)."
    db.upsert("tickers", [{"isin": isin, "ticker": ticker, "nom": v["nom"], "dernier_prix": v["prix"],
                           "dernier_prix_at": maintenant().isoformat()}], "isin")
    return None


# --------------------------------------------------------------------------- #
# Authentification : tout compte connecté utilise Supabase ; seule l'IA est interdite en démo.
# --------------------------------------------------------------------------- #
connecte = auth.connecte()
mode_demo = auth.est_demo()

if not connecte:
    st.title("📈 Suivi PEA")
    st.info("Connectez-vous pour accéder à un portefeuille. Les identifiants du compte démo "
            "sont préremplis (demo / demo).")
    auth.formulaire_connexion()
    st.stop()

# Les deux comptes (theo et demo) passent par le même stockage, filtré par db.py sur user_id.
store = db
marche_fn = D.cours_batch
fonds_fn = D.fondamentaux_batch

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))

t1, t2, t3 = st.columns([4, 1, 1], vertical_alignment="center")
t1.title("📈 Mon PEA")
t1.caption(f"Compte : {auth.utilisateur()}")
if mode_demo:
    st.info("🧪 **Compte démo partagé** : portefeuille fictif persistant (les cours de marché peuvent être réels). "
            "Les ajouts et suppressions sont visibles par tous les visiteurs du compte demo. "
            "N'y saisissez aucune donnée personnelle. Les fonctions IA sont désactivées.")
if t2.button("🔄", help="Actualiser les cours"):
    D.cours_batch.clear()
    D.fondamentaux_batch.clear()
    db.rafraichir()
    st.rerun()
if t3.button("🔒", help="Se déconnecter"):
    auth.deconnecter()
    st.rerun()

# --------------------------------------------------------------------------- #
# Chargement des données
# --------------------------------------------------------------------------- #
try:
    trans, div, vers = store.lire("transactions"), store.lire("dividendes"), store.lire("versements")
    tick, sect, snaps = store.lire("tickers"), store.lire("secteurs"), store.lire("snapshots")
except Exception as e:  # pas de détail à l'écran : il pourrait contenir des infos sensibles
    st.error("Connexion à la base impossible. Vérifiez SUPABASE_URL et SUPABASE_KEY dans les "
             "secrets, et que schema.sql a bien été exécuté.")
    st.caption(f"Type d'erreur : {type(e).__name__}")
    st.stop()

tables_manquantes = []


def lire_sur(table: str) -> pd.DataFrame:
    """Tables ajoutées en v3 : si elles n'existent pas encore, l'app reste utilisable."""
    try:
        return store.lire(table)
    except Exception:
        tables_manquantes.append(table)
        return pd.DataFrame(columns=SCHEMA.get(table, ["id"]))  # tolère un schema.py obsolète


wl, scen = lire_sur("watchlist"), lire_sur("scenarios")
scen_tr, analyses = lire_sur("scenario_trades"), lire_sur("analyses_ia")
analyses_scen = lire_sur("analyses_scen")
chat_log = lire_sur("chat_log")
if tables_manquantes:
    st.warning("Tables manquantes : " + ", ".join(tables_manquantes)
               + ". Exécutez la version à jour de schema.sql dans Supabase.")

tmap = (tick.set_index("isin") if not tick.empty
        else pd.DataFrame(columns=["ticker", "nom", "dernier_prix", "dernier_prix_at", "url"]))
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
    marche, horo = marche_fn(tickers) if tickers else ({}, maintenant())
    lignes, maj = [], []
    for isin in isins:
        connu = isin in tmap.index
        ticker = tmap.loc[isin, "ticker"] if connu else None
        dernier = tmap.loc[isin, "dernier_prix"] if connu else None
        dernier = None if dernier is None or pd.isna(dernier) else float(dernier)
        m = marche.get(ticker, {})
        prix, prev, statut = m.get("prix"), m.get("prev"), "live"
        if prix is None:
            prix, statut = dernier, ("obsolète" if dernier else "estimé")
        elif connecte and connu and (dernier is None or abs(dernier - prix) > 1e-9):
            maj.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin),
                        "dernier_prix": prix, "dernier_prix_at": maintenant().isoformat()})
        lignes.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin) if connu else None,
                       "prix": prix, "prev_close": prev, "statut": statut})
    cols = ["isin", "ticker", "nom", "prix", "prev_close", "statut"]
    return pd.DataFrame(lignes, columns=cols), maj, horo, tickers


isins_tous = list(dict.fromkeys(positions["isin"].tolist() + wl["isin"].tolist() + scen_tr["isin"].tolist()))
cours_all, maj_prix, horodatage, tickers_tous = charger_cours(isins_tous)
fonds = fonds_fn(tickers_tous) if tickers_tous else {}


def secteur_de(isin: str, ticker) -> str:
    return sect_dict.get(isin) or fonds.get(ticker, {}).get("secteur_yahoo") or "Inconnu"


def enrichir_complet(pos_brutes: pd.DataFrame) -> pd.DataFrame:
    if pos_brutes.empty:
        return pos_brutes.copy()
    p = C.enrichir_positions(pos_brutes, cours_all, div_par_isin)
    p["secteur"] = [secteur_de(i, t) for i, t in zip(p["isin"], p["ticker"])]
    return p


def prix_courant(isin: str):
    r = cours_all[cours_all["isin"] == isin]
    return None if r.empty or pd.isna(r.iloc[0]["prix"]) else float(r.iloc[0]["prix"])


pos = enrichir_complet(positions)
s = C.synthese(pos, flux, vers)

# Mémorise les derniers cours et le point de courbe du jour pour le compte courant.
if connecte:
    try:
        if maj_prix:
            db.upsert("tickers", maj_prix, "isin")
        estimes = (not pos.empty) and (pos["statut"] == "estimé").any()
        if not trans.empty and not estimes and maintenant().weekday() < 5:
            auj = pd.Timestamp(maintenant().date())
            ligne = snaps[snaps["date"] == auj]
            nouveau = {"valeur": round(s["valeur_totale"], 2), "apports": round(s["apports"], 2)}
            if ligne.empty or any(abs(ligne.iloc[0][k] - v) > 0.01 for k, v in nouveau.items()):
                db.upsert("snapshots", [{"date": auj, **nouveau}], "date")
    except Exception:
        pass  # un échec d'écriture ne doit jamais bloquer l'affichage

manquants = sorted(set(trans["isin"]) - set(tmap.index)) if connecte else []


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
CONTEXTES_URL = ("pf", "pj", "wl")  # une clé de widget par onglet (même ISIN possible dans plusieurs)


def url_publication(isin: str) -> str | None:
    """Lien de publication d'un ISIN : tickers.url, sinon l'ancienne colonne watchlist.url."""
    if "url" in tmap.columns and isin in tmap.index:
        u = C.nettoyer_url(tmap.loc[isin, "url"])
        if u:
            return u
    if "url" in wl.columns and not wl.empty:
        sel = wl.loc[wl["isin"] == isin, "url"]
        if len(sel):
            return C.nettoyer_url(sel.iloc[0])
    return None


def lien_md(isin: str) -> str:
    """Ligne Markdown « 📄 Publication » (vide si aucun lien)."""
    u = url_publication(isin)
    return f"  \n[📄 Publication]({u})" if u else ""


def _present(x) -> bool:
    return x is not None and not pd.isna(x) and x != 0


def lignes_fondamentaux(f: dict) -> list[tuple[str, str]]:
    """Fondamentaux Yahoo disponibles, dans le même ordre partout ; les valeurs absentes sont omises."""
    f = f or {}
    defs = [
        ("PER", "per", lambda x: fmt(x, 1)),
        ("PER prévisionnel", "per_prev", lambda x: fmt(x, 1)),
        ("Chiffre d'affaires", "ca", C.formater_gros_nombre),
        ("Bénéfice net", "net_income", C.formater_gros_nombre),
        ("EBITDA", "ebitda", C.formater_gros_nombre),
        ("Capitalisation", "capi", C.formater_gros_nombre),
        ("Valeur d'entreprise", "ev", C.formater_gros_nombre),
        ("EV/EBITDA", "ev_ebitda", lambda x: f"{fmt(x, 1)}x"),
        ("Actifs sous gestion", "net_assets", C.formater_gros_nombre),
        ("Frais annuels", "expense_ratio", lambda x: f"{fmt(x, 2)} %"),
    ]
    return [(lbl, fn(f[k])) for lbl, k, fn in defs if _present(f.get(k))]


def enregistrer_url(isin: str, url: str | None) -> str | None:
    """Mémorise (ou efface) l'URL d'un ISIN dans tickers. Retourne un message d'erreur ou None."""
    try:
        db.modifier("tickers", isin, {"url": url}, cle="isin")
    except Exception:
        return ("URL non enregistrée : exécutez dans Supabase « alter table tickers "
                "add column if not exists url text; »")
    return None


def _enregistrer_url_cb(isin: str, cle: str) -> None:
    brut = st.session_state.get(cle, "").strip()
    url = C.nettoyer_url(brut) if brut else None
    if brut and not url:
        flash("URL invalide : elle doit commencer par http:// ou https://.")
        return
    err = enregistrer_url(isin, url)
    if err:
        flash(err)
        return
    for ctx in CONTEXTES_URL:  # garde les éditeurs des autres onglets synchronisés
        if f"url_{ctx}_{isin}" in st.session_state:
            st.session_state[f"url_{ctx}_{isin}"] = url or ""
    flash("Lien enregistré ✅" if url else "Lien supprimé")


def _chercher_url_cb(cle: str, nom: str, ticker, isin: str) -> None:
    url = D.chercher_url_publication(nom, ticker if isinstance(ticker, str) else None, isin)
    if url:
        st.session_state[cle] = url
        flash("Seule la page d'accueil a été trouvée : précisez l'URL à la main si besoin."
              if R.est_page_accueil(url) else "URL trouvée : vérifiez-la puis enregistrez.")
    else:
        flash("Aucune URL trouvée : saisissez-la manuellement.")


def editeur_url(isin: str, ctx: str) -> None:
    """Champ « URL de publication » du compte courant avec enregistrement et recherche."""
    if not connecte:
        return
    cle = f"url_{ctx}_{isin}"
    if cle not in st.session_state:
        st.session_state[cle] = url_publication(isin) or ""
    st.text_input("URL de publication", key=cle, placeholder="https://…")
    ticker = tmap.loc[isin, "ticker"] if isin in tmap.index else None
    c1, c2 = st.columns(2)
    c1.button("💾 Enregistrer", key=cle + "_ok", on_click=_enregistrer_url_cb, args=(isin, cle))
    c2.button("🔍 Chercher", key=cle + "_q", on_click=_chercher_url_cb,
              args=(cle, nom_de(tmap, isin), ticker, isin), help="Recherche web de la publication financière")


def carte_ligne(r, ctx: str) -> None:
    """Carte d'une ligne détenue (réelle ou projetée) : synthèse, lien, détails + fondamentaux."""
    badge = "" if r.statut == "live" else f" ⚠️ {r.statut}"
    jour = pastille(r.var_jour_pct, f"{fmt(r.var_jour_pct, 2, True)} % auj.")
    total = pastille(r.perf_pct, f"{fmt(r.perf_pct, 1, True)} % total")
    with st.container(border=True):
        g, d = st.columns([3, 2])
        g.markdown(f"**{r.nom}**{badge}  \n{r.secteur} · {fmt(r.poids_pct, 0)} %{lien_md(r.isin)}")
        d.markdown(f"<div style='text-align:right'><b>{fmt(r.valeur)} €</b><br>"
                   f"{jour}<br>{total}</div>", unsafe_allow_html=True)
        with st.expander("Détails"):
            f = fonds.get(r.ticker, {})
            details = ([("Quantité", f"{r.quantite:g}"),
                        ("PRM", f"{fmt(r.prm)} €"),
                        ("Cours", f"{fmt(r.prix_eff)} €"),
                        ("+/- value latente", f"{fmt(r.pv_latente, 2, True)} €"),
                        ("Dividendes perçus", f"{fmt(r.dividendes)} €")]
                       + lignes_fondamentaux(f)
                       + [("ISIN · ticker", f"{r.isin} · {r.ticker}")])
            st.markdown("\n".join(f"- {k} : **{v}**" for k, v in details))
            editeur_url(r.isin, ctx)


# --------------------------------------------------------------------------- #
# Analyse IA
# --------------------------------------------------------------------------- #
def afficher_analyse(res: dict, quand, perime: bool, scenario: bool = False) -> None:
    c1, c2 = st.columns([1, 2])
    c1.metric("Note globale", f"{llm.note_globale(res):.1f}/10")
    c2.markdown(f"_{res['conclusion']}_")
    for c in res["criteres"]:
        st.markdown(f"**{c['label']}** · {c['note']}/10")
        st.progress(c["note"] / 10)
        st.caption(c["synthese"])
        if scenario:  # avantages / inconvénients du scénario par rapport à l'actuel
            for a in c.get("avantages", []):
                st.markdown(f"🟢 {a}")
            for i in c.get("inconvenients", []):
                st.markdown(f"🔴 {i}")
    suite = " · ⚠️ scénario modifié depuis" if (perime and scenario) else \
        (" · ⚠️ portefeuille modifié depuis" if perime else "")
    st.caption(f"Analysé le {quand:%d/%m/%Y à %H:%M} · {res.get('modele', '')}{suite}")
    st.caption(llm.AVERTISSEMENT)


def bloc_ia() -> None:
    with st.container(border=True):
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

        cle_api = auth.secret("GEMINI_API_KEY")
        modele = auth.secret("GEMINI_MODEL") or llm.MODELE_DEFAUT
        per_isin = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, empreinte = llm.construire_contexte(pos, s["cash"], per_isin, modele)

        jours = (pd.to_datetime(analyses["cree_le"], utc=True, errors="coerce").dt.tz_convert(PARIS).dt.date
                 if not analyses.empty else pd.Series(dtype=object))
        n_auj = int((jours == maintenant().date()).sum())
        limite = n_auj >= llm.MAX_APPELS_PAR_JOUR
        a_jour = derniere is not None and derniere["empreinte"] == empreinte

        label = "✨ Relancer l'analyse" if a_jour else "✨ Analyser mon portefeuille"
        clic = st.button(label, key="ia_btn", disabled=(not cle_api) or limite)
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer l'analyse.")
        elif limite:
            st.caption(f"Limite de {llm.MAX_APPELS_PAR_JOUR} analyses par jour atteinte.")
        else:
            st.caption("Envoie à Gemini uniquement les poids en % (aucun montant en €).")

        if clic:
            try:
                with st.spinner("Analyse en cours…"):
                    res = llm.analyser(texte, cle_api, modele)
            except llm.ErreurIA as e:
                st.error(str(e))
            else:
                store.inserer("analyses_ia", {"modele": modele, "empreinte": empreinte, "resultat": res})
                flash("Analyse enregistrée ✨")
                st.rerun()

        if derniere is not None:
            quand = pd.to_datetime(derniere["cree_le"], utc=True).tz_convert(PARIS)
            afficher_analyse(derniere["resultat"], quand, not a_jour)


def bloc_ia_scenario(sid: int, pos_p: pd.DataFrame, cash_p: float,
                     operations: str, versement: float) -> None:
    """Analyse IA du scénario : note les 4 critères du projeté + avantages/inconvénients vs actuel."""
    with st.container(border=True):
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

        cle_api = auth.secret("GEMINI_API_KEY")
        modele = auth.secret("GEMINI_MODEL") or llm.MODELE_DEFAUT
        per_p = {i: fonds.get(t, {}).get("per") for i, t in zip(pos_p["isin"], pos_p["ticker"])}
        per_a = {i: fonds.get(t, {}).get("per") for i, t in zip(pos["isin"], pos["ticker"])}
        texte, empreinte = llm.construire_contexte_scenario(
            pos_p, cash_p, per_p, pos, s["cash"], per_a, modele, sid, operations, versement)

        # quota commun : analyses du portefeuille + des scénarios
        n_auj = 0
        for table in (analyses, analyses_scen):
            if not table.empty:
                jours = (pd.to_datetime(table["cree_le"], utc=True, errors="coerce")
                         .dt.tz_convert(PARIS).dt.date)
                n_auj += int((jours == maintenant().date()).sum())
        limite = n_auj >= llm.MAX_APPELS_PAR_JOUR
        a_jour = derniere is not None and derniere["empreinte"] == empreinte

        label = "✨ Relancer l'analyse" if a_jour else "✨ Analyser ce scénario"
        clic = st.button(label, key=f"ias_btn_{sid}", disabled=(not cle_api) or limite)
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer l'analyse.")
        elif limite:
            st.caption(f"Limite de {llm.MAX_APPELS_PAR_JOUR} analyses par jour atteinte.")
        else:
            st.caption("Envoie à Gemini uniquement les poids en % (aucun montant en €).")

        if clic:
            try:
                with st.spinner("Analyse en cours…"):
                    res = llm.analyser(texte, cle_api, modele, scenario=True)
            except llm.ErreurIA as e:
                st.error(str(e))
            else:
                store.inserer("analyses_scen", {"scenario_id": sid, "modele": modele,
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
                      f"PER {fmt(f.get('per'), 1)} | cap. {C.formater_gros_nombre(f.get('capi'))} | "
                      f"CA {C.formater_gros_nombre(f.get('ca'))} | dividendes perçus {fmt(r.dividendes)} €")
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
              operations: str = "", versement: float = 0.0) -> None:
    """Chatbot : discussion libre sur le portefeuille actuel ou sur un scénario projeté.
    Une conversation distincte par scénario (clé de session dédiée)."""
    uid = auth.utilisateur() or "inconnu"
    cle_session = f"chat_{uid}_scen_{sid}" if scenario else f"chat_{uid}_msgs"
    titre = "#### 💬 Discuter de ce scénario" if scenario else "#### 💬 Discuter de mon portefeuille"
    with st.container(border=True):
        st.markdown(titre)
        if mode_demo:
            st.caption("Chat IA désactivé sur le compte démo pour éviter toute consommation de tokens.")
            return
        if pos.empty:
            st.caption("Aucune ligne dans le portefeuille.")
            return
        cle_api = auth.secret("GEMINI_API_KEY")
        modele = auth.secret("GEMINI_MODEL") or llm.MODELE_DEFAUT
        if not cle_api:
            st.caption("Ajoutez `GEMINI_API_KEY` dans les secrets pour activer le chat.")
            return

        if cle_session not in st.session_state:
            st.session_state[cle_session] = []
        for m in st.session_state[cle_session]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        if st.session_state[cle_session] and st.button("🧹 Effacer la conversation", key=cle_session + "_reset"):
            st.session_state[cle_session] = []
            st.rerun()

        if not chat_log.empty:
            jours = (pd.to_datetime(chat_log["cree_le"], utc=True, errors="coerce")
                     .dt.tz_convert(PARIS).dt.date)
            limite = int((jours == maintenant().date()).sum()) >= llm.MAX_CHAT_PAR_JOUR
        else:
            limite = False
        if limite:
            st.caption(f"Limite de {llm.MAX_CHAT_PAR_JOUR} messages par jour atteinte.")
            return

        # clé propre à chaque conversation : bloc_chat() est appelé 2 fois par page (Portefeuille + Projet)
        question = (st.chat_input("Posez une question…", key=f"chat_in_{cle_session}") or "").strip()
        if question:
            ctx = contexte_chat(modele, scenario, sid, pos_p, cash_p, operations, versement)
            try:
                with st.spinner("Réponse en cours…"):
                    rep = llm.discuter(ctx, st.session_state[cle_session], question, cle_api, modele)
            except llm.ErreurIA as e:
                st.error(str(e))
            else:
                st.session_state[cle_session] = (st.session_state[cle_session]
                                                 + [{"role": "user", "content": question},
                                                    {"role": "model", "content": rep}])[-12:]
                store.inserer("chat_log", {})
                st.rerun()


# --------------------------------------------------------------------------- #
# Onglet Watchlist
# --------------------------------------------------------------------------- #
def onglet_watchlist() -> None:
    if wl.empty:
        st.info("Votre watchlist est vide. Ajoutez des valeurs : elles seront proposées dans les "
                "formulaires de saisie et dans les scénarios.")
    for r in wl.itertuples():
        c = cours_all[cours_all["isin"] == r.isin]
        prix = prev = None
        if not c.empty:
            prix, prev = c.iloc[0]["prix"], c.iloc[0]["prev_close"]
        var = (prix / prev - 1) * 100 if prix and prev and not pd.isna(prev) else None
        note = "" if r.note is None or pd.isna(r.note) else f"  \n_{r.note}_"
        ticker = tmap.loc[r.isin, "ticker"] if r.isin in tmap.index else None
        f = fonds.get(ticker, {}) if ticker else {}

        with st.container(border=True):
            g, d = st.columns([3, 2])
            g.markdown(f"**{nom_de(tmap, r.isin)}**  \n{secteur_de(r.isin, ticker)}{note}{lien_md(r.isin)}")
            txt = f"<b>{fmt(prix)} €</b>" if prix and not pd.isna(prix) else "N/A"
            if var is not None:
                txt += "<br>" + pastille(var, f"{fmt(var, 2, True)} % auj.")
            d.markdown(f"<div style='text-align:right'>{txt}</div>", unsafe_allow_html=True)
            with st.expander("Détails"):
                details = ([("Cours", f"{fmt(prix)} €")] + lignes_fondamentaux(f)
                           + [("ISIN · ticker", f"{r.isin} · {ticker or '—'}")])
                st.markdown("\n".join(f"- {k} : **{v}**" for k, v in details))
                editeur_url(r.isin, "wl")
                if connecte and st.button("🗑 Retirer de la watchlist", key=f"wl_del_{r.isin}"):
                    store.supprimer("watchlist", r.isin, cle="isin")
                    st.session_state.pop(f"url_wl_{r.isin}", None)
                    flash("Retiré de la watchlist")
                    st.rerun()

    with st.expander("➕ Ajouter une action / un ETF"):
        if not connecte:
            st.caption("Disponible après connexion.")
            return
        # Remise à zéro des champs après un ajout (autorisée ici : avant la création des widgets)
        if st.session_state.pop("wl_reset", False):
            for k in ("wl_isin", "wl_tk", "wl_note", "wl_url"):
                st.session_state[k] = ""
        st.text_input("ISIN", placeholder="FR0000121014", key="wl_isin")
        st.text_input("Ticker Yahoo (facultatif)", key="wl_tk",
                      placeholder="ex : MC.PA — si l'ISIN n'est pas reconnu")
        st.text_input("Note (facultatif)", key="wl_note")
        st.text_input("URL de publication (facultatif)", key="wl_url",
                      placeholder="ex : https://investor.societe.com")
        c_add, c_cherche = st.columns(2)
        ajouter = c_add.button("Ajouter", key="wl_add", type="primary")
        c_cherche.button("🔍 Chercher l'URL", key="wl_cherche", on_click=_chercher_url_wl,
                         args=(tmap,), help="Recherche web de la publication financière")
        if msg := st.session_state.pop("wl_msg", None):
            st.info(msg)

        if ajouter:
            isin = st.session_state.get("wl_isin", "").strip().upper()
            tk = st.session_state.get("wl_tk", "").strip().upper()
            note = st.session_state.get("wl_note", "").strip()
            url_saisie = C.nettoyer_url(st.session_state.get("wl_url", ""))
            if st.session_state.get("wl_url", "").strip() and not url_saisie:
                st.error("URL invalide : elle doit commencer par http:// ou https://.")
            elif not C.isin_valide(isin):
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
                url_value = url_saisie
                if url_value is None:  # recherche automatique (silencieuse en cas d'échec)
                    nom = (nom_de(tmap, isin) if isin in tmap.index else (trouve or {}).get("nom"))
                    ticker_url = tmap.loc[isin, "ticker"] if isin in tmap.index else tk or None
                    url_value = D.chercher_url_publication(nom, ticker_url, isin) if nom else None
                db.upsert("watchlist", [{"isin": isin, "note": note or None}], "isin")
                msg = "Ajouté à la watchlist ✅"
                if url_value:
                    err_url = enregistrer_url(isin, url_value)
                    if err_url:
                        msg += " — " + err_url
                st.session_state["wl_reset"] = True
                flash(msg)
                st.rerun()


def _chercher_url_wl(tmap_: pd.DataFrame) -> None:
    """Callback du bouton « Chercher l'URL » : remplit le champ URL (modifiable ici, pas après coup)."""
    isin = st.session_state.get("wl_isin", "").strip().upper()
    if not C.isin_valide(isin):
        st.session_state["wl_msg"] = "Saisissez d'abord un ISIN valide."
        return
    if isin in tmap_.index:
        nom, ticker = nom_de(tmap_, isin), tmap_.loc[isin, "ticker"]
    else:
        trouve = D.chercher_ticker(isin) or {}
        nom, ticker = trouve.get("nom"), trouve.get("ticker")
    url = D.chercher_url_publication(nom, ticker, isin) if nom else None
    if url:
        st.session_state["wl_url"] = url
    else:
        st.session_state["wl_msg"] = "Aucune URL trouvée : saisissez-la manuellement."


# --------------------------------------------------------------------------- #
# Onglet Projet (scénarios)
# --------------------------------------------------------------------------- #
def graphique_compare(df: pd.DataFrame, cle: str) -> None:
    d = df.iloc[::-1].copy()  # le plus gros en haut
    d[cle] = sans_parentheses(d[cle])  # noms épurés
    fig = go.Figure()
    fig.add_bar(y=d[cle], x=d["reel"], name="Actuel", orientation="h")
    fig.add_bar(y=d[cle], x=d["projete"], name="Projeté", orientation="h")
    fig.update_layout(barmode="group", margin=dict(l=0, r=0, t=10, b=0), height=max(240, 52 * len(d) + 70),
                      legend=dict(orientation="h", y=-0.12), xaxis_title="% du PEA")
    fig.update_xaxes(fixedrange=True)  # pas de zoom tactile
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=PLOTLY)


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
                row = store.inserer("scenarios", {"nom": nom, "versement": 0})
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
        st.markdown(f"- {r.type} {r.quantite:g} × {nom_de(tmap, r.isin)} @ {fmt(r.prix)} € "
                    f"(≈ {fmt(r.quantite * r.prix, 0)} €)")
    if versement:
        st.markdown(f"- Versement fictif : {fmt(versement, 0)} €")
    b1, b2, b3 = st.columns(3)
    if b1.button("↩️ Annuler", disabled=sim.empty, key="sc_undo", help="Annule la dernière opération"):
        store.supprimer("scenario_trades", int(sim["id"].max()))
        st.rerun()
    if b2.button("🧹 Vider", disabled=sim.empty and versement == 0, key="sc_clear",
                 help="Repart du PEA actuel"):
        store.supprimer("scenario_trades", sid, cle="scenario_id")
        store.modifier("scenarios", sid, {"versement": 0})
        st.rerun()
    if b3.button("🗑 Supprimer", key="sc_del", help="Supprime le scénario"):
        store.supprimer("scenarios", sid)
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
                            store.inserer("scenario_trades", {"scenario_id": sid, "isin": isin, "type": typ,
                                                              "quantite": qte, "prix": px_})
                            st.rerun()
        v = st.number_input("Versement fictif (€)", min_value=0.0, value=versement, step=100.0,
                            key=f"sc_vers_{sid}")
        if st.button("Appliquer le versement", key="sc_vers_btn", disabled=(v == versement)):
            store.modifier("scenarios", sid, {"versement": float(v)})
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
    st.markdown("**Par ligne**")
    graphique_compare(par_ligne, "label")
    st.markdown("**Par secteur**")
    graphique_compare(par_secteur, "secteur")
    with st.expander("Détail des écarts (points de %)"):
        tableau = par_ligne.rename(columns={"label": "Ligne", "reel": "Actuel %", "projete": "Projeté %",
                                            "ecart": "Écart"}).round(1)
        st.dataframe(tableau, hide_index=True)
    st.subheader("Lignes du scénario")
    for r in pos_p.sort_values("valeur", ascending=False).itertuples():
        carte_ligne(r, "pj")
    ops = "; ".join(f"{r.type} {r.quantite:g} × {nom_de(tmap, r.isin)}" for r in sim.itertuples())
    bloc_ia_scenario(sid, pos_p, cash_p, ops, versement)
    bloc_chat(scenario=True, sid=sid, pos_p=pos_p, cash_p=cash_p, operations=ops, versement=versement)
    st.caption("Simulation de répartition uniquement : aucune prévision de rendement.")


# --------------------------------------------------------------------------- #
# Onglet Saisie (tous les comptes connectés)
# --------------------------------------------------------------------------- #
def onglet_saisie() -> None:
    if not connecte:
        st.info("🔒 La saisie est disponible après connexion.")
        return
    action = st.selectbox("Action", ["Transaction", "Dividende", "Versement / retrait", "Secteurs",
                                     "Corriger / supprimer", "Maintenance & sauvegarde"])

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
                prix_hist, isin_ticker = {}, tmap["ticker"].to_dict()
                for t in set(isin_ticker.values()):
                    try:
                        prix_hist[t] = D.historique_cloture(t, debut)
                    except Exception:
                        pass
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
                    if not t or enregistrer_ticker(isin, t["ticker"], t["nom"]):
                        echecs.append(isin)
                flash("Tickers résolus ✅" if not echecs else f"Échec pour : {', '.join(echecs)}")
                st.rerun()
            with st.form("f_tk"):
                isin = st.selectbox("ISIN", manquants)
                tk = st.text_input("Ticker Yahoo", placeholder="ex : MC.PA")
                ok = st.form_submit_button("Enregistrer le ticker")
            if ok:
                err = enregistrer_ticker(isin, tk.strip().upper()) if tk.strip() else "Ticker vide."
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
tab_pf, tab_hist, tab_proj, tab_wl, tab_saisie = st.tabs(
    ["📊 Portefeuille", "📈 Historique", "🔭 Projet", "👀 Watchlist", "➕ Saisie"])

with tab_pf:
    if erreur_journal:
        st.error(f"Journal incohérent : {erreur_journal} Corrigez-le dans Saisie › Corriger / supprimer.")
    if manquants:
        st.warning("Ticker manquant pour : " + ", ".join(manquants)
                   + " (Saisie › Maintenance). Ces lignes sont valorisées à leur prix de revient.")

    if trans.empty:
        st.info("Aucune transaction pour l'instant. Rendez-vous dans l'onglet « Saisie ».")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Valeur du PEA", f"{fmt(s['valeur_totale'])} €",
                  f"{fmt(s['var_jour_eur'], 2, True)} € ({fmt(s['var_jour_pct'], 2, True)} %) auj.")
        c2.metric("Plus-value globale", f"{fmt(s['pv_globale'])} €", f"{fmt(s['perf_pct'], 2, True)} %")
        c3, c4 = st.columns(2)
        c3.metric("Apports nets", f"{fmt(s['apports'])} €")
        c4.metric("Cash disponible", f"{fmt(s['cash'])} €")
        st.progress(min(s["plafond_pct"] / 100, 1.0),
                    text=f"Plafond de versements : {fmt(s['versements_cumules'], 0)} / 150 000 € "
                         f"({fmt(s['plafond_pct'], 1)} %)")

        bloc_ia()

        bloc_chat()

        if s["cash"] < -0.01:
            st.warning("Cash négatif : il manque des versements dans le journal "
                       "(Saisie › Versement / retrait).")
        if not pos.empty:
            for r in pos.itertuples():
                if r.poids_pct > SEUIL_CONCENTRATION:
                    st.warning(f"⚠️ Concentration : {r.nom} pèse {fmt(r.poids_pct, 0)} % des titres "
                               f"(seuil {SEUIL_CONCENTRATION:.0f} %).")
            hors_ligne = pos[pos["statut"] != "live"]
            if not hors_ligne.empty:
                st.warning("Cours indisponibles pour " + ", ".join(hors_ligne["nom"])
                           + " : dernier cours connu ou prix de revient utilisé.")
            st.caption(("Cours Yahoo différés" if connecte else "Cours fictifs")
                       + f" · actualisés à {horodatage:%H:%M}" + (" (cache 5 min)" if connecte else ""))

            # -- Une carte par ligne (lisible sur téléphone) ---------------- #
            for r in pos.sort_values("valeur", ascending=False).itertuples():
                carte_ligne(r, "pf")

            # -- KPIs étendus --------------------------------------------- #
            col1, col2, col3 = st.columns(3)
            with col1:
                max_concentration = pos["poids_pct"].max() if not pos.empty else 0.0
                st.metric("Concentration max", f"{fmt(max_concentration, 0)} %")
            with col2:
                n_lignes = len(pos)
                st.metric("Lignes actives", n_lignes)
            with col3:
                total_dividendes = pos["dividendes"].sum() if not pos.empty else 0.0
                rendement_div = (total_dividendes / s["valeur_totale"] * 100) if s["valeur_totale"] > 0 else 0.0
                st.metric("Rendement dividendes", f"{fmt(rendement_div, 1)} %",
                         f"{fmt(total_dividendes)} €")

            # -- Graphiques ------------------------------------------------- #
            st.subheader("Répartition")
            
            if not pos.empty:
                secteur_data = pos.groupby("secteur")["valeur"].sum().reset_index()
                if len(secteur_data) > 0:
                    fig_pie = px.pie(secteur_data, values="valeur", names="secteur",
                                     title="Par secteur", hole=0.3)
                    fig_pie.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=250,
                                          showlegend=True, legend=dict(orientation="h", y=-0.1))
                    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_pie, config=PLOTLY)
            
            pos_fig = pos.assign(nom=sans_parentheses(pos["nom"]))
            fig = px.treemap(pos_fig, path=[px.Constant("PEA"), "secteur", "nom"], values="valeur",
                             color="perf_pct", color_continuous_scale="RdYlGn",
                             color_continuous_midpoint=0)
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340, coloraxis_showscale=False)
            st.plotly_chart(fig, config=PLOTLY)

            st.subheader("Performance latente par ligne")
            perf_data = (pos.assign(nom=sans_parentheses(pos["nom"]),
                                    perf_pct=pos["perf_pct"])
                        .sort_values("perf_pct", ascending=False))
            fig_perf = px.bar(perf_data, x="perf_pct", y="nom", orientation="h",
                             color="perf_pct", color_continuous_scale="RdYlGn",
                             color_continuous_midpoint=0,
                             labels={"perf_pct": "Performance %", "nom": ""},
                             title="Performance latente (vs PRM)")
            fig_perf.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=max(220, 44 * len(perf_data)),
                                  coloraxis_showscale=False)
            fig_perf.update_xaxes(fixedrange=True)
            fig_perf.update_yaxes(fixedrange=True)
            st.plotly_chart(fig_perf, config=PLOTLY)

            st.subheader("Contribution à la performance (€)")
            contrib = (pos.assign(contrib=pos["pv_latente"] + pos["dividendes"],
                                  nom=sans_parentheses(pos["nom"]))
                       .sort_values("contrib"))
            fig = px.bar(contrib, x="contrib", y="nom", orientation="h", color="contrib",
                         color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                         labels={"contrib": "PV latente + dividendes (€)", "nom": ""})
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=max(220, 44 * len(contrib)),
                              coloraxis_showscale=False)
            fig.update_xaxes(fixedrange=True)
            fig.update_yaxes(fixedrange=True)
            st.plotly_chart(fig, config=PLOTLY)

        if not ventes.empty or not div.empty:
            with st.expander("Plus-values réalisées & dividendes"):
                st.markdown(f"- Plus-values réalisées : **{fmt(ventes['pv'].sum(), 2, True)} €**\n"
                            f"- Dividendes nets perçus : **{fmt(div['montant'].sum())} €**")

with tab_hist:
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
            fig = go.Figure()
            fig.add_scatter(x=sn["date"], y=sn["valeur"], name="Valeur du PEA", mode="lines")
            fig.add_scatter(x=sn["date"], y=sn["apports"], name="Apports nets", mode="lines",
                            line=dict(shape="hv", dash="dot"))
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300,
                              legend=dict(orientation="h", y=-0.15))
            fig.update_xaxes(fixedrange=True)  # pas de zoom tactile
            fig.update_yaxes(fixedrange=True)
            st.plotly_chart(fig, config=PLOTLY)

            st.subheader("Performance vs indice")
            st.caption("Performance pondérée par le temps : neutralise vos versements, base 100.")
            choix = st.selectbox("Comparer à", list(BENCHMARKS), label_visibility="collapsed")
            twr = C.calcul_twr(sn)
            bench = None
            if connecte:  # le compte demo utilise aussi les cours et historiques Yahoo
                try:
                    h = D.historique_cloture(BENCHMARKS[choix], sn["date"].min().strftime("%Y-%m-%d"))
                    bench = h.reindex(h.index.union(twr["date"])).ffill().reindex(twr["date"]).bfill()
                    bench = bench / bench.iloc[0] * 100
                except Exception:
                    st.caption("Indice indisponible pour le moment.")
            else:
                st.caption("Comparaison à un indice disponible après connexion.")
            fig = go.Figure()
            fig.add_scatter(x=twr["date"], y=twr["twr"], name="Mon PEA", mode="lines")
            if bench is not None:
                fig.add_scatter(x=twr["date"], y=bench.to_numpy(), name=choix, mode="lines")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300,
                              legend=dict(orientation="h", y=-0.15))
            fig.update_xaxes(fixedrange=True)  # pas de zoom tactile
            fig.update_yaxes(fixedrange=True)
            st.plotly_chart(fig, config=PLOTLY)
            resume = f"Mon PEA : **{fmt(twr['twr'].iloc[-1] - 100, 2, True)} %**"
            if bench is not None:
                resume += f" · {choix} : **{fmt(bench.iloc[-1] - 100, 2, True)} %**"
            st.markdown(resume)

with tab_proj:
    onglet_projet()

with tab_wl:
    onglet_watchlist()

with tab_saisie:
    onglet_saisie()
