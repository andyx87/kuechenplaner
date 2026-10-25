-- Migration: Alltag-/Situativ-Flag + Tagesstand fuer die Geraeteauswahl
SET search_path TO koch, public;

ALTER TABLE geraete
  ADD COLUMN IF NOT EXISTS standard boolean NOT NULL DEFAULT true;

CREATE TABLE IF NOT EXISTS geraete_heute_stand (
    id          INT PRIMARY KEY DEFAULT 1,
    stand_datum DATE NOT NULL,
    CONSTRAINT geraete_heute_stand_einzeilig CHECK (id = 1)
);

-- Beispiel: vorhandene situative Geraete markieren (anpassen/auskommentiert lassen)
-- UPDATE geraete SET standard = false WHERE name ILIKE '%grill%';
