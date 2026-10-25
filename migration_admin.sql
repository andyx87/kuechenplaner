SET search_path TO koch, public;

-- Plattform-weite Einstellungen (nur Super-Admin änderbar), eine Zeile.
CREATE TABLE IF NOT EXISTS plattform_einstellung (
  id                 int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  abo_grund_cents    int NOT NULL DEFAULT 300,
  abo_mitglied_cents int NOT NULL DEFAULT 150,
  api_markup_prozent numeric(6,2) NOT NULL DEFAULT 25
);
INSERT INTO plattform_einstellung (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Einladungen (Main-User lädt Familienmitglieder ins eigene Konto), RLS-isoliert.
CREATE TABLE IF NOT EXISTS einladung (
  id             bigserial PRIMARY KEY,
  account_id     int NOT NULL DEFAULT nullif(current_setting('app.account_id', true), '')::int,
  email          citext NOT NULL,
  token          text NOT NULL UNIQUE,
  rolle          text NOT NULL DEFAULT 'member',
  status         text NOT NULL DEFAULT 'offen',   -- offen | eingeloest | storniert
  eingeladen_von int,
  erstellt       timestamptz NOT NULL DEFAULT now(),
  eingeloest_am  timestamptz
);
CREATE INDEX IF NOT EXISTS einladung_acc ON einladung (account_id, status);

ALTER TABLE einladung ENABLE ROW LEVEL SECURITY;
ALTER TABLE einladung FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON einladung;
CREATE POLICY acc_isolation ON einladung
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
