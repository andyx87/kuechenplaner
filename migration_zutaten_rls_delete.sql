-- F12: zutaten-RLS – DELETE/UPDATE fail-open auf globale Katalog-Zeilen schließen.
--
-- Problem: Die bisherige FOR-ALL-Policy `acc_isolation` erlaubte im USING auch
-- `account_id IS NULL`. Da DELETE/UPDATE nur gegen USING (nicht WITH CHECK) geprüft
-- werden, konnte ein normaler Mandant globale Zutaten (account_id IS NULL) löschen –
-- cross-tenant-Datenverlust am gemeinsamen Katalog.
--
-- Lösung (wie bei koch.angebote): FOR ALL streng account-gebunden, Lesen globaler
-- Zeilen über eine separate FOR-SELECT-Policy.
--
-- Muss vom Tabellen-Eigentümer ausgeführt werden. Idempotent.

SET search_path TO koch, public;

DROP POLICY IF EXISTS acc_isolation ON koch.zutaten;
DROP POLICY IF EXISTS zutaten_mod ON koch.zutaten;
DROP POLICY IF EXISTS zutaten_select ON koch.zutaten;

CREATE POLICY zutaten_mod ON koch.zutaten
    USING (
        current_setting('app.bypass', true) = 'on'
        OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer
    )
    WITH CHECK (
        current_setting('app.bypass', true) = 'on'
        OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer
    );

CREATE POLICY zutaten_select ON koch.zutaten FOR SELECT
    USING (
        current_setting('app.bypass', true) = 'on'
        OR account_id IS NULL
        OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer
    );
