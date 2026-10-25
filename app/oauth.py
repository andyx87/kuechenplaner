"""OAuth 2.1 Authorization Server + persönliche Zugriffstokens für den MCP-Endpunkt.

Topfplan ist selbst Authorization Server (Nutzer, Haushalte und Login gibt es schon).
Die Protokoll-Endpunkte stellt FastMCP bzw. das MCP-SDK bereit (`OAuthProvider`):

  /.well-known/oauth-authorization-server   RFC 8414
  /.well-known/oauth-protected-resource/mcp RFC 9728 (+ WWW-Authenticate bei 401)
  /register                                 RFC 7591 Dynamic Client Registration
  /authorize                                Authorization Code + PKCE (nur S256)
  /token                                    Code-Tausch, Refresh mit Rotation
  /revoke                                   RFC 7009

Diese Datei liefert die Speicherung dahinter: Clients, offene Anfragen, Codes, Grants
(= „verbundene Apps“) und Tokens – alle Tokens nur als SHA-256-Hash. Die Zustimmung
läuft in der Web-App: /authorize leitet auf `<APP_BASE_URL>/verbinden?anfrage=…`, dort
ist der Nutzer mit seiner normalen Sitzung angemeldet und bestätigt (REST, s. rest.py).

Jedes Token ist an (user_id, account_id, scopes, resource) gebunden. Bei jeder
Prüfung wird nachgesehen, ob der Nutzer noch aktiv und Mitglied des Haushalts ist.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (AuthorizationCode, AuthorizationParams, AuthorizeError,
                                      RefreshToken, RegistrationError, TokenError,
                                      construct_redirect_uri)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from . import config
from .db import pool

log = logging.getLogger("koch")

SCOPES = ["read", "write"]
SCOPE_TEXT = {
    "read": "Rezepte, Vorrat, Geräte, Wochenplan, Einkaufsliste und Angebote lesen",
    "write": "Diese Daten anlegen, ändern und löschen (inkl. Rezeptbild über den Bild-Anbieter des Servers)",
}

CLAUDE_CALLBACKS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)

PRAEFIX_ACCESS = "tpa_"
PRAEFIX_REFRESH = "tpr_"
PRAEFIX_PAT = "tpp_"
PRAEFIX_CODE = "tpc_"

CODE_TTL_S = 300
ANFRAGE_TTL_S = 900
MAX_CLIENTS_PRO_STUNDE = 30   # DCR-Flut bremsen (zusätzlich zum IP-Limit an der Route)


def _hash(t: str) -> str:
    return hashlib.sha256((t or "").encode()).hexdigest()


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def mcp_resource_url() -> str:
    """Kanonische URL des MCP-Endpunkts (RFC 8707 resource / RFC 9728 resource)."""
    return f"{config.PUBLIC_URL}/mcp"


def _norm_resource(u: str | None) -> str:
    if not u:
        return ""
    p = urlparse(u.strip())
    pfad = p.path.rstrip("/")
    return f"{p.scheme.lower()}://{p.netloc.lower()}{pfad}"


def resource_passt(resource: str | None) -> bool:
    """True, wenn kein resource angegeben ist oder er auf diesen Server zeigt. Akzeptiert
    die MCP-URL und die Basis-URL (manche Clients senden den Origin)."""
    if not resource:
        return True
    r = _norm_resource(resource)
    return r in (_norm_resource(mcp_resource_url()), _norm_resource(config.PUBLIC_URL))


def ist_loopback(uri: str) -> bool:
    p = urlparse(uri)
    return p.scheme == "http" and (p.hostname or "") in ("localhost", "127.0.0.1", "::1")


def redirect_erlaubt(uri: str) -> bool:
    """Redirect-Policy bei der Registrierung: Claude-Callbacks, Loopback (Port egal),
    per Env erlaubte URIs; mit OAUTH_REDIRECT_FREI jede HTTPS-URI."""
    if not uri:
        return False
    p = urlparse(uri)
    if p.fragment:
        return False
    if uri in CLAUDE_CALLBACKS or uri in config.OAUTH_REDIRECT_URIS:
        return True
    if ist_loopback(uri):
        return True
    return config.OAUTH_REDIRECT_FREI and p.scheme == "https" and bool(p.hostname)


def _loopback_gleich(a: str, b: str) -> bool:
    """RFC 8252 7.3: Loopback-Redirects ohne Port vergleichen (Claude Code nutzt einen
    zufälligen Port, registriert aber evtl. einen anderen)."""
    pa, pb = urlparse(a), urlparse(b)
    return (ist_loopback(a) and ist_loopback(b) and pa.hostname == pb.hostname
            and (pa.path or "/") == (pb.path or "/") and pa.query == pb.query)


class TopfplanClient(OAuthClientInformationFull):
    """Client-Info mit portunabhängigem Loopback-Abgleich der Redirect-URI."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and self.redirect_uris:
            ru = str(redirect_uri)
            for reg in self.redirect_uris:
                if str(reg) == ru or _loopback_gleich(str(reg), ru):
                    return redirect_uri
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
        return super().validate_redirect_uri(redirect_uri)


