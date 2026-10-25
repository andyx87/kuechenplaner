-- Platform-Core: App-Registry + App-Zuordnung der Konten, damit der Admin mehrere Apps
-- zentral verwalten/auswerten kann. Globale Config-Tabelle (wie tarif, KEINE RLS).
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.app (
  code     text PRIMARY KEY,
  name     text NOT NULL,
  aktiv    boolean NOT NULL DEFAULT true,
  erstellt timestamptz NOT NULL DEFAULT now()
);
INSERT INTO koch.app (code, name) VALUES ('cooking', 'Küchenassistent')
  ON CONFLICT (code) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON koch.app TO koch_app;

-- Jedes Konto gehört zu genau einer App (Default: cooking = bestehende Daten).
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS app text NOT NULL DEFAULT 'cooking';
