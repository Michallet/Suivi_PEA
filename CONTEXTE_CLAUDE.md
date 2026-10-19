# CONTEXTE.md — Suivi PEA (pour reprise avec Claude)
**Dernière mise à jour** : 19/10/2026 · **Version du code** : v6 + corrections · **Langue** : français

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
  - **Mode démo** = aucun accès base/Yahoo/Gemini (fonctionne sans connexion)
- ✅ **Simplicité** : réponses concises, UX épurée
- ✅ **Mono-utilisateur** (multi-utilisateur reporté)

---

## 3️⃣ **Architecture actuelle**

```
app.py          # UI Streamlit (1068+ l.) : 5 onglets + bloc_ia + bloc_chat
calculs.py      # Calculs purs : PRM, PV, cash, TWR, scénarios
llm.py          # Gemini : analyse IA, chat, validation format
prompts.md      # Prompts externalisés pour l'IA
 db.py          # Supabase : lecture/écriture (cache 2 min)
schema.sql      # Schéma base (idempotent, RLS activé)
donnees.py      # Yahoo Finance : cours, fondamentaux, historiques
 demo.py        # Mode démo 100 % mémoire (aucune I/O)
 auth.py        # Auth mono-utilisateur (APP_PASSWORD)

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

## 6️⃣ **Problèmes connus / À améliorer**

### ⚠️ **Recherche Google (URL automatique)**
- **Risque** : Google peut bloquer les requêtes automatiques (CAPTCHA, restrictions IP)
- **Solution recommandée** : Remplacer par **API Google Custom Search** (gratuite : 100 req/jour)
  - Clé API à ajouter dans `st.secrets`
  - Endpoint : `https://www.googleapis.com/customsearch/v1`
- **Alternative** : Utiliser **DuckDuckGo** (pas de blocage) ou **Bing Search API**

### ⚠️ **KPIs EV/EBITDA**
- **Calcul** : `enterpriseValue / ebitda` ou `marketCap / ebitda` (fallback)
- **Limite** : `enterpriseValue` souvent **non disponible** pour les ETF → fallback sur `marketCap`
- **Amélioration** : Ajouter un indicateur de source (EV vs MarketCap)

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

**Note** : Ces URLs sont **auto-générées** par `chercher_url_publication()` pour les ISIN `FR001*`.

---

## 8️⃣ **Secrets Streamlit (à configurer)**

```toml
# .streamlit/secrets.toml
APP_PASSWORD = "votre_mot_de_passe"          # Obligatoire pour accéder aux données réelles
SUPABASE_URL = "https://votre-projet.supabase.co"
SUPABASE_KEY = "votre_clé_service_role"      # !!! PAS la clé anon !!!
GEMINI_API_KEY = "votre_clé_Gemini"          # Optionnel (désactive l'IA si absent)
# Optionnel pour la recherche URL (si API Google Custom Search)
GOOGLE_SEARCH_API_KEY = "votre_clé"
GOOGLE_SEARCH_CX = "votre_CX"
```

**⚠️ IMPORTANT** : Sans `APP_PASSWORD`, l'app reste en **mode démo** (données fictives).

---

## 9️⃣ **Points d'attention pour Claude**

### 🔴 **À ne JAMAIS faire**
- ❌ Pousser des **secrets** dans le dépôt
- ❌ Pousser des **données réelles** (ex: `seed_pea.sql`, positions, montants)
- ❌ Casser le **mode démo** (doit fonctionner sans connexion/base/Yahoo/Gemini)
- ❌ Ajouter des dépendances payantes
- ❌ Modifier les **règles métier** (§6 du CONTEXTE original)

### 🟢 **À toujours faire**
- ✅ **Tester en local** : `streamlit run app.py` (avec `.streamlit/secrets.toml`)
- ✅ **Tester le mode démo** : Sans secrets, l'app doit démarrer et afficher des données fictives
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
- [ ] Remplacer `requests + BeautifulSoup` par **API Google Custom Search**
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
APP_PASSWORD = "test123"
SUPABASE_URL = "https://votre-projet.supabase.co"
SUPABASE_KEY = "votre_clé"
GEMINI_API_KEY = ""
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
- **Mode démo** : Lancer sans secrets → données fictives
- **Mode réel** : Ajouter `APP_PASSWORD` dans `secrets.toml`
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
