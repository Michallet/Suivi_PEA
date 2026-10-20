# CONTEXTE.md — Suivi PEA (pour reprise avec Claude)
**Dernière mise à jour** : 20/10/2026 · **Version du code** : v7 (audit + fondamentaux/liens partout) · **Langue** : français

---

## 📌 **Contexte de reprise pour Claude**

Ce fichier accompagne le dépôt GitHub `Michallet/Suivi_PEA` (branch `main`, commit **4780248**).
Il résume l'état actuel du projet, les dernières modifications, et les points d'attention pour continuer le développement.

---

## 1️⃣ **Le projet en bref**

**Application** : Suivi d'un **PEA personnel** (≈ 10 lignes, ETF Amundi) en **Streamlit** (mobile-first).
**Base de données** : **Supabase** (PostgreSQL gratuit) · **Cours** : Yahoo Finance (`yfinance`) · **IA** : Gemini (optionnel).
**Hébergement** : Streamlit Community Cloud (gratuit) · **Dépôt** : [Michallet/Suivi_PEA](https://github.com/Michallet/Suivi_PEA) (public).

---

## 2️⃣ **Contraintes non négociables** (à respecter absolument)

- ✅ **100 % gratuit** (Streamlit, Supabase, Yahoo, Gemini palier gratuit)
- ✅ **Mobile-first** (écran téléphone, cartes > tableaux, pas de zoom tactile)
- ✅ **Sécurité** :
  - **Aucun secret** dans le code (tout via `st.secrets`)
  - **Dépôt public** ⇒ zéro donnée perso/réelle dans le code
  - **Compte demo** = données fictives persistantes et partagées dans Supabase ; fonctions IA bloquées
- ✅ **Simplicité** : réponses concises, UX épurée
- ✅ **Multi-utilisateur** : `theo`, `demo` et quelques comptes supplémentaires via les secrets Streamlit

---

## 3️⃣ **Architecture actuelle**

```
app.py          # UI Streamlit (1068+ l.) : 5 onglets + bloc_ia + bloc_chat
calculs.py      # Calculs purs : PRM, PV, cash, TWR, scénarios
llm.py          # Gemini : analyse IA, chat, validation format
prompts.md      # Prompts externalisés pour l'IA
db.py           # Supabase : lecture/écriture cloisonnées par user_id (cache 2 min)
schema.sql      # Schéma et migration multi-utilisateur (RLS activé)
seed_demo.sql   # Portefeuille fictif initial du compte demo (à exécuter une seule fois)
donnees.py      # Yahoo Finance : cours, fondamentaux, historiques
auth.py         # Authentification (comptes définis dans st.secrets)

Tables Supabase :
- transactions, dividendes, versements
- secteurs, tickers, snapshots
- watchlist (➕ url), scenarios, scenario_trades
- analyses_ia, analyses_scen, chat_log
```

---

## 4️⃣ **Dernières modifications (session du 19/10/2026)**

### ✅ **Fonctionnalités ajoutées** (commit **4d6cd92** + **4780248**)

#### 1. **Champ URL dans la watchlist**
- **Schema** : `watchlist.url text` (ajouté via `ALTER TABLE watchlist ADD COLUMN url text`)
- **UI** : Champ "URL de publication" dans le formulaire d'ajout à la watchlist
- **Affichage** : Noms cliquables (liens Markdown) : `**[{nom}]({url})**`

#### 2. **Recherche automatique d'URL**
- **Fonction** : `donnees.chercher_url_publication(nom: str) -> str | None`
  - Effectue une **recherche Google** pour `"{nom} Financial report"`
  - Retourne le **1er résultat organique** (via `requests` + `BeautifulSoup`)
  - **Dépendance** : `beautifulsoup4>=4.12` (ajouté à `requirements.txt`)
- **Bouton** : "🔍 Rechercher" dans le formulaire watchlist → pré-remplit le champ URL
- **Auto-remplissage** : Si URL non fournie à l'ajout, tentative automatique via le nom

#### 3. **KPIs étendus par type de titre**
- **ETF** :
  - **Actifs sous gestion** (`net_assets`) → Format : 1,54 Md €
  - **Ratio de frais** (`expense_ratio`) → Format : 0,40 %
- **Actions individuelles** :
  - **Bénéfice net** (`net_income`) → Format : 14,6 M €
  - **EBITDA** (`ebitda`) → Format : 22,3 M €
  - **EV/EBITDA** (`ev_ebitda`) → Format : 12,5x

**Sources** : Yahoo Finance (`yfinance.Ticker.info`)

---

## 5️⃣ **Problèmes résolus dans cette session**

| Problème | Cause | Correction (commit **4780248**) |
|----------|-------|--------------------------------|
| KPIs non affichés | `fonds` indexé par **ticker**, pas ISIN | Utilisation de `tmap.loc[isin, "ticker"]` |
| Erreur colonne `url` | `hasattr(r, "url")` inefficace sur namedtuple | Remplacé par `"url" in wl.columns` |
| Dépendances manquantes | `beautifulsoup4` non installé | Ajout dans `requirements.txt` |

---

## 5️⃣bis **Audit du 20/10/2026 (Claude) — corrections livrées**

| Problème | Correction |
|---|---|
| `schema.py` : `watchlist` sans `url` ⇒ `db.lire` **ignorait la colonne** (liens jamais affichés, démo incluse) | colonne ajoutée ; `demo.py` aligné (4 colonnes) |
| `r.url.strip()` plantait si la valeur était NaN/None | `calculs.nettoyer_url()` (refuse aussi `javascript:`, échappe les parenthèses Markdown) |
| Bouton « Rechercher » : posait une clé `wl_url_{isin}` jamais lue + 2 boutons dans un `st.form` | formulaire remplacé par des widgets à clés + callback `_chercher_url_wl` |
| Recherche d'URL par scraping Google (bloqué/CAPTCHA, non testé) | DuckDuckGo « html » (sans clé) + repli sur `info["website"]` de Yahoo, cache 24 h, ne lève jamais |
| « EV/EBITDA » calculé avec `marketCap` en repli (ratio faux sous un mauvais nom) | uniquement avec `enterpriseValue`, sinon non affiché |
| Absents du dépôt : `tests/`, `.streamlit/secrets.toml.example`, `.gitignore` | recréés (`tests/test_calculs.py`, `tests/test_schema.py` — 9 tests, **pas les 47 d'origine**) |
| `requirements-1.txt` : doublon obsolète (sans bs4) | à supprimer à la main sur GitHub |

**Non vérifié** : rendu Streamlit réel, DuckDuckGo en direct, Yahoo/Supabase (pas de réseau ni de Streamlit dans l'environnement d'audit).
**Alerte confidentialité** : `seed_pea.sql` et `CONTEXTE.md` §4 contiennent les positions/PRM/montants réels dans un dépôt public (contraire au §2) : les retirer **et** tenir compte que l'historique Git les conserve.
Lancer : `pip install -r requirements-dev.txt && pytest -q`.

---

## 5️⃣ter **v7 (20/10/2026) — fondamentaux et liens partout**

- **Fiche commune** (`app.py` : `carte_ligne`, `lignes_fondamentaux`) utilisée par **Portefeuille**, **Projet** (nouveau bloc « Lignes du scénario ») et **Watchlist** : mêmes lignes, valeurs absentes omises.
  Ordre : PER · PER prévisionnel · CA · Bénéfice net · EBITDA · Capitalisation · Valeur d'entreprise · EV/EBITDA · Actifs sous gestion · Frais annuels (+ quantité/PRM/+-value/dividendes hors watchlist).
- **URL de publication = par ISIN dans `tickers.url`** (plus dans `watchlist.url`, encore lue en repli). Lien « 📄 Publication » visible sur chaque carte ; champ modifiable (💾 / 🔍) dans « Détails » de chaque carte, y compris pour les lignes déjà en watchlist ou détenues.
- **SQL à exécuter une fois** : `alter table tickers add column if not exists url text;` (déjà ajouté à `schema.sql`).
- Bug corrigé : `**prix**` affiché tel quel dans la watchlist (Markdown dans un bloc HTML) ; bouton ✖ qui passait sous la carte sur mobile (déplacé dans « Détails »).
- `db.modifier(table, id_, rec, cle="id")` : UPDATE par clé (ne pas utiliser `upsert` partiel sur `tickers` : `ticker` est NOT NULL).
- Nouveaux champs Yahoo : `per_prev` (forwardPE), `ev` (enterpriseValue). Cache fondamentaux 6 h : reboot ou 🔄 pour les voir.
- Tests : `pytest -q` (9) et `python tests/e2e/parcours.py` (faux Streamlit : démo + connecté simulé).

---

## 6️⃣ **Problèmes connus / À améliorer**

### ⚠️ **Recherche d'URL de publication (automatique)**
- **Risque** : DuckDuckGo (remplace Google depuis le 20/10) peut aussi bloquer les IP de Streamlit Cloud ; repli sur le site Yahoo, sinon saisie manuelle
- **Ne PAS passer par l'API Google Custom Search** : fermée aux nouveaux clients et supprimée le 01/01/2027 (vérifié le 20/10/2026).
- **Implémentation actuelle (v7.1)** : `recherche.py` (pur, testé) construit 2 requêtes (publications + rapport PDF ; ETF : fiche produit/DIC avec l'ISIN), interroge DuckDuckGo puis Bing (HTML, sans clé), et **classe** les résultats (PDF/mots « results, annual, investor… » favorisés, pages d'accueil, Wikipédia, LinkedIn… pénalisés, bonus si le domaine porte le nom de l'émetteur). Repli : `info["website"]` Yahoo = **page d'accueil** (l'app prévient alors).
- **Jamais testé en direct** (pas de réseau en dev) : si les liens restent des pages d'accueil, les moteurs bloquent probablement les IP de Streamlit Cloud ⇒ saisie manuelle, ou service de recherche à clé (Brave Search API, SerpApi… à vérifier avant).

### ⚠️ **KPIs EV/EBITDA**
- **Calcul** : `enterpriseValue / ebitda` uniquement (plus de repli sur `marketCap`)
- **Limite** : `enterpriseValue` souvent absent ⇒ KPI non affiché

### ⚠️ **Cache des fondamentaux**
- **TTL** : 6 heures (`@st.cache_data(ttl=6*3600)`)
- **Impact** : Les KPIs peuvent être **obsolètes** si le marché a bougé
- **Solution** : Réduire le TTL à 1h ou ajouter un bouton "Rafraîchir"

---

## 7️⃣ **Données de l'utilisateur (PEA actuel)**

**3 ETF Amundi** (ISINs à connaître pour les tests) :
| Nom | ISIN | Ticker Yahoo | URL de publication |
|-----|------|--------------|-------------------|
| PEA Asie Émergente (MSCI) | `FR0013412012` | `PAASI.PA` | [Lien](https://www.amundi.fr/fr/professionnel/etf/fiche/FR0013412012) |
| PEA Euro Court Terme | `FR0013346681` | `OBLI.PA` | [Lien](https://www.amundi.fr/fr/professionnel/etf/fiche/FR0013346681) |
| PEA Monde (MSCI World) | `FR001400U5Q4` | `DCAM.PA` | [Lien](https://www.amundi.fr/fr/professionnel/etf/fiche/FR001400U5Q4) |

**Note** : ces URLs sont saisies à la main ; `chercher_url_publication()` ne les génère PAS (recherche web générique).

---

## 8️⃣ **Secrets Streamlit (à configurer)**

```toml
# .streamlit/secrets.toml ; ne jamais pousser ce fichier dans Git
SUPABASE_URL = "https://votre-projet.supabase.co"
SUPABASE_KEY = "votre_clé_service_role" # secret serveur uniquement, jamais la clé anon
GEMINI_API_KEY = "votre_clé_Gemini"    # facultatif ; inactif pour le compte demo

[users.demo]
password = "demo"
demo = true

[users.theo]
password = "un_mot_de_passe_long_et_unique"
demo = false
```

Ajouter les comptes suivants sous la forme `[users.identifiant]`, avec `password` et `demo = false`. Les secrets d'identification restent dans Streamlit ; ils ne sont pas stockés dans Supabase.

**Migration** : sauvegarder la base, exécuter `schema.sql` dans Supabase, puis exécuter `seed_demo.sql` une seule fois. Les lignes existantes seront attribuées à `theo`. Le compte `demo/demo` est partagé et modifiable par tous les visiteurs qui l'utilisent ; ne jamais y saisir d'informations personnelles.

---

## 9️⃣ **Points d'attention pour Claude**

### 🔴 **À ne JAMAIS faire**
- ❌ Pousser des **secrets** dans le dépôt
- ❌ Pousser des **données réelles** (ex: `seed_pea.sql`, positions, montants)
- ❌ Permettre au compte `demo` d’appeler l’IA, ou de lire les données d’un autre compte
- ❌ Ajouter des dépendances payantes
- ❌ Modifier les **règles métier** (§6 du CONTEXTE original)

### 🟢 **À toujours faire**
- ✅ **Tester en local** : `streamlit run app.py` (avec `.streamlit/secrets.toml`)
- ✅ **Tester le compte démo** : après migration et initialisation, `demo/demo` peut modifier son jeu fictif sans appeler Gemini
- ✅ **Vérifier les imports** : `python3 -m py_compile app.py donnees.py`
- ✅ **Respecter le mobile-first** : Pas de tableaux larges, pas de zoom tactile
- ✅ **Mettre à jour ce fichier** à chaque livraison

### 🔧 **Outils disponibles**
- **Tests unitaires** : `tests/` (47 tests existants, à étendre)
- **Tests e2e** : `tests/e2e/parcours.py` (vérifie les doublons de widgets)
- **Linter** : `pylint` ou `ruff` (non configuré, à ajouter si besoin)

---

## 🔟 **Prochaines étapes suggérées**

### 🎯 **Priorité 1 : Stabiliser la recherche URL**
- [x] ~~Remplacer par Google Custom Search~~ (API fermée) → classement multi-moteurs fait (v7.1)
- [ ] Gérer les erreurs de recherche (timeout, CAPTCHA)
- [ ] Ajouter un cache pour les URLs trouvées (éviter les requêtes répétées)

### 🎯 **Priorité 2 : Améliorer les KPIs**
- [ ] Ajouter un **sélecteur de KPIs** (l'utilisateur choisit quels KPIs afficher)
- [ ] **Rafraîchir manuellement** les fondamentaux (bouton "↻")
- [ ] **Colorer les KPIs** (vert/rouge selon performance)

### 🎯 **Priorité 3 : Migration base**
- [ ] Exécuter `ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS url text` en production
- [ ] Pré-remplir les URLs pour les ETF existants (via script Python)

### 🎯 **Priorité 4 : UX**
- [ ] **Tooltips** sur les KPIs (ex: "EV/EBITDA = Enterprise Value / EBITDA")
- [ ] **Icônes** pour les liens (🔗) et les KPIs (💰, 📈)
- [ ] **Ordre des KPIs** : Permettre à l'utilisateur de les réorganiser

---

## 📦 **Fichiers à fournir à Claude**

1. **Ce fichier** : `CONTEXTE_CLAUDE.md` (à lire en premier)
2. **Le dépôt GitHub** : `Michallet/Suivi_PEA` (branch `main`)
3. **Les secrets** : `.streamlit/secrets.toml` (à créer localement, **jamais poussé**)
4. **Optionnel** : `seed_pea.sql` (données initiales, **privé**)

---

## 💡 **Conseils pour Claude**

### 1. **Démarrer le projet**
```bash
# Cloner le dépôt
git clone https://github.com/Michallet/Suivi_PEA.git
cd Suivi_PEA

# Installer les dépendances
pip install -r requirements.txt

# Créer les secrets (exemple)
mkdir -p .streamlit
cat > .streamlit/secrets.toml <<EOF
SUPABASE_URL = "https://votre-projet.supabase.co"
SUPABASE_KEY = "votre_clé"
GEMINI_API_KEY = ""

[users.demo]
password = "demo"
demo = true

[users.theo]
password = "test123"
demo = false
EOF

# Lancer l'app
streamlit run app.py
```

### 2. **Comprendre le code**
**Ordre de lecture recommandé** :
1. `CONTEXTE_CLAUDE.md` (ce fichier)
2. `calculs.py` (règles métier)
3. `donnees.py` (données marché)
4. `db.py` (accès base)
5. `app.py` (UI)
6. `llm.py` (IA)

### 3. **Debugger**
- **Compte démo** : configurer Supabase, exécuter `seed_demo.sql`, puis se connecter avec `demo/demo`
- **Compte personnel** : configurer `[users.theo]` dans `secrets.toml`
- **Logs** : Streamlit affiche les erreurs dans le terminal

### 4. **Contribuer**
- **Branches** : Créer une branche `vibe/{description}-{date}`
- **Commits** : Messages clairs, en français
- **PR** : Toujours tester avant de merger sur `main`

---

## 📞 **Contact / Questions**

**Utilisateur** : Michallet (mobile, GitHub)
**Modèle précédent** : Kimi (a implémenté v5/v6)
**Audit** : Claude (19/10/2026)

**Ressources** :
- [Dépôt GitHub](https://github.com/Michallet/Suivi_PEA)
- [Streamlit Docs](https://docs.streamlit.io/)
- [Supabase Docs](https://supabase.com/docs)
- [yfinance Docs](https://pypi.org/project/yfinance/)

---

*Ce fichier est conçu pour permettre à Claude (ou tout autre modèle) de reprendre le projet sans perte de contexte.*


## 🔐 Multi-utilisateur v8 (20/10/2026)

- `auth.py` gère les identifiants définis dans `.streamlit/secrets.toml`, sous `[users.demo]`, `[users.theo]`, etc.
- Les champs de connexion sont préremplis `demo` / `demo`. Les utilisateurs non connectés n'accèdent à aucune donnée.
- Tous les enregistrements Supabase ont un `user_id`. `db.py` ajoute le compte courant aux écritures et filtre chaque lecture, mise à jour, suppression et upsert. Le cache de lecture est partitionné par utilisateur.
- La migration `schema.sql` attribue les lignes historiques à `theo`, puis passe les clés concernées en clés composites. Exécuter ce fichier dans Supabase avant de déployer le code.
- Exécuter ensuite `seed_demo.sql` une seule fois pour créer le portefeuille fictif persistant. Le compte demo est partagé : toutes les modifications sont visibles par les visiteurs qui se connectent avec `demo/demo`. Ne jamais y enregistrer de données personnelles.
- L'analyse de portefeuille, l'analyse de scénario et le chatbot IA sont désactivés pour `demo`; les transactions, dividendes, versements, watchlist, secteurs et scénarios restent modifiables.
- Les anciens secrets `APP_PASSWORD` sont encore lus comme mot de passe de `theo` si aucun compte `[users.theo]` n'est configuré, pour faciliter la transition. Migrer de préférence vers le bloc `[users.theo]`.


## 📷 v9 — Import du portefeuille par captures d'écran (20/10/2026)

**But** : Saisie › **Import par captures**. L'utilisateur charge 1 à 8 captures de son courtier → Gemini (vision) lit
`nom / quantité / PRM / valeur` → l'app calcule l'écart avec Supabase → **achats/ventes proposés**, modifiables, à valider.
Rien n'est écrit avant « ✅ Enregistrer ». Compte **demo** : boutons désactivés (aucun appel Gemini).

**Fichiers** : `import_ecran.py` (logique **pure**, testée) · `llm.extraire_capture` (appel HTTP vision, schéma
`SCHEMA_JSON_CAPTURE`, prompt `SYSTEME_CAPTURE`, surchargeable par `## capture` dans `prompts.md`) ·
`app.py` (`import_captures`, cartes mobile-first dans un `st.form`) · `tests/test_import_ecran.py` (16 tests).

**Règles métier retenues**
- Les captures du courtier n'affichent que le **nom** (pas l'ISIN). Ordre de résolution : ISIN lu à l'écran > nom proche d'un
  nom de `tickers` (mots du courtier ⊂ mots du nom connu, nom tronqué « Scre… » géré, ambigu = refusé) > même quantité **et**
  PRM (±0,5 %) qu'une position > ISIN proposé par l'IA (⚠️ « à vérifier »). Tout ISIN passe le contrôle Luhn
  (`C.isin_valide`) ; le ticker est résolu via `D.chercher_ticker` **avant** toute écriture.
- **Achat** (qté courtier > base) : prix **déduit** = `(PRM_courtier × Q_courtier − coût_base) / Δ`, pour que le PRM de l'app
  redevienne celui du courtier (frais inclus, frais = 0). Si ≤ 0 : prix = cours, avec alerte.
- **Vente** (qté courtier < base) : prix = cours actuel par défaut (à compléter). **Ligne détenue absente des captures** :
  vente totale **décochée** (une capture manque peut-être). **Ligne sans ISIN** : décochée.
- Alerte « lecture à vérifier » si `valeur ÷ quantité` s'écarte de >15 % du cours (>60 % du PRM sans cours) : chiffre mal lu.
- « 🔎 Contrôler » rejoue le journal + opérations cochées et liste les écarts restants (quantité, PRM >1 %).
  Garde-fous : vente > quantité détenue refusée (`calcul_positions`), journal modifié entre-temps = import annulé.
- Quota : `llm.MAX_IMPORTS_PAR_JOUR` (10) **par session** (pas de table dédiée).

**⚠️ Confidentialité (déroge au §2 « poids en % uniquement »)** : les **images** partent chez Gemini avec quantités et
montants visibles ; l'UI le dit, et demande de cadrer sans nom/n° de compte. Palier gratuit : Google peut réutiliser les contenus.
Les images ne sont ni stockées ni commitées. **Tests avec données fictives uniquement** (dépôt public).

**Non vérifié en conditions réelles** : appel Gemini réel (pas de clé/réseau en dev), lecture d'une vraie capture, rendu mobile.
Test UI fait avec `streamlit.testing` (AppTest) sur la fonction isolée, Supabase/Yahoo/Gemini simulés.
**Pistes** : mémoriser « nom courtier → ISIN » (nouvelle table) pour ne corriger un ISIN qu'une fois ; lire aussi le cash/total
du courtier pour proposer un versement ; dividendes.
