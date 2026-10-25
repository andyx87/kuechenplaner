-- Haushalts-Einladungen ohne Mailzwang: E-Mail wird optional (Link-only-Einladungen;
-- der Eingeladene gibt seine E-Mail beim Annehmen selbst an).
ALTER TABLE koch.einladung ALTER COLUMN email DROP NOT NULL;
