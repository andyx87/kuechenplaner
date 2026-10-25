-- €-Guthaben-Ledger (append-only). Als postgres importiert (koch_app hat kein CREATE im
-- Schema). RLS-Policy nimmt der Cloud-SQL-Import nicht an → Konto-Trennung erfolgt im Code
-- (buche()/Reads filtern immer per account_id). RLS später per Owner-/psql-Kanal nachrüsten.
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.guthaben_buchung (
  id           bigserial PRIMARY KEY,
  account_id   integer NOT NULL,
  app          text NOT NULL DEFAULT 'cooking',
  betrag_cents numeric(14,4) NOT NULL,
  typ          text NOT NULL,
  zweck        text,
  erstellt     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS guthaben_buchung_acc_idx ON koch.guthaben_buchung (account_id, erstellt);

GRANT SELECT, INSERT, UPDATE, DELETE ON koch.guthaben_buchung TO koch_app;
GRANT USAGE, SELECT ON SEQUENCE koch.guthaben_buchung_id_seq TO koch_app;

-- Backfill: bestehendes Guthaben als Eröffnungsbuchung (Saldo = Summe stimmt danach).
INSERT INTO koch.guthaben_buchung (account_id, app, betrag_cents, typ, zweck)
SELECT a.id, 'cooking', a.guthaben_cents, 'eroeffnung', 'Übernahme bestehendes Guthaben'
FROM koch.account a
WHERE a.guthaben_cents <> 0
  AND NOT EXISTS (SELECT 1 FROM koch.guthaben_buchung b WHERE b.account_id = a.id);
