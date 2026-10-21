"""Analyse IA du portefeuille : un seul appel Gemini, réponse JSON toujours au même format.

Confidentialité : l'analyse et le chat n'envoient que des POIDS en % (jamais de montants en euros).
EXCEPTION : l'import par captures d'écran (`extraire_capture`) envoie les IMAGES telles que
l'utilisateur les charge, donc quantités et montants visibles à l'écran.
Sur le palier gratuit de l'API Gemini, Google peut réutiliser les contenus envoyés pour améliorer
ses produits (voir ai.google.dev/gemini-api/terms) : ne mettez pas de données plus sensibles ici.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re

import pandas as pd
import requests

MODELE_DEFAUT = "gemini-3.6-flash"  # surchargeable via le secret GEMINI_MODEL (ex : gemini-3.8-flash)
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
VERSION_PROMPT = "v1"
MAX_APPELS_PAR_JOUR = 200
MAX_CHAT_PAR_JOUR = 50
MAX_TOURS_CHAT = 10          # filet de sécurité : le prompt demande des réponses courtes
MAX_TOKENS_CHAT = 2048
MAX_MOTS_REPONSE = 300  # filet de sécurité : le prompt demande quelques phrases

# Prompts éditables dans prompts.md (dépôt Git) : sections « ## analyse », « ## scenario », « ## chat ».
# Sections absentes (ou fichier manquant) = valeurs par défaut définies ci-dessous dans le code.
PROMPTS_FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.md")


def charger_prompts_md(fichier: str = PROMPTS_FICHIER) -> dict:
    """Retourne {nom_de_section: texte} lu dans prompts.md. Fichier absent = aucune surcharge."""
    try:
        texte = open(fichier, encoding="utf-8").read()
    except OSError:
        return {}
    sections = {}
    for m in re.finditer(r"^##\s+([a-z0-9_-]+)\s*$([\s\S]*?)(?=^##\s|\Z)", texte, flags=re.M | re.I):
        sections[m.group(1).lower()] = m.group(2).strip()
    return sections


PROMPTS_MD = charger_prompts_md()
MAX_MOTS_SYNTHESE = 20  # filet de sécurité : le prompt demande ~10 mots
POINTS_MAX_PAR_CRITERE = 2
MAX_MOTS_POINT = 12  # filet de sécurité : le prompt demande ~10 mots par avantage/inconvénient

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

SYSTEME_DEFAUT = (
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

# Surcharge éventuelle par prompts.md (l'utilisateur édite le ton sans toucher au code)
SYSTEME = PROMPTS_MD.get("analyse", SYSTEME_DEFAUT)

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

# Variante « scénario » : mêmes critères + avantages/inconvénients par rapport au portefeuille actuel
SYSTEME_SCENARIO_DEFAUT = (
    SYSTEME + "\n\n"
    "Cas particulier : tu reçois DEUX structures, l'ACTUELLE (référence) et la PROJETÉE (scénario). "
    "Tu évalues les 4 critères sur la structure PROJETÉE.\n"
    "- Pour chaque critère, compare le projeté à l'actuel : liste au maximum "
    f"{POINTS_MAX_PAR_CRITERE} avantages et {POINTS_MAX_PAR_CRITERE} inconvénients du scénario, "
    "chacun en environ 10 mots, factuel, sans recommandation d'achat, de vente ou d'arbitrage.\n"
    "- Si le scénario ne change rien sur un critère, écris « Aucun changement » au lieu d'inventer.\n"
    "- Réponds uniquement par un objet JSON conforme au schéma demandé."
)
SYSTEME_SCENARIO = PROMPTS_MD.get("scenario", SYSTEME_SCENARIO_DEFAUT)

SCHEMA_JSON_SCENARIO = {
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
                    "avantages": {"type": "array", "items": {"type": "string"}},
                    "inconvenients": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["cle", "note", "synthese", "avantages", "inconvenients"],
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

# Exemple statique de l'analyse comparative (onglet Projet, mode démo)
EXEMPLE_SCENARIO = {
    "criteres": [
        {"cle": "diversification_sectorielle", "label": "Diversification sectorielle", "note": 8,
         "synthese": "La santé renforcée réduit la domination du luxe.",
         "avantages": ["Poids du luxe ramené sous les 20 %", "Santé défensive désormais 2e ligne"],
         "inconvenients": ["Exposition industrielle toujours élevée"]},
        {"cle": "capex", "label": "CAPEX", "note": 6,
         "synthese": "Peu de changement : énergie et industrie toujours présentes.",
         "avantages": ["Recul relatif de l'énergie dans le total"],
         "inconvenients": ["Semi-conducteurs toujours en poids fort"]},
        {"cle": "geographique", "label": "Diversification géographique", "note": 8,
         "synthese": "Inchangée : cœur européen complété par les ETF monde.",
         "avantages": ["Aucun changement"],
         "inconvenients": ["Aucun changement"]},
        {"cle": "croissance_rendement", "label": "Croissance vs Rendement", "note": 7,
         "synthese": "Léger basculement vers le rendement (santé, dividendes).",
         "avantages": ["Rendement du portefeuille un peu plus régulier"],
         "inconvenients": ["Moins d'exposition aux valeurs de croissance"]},
    ],
    "conclusion": "Scénario prudent : diversifie sans bouleverser la structure actuelle.",
    "modele": "exemple fictif",
}


class ErreurIA(Exception):
    """Erreur affichable telle quelle à l'utilisateur (ne contient jamais la clé API)."""


