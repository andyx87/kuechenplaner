# Küchenplaner als Connector in Claude

Küchenplaner bringt einen MCP-Server mit. In Claude (claude.ai, Claude Desktop, Claude mobile,
Claude Code) eingebunden, übernimmt Claude die KI-Arbeit im Chat – Prospekte, Fotos und
Rezepttexte lesen, Rezepte schreiben, Kochschritte strukturieren – und Küchenplaner speichert
nur die strukturierten Ergebnisse und rechnet (Zutaten-Abgleich, Einkaufsliste,
Vorschläge). Mit einem Claude-Abo braucht die Instanz dafür **keinen eigenen KI-Schlüssel**.
Einzige Ausnahme ist die Bildgenerierung (`rezeptbild_erzeugen`), die den Bild-Anbieter des
Servers braucht.

Stand: 25.10.2026, fastmcp 4.1.3 / MCP-Python-SDK 2.3.0.

## 1. Was Claude verlangt (geprüft)

| Anforderung | Umsetzung in Küchenplaner |
|---|---|
| Remote-Server per **Streamable HTTP** (Legacy-SSE wird noch unterstützt, aber abgekündigt) [1] | FastMCP `http_app(path="/mcp", stateless_http=True)` → `https://<host>/mcp` |
| Öffentlich per **HTTPS** erreichbar; Aufrufe kommen aus Anthropics Infrastruktur (`160.79.104.0/21`), nicht vom Gerät [2] | Reverse-Proxy/Tunnel vor die Instanz, s. Abschnitt 2 |
| **OAuth 2.0/2.1**, Claude folgt den MCP-Autorisierungsspezifikationen 2025-03-26, 2025-06-18 und 2025-11-25 [1][3] | Küchenplaner ist selbst Authorization Server (`app/oauth.py`) |
| `401` mit `WWW-Authenticate: Bearer resource_metadata="…"` startet die Anmeldung; Claude übernimmt `scope` aus dem Header [2][3] | FastMCP-Bearer-Middleware; Scopes `read write` im Header |
| **Protected Resource Metadata** (RFC 9728), `resource` = exakt die eingetragene Server-URL, erster Eintrag in `authorization_servers` wird benutzt [2][3] | `/.well-known/oauth-protected-resource/mcp` (und Wurzelpfad als Fallback) |
| **Authorization Server Metadata** (RFC 8414) [2][3] | `/.well-known/oauth-authorization-server`, Issuer = `PUBLIC_URL` |
| **Dynamic Client Registration** (RFC 7591) – Claude registriert sich als öffentlicher Client; alternativ CIMD [2] | `/register` (DCR). CIMD wird nicht angeboten → Claude nutzt DCR |
| **PKCE S256** bei jeder Autorisierung, `code_challenge_methods_supported: ["S256"]` [2][3] | `/authorize` (nur S256), Prüfung am `/token` |
| Callback `https://claude.ai/api/mcp/auth_callback` (künftig evtl. `claude.com`), Claude Code: Loopback auf beliebigem Port, `localhost` **und** `127.0.0.1` [2] | Redirect-Allowlist mit beiden Callbacks + portunabhängigem Loopback-Abgleich |
| `resource`-Parameter (RFC 8707) in Autorisierung und Token-Anfrage; Server prüft Audience [3] | Fremde `resource` → `invalid_target`; Token an die MCP-URL gebunden |
| Token-Ablauf und **Refresh**; bei ungültigem Refresh `invalid_grant`; **Rotation** für öffentliche Clients, neuer Refresh-Token in derselben Antwort [2][3] | Access 1 h, Refresh 30 Tage, Rotation; Wiederverwendung eines alten Refresh-Tokens widerruft die Verbindung |
| `/token` nimmt `application/x-www-form-urlencoded`, `/register` JSON [2] | SDK-Handler |
| Antwortzeiten: Discovery/Registrierung/Token ≤ 10 s, Refresh ≤ 30 s [2] | lokale DB-Abfragen, kein Fremdaufruf |
| Ergebnisgrenzen: ~150 000 Zeichen je Tool-Ergebnis, 240 s je Aufruf (claude.ai/Desktop); Claude Code 25 000 Token (`MAX_MCP_OUTPUT_TOKENS`) [1] | Listen paginiert (`limit`, `cursor`), keine Bilddaten in Listen |
| Unterstützt: Tools, Prompts, Resources, Text- und Bild-Ergebnisse; **nicht**: Sampling, Resource-Subscriptions [1] | Tools + Prompts; kein Sampling |
| Zustimmungsseite soll den Host der Redirect-URI deutlich zeigen und bei reinen Loopback-Clients warnen [2][4] | `/verbinden` in der Web-App |

