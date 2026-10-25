-- F4: Idempotenz-Schlüssel für abo_buchung.
--
-- Problem: Die bisherige UNIQUE(account_id, zeitraum) diente als Idempotenz für den
-- automatischen Monats-Sweep, verschluckte aber auch berechtigte Mehrfach-Buchungen am
-- selben Tag (z. B. Abo abschließen + sofort upgraden) → stille Unter-Fakturierung.
--
-- Lösung: separater, nullable Idempotenz-Schlüssel. Nur der Sweep setzt ihn
-- ("monat:ACC:PERIODE"); nutzer-initiierte Buchungen bleiben NULL und werden immer
-- angehängt (NULLs kollidieren im partiellen Unique-Index nicht).
--
-- Idempotent ausführbar. Reihenfolge beachten (Spalte → Index → alte Constraint entfernen).

SET search_path TO koch, public;

ALTER TABLE abo_buchung ADD COLUMN IF NOT EXISTS idempotenz text;

CREATE UNIQUE INDEX IF NOT EXISTS abo_buchung_idem_uidx
    ON abo_buchung (idempotenz) WHERE idempotenz IS NOT NULL;

ALTER TABLE abo_buchung DROP CONSTRAINT IF EXISTS abo_buchung_account_id_zeitraum_key;
