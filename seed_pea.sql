-- Initialisation du PEA d'après la capture XTB (à exécuter UNE fois, après schema.sql)
-- Supabase > SQL Editor > New query > coller > Run
--
-- Hypothèses à connaître :
--  * Dates : inconnues sur la capture -> current_date. Corrigez-les ensuite dans l'app
--    (Saisie > Corriger / supprimer) ou remplacez current_date ci-dessous par la vraie date.
--  * Une seule transaction par ligne, au PRM affiché par XTB (même PRM qu'avec plusieurs achats).
--  * Versements = 2 400 € (150 000 - plafond restant 147 600).
--  * PV antérieure = 200 € + 0,87 € d'écart, pour que le cash colle à celui de XTB (5,32 €).
--    Mettez 200 si vous préférez le montant « pur » : le cash affiché sera alors de 4,45 €.

do $$
begin
  if exists (select 1 from transactions) or exists (select 1 from versements) then
    raise exception 'Tables non vides : script annulé pour éviter les doublons.';
  end if;

  -- ISIN -> ticker Yahoo (évite la résolution automatique) + dernier cours de la capture
  insert into tickers (isin, ticker, nom, dernier_prix, dernier_prix_at) values
    ('FR0013412012', 'PAASI.PA', 'Amundi PEA Asie Émergente (MSCI Emerging Asia) Screened', 37.66,  now()),
    ('FR0013346681', 'OBLI.PA',  'Amundi PEA Euro Court Terme',                             9.82,   now()),
    ('FR001400U5Q4', 'DCAM.PA',  'Amundi PEA Monde (MSCI World)',                           6.3275, now())
  on conflict (isin) do update
    set ticker = excluded.ticker, nom = excluded.nom,
        dernier_prix = excluded.dernier_prix, dernier_prix_at = excluded.dernier_prix_at;

  -- Secteurs affichés dans le treemap
  insert into secteurs (isin, secteur) values
    ('FR0013412012', 'Asie émergente'),
    ('FR0013346681', 'Monétaire'),
    ('FR001400U5Q4', 'Monde')
  on conflict (isin) do update set secteur = excluded.secteur;

  -- Positions (quantité @ PRM de la capture)
  insert into transactions (date, isin, type, quantite, prix, frais) values
    (current_date, 'FR0013412012', 'ACHAT',  15, 38.8040, 0),
    (current_date, 'FR0013346681', 'ACHAT',   9,  9.8172, 0),
    (current_date, 'FR001400U5Q4', 'ACHAT', 314,  6.1310, 0);

  -- Trésorerie
  insert into versements (date, type, montant, libelle) values
    (current_date, 'VERSEMENT',     2400.00, 'Versements cumulés (150 000 - plafond restant 147 600)'),
    (current_date, 'PV_ANTERIEURE',  200.87, 'Plus-values antérieures réinvesties (200 € + écart d''arrondi XTB)');
end $$;
