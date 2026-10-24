-- Migration 001 (refonte 2026-10) : additive et idempotente — peut être rejouée sans risque.
-- À exécuter dans Supabase : SQL Editor > New query > coller > Run. Aucune table existante n'est modifiée
-- (seulement des index ajoutés). Tant qu'elle n'est pas exécutée, l'application fonctionne avec ses replis.

-- 1. Cache marché partagé : données PUBLIQUES de Yahoo (cours, fondamentaux), aucune donnée de compte.
create table if not exists marche_cache (
  cle       text primary key,          -- « cours:MC.PA », « fonds:MC.PA »
  categorie text not null,
  valeur    jsonb not null,
  maj       timestamptz not null default now()
);
alter table marche_cache enable row level security;  -- aucune politique : accès par la clé service_role seulement

-- 2. Compteurs d'usage de l'IA (quotas par compte et plafond global).
create table if not exists usage_ia (
  id      bigint generated always as identity primary key,
  user_id text not null,
  nature  text not null check (nature in ('analyse', 'chat', 'capture', 'concurrent')),
  cree_le timestamptz not null default now()
);
alter table usage_ia enable row level security;
create index if not exists usage_ia_user_jour on usage_ia (user_id, cree_le);
create index if not exists usage_ia_jour      on usage_ia (cree_le);

-- 3. Index sur user_id des tables à clé `id` (les autres ont déjà (user_id, …) comme clé primaire).
create index if not exists transactions_user_date    on transactions (user_id, date);
create index if not exists dividendes_user_date      on dividendes (user_id, date);
create index if not exists versements_user_date      on versements (user_id, date);
create index if not exists scenario_trades_user_scen on scenario_trades (user_id, scenario_id);
create index if not exists analyses_ia_user_id       on analyses_ia (user_id, id);
create index if not exists analyses_scen_user_scen   on analyses_scen (user_id, scenario_id, id);
create index if not exists chat_log_user_jour        on chat_log (user_id, cree_le);

-- 4. Chargement d'un compte en UN aller-retour (les tables qui grossissent sont bornées).
create or replace function pea_charger_compte(p_user text)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  select jsonb_build_object(
    'transactions',    coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.date, x.id) from transactions x where x.user_id = p_user), '[]'::jsonb),
    'dividendes',      coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.date, x.id) from dividendes x where x.user_id = p_user), '[]'::jsonb),
    'versements',      coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.date, x.id) from versements x where x.user_id = p_user), '[]'::jsonb),
    'secteurs',        coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.isin) from secteurs x where x.user_id = p_user), '[]'::jsonb),
    'tickers',         coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.isin) from tickers x where x.user_id = p_user), '[]'::jsonb),
    'snapshots',       coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.date) from snapshots x where x.user_id = p_user), '[]'::jsonb),
    'watchlist',       coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.ajoute_le) from watchlist x where x.user_id = p_user), '[]'::jsonb),
    'partage',         coalesce((select jsonb_agg(to_jsonb(x) - 'user_id') from partage x where x.user_id = p_user), '[]'::jsonb),
    'scenarios',       coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.id) from scenarios x where x.user_id = p_user), '[]'::jsonb),
    'scenario_trades', coalesce((select jsonb_agg(to_jsonb(x) - 'user_id' order by x.id) from scenario_trades x where x.user_id = p_user), '[]'::jsonb),
    'analyses_ia',     coalesce((select jsonb_agg(to_jsonb(x) - 'user_id') from (select * from analyses_ia where user_id = p_user order by id desc limit 1) x), '[]'::jsonb),
    'analyses_scen',   coalesce((select jsonb_agg(to_jsonb(x) - 'user_id') from (select * from analyses_scen where user_id = p_user order by id desc limit 200) x), '[]'::jsonb)
  );
$$;
revoke all on function pea_charger_compte(text) from public;
revoke all on function pea_charger_compte(text) from anon, authenticated;
grant execute on function pea_charger_compte(text) to service_role;
