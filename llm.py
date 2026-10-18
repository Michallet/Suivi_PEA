"""Analyse IA du portefeuille : un seul appel Gemini, réponse JSON toujours au même format.

Confidentialité : seuls des POIDS en % sont envoyés (jamais de montants en euros).
Sur le palier gratuit de l'API Gemini, Google peut réutiliser les contenus envoyés pour améliorer
ses produits (voir ai.google.dev/gemini-api/terms) : ne mettez pas de données plus sensibles ici.
"""
from __future__ import annotations

import hashlib
import json
import re

import pandas as pd
import requests

MODELE_DEFAUT = "gemini-3.6-flash"  # surchargeable via le secret GEMINI_MODEL (ex : gemini-3.8-flash)
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
VERSION_PROMPT = "v1"
MAX_APPELS_PAR_JOUR = 5
MAX_MOTS_SYNTHESE = 20  # filet de sécurité : le prompt demande ~10 mots

AVERTISSEMENT = ("Analyse générée par une IA à partir de la structure de votre PEA, à titre "
                 "informatif. Ce n'est pas un conseil en investissement.")

# (clé, libellé affiché, définition donnée au modèle) — modifiable librement
CRITERES = [
    ("diversification_sectorielle", "Diversification sectorielle",
     "Répartition entre secteurs économiques, en tenant compte de la composition sous-jacente "
     "des ETF. 10 = très bien diversifié, aucun secteur dominant."),
    ("capex", "CAPEX",
     "Exposition à l'intensité capitalistique : entreprises aux investissements lourds (énergie, "
     "industrie, semi-conducteurs, infrastructures, télécoms) face à des modèles peu capitalistiques. "
     "10 = équilibre sain et dépendance maîtrisée aux cycles d'investissement ; 0 = très dépendant."),
    ("geographique", "Diversification géographique",
     "Répartition par zone d'exposition économique (France, Europe, États-Unis, émergents...), "
     "y compris via les ETF. 10 = très bien diversifié."),
    ("croissance_rendement", "Croissance vs Rendement",
     "Équilibre entre actions de croissance (réinvestissement, valorisation élevée) et actions de "
     "rendement / valeur (dividendes, valorisation modérée). 10 = mix équilibré et cohérent."),
]
CLES = [c[0] for c in CRITERES]
LIBELLES = {c[0]: c[1] for c in CRITERES}

SYSTEME = (
    "Tu es un analyste qui évalue la STRUCTURE d'un PEA français (actions et ETF européens éligibles).\n"
    "Règles impératives :\n"
    "- Tu n'es pas conseiller financier : aucune recommandation d'achat, de vente ou d'arbitrage, "
    "aucune prévision de cours ni de rendement.\n"
    "- Appuie-toi sur la composition connue des ETF (d'après leur nom et leur ISIN). Si tu ne connais "
    "pas un instrument, signale-le dans la synthèse concernée au lieu d'inventer.\n"
    "- Note chaque critère de 0 à 10 : 10 = structure très saine et équilibrée sur ce critère, "
    "0 = très déséquilibrée.\n"
    "- Synthèse par critère : environ 10 mots (15 maximum), factuelle, en français.\n"
    "- Conclusion : une seule phrase de 25 mots maximum, sans recommandation.\n"
    "- Réponds uniquement par un objet JSON conforme au schéma demandé.\n\n"
    "Critères (clé : définition) :\n"
    + "\n".join(f"- {cle} : {definition}" for cle, _, definition in CRITERES)
)

SCHEMA_JSON = {
    "type": "object",
    "properties": {
        "criteres": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cle": {"type": "string", "enum": CLES},
                    "note": {"type": "integer"},
                    "synthese": {"type": "string"},
                },
                "required": ["cle", "note", "synthese"],
            },
        },
        "conclusion": {"type": "string"},
    },
    "required": ["criteres", "conclusion"],
}

# Exemple statique affiché en mode démo (aucun appel API)
EXEMPLE = {
    "criteres": [
        {"cle": "diversification_sectorielle", "label": "Diversification sectorielle", "note": 7,
         "synthese": "Bien réparti, léger poids du luxe et de l'industrie."},
        {"cle": "capex", "label": "CAPEX", "note": 6,
         "synthese": "Énergie et industrie capitalistiques compensées par santé et luxe."},
        {"cle": "geographique", "label": "Diversification géographique", "note": 8,
         "synthese": "ETF monde et émergents complètent un cœur européen."},
        {"cle": "croissance_rendement", "label": "Croissance vs Rendement", "note": 7,
         "synthese": "Mix équilibré entre dividendes réguliers et valeurs de croissance."},
    ],
    "conclusion": "Structure globalement équilibrée, sans ligne ou secteur écrasant le reste.",
    "modele": "exemple fictif",
}


class ErreurIA(Exception):
    """Erreur affichable telle quelle à l'utilisateur (ne contient jamais la clé API)."""


