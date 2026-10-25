-- Migration: Personen-Tagesauswahl (wer isst heute mit)
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS personen_heute (
  id         SERIAL PRIMARY KEY,
  person_id  INT NOT NULL UNIQUE REFERENCES person(id) ON DELETE CASCADE
);

-- Initiale Füllung: alle aktiven Personen als "essen heute mit"
INSERT INTO personen_heute (person_id)
SELECT id FROM person WHERE aktiv = true
ON CONFLICT DO NOTHING;
