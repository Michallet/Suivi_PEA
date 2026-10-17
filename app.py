"""Suivi PEA — interface Streamlit mobile-first.

Local : streamlit run app.py   (secrets dans .streamlit/secrets.toml, voir secrets.toml.example)
"""
from __future__ import annotations

import hmac
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import calculs as C
import db
import donnees as D

st.set_page_config(page_title="Suivi PEA", page_icon="📈", layout="centered")

SEUIL_CONCENTRATION = 25.0  # % du portefeuille au-delà duquel on alerte
BENCHMARKS = {"MSCI World (CW8)": "CW8.PA", "CAC 40": "^FCHI", "Euro Stoxx 50": "^STOXX50E"}
VERT, ROUGE = "#16a34a", "#dc2626"
PARIS = ZoneInfo("Europe/Paris")
PLOTLY = {"displayModeBar": False}
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


def flash(msg: str) -> None:
    """Message affiché après le prochain rechargement (toast)."""
    st.session_state["flash"] = msg


def secret(nom: str):
    try:
        return st.secrets[nom]
    except Exception:
        return None


def demander_mdp(nom_secret: str, etiquette: str, cle: str) -> bool:
    """Déverrouille une zone par mot de passe. Refuse tout accès si le secret est absent."""
    attendu = secret(nom_secret)
    if attendu is None:
        st.error(f"Secret `{nom_secret}` non configuré : accès désactivé.")
        return False
    if st.session_state.get(cle):
        return True
    echecs = st.session_state.get(cle + "_n", 0)
    if echecs >= 5:
        st.error("Trop de tentatives. Rechargez la page plus tard.")
        return False
    with st.form(cle + "_form"):
        saisi = st.text_input(etiquette, type="password")
        valide = st.form_submit_button("Déverrouiller")
    if valide:
        if hmac.compare_digest(saisi.encode(), str(attendu).encode()):
            st.session_state[cle] = True
            st.rerun()
        st.session_state[cle + "_n"] = echecs + 1
        time.sleep(min(2 ** echecs, 8))  # ralentit les essais successifs
        st.error("Mot de passe incorrect.")
    return False


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
    db.upsert("tickers", [{"isin": isin, "ticker": ticker, "nom": v["nom"],
                           "dernier_prix": v["prix"],
                           "dernier_prix_at": maintenant().isoformat()}], "isin")
    return None


# --------------------------------------------------------------------------- #
# Accès, chargement des données
# --------------------------------------------------------------------------- #
if secret("VIEW_PASSWORD") is not None and not demander_mdp("VIEW_PASSWORD", "Mot de passe", "lecture_ok"):
    st.stop()

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))

try:
    trans, div, vers = db.lire("transactions"), db.lire("dividendes"), db.lire("versements")
    tick, sect, snaps = db.lire("tickers"), db.lire("secteurs"), db.lire("snapshots")
except Exception as e:  # on n'affiche pas le détail : il pourrait contenir des infos sensibles
    st.error("Connexion à la base impossible. Vérifiez SUPABASE_URL et SUPABASE_KEY dans les "
             "secrets, et que schema.sql a bien été exécuté.")
    st.caption(f"Type d'erreur : {type(e).__name__}")
    st.stop()

tmap = (tick.set_index("isin") if not tick.empty
        else pd.DataFrame(columns=["ticker", "nom", "dernier_prix", "dernier_prix_at"]))

t1, t2 = st.columns([4, 1], vertical_alignment="center")
t1.title("📈 Mon PEA")
if t2.button("🔄", help="Actualiser les cours"):
    D.cours_batch.clear()
    D.fondamentaux_batch.clear()
    db.lire.clear()
    st.rerun()

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
tickers_pos: tuple = ()
horodatage = maintenant()
fonds: dict = {}
pos = positions.copy()
maj_prix: list[dict] = []

