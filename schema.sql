-- À exécuter une fois dans Supabase : SQL Editor > New query > Run
-- Sécurité : RLS activé SANS aucune policy => la clé "anon" ne peut rien lire ni écrire.
-- L'application utilise la clé "service_role" (stockée uniquement dans les secrets Streamlit).

create table if not exists transactions (
  id       bigint generated always as identity primary key,
  date     date    not null,
  isin     text    not null,
  type     text    not null check (type in ('ACHAT', 'VENTE')),
  quantite numeric not null check (quantite > 0),
  prix     numeric not null check (prix >= 0),
  frais    numeric not null default 0 check (frais >= 0)
);

create table if not exists dividendes (
  id      bigint generated always as identity primary key,
  date    date    not null,
  isin    text    not null,
  montant numeric not null check (montant > 0)   -- net perçu, en €
);

create table if not exists versements (
  id      bigint generated always as identity primary key,
  date    date    not null,
  type    text    not null check (type in ('VERSEMENT', 'RETRAIT', 'PV_ANTERIEURE')),
  montant numeric not null check (montant > 0),
  libelle text
);

create table if not exists secteurs (
  isin    text primary key,
  secteur text not null
);

create table if not exists tickers (
  isin            text primary key,
  ticker          text not null,
  nom             text,
  dernier_prix    numeric,
  dernier_prix_at timestamptz
);

create table if not exists snapshots (
  date    date primary key,
  valeur  numeric not null,   -- valeur totale du PEA (titres + cash)
  apports numeric not null    -- apports nets cumulés
);

alter table transactions enable row level security;
alter table dividendes   enable row level security;
alter table versements   enable row level security;
alter table secteurs     enable row level security;
alter table tickers      enable row level security;
alter table snapshots    enable row level security;

-- =====================================================================================
-- v3 : watchlist, scénarios (portefeuille projet), analyses IA
-- (relançable sans risque sur une base existante : "if not exists")
-- =====================================================================================

create table if not exists watchlist (
  isin      text primary key references tickers(isin) on delete cascade,
  note      text,
  ajoute_le timestamptz not null default now()
);

create table if not exists scenarios (
  id        bigint generated always as identity primary key,
  nom       text    not null unique,
  versement numeric not null default 0 check (versement >= 0),   -- versement fictif du scénario
  cree_le   timestamptz not null default now()
);

create table if not exists scenario_trades (
  id          bigint generated always as identity primary key,
  scenario_id bigint  not null references scenarios(id) on delete cascade,
  isin        text    not null,
  type        text    not null check (type in ('ACHAT', 'VENTE')),
  quantite    numeric not null check (quantite > 0),
  prix        numeric not null check (prix >= 0),                -- cours au moment de la simulation
  cree_le     timestamptz not null default now()
);

create table if not exists analyses_ia (
  id         bigint generated always as identity primary key,
  cree_le    timestamptz not null default now(),
  modele     text,
  empreinte  text  not null,   -- signature de la composition analysée (évite les appels inutiles)
  resultat   jsonb not null
);

alter table watchlist       enable row level security;
alter table scenarios       enable row level security;
alter table scenario_trades enable row level security;
alter table analyses_ia     enable row level security;

-- =====================================================================================
-- v4 : analyses IA des scénarios (onglet Projet) — relançable sans risque
-- =====================================================================================

create table if not exists analyses_scen (
  id          bigint generated always as identity primary key,
  scenario_id bigint  not null references scenarios(id) on delete cascade,
  cree_le     timestamptz not null default now(),
  modele      text,
  empreinte   text  not null,   -- signature du scénario + des deux compositions analysées
  resultat    jsonb not null
);

alter table analyses_scen enable row level security;