class TopfplanCode(AuthorizationCode):
    user_id: int
    account_id: int


class TopfplanRefresh(RefreshToken):
    grant_id: int


def _access_token(token: str, *, client_id: str, scopes: list[str], expires_at: int | None,
                  resource: str | None, user_id: int, account_id: int, art: str,
                  ref_id: int) -> AccessToken:
    return AccessToken(
        token=token, client_id=client_id, scopes=list(scopes), expires_at=expires_at,
        resource=resource, subject=str(user_id),
        claims={"user_id": user_id, "account_id": account_id, "art": art, "ref_id": ref_id,
                "iss": config.PUBLIC_URL},
    )


class TopfplanOAuth(OAuthProvider):
    """OAuth-Provider für FastMCP, gespeichert in Postgres."""

    def __init__(self):
        super().__init__(
            base_url=config.PUBLIC_URL,
            issuer_url=config.PUBLIC_URL,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=["read"],
        )

    def get_routes(self, mcp_path: str | None = None):
        """SDK-Routen übernehmen, die beiden Metadaten-Dokumente aber selbst ausliefern:
        Issuer ohne abschließenden Slash (identisch in RFC 8414 und RFC 9728), `none` als
        Token-Endpunkt-Methode (DCR-Clients wie Claude sind öffentliche Clients) und die
        Ressourcen-Metadaten zusätzlich unter dem Wurzelpfad (Fallback-Suche von Claude)."""
        from mcp.server.auth.routes import build_metadata, cors_middleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        routes = super().get_routes(mcp_path)
        issuer = config.PUBLIC_URL
        meta = build_metadata(self.base_url, None, self.client_registration_options,
                              self.revocation_options).model_dump(mode="json", exclude_none=True)
        methoden = ["none", "client_secret_post", "client_secret_basic"]
        meta.update(issuer=issuer, token_endpoint_auth_methods_supported=methoden,
                    revocation_endpoint_auth_methods_supported=methoden)
        for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
            if k in meta:
                meta[k] = issuer + urlparse(meta[k]).path
        prm = {"resource": mcp_resource_url(), "authorization_servers": [issuer],
               "scopes_supported": list(SCOPES), "bearer_methods_supported": ["header"],
               "resource_name": "Topfplan"}

        def antwort(daten):
            async def handler(request):
                return JSONResponse(daten, headers={"Cache-Control": "public, max-age=300"})
            return cors_middleware(handler, ["GET", "OPTIONS"])

        neu = [r for r in routes if not (isinstance(r, Route) and r.path.startswith(
            ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource")))]
        prm_pfad = "/.well-known/oauth-protected-resource" + urlparse(mcp_resource_url()).path
        neu += [
            Route("/.well-known/oauth-authorization-server", antwort(meta), methods=["GET", "OPTIONS"]),
            Route(prm_pfad, antwort(prm), methods=["GET", "OPTIONS"]),
            Route("/.well-known/oauth-protected-resource", antwort(prm), methods=["GET", "OPTIONS"]),
        ]
        return neu

    # Claude übernimmt die Scopes aus dem WWW-Authenticate-Header der 401-Antwort:
    # beide anfordern, der Nutzer kann bei der Zustimmung auf „nur lesen“ reduzieren.
    def get_challenge_scopes(self, required_scopes: list[str] | None = None) -> list[str]:
        return list(SCOPES) if required_scopes is None else required_scopes

    # ---------- Clients (DCR) ----------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not client_id:
            return None
        async with pool().acquire() as con:
            row = await con.fetchrow("SELECT info FROM oauth_client WHERE client_id = $1", client_id)
        if row is None:
            return None
        info = row["info"]
        if isinstance(info, str):
            info = json.loads(info)
        return TopfplanClient.model_validate(info)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not uris:
            raise RegistrationError("invalid_redirect_uri", "redirect_uris fehlt")
        for u in uris:
            if not redirect_erlaubt(u):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    f"Redirect-URI nicht erlaubt: {u}. Erlaubt sind die Claude-Callbacks, "
                    "Loopback-Adressen und per OAUTH_REDIRECT_URIS freigegebene URIs.")
        if client_info.client_name and len(client_info.client_name) > 200:
            raise RegistrationError("invalid_client_metadata", "client_name zu lang")
        async with pool().acquire() as con:
            n = await con.fetchval(
                "SELECT count(*) FROM oauth_client WHERE erstellt > now() - interval '1 hour'")
            if n is not None and n >= MAX_CLIENTS_PRO_STUNDE:
                raise RegistrationError("invalid_client_metadata",
                                        "Zu viele Registrierungen, bitte später erneut versuchen.")
            await con.execute(
                "INSERT INTO oauth_client (client_id, info) VALUES ($1, $2)",
                client_info.client_id, client_info.model_dump(mode="json", exclude_none=True))

    # ---------- Autorisierung ----------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not resource_passt(params.resource):
            raise AuthorizeError("invalid_target", "resource zeigt nicht auf diesen Server")
        anfrage = secrets.token_urlsafe(32)
        daten = {
            "state": params.state,
            "scopes": params.scopes or list(SCOPES),
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_explizit": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        }
        async with pool().acquire() as con:
            await con.execute(
                "INSERT INTO oauth_anfrage (id_hash, client_id, params, ablauf) "
                "VALUES ($1, $2, $3, $4)",
                _hash(anfrage), client.client_id, daten,
                _jetzt() + timedelta(seconds=ANFRAGE_TTL_S))
        return f"{config.APP_BASE_URL}/verbinden?anfrage={anfrage}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> TopfplanCode | None:
        async with pool().acquire() as con:
            r = await con.fetchrow(
                "SELECT * FROM oauth_code WHERE code_hash = $1 AND client_id = $2",
                _hash(authorization_code), client.client_id)
            if r is None:
                return None
            if r["benutzt"] is not None:
                # Code-Wiederverwendung (OAuth 2.1 4.1.3): daraus ausgestellte Tokens widerrufen.
                if r["grant_id"]:
                    await con.execute("UPDATE oauth_grant SET widerrufen = now() "
                                      "WHERE id = $1 AND widerrufen IS NULL", r["grant_id"])
                return None
        return TopfplanCode(
            code=authorization_code, scopes=list(r["scopes"]), expires_at=r["ablauf"].timestamp(),
            client_id=r["client_id"], code_challenge=r["code_challenge"],
            redirect_uri=AnyUrl(r["redirect_uri"]), redirect_uri_provided_explicitly=r["redirect_explizit"],
            resource=r["resource"], subject=str(r["user_id"]),
            user_id=r["user_id"], account_id=r["account_id"])

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: TopfplanCode) -> OAuthToken:
        async with pool().acquire() as con:
            async with con.transaction():
                ok = await con.fetchval(
                    "UPDATE oauth_code SET benutzt = now() WHERE code_hash = $1 AND benutzt IS NULL "
                    "RETURNING 1", _hash(authorization_code.code))
                if not ok:
                    raise TokenError("invalid_grant", "authorization code already used")
                if not await _mitglied_aktiv(con, authorization_code.user_id, authorization_code.account_id):
                    raise TokenError("invalid_grant", "user is no longer a member of this household")
                grant_id = await con.fetchval(
                    "INSERT INTO oauth_grant (client_id, user_id, account_id, scopes, resource) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                    client.client_id, authorization_code.user_id, authorization_code.account_id,
                    list(authorization_code.scopes), authorization_code.resource)
                await con.execute("UPDATE oauth_code SET grant_id = $2 WHERE code_hash = $1",
                                  _hash(authorization_code.code), grant_id)
                return await _tokens_ausstellen(con, grant_id, list(authorization_code.scopes))

    # ---------- Refresh (mit Rotation + Wiederverwendungs-Erkennung) ----------

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> TopfplanRefresh | None:
        if not refresh_token.startswith(PRAEFIX_REFRESH):
            return None
        async with pool().acquire() as con:
            r = await con.fetchrow(
                """SELECT t.*, g.client_id, g.user_id, g.account_id, g.resource, g.widerrufen
                   FROM oauth_token t JOIN oauth_grant g ON g.id = t.grant_id
                   WHERE t.token_hash = $1 AND t.art = 'refresh'""", _hash(refresh_token))
            if r is None or r["client_id"] != client.client_id or r["widerrufen"] is not None:
                return None
            if r["ersetzt"] is not None:
                # Ein schon rotierter Refresh-Token wird erneut benutzt → vermutlich gestohlen.
                # Ganze Verbindung widerrufen (OAuth 2.1 4.3.1 / Security BCP).
                await con.execute("UPDATE oauth_grant SET widerrufen = now() WHERE id = $1", r["grant_id"])
                log.warning("OAuth: Refresh-Token wiederverwendet, Grant %s widerrufen", r["grant_id"])
                return None
        return TopfplanRefresh(
            token=refresh_token, client_id=r["client_id"], scopes=list(r["scopes"]),
            expires_at=int(r["ablauf"].timestamp()), resource=r["resource"],
            subject=str(r["user_id"]), grant_id=r["grant_id"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: TopfplanRefresh, scopes: list[str]) -> OAuthToken:
        async with pool().acquire() as con:
            async with con.transaction():
                ok = await con.fetchval(
                    "UPDATE oauth_token SET ersetzt = now() WHERE token_hash = $1 AND ersetzt IS NULL "
                    "RETURNING 1", _hash(refresh_token.token))
                if not ok:
                    raise TokenError("invalid_grant", "refresh token already used")
                g = await con.fetchrow("SELECT user_id, account_id, widerrufen FROM oauth_grant WHERE id = $1",
                                       refresh_token.grant_id)
                if g is None or g["widerrufen"] is not None or not await _mitglied_aktiv(
                        con, g["user_id"], g["account_id"]):
                    raise TokenError("invalid_grant", "grant revoked")
                # Alte Access-Tokens dieser Verbindung gleich mit ablösen.
                await con.execute("DELETE FROM oauth_token WHERE grant_id = $1 AND art = 'access'",
                                  refresh_token.grant_id)
                return await _tokens_ausstellen(con, refresh_token.grant_id, list(scopes))

    # ---------- Access-Token-Prüfung ----------

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token.startswith(PRAEFIX_PAT):
            return await _pat_pruefen(token)
        if not token.startswith(PRAEFIX_ACCESS):
            return None
        async with pool().acquire() as con:
            r = await con.fetchrow(
                """SELECT t.scopes, t.ablauf, t.grant_id, g.client_id, g.user_id, g.account_id,
                          g.resource, g.widerrufen, g.zuletzt_genutzt
                   FROM oauth_token t JOIN oauth_grant g ON g.id = t.grant_id
                   WHERE t.token_hash = $1 AND t.art = 'access'""", _hash(token))
            if r is None or r["widerrufen"] is not None or r["ablauf"] < _jetzt():
                return None
            if not resource_passt(r["resource"]):
                return None
            if not await _mitglied_aktiv(con, r["user_id"], r["account_id"]):
                return None
            if r["zuletzt_genutzt"] is None or r["zuletzt_genutzt"] < _jetzt() - timedelta(minutes=5):
                await con.execute("UPDATE oauth_grant SET zuletzt_genutzt = now() WHERE id = $1", r["grant_id"])
        return _access_token(token, client_id=r["client_id"], scopes=list(r["scopes"]),
                             expires_at=int(r["ablauf"].timestamp()),
                             resource=mcp_resource_url(), user_id=r["user_id"],
                             account_id=r["account_id"], art="oauth", ref_id=r["grant_id"])

    async def revoke_token(self, token) -> None:
        claims = getattr(token, "claims", None) or {}
        grant_id = getattr(token, "grant_id", None) or (claims.get("ref_id") if claims.get("art") == "oauth" else None)
        if grant_id:
            async with pool().acquire() as con:
                await con.execute("UPDATE oauth_grant SET widerrufen = now() WHERE id = $1 AND widerrufen IS NULL",
                                  int(grant_id))


async def _mitglied_aktiv(con, user_id: int, account_id: int) -> bool:
    return bool(await con.fetchval(
        """SELECT 1 FROM app_user u JOIN account_mitglied m ON m.user_id = u.id
           WHERE u.id = $1 AND m.account_id = $2 AND u.aktiv""", int(user_id), int(account_id)))


async def _tokens_ausstellen(con, grant_id: int, scopes: list[str]) -> OAuthToken:
    access = PRAEFIX_ACCESS + secrets.token_urlsafe(32)
    refresh = PRAEFIX_REFRESH + secrets.token_urlsafe(32)
    jetzt = _jetzt()
    await con.execute(
        "INSERT INTO oauth_token (token_hash, art, grant_id, scopes, ablauf) VALUES ($1,'access',$2,$3,$4)",
        _hash(access), grant_id, scopes, jetzt + timedelta(seconds=config.OAUTH_ACCESS_TTL_S))
    await con.execute(
        "INSERT INTO oauth_token (token_hash, art, grant_id, scopes, ablauf) VALUES ($1,'refresh',$2,$3,$4)",
        _hash(refresh), grant_id, scopes, jetzt + timedelta(days=config.OAUTH_REFRESH_TTL_TAGE))
    return OAuthToken(access_token=access, token_type="Bearer", expires_in=config.OAUTH_ACCESS_TTL_S,
                      scope=" ".join(scopes), refresh_token=refresh)


# ---------- Zustimmung (aufgerufen aus der Web-App, REST mit Sitzung) ----------

async def _anfrage_laden(con, anfrage: str):
    r = await con.fetchrow(
        "SELECT a.client_id, a.params, a.ablauf, c.info FROM oauth_anfrage a "
        "JOIN oauth_client c ON c.client_id = a.client_id WHERE a.id_hash = $1", _hash(anfrage or ""))
    if r is None or r["ablauf"] < _jetzt():
        return None
    params = r["params"] if isinstance(r["params"], dict) else json.loads(r["params"])
    info = r["info"] if isinstance(r["info"], dict) else json.loads(r["info"])
    return r["client_id"], params, info


async def anfrage_info(anfrage: str, account_id: int) -> dict | None:
    """Daten für die Zustimmungsseite: wer fragt an, wohin geht die Antwort, welche Rechte."""
    async with pool().acquire() as con:
        geladen = await _anfrage_laden(con, anfrage)
        if geladen is None:
            return None
        client_id, params, info = geladen
        haushalt = await con.fetchval("SELECT name FROM account WHERE id = $1", int(account_id))
    redirect = params["redirect_uri"]
    uris = [str(u) for u in (info.get("redirect_uris") or [])]
    return {
        "client_name": (info.get("client_name") or "Unbenannter Client")[:200],
        "client_uri": info.get("client_uri"),
        "redirect_host": urlparse(redirect).hostname,
        "redirect_uri": redirect,
        "nur_loopback": bool(uris) and all(ist_loopback(u) for u in uris),
        "scopes": [{"scope": s, "text": SCOPE_TEXT.get(s, s)} for s in params.get("scopes") or SCOPES
                   if s in SCOPES],
        "haushalt": haushalt,
    }


async def anfrage_entscheiden(anfrage: str, user_id: int, account_id: int, zustimmen: bool,
                              scopes: list[str] | None = None) -> dict | None:
    """Zustimmung oder Ablehnung. Gibt {redirect_url} zurück (Code bzw. access_denied)."""
    async with pool().acquire() as con:
        async with con.transaction():
            geladen = await _anfrage_laden(con, anfrage)
            if geladen is None:
                return None
            client_id, params, _info = geladen
            await con.execute("DELETE FROM oauth_anfrage WHERE id_hash = $1", _hash(anfrage))
            redirect = params["redirect_uri"]
            if not zustimmen:
                return {"redirect_url": construct_redirect_uri(
                    redirect, error="access_denied", error_description="Der Nutzer hat abgelehnt.",
                    state=params.get("state"))}
            angefragt = [s for s in (params.get("scopes") or SCOPES) if s in SCOPES]
            gewaehlt = [s for s in (scopes or angefragt) if s in angefragt]
            if "read" not in gewaehlt:
                gewaehlt = ["read"] + gewaehlt
            if not await _mitglied_aktiv(con, user_id, account_id):
                return None
            code = PRAEFIX_CODE + secrets.token_urlsafe(32)
            await con.execute(
                """INSERT INTO oauth_code (code_hash, client_id, user_id, account_id, scopes,
                       code_challenge, redirect_uri, redirect_explizit, resource, ablauf)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                _hash(code), client_id, int(user_id), int(account_id), gewaehlt,
                params["code_challenge"], redirect, bool(params.get("redirect_explizit", True)),
                params.get("resource"), _jetzt() + timedelta(seconds=CODE_TTL_S))
            await con.execute("UPDATE oauth_client SET zuletzt_genutzt = now() WHERE client_id = $1", client_id)
    return {"redirect_url": construct_redirect_uri(redirect, code=code, state=params.get("state"))}


# ---------- Verbundene Apps ----------

async def verbindungen_liste(user_id: int, account_id: int) -> list[dict]:
    async with pool().acquire() as con:
        rows = await con.fetch(
            """SELECT g.id, g.scopes, g.erstellt, g.zuletzt_genutzt, c.info->>'client_name' AS client_name
               FROM oauth_grant g LEFT JOIN oauth_client c ON c.client_id = g.client_id
               WHERE g.user_id = $1 AND g.account_id = $2 AND g.widerrufen IS NULL
                 AND EXISTS (SELECT 1 FROM oauth_token t WHERE t.grant_id = g.id AND t.art = 'refresh'
                             AND t.ersetzt IS NULL AND t.ablauf > now())
               ORDER BY g.erstellt DESC""", int(user_id), int(account_id))
    return [{"id": r["id"], "client_name": r["client_name"] or "Unbenannter Client",
             "scopes": list(r["scopes"]), "erstellt": r["erstellt"].isoformat(),
             "zuletzt_genutzt": r["zuletzt_genutzt"].isoformat() if r["zuletzt_genutzt"] else None}
            for r in rows]


async def verbindung_widerrufen(grant_id: int, user_id: int, account_id: int) -> bool:
    async with pool().acquire() as con:
        r = await con.fetchval(
            "UPDATE oauth_grant SET widerrufen = now() WHERE id = $1 AND user_id = $2 AND account_id = $3 "
            "AND widerrufen IS NULL RETURNING id", int(grant_id), int(user_id), int(account_id))
        if r:
            await con.execute("DELETE FROM oauth_token WHERE grant_id = $1", int(grant_id))
    return bool(r)


# ---------- Persönliche Zugriffstokens (Claude Code / Desktop, Header) ----------

async def pat_erstellen(user_id: int, account_id: int, name: str, scopes: list[str],
                        gueltig_tage: int | None = None) -> dict:
    name = (name or "").strip()[:80] or "Zugriffstoken"
    scopes = [s for s in SCOPES if s in (scopes or [])]
    if "read" not in scopes:
        scopes = ["read"] + scopes
    token = PRAEFIX_PAT + secrets.token_urlsafe(32)
    ablauf = _jetzt() + timedelta(days=int(gueltig_tage)) if gueltig_tage else None
    async with pool().acquire() as con:
        anzahl = await con.fetchval(
            "SELECT count(*) FROM api_token WHERE user_id = $1 AND widerrufen IS NULL", int(user_id))
        if anzahl is not None and anzahl >= 20:
            return {"error": "Höchstens 20 aktive Zugriffstokens. Bitte zuerst eines widerrufen."}
        r = await con.fetchrow(
            "INSERT INTO api_token (user_id, account_id, name, token_hash, anzeige, scopes, ablauf) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id, erstellt",
            int(user_id), int(account_id), name, _hash(token), token[:8] + "…" + token[-4:], scopes, ablauf)
    return {"id": r["id"], "name": name, "scopes": scopes, "token": token,
            "erstellt": r["erstellt"].isoformat(), "ablauf": ablauf.isoformat() if ablauf else None}


async def pat_liste(user_id: int, account_id: int) -> list[dict]:
    async with pool().acquire() as con:
        rows = await con.fetch(
            "SELECT id, name, anzeige, scopes, erstellt, zuletzt_genutzt, ablauf FROM api_token "
            "WHERE user_id = $1 AND account_id = $2 AND widerrufen IS NULL ORDER BY erstellt DESC",
            int(user_id), int(account_id))
    return [{"id": r["id"], "name": r["name"], "anzeige": r["anzeige"], "scopes": list(r["scopes"]),
             "erstellt": r["erstellt"].isoformat(),
             "zuletzt_genutzt": r["zuletzt_genutzt"].isoformat() if r["zuletzt_genutzt"] else None,
             "ablauf": r["ablauf"].isoformat() if r["ablauf"] else None} for r in rows]


async def pat_widerrufen(token_id: int, user_id: int) -> bool:
    async with pool().acquire() as con:
        r = await con.fetchval(
            "UPDATE api_token SET widerrufen = now() WHERE id = $1 AND user_id = $2 AND widerrufen IS NULL "
            "RETURNING id", int(token_id), int(user_id))
    return bool(r)


async def _pat_pruefen(token: str) -> AccessToken | None:
    async with pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT id, user_id, account_id, scopes, ablauf, widerrufen, zuletzt_genutzt FROM api_token "
            "WHERE token_hash = $1", _hash(token))
        if r is None or r["widerrufen"] is not None or (r["ablauf"] and r["ablauf"] < _jetzt()):
            return None
        if not await _mitglied_aktiv(con, r["user_id"], r["account_id"]):
            return None
        if r["zuletzt_genutzt"] is None or r["zuletzt_genutzt"] < _jetzt() - timedelta(minutes=5):
            await con.execute("UPDATE api_token SET zuletzt_genutzt = now() WHERE id = $1", r["id"])
    return _access_token(token, client_id=f"pat:{r['id']}", scopes=list(r["scopes"]),
                         expires_at=int(r["ablauf"].timestamp()) if r["ablauf"] else None,
                         resource=mcp_resource_url(), user_id=r["user_id"], account_id=r["account_id"],
                         art="pat", ref_id=r["id"])


# ---------- Aufräumen (täglicher Job) ----------

async def aufraeumen() -> dict:
    async with pool().acquire() as con:
        a = await con.execute("DELETE FROM oauth_anfrage WHERE ablauf < now()")
        c = await con.execute("DELETE FROM oauth_code WHERE ablauf < now() - interval '1 day'")
        t = await con.execute(
            "DELETE FROM oauth_token WHERE ablauf < now() - interval '1 day' "
            "OR (ersetzt IS NOT NULL AND ersetzt < now() - interval '30 days')")
        g = await con.execute(
            "DELETE FROM oauth_grant g WHERE (widerrufen IS NOT NULL AND widerrufen < now() - interval '30 days') "
            "OR NOT EXISTS (SELECT 1 FROM oauth_token t WHERE t.grant_id = g.id)")
        k = await con.execute(
            "DELETE FROM oauth_client c WHERE erstellt < now() - interval '1 day' "
            "AND NOT EXISTS (SELECT 1 FROM oauth_grant g WHERE g.client_id = c.client_id) "
            "AND (zuletzt_genutzt IS NULL OR zuletzt_genutzt < now() - interval '30 days')")
    return {"anfragen": a, "codes": c, "tokens": t, "grants": g, "clients": k, "zeit": time.time()}


OAUTH_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS oauth_client (
         client_id text PRIMARY KEY,
         info jsonb NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now(),
         zuletzt_genutzt timestamptz)""",
    """CREATE TABLE IF NOT EXISTS oauth_anfrage (
         id_hash text PRIMARY KEY,
         client_id text NOT NULL,
         params jsonb NOT NULL,
         ablauf timestamptz NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS oauth_grant (
         id serial PRIMARY KEY,
         client_id text NOT NULL,
         user_id integer NOT NULL,
         account_id integer NOT NULL,
         scopes text[] NOT NULL,
         resource text,
         erstellt timestamptz NOT NULL DEFAULT now(),
         zuletzt_genutzt timestamptz,
         widerrufen timestamptz)""",
    "CREATE INDEX IF NOT EXISTS oauth_grant_user_idx ON oauth_grant (user_id, account_id)",
    """CREATE TABLE IF NOT EXISTS oauth_code (
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
         grant_id integer)""",
    """CREATE TABLE IF NOT EXISTS oauth_token (
         token_hash text PRIMARY KEY,
         art text NOT NULL CHECK (art IN ('access', 'refresh')),
         grant_id integer NOT NULL REFERENCES oauth_grant(id) ON DELETE CASCADE,
         scopes text[] NOT NULL,
         ablauf timestamptz NOT NULL,
         ersetzt timestamptz,
         erstellt timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS oauth_token_grant_idx ON oauth_token (grant_id)",
    """CREATE TABLE IF NOT EXISTS api_token (
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
         widerrufen timestamptz)""",
    "CREATE INDEX IF NOT EXISTS api_token_user_idx ON api_token (user_id)",
]


def _rls_stmts(tabelle: str) -> list[str]:
    bedingung = ("(current_setting('app.bypass', true) = 'on' OR account_id = "
                 "(NULLIF(current_setting('app.account_id', true), ''))::integer)")
    return [
        f"ALTER TABLE {tabelle} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {tabelle} FORCE ROW LEVEL SECURITY",
        f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                             AND tablename = '{tabelle}' AND policyname = 'acc_isolation') THEN
                CREATE POLICY acc_isolation ON {tabelle} USING {bedingung} WITH CHECK {bedingung};
              END IF;
            END $$""",
    ]


# Kontobezogene MCP-Tabellen (RLS wie die übrigen Haushaltsdaten).
KONTO_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS kochmodus_schritte (
         account_id integer NOT NULL DEFAULT (NULLIF(current_setting('app.account_id', true), ''))::integer,
         rezept_id integer NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
         signatur text NOT NULL,
         quelle_hash text NOT NULL,
         schritte jsonb NOT NULL,
         quelle text NOT NULL DEFAULT 'ki',
         aktualisiert timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, rezept_id, signatur))""",
    *_rls_stmts("kochmodus_schritte"),
    """CREATE TABLE IF NOT EXISTS mcp_idempotenz (
         account_id integer NOT NULL DEFAULT (NULLIF(current_setting('app.account_id', true), ''))::integer,
         werkzeug text NOT NULL,
         schluessel text NOT NULL,
         ergebnis jsonb NOT NULL,
         erstellt timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, werkzeug, schluessel))""",
    *_rls_stmts("mcp_idempotenz"),
]

