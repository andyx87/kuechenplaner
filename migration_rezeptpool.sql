SET search_path TO koch, public;

-- F7: Veröffentlichungs-Flag (Super-Admin-Rezeptpool → Freigabe macht global sichtbar).
ALTER TABLE rezepte ADD COLUMN IF NOT EXISTS veroeffentlicht boolean NOT NULL DEFAULT false;

-- rezepte: veröffentlichte für ALLE sichtbar, aber nur eigene änder-/löschbar.
DROP POLICY IF EXISTS acc_isolation ON rezepte;
DROP POLICY IF EXISTS rezepte_select ON rezepte;
DROP POLICY IF EXISTS rezepte_mod ON rezepte;
CREATE POLICY rezepte_select ON rezepte FOR SELECT
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int
         OR veroeffentlicht);
CREATE POLICY rezepte_mod ON rezepte FOR ALL
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);

-- Kind-Tabellen: Zeilen veröffentlichter Rezepte mitlesen (Änderung weiter nur eigen).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['rezept_zutaten','rezept_geraete'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS acc_isolation ON %I', t);
    EXECUTE format('DROP POLICY IF EXISTS %I_select ON %I', t, t);
    EXECUTE format('DROP POLICY IF EXISTS %I_mod ON %I', t, t);
    EXECUTE format($f$CREATE POLICY %I_select ON %I FOR SELECT
      USING (current_setting('app.bypass', true) = 'on'
             OR account_id = nullif(current_setting('app.account_id', true), '')::int
             OR EXISTS (SELECT 1 FROM rezepte r WHERE r.id = rezept_id AND r.veroeffentlicht))$f$, t, t);
    EXECUTE format($f$CREATE POLICY %I_mod ON %I FOR ALL
      USING (current_setting('app.bypass', true) = 'on'
             OR account_id = nullif(current_setting('app.account_id', true), '')::int)
      WITH CHECK (current_setting('app.bypass', true) = 'on'
             OR account_id = nullif(current_setting('app.account_id', true), '')::int)$f$, t, t);
  END LOOP;
END $$;

-- bewertung: pro Konto eine Bewertung je Rezept (statt global eindeutig) → Ø über alle Nutzer.
ALTER TABLE bewertung DROP CONSTRAINT IF EXISTS bewertung_rezept_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS bewertung_acc_rezept ON bewertung (account_id, rezept_id);
