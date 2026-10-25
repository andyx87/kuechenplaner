SET search_path TO koch, public;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS account (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  abo_status TEXT NOT NULL DEFAULT 'aktiv',
  guthaben_cents INT NOT NULL DEFAULT 0,
  einstellungen JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app_user (
  id SERIAL PRIMARY KEY,
  email CITEXT UNIQUE NOT NULL,
  password_hash TEXT,
  name TEXT NOT NULL DEFAULT '',
  plattform_rolle TEXT,
  aktiv BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_mitglied (
  account_id INT NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  rolle TEXT NOT NULL DEFAULT 'member',
  beigetreten_am TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, user_id)
);
CREATE TABLE IF NOT EXISTS app_session (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  account_id INT REFERENCES account(id) ON DELETE SET NULL,
  token_hash TEXT UNIQUE NOT NULL,
  ablauf TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO account (id, name) VALUES (1, 'Mein Haushalt') ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('account','id'), GREATEST((SELECT max(id) FROM account), 1));

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'vorrat','bewertung','einkauf_extra','einkaufstag','essensplan','geraete','geraete_heute',
    'geraete_heute_stand','lagerort','person','person_abwesenheit_regel','personen_heute',
    'rezept_geraete','rezept_zutaten','rezepte','angebote']
  LOOP
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS account_id INT REFERENCES account(id)', t);
    EXECUTE format('UPDATE %I SET account_id = 1 WHERE account_id IS NULL', t);
  END LOOP;
END $$;

-- zutaten bleiben global (account_id NULL = für alle Accounts sichtbar)
ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS account_id INT REFERENCES account(id);
