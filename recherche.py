"""Recherche de l'URL de publication financière d'un titre : requêtes, extraction des résultats
et classement. Module PUR (aucun appel réseau, aucune dépendance à Streamlit) => testable.

Le réseau et le cache sont dans donnees.chercher_url_publication().
"""
from __future__ import annotations

import base64
import re
import unicodedata
from urllib.parse import parse_qs, quote_plus, urlparse

# Mots révélant une page de publications (rapports, résultats, fiches ETF…)
MOTS_PUBLI = ("financial", "results", "resultat", "annual", "annuel", "rapport", "report", "publication",
              "investor", "investisseur", "finance", "urd", "registration", "enregistrement",
              "factsheet", "fiche", "kiid", "dic", "prospectus", "document")
DOMAINES_BRUIT = ("wikipedia.", "linkedin.", "facebook.", "youtube.", "instagram.", "twitter.",
                  "x.com", "reddit.", "pinterest.", "glassdoor.", "indeed.")
# Mots retirés du nom avant recherche (formes juridiques, libellés d'ETF)
MOTS_VIDES = {"se", "sa", "nv", "n.v.", "ag", "plc", "spa", "sas", "acciones", "ucits", "etf", "acc",
              "dist", "screened", "eur", "share", "shares", "ord"}
RE_ETF = re.compile(r"\b(etf|ucits|amundi|lyxor|ishares|xtrackers|pea)\b", re.I)


def sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def nom_propre(nom: str) -> str:
    """« Amundi PEA Asie Émergente (MSCI EM Asia) Screened » -> « Amundi PEA Asie Émergente »."""
    nom = re.sub(r"\([^)]*\)", " ", nom or "")
    return " ".join(m for m in nom.split() if m.lower().strip(".,") not in MOTS_VIDES)


def requetes(nom: str, isin: str | None = None) -> list[str]:
    """Deux requêtes complémentaires : page de publications, puis rapport en PDF (ETF : fiche produit)."""
    n = nom_propre(nom)
    if RE_ETF.search(nom or ""):
        suffixe = f" {isin}" if isin else ""
        return [f"{n}{suffixe} fiche produit factsheet", f"{n}{suffixe} DIC prospectus pdf"]
    return [f"{n} investor relations financial results publications", f"{n} annual financial report pdf"]


# --------------------------------------------------------------------------- #
# Moteurs (HTML sans clé API) : URL de requête + extraction des résultats organiques
# --------------------------------------------------------------------------- #
def url_ddg(q: str) -> str:
    return "https://html.duckduckgo.com/html/?q=" + quote_plus(q)


def url_bing(q: str) -> str:
    return "https://www.bing.com/search?setlang=fr&q=" + quote_plus(q)


def extraire_ddg(html: str) -> list[tuple[str, str]]:
    """[(url, titre)] d'une page DuckDuckGo « html » ; les publicités (duckduckgo.com/y.js) sont écartées."""
    from bs4 import BeautifulSoup

    out = []
    for a in BeautifulSoup(html or "", "html.parser").select("a.result__a"):
        href = a.get("href", "")
        if href.startswith("//"):
            href = "https:" + href
        cible = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        if cible.startswith(("http://", "https://")) and "duckduckgo.com" not in urlparse(cible).netloc.lower():
            out.append((cible, a.get_text(" ", strip=True)))
    return out


def _decoder_bing(href: str) -> str:
    """Les liens Bing passent par bing.com/ck/a?…&u=a1<base64url de l'URL réelle>."""
    if "bing.com/ck/" in href:
        u = parse_qs(urlparse(href).query).get("u", [""])[0]
        if u.startswith("a1"):
            try:
                brut = u[2:] + "=" * (-len(u[2:]) % 4)
                return base64.urlsafe_b64decode(brut).decode("utf-8")
            except Exception:
                return ""
    return href


def extraire_bing(html: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup

    out = []
    for a in BeautifulSoup(html or "", "html.parser").select("li.b_algo h2 a"):
        cible = _decoder_bing(a.get("href", ""))
        if cible.startswith(("http://", "https://")) and "bing.com" not in urlparse(cible).netloc.lower():
            out.append((cible, a.get_text(" ", strip=True)))
    return out


MOTEURS = [("DuckDuckGo", url_ddg, extraire_ddg), ("Bing", url_bing, extraire_bing)]


# --------------------------------------------------------------------------- #
# Classement : on veut la page de publications, pas la page d'accueil
# --------------------------------------------------------------------------- #
def est_page_accueil(url: str) -> bool:
    """Racine du site ou simple page de langue (/fr, /en-gb)."""
    chemin = urlparse(url or "").path.strip("/")
    return chemin == "" or bool(re.fullmatch(r"[a-z]{2}([-_][a-z]{2})?", chemin.lower()))


def _mots_nom(nom: str) -> list[str]:
    return re.findall(r"[a-z]{4,}", sans_accents(nom_propre(nom)).lower())


def score_lien(url: str, titre: str, nom: str) -> float:
    p = urlparse(url)
    hote = p.netloc.lower()
    chemin = p.path.lower()
    texte = sans_accents(chemin + " " + (titre or "")).lower()
    s = 0.0
    if any(b in hote for b in DOMAINES_BRUIT):
        s -= 5
    if chemin.endswith(".pdf"):
        s += 3
    s += 2 * min(2, sum(m in texte for m in MOTS_PUBLI))
    if est_page_accueil(url):
        s -= 4
    mots = _mots_nom(nom)
    if mots and any(m in hote.replace("-", "") for m in mots):
        s += 2  # le site porte le nom de l'émetteur : probablement officiel
    return s


def meilleur_lien(resultats: list[tuple[str, str]], nom: str) -> str | None:
    """Meilleur résultat (score le plus haut ; à égalité, le mieux classé par le moteur)."""
    if not resultats:
        return None
    i = max(range(len(resultats)), key=lambda k: (score_lien(resultats[k][0], resultats[k][1], nom), -k))
    return resultats[i][0]
