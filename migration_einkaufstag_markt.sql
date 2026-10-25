-- Markt (Haendler) je Einkaufstag: wo an dem Tag eingekauft wird. NULL = frei
-- gelassen -> keine Angebots-Logik fuer diesen Tag.
SET search_path TO koch, public;
ALTER TABLE einkaufstag ADD COLUMN IF NOT EXISTS haendler TEXT;
