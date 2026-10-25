-- Multi-Tenant-Fix (analog geraete): UNIQUE pro Konto statt global.
SET search_path TO koch, public;
ALTER TABLE koch.einkaufstag DROP CONSTRAINT IF EXISTS einkaufstag_datum_key;
ALTER TABLE koch.einkaufstag ADD CONSTRAINT einkaufstag_account_datum_key UNIQUE (account_id, datum);
ALTER TABLE koch.lagerort DROP CONSTRAINT IF EXISTS lagerort_name_key;
ALTER TABLE koch.lagerort ADD CONSTRAINT lagerort_account_name_key UNIQUE (account_id, name);