if not positions.empty:
    isins = positions["isin"].tolist()
    tickers_pos = tuple(dict.fromkeys(tmap.loc[i, "ticker"] for i in isins if i in tmap.index))
    marche, horodatage = D.cours_batch(tickers_pos) if tickers_pos else ({}, maintenant())
    fonds = D.fondamentaux_batch(tickers_pos) if tickers_pos else {}

    lignes = []
    for isin in isins:
        connu = isin in tmap.index
        ticker = tmap.loc[isin, "ticker"] if connu else None
        dernier = tmap.loc[isin, "dernier_prix"] if connu else None
        dernier = None if dernier is None or pd.isna(dernier) else float(dernier)
        m = marche.get(ticker, {})
        prix, prev, statut = m.get("prix"), m.get("prev"), "live"
        if prix is None:  # Yahoo n'a pas répondu : dernier cours connu, sinon valorisation au PRM
            prix, statut = dernier, ("obsolète" if dernier else "estimé")
        elif connu and (dernier is None or abs(dernier - prix) > 1e-9):
            maj_prix.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin),
                             "dernier_prix": prix, "dernier_prix_at": maintenant().isoformat()})
        lignes.append({"isin": isin, "ticker": ticker, "nom": nom_de(tmap, isin) if connu else None,
                       "prix": prix, "prev_close": prev, "statut": statut})

    pos = C.enrichir_positions(positions, pd.DataFrame(lignes), div.groupby("isin")["montant"].sum())
    sect_dict = dict(zip(sect["isin"], sect["secteur"]))
    pos["secteur"] = [sect_dict.get(i) or fonds.get(t, {}).get("secteur_yahoo") or "Inconnu"
                      for i, t in zip(pos["isin"], pos["ticker"])]

s = C.synthese(pos, flux, vers)

# Mémorise les derniers cours (repli si Yahoo tombe) et le point de courbe du jour
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

manquants = sorted(set(trans["isin"]) - set(tmap.index))

# --------------------------------------------------------------------------- #
# Onglet Saisie
# --------------------------------------------------------------------------- #
def onglet_saisie() -> None:
    if not demander_mdp("ADMIN_PASSWORD", "Mot de passe admin", "admin_ok"):
        return
    if st.button("🔒 Verrouiller"):
        st.session_state["admin_ok"] = False
        st.rerun()

    action = st.selectbox("Action", ["Transaction", "Dividende", "Versement / retrait", "Secteurs",
                                     "Corriger / supprimer", "Maintenance & sauvegarde"])

    # -- Transaction ------------------------------------------------------- #
    if action == "Transaction":
        with st.form("f_trans", clear_on_submit=True):
            d = st.date_input("Date", maintenant().date(), format="DD/MM/YYYY")
            typ = st.radio("Type", ["ACHAT", "VENTE"], horizontal=True)
            isin = st.text_input("ISIN", placeholder="FR0000121014")
            q = st.number_input("Quantité", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
            p = st.number_input("Prix unitaire (€)", min_value=0.0, value=100.0, step=0.1, format="%.4f")
            fr = st.number_input("Frais (€)", min_value=0.0, value=0.0, step=0.1, format="%.2f")
            tk = st.text_input("Ticker Yahoo (facultatif)",
                               placeholder="ex : MC.PA — seulement si l'ISIN n'est pas reconnu")
            ok = st.form_submit_button("Enregistrer")
        if not ok:
            return

        isin, tk = isin.strip().upper(), tk.strip().upper()
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
            pv = v_apres["pv"].sum() - ventes["pv"].sum()
            msg += f" — plus-value réalisée : {fmt(pv, 2, True)} €"
        flash(msg)
        st.rerun()

    # -- Dividende --------------------------------------------------------- #
    elif action == "Dividende":
        if tmap.empty:
            st.info("Enregistrez d'abord une transaction.")
            return
        with st.form("f_div", clear_on_submit=True):
            d = st.date_input("Date", maintenant().date(), format="DD/MM/YYYY")
            isin = st.selectbox("Ligne", tmap.index.tolist(),
                                format_func=lambda i: f"{nom_de(tmap, i)} ({i})")
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
        actuels = dict(zip(sect["isin"], sect["secteur"]))
        with st.form("f_sect"):
            saisies = {i: st.text_input(f"{nom_de(tmap, i)} ({i})", value=actuels.get(i, ""))
                       for i in tmap.index}
            ok = st.form_submit_button("Enregistrer")
        if ok:
            db.upsert("secteurs", [{"isin": i, "secteur": v.strip()} for i, v in saisies.items() if v.strip()],
                      "isin")
            for i, v in saisies.items():
                if not v.strip() and i in actuels:
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
                         "Ajoutez-les d'abord via l'action « Transaction ».")
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
        for table in CFG:
            st.download_button(f"⬇️ {table}.csv", db.lire(table).to_csv(index=False),
                               file_name=f"{table}.csv", mime="text/csv", key=f"dl_{table}")


