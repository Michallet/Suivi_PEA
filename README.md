# 📈 Suivi PEA

Application **Streamlit mobile-first et adaptative** (téléphone, tablette, PC) de suivi d'un PEA français (actions et ETF européens) : positions, PRM,
plus-values, cash, historique, scénarios « et si… », watchlist, indicateurs techniques, analyse IA (Gemini).

| | |
|---|---|
| Interface | Streamlit (`layout="wide"` + CSS de `style.py` : plein écran sur mobile, contenu centré (1 320 px max) et cartes en grille sur tablette/PC ; cartes plutôt que tableaux, pas de zoom tactile) |
| Base | Supabase (PostgreSQL), clé `service_role` côté serveur uniquement |
| Cours et fondamentaux | Yahoo Finance (`yfinance`) |
| IA (facultative) | API Gemini, appels HTTP directs (`requests`) |
| Hébergement | Streamlit Community Cloud, branche `main` — **tout est gratuit** |
| Langue | français (code, commentaires, commits) |

> Ce fichier sert à la fois de présentation et de **contexte de reprise pour une IA** : lisez-le en entier avant
> de modifier le code.

---

## Règles non négociables

- **100 % gratuit** : aucune dépendance ni service payant.
- **Mobile-first, adaptatif** : cartes, pas de tableaux larges, `fixedrange` sur les graphiques Plotly. Toute mise en page
  « grand écran » (colonnes, grilles) doit se replier en une colonne sur téléphone.
- **Aucun secret dans le dépôt** (tout passe par `st.secrets`) et **aucune donnée réelle** : le dépôt est public.
  Les tests et exemples n'utilisent que des données fictives.
- **Cloisonnement par compte** : toute lecture/écriture Supabase est filtrée par `user_id` dans `pea/data/repo.py`.
  Le compte `demo` ne lit jamais les données d'un autre compte et **n'appelle jamais l'IA** (garde côté UI *et* serveur).
  **Seule exception** : la performance partagée (`pea/services/partage.py`) (voir « Partage de la performance »).
- **Ne pas modifier les règles métier** ci-dessous sans demande explicite.
- Les fichiers `.py` du dépôt vont **ensemble** : un déploiement partiel (ex. `app.py` sans `pea/`) plante.

---

## Architecture

Dépendances à sens unique : `domain` ← `data` ← `services` ← `ui` (vérifiées par `tests/test_architecture.py`).
Historique de la refonte, décisions et mesures : **docs/MIGRATION.md**.

