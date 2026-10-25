-- Migration: Personen-/Haushaltsmodell (Mengen-/Budgetplanung)
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS person (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    rolle          TEXT NOT NULL DEFAULT 'erwachsener',  -- 'erwachsener' | 'kind'
    kcal_ziel      INT,
    eiweiss_pct    INT NOT NULL DEFAULT 30,
    fett_pct       INT NOT NULL DEFAULT 30,
    kh_pct         INT NOT NULL DEFAULT 40,
    portionsfaktor NUMERIC(4,2) NOT NULL DEFAULT 1.0,
    aktiv          BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
