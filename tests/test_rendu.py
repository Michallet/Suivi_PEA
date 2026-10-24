"""Parité du rendu : chaque écran de chaque compte affiche les mêmes éléments que l'app de l'étape 1."""
import json
import warnings

import pytest

from tests.rendu import COMPTES, GOLDEN, rendu

warnings.filterwarnings("ignore")
REFERENCE = json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("uid", COMPTES)
def test_meme_rendu_que_l_etape_1(uid):
    obtenu = rendu("app.py", uid)
    for ecran, attendu in REFERENCE[uid].items():
        assert obtenu[ecran] == attendu, ecran
