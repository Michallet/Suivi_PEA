# Migration Suivi PEA : état après l'étape 1

Branche : `refonte/socle-2026-10` (main non touchée). Ce fichier remplace une relecture complète du code pour
l'étape 2 : le lire en premier.

## 1. Décisions prises

| Sujet | Décision |
|---|---|
| Connexion | **Mots de passe Streamlit** (choix du propriétaire), pas d'OIDC Google. `AUTH_MODE = "password"` est le seul adaptateur. Mots de passe hachés (scrypt, `password_hash`), `password` en clair encore accepté. **Conséquence** : pas de persistance après rechargement (S3 non résolu, limite assumée). |
| Compte démo | Lecture seule en base ; ses modifications vivent dans la session du visiteur (`repo`, clé `_pea_demo_tables`). Bandeau réécrit : seul changement visible. Fait dès l'étape 1, car le correctif (S2, gravité haute) se loge naturellement dans `repo`. |
| Tables additives | `marche_cache` (public), `usage_ia` (quotas), index, fonction `pea_charger_compte`. Aucune table existante modifiée. |
| Client Supabase | **Conservé.** Mesure : import de `supabase` 0,31 s et environ 50 Mo, une fois par processus. Le gain ne justifie pas le risque d'un client maison. |
| Versions | Épinglées sur la combinaison testée : Streamlit 1.66.1, pandas 3.1.0, numpy 2.5.4, plotly 7.1.0, yfinance 1.7.0, supabase 2.33.0, requests 2.34.2 (Python 3.13). |
| Conversion numérique | `pea.domain.nombres.nombre` remplace `_positif`, `_val`, `num`, `_nombre`. Seul écart : une valeur infinie devient « absente » (avant : acceptée par `_nombre`). Aucun cas réel connu. |
| Quotas | Un appel IA raté ne consomme toujours pas de quota (comptage après succès), comme avant. Les suggestions de concurrent faites à la création d'un titre sont désormais comptées. |
| Fondamentaux | Yahoo n'offre pas d'appel groupé pour `info` : un appel par titre, en arrière-plan, partagé 6 h via `marche_cache`. |

## 2. Constats de l'audit : vérification

Tous les constats ont été vérifiés, sauf trois :
- **S7 (devcontainer) : inexact.** Le dépôt ne contient ni `.devcontainer` ni `.streamlit`. Le fichier `config.toml` a été créé.
- **S9** : il y avait aussi un `except: pass` dans `historique_cloture` / la maintenance. Tous ont été retirés, et un test interdit d'en réintroduire.
- **C2** : `concurrents.py` importait `llm` et `import_ecran`. Il est maintenant découpé en une partie pure (domaine) et une partie IA (services).

