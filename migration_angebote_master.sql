-- Verknuepft Angebote mit einer generischen Master-Zutat, damit der Angebots-
-- Abgleich mit Rezepten/Vorrat/Einkaufsliste ueber denselben Master laeuft wie
-- die Vorratsartikel. Nullable: nicht jedes Angebot ist eine Kochzutat.
SET search_path TO koch, public;

ALTER TABLE angebote
    ADD COLUMN IF NOT EXISTS master_zutat_id INTEGER REFERENCES zutaten(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_angebote_master_zutat ON angebote (master_zutat_id);
