"""Saisie › Import par captures d'écran du courtier (Gemini vision) — compte démo exclu.

Captures -> relevé (Gemini) -> écarts avec la base -> opérations à valider -> insertion en une requête.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from pea import config
from pea.data import marche
from pea.data import repo
from pea.domain import calculs as C
from pea.domain import import_ecran as IE
from pea.domain.formats import fmt
from pea.domain.textes import echapper_markdown as esc
from pea.services import ia, quotas
from pea.services.portefeuille import Portefeuille
from pea.ui.composants.communs import creer_titre
from pea.ui.composants.ia import etat_ia, legende_ia
from pea.ui.etat import flash, k

SOURCES_ISIN = {"capture": "lu à l'écran", "nom": "reconnu dans votre base",
                "position": "même quantité et PRM qu'une ligne détenue",
                "ia": "⚠️ proposé par l'IA, à vérifier", None: "❓ introuvable"}
CLE_IMPORT, CLE_CHARGEUR = k("imp", "releve"), k("imp", "chargeur")
PREFIXE_CARTES = k("imp", "f")
TXT_CONFIDENTIALITE = ("🔐 Les images sont envoyées telles quelles à Gemini : quantités et montants y sont "
                       "lisibles (contrairement à l'analyse IA). Cadrez sans nom ni numéro de compte. "
                       "Sur le palier gratuit, Google peut réutiliser les contenus envoyés. "
                       "Les images ne sont pas conservées.")


def _oublier_import() -> None:
    for cle in [c for c in st.session_state if c == CLE_IMPORT or str(c).startswith(PREFIXE_CARTES)]:
        del st.session_state[cle]


def _images(files) -> list | None:
    images = []
    for f in files:
        octets = f.getvalue()
        mime = IE.type_image_reel(octets)  # on ne se fie pas au type annoncé par le navigateur
        if mime is None:
            st.error(f"« {f.name} » n'est pas une image PNG, JPEG ou WebP valide.")
            return None
        images.append((octets, mime))
    return images


def _lire_captures(pf: Portefeuille, files, cle_api: str, modele: str) -> None:
    """Gemini lit les images, puis la différence avec la base est calculée (rien n'est écrit)."""
    if pf.demo:  # défense en profondeur : l'UI désactive déjà le bouton (et quotas.verifier refuse)
        return
    images = _images(files)
    if images is None:
        return
    try:
        quotas.verifier("capture")
        with st.spinner("Lecture des captures par Gemini…"):
            brut = ia.extraire_capture(images, cle_api, modele)
    except (ia.ErreurIA, quotas.QuotaDepasse) as e:
        st.error(str(e))
        return
    quotas.enregistrer("capture")
    lignes, avert = IE.normaliser_releve(brut)
    if not lignes:
        st.error("Aucune ligne de portefeuille lisible sur ces captures.")
        for a in avert:
            st.caption(a)
        return
    tmap = pf.tmap
    noms = {i: n for i, n in tmap["nom"].items() if isinstance(n, str)} if not tmap.empty else {}
    cours = {i: float(p) for i, p in tmap["dernier_prix"].dropna().items()} if not tmap.empty else {}
    cours.update({r.isin: float(r.prix) for r in pf.cours.itertuples() if pd.notna(r.prix)})
    releve = IE.resoudre_isins(lignes, noms, pf.positions)
    ops = IE.proposer_operations(releve, pf.positions, cours, config.maintenant().date())
    ver = st.session_state.get(CLE_IMPORT, {}).get("ver", 0) + 1
    st.session_state[CLE_IMPORT] = {"releve": releve, "ops": ops, "avert": avert, "ver": ver,
                                    "n_trans": len(pf.trans)}
    st.session_state[CLE_CHARGEUR] = st.session_state.get(CLE_CHARGEUR, 0) + 1  # vide le chargeur d'images
    st.rerun()


def _carte_operation(i: int, ver: int, r) -> dict:
    """Une opération proposée = une carte modifiable (mobile-first). Retourne les valeurs saisies."""
    cle = f"{PREFIXE_CARTES}{ver}_{i}"
    with st.container(border=True):
        valider = st.checkbox(f"**{r.type}** · {r.nom}", value=bool(r.valider), key=cle + "v")
        c1, c2, c3 = st.columns(3)
        q = c1.number_input("Quantité", min_value=0.0, value=float(r.quantite), step=1.0, format="%.4f", key=cle + "q")
        p = c2.number_input("Prix (€)", min_value=0.0, value=float(r.prix), step=0.1, format="%.4f", key=cle + "p")
        fr = c3.number_input("Frais (€)", min_value=0.0, value=float(r.frais), step=0.1, format="%.2f", key=cle + "f")
        d = st.date_input("Date", r.date, format="DD/MM/YYYY", key=cle + "d")
        isin = st.text_input("ISIN", value=r.isin, key=cle + "i")
        if r.note:
            st.caption(r.note)
    return {"valider": valider, "date": d, "isin": isin.strip().upper(), "nom": r.nom, "type": r.type,
            "quantite": q, "prix": p, "frais": fr, "note": r.note}


def _chargement(pf: Portefeuille) -> None:
    if pf.demo:
        st.file_uploader("Captures", disabled=True, key=k("imp", "demo_up"))
        st.button("🔍 Lire les captures", disabled=True, key=k("imp", "demo_btn"))
        st.caption("Indisponible en mode démo (utilise l'API Gemini).")
        return
    cle_api, modele, limite = etat_ia("capture")
    files = st.file_uploader(f"Captures (PNG/JPEG, {ia.MAX_CAPTURES} max)", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True, key=k("imp", "up", st.session_state.get(CLE_CHARGEUR, 0)))
    legende_ia("capture", cle_api, limite, "l'import", TXT_CONFIDENTIALITE)
    if st.button("🔍 Lire les captures", key=k("imp", "lire"), disabled=(not cle_api) or limite or not files):
        if len(files) > ia.MAX_CAPTURES:
            st.error(f"Maximum {ia.MAX_CAPTURES} captures par import.")
        else:
            _lire_captures(pf, files, cle_api, modele)


def _afficher_releve(imp: dict) -> None:
    for a in imp["avert"]:
        st.caption("• " + a)
    with st.expander(f"📋 {len(imp['releve'])} ligne(s) lue(s) chez le courtier"):
        for l in imp["releve"]:
            st.markdown(f"- **{esc(l['nom'])}** : {l['quantite']:g} @ {fmt(l['prm'], 4)} € · "
                        f"{l['isin'] or '?'} ({SOURCES_ISIN[l['source_isin']]})")
    if imp["ops"].empty:
        st.success("✅ Les quantités de votre suivi correspondent déjà aux captures.")
    else:
        st.markdown(f"#### {len(imp['ops'])} opération(s) proposée(s)")
        st.caption("Cochez, corrigez ou complétez (prix, date, frais, ISIN), puis enregistrez. "
                   "Le prix d'un achat est déduit du PRM du courtier ; celui d'une vente est le cours "
                   "actuel par défaut.")


def _controler(releve, apres: pd.DataFrame) -> None:
    ecarts = IE.ecarts_apres(releve, apres)
    if ecarts.empty:
        st.success("✅ Après ces opérations, quantités et PRM correspondent aux captures.")
        return
    st.warning("Écarts restants avec les captures après ces opérations :")
    for r in ecarts.itertuples():
        prm = ("" if pd.isna(r.prm_courtier) or pd.isna(r.prm_base) else
               f" · PRM {fmt(r.prm_base, 4)} (suivi) / {fmt(r.prm_courtier, 4)} (courtier)")
        st.markdown(f"- **{esc(r.nom)}** : quantité {r.qte_base:g} (suivi) / {r.qte_courtier:g} (courtier){prm}")


def _enregistrer(pf: Portefeuille, nouvelles: pd.DataFrame) -> None:
    if nouvelles.empty:
        st.info("Aucune opération cochée.")
        return
    for isin in nouvelles["isin"].unique():  # tickers résolus AVANT toute écriture
        if isin in pf.tmap.index:
            continue
        trouve = marche.chercher_ticker(isin)
        if not trouve:
            st.error(f"Ticker introuvable pour {isin} : ajoutez-le via Saisie › Transaction, puis relancez l'import.")
            return
        err = creer_titre(pf, isin, trouve["ticker"], trouve.get("nom"), suggerer=False)
        if err:
            st.error(err)
            return
    repo.inserer_lot("transactions", [r._asdict() for r in nouvelles.itertuples(index=False)])  # une requête
    _oublier_import()
    flash(f"{len(nouvelles)} transaction(s) enregistrée(s) ✅")
    st.rerun()


def afficher(pf: Portefeuille) -> None:
    st.caption("Chargez une ou plusieurs captures de votre portefeuille chez le courtier : "
               "l'app propose les achats / ventes qui alignent votre suivi sur la réalité. "
               "Rien n'est enregistré avant votre validation.")
    _chargement(pf)
    imp = None if pf.demo else st.session_state.get(CLE_IMPORT)
    if not imp:
        return
    if imp["n_trans"] != len(pf.trans):
        _oublier_import()
        st.warning("Le journal a changé depuis la lecture : relancez la lecture des captures.")
        return
    _afficher_releve(imp)
    with st.form(k("f_imp", imp["ver"])):
        saisies = [_carte_operation(i, imp["ver"], r) for i, r in enumerate(imp["ops"].itertuples())]
        c1, c2 = st.columns(2)
        controler = c1.form_submit_button("🔎 Contrôler")
        enregistrer = c2.form_submit_button("✅ Enregistrer", type="primary")
    if st.button("✖ Annuler l'import", key=k("imp", "annuler")):
        _oublier_import()
        st.rerun()
    if not (controler or enregistrer):
        return
    nouvelles, erreurs = IE.preparer_insertions(pd.DataFrame(saisies, columns=IE.COLS_OPERATIONS))
    if erreurs:
        for e in erreurs:
            st.error(e)
        return
    try:
        apres, _ = C.calcul_positions(pd.concat([pf.trans, nouvelles], ignore_index=True))
    except ValueError as e:
        st.error(str(e))
        return
    if controler:
        _controler(imp["releve"], apres)
    else:
        _enregistrer(pf, nouvelles)
