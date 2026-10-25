-- Grobe Rubrik eines Angebots fuer die Uebersicht:
--   zutat        – Grund-/Master-Zutat zum Selberkochen (oben)
--   fertiggericht – verarbeitetes/fertiges Lebensmittel (TK-Pizza, Frucht-Joghurt, Snacks, Getraenke ...)
--   non_food     – kein Lebensmittel (Haushalt, Drogerie, Tierbedarf ...)
-- NULL = noch nicht klassifiziert; das Backend leitet dann heuristisch aus der
-- Kategorie ab.
SET search_path TO koch, public;

ALTER TABLE angebote ADD COLUMN IF NOT EXISTS art TEXT;
