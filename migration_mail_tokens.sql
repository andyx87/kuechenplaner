-- Phase 2 Mailversand: Passwort-Reset + E-Mail-Bestätigung.
-- Token-Tabellen ohne account_id (kontofreie Vorgänge vor Login) – kein RLS nötig;
-- Zugriff im Backend über acquire(bypass=True), Lookup nur per geheimem Token-Hash.
SET search_path TO koch, public;

-- E-Mail-Verifizierungs-Flag am Nutzer
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS email_verifiziert boolean NOT NULL DEFAULT false;

-- Passwort-Reset-Tokens (sha256-Hash, begrenzte Gültigkeit, einmalig)
CREATE TABLE IF NOT EXISTS passwort_reset (
  id          serial PRIMARY KEY,
  user_id     integer NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash  text NOT NULL UNIQUE,
  ablauf      timestamptz NOT NULL,
  benutzt     boolean NOT NULL DEFAULT false,
  erstellt    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS passwort_reset_token_idx ON passwort_reset (token_hash);

-- E-Mail-Bestätigungs-Tokens
CREATE TABLE IF NOT EXISTS email_verify (
  id          serial PRIMARY KEY,
  user_id     integer NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash  text NOT NULL UNIQUE,
  ablauf      timestamptz NOT NULL,
  erstellt    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS email_verify_token_idx ON email_verify (token_hash);
