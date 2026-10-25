-- Aktivitäts-Stempel fürs Konto – Grundlage der Beta-Inaktivitäts-Regel (BETA_INAKTIV_TAGE):
-- userauth.context_from_token schreibt höchstens stündlich; der tägliche Job
-- _beta_inaktiv_loop stuft Beta-Konten ohne Aktivität zurück und gibt den Platz frei.
-- OHNE diese Spalte ist die Regel bewusst wirkungslos (fail-safe: niemand wird zurückgestuft).
--
-- EINGESPIELT: 26.07.2026 auf Prod (kitchen-db, Schema koch) durch den Owner –
-- in einer Transaktion mit ON_ERROR_STOP=1. Idempotent, erneutes Ausführen gefahrlos.
-- Die Inaktivitäts-Regel ist damit SCHARF.

SET search_path TO koch, public;

ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS zuletzt_aktiv timestamptz;
