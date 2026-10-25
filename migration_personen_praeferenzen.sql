-- Migration: Personen-Präferenzen (Ernährungsform, Allergien, Abneigungen, Vorlieben)
-- Idempotent: kann mehrfach ausgeführt werden.
SET search_path TO koch, public;

ALTER TABLE person ADD COLUMN IF NOT EXISTS ernaehrung TEXT NOT NULL DEFAULT '';  -- z.B. omnivor / vegetarisch / vegan / pescetarisch
ALTER TABLE person ADD COLUMN IF NOT EXISTS allergien  TEXT NOT NULL DEFAULT '';  -- sicherheitskritisch, wird hart ausgeschlossen (z.B. "Laktose, Nüsse")
ALTER TABLE person ADD COLUMN IF NOT EXISTS mag_nicht  TEXT NOT NULL DEFAULT '';  -- Abneigungen, werden gemieden (z.B. "Pilze, Innereien")
ALTER TABLE person ADD COLUMN IF NOT EXISTS mag_gern   TEXT NOT NULL DEFAULT '';  -- Vorlieben, werden bevorzugt (z.B. "Pasta, Käse, mild")
