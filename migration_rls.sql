SET search_path TO koch, public;

-- zutaten: kontobezogene Eindeutigkeit statt global (global = account_id NULL)
ALTER TABLE zutaten DROP CONSTRAINT IF EXISTS zutaten_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS zutaten_acc_name_key ON zutaten (coalesce(account_id, 0), name);

-- Private Tabellen: Default + RLS (nur eigenes Konto, bypass für Wartung)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'vorrat','bewertung','einkauf_extra','einkaufstag','essensplan','geraete','geraete_heute',
    'geraete_heute_stand','lagerort','person','person_abwesenheit_regel','personen_heute',
    'rezept_geraete','rezept_zutaten','rezepte','angebote']
  LOOP
    EXECUTE format('ALTER TABLE %I ALTER COLUMN account_id SET DEFAULT nullif(current_setting(''app.account_id'', true), '''')::int', t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS acc_isolation ON %I', t);
    EXECUTE format($f$CREATE POLICY acc_isolation ON %I
      USING (current_setting('app.bypass', true) = 'on'
             OR account_id = nullif(current_setting('app.account_id', true), '')::int)
      WITH CHECK (current_setting('app.bypass', true) = 'on'
             OR account_id = nullif(current_setting('app.account_id', true), '')::int)$f$, t);
  END LOOP;
END $$;

-- zutaten: geteilt (account_id NULL = global, für alle sichtbar)
ALTER TABLE zutaten ALTER COLUMN account_id SET DEFAULT nullif(current_setting('app.account_id', true), '')::int;
ALTER TABLE zutaten ENABLE ROW LEVEL SECURITY;
ALTER TABLE zutaten FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON zutaten;
CREATE POLICY acc_isolation ON zutaten
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id IS NULL
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
