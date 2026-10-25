SET search_path TO koch, public;

-- Rezept-Kategorien für bessere Filterung: Gang (Vorspeise/Hauptgericht/Nachspeise/…)
-- und Küche (feste Liste: Deutsch/Italienisch/Mediterran/Asiatisch/Mexikanisch/…).
-- Nullable: bestehende Rezepte ohne Kategorie erscheinen unter „Alle".
ALTER TABLE rezepte ADD COLUMN IF NOT EXISTS gang text;
ALTER TABLE rezepte ADD COLUMN IF NOT EXISTS kueche text;
