-- Migration: manuell aufgeschriebene Einkaufslisten-Artikel
-- (zusaetzlich zu den aus Plan + Vorrat berechneten Positionen).
-- Global und persistent; werden per Loeschen wieder entfernt.
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS einkauf_extra (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    menge       NUMERIC,                       -- optional
    einheit     TEXT,                          -- optional
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