| ID | Statut |
|---|---|
| S1 `.gitignore` | Fait. Rotation des clés recommandée si un `secrets.toml` a déjà été poussé. |
| S2 démo partagée | Fait (lecture seule, test AppTest « aucune écriture »). |
| S3 session perdue au rechargement | **Non résolu** : conséquence du choix des mots de passe. |
| S4 mots de passe | Fait : scrypt, blocage par (identifiant, session), ralentissement par identifiant (5 s au plus). |
| S5 isolation | Fait : porte unique `repo`, tests d'isolation multi-comptes, test d'architecture (aucun autre module ne touche Supabase). RLS + JWT : non fait (option). |
| S6 quotas | Fait : `usage_ia`, plafond global, 6/min par compte, 20/min au total, sémaphore 3, pause commune après un 429 (`Retry-After`). |
| S7 config | Fait : XSRF, upload 20 Mo, erreurs sans trace, barre d'outils minimale, statistiques désactivées. |
| S8 textes externes | Fait : `echapper_markdown` (noms, pseudos, notes), `nettoyer_sortie_ia` (liens, images, HTML), `sur_pour_graphique` (légendes). |
| S9 erreurs muettes | Fait : journalisation (type d'erreur uniquement). |
| S10 versions | Fait. |
| P1 onglets | Fait (`on_change="rerun"`, `key="onglet"`, `tab.open`). |
| P2 attente Yahoo | Fait : arrière-plan, attente ≤ 4 s, fragment `surveiller_marche` qui relance l'affichage. |
| P3 🔄 global | Fait : invalide le compte courant ; Yahoo seulement si le cours a plus de 60 s. |
| P4 Yahoo | Fait : `yf.download` groupé, L1 + L2, cache négatif, recul exponentiel. |
| P5 Supabase | Fait : RPC en un aller-retour, colonnes ciblées, `analyses_*` bornées, `chat_log` plus relue, `count` daté, lots, index. |
| P6 écritures de suivi | Fait : `snapshots` ≤ 1/15 min, `tickers.dernier_prix` ≤ 1/30 min par compte. |
| P7 contexte | **Étape 2.** |
| P8 Gemini | Fait : sémaphore, délais 45 à 90 s (au lieu de 60 à 120 s), messages clairs. |
| P9 maintenance | Reconstitution : un téléchargement groupé. Exports CSV : inchangés (servis par le cache mémoire). |
| C1 à C7 | C2, C3, C4, C5 (conversions, formateurs) et C7 : faits. C1, C5 (bloc IA unique, quota unique dans l'UI) et C6 : **étape 2**. |

## 3. Mesures avant/après

Faux Supabase et faux Yahoo qui comptent les appels (`python -m tests.mesures`, fichiers `docs/mesures_avant.json`
et `docs/mesures_apres.json`). Les comptes sont fictifs (3 comptes, 5 titres).

| Situation | Avant (Supabase / Yahoo) | Après | Budget |
|---|---|---|---|
| Première session à froid | 16 / 11 | 6 / 6 (1 groupé + 5 `info`) | ≤ 2 lectures Supabase, 1 Yahoo groupé |
| Rerun complet, caches chauds | 1 / 0 | 1 / 0 | ≤ 1 / 0 ✅ |
| Interaction sur un widget | 0 / 0 | 0 / 0 | 0 ✅ |
| Clic 🔄 par un compte | 13 / 10 | 1 / 0 | — |
| Autre compte juste après ce clic | 16 / 0 | 3 / 0 | — |
| 10 sessions (3 comptes) | 49 / 11 | 12 / 6 (1 groupé) | 1 groupé ✅ |
| Mémoire max du processus de test | 279 Mo | 204 Mo | < 1 Go ✅ |

Écarts au budget à froid :
- **Supabase** : 1 RPC + 1 lecture `marche_cache` + 1 comptage de quota. Les écritures (cache marché, dernier prix) ont lieu après l'affichage.
- **Yahoo** : les 5 `info` (fondamentaux) n'existent pas en version groupée. Ils sont partagés 6 h via `marche_cache` : 0 appel dès qu'un compte les a chargés.

## 4. API des nouveaux modules

- `pea.config` : constantes ; `secret`, `secret_bool`, `secret_entier`, `comptes()`, `est_demo(uid)`, `cle_gemini()`, `modele_gemini()`, `quota_ia_global()`, `debug_perf()`, `definir_secrets_pour_tests`.
- `pea.domain` (pur) :
  - `calculs` : inchangé, sauf `formater_gros_nombre`, déplacé dans `formats`.
  - `technique` : inchangé.
  - `import_ecran` : utilise `nombres.nombre`.
  - `concurrents` : `construire_contexte`, `normaliser_candidats`, `choisir_concurrent`, `preparer_concurrent`, `lignes_comparaison`.
  - `formats` : `fmt`, `pastille`, `formater_gros_nombre`, `sans_parentheses`, `court`, `cellule`, `url_google_actualites`, `lien_actualites`.
  - `fondamentaux` : `GRANDEURS`, `RATIOS_POSITIFS`, `lignes_fondamentaux`, `est_etf`, `valeur_grandeur`.
  - `nombres` : `nombre`, `positif`.
  - `textes` : `echapper_markdown`, `nettoyer_sortie_ia`, `sur_pour_graphique`.
  - `erreurs` : `ErreurIA`.
- `pea.data.repo` :
  - Session et cache : `initialiser`, `utilisateur_actif`, `est_demo`, `lire(table)` (renvoie une copie), `precharger(tables)`, `invalider(table)`, `invalider_compte()`.
  - Écritures : `inserer`, `inserer_lot`, `modifier`, `supprimer`, `supprimer_plusieurs`, `upsert`, `appliquer_modifs`.
  - Comptages et tables : `compter`, `compter_global`, `table_disponible`.
  - Cache marché partagé : `marche_lire`, `marche_ecrire`.
  - Partage : `enregistrer_partage`, `partages_bruts`, `PSEUDO_MAX`.
  - Tests : `definir_client`, `definir_contexte`, `Contexte`.
- `pea.data.marche` :
  - Cours et fondamentaux : `cours_batch(tickers, attente)`, qui renvoie `{prix, prev, age_s}` et un horodatage ; `fondamentaux_batch` ; `ohlc_batch` ; `prechauffer` ; `actualiser_cours` ; `rafraichissement_en_cours`.
  - Historiques : `historique_cloture`, `historiques_groupes`.
  - Résolution : `chercher_ticker`, `valider_ticker`, `lire_cours`.
  - Tests : `definir_yahoo`.
- `pea.services` :
  - `auth` : connexion et session (`connecte`, `utilisateur`, `est_demo`, `formulaire_connexion`, `deconnecter`, `vider_etat_compte`) ; mots de passe (`hacher`, `verifier_identifiants`).
  - `quotas` : `verifier(nature)`, à appeler avant l'appel ; `enregistrer(nature)`, après un succès ; `limite_atteinte`, `message_limite`, `restant`, `QuotaDepasse`.
  - `ia` : façade de l'ancien `llm`, avec en plus `suggerer` et `demander_candidats`.
  - `partage.performances_partagees()`.
  - `suivi.memoriser(...)`.
- Outil : `python -m pea.outils.hacher_mot_de_passe`.

## 5. SQL à exécuter (dans cet ordre)

1. `sql/schema.sql` (idempotent, déjà en place sur la base existante).
2. `sql/migrations/001_cache_marche_quotas.sql` (additive, rejouable).

Sans l'étape 2, l'application fonctionne avec des replis :
- **Cache** : en mémoire seulement.
- **Quotas** : comptés à partir des anciennes tables ou en mémoire.
- **Chargement** : lectures parallèles.

## 6. Reste à faire (étape 2)

1. **Contexte portefeuille (P7)** : supprimer les variables globales d'`app.py` (positions, cours, synthèse, `tmap`, `fonds`).
2. **`ui/pages/`** :
   - Découper `onglet_projet`, `onglet_saisie` et `import_captures` (fonctions de plus de 60 lignes).
   - Écrire un seul bloc IA, qui fusionne `bloc_ia` et `bloc_ia_scenario`.
   - Construire un seul dictionnaire PER par ISIN.
3. **Logique de gestion encore dans `app.py`** : déplacer `enregistrer_ticker`, `suggerer_a_la_creation`, `concurrent_de`, `enregistrer_concurrent` et `resoudre_concurrent` vers `services/titres.py`.
4. **Formulaire de connexion** : le sortir de `services/auth.py` vers l'interface.
5. **Clés de session (C6)** : passer à des espaces de noms. Les préfixes `PREFIXES_ETAT_COMPTE` restent fragiles (`"imp"`).
6. **`st.rerun(scope="fragment")`** : l'utiliser là où seule une zone change. Écritures en lot dans l'écran de correction (déjà en lot dans `repo.appliquer_modifs`).
7. **Exports CSV de la maintenance** : en différé (`data` appelable, Streamlit 1.66), après un test en conditions réelles.
8. **Tests AppTest des actions** : saisie d'une transaction, import, scénario, watchlist, en démo et sur un compte privé.
9. **Nettoyage final** :
   - Réécrire le README.
   - Fournir la liste de bascule et la marche arrière.

## 7. Risques restants

- **Non testé en réel** : la base Supabase, Yahoo et Gemini n'ont pas été appelés depuis ce bac à sable (réseau fermé). La fonction SQL `pea_charger_compte`, le format de `yf.download` 1.7 sur de vrais titres et l'en-tête `Retry-After` de Gemini sont couverts par des faux seulement. À vérifier au premier déploiement :
  - le compte personnel s'affiche avec les mêmes chiffres qu'avant ;
  - avec `DEBUG_PERF = true`, les temps affichés sont cohérents ;
  - une seconde visite n'appelle plus Yahoo.
- **Rendu** : les onglets paresseux (Streamlit ≥ 1.59) changent le comportement du changement d'onglet (un rerun). Le CSS cible des `data-testid` qui peuvent varier.
- **pandas 3** : le code d'origine a été écrit pour pandas 2. Les tests de caractérisation passent en pandas 3.1, mais sur des données fictives.
- **Démo** : une session démo très longue garde ses tables modifiées en mémoire serveur (taille bornée par l'usage).
- **Session** : sans OIDC, un onglet mobile mis en veille revient sur la démo.
