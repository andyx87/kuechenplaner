-- €-Guthaben-Ledger (append-only) als Buchungs-/Revisions-Basis. Saldo = Summe der
-- Buchungen; account.guthaben_cents bleibt als (transaktional gepflegter) Cache/Saldo.
-- App-Dimension (app) macht das Ledger für künftige Apps wiederverwendbar (Platform-Core).
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.guthaben_buchung (
  id           bigserial PRIMARY KEY,
  account_id   integer NOT NULL,
  app          text NOT NULL DEFAULT 'cooking',
  betrag_cents numeric(14,4) NOT NULL,            -- > 0 Gutschrift, < 0 Abzug
  typ          text NOT NULL,                     -- aufladung | nutzung | korrektur | eroeffnung | storno
  zweck        text,
  erstellt     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS guthaben_buchung_acc_idx ON koch.guthaben_buchung (account_id, erstellt);

-- RLS analog acc_isolation (läuft als koch_app, daher Eigentümer der Tabelle).
ALTER TABLE koch.guthaben_buchung ENABLE ROW LEVEL SECURITY;
ALTER TABLE koch.guthaben_buchung FORCE ROW LEVEL SECURITY;
CREATE POLICY acc_isolation ON koch.guthaben_buchung
  USING (((current_setting('app.bypass', true) = 'on') OR (account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer)))
  WITH CHECK (((current_setting('app.bypass', true) = 'on') OR (account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer)));

-- Backfill: bestehendes Guthaben als Eröffnungsbuchung übernehmen (Saldo = Summe stimmt danach).
SELECT set_config('app.bypass', 'on', false);
INSERT INTO koch.guthaben_buchung (account_id, app, betrag_cents, typ, zweck)
SELECT id, 'cooking', guthaben_cents, 'eroeffnung', 'Übernahme bestehendes Guthaben'
FROM koch.account
WHERE guthaben_cents <> 0;
