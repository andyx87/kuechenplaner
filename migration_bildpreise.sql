SET search_path TO koch, public;

-- Bildgenerierung mit zwei Stufen (schnell/standard) – Preise je Stufe konfigurierbar.
ALTER TABLE plattform_einstellung
  ADD COLUMN IF NOT EXISTS bild_schnell_cents  int NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS bild_standard_cents int NOT NULL DEFAULT 9;
