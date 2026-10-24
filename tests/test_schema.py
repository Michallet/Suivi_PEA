"""pea/data/schema.py doit rester cohérent avec les fichiers SQL (colonnes et tables)."""
import re

from pea.data.schema import SCHEMA
from tests.modules import RACINE


def colonnes_sql() -> dict[str, set[str]]:
    texte = (RACINE / "sql/schema.sql").read_text(encoding="utf-8")
    texte += (RACINE / "sql/migrations/001_cache_marche_quotas.sql").read_text(encoding="utf-8")
    tables = {}
    for m in re.finditer(r"create table if not exists (\w+) \((.*?)\n\);", texte, flags=re.S):
        cols = {l.strip().split()[0] for l in m.group(2).splitlines()
                if l.strip() and not l.strip().startswith(("primary", "unique", "constraint", "references", "--"))}
        tables[m.group(1)] = cols
    for m in re.finditer(r"alter table (\w+) add column if not exists (\w+)", texte):
        tables[m.group(1)].add(m.group(2))
    return tables


def test_colonnes_metier_presentes_en_sql():
    sql = colonnes_sql()
    for table, cols in SCHEMA.items():
        assert table in sql, table
        assert set(cols) <= sql[table], (table, set(cols) - sql[table])
        assert "user_id" in sql[table]