| Fichier | Rôle |
|---|---|
| `app.py` | Assemblage seulement (< 100 lignes) : page, porte de connexion, contexte du compte, 5 onglets paresseux |
| `pea/config.py` | Constantes (quotas, seuils, durées de cache, indices), `maintenant()`, lecture typée des secrets |
| `pea/domain/` | Pur, testé, sans Streamlit ni réseau : `calculs`, `technique`, `import_ecran`, `concurrents`, `formats`, `fondamentaux`, `nombres`, `textes` |
| `pea/data/repo.py` | **Seule** porte vers Supabase : `user_id` forcé, cache par compte, chargement en un aller-retour, démo en lecture seule |
| `pea/data/marche.py` | Yahoo Finance : téléchargement groupé, cache mémoire + `marche_cache` partagé, arrière-plan, recul après 429 |
| `pea/data/schema.py` | Colonnes métier de chaque table (cohérence avec le SQL vérifiée par les tests) |
| `pea/services/portefeuille.py` | **Contexte du compte** (`Portefeuille`) : données, cours, positions, synthèse, fondamentaux ; construit une fois par rerun, mémoïsé |
| `pea/services/` (suite) | `auth` (mots de passe des secrets), `titres` (création de ticker, concurrent), `quotas` (IA), `ia/` (prompts, contexte, validation, client HTTP), `partage`, `suivi` |
| `pea/ui/pages/` | Un module par onglet : `portefeuille`, `historique`, `projet`, `watchlist`, `saisie/` (une sous-page par action) |
| `pea/ui/composants/` | `cartes` (lignes, concurrent), `graphiques` (Plotly), `ia` (bloc d'analyse et chat uniques), `communs` |
| `pea/ui/` (suite) | `entete` (connexion, 🔄, 🔒, bandeau démo), `etat` (clés de session `c.…`, messages), `style` (CSS, palette) |
| `prompts.md` | Prompts éditables (sections `## analyse`, `## scenario`, `## chat`, `## capture`, `## concurrent`) |
| `sql/schema.sql`, `sql/migrations/` | Schéma Supabase et migrations additives, idempotentes |
| `sql/seed_demo.sql` | Portefeuille fictif du compte `demo` (à exécuter **une seule fois**) |
| `tests/` | Caractérisation des règles métier, parité du rendu, isolation des comptes, AppTest multi-comptes, mesures |

**Ordre de lecture conseillé** : `pea/domain/calculs.py` → `pea/data/repo.py` → `pea/services/portefeuille.py` →
`app.py` → la page concernée dans `pea/ui/pages/`.

**Ajouter un écran ou une action** : une fonction `afficher(pf)` dans `pea/ui/pages/` (ou `saisie/`), qui reçoit le
contexte `pf` et n'écrit qu'à travers `repo` ; clés de widgets via `etat.k(...)` ; après une écriture, `flash(...)` puis
`st.rerun()` (le contexte est reconstruit) ; si rien n'est écrit, `etat.relancer_zone()` ne relance que le fragment.

**Tables** : `transactions`, `dividendes`, `versements`, `secteurs`, `tickers` (ISIN → ticker, dernier prix, concurrent),
`snapshots` (valeur et apports par jour), `watchlist`, `scenarios`, `scenario_trades`, `analyses_ia`, `analyses_scen`,
`chat_log` (ancien compteur du chat), `usage_ia` (compteurs de quotas), `partage` (choix de partage de la performance + pseudo).
Toutes portent un `user_id`, sauf `marche_cache` (données publiques de Yahoo partagées entre comptes).

---

## Règles métier

- **PRM** = coût moyen pondéré, frais d'achat inclus. Une vente réduit le coût au PRM ; plus-value réalisée =
  produit net − PRM × quantité. Une vente supérieure à la quantité détenue est refusée.
- **Cash** = versements − retraits − achats + ventes + dividendes (frais déduits).
- **Apports nets** = versements − retraits. Une `PV_ANTERIEURE` (plus-value antérieure réinvestie) alimente le cash
  mais **n'est pas un apport**.
- **Plafond PEA** : 150 000 € de versements cumulés. **Alerte de concentration** : une ligne > 25 % des titres.
- **Historique** : un point (`snapshots`) est enregistré lors des visites en semaine (au plus tous les quarts d'heure) ; reconstituable depuis les
  transactions (Saisie › Maintenance). Performance vs indice en **TWR** base 100 (MSCI World CW8, CAC 40, Euro Stoxx 50).
- **Statut d'un cours** : `live` > `obsolète` (dernier prix connu en base) > `estimé` (prix de revient).
- **Scénarios (onglet Projet)** : opérations fictives au dernier cours, rejouées sur le journal réel ; le réel n'est
  jamais modifié.
- **Liens** : chaque carte porte un lien Google Actualités calculé à l'affichage (rien n'est stocké en base).

### Partage de la performance (Historique)
Case sous le 2ᵉ graphique, **décochée par défaut** (table `partage` : `partage`, `pseudo`, migration dans `schema.sql`).
Le graphique « Performance vs indice » ajoute, en plus de l'indice, la courbe TWR des **autres comptes** ayant coché la case
(sélecteur d'utilisateurs, tous affichés par défaut) — indépendamment du choix de l'utilisateur lui-même de partager.
- Seul l'**indice TWR base 100** quitte `pea/services/partage.py` : jamais valeur, apports ni positions.
- Exclus : compte `demo` (ne voit rien, ne partage rien), soi-même, comptes absents des secrets. Pseudo vide = « Anonyme » ;
  pseudos identiques suffixés `(2)`… Cache 2 min. Décocher coupe le partage dès l'expiration du cache.
- Courbes alignées sur la période choisie ; un ami dont l'historique commence plus tard démarre à 100 à son 1er point.

### Matrice de notes (Portefeuille, sous les graphiques)
Nuage de points croisant **deux grandeurs au choix** (PER, PER prévisionnel, EV/EBITDA, capitalisation/CA, marge nette,
bénéfice net, EBITDA, CA, capitalisation ; défaut : bénéfice net × PER). Chaque grandeur est convertie en **note de 1 à
10 par rang, relative aux lignes affichées** (`calculs.note_relative`) : échelle toujours identique, sans souci de
négatifs ni d'échelle log.
- **10 = le meilleur** : PER, PER prévisionnel, EV/EBITDA et capitalisation/CA **bas = 10** ; marge, bénéfice, EBITDA, CA,
  capitalisation **hauts = 10**.
- **Valeur absente ou ≤ 0 pour un ratio de valorisation (société déficitaire) = note 1** ; les lignes renseignées sont alors
  réparties sur 2 → 10. Seuls les **ETF** (pas de fondamentaux) sont écartés.
- Case « Inclure la watchlist » (tout ou rien, décochée par défaut) ; taille = poids, couleur = performance, ◆ = watchlist.
  Séparation à 5,5 ; il faut au moins 3 actions. La phrase sous le graphique donne la règle chiffrée du portefeuille.
- Les notes sont **relatives** : ajouter ou retirer une ligne les fait bouger ; non comparables d'un portefeuille à l'autre.

### Indicateurs techniques (`pea/domain/technique.py`)
Sélecteur *Fondamentaux | Indicateurs techniques* dans Portefeuille, Projet et Watchlist ; les bougies (~1 an) ne
sont téléchargées que si la vue technique est choisie. Chaque indicateur a un score −1…+1 ; **note /10 = 5 + 5 ×
moyenne pondérée** (MM 40 %, RSI 20 %, stochastique 20 %, Bollinger 20 %) ; verdict ≥ 6 Acheter, ≤ 4 Vendre.
Filtre de tendance : en tendance nette, les oscillateurs contraires comptent pour moitié. Signal indicatif, pas un
conseil. Constantes réglables en tête du module.

### Concurrent (`pea/domain/concurrents.py`, IA : `pea/services/ia/concurrent.py`)
Un seul concurrent par action (pas par ETF), colonnes `tickers.concurrent_*`. Suggestion IA **une fois** à la création
d'un titre (hors import, maintenance, démo, ETF), puis sur demande ; on garde le premier candidat dont l'ISIN passe le
contrôle Luhn, est résolu par Yahoo **et** dont le nom ressemble au nom annoncé (garde-fou anti-ISIN halluciné).
Seuls nom, ISIN, secteur et capitalisation du titre partent chez Gemini. Comparaison : PER, PER prévisionnel,
EV/EBITDA, marges nette et EBITDA, capitalisation si les deux cotent en €.

### Import par captures (Saisie › Import par captures)
1 à 8 captures du courtier → Gemini (vision) lit nom / quantité / PRM / valeur → l'app calcule l'écart avec la base et
propose des achats/ventes modifiables ; **rien n'est écrit avant « ✅ Enregistrer »**.
- Résolution de l'ISIN, par ordre : ISIN lu à l'écran > nom proche d'un nom connu (ambigu = refusé) > même quantité
  **et** PRM (±0,5 %) qu'une position > ISIN proposé par l'IA (marqué « à vérifier »). Tout ISIN passe le contrôle Luhn.
- **Achat** : prix déduit de `(PRM courtier × Q courtier − coût en base) / Δ` pour que le PRM de l'app redevienne celui
  du courtier. **Vente** : cours actuel par défaut. Ligne détenue absente des captures ou sans ISIN : opération décochée.
- Alerte si valeur ÷ quantité s'écarte de >15 % du cours. « 🔎 Contrôler » rejoue le journal et liste les écarts restants.
- Le type d'image est vérifié sur les octets (PNG/JPEG/WebP). Les images ne sont ni stockées ni commitées.

---

## IA (Gemini) et confidentialité

- Analyse du portefeuille, analyse de scénario et chat : **poids en %**, secteurs, PER, performances — pas de montants
  en € de positions. **Exceptions** : l'import par captures envoie les **images** telles quelles (quantités et montants
  visibles ; l'UI le dit) ; le chat reçoit aussi les dividendes perçus par ligne.
- Palier gratuit : Google peut réutiliser les contenus envoyés. N'y envoyez rien de plus sensible.
- Quotas dans `pea/config.py` (source unique), comptés en base (`usage_ia`) : analyses 30/jour/compte, chat 100,
  imports par captures 30, suggestions de concurrent 30 ; plafond global de 300 appels/jour (secret
  `QUOTA_IA_GLOBAL_PAR_JOUR`), 6 appels/minute par compte, 3 appels simultanés. Les vraies limites sont celles de Google.
- Modèle par défaut `gemini-3.6-flash`, surchargeable par le secret `GEMINI_MODEL`.
- L'IA donne un avis sur la **structure** ; jamais d'ordre d'achat/vente, de prévision chiffrée ni de conseil fiscal.

---

## Installation

```bash
git clone https://github.com/Michallet/Suivi_PEA.git && cd Suivi_PEA
pip install -r requirements-dev.txt      # requirements.txt + pytest
cp secrets.toml.example .streamlit/secrets.toml   # puis éditer ; ce fichier est ignoré par Git
python -m pytest                          # tous les tests (données fictives, aucun réseau)
streamlit run app.py
```

`.streamlit/config.toml` est versionné (XSRF actif, upload ≤ 20 Mo, aucune trace d'erreur dans le navigateur) ;
`.streamlit/secrets.toml` ne l'est **jamais** (`.gitignore`).

**Secrets** (`.streamlit/secrets.toml` en local, *Settings › Secrets* sur Streamlit Cloud) : voir `secrets.toml.example`.
Chaque compte est un bloc `[users.identifiant]` avec son `password` (gérés à la main dans les secrets). Après 8 essais ratés, une **session** est bloquée 15 min pour cet identifiant (un tiers ne peut plus
bloquer le compte d'un autre) ; les essais répétés sur un identifiant sont aussi ralentis (5 s au plus).

**Connexion par défaut (mode démo)** : l'app s'ouvre sur le compte `demo` (`CONNEXION_DEMO_AUTO` dans
`pea/config.py`, surchargé par le secret `AUTO_CONNEXION_DEMO`). Le verrou 🔒 ou le bandeau « Mode démo » ouvre le
formulaire de connexion. La démo est **en lecture seule en base** : les modifications d'un visiteur restent dans sa
session. La session vit dans le navigateur : un rechargement de page oblige à se reconnecter (choix des mots de passe
Streamlit plutôt qu'un fournisseur OIDC).

**Base** : exécuter `sql/schema.sql` puis `sql/migrations/001_cache_marche_quotas.sql` dans le SQL Editor de Supabase
(idempotents, rejouables), puis `sql/seed_demo.sql` **une seule fois** pour le compte demo. Sans la migration 001,
l'application fonctionne (replis en mémoire) mais sans cache partagé ni chargement en un aller-retour.

**Vérification** : `python -m pytest` (≈ 150 tests, 20 s) ; `python -m tests.mesures docs/mesures.json` compte les
appels réseau avec des faux Supabase et Yahoo.

---

## Performance : ce qu'il faut savoir avant de toucher au code

- **Onglets paresseux** (`st.tabs(..., on_change="rerun", key="onglet")` + `tab.open`) : seul l'onglet ouvert s'exécute.
- **Contexte** (`pea/services/portefeuille.py`) : mémoïsé dans la session par (compte, signature des données,
  horodatage marché, fondamentaux connus). Un rerun à caches chauds ne relit ni ne recalcule rien.
- **Base** (`pea/data/repo.py`) : cache mémoire 2 min par (compte, table) ; une écriture n'invalide que sa table,
  🔄 que le compte courant. Démarrage : une fonction SQL renvoie tout le compte en un aller-retour.
- **Marché** (`pea/data/marche.py`) : cache par titre partagé entre comptes (cours 5 min, fondamentaux 6 h, bougies
  1 h), copié dans `marche_cache`. Les cours périmés sont retéléchargés en un seul appel groupé, en arrière-plan :
  la page attend au plus 4 s puis affiche le dernier cours connu et se met à jour dès l'arrivée des nouveaux.
- **Fragments** (`@st.fragment`) : Portefeuille (synthèse, cartes, graphiques), Historique, Projet, Watchlist, Saisie.
- Écritures de suivi (dernier prix, point du jour) **en fin de script**, limitées par compte (30 min / 15 min).
- Hors du code : mise en veille de Streamlit Community Cloud et pause du projet Supabase gratuit après inactivité.

## Pièges connus

- `tickers.ticker` est `NOT NULL` : pour modifier un titre, utiliser `repo.modifier(table, id, rec, cle="isin")`,
  pas un `upsert` partiel.
- Les fondamentaux sont indexés par **ticker** (pas par ISIN) : passer par `pf.ticker_de(isin)`.
- `EV/EBITDA` n'est calculé qu'avec `enterpriseValue` ; sans elle, il n'est pas affiché (pas de repli sur la capitalisation).
- Une valeur Yahoo manquante ne doit jamais devenir `0` ; l'app préfère « N/A » ou le dernier prix connu.
- Dans un `st.form`, seuls les `st.form_submit_button` sont autorisés (pas de `st.button`) ; pour une action
  intermédiaire, utiliser des widgets à clés et des callbacks.
- Le cache des fondamentaux dure 6 h : 🔄 (ou redémarrage) pour voir de nouvelles valeurs.
- **Clés de session** : toute clé propre à un compte passe par `etat.k(...)` (préfixe `c.`), sinon elle survit à la
  déconnexion. Un test refuse les clés écrites en dur hors de cet espace.
- Un **fragment** relancé seul réutilise le contexte `pf` du dernier rerun complet : après une écriture en base,
  toujours `st.rerun()` (complet), jamais `relancer_zone()`.
- Le test de parité du rendu (`tests/test_rendu.py`) échoue à tout changement visible : s'il est voulu, régénérer la
  référence avec `python -m tests.rendu` et le dire dans le commit.

## Limites connues

- Non vérifié en conditions réelles dans les dernières livraisons : lecture d'une vraie capture par Gemini, qualité
  des suggestions de concurrent, rendu mobile et comportement tactile des fragments.
- Mise en page adaptative, nouveaux graphiques et bandeau démo cliquable : livrés **sans test visuel** (le CSS de
  `pea/ui/style.py` cible des attributs `data-testid` / classes `st-key-*` de Streamlit, qui peuvent changer d'une version à
  l'autre ; si une grille ne s'applique plus, les cartes retombent simplement sur une colonne).
- Les données Yahoo sont indicatives (fondamentaux parfois absents, surtout pour les ETF).

## Interface adaptative et graphiques

- `style.appliquer()` (CSS) est appelé au début d'`app.py`. Les listes de cartes sont dans des `st.container(key="grille_…")`
  mis en grille par le CSS (`auto-fill`, 340 px mini) ; la saisie (`key="saisie"`) et le formulaire de connexion
  (`key="connexion"`) ont une largeur limitée. Les graphiques côte à côte utilisent `st.columns`, qui s'empilent sur mobile.
- Le bandeau IA (Analyse & Chat) est un `st.expander` **replié par défaut** (Portefeuille et Projet) ; une fois déplié,
  analyse et chat sont côte à côte sur grand écran.
- Tous les graphiques passent par `style.habiller(fig)` : palette douce commune (`style.PALETTE`), police système moderne,
  nombres à la française, infobulles arrondies (€ sans décimale, % à 1 décimale). Un nouveau graphique doit en faire autant
  et définir un `hovertemplate` arrondi. Pas de `plotly.express` : graphiques construits avec `plotly.graph_objects` et des
  listes simples (évite des avertissements de dépréciation dans les logs).

## Pistes

- Mémoriser « nom du courtier → ISIN » (nouvelle table) pour ne corriger un ISIN qu'une fois.
- Import : lire aussi le cash/total du courtier pour proposer un versement ; gérer les dividendes.
- Sélecteur de KPI affichés ; infobulles sur les ratios ; coloration vert/rouge des KPI.

## Contribuer

- Branches `refonte/…` ou `vibe/{description}-{date}` ; commits clairs, en français ; tester avant de fusionner dans `main`.
- Mettre à jour ce README à chaque livraison qui change le comportement.
- Ne jamais pousser : secrets, données réelles (positions, montants, `seed_pea.sql`), captures d'écran de courtier.
  L'historique Git conserve tout ce qui a été commité un jour : un secret ou une donnée réelle poussé est à considérer
  comme compromis.
