"""Écrit tests/golden/caracterisation.json depuis le code COURANT.

À exécuter UNIQUEMENT sur le code d'origine (avant refonte), puis ne plus y toucher : le fichier
est la référence de non-régression des règles métier.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.scenarios import SCENARIOS  # noqa: E402
from tests.serialisation import norm  # noqa: E402

if __name__ == "__main__":
    sortie = {nom: norm(f()) for nom, f in SCENARIOS.items()}
    chemin = pathlib.Path(__file__).resolve().parent / "golden" / "caracterisation.json"
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(sortie)} scénarios écrits dans {chemin}")
