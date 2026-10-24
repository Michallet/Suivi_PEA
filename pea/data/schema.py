"""Colonnes métier de chaque table, ordre de tri, colonnes numériques, lectures bornées.

La colonne technique ``user_id`` existe dans toutes les tables de compte mais n'est jamais renvoyée à
l'interface. La cohérence avec sql/schema.sql est vérifiée par tests/test_schema.py.
"""
SCHEMA = {
    "transactions": ["id", "date", "isin", "type", "quantite", "prix", "frais"],
    "dividendes": ["id", "date", "isin", "montant"],
    "versements": ["id", "date", "type", "montant", "libelle"],
    "secteurs": ["isin", "secteur"],
    "tickers": ["isin", "ticker", "nom", "dernier_prix", "dernier_prix_at",
                "concurrent_isin", "concurrent_ticker", "concurrent_nom"],
    "snapshots": ["date", "valeur", "apports"],
    "watchlist": ["isin", "note", "ajoute_le"],
    "partage": ["partage", "pseudo"],
    "scenarios": ["id", "nom", "versement", "cree_le"],
    "scenario_trades": ["id", "scenario_id", "isin", "type", "quantite", "prix", "cree_le"],
    "analyses_ia": ["id", "cree_le", "modele", "empreinte", "resultat"],
    "analyses_scen": ["id", "scenario_id", "cree_le", "modele", "empreinte", "resultat"],
    "chat_log": ["id", "cree_le"],
    "usage_ia": ["id", "nature", "cree_le"],
}

# Toutes ces tables contiennent un user_id : aucune donnée métier n'est partagée entre comptes.
TABLES_PAR_UTILISATEUR = frozenset(SCHEMA)
# Tables lues au démarrage d'une session (chat_log et usage_ia ne sont que comptées, jamais relues).
TABLES_COMPTE = ("transactions", "dividendes", "versements", "secteurs", "tickers", "snapshots", "watchlist",
                 "partage", "scenarios", "scenario_trades", "analyses_ia", "analyses_scen")
ORDRE = {
    "transactions": ["date", "id"], "dividendes": ["date", "id"], "versements": ["date", "id"],
    "secteurs": ["isin"], "tickers": ["isin"], "snapshots": ["date"],
    "watchlist": ["ajoute_le"], "scenarios": ["id"],
    "scenario_trades": ["id"], "analyses_ia": ["id"], "analyses_scen": ["scenario_id", "id"],
    "chat_log": ["id"], "partage": ["pseudo"], "usage_ia": ["id"],
}
# Tables qui grossissent sans limite : seules les lignes les plus récentes sont relues (P5).
DERNIERES_LIGNES = {"analyses_ia": 1, "analyses_scen": 200}
NUMERIQUES = ("quantite", "prix", "frais", "montant", "dernier_prix", "valeur", "apports", "versement")
# Clé naturelle des tables sans `id` (hors user_id) : sert aux upserts et au mode démo.
CLES_NATURELLES = {"secteurs": ("isin",), "tickers": ("isin",), "snapshots": ("date",), "watchlist": ("isin",),
                   "partage": ()}
# Suppressions en cascade portées par les clés étrangères (reproduites en mode démo).
CASCADES = {"scenarios": (("scenario_trades", "scenario_id"), ("analyses_scen", "scenario_id")),
            "tickers": (("watchlist", "isin"),)}
