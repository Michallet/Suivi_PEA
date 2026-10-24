"""Contexte envoyé au modèle : poids en % uniquement, jamais de montant en euros (sauf import par captures)."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from pea.domain.erreurs import ErreurIA
from pea.services.ia.prompts import VERSION_PROMPT


def _lignes_poids(pos: pd.DataFrame, cash: float, per_par_isin: dict):
    """Lignes de contexte (poids en % uniquement) + empreinte de composition."""
    total = (float(pos["valeur"].sum()) if not pos.empty else 0.0) + max(float(cash), 0.0)
    if total <= 0:
        raise ErreurIA("Portefeuille vide : rien à analyser.")
    lignes, cles = [], []
    for r in pos.sort_values("valeur", ascending=False).itertuples():
        poids = r.valeur / total * 100
        per = per_par_isin.get(r.isin)
        lignes.append(
            f"{len(lignes) + 1}. {r.nom} | ISIN {r.isin} | secteur : {r.secteur} | "
            f"poids : {poids:.1f} % | PER : {('%.1f' % per) if per else 'n/d'} | "
            f"performance latente : {r.perf_pct:+.1f} %")
        cles.append((r.isin, round(poids)))
    cash_pct = max(float(cash), 0.0) / total * 100
    return lignes, cles, cash_pct


def construire_contexte(pos: pd.DataFrame, cash: float, per_par_isin: dict, modele: str):
    """Retourne (texte du prompt, empreinte). Poids en % uniquement, aucun montant en euros."""
    lignes, cles, cash_pct = _lignes_poids(pos, cash, per_par_isin)
    texte = (
        "Portefeuille PEA d'un investisseur particulier français.\n"
        "Les poids sont en % de la valeur totale du PEA (cash inclus). Aucun montant en euros n'est communiqué.\n\n"
        f"Nombre de lignes : {len(lignes)}\nCash : {cash_pct:.1f} %\nLignes (poids décroissant) :\n"
        + "\n".join(lignes) + "\n\nÉvalue les 4 critères."
    )
    brut = json.dumps([VERSION_PROMPT, modele, sorted(cles), round(cash_pct)], sort_keys=True)
    return texte, hashlib.sha256(brut.encode()).hexdigest()[:16]


def construire_contexte_scenario(pos_p: pd.DataFrame, cash_p: float, per_p: dict,
                                 pos: pd.DataFrame, cash: float, per: dict, modele: str,
                                 scenario_id, operations: str, versement: float):
    """Retourne (texte du prompt, empreinte) : structure PROJETÉE à évaluer, ACTUELLE en référence.

    `operations` : résumé textuel des opérations fictives (jamais de montants en €).
    """
    lignes_p, cles_p, cash_p_pct = _lignes_poids(pos_p, cash_p, per_p)
    lignes_a, cles_a, cash_a_pct = _lignes_poids(pos, cash, per)
    texte = (
        "Portefeuille PEA d'un investisseur particulier français.\n"
        "Les poids sont en % de la valeur totale du PEA (cash inclus). Aucun montant en euros n'est communiqué.\n\n"
        "STRUCTURE ACTUELLE (référence) :\n"
        f"Cash : {cash_a_pct:.1f} %\nLignes (poids décroissant) :\n" + "\n".join(lignes_a) + "\n\n"
        "STRUCTURE PROJETÉE (scénario à évaluer) :\n"
        f"Cash : {cash_p_pct:.1f} %\nLignes (poids décroissant) :\n" + "\n".join(lignes_p) + "\n\n"
        f"Opérations fictives du scénario : {operations or 'aucune'}"
        + (f" ; versement fictif : {versement:.0f} €" if versement else "") + ".\n\n"
        "Évalue les 4 critères sur la structure PROJETÉE, puis donne pour chaque critère "
        "les avantages et les inconvénients du scénario par rapport à l'actuelle."
    )
    brut = json.dumps([VERSION_PROMPT, modele, "scenario", int(scenario_id), sorted(cles_p),
                       round(cash_p_pct), sorted(cles_a), round(cash_a_pct),
                       str(operations), round(float(versement or 0), 2)], sort_keys=True)
    return texte, hashlib.sha256(brut.encode()).hexdigest()[:16]
