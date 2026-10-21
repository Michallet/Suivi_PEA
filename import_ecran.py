"""Import du portefeuille depuis des captures d'écran du courtier : logique pure.

Aucune dépendance à Streamlit, au réseau ni à Gemini (testable avec pytest).
Chaîne de traitement :

1. ``normaliser_releve``  : nettoie le JSON renvoyé par Gemini (nombres, doublons entre captures qui se
   chevauchent, ISIN invalides écartés).
2. ``resoudre_isins``     : retrouve l'ISIN de chaque ligne. Les captures de courtier n'affichent
   souvent que le NOM : on rapproche d'abord avec la base de l'utilisateur, l'ISIN proposé par
   l'IA n'est qu'un dernier recours (signalé « à vérifier »).
3. ``proposer_operations``: différence entre le relevé du courtier et les positions de la base
   -> achats / ventes à valider. Le prix d'un achat est DÉDUIT du PRM du courtier pour que le PRM
   de l'application redevienne identique au sien.
4. ``preparer_insertions``: contrôle final des lignes cochées par l'utilisateur.
5. ``ecarts_apres``       : écarts restants entre le courtier et la base une fois les opérations passées.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

import pandas as pd

import calculs as C

TOL_QTE = 1e-6          # quantités considérées égales
TOL_PRM_PCT = 1.0       # écart de PRM (en %) en dessous duquel on ne signale rien
SEUIL_NOM = 0.8         # part des mots du nom courtier retrouvés dans le nom connu
SEUIL_PRM_POSITION = 0.5  # % : rapprochement par « même quantité et même PRM »
ECART_COURS_PCT = 15.0  # valeur affichée / quantité vs cours Yahoo : au-delà, lecture douteuse
ECART_PRM_PCT = 60.0    # idem sans cours Yahoo : comparaison au PRM

COLS_OPERATIONS = ["valider", "date", "isin", "nom", "type", "quantite", "prix", "frais", "note"]
COLS_ECARTS = ["isin", "nom", "qte_base", "qte_courtier", "prm_base", "prm_courtier", "ecart_prm_pct"]
MOTS_VIDES = {"action", "etf", "ucits", "acc", "dist", "eur", "the", "de", "du", "des", "la", "le",
              "les", "et", "sa", "se", "ag", "nv", "plc"}


# --------------------------------------------------------------------------- #
# Contrôle des images envoyées
# --------------------------------------------------------------------------- #
def type_image_reel(octets: bytes) -> str | None:
    """Type MIME déduit des premiers octets (PNG, JPEG, WebP), sinon None.

    Le type annoncé par le navigateur est modifiable : on ne transmet à Gemini que de vraies images.
    """
    if octets[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if octets[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "image/webp"
    return None


# --------------------------------------------------------------------------- #
# Lecture du JSON renvoyé par Gemini
# --------------------------------------------------------------------------- #
def _nombre(x) -> float | None:
    """Nombre lu tel quel ou dans une chaîne « 1 859,86 » ; None si illisible."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return None if pd.isna(x) else float(x)
    t = re.sub(r"[\s  €]", "", str(x)).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _normaliser_nom(nom: str) -> tuple[list[str], bool]:
    """(mots significatifs, nom tronqué ?). Un nom se terminant par « … » ou « ... » est tronqué."""
    brut = str(nom or "").strip()
    tronque = brut.endswith("…") or brut.endswith("...")
    sans_accents = unicodedata.normalize("NFKD", brut.lower()).encode("ascii", "ignore").decode()
    mots = [m for m in re.split(r"[^a-z0-9]+", sans_accents) if m and m not in MOTS_VIDES]
    return mots, tronque


