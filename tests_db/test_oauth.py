"""OAuth 2.1 für den MCP-Connector: Discovery, DCR, PKCE, Refresh-Rotation, Widerruf,
persönliche Tokens und Haushaltstrennung."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from conftest import admin_sql
from helfer import (CLAUDE_CALLBACK, anfrage_aus, autorisieren, mcp, mcp_status, mcp_tools, ok, pkce,
                    refresh, registrieren, token_tausch, voller_ablauf, zustimmen)


def test_401_mit_resource_metadata(server):
    r = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401
    www = r.headers["www-authenticate"]
    assert www.startswith("Bearer")
    assert f'resource_metadata="{server}/.well-known/oauth-protected-resource/mcp"' in www
    assert "read" in www and "write" in www   # Claude übernimmt die Scopes aus dem Header


def test_metadaten(server):
    prm = httpx.get(f"{server}/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == f"{server}/mcp"
    assert prm["authorization_servers"][0].rstrip("/") == server
    asm = httpx.get(f"{server}/.well-known/oauth-authorization-server").json()
    assert asm["issuer"].rstrip("/") == server
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        assert asm[k].startswith(server)
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert "none" in asm["token_endpoint_auth_methods_supported"]
    assert set(asm["scopes_supported"]) == {"read", "write"}
    assert "refresh_token" in asm["grant_types_supported"]


def test_dcr_redirect_policy(server):
    assert registrieren(server).status_code == 201
    assert registrieren(server, "https://claude.com/api/mcp/auth_callback").status_code == 201
    assert registrieren(server, "http://localhost:33418/callback").status_code == 201
    boese = registrieren(server, "https://angreifer.example/callback")
    assert boese.status_code == 400
    assert boese.json()["error"] == "invalid_redirect_uri"


def test_voller_ablauf_und_mcp(server, nutzer):
    a = nutzer("Anna")
    tok = voller_ablauf(server, a["token"])
    assert tok["token_type"] == "Bearer" and tok["expires_in"] > 0
    assert tok["access_token"].startswith("tpa_") and tok["refresh_token"].startswith("tpr_")
    assert set(tok["scope"].split()) == {"read", "write"}
    daten = ok(server, tok["access_token"], "haushalt_uebersicht")
    assert daten["haushalt"] == "Annas Haushalt"
    # Tokens nur gehasht gespeichert
    rows = admin_sql("SELECT token_hash FROM oauth_token")
    assert all(tok["access_token"] not in r["token_hash"] and len(r["token_hash"]) == 64 for r in rows)


def test_anfrage_info_und_ablehnung(server, nutzer):
    a = nutzer()
    cid = registrieren(server).json()["client_id"]
    _v, ch = pkce()
    anfrage = anfrage_aus(autorisieren(server, cid, ch))
    info = httpx.get(f"{server}/api/oauth/anfrage/{anfrage}", headers={"Authorization": f"Bearer {a['token']}"}).json()
    assert info["client_name"] == "Claude" and info["redirect_host"] == "claude.ai"
    assert {s["scope"] for s in info["scopes"]} == {"read", "write"}
    # ohne Login keine Zustimmung
    assert httpx.get(f"{server}/api/oauth/anfrage/{anfrage}").status_code == 401
    r = zustimmen(server, a["token"], anfrage, ja=False)
    q = parse_qs(urlparse(r.json()["redirect_url"]).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["xyz"]
    # Anfrage ist verbraucht
    assert zustimmen(server, a["token"], anfrage).status_code == 404


def test_pkce_falscher_verifier_und_code_wiederverwendung(server, nutzer):
    a = nutzer()
    cid = registrieren(server).json()["client_id"]
    verifier, ch = pkce()
    anfrage = anfrage_aus(autorisieren(server, cid, ch))
    code = parse_qs(urlparse(zustimmen(server, a["token"], anfrage).json()["redirect_url"]).query)["code"][0]
    falsch = token_tausch(server, cid, code, "x" * 50)
    assert falsch.status_code in (400, 401) and falsch.json()["error"] == "invalid_grant"
    gut = token_tausch(server, cid, code, verifier)
    assert gut.status_code == 200
    nochmal = token_tausch(server, cid, code, verifier)
    assert nochmal.json()["error"] == "invalid_grant"
    # Wiederverwendung widerruft die aus dem Code ausgestellte Verbindung
    assert mcp_status(server, gut.json()["access_token"]) == 401


def test_plain_pkce_und_fremder_resource_abgelehnt(server):
    cid = registrieren(server).json()["client_id"]
    r = httpx.get(f"{server}/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": "abc", "code_challenge_method": "plain", "state": "s"}, follow_redirects=False)
    assert r.status_code in (302, 400)
    if r.status_code == 302:
        assert "error=invalid_request" in r.headers["location"]
    _v, ch = pkce()
    r2 = autorisieren(server, cid, ch, resource="https://anderer-server.example/mcp")
    assert r2.status_code == 302 and "error=invalid_target" in r2.headers["location"]


def test_refresh_rotation_und_wiederverwendung(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"])
    r1 = refresh(server, t["client_id"], t["refresh_token"])
    assert r1.status_code == 200, r1.text
    neu = r1.json()
    assert neu["refresh_token"] != t["refresh_token"] and neu["access_token"] != t["access_token"]
    # altes Access-Token ist mit der Rotation abgelöst, neues funktioniert
    assert mcp(server, neu["access_token"], "haushalt_uebersicht")[0]
    # alter Refresh-Token erneut benutzt → invalid_grant + ganze Verbindung widerrufen
    r2 = refresh(server, t["client_id"], t["refresh_token"])
    assert r2.json()["error"] == "invalid_grant"
    assert mcp_status(server, t["access_token"]) == 401   # durch Rotation abgelöst
    assert mcp_status(server, neu["access_token"]) == 401  # durch Wiederverwendung widerrufen
    assert refresh(server, t["client_id"], neu["refresh_token"]).json()["error"] == "invalid_grant"


def test_refresh_fremder_client(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"])
    anderer = registrieren(server).json()["client_id"]
    assert refresh(server, anderer, t["refresh_token"]).json()["error"] == "invalid_grant"


def test_revocation_endpoint(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"])
    r = httpx.post(f"{server}/revoke", data={"token": t["access_token"], "client_id": t["client_id"]})
    assert r.status_code == 200
    assert mcp_status(server, t["access_token"]) == 401
    assert refresh(server, t["client_id"], t["refresh_token"]).json()["error"] == "invalid_grant"


def test_verbundene_apps_widerrufen(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"])
    h = {"Authorization": f"Bearer {a['token']}"}
    apps = httpx.get(f"{server}/api/verbindungen", headers=h).json()["apps"]
    assert len(apps) == 1 and apps[0]["client_name"] == "Claude"
    assert httpx.delete(f"{server}/api/verbindungen/apps/{apps[0]['id']}", headers=h).status_code == 200
    assert mcp_status(server, t["access_token"]) == 401
    assert httpx.get(f"{server}/api/verbindungen", headers=h).json()["apps"] == []
    b = nutzer()
    # fremde Verbindung kann man nicht widerrufen
    t2 = voller_ablauf(server, a["token"])
    fremd = httpx.get(f"{server}/api/verbindungen", headers=h).json()["apps"][0]["id"]
    assert httpx.delete(f"{server}/api/verbindungen/apps/{fremd}",
                        headers={"Authorization": f"Bearer {b['token']}"}).status_code == 404
    assert mcp(server, t2["access_token"], "haushalt_uebersicht")[0]


def test_nur_lesen_scope(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"], scopes=["read"])
    assert t["scope"] == "read"
    tools = mcp_tools(server, t["access_token"])
    assert "haushalt_uebersicht" in tools and "vorrat_holen" in tools
    assert "vorrat_buchen" not in tools and "rezept_loeschen" not in tools
    erfolgreich, _ = mcp(server, t["access_token"], "vorrat_buchen",
                         posten=[{"name": "Reis", "menge": 1, "einheit": "kg"}], vorschau=False)
    assert erfolgreich is False


def test_persoenliche_tokens(server, nutzer):
    a = nutzer()
    h = {"Authorization": f"Bearer {a['token']}"}
    r = httpx.post(f"{server}/api/verbindungen/tokens", json={"name": "Claude Code", "scopes": ["read", "write"]}, headers=h)
    assert r.status_code == 200, r.text
    pat = r.json()
    assert pat["token"].startswith("tpp_")
    liste = httpx.get(f"{server}/api/verbindungen", headers=h).json()["tokens"]
    assert liste[0]["name"] == "Claude Code" and "token" not in liste[0] and pat["token"] not in str(liste)
    assert ok(server, pat["token"], "haushalt_uebersicht")["haushalt"]
    assert httpx.delete(f"{server}/api/verbindungen/tokens/{pat['id']}", headers=h).status_code == 200
    assert mcp_status(server, pat["token"]) == 401
    # Session-Tokens der Web-App gelten am MCP-Endpunkt NICHT
    assert mcp_status(server, a["token"]) == 401


def test_mitgliedschaft_entzogen_token_ungueltig(server, nutzer):
    a = nutzer()
    t = voller_ablauf(server, a["token"])
    assert mcp(server, t["access_token"], "haushalt_uebersicht")[0]
    admin_sql("UPDATE app_user SET aktiv = false WHERE id = $1", a["user_id"])
    assert mcp_status(server, t["access_token"]) == 401
    b = nutzer()
    tb = voller_ablauf(server, b["token"])["access_token"]
    admin_sql("DELETE FROM account_mitglied WHERE user_id = $1", b["user_id"])
    assert mcp_status(server, tb) == 401


def test_haushalte_getrennt(server, nutzer):
    a, b = nutzer("Anna"), nutzer("Ben")
    ta = voller_ablauf(server, a["token"])["access_token"]
    tb = voller_ablauf(server, b["token"])["access_token"]
    ok(server, ta, "vorrat_buchen", posten=[{"name": "Geheimzutat Anna", "menge": 2, "einheit": "Stück"}],
       vorschau=False)
    rez = ok(server, ta, "rezept_anlegen", rezept={
        "name": "Annas Suppe", "portionen": 2, "zutaten": [{"name": "Tomaten", "menge": 500, "einheit": "g"}],
        "zubereitung": [{"titel": "Suppe", "varianten": [{"geraet": None, "text": "Tomaten kochen und pürieren."}]}]})
    # Ben sieht nichts davon
    assert ok(server, tb, "vorrat_holen")["gesamt"] == 0
    assert all(r["name"] != "Annas Suppe" for r in ok(server, tb, "rezepte_suchen")["eintraege"])
    assert mcp(server, tb, "rezept_holen", rezept_id=rez["rezept_id"])[0] is False
    # und kann nichts ändern oder löschen
    assert mcp(server, tb, "rezept_loeschen", rezept_id=rez["rezept_id"])[0] is False
    r = ok(server, tb, "rezepte_aktualisieren", rezepte=[{"rezept_id": rez["rezept_id"], "name": "gehackt"}],
           vorschau=False)
    assert r["aktualisiert"] == 0
    vid = ok(server, ta, "vorrat_holen")["eintraege"][0]["vorrat_id"]
    assert mcp(server, tb, "vorrat_aendern", vorrat_id=vid, menge=99)[0] is False
    assert ok(server, tb, "vorrat_loeschen", vorrat_ids=[vid])["geloescht"] == []
    assert ok(server, ta, "rezept_holen", rezept_id=rez["rezept_id"])["name"] == "Annas Suppe"
    assert ok(server, ta, "vorrat_holen")["eintraege"][0]["menge"] == 2


def test_super_admin_handelt_per_mcp_nur_im_eigenen_haushalt(server, nutzer):
    a = nutzer("Admin")
    admin_sql("UPDATE app_user SET plattform_rolle = 'super_admin' WHERE id = $1", a["user_id"])
    t = voller_ablauf(server, a["token"])["access_token"]
    ok(server, t, "angebote_importieren", markt="Testmarkt Admin", gueltig_von="2026-01-01",
       gueltig_bis="2099-12-31", angebote=[{"name": "Butter", "preis": 1.99}], vorschau=False)
    rows = admin_sql("SELECT account_id FROM angebote WHERE haendler = 'Testmarkt Admin'")
    assert rows and all(r["account_id"] == a["account_id"] for r in rows)   # nicht global (NULL)
