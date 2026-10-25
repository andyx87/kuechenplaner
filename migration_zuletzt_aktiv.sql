-- Aktivitäts-Stempel fürs Konto: userauth.context_from_token schreibt höchstens
-- stündlich; die Admin-Kennzahlen (aktive Haushalte 7/30 Tage) lesen ihn.
-- Idempotent, erneutes Ausführen gefahrlos. Die App legt die Spalte beim Start
-- ebenfalls an (db.ensure_index_schema), sofern sie die Rechte dazu hat.

SET search_path TO koch, public;

ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS zuletzt_aktiv timestamptz;
