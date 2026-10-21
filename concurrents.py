"""Concurrent coté d'un titre : un seul par titre, stocké en base (tickers.concurrent_*).

* `suggerer` : l'IA propose jusqu'à 3 candidats, on garde le premier dont l'ISIN est valide, résolu
  par Yahoo ET dont le nom correspond (garde-fou contre un ISIN halluciné). Appelé UNE fois à la
  création du titre (voir app.py), puis seulement sur demande explicite.
* `preparer_concurrent` : saisie manuelle (ISIN et/ou ticker), mêmes contrôles.
* `lignes_comparaison` : multiples et marges côte à côte (grandeurs sans unité : pas de souci de devise).
Aucune dépendance à Streamlit ; le réseau (Yahoo) est injecté via `resoudre`.
"""
from __future__ import annotations

import pandas as pd

import calculs as C
import import_ecran as IE
import llm

MAX_CANDIDATS = 3
MAX_SUGGESTIONS_PAR_JOUR = 20  # suggestions IA à la demande, comptées par session (voir app.py)

SYSTEME_DEFAUT = (
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
SYSTEME = llm.PROMPTS_MD.get("concurrent", SYSTEME_DEFAUT)  # surchargeable par « ## concurrent » dans prompts.md

SCHEMA_JSON = {
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


# --------------------------------------------------------------------------- #
# Suggestion par l'IA
# --------------------------------------------------------------------------- #
def construire_contexte(nom: str, isin: str, f: dict | None) -> str:
    """Texte envoyé à Gemini : identité publique du titre uniquement (aucune donnée du portefeuille)."""
    f = f or {}
    lignes = [f"Entreprise : {nom}", f"ISIN : {isin} (pays : {isin[:2]})"]
    if f.get("secteur_yahoo"):
        lignes.append(f"Secteur : {f['secteur_yahoo']}")
    if f.get("industrie"):
        lignes.append(f"Industrie : {f['industrie']}")
    if f.get("capi"):
        lignes.append(f"Capitalisation approximative : {C.formater_gros_nombre(f['capi'])}")
    return "\n".join(lignes) + "\n\nPropose les concurrents cotés les plus pertinents."


def normaliser_candidats(obj) -> list[dict]:
    """Garde les candidats à ISIN valide (contrôle Luhn), sans doublon, dans l'ordre de l'IA."""
    brut = obj.get("candidats") if isinstance(obj, dict) else None
    if not isinstance(brut, list):
        raise llm.ErreurIA("Réponse de l'IA inattendue (candidats).")
    vus, sortie = set(), []
    for c in brut:
        if not isinstance(c, dict):
            continue
        isin = str(c.get("isin") or "").strip().upper()
        nom = " ".join(str(c.get("nom") or "").split())
        if nom and C.isin_valide(isin) and isin not in vus:
            vus.add(isin)
            sortie.append({"nom": nom, "isin": isin, "raison": " ".join(str(c.get("raison") or "").split())})
    return sortie[:MAX_CANDIDATS]


def _payload(texte: str, variante: str) -> dict:
    config = {"responseMimeType": "application/json", "thinkingConfig": {"thinkingLevel": "low"},
              "maxOutputTokens": 2048}
    if variante == "json_schema":
        config["responseJsonSchema"] = SCHEMA_JSON
    else:
        config["responseSchema"] = llm._en_majuscules(SCHEMA_JSON)
    return {"systemInstruction": {"parts": [{"text": SYSTEME}]},
            "contents": [{"role": "user", "parts": [{"text": texte}]}],
            "generationConfig": config}


def demander_candidats(texte: str, cle: str, modele: str | None = None, timeout: int = 60) -> list[dict]:
    """Un appel Gemini (un nouvel essai si la réponse est illisible). Lève llm.ErreurIA."""
    modele = modele or llm.MODELE_DEFAUT
    derniere = None
    for _ in range(2):
        try:
            r = llm._post(_payload(texte, "json_schema"), cle, modele, timeout)
            if r.status_code == 400 and "schema" in llm._message_erreur(r).lower():
                r = llm._post(_payload(texte, "response_schema"), cle, modele, timeout)
            return normaliser_candidats(llm._parser_json(llm._texte_reponse(r, modele)))
        except llm.ErreurIA as e:
            derniere = e
            if any(m in str(e) for m in ("refusée", "introuvable", "Quota", "Clé")):
                break
    raise derniere


def choisir_concurrent(candidats: list[dict], isin_titre: str, resoudre) -> dict | None:
    """Premier candidat dont l'ISIN est résolu par `resoudre(isin) -> {ticker, nom} | None` ET dont le
    nom Yahoo ressemble au nom annoncé. Retourne {isin, ticker, nom, raison} ou None."""
    for c in candidats[:MAX_CANDIDATS]:
        if c["isin"] == isin_titre:
            continue
        try:
            r = resoudre(c["isin"])
        except Exception:
            r = None
        if r and r.get("ticker") and IE.noms_proches(c["nom"], r.get("nom") or ""):
            return {"isin": c["isin"], "ticker": r["ticker"], "nom": c["nom"], "raison": c.get("raison", "")}
    return None


def suggerer(nom: str, isin: str, f: dict | None, cle: str, modele: str | None, resoudre) -> dict | None:
    """Pipeline complet (1 appel Gemini + au plus 3 résolutions Yahoo). Lève llm.ErreurIA."""
    candidats = demander_candidats(construire_contexte(nom, isin, f), cle, modele)
    return choisir_concurrent(candidats, isin, resoudre)


# --------------------------------------------------------------------------- #
# Saisie manuelle
# --------------------------------------------------------------------------- #
def preparer_concurrent(isin_saisi: str, ticker_saisi: str, isin_titre: str,
                        resoudre) -> tuple[dict | None, str | None]:
    """(concurrent, erreur). `resoudre(isin, ticker) -> {ticker, nom} | None` : ticker validé par Yahoo si
    fourni, sinon trouvé à partir de l'ISIN. L'ISIN est facultatif quand un ticker est donné."""
    isin, ticker = (isin_saisi or "").strip().upper(), (ticker_saisi or "").strip().upper()
    if not isin and not ticker:
        return None, "Indiquez l'ISIN du concurrent (ou à défaut son ticker Yahoo)."
    if isin and not C.isin_valide(isin):
        return None, "ISIN invalide (12 caractères, clé de contrôle incorrecte)."
    if isin and isin == isin_titre:
        return None, "Le concurrent doit être une autre société que le titre."
    r = resoudre(isin, ticker or None)
    if not r or not r.get("ticker"):
        return None, ("Aucun cours Yahoo trouvé pour ce ticker." if ticker
                      else "Ticker introuvable pour cet ISIN : renseignez le ticker Yahoo.")
    return {"isin": isin, "ticker": r["ticker"], "nom": r.get("nom") or r["ticker"]}, None


# --------------------------------------------------------------------------- #
# Comparaison
# --------------------------------------------------------------------------- #
def _val(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if pd.notna(x) and x == x else None


def _marge(f: dict, cle: str):
    num, ca = _val(f.get(cle)), _val(f.get("ca"))
    return num / ca * 100 if num is not None and ca and ca > 0 else None


def lignes_comparaison(ft: dict | None, fc: dict | None) -> list[dict]:
    """Lignes {label, vt, vc, unite, ecart, type_ecart} ; vt = titre, vc = concurrent.

    unite : 'x' (multiple), '%' (marge), 'montant' (€). ecart : multiples -> écart relatif en %
    (type 'pct') ; marges -> écart en points (type 'pts') ; montants -> rapport (type 'ratio').
    Les montants ne sont comparés que si les DEUX titres cotent en euros (sinon la devise fausserait le rapport).
    """
    ft, fc = ft or {}, fc or {}
    lignes = []

    def ajouter(label, vt, vc, unite, mode):
        if vt is None and vc is None:
            return
        ecart = None
        if vt is not None and vc is not None:
            if mode == "pct" and vt > 0 and vc > 0:
                ecart = (vt / vc - 1) * 100
            elif mode == "pts":
                ecart = vt - vc
            elif mode == "ratio" and vc > 0:
                ecart = vt / vc
        lignes.append({"label": label, "vt": vt, "vc": vc, "unite": unite, "ecart": ecart,
                       "type_ecart": mode})

    for label, cle in (("PER", "per"), ("PER prévisionnel", "per_prev"), ("EV/EBITDA", "ev_ebitda")):
        ajouter(label, _val(ft.get(cle)), _val(fc.get(cle)), "x", "pct")
    ajouter("Marge nette", _marge(ft, "net_income"), _marge(fc, "net_income"), "%", "pts")
    ajouter("Marge EBITDA", _marge(ft, "ebitda"), _marge(fc, "ebitda"), "%", "pts")
    if ft.get("devise") == "EUR" and fc.get("devise") == "EUR":
        ajouter("Capitalisation", _val(ft.get("capi")), _val(fc.get("capi")), "montant", "ratio")
    return lignes
