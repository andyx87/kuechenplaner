"""Unit-Tests ohne Datenbank: Redirect-Policy, Loopback-Abgleich (RFC 8252), Audience-
Prüfung (RFC 8707) und die Pydantic-Schemas der MCP-Werkzeuge. Der komplette OAuth-Ablauf
(DCR, PKCE, Refresh-Rotation, Widerruf, Haushaltstrennung) läuft in tests_db/ gegen Postgres."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app import config, oauth, schemas  # noqa: E402


def test_redirect_policy(monkeypatch):
    assert oauth.redirect_erlaubt("https://claude.ai/api/mcp/auth_callback")
    assert oauth.redirect_erlaubt("https://claude.com/api/mcp/auth_callback")
    assert oauth.redirect_erlaubt("http://localhost:4711/callback")
    assert oauth.redirect_erlaubt("http://127.0.0.1:33418/callback")
    assert not oauth.redirect_erlaubt("https://angreifer.example/cb")
    assert not oauth.redirect_erlaubt("http://claude.ai/api/mcp/auth_callback")
    assert not oauth.redirect_erlaubt("https://claude.ai/api/mcp/auth_callback#frag")
    assert not oauth.redirect_erlaubt("")
    monkeypatch.setattr(config, "OAUTH_REDIRECT_URIS", ["https://mein-client.example/cb"])
    assert oauth.redirect_erlaubt("https://mein-client.example/cb")
    monkeypatch.setattr(config, "OAUTH_REDIRECT_FREI", True)
    assert oauth.redirect_erlaubt("https://irgendwer.example/cb")
    assert not oauth.redirect_erlaubt("http://irgendwer.example/cb")


def test_loopback_portunabhaengig():
    from pydantic import AnyUrl
    c = oauth.TopfplanClient(client_id="x", redirect_uris=[AnyUrl("http://localhost:1234/callback")])
    assert str(c.validate_redirect_uri(AnyUrl("http://localhost:5555/callback"))).startswith("http://localhost:5555")
    from mcp.shared.auth import InvalidRedirectUriError
    with pytest.raises(InvalidRedirectUriError):
        c.validate_redirect_uri(AnyUrl("http://localhost:5555/anders"))
    with pytest.raises(InvalidRedirectUriError):
        c.validate_redirect_uri(AnyUrl("http://127.0.0.1:5555/callback"))
    h = oauth.TopfplanClient(client_id="y", redirect_uris=[AnyUrl("https://claude.ai/api/mcp/auth_callback")])
    with pytest.raises(InvalidRedirectUriError):
        h.validate_redirect_uri(AnyUrl("https://claude.ai:8443/api/mcp/auth_callback"))


def test_resource_audience(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://kochen.example.org")
    assert oauth.resource_passt(None)
    assert oauth.resource_passt("https://kochen.example.org/mcp")
    assert oauth.resource_passt("https://KOCHEN.example.org/mcp/")
    assert oauth.resource_passt("https://kochen.example.org")
    assert not oauth.resource_passt("https://kochen.example.org.evil.example/mcp")
    assert not oauth.resource_passt("https://anderer.example/mcp")


def test_schema_vorrat_und_angebote():
    with pytest.raises(Exception):
        schemas.VorratPosten(name="Reis", menge=0, einheit="g")
    with pytest.raises(Exception):
        schemas.VorratPosten(name="Reis", menge=1, einheit="g", mhd="31.12.2026")
    with pytest.raises(Exception):
        schemas.VorratPosten(name="Reis", menge=1, einheit="g", unbekannt=1)   # extra=forbid
    with pytest.raises(Exception):
        schemas.AngeboteImport(markt="M", gueltig_von="2026-02-01", gueltig_bis="2026-01-01",
                               angebote=[{"name": "Butter", "preis": 1}])
    imp = schemas.AngeboteImport(markt="M", gueltig_von="2026-01-01", gueltig_bis="2026-01-07",
                                 angebote=[{"name": "Butter", "preis": 1.99}])
    assert imp.angebote[0].art == "zutat"
    js = schemas.AngeboteImport.model_json_schema()
    posten = js["$defs"]["AngebotPosten"]["properties"]
    assert {"name", "marke", "menge", "einheit", "preis", "grundpreis", "kategorie"} <= set(posten)


def test_schema_rezept():
    with pytest.raises(Exception):
        schemas.RezeptIn(name="X", zutaten=[], zubereitung=[{"titel": "A", "varianten": [{"text": "abc"}]}])
    with pytest.raises(Exception):
        schemas.RezeptIn(name="X", zutaten=[{"name": "Reis"}], gang="Irgendwas",
                         zubereitung=[{"titel": "A", "varianten": [{"text": "abc"}]}])
    r = schemas.RezeptIn(name="X", zutaten=[{"name": "Reis"}],
                         zubereitung=[{"titel": "A", "varianten": [{"geraet": None, "text": "kochen"}]}])
    assert r.portionen == 2
    u = schemas.RezeptUpdate(rezept_id=3, portionen=4)
    assert u.model_dump(exclude_unset=True) == {"rezept_id": 3, "portionen": 4}
