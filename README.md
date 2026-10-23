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
- **Cloisonnement par compte** : toute lecture/écriture Supabase est filtrée par `user_id` dans `db.py`.
  Le compte `demo` ne lit jamais les données d'un autre compte et **n'appelle jamais l'IA** (garde côté UI *et* serveur).
  **Seule exception** : `db.performances_partagees()` (voir « Partage de la performance »).
- **Ne pas modifier les règles métier** ci-dessous sans demande explicite.
- Les fichiers `.py` du dépôt vont **ensemble** : un déploiement partiel (ex. `app.py` sans `donnees.py`) plante.

---

## Architecture

| Fichier | Rôle |
|---|---|
| `app.py` | Interface : 5 onglets (Portefeuille · Historique · Projet · Watchlist · Saisie), cartes de lignes, blocs IA/chat (dans un dépliant), import par captures |
| `style.py` | Présentation : CSS adaptatif (largeur, grilles de cartes, bandeau démo cliquable), palette et habillage communs des graphiques Plotly (police, nombres français, infobulles) |
| `calculs.py` | Calculs purs : positions/PRM, plus-values, cash, synthèse, TWR, reconstitution d'historique, scénarios, répartitions, notes relatives 1-10 (`note_relative`) |
| `technique.py` | Indicateurs techniques purs (MM, RSI, stochastique, Bollinger) et note /10 |
| `concurrents.py` | Concurrent d'un titre : suggestion IA validée, saisie manuelle, comparaison des multiples (réseau injecté) |
| `import_ecran.py` | Import par captures : nettoyage du JSON Gemini, résolution des ISIN, opérations proposées (logique pure) |
| `llm.py` | Gemini : analyse, chat, lecture de captures, helpers HTTP communs (`appeler_json`, `avec_reessai`), quotas |
| `prompts.md` | Prompts éditables (sections `## analyse`, `## scenario`, `## chat`, `## capture`, `## concurrent`) ; section absente = défaut du code |
| `donnees.py` | Yahoo Finance : cours, fondamentaux, bougies, résolution ISIN → ticker, caches par titre |
| `db.py` | Supabase : lecture paginée en cache, écritures, upserts, préchargement parallèle |
| `auth.py` | Connexion (comptes lus dans `st.secrets`), connexion automatique au compte demo (interrupteur), limitation des essais, nettoyage de l'état au changement de compte |
| `schema.py` | Colonnes métier de chaque table, ordre de tri, colonnes numériques |
| `schema.sql` | Schéma Supabase complet (idempotent, RLS activée) |
| `seed_demo.sql` | Portefeuille fictif du compte `demo` (à exécuter **une seule fois**) |
| `secrets.toml.example` | Modèle des secrets |

**Ordre de lecture conseillé** : `calculs.py` → `donnees.py` → `db.py` → `app.py` → `llm.py`.

**Tables** : `transactions`, `dividendes`, `versements`, `secteurs`, `tickers` (ISIN → ticker, dernier prix, concurrent),
`snapshots` (valeur et apports par jour), `watchlist`, `scenarios`, `scenario_trades`, `analyses_ia`, `analyses_scen`,
`chat_log` (une ligne par message, pour le quota), `partage` (choix de partage de la performance + pseudo). Toutes portent un `user_id`.

---

## Règles métier

- **PRM** = coût moyen pondéré, frais d'achat inclus. Une vente réduit le coût au PRM ; plus-value réalisée =
  produit net − PRM × quantité. Une vente supérieure à la quantité détenue est refusée.
- **Cash** = versements − retraits − achats + ventes + dividendes (frais déduits).
- **Apports nets** = versements − retraits. Une `PV_ANTERIEURE` (plus-value antérieure réinvestie) alimente le cash
  mais **n'est pas un apport**.
- **Plafond PEA** : 150 000 € de versements cumulés. **Alerte de concentration** : une ligne > 25 % des titres.
- **Historique** : un point (`snapshots`) est enregistré à chaque visite en semaine ; reconstituable depuis les
  transactions (Saisie › Maintenance). Performance vs indice en **TWR** base 100 (MSCI World CW8, CAC 40, Euro Stoxx 50).