# --------------------------------------------------------------------------- #
# Contexte envoyé au modèle
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Validation / normalisation de la réponse (le format de sortie est garanti ici)
# --------------------------------------------------------------------------- #
def _tronquer_mots(texte: str, n: int) -> str:
    mots = re.sub(r"\s+", " ", str(texte)).strip().split(" ")
    return " ".join(mots) if len(mots) <= n else " ".join(mots[:n]).rstrip(",;:") + "…"


def _points(liste) -> list:
    """Normalise une liste d'avantages/inconvénients : 2 max, ~12 mots chacun."""
    if not isinstance(liste, list):
        return []
    return [_tronquer_mots(x, MAX_MOTS_POINT) for x in liste
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
                       "synthese": _tronquer_mots(c.get("synthese", ""), MAX_MOTS_SYNTHESE)}
            if comparer:
                critere["avantages"] = _points(c.get("avantages"))
                critere["inconvenients"] = _points(c.get("inconvenients"))
            par_cle[c["cle"]] = critere
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


def _payload(texte: str, variante: str, schema: dict) -> dict:
    config = {
        "responseMimeType": "application/json",
        # Pas de temperature/top_p/top_k : ignorés (puis refusés) par les modèles Gemini 3.x
        "thinkingConfig": {"thinkingLevel": "low"},
        "maxOutputTokens": 4096,  # la réflexion est comptée dans la sortie
    }
    if variante == "json_schema":
        config["responseJsonSchema"] = schema
    else:
        config["responseSchema"] = _en_majuscules(schema)
    systeme = SYSTEME_SCENARIO if schema is SCHEMA_JSON_SCENARIO else SYSTEME
    return {"systemInstruction": {"parts": [{"text": systeme}]},
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


def _generer(texte: str, cle: str, modele: str, timeout: int,
             schema: dict = SCHEMA_JSON) -> str:
    r = _post(_payload(texte, "json_schema", schema), cle, modele, timeout)
    if r.status_code == 400 and "schema" in _message_erreur(r).lower():
        r = _post(_payload(texte, "response_schema", schema), cle, modele, timeout)  # variante OpenAPI
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


def analyser(texte: str, cle: str, modele: str | None = None, timeout: int = 90,
             scenario: bool = False) -> dict:
    """Un appel (un seul nouvel essai si la réponse est invalide). Lève ErreurIA.

    Avec `scenario=True` : schéma étendu (avantages/inconvénients) et prompt comparatif.
    """
    modele = modele or MODELE_DEFAUT
    schema = SCHEMA_JSON_SCENARIO if scenario else SCHEMA_JSON
    derniere = None
    for _ in range(2):
        try:
            res = valider_resultat(_parser_json(_generer(texte, cle, modele, timeout, schema)),
                                   comparer=scenario)
            res["modele"] = modele
            return res
        except ErreurIA as e:
            derniere = e
            if "refusée" in str(e) or "introuvable" in str(e) or "Quota" in str(e) or "Clé" in str(e):
                break  # inutile de réessayer
    raise derniere


# --------------------------------------------------------------------------- #
# Import par captures d'écran du courtier (vision)
# --------------------------------------------------------------------------- #
MAX_CAPTURES = 8                       # images par import
MAX_OCTETS_CAPTURES = 15 * 1024 * 1024  # total (limite de requête Gemini : 20 Mo)
MAX_IMPORTS_PAR_JOUR = 10              # filet de sécurité (compté dans la session, voir app.py)
TYPES_IMAGE = ("image/png", "image/jpeg", "image/webp")

SYSTEME_CAPTURE_DEFAUT = (
    "Tu lis des captures d'écran de l'application d'un courtier et tu en extrais la liste des "
    "lignes d'un portefeuille PEA (actions et ETF). Tu ne fais aucune analyse.\n"
    "Règles impératives :\n"
    "- Une entrée par ligne du portefeuille, avec exactement ce qui est affiché. N'invente aucune "
    "ligne, ne complète pas une ligne coupée ou illisible : omets-la.\n"
    "- nom : le nom tel qu'affiché (garde les « … » ou « ... » d'un nom tronqué). N'inclus pas "
    "l'étiquette de type (« Action », « ETF »).\n"
    "- quantite : le nombre de titres détenus. prm : le prix de revient moyen par titre (PRM, PRU, "
    "prix d'achat moyen), en euros. Sur ce courtier, une ligne « 3 @ 21.190 » veut dire quantité 3 "
    "et PRM 21,19.\n"
    "- valeur : la valorisation totale de la ligne en euros si elle est affichée (le montant "
    "principal à droite du nom), sinon 0. Ignore les variations (+/-, %).\n"
    "- isin_capture : l'ISIN SEULEMENT s'il est écrit à l'écran, sinon chaîne vide. "
    "isin_ia : l'ISIN de l'instrument d'après ta connaissance, uniquement si tu en es certain, "
    "sinon chaîne vide. Ne devine jamais.\n"
    "- Nombres au format décimal avec un point (1859.86), sans espace ni symbole.\n"
    "- Ignore le solde total, les noms, numéros de compte et toute information personnelle.\n"
    "- Plusieurs captures peuvent se chevaucher : une ligne visible deux fois ne figure qu'une fois.\n"
    "- Réponds uniquement par un objet JSON conforme au schéma demandé."
)
SYSTEME_CAPTURE = PROMPTS_MD.get("capture", SYSTEME_CAPTURE_DEFAUT)

SCHEMA_JSON_CAPTURE = {
    "type": "object",
    "properties": {
        "lignes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "isin_capture": {"type": "string"},
                    "isin_ia": {"type": "string"},
                    "quantite": {"type": "number"},
                    "prm": {"type": "number"},
                    "valeur": {"type": "number"},
                },
                "required": ["nom", "isin_capture", "isin_ia", "quantite", "prm", "valeur"],
            },
        },
    },
    "required": ["lignes"],
}


