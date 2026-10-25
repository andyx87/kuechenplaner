-- Härtung: Row-Level-Security für das €-Guthaben-Ledger (Konto-Trennung auf DB-Ebene,
-- nicht nur im Code). Additiv – kein Datenverlust. Als postgres (Tabellen-Eigentümer).
SET search_path TO koch, public;

ALTER TABLE koch.guthaben_buchung ENABLE ROW LEVEL SECURITY;
ALTER TABLE koch.guthaben_buchung FORCE ROW LEVEL SECURITY;
CREATE POLICY acc_isolation ON koch.guthaben_buchung
  USING ((current_setting('app.bypass', true) = 'on') OR (account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer))
  WITH CHECK ((current_setting('app.bypass', true) = 'on') OR (account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer));
