"""Conversions numériques uniques : un seul endroit pour lire un nombre venu de Yahoo, de l'IA ou d'un formulaire."""
from __future__ import annotations

import math
import re

_ESPACES_ET_EURO = re.compile(r"[\s \xa0€]")


def nombre(x) -> float | None:
    """Nombre fini lu tel quel ou dans une chaîne (« 1 859,86 », « 12 € ») ; None si absent ou illisible.

    Jamais 0 par défaut : une valeur manquante reste manquante (règle du README sur les données Yahoo).
    Booléens, NaN et infinis sont refusés.
    """
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        try:
            v = float(_ESPACES_ET_EURO.sub("", str(x)).replace(",", "."))
        except ValueError:
            return None
    return v if math.isfinite(v) else None


def positif(x) -> float | None:
    """Comme `nombre`, mais strictement positif (cours, ratios de valorisation) ; None sinon."""
    v = nombre(x)
    return v if v is not None and v > 0 else None
