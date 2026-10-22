-- À exécuter UNE FOIS après schema.sql pour remplir le compte demo avec des données fictives.
-- Ce script ne supprime rien. Il s'arrête si le compte demo possède déjà des transactions.
DO $$
DECLARE
  sid bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM transactions WHERE user_id = 'demo') THEN
    RAISE NOTICE 'Le compte demo contient déjà des transactions : aucune donnée ajoutée.';
    RETURN;
  END IF;

  INSERT INTO tickers (user_id, isin, ticker, nom, dernier_prix, dernier_prix_at) VALUES
    ('demo','FR001400U5Q4','DCAM.PA','Amundi PEA Monde (MSCI World)',6.31,now()),
    ('demo','FR0000121014','MC.PA','LVMH',612.40,now()),
    ('demo','FR0000120271','TTE.PA','TotalEnergies',57.90,now()),
    ('demo','FR0000120073','AI.PA','Air Liquide',172.50,now()),
    ('demo','FR0000121972','SU.PA','Schneider Electric',238.00,now()),
    ('demo','FR0000120578','SAN.PA','Sanofi',86.40,now()),
    ('demo','NL0010273215','ASML.AS','ASML',702.00,now()),
    ('demo','NL0000235190','AIR.PA','Airbus',168.00,now()),
    ('demo','FR0013412012','PAASI.PA','Amundi PEA Asie Émergente (MSCI EM Asia)',37.66,now()),
    ('demo','FR0000052292','RMS.PA','Hermès',2380.00,now()),
    ('demo','FR0000120321','OR.PA','L''Oréal',372.00,now()),
    ('demo','FR0000131104','BNP.PA','BNP Paribas',74.80,now())
  ON CONFLICT (user_id, isin) DO UPDATE SET
    ticker=EXCLUDED.ticker, nom=EXCLUDED.nom, dernier_prix=EXCLUDED.dernier_prix,
    dernier_prix_at=EXCLUDED.dernier_prix_at;

  INSERT INTO secteurs (user_id, isin, secteur) VALUES
    ('demo','FR001400U5Q4','Monde'),
    ('demo','FR0000121014','Luxe'),
    ('demo','FR0000120271','Énergie'),
    ('demo','FR0000120073','Industrie'),
    ('demo','FR0000121972','Industrie'),
    ('demo','FR0000120578','Santé'),
    ('demo','NL0010273215','Technologie'),
    ('demo','NL0000235190','Industrie'),
    ('demo','FR0013412012','Asie émergente')
  ON CONFLICT (user_id, isin) DO UPDATE SET secteur=EXCLUDED.secteur;

  INSERT INTO transactions (user_id, date, isin, type, quantite, prix, frais) VALUES
    ('demo', current_date - 280, 'FR001400U5Q4','ACHAT',120,5.90,0),
    ('demo', current_date - 270, 'FR0000121014','ACHAT',4,590.00,0),
    ('demo', current_date - 250, 'FR0000120271','ACHAT',25,55.20,0),
    ('demo', current_date - 230, 'FR0000120073','ACHAT',8,168.00,0),
    ('demo', current_date - 200, 'FR0000121972','ACHAT',5,215.00,0),
    ('demo', current_date - 170, 'FR0000120578','ACHAT',14,89.00,0),
    ('demo', current_date - 150, 'NL0010273215','ACHAT',2,640.00,0),
    ('demo', current_date - 120, 'FR0013412012','ACHAT',20,36.50,0),
    ('demo', current_date - 110, 'NL0000235190','ACHAT',6,130.00,0),
    ('demo', current_date - 40,  'NL0000235190','VENTE',3,152.00,0);

  INSERT INTO dividendes (user_id, date, isin, montant) VALUES
    ('demo', current_date - 95, 'FR0000120073',22.40),
    ('demo', current_date - 60, 'FR0000120271',31.50);

  INSERT INTO versements (user_id, date, type, montant, libelle) VALUES
    ('demo', current_date - 300,'VERSEMENT',9000.00,'Versement initial'),
    ('demo', current_date - 125,'VERSEMENT',2000.00,NULL),
    ('demo', current_date - 300,'PV_ANTERIEURE',250.00,'Gains antérieurs');

  INSERT INTO watchlist (user_id, isin, note, ajoute_le) VALUES
    ('demo','FR0000052292','Luxe : attendre un meilleur point d''entrée ?',now()),
    ('demo','FR0000120321','Défensif, dividende régulier',now()),
    ('demo','FR0000131104','Banque, valorisation basse',now())
  ON CONFLICT (user_id, isin) DO NOTHING;

  INSERT INTO scenarios (user_id, nom, versement)
  VALUES ('demo','Exemple : renforcer la santé',0)
  ON CONFLICT (user_id, nom) DO UPDATE SET nom=EXCLUDED.nom
  RETURNING id INTO sid;

  IF NOT EXISTS (SELECT 1 FROM scenario_trades WHERE user_id='demo' AND scenario_id=sid) THEN
    INSERT INTO scenario_trades (user_id, scenario_id, isin, type, quantite, prix, cree_le) VALUES
      ('demo',sid,'FR0000120321','ACHAT',3.0,372.00,now()),
      ('demo',sid,'NL0010273215','VENTE',1.0,702.00,now());
  END IF;

  -- Historique illustratif hebdomadaire (fictif) pour rendre l'onglet Historique exploitable.
  INSERT INTO snapshots (user_id, date, valeur, apports)
  SELECT 'demo', current_date - j,
         round((10200 + (280-j) * 5.5 + sin(j * 0.12) * 140)::numeric, 2),
         CASE WHEN j > 125 THEN 9000.00 ELSE 11000.00 END
  FROM generate_series(0, 280, 7) AS g(j)
  ON CONFLICT (user_id, date) DO NOTHING;

  RAISE NOTICE 'Portefeuille fictif demo initialisé.';
END $$;
