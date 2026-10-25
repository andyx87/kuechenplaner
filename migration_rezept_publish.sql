-- Rezept-Veröffentlichungs-Regeln: importierte Kopien nicht veröffentlichbar,
-- jedes Rezept nur EINMAL veröffentlichbar. Spalten + Backfill.
SET search_path TO koch, public;

ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS importiert boolean NOT NULL DEFAULT false;
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS je_veroeffentlicht boolean NOT NULL DEFAULT false;

-- RLS umgehen, um bestehende Daten kontoübergreifend zu markieren.
SELECT set_config('app.bypass', 'on', false);

-- Bereits veröffentlichte Rezepte gelten als 'einmal veröffentlicht'.
UPDATE koch.rezepte SET je_veroeffentlicht = true WHERE veroeffentlicht = true;

-- Bestehende Importe markieren (Kopien tragen quelle='Öffentliches Rezept').
UPDATE koch.rezepte SET importiert = true WHERE quelle = 'Öffentliches Rezept';
