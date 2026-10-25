-- Migration: Grundzutaten (Wasser, Salz, Gewuerze, Oel ...) dauerhaft markieren.
-- Solche Zutaten landen nie auf der Einkaufsliste und gelten im Rezept-Check
-- nicht als "fehlend". Default false -> Verhalten bleibt unveraendert, bis
-- eine Zutat ausgeblendet wird.
SET search_path TO koch, public;

ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS grundzutat BOOLEAN NOT NULL DEFAULT false;
