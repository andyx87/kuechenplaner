import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, db, ki, services
from .rest import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("koch")

# Sentry nur initialisieren, wenn eine DSN gesetzt ist (secure-by-default AUS) – ohne
# SENTRY_DSN bleibt es ein vollstaendiger No-Op, kein Import-Fehler, kein Crash.
if config.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENV,
        traces_sample_rate=0.05,
    )
    log.info("Sentry aktiviert (environment=%s).", config.SENTRY_ENV)

# ASGI-App des MCP-Servers (Streamable HTTP). Intern unter "/" gemountet -> Endpunkt /mcp.
# Nur wenn MCP_ENABLED gesetzt ist (secure-by-default AUS, s. config.MCP_ENABLED):
# In der Cloud bleibt /mcp ungemountet, damit der ungeschuetzte Endpunkt nicht
# oeffentlich erreichbar ist. Der Import erfolgt bewusst erst hier (nur bei Bedarf).
mcp_app = None
if config.MCP_ENABLED:
    from .mcp_server import mcp
    mcp_app = mcp.http_app(path="/")
    # F10: MCP läuft ohne Auth-Kontext und ist bewusst single-tenant (LAN). Nur hier darf
    # der kontextlose Default auf Konto 1 zeigen; im Cloud-Build (MCP aus) bleibt er -1.
    db.set_no_context_account(1)


async def _angebote_cleanup_loop():
    """Taeglich abgelaufene Angebote loeschen (am Tag nach ihrer Gueltigkeit).
    Laeuft einmal beim Start und danach alle 24 h."""
    while True:
        try:
            res = await services.delete_expired_angebote()
            if res.get("geloescht"):
                log.info("Angebote-Cleanup: %s abgelaufene entfernt", res["geloescht"])
        except Exception as e:  # Job darf den Server nie stoeren
            log.warning("Angebote-Cleanup fehlgeschlagen: %s", e)
        await asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.ensure_mail_schema()   # additive Mail-Tokens-Migration (idempotent)
    await db.ensure_index_schema()  # Betriebs-Indexe/-Spalten (idempotent)
    cleanup_task = asyncio.create_task(_angebote_cleanup_loop())
    # Lifespan des MCP-Servers mitlaufen lassen (Session-Manager etc.) – nur wenn aktiv.
    if mcp_app is not None:
        async with mcp_app.lifespan(app):
            yield
    else:
        yield
    cleanup_task.cancel()
    await db.close()


app = FastAPI(title="Topfplan", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(services.NichtGefunden)
async def _nichtgefunden_handler(request: Request, exc: services.NichtGefunden):
    """Lösch-/Zugriff auf fremde oder nicht existierende Ressource → HTTP 404
    (statt fälschlich 200, wenn RLS die Zeile schützt)."""
    return JSONResponse(status_code=404, content={
        "fehler": "nicht_gefunden",
        "meldung": str(exc) or "Nicht gefunden oder kein Zugriff."})


@app.exception_handler(ki.KiNichtKonfiguriert)
async def _ki_nicht_konfiguriert_handler(request: Request, exc: ki.KiNichtKonfiguriert):
    """KI-Funktion auf dieser Instanz nicht eingerichtet → HTTP 503 (kein Anbieter-Aufruf)."""
    return JSONResponse(status_code=503, content={
        "fehler": "ki_nicht_konfiguriert", "faehigkeit": exc.faehigkeit,
        "meldung": "Diese KI-Funktion ist auf diesem Server nicht eingerichtet."})


app.include_router(router)
if mcp_app is not None:
    app.mount("/mcp", mcp_app)
    log.info("MCP-Endpunkt /mcp aktiviert (MCP_ENABLED=1).")
else:
    log.info("MCP-Endpunkt deaktiviert (MCP_ENABLED nicht gesetzt) – /mcp nicht gemountet.")


@app.get("/health")
async def health():
    """Health-Check mit echtem DB-Ping (SELECT 1 über den bestehenden Pool, Timeout 2s).
    Bei DB-Fehler/Timeout 503 statt 200, damit Orchestrierung/Monitoring einen echten
    Ausfall erkennt statt nur die Erreichbarkeit des Prozesses."""
    try:
        async with db.pool().acquire() as con:
            await asyncio.wait_for(con.fetchval("SELECT 1"), timeout=2.0)
    except Exception as e:
        log.warning("Health-Check: DB nicht erreichbar: %s", e)
        return JSONResponse(status_code=503, content={"status": "db_down"})
    return {"status": "ok"}