def normaliser_releve(obj) -> tuple[list[dict], list[str]]:
    """Retourne (lignes propres, avertissements).

    Ligne : {nom, isin_capture, isin_ia, quantite, prm, valeur}. ``isin_capture`` = ISIN lu à l'écran,
    ``isin_ia`` = ISIN deviné par l'IA ; les deux sont écartés s'ils échouent au contrôle (Luhn).
    Une même ligne vue sur deux captures qui se chevauchent n'est gardée qu'une fois.
    """
    avert: list[str] = []
    brutes = obj.get("lignes") if isinstance(obj, dict) else None
    if not isinstance(brutes, list):
        return [], ["Réponse de l'IA inattendue : aucune liste de lignes."]
    lignes: list[dict] = []
    for b in brutes:
        if not isinstance(b, dict):
            continue
        nom = re.sub(r"\s+", " ", str(b.get("nom") or "")).strip()
        q, prm, val = _nombre(b.get("quantite")), _nombre(b.get("prm")), _nombre(b.get("valeur"))
        if not nom or q is None or q <= 0 or prm is None or prm <= 0:
            avert.append(f"Ligne ignorée (illisible ou incomplète) : « {nom or '?'} ».")
            continue
        isins = {}
        for cle in ("isin_capture", "isin_ia"):
            v = str(b.get(cle) or "").strip().upper()
            isins[cle] = v if v and C.isin_valide(v) else None
            if v and isins[cle] is None:
                avert.append(f"ISIN « {v} » invalide ignoré pour « {nom} ».")
        doublon = next((l for l in lignes if _meme_ligne(l, nom, isins)), None)
        if doublon is not None:
            if abs(doublon["quantite"] - q) > TOL_QTE or abs(doublon["prm"] - prm) > 1e-3 * prm:
                avert.append(f"« {nom} » apparaît deux fois avec des valeurs différentes : "
                             f"la première lecture est conservée.")
            continue
        lignes.append({"nom": nom, "quantite": q, "prm": prm, "valeur": val, **isins})
    return lignes, avert


def _meme_ligne(l: dict, nom: str, isins: dict) -> bool:
    for cle in ("isin_capture", "isin_ia"):
        if isins[cle] and isins[cle] == l[cle]:
            return True
    return _normaliser_nom(l["nom"])[0] == _normaliser_nom(nom)[0]


# --------------------------------------------------------------------------- #
# Retrouver l'ISIN
# --------------------------------------------------------------------------- #
def _score_nom(mots_c: list[str], tronque: bool, mots_k: list[str]) -> tuple[float, float]:
    """(couverture, jaccard) : part des mots du courtier retrouvés dans le nom connu."""
    if not mots_c or not mots_k:
        return 0.0, 0.0
    trouves = 0
    for i, m in enumerate(mots_c):
        dernier = tronque and i == len(mots_c) - 1  # le dernier mot coupé : on compare le préfixe
        if m in mots_k or (dernier and any(k.startswith(m) for k in mots_k)):
            trouves += 1
    union = len(set(mots_c) | set(mots_k))
    return trouves / len(mots_c), len(set(mots_c) & set(mots_k)) / union


def noms_proches(a: str, b: str, seuil: float = 0.5) -> bool:
    """Vrai si au moins `seuil` des mots du nom `a` figurent dans le nom `b` (accents/casse/formes
    juridiques ignorés) : « Siemens » ~ « SIEMENS AG ». Sert à vérifier qu'un ISIN désigne bien la société attendue."""
    mots_a, tronque = _normaliser_nom(a)
    couverture, _ = _score_nom(mots_a, tronque, _normaliser_nom(b)[0])
    return couverture >= seuil


def _par_nom(nom: str, connus: dict[str, str]) -> str | None:
    """ISIN du nom connu qui ressemble le plus, seulement s'il est sans ambiguïté."""
    mots_c, tronque = _normaliser_nom(nom)
    notes = []
    for isin, nom_k in connus.items():
        if nom_k:
            couv, jac = _score_nom(mots_c, tronque, _normaliser_nom(nom_k)[0])
            if couv >= SEUIL_NOM:
                notes.append((couv, jac, isin))
    notes.sort(reverse=True)
    if not notes:
        return None
    if len(notes) > 1 and notes[0][0] - notes[1][0] < 1e-9 and notes[0][1] - notes[1][1] < 0.1:
        return None  # deux candidats aussi bons : on laisse l'utilisateur trancher
    return notes[0][2]


def _par_position(l: dict, positions: pd.DataFrame, deja: set) -> str | None:
    """Ligne détenue ayant exactement la même quantité et (à 0,5 % près) le même PRM."""
    if positions.empty:
        return None
    cand = [r.isin for r in positions.itertuples()
            if r.isin not in deja and abs(r.quantite - l["quantite"]) < TOL_QTE
            and abs(r.prm / l["prm"] - 1) * 100 <= SEUIL_PRM_POSITION]
    return cand[0] if len(cand) == 1 else None


