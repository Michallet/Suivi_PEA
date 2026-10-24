"""Affiche l'empreinte scrypt d'un mot de passe, à coller dans les secrets : password_hash = "…".

    python -m pea.outils.hacher_mot_de_passe

Le mot de passe est demandé sans écho et n'est ni affiché ni enregistré.
"""
import getpass

from pea.services.auth import hacher

if __name__ == "__main__":
    mdp = getpass.getpass("Mot de passe : ")
    if mdp != getpass.getpass("Confirmation : "):
        raise SystemExit("Les deux saisies diffèrent.")
    if len(mdp) < 12:
        raise SystemExit("12 caractères minimum.")
    print(f'password_hash = "{hacher(mdp)}"')
