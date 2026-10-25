-- Migration: Kanonisierung von Zutaten (Master-Zutat per Referenz).
-- Eine Zutat mit kanonische_zutat_id = NULL ist ihr eigener Master.
-- Markenprodukte (z.B. "Bertolli Olivenöl") zeigen per kanonische_zutat_id
-- auf eine Master-Zutat (z.B. "Olivenöl"). Matching laeuft ueber den Master.
-- kanonisch_fixiert schuetzt manuelle Zuordnungen vor dem KI-Batch.
SET search_path TO koch, public;

ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS kanonische_zutat_id INTEGER
    REFERENCES zutaten(id) ON DELETE SET NULL;
ALTER TABLE zutaten ADD COLUMN IF NOT EXISTS kanonisch_fixiert BOOLEAN NOT NULL DEFAULT false;

-- Eine Zutat darf nicht auf sich selbst zeigen.
-- (Sanfter Schutz; harte Constraints koennten Altdaten blockieren.)
CREATE INDEX IF NOT EXISTS idx_zutaten_kanonisch ON zutaten(kanonische_zutat_id);
