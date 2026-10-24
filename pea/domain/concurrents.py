"""Concurrent coté d'un titre : un seul par titre, stocké en base (tickers.concurrent_*).

Partie PURE (aucun réseau, aucune IA) :
* `construire_contexte` : texte envoyé à l'IA (identité publique du titre uniquement) ;
* `normaliser_candidats` / `choisir_concurrent` : on garde le premier candidat dont l'ISIN est valide,
  résolu par Yahoo ET dont le nom correspond (garde-fou contre un ISIN halluciné) ;
* `preparer_concurrent` : saisie manuelle (ISIN et/ou ticker), mêmes contrôles ;
* `lignes_comparaison` : multiples et marges côte à côte.
Le réseau (Yahoo) est injecté via `resoudre`. L'appel à l'IA est dans pea.services.ia.concurrent.
"""
from __future__ import annotations

from pea.domain import calculs as C
from pea.domain import import_ecran as IE
from pea.domain.erreurs import ErreurIA
from pea.domain.formats import formater_gros_nombre
from pea.domain.nombres import nombre

MAX_CANDIDATS = 3


def construire_contexte(nom: str, isin: str, f: dict | None) -> str:
    """Texte envoyé à Gemini : identité publique du titre uniquement (aucune donnée du portefeuille)."""
    f = f or {}
    lignes = [f"Entreprise : {nom}", f"ISIN : {isin} (pays : {isin[:2]})"]
    if f.get("secteur_yahoo"):
        lignes.append(f"Secteur : {f['secteur_yahoo']}")
    if f.get("industrie"):
        lignes.append(f"Industrie : {f['industrie']}")
    if f.get("capi"):
        lignes.append(f"Capitalisation approximative : {formater_gros_nombre(f['capi'])}")
    return "\n".join(lignes) + "\n\nPropose les concurrents cotés les plus pertinents."


def normaliser_candidats(obj) -> list[dict]:
    """Garde les candidats à ISIN valide (contrôle Luhn), sans doublon, dans l'ordre de l'IA."""
    brut = obj.get("candidats") if isinstance(obj, dict) else None
    if not isinstance(brut, list):
        raise ErreurIA("Réponse de l'IA inattendue (candidats).")
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


def _marge(f: dict, cle: str):
    num, ca = nombre(f.get(cle)), nombre(f.get("ca"))
    return num / ca * 100 if num is not None and ca and ca > 0 else None


def lignes_comparaison(ft: dict | None, fc: dict | None) -> list[dict]:
    """Lignes {label, vt, vc, unite} ; vt = titre, vc = concurrent (None si indisponible).

    unite : 'x' (multiple), '%' (marge), 'montant' (€). Les montants ne sont donnés que si les DEUX
    titres cotent en euros (sinon la devise fausserait la comparaison).
    """
    ft, fc = ft or {}, fc or {}
    lignes = []

    def ajouter(label, vt, vc, unite):
        if vt is not None or vc is not None:
            lignes.append({"label": label, "vt": vt, "vc": vc, "unite": unite})

    for label, cle in (("PER", "per"), ("PER prévisionnel", "per_prev"), ("EV/EBITDA", "ev_ebitda")):
        ajouter(label, nombre(ft.get(cle)), nombre(fc.get(cle)), "x")
    ajouter("Marge nette", _marge(ft, "net_income"), _marge(fc, "net_income"), "%")
    ajouter("Marge EBITDA", _marge(ft, "ebitda"), _marge(fc, "ebitda"), "%")
    if ft.get("devise") == "EUR" and fc.get("devise") == "EUR":
        ajouter("Capitalisation", nombre(ft.get("capi")), nombre(fc.get("capi")), "montant")
    return lignes
