-- Betriebs-Indexe für Instanzen mit vielen Konten.
-- Rein ADDITIV und idempotent. Muss vom Tabellen-Eigentümer laufen.

SET search_path TO koch, public;

-- Login, account_fuer_user, Nutzerlisten-Join: der PK beginnt mit account_id und trägt
-- Lookups über user_id nicht.
CREATE INDEX IF NOT EXISTS account_mitglied_user_idx ON koch.account_mitglied (user_id);

-- Personen je Konto.
CREATE INDEX IF NOT EXISTS person_acc_idx            ON koch.person (account_id);

-- Session-Invalidierung bei Passwort-Reset/Sperrung auf wachsender Session-Tabelle.
CREATE INDEX IF NOT EXISTS app_session_user_idx      ON koch.app_session (user_id);

-- Admin-Kennzahlen neu_7d/neu_30d und Nutzerlisten-Sortierung "neu".
CREATE INDEX IF NOT EXISTS app_user_created_idx      ON koch.app_user (created_at DESC);
