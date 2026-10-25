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


async def ensure_mail_schema() -> None:
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _MAIL_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_mail_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_mail_schema: %d/%d Statements ok", ok, len(_MAIL_SCHEMA_STMTS))


# F4: Idempotenz-Schlüssel für abo_buchung. Ersetzt die zu grobe UNIQUE(account_id, zeitraum),
# die mehrere Buchungen am selben Tag verschluckte (Unter-Fakturierung). Nur der Monats-Sweep
# setzt einen idempotenz-Wert; Nutzer-Buchungen (NULL) werden immer angehängt. Reihenfolge:
# Spalte -> partieller Unique-Index -> alte Constraint entfernen. Idempotent & tolerant;
# scheitert das (fehlende DDL-Rechte des App-Users), greift der Code-Fallback in _abo_buchung.
_ABO_SCHEMA_STMTS = [
    "ALTER TABLE abo_buchung ADD COLUMN IF NOT EXISTS idempotenz text",
    "CREATE UNIQUE INDEX IF NOT EXISTS abo_buchung_idem_uidx ON abo_buchung (idempotenz) WHERE idempotenz IS NOT NULL",
    "ALTER TABLE abo_buchung DROP CONSTRAINT IF EXISTS abo_buchung_account_id_zeitraum_key",
]


async def ensure_abo_schema() -> None:
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _ABO_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_abo_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_abo_schema: %d/%d Statements ok", ok, len(_ABO_SCHEMA_STMTS))


# Preisliste: Foto-Pack (Preis + Credit-Anzahl) in plattform_einstellung, damit Preise nicht
# im Code stehen. Siehe migration_beta_quelle_kuendigung.sql. Idempotent & tolerant – fehlen dem App-User
# die DDL-Rechte, liefert billing._preise() die Code-Defaults (Anzeige bleibt korrekt, die
# Werte sind dann bis zur Migration durch den Owner nur nicht über die Admin-UI pflegbar).
_PREISLISTE_SCHEMA_STMTS = [
    "ALTER TABLE plattform_einstellung ADD COLUMN IF NOT EXISTS foto_pack_cents integer NOT NULL DEFAULT 1299",
    "ALTER TABLE plattform_einstellung ADD COLUMN IF NOT EXISTS foto_pack_credits integer NOT NULL DEFAULT 75",
]


# Fehlende Betriebs-Indexe (UX-/Admin-Review 2026-07-26). Siehe migration_indexe.sql.
_INDEX_SCHEMA_STMTS = [
    "CREATE INDEX IF NOT EXISTS ai_nutzung_erstellt_idx ON ai_nutzung (erstellt DESC)",
    "CREATE INDEX IF NOT EXISTS account_mitglied_user_idx ON account_mitglied (user_id)",
    "CREATE INDEX IF NOT EXISTS person_acc_idx ON person (account_id)",
    "CREATE INDEX IF NOT EXISTS app_session_user_idx ON app_session (user_id)",
    "CREATE INDEX IF NOT EXISTS app_user_created_idx ON app_user (created_at DESC)",
]


async def ensure_index_schema() -> None:
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _INDEX_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_index_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_index_schema: %d/%d Statements ok", ok, len(_INDEX_SCHEMA_STMTS))


# Kündigungserklärungen (§ 312k BGB). Kein RLS: gehen auch ohne Anmeldung ein.
_KUENDIGUNG_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS kuendigung (
         id bigserial PRIMARY KEY,
         eingegangen timestamptz NOT NULL DEFAULT now(),
         email text NOT NULL, name text, vertrag text,
         art text NOT NULL DEFAULT 'ordentlich', grund text, zum_datum date,
         account_id integer, wirkung text, vertrag_bis date, ip text,
         bestaetigt_am timestamptz)""",
    "CREATE INDEX IF NOT EXISTS kuendigung_email_idx ON kuendigung (lower(email))",
    "CREATE INDEX IF NOT EXISTS kuendigung_eingegangen_idx ON kuendigung (eingegangen DESC)",
]


async def ensure_kuendigung_schema() -> None:
    """Nachweistabelle für Kündigungserklärungen. Siehe migration_beta_quelle_kuendigung.sql."""
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _KUENDIGUNG_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_kuendigung_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_kuendigung_schema: %d/%d Statements ok", ok, len(_KUENDIGUNG_SCHEMA_STMTS))


# Beta-Anmeldung je Kanal. Kein RLS (Plattform-Tabelle ohne Kontobezug, wie tarif).
_BETA_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS beta_quelle (
         slug text PRIMARY KEY, name text NOT NULL,
         max_konten integer NOT NULL DEFAULT 50, trial_tage integer NOT NULL DEFAULT 90,
         aktiv boolean NOT NULL DEFAULT true, erstellt timestamptz NOT NULL DEFAULT now())""",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS beta_quelle text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS zuletzt_aktiv timestamptz",
    "CREATE INDEX IF NOT EXISTS account_beta_quelle_idx ON account (beta_quelle) WHERE beta_quelle IS NOT NULL",
    # Nur Facebook aktiv; die übrigen Kanäle sind vorbereitet, aber abgeschaltet
    # (Freischalten: UPDATE beta_quelle SET aktiv = true WHERE slug = 'reddit').
    """INSERT INTO beta_quelle (slug, name, max_konten, trial_tage, aktiv)
         VALUES ('facebook','Facebook',50,90,true), ('reddit','Reddit',20,90,false),
                ('privat','Privat',10,90,false), ('allgemein','Allgemein',10,90,false)
         ON CONFLICT (slug) DO NOTHING""",
]


async def ensure_beta_schema() -> None:
    """Beta-Anmeldelinks je Kanal (/beta/<slug>). Siehe migration_beta_quelle_kuendigung.sql. Idempotent &
    tolerant – ohne die Tabelle liefert userauth.beta_info() einfach 'unbekannter Kanal',
    die normale Registrierung bleibt unberührt."""
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _BETA_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_beta_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_beta_schema: %d/%d Statements ok", ok, len(_BETA_SCHEMA_STMTS))


async def ensure_preisliste_schema() -> None:
    import logging
    log = logging.getLogger("koch")
    ok = 0
    for stmt in _PREISLISTE_SCHEMA_STMTS:
        try:
            async with pool().acquire() as con:
                await con.execute(stmt)
            ok += 1
        except Exception as e:  # noqa: BLE001 – Start darf nicht crashen
            log.warning("ensure_preisliste_schema: Statement übersprungen: %s", str(e)[:120])
    log.info("ensure_preisliste_schema: %d/%d Statements ok", ok, len(_PREISLISTE_SCHEMA_STMTS))


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
