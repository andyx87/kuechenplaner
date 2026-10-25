import json
from contextlib import asynccontextmanager

import asyncpg

from . import config

_pool: "asyncpg.Pool | None" = None

# F10: Konto, das ohne Auth-Kontext (und ohne bypass) verwendet wird. Default -1 = ein
# unmögliches Konto → RLS liefert nichts (fail-closed). Früher war das 1 (Eigentümer),
# wodurch jeder kontextlose Pfad still die Owner-Daten sah. Nur die LAN-MCP-Anbindung
# (single-tenant, MCP_ENABLED) darf das bewusst auf 1 stellen (siehe main.py).
_no_context_account = -1


def set_no_context_account(account_id: int) -> None:
    global _no_context_account
    _no_context_account = int(account_id)


async def _init_conn(conn) -> None:
    # jsonb automatisch zu/von Python-Objekten kodieren
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def connect() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=config.DATABASE_URL,
            min_size=1,
            max_size=5,
            server_settings={"search_path": f"{config.DB_SCHEMA},public"},
            init=_init_conn,
        )


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# Additive Mini-Migration für den Mailversand (Phase 2): idempotent beim Start.
# Läuft mit der App-Verbindung (koch_app). Jedes Statement EINZELN + tolerant – so
# blockiert ein fehlendes Recht (z. B. ALTER app_user, Eigentümer-only) die übrigen
# CREATEs nicht. Der FK zu app_user wird bewusst WEGGELASSEN (REFERENCES-Recht nicht
# garantiert); user_id bleibt einfache Integer-Spalte. Siehe migration_mail_tokens.sql.
_MAIL_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS passwort_reset (
         id serial PRIMARY KEY,
         user_id integer NOT NULL,
         token_hash text NOT NULL UNIQUE,
         ablauf timestamptz NOT NULL,
         benutzt boolean NOT NULL DEFAULT false,
         erstellt timestamptz NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS passwort_reset_token_idx ON passwort_reset (token_hash)",
    """CREATE TABLE IF NOT EXISTS email_verify (
         id serial PRIMARY KEY,
         user_id integer NOT NULL,
         token_hash text NOT NULL UNIQUE,
         ablauf timestamptz NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS email_verify_token_idx ON email_verify (token_hash)",
]


# Fehlende Betriebs-Indexe/Spalten (idempotent). Siehe migration_indexe.sql.
_INDEX_SCHEMA_STMTS = [
    "CREATE INDEX IF NOT EXISTS account_mitglied_user_idx ON account_mitglied (user_id)",
    "CREATE INDEX IF NOT EXISTS person_acc_idx ON person (account_id)",
    "CREATE INDEX IF NOT EXISTS app_session_user_idx ON app_session (user_id)",
    "CREATE INDEX IF NOT EXISTS app_user_created_idx ON app_user (created_at DESC)",
    # Aktivitätsstempel des Haushalts (userauth.context_from_token, Admin-Kennzahlen).
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS zuletzt_aktiv timestamptz",
]


async def _ensure(name: str, stmts: list[str]) -> None:
    """Führt additive DDL einzeln und tolerant aus – fehlende Rechte des App-Users
    (Eigentümer-only DDL) blockieren die übrigen Statements und den Start nicht."""
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in stmts:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("%s: Statement übersprungen: %s", name, str(e)[:120])
    log.info("%s: %d/%d Statements ok", name, ok, len(stmts))


async def ensure_mail_schema() -> None:
    await _ensure("ensure_mail_schema", _MAIL_SCHEMA_STMTS)


async def ensure_index_schema() -> None:
    await _ensure("ensure_index_schema", _INDEX_SCHEMA_STMTS)


def pool() -> "asyncpg.Pool":
    if _pool is None:
        raise RuntimeError("DB-Pool nicht initialisiert")
    return _pool


@asynccontextmanager
async def acquire(bypass: bool = False):
    """Verbindung mit gesetztem Mandanten-Kontext (Postgres-RLS).

    Setzt `app.account_id` aus dem aktuellen Auth-Kontext (ContextVar). Ohne Kontext
    wird `_no_context_account` genutzt – standardmäßig -1 (unmögliches Konto → RLS liefert
    nichts, fail-closed). Nur die LAN-MCP-Anbindung setzt das bewusst auf 1 (F10).
    bypass=True -> volle Sicht (nur fuer vertrauenswuerdige Wartungsjobs)."""
    from .userauth import current_account
    acc = current_account.get()
    acc_eff = acc if acc is not None else _no_context_account
    async with pool().acquire() as con:
        if bypass:
            await con.execute("SELECT set_config('app.bypass','on',false)")
        else:
            await con.execute(
                "SELECT set_config('app.account_id', $1, false), set_config('app.bypass','off',false)",
                str(acc_eff))
        try:
            yield con
        finally:
            await con.execute("SELECT set_config('app.account_id','',false), set_config('app.bypass','off',false)")
