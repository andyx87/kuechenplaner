-- Migration: Wochenplaner (essensplan + einkaufstag)
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS essensplan (
    id          SERIAL PRIMARY KEY,
    datum       DATE NOT NULL,
    mahlzeit    TEXT NOT NULL DEFAULT 'Abendessen',
    rezept_id   INT REFERENCES rezepte(id) ON DELETE SET NULL,
    notiz       TEXT,
    person_ids  INT[] NOT NULL DEFAULT '{}',
    portionen   NUMERIC(5,2),
    erstellt_am TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS einkaufstag (
    id    SERIAL PRIMARY KEY,
    datum DATE NOT NULL UNIQUE
);
