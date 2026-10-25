-- Entfernt die Abrechnungs-/Abo-/Beta-Teile aus einer Datenbank, die noch mit dem
-- früheren (kommerziellen) Schema angelegt wurde. Frische Installationen brauchen das
-- NICHT: schema.sql enthält diese Tabellen/Spalten nicht mehr.
--
-- Idempotent (IF EXISTS). Muss vom Tabellen-Eigentümer laufen, z. B.:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migration_ohne_abrechnung.sql
-- ACHTUNG: löscht die Abrechnungsdaten (Guthaben-Buchungen, Abo-Buchungen,
-- KI-Nutzungsprotokoll, Kündigungsnachweise) unwiderruflich. Vorher sichern, falls
-- diese Daten noch aufbewahrt werden müssen.

SET search_path TO koch, public;

BEGIN;

DROP TABLE IF EXISTS koch.ki_reservierung;
DROP TABLE IF EXISTS koch.stripe_event;
DROP TABLE IF EXISTS koch.guthaben_buchung;
DROP TABLE IF EXISTS koch.guthaben_einladung;
DROP TABLE IF EXISTS koch.abo_buchung;
DROP TABLE IF EXISTS koch.ai_nutzung;
DROP TABLE IF EXISTS koch.kuendigung;
DROP TABLE IF EXISTS koch.beta_quelle;
DROP TABLE IF EXISTS koch.plattform_einstellung;
DROP TABLE IF EXISTS koch.rechtstext;

ALTER TABLE koch.account
  DROP COLUMN IF EXISTS abo_status,
  DROP COLUMN IF EXISTS guthaben_cents,
  DROP COLUMN IF EXISTS tarif_code,
  DROP COLUMN IF EXISTS payg_overage,
  DROP COLUMN IF EXISTS payg_overage_seit,
  DROP COLUMN IF EXISTS abo_bezahlt_bis,
  DROP COLUMN IF EXISTS abo_gekuendigt,
  DROP COLUMN IF EXISTS abo_naechster_tarif,
  DROP COLUMN IF EXISTS abo_typ,
  DROP COLUMN IF EXISTS bild_credits,
  DROP COLUMN IF EXISTS stripe_customer_id,
  DROP COLUMN IF EXISTS stripe_subscription_id,
  DROP COLUMN IF EXISTS trial_bis,
  DROP COLUMN IF EXISTS beta_quelle,
  DROP COLUMN IF EXISTS app;

DROP TABLE IF EXISTS koch.tarif;
DROP TABLE IF EXISTS koch.app;

ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS zuletzt_aktiv timestamptz;

COMMIT;
