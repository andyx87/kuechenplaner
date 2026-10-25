-- Fehlende Indexe für Betrieb mit 300-500 Konten (Befund UX-/Admin-Review 2026-07-26,
-- gemessen an einer Seed-DB mit 500 Konten / 5.000 Nutzern / 450.000 ai_nutzung-Zeilen).
--
-- Bereits vorhanden und ausreichend: ai_nutzung(account_id, erstellt DESC) für alle
-- konto-gescopten Billing-Abfragen; guthaben_buchung, abo_buchung und kuendigung sind
-- bereits passend indiziert.
--
-- Rein ADDITIV und idempotent. Muss vom Tabellen-Eigentümer laufen.
-- EINGESPIELT: 26.07.2026 auf Prod (kitchen-db, Schema koch); alle 5 Indexe verifiziert.

SET search_path TO koch, public;

-- Kontoübergreifende Admin-Dashboard-Aggregationen (adminstats: Kosten/Nutzung je Zeitraum).
CREATE INDEX IF NOT EXISTS ai_nutzung_erstellt_idx   ON koch.ai_nutzung (erstellt DESC);

-- Login, account_fuer_user, Nutzerlisten-Join, Kündigungs-Kontosuche: der PK beginnt mit
-- account_id und trägt Lookups über user_id nicht.
CREATE INDEX IF NOT EXISTS account_mitglied_user_idx ON koch.account_mitglied (user_id);

-- Personen je Konto (abo_sweep je Konto, Abrechnungsseite; gemessen 19 -> 3 Buffer).
CREATE INDEX IF NOT EXISTS person_acc_idx            ON koch.person (account_id);

-- Session-Invalidierung bei Passwort-Reset/Sperrung auf wachsender Session-Tabelle.
CREATE INDEX IF NOT EXISTS app_session_user_idx      ON koch.app_session (user_id);

-- Admin-Kennzahlen neu_7d/neu_30d und Nutzerlisten-Sortierung "neu".
CREATE INDEX IF NOT EXISTS app_user_created_idx      ON koch.app_user (created_at DESC);
