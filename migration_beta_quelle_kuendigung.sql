-- Preisliste (Foto-Pack), Beta-Anmeldelinks und Kündigungs-Nachweis (§ 312k BGB).
--
-- EINGESPIELT: 26.07.2026 direkt auf Prod (kitchen-db, DB+Schema koch) durch den Owner.
-- Diese Datei ist die Repo-Fassung des dort ausgeführten SQL (konsolidiert die früheren
-- Entwürfe migration_preisliste.sql, migration_beta.sql, migration_kuendigung.sql, die
-- damit entfallen). Idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING) – erneutes
-- Ausführen ist gefahrlos. Muss vom Tabellen-Eigentümer laufen: `koch_app` ist nicht
-- Owner, die Startup-ensure_*-Blöcke in app/db.py scheitern auf Prod mit "must be owner"
-- (bewusst tolerant) und dienen nur lokalen/Dev-Setups.
--
-- NICHT Teil dieses Einspielstands, aber am selben Tag separat nachgezogen (26.07.2026):
--   · migration_zuletzt_aktiv.sql  (Aktivitäts-Stempel für die Beta-Inaktivitäts-Regel)
--   · migration_indexe.sql         (Betriebs-Indexe aus dem Admin-Review)

SET search_path TO koch, public;

-- ── 1) Preisliste: Foto-Pack in plattform_einstellung ─────────────────────────────
ALTER TABLE koch.plattform_einstellung
  ADD COLUMN IF NOT EXISTS foto_pack_cents   integer NOT NULL DEFAULT 1299;
ALTER TABLE koch.plattform_einstellung
  ADD COLUMN IF NOT EXISTS foto_pack_credits integer NOT NULL DEFAULT 75;

-- ── 2) Beta-Anmeldelinks je Kanal (/beta/<slug>) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS koch.beta_quelle (
  slug        text PRIMARY KEY,                       -- Teil der URL: /beta/<slug>
  name        text    NOT NULL,                       -- Anzeigename ("Reddit")
  max_konten  integer NOT NULL DEFAULT 50,            -- Platzkontingent des Kanals
  trial_tage  integer NOT NULL DEFAULT 90,            -- Länge des geschenkten Vollzugangs
  aktiv       boolean NOT NULL DEFAULT true,          -- Link abschaltbar, ohne ihn zu löschen
  erstellt    timestamptz NOT NULL DEFAULT now()
);

-- Herkunft am Konto: Kanal-Auswertung + Zählen der belegten Plätze (nur laufende Trials).
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS beta_quelle text;
CREATE INDEX IF NOT EXISTS account_beta_quelle_idx
  ON koch.account (beta_quelle) WHERE beta_quelle IS NOT NULL;

-- Startbelegung: NUR Facebook aktiv (50 Plätze, 90 Tage). Weitere Kanäle freischalten:
--   UPDATE koch.beta_quelle SET aktiv = true WHERE slug = 'reddit';
INSERT INTO koch.beta_quelle (slug, name, max_konten, trial_tage, aktiv) VALUES
  ('facebook',  'Facebook',  50, 90, true),
  ('reddit',    'Reddit',    20, 90, false),
  ('privat',    'Privat',    10, 90, false),
  ('allgemein', 'Allgemein', 10, 90, false)
ON CONFLICT (slug) DO NOTHING;

-- ── 3) Kündigungs-Nachweis (§ 312k BGB, append-only) ──────────────────────────────
CREATE TABLE IF NOT EXISTS koch.kuendigung (
  id            bigserial PRIMARY KEY,
  eingegangen   timestamptz NOT NULL DEFAULT now(),   -- Zugang: Datum + Uhrzeit (Nachweis)
  email         text        NOT NULL,                 -- Angabe des Verbrauchers (kleingeschrieben)
  name          text,
  vertrag       text,                                 -- Bezeichnung, z.B. "Topfplan-Abo"
  art           text        NOT NULL DEFAULT 'ordentlich',  -- 'ordentlich' | 'ausserordentlich'
  grund         text,
  zum_datum     date,                                 -- gewünschter Beendigungszeitpunkt (optional)
  account_id    integer,                              -- zugeordnet, falls die E-Mail bekannt ist
  wirkung       text,                                 -- 'stripe_periodenende' | 'kein_abo' | 'kein_konto' | 'fehler'
  vertrag_bis   date,                                 -- tatsächliches Vertragsende
  ip            text,
  bestaetigt_am timestamptz                           -- Zeitpunkt der Bestätigungs-Mail
);
CREATE INDEX IF NOT EXISTS kuendigung_email_idx       ON koch.kuendigung (lower(email));
CREATE INDEX IF NOT EXISTS kuendigung_eingegangen_idx ON koch.kuendigung (eingegangen DESC);

-- ── Rechte: das Backend läuft als koch_app (kein Owner) ───────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON koch.beta_quelle, koch.kuendigung TO koch_app;
GRANT USAGE ON SEQUENCE koch.kuendigung_id_seq TO koch_app;

-- Verifikation (informativ):
--   SELECT slug, aktiv, max_konten, trial_tage,
--          (SELECT count(*) FROM koch.account a
--            WHERE a.beta_quelle = q.slug AND a.trial_bis >= current_date) AS belegt
--     FROM koch.beta_quelle q ORDER BY slug;
--   SELECT foto_pack_cents, foto_pack_credits FROM koch.plattform_einstellung WHERE id = 1;
