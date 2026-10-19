# CONTEXTE.md — Suivi PEA (point de reprise pour un autre modèle)

> Mis à jour : 18/10/2026 · Version du projet : **v3** · Langue de travail : **français** · Utilisateur sur **mobile**.
> **Consigne permanente de l'utilisateur** : à chaque nouvelle demande, livrer avec la réponse un fichier `CONTEXTE.md` à jour
> (contexte des échanges + état du projet), pour pouvoir continuer sur un autre modèle si les quotas le limitent.

## 1. Le projet en deux phrases
Application web **Streamlit** (hébergée gratuitement sur Streamlit Community Cloud) de suivi d'un **PEA** personnel (une dizaine de lignes),
consultée 2-3 fois par jour sur téléphone, avec base **Supabase** (Postgres gratuit) et cours **Yahoo Finance** (`yfinance`).
Dépôt GitHub **public** : `github.com/Michallet/Suivi_PEA` (aucun secret dans le dépôt ; tout passe par `st.secrets`).

## 2. Contraintes non négociables (décidées par l'utilisateur)
- **100 % gratuit** (hébergement, base, API). **Mobile-first** (carte par ligne, onglets, pas de tableaux larges).
- **Sécurité** : dépôt public ⇒ aucun mot de passe/clé dans le code ; données réelles derrière mot de passe ; mode démo sans accès base.
- **Simplicité** : peu de lignes, peu de clics. Réponses concises (écran de téléphone), en français.
- Mono-utilisateur pour l'instant (**multi-utilisateur mis de côté** : voir §9).

## 3. Historique des échanges (résumé chronologique)
1. Brief initial : outil de suivi PEA (alternative au dashboard XTB et à Google Sheets), script `app.py` v1 fourni (CSV + `config.json`).
2. Demande de **5 pistes d'amélioration** ⇒ proposées puis **toutes implémentées (v2)** : calcul PRM corrigé, persistance Supabase, UX mobile, fonctions PEA, robustesse des cours.
   - Bug v1 corrigé : après une vente, le PRM était faussé et la plus-value comptée deux fois.
3. Question Google Sheets vs Postgres ⇒ avis donné ; **l'utilisateur reste sur Supabase**.
4. Comment pousser du code depuis le téléphone ⇒ (a) Claude Code web/mobile (abonnement requis, préversion), (b) github.com navigateur « Upload files ».
5. Lovable comme substitut à Streamlit ⇒ **écarté** (offre gratuite = projets publics + crédits limités ; réécriture complète ; sécurité côté navigateur).
6. Procédure d'initialisation Supabase expliquée ; diagnostic d'un démarrage Streamlit en échec (causes probables listées : `requirements.txt`, fichiers manquants, secrets mal formés ; **cause réelle jamais communiquée**).
7. **Capture XTB** ⇒ `seed_pea.sql` (3 ETF, versements, tickers) pour peupler Supabase sans passer par l'interface.
8. Avis sur 4 pistes (watchlist, portefeuille projet, authentification, LLM) ⇒ **implémentées en v3** avec ces précisions de l'utilisateur :
   - auth **mono-utilisateur** : le mot de passe débloque les données réelles ; **mode démo** (données fictives) avant connexion ;
   - LLM : **version 2** = un bouton ✨, appel **one-shot** à **Gemini 3.6 Flash**, clé en secret, sortie **toujours au même format**
     (note /10 sur 4 critères + ~10 mots de synthèse), pas de chatbot.

## 4. Le PEA réel de l'utilisateur (d'après sa capture XTB)
| Ligne | ISIN | Ticker Yahoo | Qté @ PRM |
|---|---|---|---|
| Amundi PEA Asie Émergente (MSCI EM Asia) | `FR0013412012` | `PAASI.PA` | 15 @ 38,8040 |
| Amundi PEA Euro Court Terme | `FR0013346681` | `OBLI.PA` | 9 @ 9,8172 |
| Amundi PEA Monde (MSCI World) | `FR001400U5Q4` | `DCAM.PA` | 314 @ 6,1310 |

