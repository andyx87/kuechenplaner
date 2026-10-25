-- OAuth 2.1 / MCP-Connector: Clients, Zustimmungen, Tokens (gehasht), persönliche Tokens,
-- haushaltsbezogene Kochmodus-Schritte und Idempotenz-Schlüssel der MCP-Werkzeuge.
-- Idempotent. Als Eigentümer der Tabellen einspielen (die App versucht es beim Start selbst).
SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS oauth_client (
         client_id text PRIMARY KEY,
         info jsonb NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now(),
         zuletzt_genutzt timestamptz);

CREATE TABLE IF NOT EXISTS oauth_anfrage (
         id_hash text PRIMARY KEY,
         client_id text NOT NULL,
         params jsonb NOT NULL,
         ablauf timestamptz NOT NULL);

CREATE TABLE IF NOT EXISTS oauth_grant (
         id serial PRIMARY KEY,
         client_id text NOT NULL,
         user_id integer NOT NULL,
         account_id integer NOT NULL,
         scopes text[] NOT NULL,
         resource text,
         erstellt timestamptz NOT NULL DEFAULT now(),
         zuletzt_genutzt timestamptz,
         widerrufen timestamptz);

CREATE INDEX IF NOT EXISTS oauth_grant_user_idx ON oauth_grant (user_id, account_id);

CREATE TABLE IF NOT EXISTS oauth_code (
         code_hash text PRIMARY KEY,
         client_id text NOT NULL,
         user_id integer NOT NULL,
         account_id integer NOT NULL,
         scopes text[] NOT NULL,
         code_challenge text NOT NULL,
         redirect_uri text NOT NULL,
         redirect_explizit boolean NOT NULL DEFAULT true,
         resource text,
         ablauf timestamptz NOT NULL,
         benutzt timestamptz,
         grant_id integer);

CREATE TABLE IF NOT EXISTS oauth_token (
         token_hash text PRIMARY KEY,
         art text NOT NULL CHECK (art IN ('access', 'refresh')),
         grant_id integer NOT NULL REFERENCES oauth_grant(id) ON DELETE CASCADE,
         scopes text[] NOT NULL,
         ablauf timestamptz NOT NULL,
         ersetzt timestamptz,
         erstellt timestamptz NOT NULL DEFAULT now());

CREATE INDEX IF NOT EXISTS oauth_token_grant_idx ON oauth_token (grant_id);

CREATE TABLE IF NOT EXISTS api_token (
         id serial PRIMARY KEY,
         user_id integer NOT NULL,
         account_id integer NOT NULL,
         name text NOT NULL,
         token_hash text NOT NULL UNIQUE,
         anzeige text NOT NULL,
         scopes text[] NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now(),
         zuletzt_genutzt timestamptz,
         ablauf timestamptz,
         widerrufen timestamptz);

CREATE INDEX IF NOT EXISTS api_token_user_idx ON api_token (user_id);

CREATE TABLE IF NOT EXISTS kochmodus_schritte (
         account_id integer NOT NULL DEFAULT (NULLIF(current_setting('app.account_id', true), ''))::integer,
         rezept_id integer NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
         signatur text NOT NULL,
         quelle_hash text NOT NULL,
         schritte jsonb NOT NULL,
         quelle text NOT NULL DEFAULT 'ki',
         aktualisiert timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, rezept_id, signatur));

ALTER TABLE kochmodus_schritte ENABLE ROW LEVEL SECURITY;

ALTER TABLE kochmodus_schritte FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                             AND tablename = 'kochmodus_schritte' AND policyname = 'acc_isolation') THEN
                CREATE POLICY acc_isolation ON kochmodus_schritte USING (current_setting('app.bypass', true) = 'on' OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer) WITH CHECK (current_setting('app.bypass', true) = 'on' OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer);
              END IF;
            END $$;

CREATE TABLE IF NOT EXISTS mcp_idempotenz (
         account_id integer NOT NULL DEFAULT (NULLIF(current_setting('app.account_id', true), ''))::integer,
         werkzeug text NOT NULL,
         schluessel text NOT NULL,
         ergebnis jsonb NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, werkzeug, schluessel));

ALTER TABLE mcp_idempotenz ENABLE ROW LEVEL SECURITY;

ALTER TABLE mcp_idempotenz FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                             AND tablename = 'mcp_idempotenz' AND policyname = 'acc_isolation') THEN
                CREATE POLICY acc_isolation ON mcp_idempotenz USING (current_setting('app.bypass', true) = 'on' OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer) WITH CHECK (current_setting('app.bypass', true) = 'on' OR account_id = (NULLIF(current_setting('app.account_id', true), ''))::integer);
              END IF;
            END $$;

