"""Prompts, schémas JSON, critères d'analyse et exemples statiques de l'IA (aucun appel réseau ici).

Les prompts sont éditables dans `prompts.md` (racine du dépôt) : sections « ## analyse », « ## scenario »,
« ## chat », « ## capture », « ## concurrent ». Section absente (ou fichier manquant) = valeur par défaut ci-dessous.
"""
from __future__ import annotations

import re

from pea import config

VERSION_PROMPT = "v1"
PROMPTS_FICHIER = str(config.RACINE / "prompts.md")
MAX_MOTS_REPONSE = 300  # filet de sécurité : le prompt demande quelques phrases
POINTS_MAX_PAR_CRITERE = 2


def charger_prompts_md(fichier: str = PROMPTS_FICHIER) -> dict:
    """Retourne {nom_de_section: texte} lu dans prompts.md. Fichier absent = aucune surcharge."""
    try:
        with open(fichier, encoding="utf-8") as f:
            texte = f.read()
    except OSError:
        return {}
    sections = {}
    for m in re.finditer(r"^##\s+([a-z0-9_-]+)\s*$([\s\S]*?)(?=^##\s|\Z)", texte, flags=re.M | re.I):
        sections[m.group(1).lower()] = m.group(2).strip()
    return sections


PROMPTS_MD = charger_prompts_md()

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


# --------------------------------------------------------------------------- #
# Import par captures d'écran du courtier (vision)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Chatbot
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


# --------------------------------------------------------------------------- #
# Concurrent (suggestion)
# --------------------------------------------------------------------------- #
SYSTEME_CONCURRENT_DEFAUT = (
    "Tu aides un investisseur à repérer UN concurrent coté d'une entreprise cotée, pour comparer leurs "
    "ratios financiers (PER, EV/EBITDA, marges). Tu ne fais aucune analyse ni recommandation.\n"
    "Tu reçois le nom, l'ISIN, le secteur, l'industrie et la capitalisation approximative.\n"
    "Propose au plus 3 candidats, du meilleur au moins bon. Critères, par ordre d'importance :\n"
    "1. Concurrent DIRECT : même activité principale et mêmes types de clients.\n"
    "2. Coté sur une grande place boursière, avec des données publiques complètes.\n"
    "3. De préférence du même pays, sinon de la même zone géographique (Europe).\n"
    "4. Taille comparable : capitalisation du même ordre de grandeur (idéalement entre un tiers et trois "
    "fois celle du titre).\n"
    "5. Jamais la même société, une de ses filiales, ni son actionnaire majoritaire.\n"
    "ISIN : celui de l'action ordinaire principale du candidat. N'invente JAMAIS un ISIN : si tu n'es pas "
    "certain à 100 %, laisse la chaîne vide (le candidat sera ignoré).\n"
    "raison : au plus 12 mots, factuelle.\n"
    "Réponds uniquement par un objet JSON conforme au schéma demandé."
)
SYSTEME_CONCURRENT = PROMPTS_MD.get("concurrent", SYSTEME_CONCURRENT_DEFAUT)

SCHEMA_JSON_CONCURRENT = {
    "type": "object",
    "properties": {
        "candidats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"nom": {"type": "string"}, "isin": {"type": "string"},
                               "raison": {"type": "string"}},
                "required": ["nom", "isin", "raison"],
            },
        },
    },
    "required": ["candidats"],
}
