-- Guided Cooking: gecachte, KI-strukturierte Schritte je Rezept (Map Varianten-Signatur
-- -> Schritte-Array). Rezept-intrinsisch, daher global gecacht (kein Account-Bezug).
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS zubereitung_guided jsonb;
