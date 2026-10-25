-- Produktbild-Ausschnitt aus dem Prospekt je Angebot (JPEG als Data-URL).
ALTER TABLE angebote ADD COLUMN IF NOT EXISTS bild text;
