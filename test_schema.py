"""Garde-fou : les colonnes de schema.py doivent correspondre à celles de schema.sql.

Une colonne présente en base mais absente de SCHEMA est silencieusement ignorée par db.lire()
(c'était le cas de watchlist.url).
"""
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
from schema import SCHEMA  # noqa: E402


def _colonnes_sql() -> dict:
    sql = open(os.path.join(RACINE, "schema.sql"), encoding="utf-8").read()
    tables = {}
    for m in re.finditer(r"create table if not exists (\w+) \((.*?)\n\);", sql, flags=re.S | re.I):
        cols = []
        for ligne in m.group(2).splitlines():
            ligne = ligne.split("--")[0].strip()
            if ligne and not ligne.lower().startswith(("primary", "unique", "check", "foreign")):
                cols.append(ligne.split()[0])
        tables[m.group(1)] = cols
    return tables


def test_schema_py_correspond_a_schema_sql():
    sql = _colonnes_sql()
    assert set(sql) == set(SCHEMA), f"tables différentes : {set(sql) ^ set(SCHEMA)}"
    for table, cols in sql.items():
        assert sorted(cols) == sorted(SCHEMA[table]), f"{table} : SQL {cols} ≠ schema.py {SCHEMA[table]}"