# --------------------------------------------------------------------------- #
# Mise en page : 3 onglets
# --------------------------------------------------------------------------- #
tab_pf, tab_hist, tab_saisie = st.tabs(["📊 Portefeuille", "📈 Historique", "➕ Saisie"])

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
        c2.metric("Plus-value globale", f"{fmt(s['pv_globale'])} €",
                  f"{fmt(s['perf_pct'], 2, True)} %")
        c3, c4 = st.columns(2)
        c3.metric("Apports nets", f"{fmt(s['apports'])} €")
        c4.metric("Cash disponible", f"{fmt(s['cash'])} €")
        st.progress(min(s["plafond_pct"] / 100, 1.0),
                    text=f"Plafond de versements : {fmt(s['versements_cumules'], 0)} / 150 000 € "
                         f"({fmt(s['plafond_pct'], 1)} %)")

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
            st.caption(f"Cours Yahoo différés · actualisés à {horodatage:%H:%M} (cache 5 min)")

            # -- Une carte par ligne (lisible sur téléphone) ---------------- #
            for r in pos.sort_values("valeur", ascending=False).itertuples():
                badge = "" if r.statut == "live" else f" ⚠️ {r.statut}"
                jour = pastille(r.var_jour_pct, f"{fmt(r.var_jour_pct, 2, True)} % auj.")
                total = pastille(r.perf_pct, f"{fmt(r.perf_pct, 1, True)} % total")
                with st.container(border=True):
                    g, d = st.columns([3, 2])
                    g.markdown(f"**{r.nom}**{badge}  \n{r.secteur} · {fmt(r.poids_pct, 0)} %")
                    d.markdown(f"<div style='text-align:right'><b>{fmt(r.valeur)} €</b><br>"
                               f"{jour}<br>{total}</div>", unsafe_allow_html=True)
                    with st.expander("Détails"):
                        f = fonds.get(r.ticker, {})
                        details = [
                            ("Quantité", f"{r.quantite:g}"),
                            ("PRM", f"{fmt(r.prm)} €"),
                            ("Cours", f"{fmt(r.prix_eff)} €"),
                            ("+/- value latente", f"{fmt(r.pv_latente, 2, True)} €"),
                            ("Dividendes perçus", f"{fmt(r.dividendes)} €"),
                            ("PER", fmt(f.get("per"), 1)),
                            ("Chiffre d'affaires", C.formater_gros_nombre(f.get("ca"))),
                            ("Capitalisation", C.formater_gros_nombre(f.get("capi"))),
                            ("ISIN · ticker", f"{r.isin} · {r.ticker}"),
                        ]
                        st.markdown("\n".join(f"- {k} : **{v}**" for k, v in details))

            # -- Graphiques ------------------------------------------------- #
            st.subheader("Répartition")
            fig = px.treemap(pos, path=[px.Constant("PEA"), "secteur", "nom"], values="valeur",
                             color="perf_pct", color_continuous_scale="RdYlGn",
                             color_continuous_midpoint=0)
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340, coloraxis_showscale=False)
            st.plotly_chart(fig, config=PLOTLY)

            st.subheader("Contribution à la performance (€)")
            contrib = pos.assign(contrib=pos["pv_latente"] + pos["dividendes"]).sort_values("contrib")
            fig = px.bar(contrib, x="contrib", y="nom", orientation="h", color="contrib",
                         color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                         labels={"contrib": "PV latente + dividendes (€)", "nom": ""})
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=max(220, 44 * len(contrib)),
                              coloraxis_showscale=False)
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
            st.plotly_chart(fig, config=PLOTLY)

            st.subheader("Performance vs indice")
            st.caption("Performance pondérée par le temps : neutralise vos versements, base 100.")
            choix = st.selectbox("Comparer à", list(BENCHMARKS), label_visibility="collapsed")
            twr = C.calcul_twr(sn)
            bench = None
            try:
                h = D.historique_cloture(BENCHMARKS[choix], sn["date"].min().strftime("%Y-%m-%d"))
                bench = h.reindex(h.index.union(twr["date"])).ffill().reindex(twr["date"]).bfill()
                bench = bench / bench.iloc[0] * 100
            except Exception:
                st.caption("Indice indisponible pour le moment.")
            fig = go.Figure()
            fig.add_scatter(x=twr["date"], y=twr["twr"], name="Mon PEA", mode="lines")
            if bench is not None:
                fig.add_scatter(x=twr["date"], y=bench.to_numpy(), name=choix, mode="lines")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300,
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, config=PLOTLY)
            resume = f"Mon PEA : **{fmt(twr['twr'].iloc[-1] - 100, 2, True)} %**"
            if bench is not None:
                resume += f" · {choix} : **{fmt(bench.iloc[-1] - 100, 2, True)} %**"
            st.markdown(resume)

with tab_saisie:
    onglet_saisie()
