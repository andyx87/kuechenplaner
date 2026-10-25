SET search_path TO koch, public;

-- Mehrere Händler je Einkaufstag (1:n). einkaufstag bleibt als „ist Einkaufstag"-Flag
-- (einkaufstag.haendler = erster/primärer Händler für Abwärtskompatibilität).
CREATE TABLE IF NOT EXISTS einkaufstag_haendler (
  id          serial PRIMARY KEY,
  datum       date NOT NULL,
  haendler    text NOT NULL,
  account_id  int REFERENCES account(id) ON DELETE CASCADE
                DEFAULT nullif(current_setting('app.account_id', true), '')::int,
  UNIQUE (account_id, datum, haendler)
);

ALTER TABLE einkaufstag_haendler ENABLE ROW LEVEL SECURITY;
ALTER TABLE einkaufstag_haendler FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON einkaufstag_haendler;
CREATE POLICY acc_isolation ON einkaufstag_haendler
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);

-- Bestehende Einzel-Händler übernehmen
INSERT INTO einkaufstag_haendler (datum, haendler, account_id)
SELECT datum, haendler, account_id FROM einkaufstag
WHERE haendler IS NOT NULL AND haendler <> ''
ON CONFLICT DO NOTHING;