Versements 2 400 € (plafond restant 147 600 €), plus-value antérieure réinvestie ≈ 200,87 €, cash XTB 5,32 €, total 2 645,33 €.
**À corriger par l'utilisateur** : les dates des opérations (la capture n'en montre pas ⇒ `current_date` dans `seed_pea.sql`) et les frais (0 par défaut).
⚠️ Leçon : un ISIN cité de mémoire s'est révélé faux (Asie) ; **toujours vérifier les ISIN/ID de modèle par recherche**, et valider la clé de contrôle (`calculs.isin_valide`).

## 5. Architecture (fichiers)
```
app.py          UI Streamlit : 5 onglets (Portefeuille · Historique · Projet · Watchlist · Saisie), bloc IA, cartes mobiles
calculs.py      Calculs PURS (PRM, PV réalisées, cash, apports, TWR, reconstitution d'historique, scénarios, répartitions)
db.py           Supabase : lire (cache 2 min, paginé), inserer (renvoie la ligne), modifier, supprimer, upsert, appliquer_modifs
schema.py       Colonnes/ordre/types des tables (partagé par db.py et demo.py)
donnees.py      Yahoo : cours (cache 5 min), fondamentaux (6 h), historiques (1 h), résolution ISIN→ticker (à la saisie seulement)
demo.py         Mode démo : portefeuille FICTIF 100 % en mémoire (DemoStore = même interface que db), faux cours, exemple d'analyse IA
auth.py         Mot de passe (APP_PASSWORD, ou ADMIN_PASSWORD), verrou GLOBAL anti-force-brute (8 échecs/15 min), échec fermé
llm.py          Appel Gemini one-shot, schéma JSON, validation/normalisation du format, empreinte du portefeuille
schema.sql      À exécuter dans Supabase (SQL Editor). Idempotent (create table if not exists). RLS activé sans policy.
seed_pea.sql    Données initiales issues de la capture XTB (une seule fois, après schema.sql ; refuse de tourner si tables non vides)
scripts/migrer_csv.py   Migration unique des anciens CSV (v1) vers Supabase
tests/          test_calculs.py, test_llm.py, test_demo.py, test_auth.py (+ _stub.py) ; tests/e2e/{harness,parcours,rendu}.py
requirements.txt  streamlit, pandas, numpy, plotly, yfinance, supabase, requests
.streamlit/secrets.toml.example   modèle des secrets (le vrai fichier n'est JAMAIS commité)
```
Tables Supabase : `transactions`, `dividendes`, `versements` (VERSEMENT | RETRAIT | PV_ANTERIEURE), `secteurs`, `tickers` (dictionnaire ISIN→ticker + dernier cours),
`snapshots` (valeur PEA/jour), **v3** : `watchlist`, `scenarios`, `scenario_trades`, `analyses_ia`.

