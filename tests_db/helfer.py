"""Hilfen für OAuth-Ablauf und MCP-Aufrufe in den Integrationstests."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx

CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def registrieren(base: str, redirect: str = CLAUDE_CALLBACK, **extra) -> httpx.Response:
    body = {"redirect_uris": [redirect], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "client_name": "Claude", **extra}
    return httpx.post(f"{base}/register", json=body)


def autorisieren(base: str, client_id: str, challenge: str, redirect: str = CLAUDE_CALLBACK,
                 scope: str | None = "read write", state: str = "xyz", resource: str | None = None) -> httpx.Response:
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
              "resource": resource or f"{base}/mcp"}
    if scope:
        params["scope"] = scope
    return httpx.get(f"{base}/authorize", params=params, follow_redirects=False)


def anfrage_aus(resp: httpx.Response) -> str:
    loc = resp.headers["location"]
    return parse_qs(urlparse(loc).query)["anfrage"][0]


def zustimmen(base: str, session: str, anfrage: str, scopes=None, ja=True) -> httpx.Response:
    return httpx.post(f"{base}/api/oauth/anfrage/{anfrage}", json={"zustimmen": ja, "scopes": scopes},
                      headers={"Authorization": f"Bearer {session}"})


def token_tausch(base: str, client_id: str, code: str, verifier: str, redirect: str = CLAUDE_CALLBACK) -> httpx.Response:
    return httpx.post(f"{base}/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": client_id,
        "code_verifier": verifier, "resource": f"{base}/mcp"})


def refresh(base: str, client_id: str, refresh_token: str) -> httpx.Response:
    return httpx.post(f"{base}/token", data={"grant_type": "refresh_token", "refresh_token": refresh_token,
                                             "client_id": client_id, "resource": f"{base}/mcp"})


def voller_ablauf(base: str, session: str, scopes=None) -> dict:
    """Kompletter Claude-Ablauf: DCR → authorize → Zustimmung → Token-Tausch."""
    r = registrieren(base)
    assert r.status_code == 201, r.text
    client_id = r.json()["client_id"]
    verifier, challenge = pkce()
    a = autorisieren(base, client_id, challenge)
    assert a.status_code == 302, a.text
    z = zustimmen(base, session, anfrage_aus(a), scopes=scopes)
    assert z.status_code == 200, z.text
    code = parse_qs(urlparse(z.json()["redirect_url"]).query)["code"][0]
    t = token_tausch(base, client_id, code, verifier)
    assert t.status_code == 200, t.text
    return {"client_id": client_id, **t.json()}


async def _mcp(base: str, token: str, fn):
    from fastmcp import Client
    async with Client(f"{base}/mcp", auth=token) as c:
        return await fn(c)


def mcp_tools(base: str, token: str) -> list[str]:
    async def fn(c):
        return [t.name for t in await c.list_tools()]
    return asyncio.run(_mcp(base, token, fn))


def mcp(base: str, token: str, tool: str, **args):
    """Ruft ein Werkzeug auf → (ok, daten|fehlertext)."""
    async def fn(c):
        res = await c.call_tool(tool, args, raise_on_error=False)
        if res.is_error:
            return False, " ".join(getattr(b, "text", "") for b in res.content)
        return True, res.structured_content if res.structured_content is not None else res.data
    return asyncio.run(_mcp(base, token, fn))


def ok(base: str, token: str, tool: str, **args):
    erfolgreich, daten = mcp(base, token, tool, **args)
    assert erfolgreich, f"{tool} fehlgeschlagen: {daten}"
    return daten


def mcp_status(base: str, token: str) -> int:
    """HTTP-Status eines rohen MCP-Aufrufs (401 = Token ungültig)."""
    return httpx.post(f"{base}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                      headers={"Authorization": f"Bearer {token}",
                               "Accept": "application/json, text/event-stream"}).status_code
