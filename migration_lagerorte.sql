-- Migration: Lagerorte als eigene Tabelle + Verknüpfung am Vorrat
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS lagerort (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sortierung  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE vorrat
  ADD COLUMN IF NOT EXISTS lagerort_id INT REFERENCES lagerort(id) ON DELETE SET NULL;

-- Bestehende Freitext-Orte in Lagerorte übernehmen und verknüpfen
INSERT INTO lagerort (name)
SELECT DISTINCT btrim(ort) FROM vorrat
WHERE ort IS NOT NULL AND btrim(ort) <> ''
ON CONFLICT (name) DO NOTHING;

UPDATE vorrat v SET lagerort_id = l.id
FROM lagerort l
WHERE v.lagerort_id IS NULL AND v.ort IS NOT NULL AND btrim(v.ort) = l.name;

-- Ein paar Standard-Lagerorte (nur falls noch nicht vorhanden)
INSERT INTO lagerort (name, sortierung) VALUES
  ('Kühlschrank', 1), ('Tiefkühler', 2), ('Vorratsschrank', 3)
ON CONFLICT (name) DO NOTHING;
