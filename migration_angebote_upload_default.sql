-- Prospekt-/Angebots-Upload für ALLE freischalten (Flag wird zum Entzugs-Schalter).
--
-- Hintergrund: `darf_angebote_upload` stand auf DEFAULT false – der Upload war nur nach
-- Admin-Freischaltung je Nutzer sichtbar (Frontend-Button + Server-Gate). Das Gate stammte
-- aus der Zeit, als ein Prospekt-Import bis ~30 Cent kosten konnte; seit dem Modell-Fix
-- (Flash-Lite + Ausgabe-Deckel, PR #28) kostet ein 20-Seiten-Prospekt ~1,4 Cent, zusätzlich
-- greift ein Rate-Limit von 10 Importen/Tag je Nutzer (app/rest.py). Der Prospekt-Import ist
-- DAS beworbene Beta-Feature – ohne diese Migration sehen Tester den Button nicht.
--
-- Semantik danach: standardmäßig erlaubt; die Admin-Checkbox „Angebote-Upload" in der
-- Nutzerverwaltung wird zum ENTZUGS-Schalter für Missbrauchsfälle.
--
-- Idempotent, vom Owner auszuführen. Kein Deploy nötig – Frontend und Backend lesen das Flag.

SET search_path TO koch, public;

ALTER TABLE koch.app_user ALTER COLUMN darf_angebote_upload SET DEFAULT true;
UPDATE koch.app_user SET darf_angebote_upload = true;

-- Verifikation (informativ):
--   SELECT count(*) FILTER (WHERE darf_angebote_upload) AS erlaubt, count(*) AS gesamt
--     FROM koch.app_user;