- **Statut d'un cours** : `live` > `obsolète` (dernier prix connu en base) > `estimé` (prix de revient).
- **Scénarios (onglet Projet)** : opérations fictives au dernier cours, rejouées sur le journal réel ; le réel n'est
  jamais modifié.
- **Liens** : chaque carte porte un lien Google Actualités calculé à l'affichage (rien n'est stocké en base).

### Partage de la performance (Historique)
Case sous le 2ᵉ graphique, **décochée par défaut** (table `partage` : `partage`, `pseudo`, migration dans `schema.sql`).
Le graphique « Performance vs indice » ajoute, en plus de l'indice, la courbe TWR des **autres comptes** ayant coché la case
(sélecteur d'utilisateurs, tous affichés par défaut) — indépendamment du choix de l'utilisateur lui-même de partager.
- Seule l'**indice TWR base 100** quitte `db.py` (`performances_partagees`) : jamais valeur, apports ni positions.
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

### Indicateurs techniques (`technique.py`)
Sélecteur *Fondamentaux | Indicateurs techniques* dans Portefeuille, Projet et Watchlist ; les bougies (~1 an) ne
sont téléchargées que si la vue technique est choisie. Chaque indicateur a un score −1…+1 ; **note /10 = 5 + 5 ×
moyenne pondérée** (MM 40 %, RSI 20 %, stochastique 20 %, Bollinger 20 %) ; verdict ≥ 6 Acheter, ≤ 4 Vendre.
Filtre de tendance : en tendance nette, les oscillateurs contraires comptent pour moitié. Signal indicatif, pas un
conseil. Constantes réglables en tête du module.

### Concurrent (`concurrents.py`)
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
- Quotas dans `llm.py` (source unique) : analyses 30/jour/compte, chat 100/jour/compte, imports par captures 30 et
  suggestions de concurrent 30 par session. Les vraies limites sont celles de Google (par projet et par modèle).
- Modèle par défaut `gemini-3.6-flash`, surchargeable par le secret `GEMINI_MODEL`.
- L'IA donne un avis sur la **structure** ; jamais d'ordre d'achat/vente, de prévision chiffrée ni de conseil fiscal.

---

## Installation

```bash
git clone https://github.com/Michallet/Suivi_PEA.git && cd Suivi_PEA
pip install -r requirements.txt
mkdir -p .streamlit && cp secrets.toml.example .streamlit/secrets.toml   # puis éditer
streamlit run app.py
```

**Secrets** (`.streamlit/secrets.toml` en local, *Settings › Secrets* sur Streamlit Cloud ; **jamais dans Git**) :

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "clé service_role"      # secret serveur uniquement, jamais la clé anon
GEMINI_API_KEY = ""                    # facultatif ; inactif pour le compte demo
# GEMINI_MODEL = "gemini-3.6-flash"    # facultatif
# DEBUG_PERF = true                    # facultatif : affiche les temps (base / cours / fondamentaux / calculs)
# AUTO_CONNEXION_DEMO = false          # facultatif : surcharge auth.CONNEXION_DEMO_AUTO (voir « Connexion par défaut »)

[users.demo]
password = "demo"
demo = true

[users.theo]
password = "un_mot_de_passe_long_et_unique"
demo = false
```

Autres comptes : même modèle `[users.identifiant]` (`password`, `demo = false`). Les mots de passe restent dans les
secrets Streamlit, pas dans Supabase. Les essais de connexion des comptes privés sont limités (8 par 15 min) ; le
compte `demo` est public par conception. L'ancien secret `APP_PASSWORD` est encore lu comme mot de passe de `theo`
si `[users.theo]` est absent.

**Connexion par défaut (mode démo)** : à l'ouverture, l'app se connecte seule au compte `demo` (pratique pour les
tests). L'interrupteur est le booléen `CONNEXION_DEMO_AUTO` en tête de `auth.py` (`True` = démo d'office, `False` =
écran de connexion comme avant) ; le secret facultatif `AUTO_CONNEXION_DEMO` prime sur lui, sans toucher au code. Pour
passer sur un compte personnel : cliquer sur le **verrou 🔒** (en-tête de chaque page) ou sur le **bandeau « Mode démo »** ;
cela ouvre le formulaire de connexion (démo préremplie) sans reconnecter la démo d'office, jusqu'à la prochaine connexion
réussie. Se déconnecter d'un compte personnel avec le verrou fait de même. Le cloisonnement par compte est inchangé.

**Base** : exécuter `schema.sql` dans le SQL Editor de Supabase (idempotent, peut être rejoué), puis `seed_demo.sql`
**une seule fois** pour le compte demo. Le compte `demo/demo` est partagé et modifiable par tous ses visiteurs :
n'y saisir aucune donnée personnelle. Sur une base issue de l'ancien schéma mono-utilisateur (avant v8), consulter
l'historique Git de `schema.sql` pour la migration vers `user_id`.

**Vérification rapide** (le dépôt ne contient pas de suite de tests) : `python -m py_compile *.py`, puis lancer l'app
avec les comptes `demo` et personnel. Les modules `calculs`, `technique`, `concurrents`, `import_ecran`, `llm` ne
dépendent pas de Streamlit et se testent seuls (réseau à simuler).

---

## Performance : ce qu'il faut savoir avant de toucher au code

- **Cache base** (`db.py`) : 2 min, **par (compte, table)** ; une écriture n'invalide que sa table
  (`_invalider`). `db.precharger()` lit toutes les tables en parallèle. Le bouton 🔄 vide tout.
- **Cache Yahoo** (`donnees.py`) : **par titre** — cours 5 min, fondamentaux 6 h, bougies 1 h ; un échec n'est mémorisé
  que 1 à 5 min. Un titre ajouté ne retélécharge pas les autres.
- **Fragments** (`@st.fragment`) : Portefeuille (3 fragments frères : synthèse, cartes, graphiques), Historique,
  Projet, Watchlist et Saisie ne relancent que leur zone ; les écritures finissent par un `st.rerun()` complet.
- Les écritures de suivi (derniers cours, point du jour de `snapshots`) sont faites **en fin de script**, après
  l'affichage de la page.
- Hors du code : mise en veille de Streamlit Community Cloud et pause du projet Supabase gratuit après inactivité.

---

## Pièges connus

- `tickers.ticker` est `NOT NULL` : pour modifier un titre, utiliser `db.modifier(table, id, rec, cle="isin")`,
  pas un `upsert` partiel.
- Les fondamentaux sont indexés par **ticker** (pas par ISIN) : passer par `tmap.loc[isin, "ticker"]`.
- `EV/EBITDA` n'est calculé qu'avec `enterpriseValue` ; sans elle, il n'est pas affiché (pas de repli sur la capitalisation).
- Une valeur Yahoo manquante ne doit jamais devenir `0` ; l'app préfère « N/A » ou le dernier prix connu.
- Dans un `st.form`, seuls les `st.form_submit_button` sont autorisés (pas de `st.button`) ; pour une action
  intermédiaire, utiliser des widgets à clés et des callbacks.
- Le cache des fondamentaux dure 6 h : 🔄 (ou redémarrage) pour voir de nouvelles valeurs.

## Limites connues

- Non vérifié en conditions réelles dans les dernières livraisons : lecture d'une vraie capture par Gemini, qualité
  des suggestions de concurrent, rendu mobile et comportement tactile des fragments.
- Mise en page adaptative, nouveaux graphiques et bandeau démo cliquable : livrés **sans test visuel** (le CSS de
  `style.py` cible des attributs `data-testid` / classes `st-key-*` de Streamlit, qui peuvent changer d'une version à
  l'autre ; si une grille ne s'applique plus, les cartes retombent simplement sur une colonne).
- Les données Yahoo sont indicatives (fondamentaux parfois absents, surtout pour les ETF).
- Le compte `demo` est modifiable par tous sans plafond d'écriture.

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

- Branches `vibe/{description}-{date}` ; commits clairs, en français ; tester avant de fusionner dans `main`.
- Mettre à jour ce README à chaque livraison qui change le comportement.
- Ne jamais pousser : secrets, données réelles (positions, montants, `seed_pea.sql`), captures d'écran de courtier.
  L'historique Git conserve tout ce qui a été commité un jour : un secret ou une donnée réelle poussé est à considérer
  comme compromis.
