-- Gäste-Portionen pro Plan-Eintrag: werden zu den mitessenden Personen addiert
-- (Portionsberechnung für Vorschau und Einkaufsliste).
SET search_path TO koch, public;

ALTER TABLE essensplan ADD COLUMN IF NOT EXISTS gaeste INTEGER NOT NULL DEFAULT 0;
