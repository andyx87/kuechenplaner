-- Nutzungsbasiertes Abo-Modell (Claude-Stil): 3 Stufen + Pay-as-you-go.
-- Stufen unterscheiden sich nur durch das inkludierte Monatsbudget; zusätzlich
-- Stunden- und Wochenlimit (Rate-Limiting). Alle Beträge in marked-up Cent
-- (gleiche Einheit wie ai_nutzung.kosten_cents). Ersetzt die Personen-Pauschale.
SET search_path TO koch, public;

-- Tarif-Definitionen: globale Config (wie plattform_einstellung), KEINE RLS.
CREATE TABLE IF NOT EXISTS tarif (
  code                text PRIMARY KEY,            -- 'basis' | 'plus' | 'max' | 'payg'
  name                text NOT NULL,
  ist_payg            boolean NOT NULL DEFAULT false,
  preis_cents         integer NOT NULL DEFAULT 0,  -- Monatsgebühr (0 bei payg)
  budget_cents        integer NOT NULL DEFAULT 0,  -- inkludiertes Monatsbudget; 0 = keins
  stunden_limit_cents integer,                     -- NULL = kein Stundenlimit
  wochen_limit_cents  integer,                     -- NULL = kein Wochenlimit
  sortierung          integer NOT NULL DEFAULT 0,
  aktiv               boolean NOT NULL DEFAULT true
);

-- Seed-Defaults (super-admin editierbar): Budget ≈ 3× Gebühr, Stundenlimit ≈ 10 %,
-- Wochenlimit ≈ 40 % des Monatsbudgets.
INSERT INTO tarif (code,name,ist_payg,preis_cents,budget_cents,stunden_limit_cents,wochen_limit_cents,sortierung) VALUES
  ('basis','Basis',          false,  499,  1500,  150,  600, 1),
  ('plus', 'Plus',           false,  999,  4000,  400, 1600, 2),
  ('max',  'Max',            false, 1999, 10000, 1000, 4000, 3),
  ('payg', 'Pay-as-you-go',  true,     0,     0, NULL, NULL, 4)
ON CONFLICT (code) DO NOTHING;

-- Aktueller Tarif des Kontos + Pay-as-you-go-Überlauf (pro Zyklus).
-- Default 'payg' → Bestandskonten verhalten sich exakt wie bisher (Guthaben-Abzug).
ALTER TABLE account ADD COLUMN IF NOT EXISTS tarif_code text NOT NULL DEFAULT 'payg' REFERENCES tarif(code);
ALTER TABLE account ADD COLUMN IF NOT EXISTS payg_overage boolean NOT NULL DEFAULT false;
ALTER TABLE account ADD COLUMN IF NOT EXISTS payg_overage_seit date;

-- App-Rolle (verbindet als koch_app, NOSUPERUSER) braucht Lese-/Schreibrecht auf tarif.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'koch_app') THEN
    GRANT SELECT, UPDATE ON koch.tarif TO koch_app;
  END IF;
END $$;
