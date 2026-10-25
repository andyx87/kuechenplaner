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

# MCP-Server (Streamable HTTP) mit OAuth 2.1. Die App ist selbst Authorization Server
# (app/oauth.py); ohne gültiges Token antwortet /mcp mit 401 + WWW-Authenticate. Jeder
# Aufruf läuft im Haushalt des Tokens (app/mcp_auth.py), es gibt keinen kontextlosen Modus.
mcp_app = None
oauth_provider = None
if config.MCP_ENABLED:
    from . import oauth
    from .mcp_server import mcp
    oauth_provider = oauth.TopfplanOAuth()
    mcp.auth = oauth_provider
    mcp_app = mcp.http_app(path="/mcp", stateless_http=True)
    if not config.PUBLIC_URL.startswith("https://"):
        log.warning("PUBLIC_URL ist nicht https (%s) – Claude-Connectoren brauchen HTTPS.", config.PUBLIC_URL)


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
        if oauth_provider is not None:
            try:
                from . import oauth
                await oauth.aufraeumen()
            except Exception as e:
                log.warning("OAuth-Aufräumen fehlgeschlagen: %s", e)
        await asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.ensure_mail_schema()   # additive Mail-Tokens-Migration (idempotent)
    await db.ensure_index_schema()  # Betriebs-Indexe/-Spalten (idempotent)
    await db.ensure_mcp_schema()    # OAuth-/MCP-Tabellen (idempotent, s. migration_mcp_oauth.sql)
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


# Zuletzt: MCP-App an der Wurzel einhängen. Sie bringt /mcp, /.well-known/oauth-*,
# /authorize, /token, /register und /revoke mit; alle FastAPI-Routen oben haben Vorrang.
if mcp_app is not None:
    from .oauth_routen import register_bremsen, revoke_reparieren
    register_bremsen(mcp_app)
    revoke_reparieren(mcp_app)
    app.mount("/", mcp_app)
    log.info("MCP-Endpunkt %s/mcp mit OAuth aktiviert.", config.PUBLIC_URL)
else:
    log.info("MCP-Endpunkt deaktiviert (MCP_ENABLED=0).")