Quellen:

1. Build an MCP server for Claude – <https://claude.com/docs/connectors/building/index.md>
2. Authentication for connectors – <https://claude.com/docs/connectors/building/authentication.md>
3. MCP-Spezifikation, Authorization – <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>
   (aktuelle Fassung: <https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization>)
4. Add a connector that isn't in the directory – <https://claude.com/docs/connectors/custom/add-unlisted.md>
5. Claude Code: MCP – <https://code.claude.com/docs/en/mcp>

### Was davon FastMCP liefert

fastmcp 4.1.3 (`fastmcp.server.auth.OAuthProvider`) bringt mit dem MCP-SDK die Endpunkte
`/authorize`, `/token`, `/register`, `/revoke`, die PKCE-Prüfung, die Bearer-Middleware mit
`WWW-Authenticate` und `require_scopes` für einzelne Werkzeuge. Küchenplaner implementiert die
Speicher-Schnittstelle in Postgres und ergänzt:

- eigene Metadaten-Dokumente (Issuer ohne abschließenden Slash in RFC 8414 und 9728,
  `none` als Token-Endpunkt-Methode – das SDK nennt nur `client_secret_*`),
- portunabhängigen Loopback-Abgleich (das SDK vergleicht Redirect-URIs exakt),
- einen Ausgleich am `/revoke`: das SDK verlangt dort ein `client_secret`-Feld, das
  öffentliche Clients nach RFC 7009 nicht senden; fehlt es, wird es leer ergänzt,
- Rate-Limits für `/register` (10/h je IP, 30/h gesamt).

## 2. Selbst hosten hinter HTTPS

Claude ruft den Server **aus dem Internet** auf. Ein reiner LAN-Betrieb funktioniert mit
claude.ai, Desktop und Mobile nicht (Claude Code auf demselben Rechner ginge auch lokal).

1. `.env` (s. `.env.example`):

   ```env
   APP_BASE_URL=https://kochen.example.org   # Web-App (Zustimmungsseite /verbinden)
   PUBLIC_URL=https://kochen.example.org     # Issuer + MCP-Ressource; leer = APP_BASE_URL
   MCP_ENABLED=1
   APP_DB_PASSWORD=<zufällig>
   DATABASE_URL=postgresql://koch_app:<APP_DB_PASSWORD>@db:5432/koch
   TRUSTED_PROXY_HOPS=1
   ```

   Die App muss sich als **Nicht-Superuser** verbinden (`koch_app`, wird von
   `db/02-app-rolle.sh` beim ersten Start angelegt). Ein Superuser umgeht Row Level
   Security – dann wären die Haushalte nicht getrennt.

2. Reverse-Proxy mit TLS vor den Frontend-Container (`koch-web`, Port 8096). Dessen nginx
   leitet `/api`, `/mcp`, `/.well-known/oauth-*`, `/authorize`, `/token`, `/register` und
   `/revoke` an das Backend. Beispiel Caddy:

   ```caddyfile
   kochen.example.org {
       reverse_proxy localhost:8096
   }
   ```

   Ein Tunnel (z. B. Cloudflare Tunnel) geht genauso. Liegt eine Zugangssperre davor
   (Basic-Auth, Cloudflare Access, VPN), müssen `/mcp`, `/.well-known/*`, `/token`,
   `/register` und `/revoke` für Anthropics Adressbereich `160.79.104.0/21` frei sein –
   diese Aufrufe kommen von Claudes Servern, nicht aus dem Browser. `/authorize` und
   `/verbinden` öffnet dagegen der Browser des Nutzers.

3. Bestehende Datenbanken: `migration_mcp_oauth.sql` einmal als Eigentümer der Tabellen
   einspielen (die App versucht es beim Start selbst, braucht dafür aber DDL-Rechte).

