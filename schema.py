"""Structure des colonnes métier exposées à l'interface Streamlit.

La colonne technique ``user_id`` existe dans toutes les tables mais est volontairement
filtrée dans ``db.lire`` et n'est pas exposée aux éditeurs de données.
"""
SCHEMA = {
    "transactions": ["id", "date", "isin", "type", "quantite", "prix", "frais"],
    "dividendes": ["id", "date", "isin", "montant"],
    "versements": ["id", "date", "type", "montant", "libelle"],
    "secteurs": ["isin", "secteur"],
    "tickers": ["isin", "ticker", "nom", "dernier_prix", "dernier_prix_at"],
    "snapshots": ["date", "valeur", "apports"],
    "watchlist": ["isin", "note", "ajoute_le"],
    "scenarios": ["id", "nom", "versement", "cree_le"],
    "scenario_trades": ["id", "scenario_id", "isin", "type", "quantite", "prix", "cree_le"],
    "analyses_ia": ["id", "cree_le", "modele", "empreinte", "resultat"],
    "analyses_scen": ["id", "scenario_id", "cree_le", "modele", "empreinte", "resultat"],
    "chat_log": ["id", "cree_le"],
}

# Toutes les tables contiennent un user_id : aucune donnée métier n'est partagée entre comptes.
TABLES_PAR_UTILISATEUR = frozenset(SCHEMA)
ORDRE = {
    "transactions": ["date", "id"], "dividendes": ["date", "id"], "versements": ["date", "id"],
    "secteurs": ["isin"], "tickers": ["isin"], "snapshots": ["date"],
    "watchlist": ["ajoute_le"], "scenarios": ["id"],
    "scenario_trades": ["id"], "analyses_ia": ["id"], "analyses_scen": ["scenario_id", "id"],
    "chat_log": ["id"],
}
NUMERIQUES = ("quantite", "prix", "frais", "montant", "dernier_prix", "valeur", "apports", "versement")
