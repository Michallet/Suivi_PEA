"""Non-régression : les sorties du code pur doivent rester identiques à celles du code d'origine."""
import json
import math
import pathlib

import pytest

from tests.scenarios import SCENARIOS
from tests.serialisation import norm

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden" / "caracterisation.json").read_text(encoding="utf-8"))


def _egal(a, b, chemin="") -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), f"{chemin} : clés différentes {sorted(set(a) ^ set(b))}"
        for k in a:
            _egal(a[k], b[k], f"{chemin}/{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{chemin} : longueurs {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _egal(x, y, f"{chemin}[{i}]")
    elif isinstance(a, float) and isinstance(b, float) and not (math.isnan(a) or math.isnan(b)):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-9), f"{chemin} : {a} != {b}"
    else:
        assert a == b, f"{chemin} : {a!r} != {b!r}"


def test_tous_les_scenarios_ont_une_reference():
    assert set(SCENARIOS) == set(GOLDEN)


@pytest.mark.parametrize("nom", sorted(SCENARIOS))
def test_scenario_identique_au_code_d_origine(nom):
    _egal(norm(SCENARIOS[nom]()), GOLDEN[nom], nom)