# --------------------------------------------------------------------------- #
# Contexte envoyé au modèle
# --------------------------------------------------------------------------- #
def construire_contexte(pos: pd.DataFrame, cash: float, per_par_isin: dict, modele: str):
    """Retourne (texte du prompt, empreinte). Poids en % uniquement, aucun montant en euros."""
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
    texte = (
        "Portefeuille PEA d'un investisseur particulier français.\n"
        "Les poids sont en % de la valeur totale du PEA (cash inclus). Aucun montant en euros n'est communiqué.\n\n"
        f"Nombre de lignes : {len(lignes)}\nCash : {cash_pct:.1f} %\nLignes (poids décroissant) :\n"
        + "\n".join(lignes) + "\n\nÉvalue les 4 critères."
    )
    brut = json.dumps([VERSION_PROMPT, modele, sorted(cles), round(cash_pct)], sort_keys=True)
    return texte, hashlib.sha256(brut.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Validation / normalisation de la réponse (le format de sortie est garanti ici)
# --------------------------------------------------------------------------- #
def _tronquer_mots(texte: str, n: int) -> str:
    mots = re.sub(r"\s+", " ", str(texte)).strip().split(" ")
    return " ".join(mots) if len(mots) <= n else " ".join(mots[:n]).rstrip(",;:") + "…"


def valider_resultat(obj) -> dict:
    """Exige les 4 critères exactement une fois ; borne les notes à 0-10 ; limite la longueur."""
    if not isinstance(obj, dict) or not isinstance(obj.get("criteres"), list):
        raise ErreurIA("Réponse de l'IA inattendue (structure).")
    par_cle = {}
    for c in obj["criteres"]:
        if isinstance(c, dict) and c.get("cle") in CLES and c["cle"] not in par_cle:
            try:
                note = int(round(float(c.get("note"))))
            except (TypeError, ValueError):
                raise ErreurIA("Réponse de l'IA inattendue (note invalide).")
            par_cle[c["cle"]] = {"cle": c["cle"], "label": LIBELLES[c["cle"]],
                                 "note": max(0, min(10, note)),
                                 "synthese": _tronquer_mots(c.get("synthese", ""), MAX_MOTS_SYNTHESE)}
    manquants = [k for k in CLES if k not in par_cle]
    if manquants:
        raise ErreurIA("Réponse de l'IA incomplète (critères manquants : " + ", ".join(manquants) + ").")
    return {"criteres": [par_cle[k] for k in CLES],
            "conclusion": _tronquer_mots(obj.get("conclusion", ""), 35)}


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


# --------------------------------------------------------------------------- #
# Appel HTTP
# --------------------------------------------------------------------------- #
def _en_majuscules(schema):
    """Schéma JSON -> variante « responseSchema » (types en majuscules)."""
    if isinstance(schema, dict):
        return {k: (v.upper() if k == "type" and isinstance(v, str) else _en_majuscules(v))
                for k, v in schema.items()}
    if isinstance(schema, list):
        return [_en_majuscules(x) for x in schema]
    return schema


def _payload(texte: str, variante: str) -> dict:
    config = {
        "responseMimeType": "application/json",
        # Pas de temperature/top_p/top_k : ignorés (puis refusés) par les modèles Gemini 3.x
        "thinkingConfig": {"thinkingLevel": "low"},
        "maxOutputTokens": 4096,  # la réflexion est comptée dans la sortie
    }
    if variante == "json_schema":
        config["responseJsonSchema"] = SCHEMA_JSON
    else:
        config["responseSchema"] = _en_majuscules(SCHEMA_JSON)
    return {"systemInstruction": {"parts": [{"text": SYSTEME}]},
            "contents": [{"role": "user", "parts": [{"text": texte}]}],
            "generationConfig": config}


def _post(payload: dict, cle: str, modele: str, timeout: int):
    try:
        return requests.post(URL.format(modele=modele), json=payload, timeout=timeout,
                             headers={"x-goog-api-key": cle, "Content-Type": "application/json"})
    except requests.Timeout:
        raise ErreurIA("Délai dépassé : Gemini n'a pas répondu à temps. Réessayez.")
    except requests.RequestException:
        raise ErreurIA("Connexion à Gemini impossible. Réessayez plus tard.")


def _message_erreur(r) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except Exception:
        return ""


def _generer(texte: str, cle: str, modele: str, timeout: int) -> str:
    r = _post(_payload(texte, "json_schema"), cle, modele, timeout)
    if r.status_code == 400 and "schema" in _message_erreur(r).lower():
        r = _post(_payload(texte, "response_schema"), cle, modele, timeout)  # variante OpenAPI
    if r.status_code in (401, 403):
        raise ErreurIA("Clé API Gemini refusée (vérifiez GEMINI_API_KEY).")
    if r.status_code == 404:
        raise ErreurIA(f"Modèle « {modele} » introuvable (vérifiez GEMINI_MODEL).")
    if r.status_code == 429:
        raise ErreurIA("Quota Gemini atteint. Réessayez plus tard.")
    if r.status_code >= 500:
        raise ErreurIA("Service Gemini momentanément indisponible. Réessayez.")
    if r.status_code != 200:
        raise ErreurIA(f"Requête refusée par Gemini ({r.status_code}) : {_message_erreur(r)}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ErreurIA("Gemini n'a renvoyé aucune réponse exploitable (contenu bloqué ou vide).")
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def analyser(texte: str, cle: str, modele: str | None = None, timeout: int = 90) -> dict:
    """Un appel (un seul nouvel essai si la réponse est invalide). Lève ErreurIA."""
    modele = modele or MODELE_DEFAUT
    derniere = None
    for _ in range(2):
        try:
            res = valider_resultat(_parser_json(_generer(texte, cle, modele, timeout)))
            res["modele"] = modele
            return res
        except ErreurIA as e:
            derniere = e
            if "refusée" in str(e) or "introuvable" in str(e) or "Quota" in str(e) or "Clé" in str(e):
                break  # inutile de réessayer
    raise derniere
