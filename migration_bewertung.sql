-- Migration: Rezept-Bewertungen (1–5 Sterne + Kommentar, eine pro Rezept)
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS bewertung (
    id          SERIAL PRIMARY KEY,
    rezept_id   INT NOT NULL UNIQUE REFERENCES rezepte(id) ON DELETE CASCADE,
    sterne      INT NOT NULL CHECK (sterne BETWEEN 1 AND 5),
    kommentar   TEXT,
    bewertet_am TIMESTAMPTZ NOT NULL DEFAULT now()
);
