# Activation du mode multi-utilisateur

## 1. Sauvegarde et migration Supabase

Avant toute modification, exporter/sauvegarder la base Supabase existante.

Dans le SQL Editor Supabase, exécuter **`schema.sql`**. Le script ajoute `user_id` aux tables métier, attribue les données existantes à `theo` et adapte les clés (par utilisateur). Il est conçu pour être relancé sans réattribuer les données déjà affectées.

Ensuite, exécuter **`seed_demo.sql` une seule fois** pour créer le jeu de données fictif du compte `demo`. Il n'écrase pas un compte démo ayant déjà des transactions.

## 2. Secrets Streamlit

Copier `.streamlit/secrets.toml.example` dans `.streamlit/secrets.toml` en local, ou coller son contenu dans Streamlit Community Cloud > Settings > Secrets. Remplacer les valeurs Supabase et le mot de passe de `theo` :

```toml
SUPABASE_URL = "https://votre-projet.supabase.co"
SUPABASE_KEY = "votre_clé_service_role"
GEMINI_API_KEY = "" # optionnel

[users.demo]
password = "demo"
demo = true

[users.theo]
password = "REMPLACER_PAR_UN_MOT_DE_PASSE_LONG_ET_UNIQUE"
demo = false
```

Pour ajouter un compte, créer un bloc `[users.identifiant]` avec un mot de passe unique et `demo = false`. Les mots de passe restent dans les secrets Streamlit, pas dans Supabase ni dans le dépôt Git.

## 3. Comportement

- Les champs de connexion sont préremplis `demo` / `demo`; cliquer sur **Entrer** ouvre le compte démo.
- `demo` et `theo` utilisent le même schéma Supabase, mais `db.py` applique systématiquement le filtre `user_id` pour chaque lecture et écriture. Le cache est séparé par compte.
- Toutes les fonctions sont accessibles sur le compte démo sauf analyse IA, analyse de scénario IA et chatbot IA.
- **Le compte démo est partagé et modifiable** : transactions, dividendes, versements, watchlist et scénarios ajoutés ou supprimés sont persistants et visibles par les prochains visiteurs. Ne jamais y mettre de données personnelles.
- Les enregistrements existants sont migrés vers `theo`, pas vers `demo`.

## 4. Vérifications locales

```bash
pip install -r requirements.txt
pytest -q
streamlit run app.py
```

