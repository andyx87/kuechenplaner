SET search_path TO koch, public;

-- Monatliche Abo-Grundpauschale: ein Eintrag pro Konto und Monat (idempotent).
CREATE TABLE IF NOT EXISTS abo_buchung (
  id           bigserial PRIMARY KEY,
  account_id   integer NOT NULL DEFAULT nullif(current_setting('app.account_id', true), '')::int,
  zeitraum     date NOT NULL,            -- erster Tag des abgerechneten Monats
  mitglieder   integer NOT NULL DEFAULT 1,
  betrag_cents integer NOT NULL,
  gebucht      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, zeitraum)
);
CREATE INDEX IF NOT EXISTS abo_buchung_acc_zeit ON abo_buchung (account_id, zeitraum DESC);

ALTER TABLE abo_buchung ENABLE ROW LEVEL SECURITY;
ALTER TABLE abo_buchung FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON abo_buchung;
CREATE POLICY acc_isolation ON abo_buchung
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
