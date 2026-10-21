-- À exécuter dans Supabase : SQL Editor > New query > Run.
-- Migration multi-utilisateur v8. Les lignes déjà présentes sont attribuées au compte "theo".
-- L'application utilise SUPABASE_KEY (service_role) uniquement côté serveur via Streamlit Secrets.

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
  user_id         text not null,
  isin            text not null,
  ticker          text not null,
  nom             text,
  dernier_prix    numeric,
  dernier_prix_at timestamptz,
  url             text, -- URL de publication financière (v6)
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
  user_id  text not null,
  isin     text not null,
  note     text,
  url      text,
  ajoute_le timestamptz not null default now(),
  primary key (user_id, isin)
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
  cree_le     timestamptz not null default now()
);

create table if not exists analyses_ia (
  id         bigint generated always as identity primary key,
  user_id    text    not null,
  cree_le    timestamptz not null default now(),
  modele     text,
  empreinte  text    not null, -- signature de la composition analysée
  resultat   jsonb   not null
);

create table if not exists analyses_scen (
  id          bigint generated always as identity primary key,
  user_id     text    not null,
  scenario_id bigint  not null,
  cree_le     timestamptz not null default now(),
  modele      text,
  empreinte   text    not null, -- signature du scénario et des compositions
  resultat    jsonb   not null
);

create table if not exists chat_log (
  id      bigint generated always as identity primary key,
  user_id text    not null,
  cree_le timestamptz not null default now()
);

-- RLS reste activé. Le serveur Streamlit emploie la clé service_role, jamais exposée au navigateur.
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
alter table analyses_scen  enable row level security;
alter table chat_log        enable row level security;

-- v6 : URL de publication financière — compatible avec les bases plus anciennes.
alter table tickers   add column if not exists url text;
alter table watchlist add column if not exists url text;

-- =====================================================================================
-- v8 : migration idempotente depuis le schéma mono-utilisateur historique.
-- Tout enregistrement existant est conservé et attribué à theo ; aucun contenu n'est supprimé.
-- =====================================================================================
alter table transactions    add column if not exists user_id text;
alter table dividendes      add column if not exists user_id text;
alter table versements      add column if not exists user_id text;
alter table secteurs        add column if not exists user_id text;
alter table tickers         add column if not exists user_id text;
alter table snapshots       add column if not exists user_id text;
alter table watchlist       add column if not exists user_id text;
alter table scenarios       add column if not exists user_id text;
alter table scenario_trades add column if not exists user_id text;
alter table analyses_ia     add column if not exists user_id text;
alter table analyses_scen  add column if not exists user_id text;
alter table chat_log        add column if not exists user_id text;

update transactions    set user_id = 'theo' where user_id is null;
update dividendes      set user_id = 'theo' where user_id is null;
update versements      set user_id = 'theo' where user_id is null;
update secteurs        set user_id = 'theo' where user_id is null;
update tickers         set user_id = 'theo' where user_id is null;
update snapshots       set user_id = 'theo' where user_id is null;
update watchlist       set user_id = 'theo' where user_id is null;
update scenarios       set user_id = 'theo' where user_id is null;
update scenario_trades set user_id = 'theo' where user_id is null;
update analyses_ia     set user_id = 'theo' where user_id is null;
update analyses_scen  set user_id = 'theo' where user_id is null;
update chat_log        set user_id = 'theo' where user_id is null;

alter table transactions    alter column user_id set not null;
alter table dividendes      alter column user_id set not null;
alter table versements      alter column user_id set not null;
alter table secteurs        alter column user_id set not null;
alter table tickers         alter column user_id set not null;
alter table snapshots       alter column user_id set not null;
alter table watchlist       alter column user_id set not null;
alter table scenarios       alter column user_id set not null;
alter table scenario_trades alter column user_id set not null;
alter table analyses_ia     alter column user_id set not null;
alter table analyses_scen  alter column user_id set not null;
alter table chat_log        alter column user_id set not null;

-- Retire les anciennes clés étrangères simples avant de passer aux clés composites.
alter table watchlist       drop constraint if exists watchlist_isin_fkey;
alter table watchlist       drop constraint if exists watchlist_ticker_fk;
alter table scenario_trades drop constraint if exists scenario_trades_scenario_id_fkey;
alter table scenario_trades drop constraint if exists scenario_trades_owner_fk;
alter table analyses_scen  drop constraint if exists analyses_scen_scenario_id_fkey;
alter table analyses_scen  drop constraint if exists analyses_scen_owner_fk;

-- Les ISIN et dates sont uniques à l'intérieur d'un compte, et non plus dans toute la base.
alter table tickers   drop constraint if exists tickers_pkey;
alter table tickers   add constraint tickers_pkey primary key (user_id, isin);
alter table secteurs  drop constraint if exists secteurs_pkey;
alter table secteurs  add constraint secteurs_pkey primary key (user_id, isin);
alter table snapshots drop constraint if exists snapshots_pkey;
alter table snapshots add constraint snapshots_pkey primary key (user_id, date);
alter table watchlist drop constraint if exists watchlist_pkey;
alter table watchlist add constraint watchlist_pkey primary key (user_id, isin);

alter table scenarios drop constraint if exists scenarios_nom_key;
alter table scenarios drop constraint if exists scenarios_user_id_nom_key;
alter table scenarios add constraint scenarios_user_id_nom_key unique (user_id, nom);
alter table scenarios drop constraint if exists scenarios_user_id_id_key;
alter table scenarios add constraint scenarios_user_id_id_key unique (user_id, id);

alter table watchlist add constraint watchlist_ticker_fk foreign key (user_id, isin)
  references tickers(user_id, isin) on delete cascade;
alter table scenario_trades add constraint scenario_trades_owner_fk foreign key (user_id, scenario_id)
  references scenarios(user_id, id) on delete cascade;
alter table analyses_scen add constraint analyses_scen_owner_fk foreign key (user_id, scenario_id)
  references scenarios(user_id, id) on delete cascade;

-- v9.2 : un concurrent coté par titre (comparaison des multiples). À exécuter une fois ; idempotent.
alter table tickers add column if not exists concurrent_isin   text;
alter table tickers add column if not exists concurrent_ticker text;
alter table tickers add column if not exists concurrent_nom    text;
