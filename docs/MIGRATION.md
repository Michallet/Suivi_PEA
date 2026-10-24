# Migration Suivi PEA : bilan (étapes 1 et 2)

Branche : `refonte/socle-2026-10` (`main` non touchée). Étape 1 : socle (données, services, correctifs sûrs).
Étape 2 : application découpée en pages, contexte portefeuille, `app.py` mince, tests et bascule.

## 1. Décisions prises

| Sujet | Décision |
|---|---|
| Connexion | **Mots de passe Streamlit, en clair dans les secrets** (choix du propriétaire, qui gère lui-même les comptes `[users.*]`). Ni OIDC Google (jalon 2.4 non réalisé, par choix), ni hachage (outil retiré). Durcissement conservé : blocage par (identifiant, session) après 8 échecs, ralentissement par identifiant (5 s au plus), comparaison en temps constant. **Conséquence** : un rechargement de page oblige à se reconnecter (S3 non résolu, limite assumée). |
| Compte démo | Lecture seule en base ; ses modifications vivent dans la session du visiteur. Bandeau réécrit : seul changement visible de toute la refonte. |
| Tables additives | `marche_cache` (public), `usage_ia` (quotas), index, fonction `pea_charger_compte`. Aucune table existante modifiée. |
| Client Supabase | Conservé (import 0,31 s et environ 50 Mo, une fois par processus). |
| Versions | Épinglées : Streamlit 1.66.1, pandas 3.1.0, numpy 2.5.4, plotly 7.1.0, yfinance 1.7.0, supabase 2.33.0, requests 2.34.2 (Python 3.13). |
| Contexte | `Portefeuille` construit une fois par rerun, mémoïsé dans la session par (compte, `repo.signature`, horodatage marché, fondamentaux connus). |
| Clés de session | Espace de noms `c.` (`pea.ui.etat.k`) ; purge unique à la connexion et à la déconnexion. Les conversations du chat ne portent plus l'identifiant du compte dans leur clé (elles sont purgées). |
| Relances | `st.rerun()` complet après toute écriture (le contexte doit être reconstruit) ; `relancer_zone()` (`scope="fragment"`) quand seule la zone change : chat, suggestion de concurrent affichée. |
| Écritures en lot | Import (`inserer_lot`), correction (`appliquer_modifs`) et désormais secteurs (`upsert` + `supprimer_plusieurs`). |
| Messages d'erreur | Échec d'enregistrement du partage : seul le type d'erreur est affiché (comme pour la base). |

## 2. Constats de l'audit

