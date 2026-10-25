"""Mandantenkontext pro MCP-Aufruf.

Die Bearer-Prüfung selbst macht FastMCP mit `oauth.TopfplanOAuth.load_access_token`
(OAuth-Access-Token oder persönliches Zugriffstoken). Diese Middleware übernimmt aus dem
geprüften Token Nutzer und Haushalt in die ContextVars, aus denen `db.acquire()` das
Postgres-RLS-Konto setzt. Ohne gültiges Token gibt es keinen Kontext → RLS sieht nichts.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext

from .userauth import current_account, current_user, mcp_kontext


def konto_aus_token() -> tuple[int, int, list[str]] | None:
    tok = get_access_token()
    if tok is None:
        return None
    claims = getattr(tok, "claims", None) or {}
    uid, acc = claims.get("user_id"), claims.get("account_id")
    if not uid or not acc:
        return None
    return int(uid), int(acc), list(tok.scopes or [])


class HaushaltsKontext(Middleware):
    """Setzt current_user/current_account/mcp_kontext für die Dauer eines MCP-Requests."""

    async def on_request(self, context: MiddlewareContext, call_next):
        k = konto_aus_token()
        if k is None:
            # Über HTTP unerreichbar (FastMCP antwortet vorher mit 401). Ohne Kontext bliebe
            # RLS ohnehin leer; Werkzeugaufrufe werden trotzdem ausdrücklich abgelehnt.
            if context.method == "tools/call":
                raise ToolError("Nicht angemeldet: gültiges Zugriffstoken erforderlich.")
            return await call_next(context)
        uid, acc, _scopes = k
        t1 = current_user.set(uid)
        t2 = current_account.set(acc)
        t3 = mcp_kontext.set(True)
        try:
            return await call_next(context)
        finally:
            current_user.reset(t1)
            current_account.reset(t2)
            mcp_kontext.reset(t3)
