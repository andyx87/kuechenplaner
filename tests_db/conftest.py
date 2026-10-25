"""Integrationstests gegen ein echtes Postgres (RLS!) und den echten Server.

Getrennt von tests/, weil dort Module per sys.modules gestubbt werden. Aufruf:

    TEST_DATABASE_URL_ADMIN=postgresql://koch:pw@host:5432/koch python -m pytest tests_db -q

Die Fixture legt Schema `koch` aus schema.sql NEU an (DROP SCHEMA … CASCADE – nur gegen
eine Wegwerf-Datenbank laufen lassen!), erzeugt eine Nicht-Superuser-Rolle `koch_app`,
damit FORCE ROW LEVEL SECURITY wirkt, und startet die App per uvicorn in einem Thread.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_DATABASE_URL_ADMIN")
PORT = int(os.environ.get("TEST_PORT", "18093"))
BASE = f"http://127.0.0.1:{PORT}"
APP_PW = "koch-app-test"

if not ADMIN_URL:
    pytest.skip("TEST_DATABASE_URL_ADMIN nicht gesetzt – DB-Integrationstests übersprungen.",
                allow_module_level=True)


def _app_url() -> str:
    p = urlparse(ADMIN_URL)
    netloc = f"koch_app:{APP_PW}@{p.hostname}:{p.port or 5432}"
    return urlunparse(p._replace(netloc=netloc))


async def _schema_neu():
    import asyncpg
    con = await asyncpg.connect(ADMIN_URL)
    try:
        await con.execute("DROP SCHEMA IF EXISTS koch CASCADE")
        await con.execute((REPO / "schema.sql").read_text())
        await con.execute("SET search_path TO koch, public")
        exists = await con.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'koch_app'")
        if not exists:
            await con.execute(f"CREATE ROLE koch_app LOGIN PASSWORD '{APP_PW}' NOSUPERUSER NOBYPASSRLS")
        await con.execute("GRANT USAGE ON SCHEMA koch TO koch_app")
        await con.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA koch TO koch_app")
        await con.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA koch TO koch_app")
        # Globale Master-Zutaten (account_id NULL) wie im Katalog einer echten Instanz.
        for name in ("Tomaten", "Naturjoghurt", "Hähnchenbrust", "Zwiebel", "Reis", "Olivenöl"):
            await con.execute("INSERT INTO koch.zutaten (name, account_id) VALUES ($1, NULL)", name)
    finally:
        await con.close()


def admin_sql(sql: str, *args):
    import asyncpg

    async def _run():
        con = await asyncpg.connect(ADMIN_URL)
        try:
            await con.execute("SET search_path TO koch, public")
            return await con.fetch(sql, *args)
        finally:
            await con.close()
    return asyncio.run(_run())


@pytest.fixture(scope="session")
def server():
    asyncio.run(_schema_neu())
    os.environ.update({
        "DATABASE_URL": _app_url(), "DB_SCHEMA": "koch", "MCP_ENABLED": "1",
        "PUBLIC_URL": BASE, "APP_BASE_URL": BASE, "TRUSTED_PROXY_HOPS": "1",
        "KI_BASE_URL": "", "KI_IMAGE_MODEL": "",
    })
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import uvicorn
    from app.main import app
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Server startet nicht")
    yield BASE
    srv.should_exit = True
    t.join(timeout=5)


_zaehler = {"n": 0}


@pytest.fixture
def nutzer(server):
    """Registriert einen neuen Nutzer (eigener Haushalt) → {token, user_id, account_id, email}."""
    from app import ratelimit

    def _neu(name="Test"):
        ratelimit._buckets.clear()   # Registrierungs-Limit (5/h je IP) gilt im Test nicht
        _zaehler["n"] += 1
        email = f"nutzer{_zaehler['n']}-{int(time.time()*1000)}@example.org"
        r = httpx.post(f"{server}/api/auth/register",
                       json={"email": email, "password": "geheim12345", "name": name})
        assert r.status_code == 200, r.text
        d = r.json()
        return {"token": d["token"], "user_id": d["user"]["id"], "account_id": d["account"]["id"], "email": email}
    return _neu
