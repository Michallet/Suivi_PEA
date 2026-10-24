"""Erreurs métier partagées entre couches (le domaine ne dépend d'aucune couche supérieure)."""


class ErreurIA(Exception):
    """Erreur affichable telle quelle à l'utilisateur (ne contient jamais la clé API)."""
