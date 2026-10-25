"""Ergänzungen an den OAuth-Routen, die FastMCP/das MCP-SDK bereitstellt."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import ratelimit


def register_bremsen(asgi_app, limit: int = 10, fenster_s: int = 3600) -> None:
    """Dynamic Client Registration (/register) pro IP begrenzen. DCR ist öffentlich, damit
    Claude sich ohne Vorab-Einrichtung registrieren kann – unbegrenzt wäre es eine Einladung
    zum Vollschreiben der Client-Tabelle (zusätzlich: globales Limit in oauth.register_client)."""
    for route in getattr(asgi_app, "routes", []):
        if isinstance(route, Route) and route.path == "/register":
            inner = route.app

            async def gebremst(scope, receive, send, _inner=inner):
                if scope.get("type") == "http" and scope.get("method") == "POST":
                    ip = ratelimit.client_ip(Request(scope))
                    if not ratelimit.treffer(f"oauth-register:ip:{ip}", limit, fenster_s):
                        resp = JSONResponse({"error": "invalid_client_metadata",
                                             "error_description": "Zu viele Registrierungen von dieser Adresse."},
                                            status_code=429)
                        await resp(scope, receive, send)
                        return
                await _inner(scope, receive, send)

            route.app = gebremst


def revoke_reparieren(asgi_app) -> None:
    """RFC 7009 erlaubt öffentlichen Clients den Widerruf ohne client_secret. Das MCP-SDK
    (mcp 2.3.0, RevocationRequest) verlangt das Feld aber im Formular. Fehlt es, wird es hier
    leer ergänzt, bevor die SDK-Route das Formular liest."""
    from urllib.parse import parse_qsl, urlencode

    for route in getattr(asgi_app, "routes", []):
        if isinstance(route, Route) and route.path == "/revoke":
            inner = route.app

            async def ergaenzt(scope, receive, send, _inner=inner):
                if scope.get("type") != "http" or scope.get("method") != "POST":
                    await _inner(scope, receive, send)
                    return
                body = b""
                while True:
                    msg = await receive()
                    body += msg.get("body", b"")
                    if not msg.get("more_body"):
                        break
                ctype = dict(scope.get("headers") or []).get(b"content-type", b"")
                if ctype.startswith(b"application/x-www-form-urlencoded"):
                    felder = parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True)
                    if not any(k == "client_secret" for k, _ in felder):
                        felder.append(("client_secret", ""))
                        body = urlencode(felder).encode()
                headers = [(k, v) for k, v in (scope.get("headers") or []) if k != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                neu_scope = {**scope, "headers": headers}
                gesendet = False

                async def neu_receive():
                    nonlocal gesendet
                    if not gesendet:
                        gesendet = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                await _inner(neu_scope, neu_receive, send)

            route.app = ergaenzt
