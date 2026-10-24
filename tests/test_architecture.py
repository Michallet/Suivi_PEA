"""Dépendances à sens unique : domaine ← données ← services ← interface ; Supabase derrière une seule porte."""
import ast
import pathlib

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent
INTERDITS_DOMAINE = {"streamlit", "requests", "yfinance", "supabase", "pea.data", "pea.services", "pea.ui"}


def imports(fichier: pathlib.Path) -> set[str]:
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            noms |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            noms.add(n.module)
    return noms


def _fichiers(dossier):
    return sorted((RACINE / dossier).rglob("*.py"))


@pytest.mark.parametrize("f", _fichiers("pea/domain"), ids=lambda f: f.name)
def test_domaine_pur(f):
    assert not {i for i in imports(f) if any(i == x or i.startswith(x + ".") for x in INTERDITS_DOMAINE)}


@pytest.mark.parametrize("f", _fichiers("pea/data"), ids=lambda f: f.name)
def test_donnees_ne_dependent_pas_des_services(f):
    assert not {i for i in imports(f) if i.startswith(("pea.services", "pea.ui"))}


def test_supabase_derriere_une_seule_porte():
    fautifs = []
    for f in [RACINE / "app.py", *RACINE.joinpath("pea").rglob("*.py")]:
        if f.name == "repo.py":
            continue
        texte = f.read_text(encoding="utf-8")
        if "supabase" in imports(f) or "create_client" in texte or "repo._client" in texte:
            fautifs.append(f.name)
    assert not fautifs


def test_aucun_except_muet():
    fautifs = []
    for f in [RACINE / "app.py", *RACINE.joinpath("pea").rglob("*.py")]:
        lignes = f.read_text(encoding="utf-8").splitlines()
        for i, l in enumerate(lignes[:-1]):
            if l.strip() == "except Exception:" and lignes[i + 1].strip() == "pass":
                fautifs.append(f"{f.name}:{i + 1}")
    assert not fautifs


@pytest.mark.parametrize("f", _fichiers("pea/services"), ids=lambda f: f.name)
def test_services_ne_dependent_pas_de_l_interface(f):
    assert not {i for i in imports(f) if i.startswith("pea.ui")}


def test_app_mince():
    assert len((RACINE / "app.py").read_text(encoding="utf-8").splitlines()) <= 150


def test_fonctions_courtes():
    """Aucune fonction de plus de 60 lignes dans l'application (constat C1 de l'audit)."""
    longues = []
    for f in [RACINE / "app.py", *RACINE.joinpath("pea").rglob("*.py")]:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.end_lineno - n.lineno + 1 > 60:
                longues.append(f"{f.name}:{n.name} ({n.end_lineno - n.lineno + 1})")
    assert not longues, longues


def test_cles_de_session_par_espace_de_noms():
    """L'interface n'écrit dans st.session_state qu'avec des clés de l'espace `c.` (via etat.k) ou des
    clés globales connues : la purge à la déconnexion reste complète."""
    import re
    motif = re.compile(r"session_state\[\s*[\"']([^\"']+)[\"']\s*\]")
    globales = {"user_id", "onglet", "_attente_marche", "login_user", "login_password"}
    fautives = []
    for f in [RACINE / "app.py", *RACINE.joinpath("pea", "ui").rglob("*.py")]:
        for cle in motif.findall(f.read_text(encoding="utf-8")):
            if not cle.startswith("c.") and cle not in globales:
                fautives.append(f"{f.name}:{cle}")
    assert not fautives, fautives
