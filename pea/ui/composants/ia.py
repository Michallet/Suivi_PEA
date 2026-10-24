"""Blocs IA communs au portefeuille et aux scénarios : un seul bloc d'analyse, un seul chat, un seul
calcul de quota (`etat_ia`) et une seule légende (`legende_ia`)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from pea import config
from pea.data import repo
from pea.domain.formats import fmt, formater_gros_nombre
from pea.domain.textes import echapper_markdown as esc
from pea.domain.textes import nettoyer_sortie_ia
from pea.services import ia, quotas
from pea.services.portefeuille import Portefeuille
from pea.ui.etat import flash, k, relancer_zone

TXT_POIDS_SEULEMENT = "Envoie à Gemini uniquement les poids en % (aucun montant en €)."


def etat_ia(nature: str) -> tuple[str | None, str, bool]:
    """(clé API, modèle, limite atteinte) : calcul unique pour tous les blocs IA."""
    cle_api = config.cle_gemini()
    return cle_api, config.modele_gemini(), bool(cle_api) and quotas.limite_atteinte(nature)


def legende_ia(nature: str, cle_api, limite: bool, usage: str, texte_ok: str | None = None) -> None:
    if not cle_api:
        st.caption(f"Ajoutez `GEMINI_API_KEY` dans les secrets pour activer {usage}.")
    elif limite:
        st.caption(quotas.message_limite(nature))
    elif texte_ok:
        st.caption(texte_ok)


# --------------------------------------------------------------------------------------------------
# Analyse (portefeuille ou scénario)
# --------------------------------------------------------------------------------------------------
@dataclass
class Cible:
    """Ce qui est analysé : le portefeuille actuel ou un scénario."""
    titre: str
    libelle: str
    cle: str
    exemple: dict
    legende_demo: str
    pos: pd.DataFrame
    contexte: callable           # modele -> (texte, empreinte)
    derniere: object             # dernière analyse enregistrée (Series) ou None
    table: str
    extra: dict
    message: str
    scenario: bool = False


def cible_portefeuille(pf: Portefeuille) -> Cible:
    return Cible(
        titre="#### ✨ Analyse IA", libelle="✨ Analyser mon portefeuille", cle=k("ia", "btn"),
        exemple=ia.EXEMPLE, legende_demo="Exemple fictif : aucun appel IA en mode démo. Passez sur un compte "
                                         "personnel pour analyser votre portefeuille.",
        pos=pf.pos, contexte=lambda m: ia.construire_contexte(pf.pos, pf.cash, pf.per_par_isin(), m),
        derniere=pf.derniere_analyse(), table="analyses_ia", extra={}, message="Analyse enregistrée ✨")


def cible_scenario(pf: Portefeuille, sid: int, pos_p: pd.DataFrame, cash_p: float, operations: str,
                   versement: float) -> Cible:
    return Cible(
        titre="#### ✨ Analyse IA du scénario", libelle="✨ Analyser ce scénario", cle=k("ias", "btn", sid),
        exemple=ia.EXEMPLE_SCENARIO, legende_demo="Exemple fictif (aucun appel IA en mode démo).",
        pos=pos_p, contexte=lambda m: contexte_scenario(pf, sid, pos_p, cash_p, operations, versement, m),
        derniere=pf.derniere_analyse(sid), table="analyses_scen", extra={"scenario_id": sid},
        message="Analyse du scénario enregistrée ✨", scenario=True)


def contexte_scenario(pf: Portefeuille, sid, pos_p, cash_p, operations, versement, modele):
    return ia.construire_contexte_scenario(pos_p, cash_p, pf.per_par_isin(pos_p), pf.pos, pf.cash,
                                           pf.per_par_isin(), modele, sid, operations, versement)


def afficher_analyse(res: dict, quand, perime: bool, scenario: bool = False) -> None:
    c1, c2 = st.columns([1, 2])
    c1.metric("Note globale", f"{ia.note_globale(res):.1f}/10")
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
    st.caption(ia.AVERTISSEMENT)


def bloc_analyse(pf: Portefeuille, cible: Cible, cadre: bool = True) -> None:
    with st.container(border=cadre):
        st.markdown(cible.titre)
        if pf.demo:
            st.button(cible.libelle, disabled=True, key=cible.cle + ".demo")
            st.caption(cible.legende_demo)
            afficher_analyse(cible.exemple, config.maintenant(), False, scenario=cible.scenario)
            return
        if cible.pos.empty:
            st.caption("Aucune ligne à analyser.")
            return
        cle_api, modele, limite = etat_ia("analyse")  # quota commun : portefeuille + scénarios
        texte, empreinte = cible.contexte(modele)
        a_jour = cible.derniere is not None and cible.derniere["empreinte"] == empreinte
        clic = st.button("✨ Relancer l'analyse" if a_jour else cible.libelle, key=cible.cle,
                         disabled=(not cle_api) or limite)
        legende_ia("analyse", cle_api, limite, "l'analyse", TXT_POIDS_SEULEMENT)
        if clic:
            try:
                quotas.verifier("analyse")
                with st.spinner("Analyse en cours…"):
                    res = ia.analyser(texte, cle_api, modele, scenario=True) if cible.scenario \
                        else ia.analyser(texte, cle_api, modele)
            except (ia.ErreurIA, quotas.QuotaDepasse) as e:
                st.error(str(e))
            else:
                quotas.enregistrer("analyse")
                repo.inserer(cible.table, {**cible.extra, "modele": modele, "empreinte": empreinte, "resultat": res})
                flash(cible.message)
                st.rerun()
        if cible.derniere is not None:
            quand = pd.to_datetime(cible.derniere["cree_le"], utc=True).tz_convert(config.PARIS)
            afficher_analyse(cible.derniere["resultat"], quand, not a_jour, scenario=cible.scenario)


# --------------------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------------------
def _fondamentaux_texte(pf: Portefeuille, p: pd.DataFrame) -> str:
    """Une ligne de fondamentaux par ligne détenue (données Yahoo, indicatives)."""
    lignes = ["Fondamentaux des lignes détenues (Yahoo, indicatifs) :"]
    for r in p.sort_values("valeur", ascending=False).itertuples():
        f = pf.fondamentaux(r.ticker)
        lignes.append(f"- {r.nom} | {r.secteur} | poids {r.poids_pct:.1f} % des titres | "
                      f"PER {fmt(f.get('per'), 1)} | cap. {formater_gros_nombre(f.get('capi'))} | "
                      f"CA {formater_gros_nombre(f.get('ca'))} | dividendes perçus {fmt(r.dividendes)} €")
    return "\n".join(lignes)


def _resume_analyse(derniere, intro: str) -> str | None:
    if derniere is None:
        return None
    notes = " ; ".join(f"{c['label']} {c['note']}/10" for c in derniere["resultat"]["criteres"])
    return f"{intro} : {notes}. Conclusion : {derniere['resultat']['conclusion']}"


def contexte_chat(pf: Portefeuille, modele: str, scenario: dict | None = None) -> str:
    """Contexte injecté dans chaque message du chat : structure (poids en %, jamais de € de position),
    dernière analyse IA et fondamentaux. En mode scénario, on parle du portefeuille PROJETÉ."""
    if scenario:
        sid = scenario["sid"]
        texte, _ = contexte_scenario(pf, sid, scenario["pos_p"], scenario["cash_p"], scenario["operations"],
                                     scenario["versement"], modele)
        parties = [f"Tu discutes du scénario « {pf.nom_scenario(sid)} » (SIMULATION de répartition), pas du "
                   "portefeuille actuel : précise-le si une question est ambiguë.", texte,
                   _resume_analyse(pf.derniere_analyse(sid), "Dernière analyse IA de ce scénario"),
                   _fondamentaux_texte(pf, scenario["pos_p"])]
    else:
        texte, _ = ia.construire_contexte(pf.pos, pf.cash, pf.per_par_isin(), modele)
        parties = [texte, _resume_analyse(pf.derniere_analyse(), "Dernière analyse IA de la structure"),
                   _fondamentaux_texte(pf, pf.pos)]
    return "\n\n".join(p for p in parties if p)


def bloc_chat(pf: Portefeuille, scenario: dict | None = None, cadre: bool = True) -> None:
    """Chatbot : discussion libre sur le portefeuille actuel ou sur un scénario projeté (une conversation
    par scénario). `scenario` : {sid, pos_p, cash_p, operations, versement}."""
    cle = k("chat", "scen", scenario["sid"]) if scenario else k("chat", "pf")
    titre = "#### 💬 Discuter de ce scénario" if scenario else "#### 💬 Discuter de mon portefeuille"
    with st.container(border=cadre):
        st.markdown(titre)
        if pf.demo:
            st.caption("Chat IA désactivé sur le compte démo pour éviter toute consommation de tokens.")
            return
        if pf.pos.empty:
            st.caption("Aucune ligne dans le portefeuille.")
            return
        cle_api, modele, limite = etat_ia("chat")
        if not cle_api:
            legende_ia("chat", cle_api, limite, "le chat")
            return
        messages = st.session_state.setdefault(cle, [])
        for m in messages:
            with st.chat_message(m["role"]):
                st.markdown(nettoyer_sortie_ia(m["content"]) if m["role"] == "model" else esc(m["content"]))
        if messages and st.button("🧹 Effacer la conversation", key=cle + ".reset"):
            st.session_state[cle] = []
            relancer_zone()
        if limite:
            legende_ia("chat", cle_api, limite, "le chat")
            return
        question = (st.chat_input("Posez une question…", key=cle + ".in") or "").strip()
        if not question:
            return
        try:
            quotas.verifier("chat")
            with st.spinner("Réponse en cours…"):
                rep = ia.discuter(contexte_chat(pf, modele, scenario), messages, question, cle_api, modele)
        except (ia.ErreurIA, quotas.QuotaDepasse) as e:
            st.error(str(e))
        else:
            quotas.enregistrer("chat")
            st.session_state[cle] = (messages + [{"role": "user", "content": question},
                                                 {"role": "model", "content": rep}])[-12:]
            relancer_zone()
