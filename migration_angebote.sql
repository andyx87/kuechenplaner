SET search_path TO koch, public;

-- Angebote: globale Admin-Angebote (account_id NULL) sind für ALLE sichtbar,
-- aber nur EIGENE (kontobezogene) Angebote sind änder-/löschbar.
ALTER TABLE angebote ALTER COLUMN account_id DROP NOT NULL;

-- Bestehende Angebote gehören dem Owner/Super-Admin → als globale Admin-Angebote freigeben.
UPDATE angebote SET account_id = NULL WHERE account_id = 1;

DROP POLICY IF EXISTS acc_isolation ON angebote;
DROP POLICY IF EXISTS angebote_select ON angebote;
DROP POLICY IF EXISTS angebote_mod ON angebote;
CREATE POLICY angebote_select ON angebote FOR SELECT
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id IS NULL
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
CREATE POLICY angebote_mod ON angebote FOR ALL
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);

-- F8: je User freischalten, ob eigene Angebote hochgeladen werden dürfen.
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS darf_angebote_upload boolean NOT NULL DEFAULT false;
