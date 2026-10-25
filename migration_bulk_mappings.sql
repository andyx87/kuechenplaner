SET search_path TO koch, public;

-- 1. Neue generische Master-Zutaten anlegen (Komplett Umlaut-frei!)
INSERT INTO zutaten (name, standard_einheit, kanonisch_fixiert) VALUES
('Fischkonserve', 'Dose', true),
('Pumpernickel', 'g', true),
('Linsen (braun)', 'g', true),
('Glutenfreies Brot', 'g', true),
('Schnittbohnen (Glas)', 'ml', true),
('Dosen-Eintopf', 'g', true),
('Schokoriegel / Snacks', 'g', true),
('Knabber-Brezeln / Salzstangen', 'g', true),
('Schoko-Waffeln', 'g', true),
('Eiscreme (Fuerst Pueckler)', 'ml', true),
('Eiscreme (Schokolade)', 'ml', true),
('Eiscreme (Walnuss)', 'ml', true),
('Aufbackbroetchen', 'g', true),
('Marmelade', 'g', true),
('Senf (scharf)', 'ml', true),
('Senf (mild / suess)', 'g', true),
('Frische Eier', 'Stueck', true),
('Artischocken (Glas)', 'g', true)
ON CONFLICT (name) DO UPDATE SET kanonisch_fixiert = true;

-- 2. Bulk-Kanonisierung der verbleibenden ungemappten Artikel
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Fischkonserve' LIMIT 1), kanonisch_fixiert = true WHERE id IN (33, 34, 35, 36);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Pumpernickel' LIMIT 1), kanonisch_fixiert = true WHERE id = 185;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Linsen (braun)' LIMIT 1), kanonisch_fixiert = true WHERE id = 218;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Glutenfreies Brot' LIMIT 1), kanonisch_fixiert = true WHERE id IN (178, 184);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Schnittbohnen (Glas)' LIMIT 1), kanonisch_fixiert = true WHERE id = 197;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Dosen-Eintopf' LIMIT 1), kanonisch_fixiert = true WHERE id IN (220, 224);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Schokoriegel / Snacks' LIMIT 1), kanonisch_fixiert = true WHERE id IN (188, 193, 172);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Knabber-Brezeln / Salzstangen' LIMIT 1), kanonisch_fixiert = true WHERE id IN (154, 181, 173);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Schoko-Waffeln' LIMIT 1), kanonisch_fixiert = true WHERE id IN (190, 191);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Eiscreme (Fuerst Pueckler)' LIMIT 1), kanonisch_fixiert = true WHERE id IN (231, 232);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Eiscreme (Schokolade)' LIMIT 1), kanonisch_fixiert = true WHERE id IN (230, 247);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Eiscreme (Walnuss)' LIMIT 1), kanonisch_fixiert = true WHERE id = 229;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Aufbackbroetchen' LIMIT 1), kanonisch_fixiert = true WHERE id = 238;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Marmelade' LIMIT 1), kanonisch_fixiert = true WHERE id IN (135, 145);
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Senf (scharf)' LIMIT 1), kanonisch_fixiert = true WHERE id = 210;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Senf (mild / suess)' LIMIT 1), kanonisch_fixiert = true WHERE id = 211;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Frische Eier' LIMIT 1), kanonisch_fixiert = true WHERE id = 133;
UPDATE zutaten SET kanonische_zutat_id = (SELECT id FROM zutaten WHERE name = 'Artischocken (Glas)' LIMIT 1), kanonisch_fixiert = true WHERE id = 216;
UPDATE zutaten SET kanonische_zutat_id = 15, kanonisch_fixiert = true WHERE id = 277;
UPDATE zutaten SET kanonische_zutat_id = 14, kanonisch_fixiert = true WHERE id = 47;