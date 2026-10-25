SET search_path TO koch, public;

-- Fiktives Startguthaben 50 € (Beta): Default für neue Konten + Bestand backfillen.
ALTER TABLE account ALTER COLUMN guthaben_cents SET DEFAULT 5000;
UPDATE account SET guthaben_cents = 5000 WHERE guthaben_cents = 0;

-- KI-Nutzungs-Ledger: ein Eintrag pro KI-Aufruf, kontobezogen (RLS).
CREATE TABLE IF NOT EXISTS ai_nutzung (
  id                bigserial PRIMARY KEY,
  account_id        integer NOT NULL DEFAULT nullif(current_setting('app.account_id', true), '')::int,
  user_id           integer,
  zweck             text NOT NULL,
  modell            text,
  prompt_tokens     integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  total_tokens      integer NOT NULL DEFAULT 0,
  kosten_cents      integer NOT NULL DEFAULT 0,
  erstellt          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_nutzung_acc_zeit ON ai_nutzung (account_id, erstellt DESC);

ALTER TABLE ai_nutzung ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_nutzung FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON ai_nutzung;
CREATE POLICY acc_isolation ON ai_nutzung
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
