-- S-7 (Sicherheits-Audit 2026-09-11, AND-22 / Auftrag AND-35): Reservierungszeilen für das
-- v4-Kontingent-Modell.
--
-- Problem bisher: Das v4-Gate (billing.limit_pruefen_v4) prüfte Monatskontingent und
-- Bild-Credits, danach lief der langlaufende Modell-/Bildaufruf, und ERST danach wurde die
-- Nutzung protokolliert bzw. der Credit gezogen – ohne Konto-Lock dazwischen. N parallele
-- Anfragen kamen alle durch dieselbe Prüfung; Monatskontingent und Bild-Credits ließen sich
-- überziehen (Kosten entstehen real bei Vertex AI). Im PAYG-Pfad ist genau das seit F3 über
-- eine Vorab-Reservierung gelöst.
--
-- Lösung: Pro laufendem KI-/Bildaufruf eine Zeile hier. Sie zählt schon im Gate gegen das
-- Monatskontingent (billing._monats_zaehler_v4) und wird unter `SELECT … FOR UPDATE` auf der
-- Kontozeile angelegt (billing.gate_v4). Erfolg: die echte `ai_nutzung`-Zeile ersetzt sie in
-- derselben Transaktion. Fehlschlag (Timeout/Exception/leere Antwort): billing.freigeben_v4()
-- löscht sie und erstattet einen gezogenen Bild-Credit. Crash: `ablauf` lässt die Zeile
-- verfallen, das nächste Gate räumt sie auf und bucht einen Credit zurück.
--
-- Rein ADDITIV, idempotent ausführbar. Muss vom Tabellen-Eigentümer (postgres) laufen –
-- `koch_app` ist nicht Owner und hat kein CREATE im Schema. Bitte VOR dem Deploy des
-- Backends einspielen (fehlt die Tabelle, läuft das Gate übergangsweise ohne Reservierung
-- weiter und meldet das als ERROR im Log).
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.ki_reservierung (
  id         bigserial PRIMARY KEY,
  account_id integer NOT NULL
             DEFAULT nullif(current_setting('app.account_id', true), '')::int
             REFERENCES koch.account(id) ON DELETE CASCADE,   -- Konto weg => Reservierungen weg
  user_id    integer,                                        -- wer den Aufruf gestartet hat
  zweck      text NOT NULL,                                  -- 'chat', 'rezept-bild', …
  art        text NOT NULL DEFAULT 'ki',                     -- 'ki' | 'bild' | 'bild_credit'
  erstellt   timestamptz NOT NULL DEFAULT now(),
  ablauf     timestamptz NOT NULL DEFAULT now() + interval '10 minutes'  -- Crash-Schutz
);

-- Gate zählt/äumt pro Konto; der Index hält das kurz (Tabelle bleibt klein: nur laufende
-- Aufrufe plus höchstens ein paar verfallene Zeilen).
CREATE INDEX IF NOT EXISTS ki_reservierung_acc_ablauf_idx
  ON koch.ki_reservierung (account_id, ablauf);

-- Mandantentrennung wie bei ai_nutzung (FORCE, damit auch der Tabellen-Owner unter die
-- Policy fällt); `app.bypass` nur für vertrauenswürdige Wartungsjobs.
ALTER TABLE koch.ki_reservierung ENABLE ROW LEVEL SECURITY;
ALTER TABLE koch.ki_reservierung FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON koch.ki_reservierung;
CREATE POLICY acc_isolation ON koch.ki_reservierung
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);

-- ── Rechte: das Backend läuft als koch_app (kein Owner) ───────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON koch.ki_reservierung TO koch_app;
GRANT USAGE, SELECT ON SEQUENCE koch.ki_reservierung_id_seq TO koch_app;

-- Verifikation (informativ):
--   \d koch.ki_reservierung                     -- Spalten, FK, Index, FORCE RLS
--   SELECT art, count(*) FROM koch.ki_reservierung GROUP BY art;   -- im Leerbetrieb leer
--   SELECT count(*) FROM koch.ki_reservierung WHERE ablauf <= now();  -- verfallene Zeilen