4. Prüfen:

   ```bash
   curl -s https://kochen.example.org/.well-known/oauth-protected-resource/mcp
   curl -s https://kochen.example.org/.well-known/oauth-authorization-server
   curl -si -X POST https://kochen.example.org/mcp | grep -i www-authenticate
   ```

Weitere Einstellungen: `OAUTH_REDIRECT_URIS` (zusätzliche exakte Redirect-URIs anderer
Clients), `OAUTH_REDIRECT_FREI=1` (jede HTTPS-Redirect-URI zulassen), `OAUTH_ACCESS_TTL_S`,
`OAUTH_REFRESH_TTL_TAGE`. Abgelaufene Anfragen, Codes, Tokens und unbenutzte Clients räumt
ein täglicher Job auf.

## 3. Connector in Claude hinzufügen

**claude.ai / Claude Desktop / Mobile (Free, Pro, Max):** *Customize → Connectors → Add
custom connector*, Name „Küchenplaner“, URL `https://kochen.example.org/mcp`. Bei der
OAuth-Client-Auswahl *Register automatically* (DCR) wählen bzw. die Felder für Client-ID
und Secret leer lassen. Free-Konten können einen eigenen Connector anlegen. Auf Team- und
Enterprise-Plänen fügt ein Owner den Connector unter *Organization settings → Connectors*
hinzu, danach verbindet jedes Mitglied sein eigenes Küchenplaner-Konto. [4]

Beim Verbinden öffnet sich `https://kochen.example.org/verbinden?...`: Anmelden (falls
nötig), Haushalt, anfragende App, Ziel-Host und Rechte prüfen, **Zulassen**. „Schreiben“
lässt sich abwählen – dann sieht Claude nur die lesenden Werkzeuge.

**Claude Code** mit OAuth:

```bash
claude mcp add --transport http kuechenplaner https://kochen.example.org/mcp
# danach in Claude Code: /mcp → kuechenplaner → anmelden (Browser)
```

**Claude Code** mit persönlichem Zugriffstoken (z. B. für `claude -p` ohne Browser):
In Küchenplaner *Einstellungen → Claude & MCP → Token erstellen*, dann

```bash
claude mcp add --transport http kuechenplaner https://kochen.example.org/mcp \
  --header "Authorization: Bearer tpp_…"
```

Persönliche Tokens werden nur einmal angezeigt, sind an Nutzer und Haushalt gebunden und
lassen sich in den Einstellungen widerrufen. Dort stehen auch alle **verbundenen Apps**
(OAuth) mit „Trennen“.

## 4. Werkzeuge

Alle Werkzeuge handeln ausschließlich im Haushalt des angemeldeten Nutzers (RLS). Plattform-
Admin-Rechte gelten über MCP nicht. Lesende Werkzeuge sind als `readOnlyHint`, löschende als
`destructiveHint` markiert; schreibende verlangen den Scope `write`.

| Bereich | Werkzeuge |
|---|---|
| Einstieg | `haushalt_uebersicht` |
| Angebote | `angebote_schema`, `angebote_importieren` (Batch ≤ 500, Vorschau, Idempotenz-Schlüssel, Dubletten werden übersprungen), `angebote_holen`, `angebote_blatt_loeschen` |
| Vorrat & Geräte | `vorrat_buchen` (Batch ≤ 200, Vorschau mit Zutaten-Abgleich exakt/Umlaut/Plural/neu), `vorrat_holen`, `vorrat_aendern`, `vorrat_loeschen`, `geraete_anlegen`, `geraete_heute_setzen` |
| Rezepte | `rezepte_suchen`, `rezept_holen`, `rezept_anlegen`, `rezept_aendern`, `rezepte_anpassungsbedarf` + `rezepte_aktualisieren` („alle Rezepte aktualisieren“), `rezepte_vorschlagen` (Vorrat + heutige Geräte), `rezepte_aus_angeboten`, `rezept_vorrat_check`, `rezept_loeschen` |
| Plan & Einkauf | `wochenplan_holen`, `wochenplan_setzen`, `plan_eintraege_loeschen`, `einkaufstag_setzen`, `einkaufsliste_erzeugen`, `einkauf_extra_hinzufuegen`, `einkauf_abhaken` (gekaufte Positionen → Vorrat) |
| Kochmodus | `kochmodus_holen`, `kochmodus_speichern` (Schritte je Haushalt; die Web-App zeigt sie mit Timern) |
| Bild | `rezeptbild_erzeugen` (nur mit Bild-Anbieter auf dem Server, sonst klare Fehlermeldung) |

