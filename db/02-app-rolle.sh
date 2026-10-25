#!/bin/sh
# Legt die Rolle an, mit der die App sich verbindet. Bewusst KEIN Superuser und ohne
# BYPASSRLS: Superuser umgehen Row Level Security, dann wäre die Haushaltstrennung
# (Web-App und MCP) wirkungslos. Läuft nur beim allerersten Start (leeres Volume),
# nach 01-schema.sql. Tabellen gehören weiter POSTGRES_USER (Migrationen als dieser).
set -eu
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD fehlt}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_pw="$APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE koch_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
GRANT USAGE ON SCHEMA koch TO koch_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA koch TO koch_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA koch TO koch_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA koch GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO koch_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA koch GRANT USAGE, SELECT ON SEQUENCES TO koch_app;
EOSQL