def resoudre_isins(lignes: list[dict], noms_connus: dict[str, str],
                   positions: pd.DataFrame) -> list[dict]:
    """Ajoute ``isin`` et ``source_isin`` (capture | nom | position | ia | None) à chaque ligne.

    ``noms_connus`` : {isin: nom} de la base (tickers). Ordre de confiance décroissant :
    ISIN lu à l'écran, nom connu, même quantité + même PRM qu'une position, ISIN deviné par l'IA.
    Deux lignes du courtier résolues vers le même ISIN sont fusionnées (quantités additionnées,
    PRM pondéré).
    """
    res: list[dict] = []
    pris: set[str] = set()
    for l in lignes:                      # 1re passe : les sources fiables, pour réserver les ISIN
        isin, src = None, None
        if l["isin_capture"]:
            isin, src = l["isin_capture"], "capture"
        else:
            isin = _par_nom(l["nom"], noms_connus)
            src = "nom" if isin else None
        if isin:
            pris.add(isin)
        res.append({**l, "isin": isin, "source_isin": src})
    for r in res:                         # 2e passe : repli quantité + PRM, puis suggestion de l'IA
        if r["isin"]:
            continue
        isin = _par_position(r, positions, pris)
        if isin:
            r["isin"], r["source_isin"] = isin, "position"
        elif r["isin_ia"]:
            r["isin"], r["source_isin"] = r["isin_ia"], "ia"
        if r["isin"]:
            pris.add(r["isin"])
    return _fusionner(res)


def _fusionner(res: list[dict]) -> list[dict]:
    sortie: dict[str, dict] = {}
    for r in res:
        if not r["isin"] or r["isin"] not in sortie:
            sortie[r["isin"] or f"?{len(sortie)}"] = r
            continue
        a = sortie[r["isin"]]
        q = a["quantite"] + r["quantite"]
        a["prm"] = (a["prm"] * a["quantite"] + r["prm"] * r["quantite"]) / q
        a["quantite"] = q
        a["valeur"] = (a["valeur"] or 0) + (r["valeur"] or 0) if (a["valeur"] or r["valeur"]) else None
    return list(sortie.values())


# --------------------------------------------------------------------------- #
# Différence courtier / base
# --------------------------------------------------------------------------- #
def controle_lecture(l: dict, cours: float | None) -> str:
    """Alerte si valeur affichée / quantité s'écarte trop du cours (ou du PRM) : chiffre mal lu ?"""
    if not l.get("valeur") or l["quantite"] <= 0:
        return ""
    unitaire = l["valeur"] / l["quantite"]
    if cours:
        ecart, seuil, ref = abs(unitaire / cours - 1) * 100, ECART_COURS_PCT, "au cours"
    else:
        ecart, seuil, ref = abs(unitaire / l["prm"] - 1) * 100, ECART_PRM_PCT, "au PRM"
    return f"⚠️ Lecture à vérifier : valeur ÷ quantité s'écarte de {ecart:.0f} % {ref}. " if ecart > seuil else ""


def proposer_operations(releve: list[dict], positions: pd.DataFrame, cours: dict[str, float],
                        jour: date) -> pd.DataFrame:
    """Achats / ventes qui amènent la base au niveau du relevé du courtier.

    * Quantité plus élevée chez le courtier -> ACHAT de la différence, au prix qui redonne le PRM du courtier.
    * Quantité plus faible                  -> VENTE de la différence, au cours (prix à compléter).
    * Ligne détenue absente des captures    -> VENTE totale, DÉCOCHÉE (la capture peut être incomplète).
    * Ligne sans ISIN reconnu               -> ACHAT décoché, ISIN à renseigner.
    """
    pos = positions.set_index("isin") if not positions.empty else pd.DataFrame(
        columns=["quantite", "cout", "prm"])
    noms = {l["isin"]: l["nom"] for l in releve if l.get("isin")}
    lignes: list[dict] = []

    def ajouter(valider, isin, nom, typ, q, prix, note):
        lignes.append({"valider": valider, "date": jour, "isin": isin or "", "nom": nom, "type": typ,
                       "quantite": round(float(q), 6), "prix": round(float(prix), 4),
                       "frais": 0.0, "note": note.strip()})

    for l in releve:
        isin, q_b, prm_b = l.get("isin"), l["quantite"], l["prm"]
        q_db = float(pos.loc[isin, "quantite"]) if isin in pos.index else 0.0
        cout_db = float(pos.loc[isin, "cout"]) if isin in pos.index else 0.0
        marche = cours.get(isin) if isin else None
        alerte = controle_lecture(l, marche)
        delta = q_b - q_db
        if abs(delta) <= TOL_QTE:
            continue
        if not isin:
            ajouter(False, "", l["nom"], "ACHAT", q_b, prm_b,
                    alerte + "ISIN introuvable : à renseigner puis cocher.")
        elif delta > 0:
            implicite = (prm_b * q_b - cout_db) / delta
            if implicite > 0:
                ajouter(True, isin, l["nom"], "ACHAT", delta, implicite,
                        alerte + "Prix déduit du PRM du courtier (frais inclus).")
            else:
                ajouter(True, isin, l["nom"], "ACHAT", delta, marche or prm_b,
                        alerte + "PRM courtier incohérent avec la base : prix au cours, à corriger.")
        else:
            ajouter(True, isin, l["nom"], "VENTE", -delta, marche or prm_b,
                    alerte + "Prix de vente à compléter (cours actuel par défaut).")
        if isin and l.get("source_isin") == "ia":
            lignes[-1]["note"] = "⚠️ ISIN proposé par l'IA, à vérifier. " + lignes[-1]["note"]

    for isin, r in pos.iterrows():       # lignes détenues qui n'apparaissent plus
        if isin not in noms and r["quantite"] > TOL_QTE:
            ajouter(False, isin, isin, "VENTE", r["quantite"], cours.get(isin) or r["prm"],
                    "Absente des captures : vendue ? Décochée par prudence "
                    "(une capture manque peut-être).")
    return pd.DataFrame(lignes, columns=COLS_OPERATIONS)