## 6. Règles métier (à ne pas casser)
- **PRM = coût moyen pondéré, frais d'achat inclus.** Une vente réduit le coût au PRM (pas au prix de vente) ; PV réalisée = produit net − PRM × qté.
- **Cash** = versements + PV antérieure − retraits − achats + ventes + dividendes (frais déduits). **Apports nets** = versements − retraits (la PV antérieure n'est PAS un apport).
- **Plafond PEA** 150 000 € = versements cumulés bruts (les retraits ne libèrent pas de place).
- **Plus-value globale** = (titres + cash) − apports nets. (≠ « gain » XTB, qui ne compare que les titres à leur prix de revient.)
- Cours : live → dernier cours connu (⚠️ « obsolète ») → prix de revient (⚠️ « estimé »). **Jamais 0** quand Yahoo échoue.
- Snapshot quotidien écrit à chaque visite **en semaine**, uniquement avec des données réelles et sans cours « estimé ».
- **Scénarios** : journal réel + opérations fictives rejouées par `calculs.appliquer_scenario` (fonction pure ⇒ le réel n'est jamais modifié).
  Saisie en montant (parts entières = `montant // cours`), quantité, ou « Tout » (vente). Pas de prévision de rendement.
- **Watchlist** : table `watchlist(isin → tickers)`. Les ISIN de `tickers` alimentent des listes déroulantes (détenus > watchlist > autres) + « Nouvel ISIN… ».

## 7. Analyse IA (Gemini) — faits vérifiés le 18/10/2026
- Modèle par défaut `gemini-3.6-flash` (surchargeable via secret `GEMINI_MODEL`). Endpoint REST
  `POST https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent`, clé dans l'en-tête `x-goog-api-key` (jamais dans l'URL).
- Gemini 3.6 Flash est présenté par Google comme **« génération précédente »** (toujours disponible en production) ; **Gemini 3.8 Flash** est le Flash le plus récent.
- Paramètres : **pas de `temperature`/`top_p`/`top_k`** (ignorés, bientôt refusés) ; `thinkingConfig.thinkingLevel = "low"` ; `maxOutputTokens = 4096` (la réflexion compte dans la sortie) ;
  sortie structurée via `responseMimeType=application/json` + `responseJsonSchema` (**repli automatique** sur `responseSchema` en majuscules si HTTP 400 « schema »).
- **Palier gratuit** : gratuit pour 3.6 Flash mais **les contenus peuvent servir à améliorer les produits Google** ; le palier payant l'exclut
  (3.6 Flash payant : 0,75 $/3,75 $ par M tokens jusqu'au 31/12/2026, puis 1,50 $/7,50 $). Quotas gratuits non publiés (visibles dans AI Studio).
  Un récapitulatif **tiers non vérifié** indique que depuis les conditions du 23/03/2026 seuls les services payants pourraient servir des utilisateurs finaux dans l'EEE : à vérifier si l'app devient multi-utilisateur.
- **Confidentialité** : seuls des **poids en %** (et nom/ISIN/secteur/PER/perf %) sont envoyés — aucun montant en €.
- Format de sortie garanti **côté code** (`llm.valider_resultat`) : 4 critères exactement une fois, note entière bornée 0-10, synthèse ≤ 20 mots, conclusion ≤ 35 mots.
  Critères (modifiables dans `llm.CRITERES`) : Diversification sectorielle · **CAPEX** · Diversification géographique · Croissance vs Rendement.
  ⚠️ « CAPEX » est **interprété** comme « exposition à l'intensité capitalistique (entreprises aux investissements lourds) » ; 10 = équilibre sain. À valider avec l'utilisateur.
- Garde-fous : max **5 analyses/jour** (`llm.MAX_APPELS_PAR_JOUR`), résultat stocké dans `analyses_ia` (affiché au rechargement, marqué « portefeuille modifié depuis » si l'empreinte change),
  prompt interdisant conseils d'achat/vente et prévisions, avertissement « pas un conseil en investissement ».

## 8. Secrets Streamlit (Settings › Secrets) — jamais dans le dépôt
```toml
APP_PASSWORD   = "longue phrase de passe"      # (ou ancien nom ADMIN_PASSWORD) ; absent ⇒ démo uniquement
SUPABASE_URL   = "https://xxxx.supabase.co"
SUPABASE_KEY   = "clé service_role"            # jamais la clé anon/publishable
GEMINI_API_KEY = "AIza..."                     # facultatif
# GEMINI_MODEL = "gemini-3.6-flash"            # facultatif
```
`VIEW_PASSWORD` (v2) est **supprimé** : désormais, sans connexion = démo.

## 9. Décisions écartées / mises de côté
- **Multi-utilisateur** : reporté. Plan si besoin : Supabase Auth (comptes créés à la main) + colonne `user_id` partout + RLS `user_id = auth.uid()`,
  client Supabase et caches **par session** (sinon fuite entre comptes), persistance de session sur mobile (cookie). Ne jamais coder soi-même une table de mots de passe.
- **Google Sheets** à la place de Postgres : étudié, **non retenu**. **Lovable** : non retenu. **Chatbot complet** : non (bouton one-shot seulement).
- Limite connue : `st.session_state` est perdu au rechargement ⇒ **reconnexion** à chaque rechargement de page (le gestionnaire de mots de passe du téléphone aide).

## 10. État de vérification (honnêteté)
| Élément | Statut |
|---|---|
| Calculs (PRM, cash, TWR, scénarios, répartitions…) | ✅ 47 tests unitaires (sandbox, pandas 3) |
| Appel Gemini (en-têtes, repli de schéma, erreurs HTTP, validation) | ✅ testé avec `requests.post` simulé — ⚠️ **jamais appelé pour de vrai** |
| App complète (démo, réel, IA, scénarios, watchlist, saisie, auth) | ✅ 31 vérifications e2e avec **faux Streamlit** + fausse base (`tests/e2e/parcours.py`) |
| Rendu réel Streamlit/Plotly sur mobile, connexion Supabase, Yahoo en direct | ❌ **non testés** (pas de réseau dans l'environnement de développement) |
| Verrou anti-force-brute | ✅ logique testée ; non testé en conditions réelles (état en mémoire, réinitialisé au redémarrage) |

Lancer les tests : `pip install -r requirements.txt pytest && pytest -q` puis `python tests/e2e/parcours.py` (affiche PASS/FAIL).

## 11. Mise en production de la v3 (étapes pour l'utilisateur)
1. Supabase › SQL Editor : **ré-exécuter `schema.sql` en entier** (idempotent) ⇒ crée `watchlist`, `scenarios`, `scenario_trades`, `analyses_ia`.
   (Si `seed_pea.sql` n'a pas encore été exécuté : l'exécuter **après** `schema.sql`.)
2. Streamlit Cloud › Secrets : ajouter `APP_PASSWORD` (et `GEMINI_API_KEY` pour l'IA).
3. Pousser sur GitHub : `app.py`, `calculs.py`, `db.py`, `donnees.py`, `schema.py`*, `demo.py`*, `llm.py`*, `auth.py`*, `requirements.txt` (* = nouveaux). Puis *Reboot app*.
4. Vérifier : sans connexion ⇒ bandeau « Mode démo » ; avec le mot de passe ⇒ données réelles ; bouton ✨ ⇒ 4 notes.
5. Si l'IA échoue : lire le message affiché (clé refusée, quota, modèle introuvable → essayer `GEMINI_MODEL = "gemini-3.8-flash"`).

## 12. Backlog possible (non demandé, à proposer seulement si pertinent)
- Rééquilibrage vers une allocation cible ; alertes de seuil ; export PDF/CSV de l'analyse ; persistance de session (cookie) ; multi-utilisateur (§9).
- Si Gemini 3.6 Flash est retiré : passer `GEMINI_MODEL` à un modèle plus récent (vérifier d'abord la page des tarifs Google, qui indique aussi le palier gratuit par modèle).

## 13. Conventions pour le modèle qui reprend
- Répondre **en français**, concis (≈ un écran de téléphone), **résultat d'abord**. Ne pas inventer : vérifier par recherche tout fait changeant (prix, noms de modèles, ISIN, conditions).
- Avant de livrer du code : **tester** (tests unitaires + `tests/e2e/parcours.py`), dire clairement ce qui n'a pas pu être testé.
- Ne jamais mettre de secret dans le dépôt ; ne jamais casser le principe « démo = aucun accès base ».
- Fournir ce fichier **à jour avec chaque réponse** et ajouter une ligne au §3 pour la demande traitée.

## 14. Prompt de reprise (à coller dans un autre modèle avec les fichiers du projet)
> Tu reprends le projet « Suivi PEA » décrit dans CONTEXTE.md (joint) avec le code du dépôt. Lis d'abord CONTEXTE.md en entier, puis
> `calculs.py` et `app.py`. Respecte §2 (contraintes), §6 (règles métier) et §13 (conventions). Réponds en français, concis, et mets à jour CONTEXTE.md à chaque livraison.
> Ma demande : …
---

# ÉVOLUTIONS — session d'octobre 2026 (Kimi) — lire avant de reprendre le projet

> Ajouté le 19/10/2026 · État du projet : **v6** · Fichiers modifiés depuis la v3 :
> `llm.py`, `app.py`, `demo.py`, `schema.py`, `schema.sql`, **+ `prompts.md` (nouveau)**.

## Résumé chronologique de cette session

9. **Analyse IA pour l'onglet Projet (v4)** : bouton « ✨ Analyser ce scénario » — le LLM note
   la structure PROJETÉE sur les 4 mêmes critères et liste (max 2) avantages/inconvénients
   par critère vs l'actuel. Nouvelle table `analyses_scen` (cascade sur `scenarios`, SQL v4 à
   exécuter dans Supabase). Quota : les 5 analyses/jour couvrent portefeuille + scénarios réunis.
10. **Dashboard (v4)** : zoom tactile désactivé partout (`PLOTLY` sans scrollZoom/doubleClick +
    `fixedrange=True` sur les axes des 4 graphiques cartésiens ; le treemap n'a pas d'axes).
    Noms épurés des parenthèses via `sans_parentheses()` (helper `app.py`) appliqué au
    comparatif actuel/projeté, au treemap et au bar chart de contribution. **Piège connu** :
    les parenthèses sont souvent AU MILIEU des noms d'ETF (« Amundi PEA Monde (MSCI World)
    UCITS ETF ») — une regex « fin de chaîne » ne suffit pas.
11. **Chatbot intégré (v5)** : discussion libre (`st.chat_input`, historique en
    `st.session_state`), contexte portefeuille injecté en instruction système (poids en %,
    jamais de €), dernière analyse IA incluse. Table `chat_log` (SQL v5), quota 20 msg/jour.
    LLM : `SYSTEME_CHAT` + `llm.discuter()` (historique tronqué aux 5 derniers échanges,
    réponse tronquée à 300 mots).
12. **Robustesse (v5.1)** : `KeyError: 'chat_log'` en mode démo (session navigateur créée
    avant l'ajout de la table) + serveur Streamlit pas rebooté après push. Corrigé :
    `lire_sur` utilise `SCHEMA.get(table, ["id"])`, `DemoStore` se met à niveau seul
    (`setdefault`) et `lire` tolère les tables absentes. **Toujours faire Manage app → Reboot
    sur Streamlit Cloud après un push.**
13. **Pistes discutées puis choix utilisateur (v6)** :
    - Chatbot étendu à l'onglet Projet : OUI (conversation par scénario, clé de session
      `chat_scen_{sid}`, garde-fou d'ambiance « tu discutes du scénario X, pas du réel »).
    - Fondamentaux dans le prompt : OUI (bloc `fondamentaux_block` : poids %, PER, capi, CA,
      dividendes perçus — ligne par ligne, issus de `fonds`/`yfinance`). Watchlist et
      scénarios DANS le prompt : reportés (coût tokens, peu utile).
    - Prompts externalisés : dans un fichier **`prompts.md` à la racine du dépôt** (PAS de
      secrets Streamlit). Sections `## analyse`, `## scenario`, `## chat` ; section absente =
      défaut codé dans `llm.py` (`charger_prompts_md`). Nécessite un reboot Streamlit.
    - **Ton moins frileux demandé** : l'IA doit se mouiller (avis tranché, préférences
      assumées) ; limite assumée conservée : pas d'ordre d'achat/vente, pas de prévision
      chiffrée, pas de fiscal. Le ton se règle désormais à la main dans `prompts.md`.

## État technique v6

- **Chatbot** : `bloc_chat(scenario=False|True, ...)` dans `app.py` (remplace `bloc_chatbot`) ;
  appelé dans l'onglet Portefeuille (actuel) et dans `onglet_projet` (scénario, après
  `bloc_ia_scenario`). Contexte : `contexte_chat()` + `fondamentaux_block()`.
- **Prompts** : `llm.py` charge `prompts.md` au démarrage (`PROMPTS_MD`) ; constantes
  `SYSTEME_DEFAUT`/`SYSTEME_SCENARIO_DEFAUT`/`SYSTEME_CHAT_DEFAUT` conservées comme repli.
- **Base SQL** : v4 (`analyses_scen`) + v5 (`chat_log`) à exécuter dans Supabase si ce n'est
  pas déjà fait — l'app reste utilisable sans, en mode dégradé avec avertissement.
- **À faire plus tard (idées notées)** : gate premium du chatbot (2e mot de passe via secret),
  watchlist/scénarios dans le contexte du chat, connecteur API Kimi (payant dès le 1er appel,
  ~1 $ min ; API compatible OpenAI — réécriture de `_payload`/`_generer` nécessaire).
- **Manuel d'utilisation du repo pour un nouvel assistant** : tout est dans ce fichier +
  `prompts.md` (ton IA) ; les secrets Streamlit attendus sont dans `.streamlit/secrets.toml.example` ;
  déployer = push GitHub + reboot Streamlit Cloud ; SQL = sections v4/v5 de `schema.sql`.