| ID | Statut |
|---|---|
| S1 `.gitignore` | Fait. Rotation des clés recommandée si un `secrets.toml` a déjà été poussé. |
| S2 démo partagée | Fait (lecture seule ; tests « aucune écriture » et « saisie en démo reste dans la session »). |
| S3 session perdue au rechargement | **Non résolu** : conséquence du choix des mots de passe. |
| S4 mots de passe | Blocage par session et ralentissement : faits. Hachage : abandonné par choix du propriétaire. |
| S5 isolation | Fait : porte unique `repo`, tests d'isolation, comptes successifs dans la même session sans fuite. RLS + JWT : non fait (option). |
| S6 quotas | Fait : `usage_ia`, plafond global, limiteurs, sémaphore, pause commune après un 429. |
| S7 config | Fait (le constat sur `.devcontainer` était inexact : le dossier n'existait pas). |
| S8 textes externes | Fait : échappement Markdown, nettoyage des sorties d'IA, légendes de graphiques. |
| S9, S10 | Faits. |
| P1 à P6, P8, P9 | Faits (étape 1). |
| P7 contexte | **Fait** (étape 2). |
| C1 fonctions longues | **Fait** : aucune fonction de plus de 60 lignes (test). |
| C2 à C5 | Faits ; bloc IA unique (`bloc_analyse` + `Cible`), calcul de quota unique (`etat_ia`, `legende_ia`), dictionnaire PER unique (`Portefeuille.per_par_isin`). |
| C6 clés de session | **Fait** (espace `c.` + test qui refuse les clés en dur). |
| C7 | Fait. |

## 3. Mesures

Faux Supabase et faux Yahoo qui comptent les appels (`python -m tests.mesures <fichier>`). Comptes fictifs (3 comptes, 5 titres).
Fichiers : `docs/mesures_avant.json`, `docs/mesures_apres.json` (étape 1), `docs/mesures_etape2.json`.

| Situation (Supabase / Yahoo) | Avant | Étape 1 | Étape 2 | Budget |
|---|---|---|---|---|
| Première session à froid | 16 / 11 | 6 / 6 | 5 / 6 (lectures : 1 RPC + 1 `marche_cache`) | ≤ 2 lectures ✅ ; 1 Yahoo groupé (+ 5 `info`, voir ci-dessous) |
| Rerun complet, caches chauds | 1 / 0 · 0,46 s | 1 / 0 · 0,26 s | 1 / 0 · 0,13 s | ≤ 1 / 0, < 1 s ✅ |
| Interaction sur un widget | 0 / 0 | 0 / 0 | 0 / 0 | 0 ✅ |
| Clic 🔄 par un compte | 13 / 10 | 1 / 0 | 1 / 0 | — |
| Autre compte juste après | 16 / 0 | 3 / 0 | 2 / 0 | — |
| 10 sessions (3 comptes) | 49 / 11 | 12 / 6 | 10 / 6 (1 groupé) | 1 groupé ✅ |
| Mémoire max du processus de test | 279 Mo | 204 Mo | 190 Mo | < 1 Go ✅ |

- Les 5 appels `info` (fondamentaux) n'existent pas en version groupée chez Yahoo ; ils sont partagés 6 h via `marche_cache`.
- Le rerun à chaud relit `tickers` une fois : c'est la conséquence de l'écriture du dernier prix au passage précédent (au plus toutes les 30 min).
- Sans clé Gemini, plus aucune lecture du compteur de quota (étape 1 : 1 lecture par session).

## 4. Parité

- `tests/test_caracterisation.py` : sorties des fonctions pures identiques à la référence d'avant refonte.
- `tests/test_rendu.py` : pour 3 comptes (2 privés, démo), les 5 onglets et les 7 actions de Saisie affichent exactement
  les mêmes éléments (types et textes, dans l'ordre) que l'`app.py` de l'étape 1. Référence : `tests/golden/rendu.json`.
- `tests/test_app.py` : chiffres de la synthèse identiques à ceux de l'application d'origine.

## 5. API des modules

- `pea.config` : constantes, `PARIS`, `maintenant()`, `PREFIXE_COMPTE` ; `secret`, `comptes()`, `est_demo(uid)`, `cle_gemini()`, `modele_gemini()`, `debug_perf()`.
- `pea.domain` (pur) : `calculs`, `technique`, `import_ecran`, `concurrents`, `formats`, `fondamentaux`, `nombres`, `textes`, `erreurs`.
- `pea.data.repo` : `lire`, `precharger`, `signature`, `inserer(_lot)`, `modifier`, `supprimer(_plusieurs)`, `upsert`, `appliquer_modifs`, `invalider(_compte)`, `marche_lire/ecrire`, `enregistrer_partage`, `partages_bruts`.
- `pea.data.marche` : `cours_batch`, `fondamentaux_batch`, `ohlc_batch`, `prechauffer`, `actualiser_cours`, `rafraichissement_en_cours`, `historique_cloture`, `historiques_groupes`, `chercher_ticker`, `valider_ticker`.
- `pea.services` :
  - `portefeuille` : `construire(session, actualiser, jalon) -> Portefeuille`, `BaseIndisponible`, `CLE_ACTUALISER`. `Portefeuille` : données (`trans`, `div`, `vers`, `snaps`, `wl`, `scen`, `scen_tr`, `analyses*`, `tmap`), calculs (`positions`, `ventes`, `flux`, `pos`, `synthese`, `cash`), marché (`cours`, `horodatage`, `fonds`) et méthodes (`nom_de`, `ticker_de`, `secteur_de`, `fondamentaux`, `per_par_isin`, `enrichir`, `prix_courant`, `ordre_isins`, `concurrent_de`, `derniere_analyse`, `scenario`, `memoriser_suivi`).
  - `titres` : `enregistrer_ticker`, `resoudre_ticker`, `resoudre_concurrent`, `enregistrer_concurrent`, `preparer_concurrent`, `proposer_concurrent`, `suggerer_a_la_creation`, `ia_concurrent_disponible`.
  - `auth` : `connecte`, `utilisateur`, `est_demo`, `tenter_connexion`, `deconnecter`, `vider_etat_compte`, `connecter_demo_par_defaut`.
  - `quotas`, `ia`, `partage`, `suivi` : inchangés depuis l'étape 1.
- `pea.ui` : `entete` (`porte`, `entete`), `etat` (`k`, `flash`, `afficher_flash`, `relancer_zone`), `composants/` (`cartes`, `graphiques`, `ia`, `communs`), `pages/` (`afficher(pf)` par onglet ; `saisie/` une sous-page par action).

## 6. SQL à exécuter (dans cet ordre)

1. `sql/schema.sql` (idempotent, déjà en place sur la base existante).
2. `sql/migrations/001_cache_marche_quotas.sql` (additive, rejouable).

Sans la migration 001, l'application fonctionne avec des replis (cache en mémoire, quotas en mémoire ou sur les
anciennes tables, lectures parallèles au lieu de la fonction SQL).

## 7. Bascule et marche arrière

**Bascule**, dans cet ordre :
1. **Sauvegarde** : dans l'app actuelle, Saisie › Maintenance › télécharger les 4 CSV.
2. **Tag de retour** : `git tag avant-refonte main && git push origin avant-refonte`.
3. **SQL** : exécuter la migration 001 dans le SQL Editor de Supabase.
4. **Secrets** : rien d'obligatoire. Les blocs `[users.*]` avec `password` restent valables ; facultatif : `DEBUG_PERF = true` pour le premier contrôle.
5. **Déploiement de la branche** : pousser `refonte/socle-2026-10`, puis sur Streamlit Community Cloud créer une
   seconde app sur cette branche (mêmes secrets), avec Python 3.13.
6. **Test** : se connecter à son compte, vérifier que les chiffres sont identiques à ceux de l'app actuelle, ouvrir
   chaque onglet, faire une saisie puis la supprimer (Corriger / supprimer) ; vérifier que la démo n'écrit rien.
7. **Fusion** dans `main` (l'app principale se redéploie seule), puis supprimer l'app de test et retirer `DEBUG_PERF`.
8. **Rotation des clés** (`service_role` Supabase, Gemini) si un `secrets.toml` a un jour été poussé sur GitHub.

**Marche arrière** : `git revert -m 1 <commit de fusion>` puis pousser `main` (l'app se redéploie sur l'ancienne
version) ; en dernier recours, remettre `main` sur le tag `avant-refonte`. La migration 001 n'a rien modifié d'existant : elle peut rester
en place ; l'ancienne version l'ignore.

## 8. Reste à faire (facultatif)

- Exports CSV de la maintenance en différé (`data` appelable) : non fait, à tester d'abord en conditions réelles.
- RLS + JWT par compte (défense en profondeur, aujourd'hui assurée par `repo` et la clé `service_role` côté serveur).
- OIDC Google (`st.login`) si la reconnexion après rechargement devient gênante : l'interrupteur `AUTH_MODE` est en place.

## 9. Risques restants

- **Non testé en réel** : Supabase, Yahoo et Gemini n'ont pas été appelés depuis le bac à sable (réseau fermé). La
  fonction SQL `pea_charger_compte`, le format de `yf.download` sur de vrais titres et l'en-tête `Retry-After` de
  Gemini sont couverts par des faux seulement : c'est l'objet de l'étape 6 de la bascule.
- **Fragments** : un fragment relancé seul garde le contexte du dernier rerun complet (comme les variables globales
  avant) ; toute écriture doit donc faire un `st.rerun()` complet.
- **Rendu** : le CSS cible des `data-testid` de Streamlit qui peuvent changer d'une version à l'autre.
- **pandas 3** : code d'origine écrit pour pandas 2 ; tests verts en 3.1 sur données fictives.
- **Session** : sans OIDC, un onglet mobile mis en veille revient sur la démo.
