"""Structure des tables (partagée par db.py et demo.py, sans dépendance externe)."""
SCHEMA = {
    "transactions": ["id", "date", "isin", "type", "quantite", "prix", "frais"],
    "dividendes": ["id", "date", "isin", "montant"],
    "versements": ["id", "date", "type", "montant", "libelle"],
    "secteurs": ["isin", "secteur"],
    "tickers": ["isin", "ticker", "nom", "dernier_prix", "dernier_prix_at", "url"],
    "snapshots": ["date", "valeur", "apports"],
    "watchlist": ["isin", "note", "url", "ajoute_le"],
    "scenarios": ["id", "nom", "versement", "cree_le"],
    "scenario_trades": ["id", "scenario_id", "isin", "type", "quantite", "prix", "cree_le"],
    "analyses_ia": ["id", "cree_le", "modele", "empreinte", "resultat"],
    "analyses_scen": ["id", "scenario_id", "cree_le", "modele", "empreinte", "resultat"],
    "chat_log": ["id", "cree_le"],
}
ORDRE = {
    "transactions": ["date", "id"], "dividendes": ["date", "id"], "versements": ["date", "id"],
    "snapshots": ["date"], "watchlist": ["ajoute_le"], "scenarios": ["id"],
    "scenario_trades": ["id"], "analyses_ia": ["id"], "analyses_scen": ["scenario_id", "id"], "chat_log": ["id"],
}
NUMERIQUES = ("quantite", "prix", "frais", "montant", "dernier_prix", "valeur", "apports", "versement")
