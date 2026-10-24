"""Validation et normalisation des réponses de l'IA : le format de sortie est garanti ici."""
from __future__ import annotations

import json
import re

from pea.domain.erreurs import ErreurIA
from pea.domain.textes import nettoyer_sortie_ia
from pea.services.ia.prompts import CLES, LIBELLES, POINTS_MAX_PAR_CRITERE

MAX_MOTS_SYNTHESE = 20  # filet de sécurité : le prompt demande ~10 mots
MAX_MOTS_POINT = 12  # filet de sécurité : le prompt demande ~10 mots par avantage/inconvénient


def _tronquer_mots(texte: str, n: int) -> str:
    mots = re.sub(r"\s+", " ", str(texte)).strip().split(" ")
    return " ".join(mots) if len(mots) <= n else " ".join(mots[:n]).rstrip(",;:") + "…"


def _points(liste) -> list:
    """Normalise une liste d'avantages/inconvénients : 2 max, ~12 mots chacun."""
    if not isinstance(liste, list):
        return []
    return [_tronquer_mots(nettoyer_sortie_ia(x), MAX_MOTS_POINT) for x in liste
            if str(x or "").strip()][:POINTS_MAX_PAR_CRITERE]


def valider_resultat(obj, comparer: bool = False) -> dict:
    """Exige les 4 critères exactement une fois ; borne les notes à 0-10 ; limite la longueur.

    Avec `comparer=True`, exige aussi avantages/inconvenients (analyse de scénario).
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("criteres"), list):
        raise ErreurIA("Réponse de l'IA inattendue (structure).")
    par_cle = {}
    for c in obj["criteres"]:
        if isinstance(c, dict) and c.get("cle") in CLES and c["cle"] not in par_cle:
            try:
                note = int(round(float(c.get("note"))))
            except (TypeError, ValueError):
                raise ErreurIA("Réponse de l'IA inattendue (note invalide).")
            critere = {"cle": c["cle"], "label": LIBELLES[c["cle"]],
                       "note": max(0, min(10, note)),
                       "synthese": _tronquer_mots(nettoyer_sortie_ia(c.get("synthese", "")), MAX_MOTS_SYNTHESE)}
            if comparer:
                critere["avantages"] = _points(c.get("avantages"))
                critere["inconvenients"] = _points(c.get("inconvenients"))
            par_cle[c["cle"]] = critere
    manquants = [k for k in CLES if k not in par_cle]
    if manquants:
        raise ErreurIA("Réponse de l'IA incomplète (critères manquants : " + ", ".join(manquants) + ").")
    return {"criteres": [par_cle[k] for k in CLES],
            "conclusion": _tronquer_mots(nettoyer_sortie_ia(obj.get("conclusion", "")), 35)}


def note_globale(res: dict) -> float:
    return sum(c["note"] for c in res["criteres"]) / len(res["criteres"])


def _parser_json(texte: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texte or "").strip(), flags=re.I)
    debut, fin = t.find("{"), t.rfind("}")
    if debut < 0 or fin < debut:
        raise ErreurIA("Réponse de l'IA illisible (pas de JSON).")
    try:
        return json.loads(t[debut:fin + 1])
    except json.JSONDecodeError:
        raise ErreurIA("Réponse de l'IA illisible (JSON invalide).")
