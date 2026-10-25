SET search_path TO koch, public;

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