Fertige Abläufe als MCP-Prompts: `prospekt_importieren`, `vorrat_aus_foto`,
`wochenplan_erstellen`, `rezepte_an_geraete_anpassen`, `kochmodus_vorbereiten`.

## 5. Beispiel-Prompts

- *Prospekt:* „Hier ist der Prospekt von Supermarkt Musterstadt für nächste Woche
  (PDF/Link). Übernimm alle Lebensmittel-Angebote in Küchenplaner – erst Vorschau zeigen.“
- *Küchenfoto:* „Das ist mein Kühlschrank. Trag alles mit geschätzter Menge in den Vorrat
  ein, Lagerort Kühlschrank. Zeig mir vorher, was du neu anlegen würdest.“
- *Geräte:* „Auf dem Foto siehst du meine Küche. Leg die Geräte an, die du erkennst.“
- *Rezept:* „Speichere dieses Rezept (Link) in Küchenplaner, mit Varianten für meine Geräte.“
- *Alle Rezepte aktualisieren:* „Ich habe jetzt eine Heißluftfritteuse. Passe alle meine
  Rezepte an meine Geräte an.“
- *Vorschläge:* „Was kann ich heute mit meinem Vorrat und den heutigen Geräten kochen?“ /
  „Welche Rezepte passen zu den Angeboten dieser Woche?“
- *Woche:* „Plane Abendessen für Montag bis Freitag, nutze die Angebote, Anna isst
  vegetarisch. Danach die Einkaufsliste.“
- *Einkauf:* „Ich habe Reis (1 kg) und Tomaten (500 g) gekauft – abhaken und in den
  Vorrat.“
- *Kochmodus:* „Bereite den Kochmodus für Rezept 12 vor.“

## 6. Grenzen

- **Keine Datei-Übergabe an Werkzeuge.** Claude kann hochgeladene Fotos oder PDFs nicht als
  Binärdaten an ein MCP-Werkzeug weiterreichen. Fotos, Prospekte und PDFs liest Claude im
  Chat selbst und schickt nur die erkannten Daten. Die Produktausschnitte, die der
  serverseitige Prospekt-Import der Web-App erzeugt, gibt es auf diesem Weg nicht.
- Kein serverseitiges Abrufen von Links durch Küchenplaner: Claude öffnet Links mit seinen
  eigenen Werkzeugen.
- Ergebnisgröße: große Listen sind paginiert. Bei sehr großen Prospekten lieber pro
  Seitenbereich importieren (Dubletten werden übersprungen, Idempotenz-Schlüssel helfen bei
  Wiederholungen).
- Bildgenerierung braucht einen Bild-Anbieter auf dem Server (`KI_IMAGE_MODEL` usw.) und
  verursacht dort Kosten.
- Der Abhak-Status der Einkaufsliste in der Web-App ist weiterhin gerätelokal;
  `einkauf_abhaken` bucht Gekauftes in den Vorrat und entfernt erledigte manuelle Artikel.
- Klarnamen: Über MCP sieht Claude die Namen der Haushaltsmitglieder (anders als der
  In-App-Chat, der pseudonymisiert).
- Nicht umgesetzt: Client ID Metadata Documents (CIMD), Enterprise Managed Auth,
  `client_credentials`. Claude fällt ohne CIMD auf DCR zurück. [2]

## 7. Tests

```bash
python -m pytest -q tests                      # ohne Datenbank
TEST_DATABASE_URL_ADMIN=postgresql://koch:pw@localhost:5432/koch \
  python -m pytest -q tests_db                 # Wegwerf-Postgres 16: Schema wird neu angelegt!
```

`tests_db/` startet die echte App (uvicorn) gegen eine Nicht-Superuser-Rolle und spielt den
kompletten Claude-Ablauf durch: 401 + Discovery, DCR mit Redirect-Policy, Zustimmung, PKCE,
Code- und Refresh-Wiederverwendung, Rotation, Widerruf, Lese-Scope, persönliche Tokens,
entzogene Mitgliedschaft, Haushaltstrennung und alle Werkzeug-Abläufe. Nicht automatisiert
getestet ist die Verbindung mit dem echten Claude-Client.
