-- Guthaben-Einladungen: Admin erzeugt einmalig gültige Codes mit variablem Freiguthaben.
-- Globale Tabelle (wie tarif/plattform_einstellung), KEINE RLS – Zugriff nur über die
-- API-Endpunkte (Admin erstellt, beliebiges Konto löst per Code ein).
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.guthaben_einladung (
  code               text PRIMARY KEY,
  betrag_cents       integer NOT NULL CHECK (betrag_cents > 0),
  erstellt_von       integer REFERENCES koch.app_user(id) ON DELETE SET NULL,
  erstellt_am        timestamptz NOT NULL DEFAULT now(),
  eingeloest_am      timestamptz,
  eingeloest_account integer REFERENCES koch.account(id) ON DELETE SET NULL
);

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'koch_app') THEN
    GRANT SELECT, INSERT, UPDATE ON koch.guthaben_einladung TO koch_app;
  END IF;
END $$;