def _texte_reponse(r, modele: str) -> str:
    """Statut HTTP -> ErreurIA lisible ; sinon texte de la réponse (hors « pensées »)."""
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


def _payload_capture(images: list, variante: str) -> dict:
    parts = [{"text": f"{len(images)} capture(s) d'écran du portefeuille. Extrais les lignes."}]
    parts += [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}
              for data, mime in images]
    config = {"responseMimeType": "application/json",
              "thinkingConfig": {"thinkingLevel": "low"},
              "maxOutputTokens": 8192}
    if variante == "json_schema":
        config["responseJsonSchema"] = SCHEMA_JSON_CAPTURE
    else:
        config["responseSchema"] = _en_majuscules(SCHEMA_JSON_CAPTURE)
    return {"systemInstruction": {"parts": [{"text": SYSTEME_CAPTURE}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": config}


def extraire_capture(images: list, cle: str, modele: str | None = None, timeout: int = 120) -> dict:
    """Envoie les captures à Gemini et retourne le JSON brut {"lignes": [...]} (à nettoyer avec
    `import_ecran.normaliser_releve`). `images` : liste de (octets, type MIME). Lève ErreurIA.
    """
    modele = modele or MODELE_DEFAUT
    if not images:
        raise ErreurIA("Aucune capture à analyser.")
    if len(images) > MAX_CAPTURES:
        raise ErreurIA(f"Maximum {MAX_CAPTURES} captures par import.")
    if any(mime not in TYPES_IMAGE for _, mime in images):
        raise ErreurIA("Format d'image non pris en charge (PNG, JPEG ou WebP).")
    if sum(len(d) for d, _ in images) > MAX_OCTETS_CAPTURES:
        raise ErreurIA("Images trop volumineuses (15 Mo maximum au total).")
    derniere = None
    for _ in range(2):
        try:
            r = _post(_payload_capture(images, "json_schema"), cle, modele, timeout)
            if r.status_code == 400 and "schema" in _message_erreur(r).lower():
                r = _post(_payload_capture(images, "response_schema"), cle, modele, timeout)
            obj = _parser_json(_texte_reponse(r, modele))
            if not isinstance(obj, dict) or not isinstance(obj.get("lignes"), list):
                raise ErreurIA("Réponse de l'IA inattendue (structure).")
            return obj
        except ErreurIA as e:
            derniere = e
            if any(m in str(e) for m in ("refusée", "introuvable", "Quota", "Clé", "Maximum")):
                break  # inutile de réessayer
    raise derniere


# --------------------------------------------------------------------------- #
# Chatbot : conversation libre avec le contexte du portefeuille en mémoire
# --------------------------------------------------------------------------- #
SYSTEME_CHAT_DEFAUT = (
    "Tu es un analyste qui discute avec un investisseur particulier français de son PEA "
    "(actions et ETF européens éligibles). La structure de son portefeuille (poids en %) et "
    "les analyses déjà réalisées te sont communiquées ci-dessous.\n"
    "Règles :\n"
    "- Donne ton avis factuel : désigne les forces, les faiblesses et les lignes ou secteurs à "
    "surveiller ; compare des options entre elles. Si quelque chose te semble déséquilibré, "
    "dis-le franchement plutôt que de rester neutre.\n"
    "- Reste dans la limite de l'analyse de structure : pas d'ordre d'achat ou de vente, pas de "
    "prévision de cours ni de rendement chiffré, pas de promesse de gain. Formule en point de "
    "vigilance plutôt qu'en recommandation, et assume tes préférences quand tu les exprimes.\n"
    "- Pas de conseil fiscal.\n"
    "- Ne t'appuie que sur les informations de cette conversation : si une information te manque, "
    "dis-le au lieu d'inventer.\n"
    "- Réponds en français, en quelques phrases concises et directes. Pas de langue de bois.\n\n"
    "Confidentialité : tu ne reçois que des poids en % (aucun montant en euros)."
)
SYSTEME_CHAT = PROMPTS_MD.get("chat", SYSTEME_CHAT_DEFAUT)


def discuter(contexte: str, historique: list, question: str, cle: str,
             modele: str | None = None, timeout: int = 90) -> str:
    """Répond à une question de chat. `historique` : [{"role": "user"|"model", "content": str}].

    Le contexte du portefeuille (poids en %, dernière analyse IA) est injecté en instruction
    systématique à chaque message : la conversation n'a pas besoin d'historique long.
    """
    modele = modele or MODELE_DEFAUT
    contenus = ([{"role": m["role"], "parts": [{"text": m["content"]}]}
                 for m in historique[-2 * MAX_TOURS_CHAT:]]
                + [{"role": "user", "parts": [{"text": question}]}])
    payload = {"systemInstruction": {"parts": [{"text": SYSTEME_CHAT + "\n\n" + contexte}]},
               "contents": contenus,
               "generationConfig": {"maxOutputTokens": MAX_TOKENS_CHAT,
                                    "thinkingConfig": {"thinkingLevel": "low"}}}
    try:
        r = requests.post(URL.format(modele=modele), json=payload, timeout=timeout,
                          headers={"x-goog-api-key": cle, "Content-Type": "application/json"})
    except requests.Timeout:
        raise ErreurIA("Délai dépassé : Gemini n'a pas répondu à temps. Réessayez.")
    except requests.RequestException:
        raise ErreurIA("Connexion à Gemini impossible. Réessayez plus tard.")
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
    texte = "".join(x.get("text", "") for x in parts if not x.get("thought")).strip()
    if not texte:
        raise ErreurIA("Gemini n'a renvoyé aucune réponse exploitable (contenu bloqué ou vide).")
    return _tronquer_mots(texte, MAX_MOTS_REPONSE)
