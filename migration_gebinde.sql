-- Gebinde-Groesse pro Artikel: "1 standard_einheit (z.B. Packung) = gebinde_menge gebinde_einheit (g/ml)".
-- Erlaubt das Umrechnen von Vorrat-Gebinden auf die Rezept-Basiseinheit beim Matching.
SET search_path TO koch, public;

ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS gebinde_menge NUMERIC;
ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS gebinde_einheit TEXT;
