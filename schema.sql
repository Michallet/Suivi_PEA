-- Schéma Supabase (PostgreSQL) de Suivi PEA — à exécuter dans : SQL Editor > New query > Run.
-- Idempotent : sans risque sur une base déjà en place (rien n'est supprimé ni réécrit).
-- L'app utilise la clé service_role côté serveur uniquement (Streamlit Secrets) ; chaque ligne porte
-- le user_id du compte (theo, demo, …) et db.py filtre toutes les requêtes dessus.

create table if not exists transactions (
  id       bigint generated always as identity primary key,
  user_id  text    not null,
  date     date    not null,
  isin     text    not null,
  type     text    not null check (type in ('ACHAT', 'VENTE')),
  quantite numeric not null check (quantite > 0),
  prix     numeric not null check (prix >= 0),
  frais    numeric not null default 0 check (frais >= 0)
);

create table if not exists dividendes (
  id       bigint generated always as identity primary key,
  user_id  text    not null,
  date     date    not null,
  isin     text    not null,
  montant  numeric not null check (montant > 0) -- net perçu, en €
);

create table if not exists versements (
  id       bigint generated always as identity primary key,
  user_id  text    not null,
  date     date    not null,
  type     text    not null check (type in ('VERSEMENT', 'RETRAIT', 'PV_ANTERIEURE')),
  montant  numeric not null check (montant > 0),
  libelle  text
);

create table if not exists secteurs (
  user_id text not null,
  isin    text not null,
  secteur text not null,
  primary key (user_id, isin)
);

create table if not exists tickers (
  user_id           text not null,
  isin              text not null,
  ticker            text not null,
  nom               text,
  dernier_prix      numeric,
  dernier_prix_at   timestamptz,
  concurrent_isin   text, -- un concurrent coté par titre (comparaison des multiples)
  concurrent_ticker text,
  concurrent_nom    text,
  primary key (user_id, isin)
);

create table if not exists snapshots (
  user_id text    not null,
  date    date    not null,
  valeur  numeric not null, -- valeur totale du PEA (titres + cash)
  apports numeric not null, -- apports nets cumulés
  primary key (user_id, date)
);

create table if not exists watchlist (
  user_id   text not null,
  isin      text not null,
  note      text,
  ajoute_le timestamptz not null default now(),
  primary key (user_id, isin),
  constraint watchlist_ticker_fk foreign key (user_id, isin)
    references tickers (user_id, isin) on delete cascade
);

create table if not exists scenarios (
  id        bigint generated always as identity primary key,
  user_id   text    not null,
  nom       text    not null,
  versement numeric not null default 0 check (versement >= 0), -- versement fictif du scénario
  cree_le   timestamptz not null default now(),
  unique (user_id, nom),
  unique (user_id, id)
);

create table if not exists scenario_trades (
  id          bigint generated always as identity primary key,
  user_id     text    not null,
  scenario_id bigint  not null,
  isin        text    not null,
  type        text    not null check (type in ('ACHAT', 'VENTE')),
  quantite    numeric not null check (quantite > 0),
  prix        numeric not null check (prix >= 0), -- cours au moment de la simulation
  cree_le     timestamptz not null default now(),
  constraint scenario_trades_owner_fk foreign key (user_id, scenario_id)
    references scenarios (user_id, id) on delete cascade
);

create table if not exists analyses_ia (
  id        bigint generated always as identity primary key,
  user_id   text    not null,
  cree_le   timestamptz not null default now(),
  modele    text,
  empreinte text    not null, -- signature de la composition analysée
  resultat  jsonb   not null
);

create table if not exists analyses_scen (
  id          bigint generated always as identity primary key,
  user_id     text    not null,
  scenario_id bigint  not null,
  cree_le     timestamptz not null default now(),
  modele      text,
  empreinte   text    not null, -- signature du scénario et des compositions
  resultat    jsonb   not null,
  constraint analyses_scen_owner_fk foreign key (user_id, scenario_id)
    references scenarios (user_id, id) on delete cascade
);

create table if not exists chat_log ( -- une ligne par message envoyé au chat (quota journalier)
  id      bigint generated always as identity primary key,
  user_id text    not null,
  cree_le timestamptz not null default now()
);

-- Row Level Security activée sur toutes les tables (la clé service_role la contourne côté serveur).
alter table transactions    enable row level security;
alter table dividendes      enable row level security;
alter table versements      enable row level security;
alter table secteurs        enable row level security;
alter table tickers         enable row level security;
alter table snapshots       enable row level security;
alter table watchlist       enable row level security;
alter table scenarios       enable row level security;
alter table scenario_trades enable row level security;
alter table analyses_ia     enable row level security;
alter table analyses_scen   enable row level security;
alter table chat_log        enable row level security;

-- Base créée avant l'ajout du concurrent : ces colonnes sont ajoutées si elles manquent.
alter table tickers add column if not exists concurrent_isin   text;
alter table tickers add column if not exists concurrent_ticker text;
alter table tickers add column if not exists concurrent_nom    text;

-- Optionnel : colonnes « url » héritées de l'ancienne fonction « lien de publication » (plus lues).
-- alter table tickers   drop column if exists url;
-- alter table watchlist drop column if exists url;