def preparer_insertions(ops: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Lignes cochées -> DataFrame au format `transactions` ; erreurs bloquantes en clair."""
    erreurs: list[str] = []
    ok = ops[ops["valider"].fillna(False).astype(bool)].copy()
    sortie = []
    for i, r in ok.iterrows():
        pre = f"Ligne {i + 1} ({r['nom'] or r['isin'] or '?'}) : "
        isin = str(r["isin"] or "").strip().upper()
        if not C.isin_valide(isin):
            erreurs.append(pre + "ISIN invalide ou manquant.")
        if r["type"] not in ("ACHAT", "VENTE"):
            erreurs.append(pre + "type inconnu.")
        q, p, f = _nombre(r["quantite"]), _nombre(r["prix"]), _nombre(r["frais"]) or 0.0
        if q is None or q <= 0 or p is None or p <= 0 or f < 0:
            erreurs.append(pre + "quantité, prix ou frais invalide.")
        d = pd.to_datetime(r["date"], errors="coerce")
        if pd.isna(d):
            erreurs.append(pre + "date manquante.")
        elif d.date() > date.today() + timedelta(days=1):  # tolérance de fuseau
            erreurs.append(pre + "date dans le futur.")
        sortie.append({"date": d, "isin": isin, "type": r["type"], "quantite": q, "prix": p, "frais": f})
    return pd.DataFrame(sortie, columns=["date", "isin", "type", "quantite", "prix", "frais"]), erreurs


def ecarts_apres(releve: list[dict], positions: pd.DataFrame) -> pd.DataFrame:
    """Écarts qui subsistent entre le courtier et `positions` (quantité, ou PRM au-delà de 1 %)."""
    pos = positions.set_index("isin") if not positions.empty else pd.DataFrame(
        columns=["quantite", "prm"])
    lignes, vus = [], set()
    for l in releve:
        isin = l.get("isin")
        vus.add(isin)
        q_db = float(pos.loc[isin, "quantite"]) if isin in pos.index else 0.0
        prm_db = float(pos.loc[isin, "prm"]) if isin in pos.index else None
        ecart = (prm_db / l["prm"] - 1) * 100 if prm_db else None
        if not isin or abs(q_db - l["quantite"]) > TOL_QTE or (ecart is not None and abs(ecart) > TOL_PRM_PCT):
            lignes.append({"isin": isin or "ISIN ?", "nom": l["nom"], "qte_base": q_db,
                           "qte_courtier": l["quantite"], "prm_base": prm_db,
                           "prm_courtier": l["prm"], "ecart_prm_pct": ecart})
    for isin, r in pos.iterrows():
        if isin not in vus and r["quantite"] > TOL_QTE:
            lignes.append({"isin": isin, "nom": isin, "qte_base": float(r["quantite"]),
                           "qte_courtier": 0.0, "prm_base": float(r["prm"]),
                           "prm_courtier": None, "ecart_prm_pct": None})
    return pd.DataFrame(lignes, columns=COLS_ECARTS)
