"""Nettoyage des textes d'origine externe avant affichage (pseudos, noms Yahoo, sorties de l'IA).

Objectif : un texte venu de l'extérieur ne doit jamais produire de lien cliquable, d'image distante
ni de balise HTML dans une page Markdown de l'application.
"""
from __future__ import annotations

import html
import re

_SPECIAUX_MD = re.compile(r"([\\`*_\[\]<>!|~$#])")
_BALISES = re.compile(r"<[^>\n]*>")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LIEN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_LIEN_REF = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
_DEFINITION_REF = re.compile(r"(?m)^[ \t]*\[[^\]]+\]:[ \t]*\S.*$")
_URL_NUE = re.compile(r"(?i)\b(?:https?://|ftp://|www\.)\S+")


def echapper_markdown(texte) -> str:
    """Texte brut sûr à insérer dans du Markdown : caractères spéciaux échappés, une seule ligne."""
    t = " ".join(str(texte if texte is not None else "").split())
    return _SPECIAUX_MD.sub(r"\\\1", t)


def sur_pour_graphique(texte) -> str:
    """Texte sûr pour une légende Plotly (qui interprète quelques balises HTML)."""
    return html.escape(" ".join(str(texte if texte is not None else "").split()), quote=False)


def nettoyer_sortie_ia(texte) -> str:
    """Retire balises HTML, images, liens (le libellé est conservé) et adresses nues d'une sortie d'IA.

    La mise en forme simple (gras, listes, retours à la ligne) est conservée.
    """
    t = str(texte if texte is not None else "")
    t = _DEFINITION_REF.sub("", t)
    t = _IMAGE.sub(lambda m: m.group(1), t)
    t = _LIEN.sub(lambda m: m.group(1), t)
    t = _LIEN_REF.sub(lambda m: m.group(1), t)
    t = _BALISES.sub("", t)
    t = _URL_NUE.sub("(lien retiré)", t)
    return t.strip()
