# Topfplan

Topfplan ist ein selbst gehosteter Küchenplaner für Haushalte: Vorrat, Rezepte,
Wochenplan, Einkaufsliste und Supermarkt-Angebote an einem Ort – als Web-App (PWA), die
du auf deinem eigenen Server betreibst. KI-Funktionen sind optional und laufen mit
**deinem eigenen Schlüssel** bei einem Anbieter deiner Wahl (oder lokal, z. B. mit Ollama).
Es gibt keine Abrechnung, keine Kontingente und keine Telemetrie.

> Status: frühe Open-Source-Fassung. Icons, Splash- und Vorschaubilder sind neutrale
> Platzhalter (`brand/build_placeholder.py`); echtes Artwork ist noch offen.
> Code und Kommentare sind überwiegend auf Deutsch.

*English summary below.*

## Funktionen

- **Vorrat** mit Lagerorten, Mengen, Ablaufdaten und Gebinde-Umrechnung; Zutaten werden
  auf Grundzutaten abgebildet (z. B. „Bio-Vollmilch 1 l“ → Milch)
- **Rezepte** anlegen und bearbeiten, Komponenten mit Varianten je Küchengerät, Bewertung,
  Suche, Vorschläge aus dem Vorrat („sofort kochbar“, „fast kochbar“), Kochen bucht den
  Vorrat ab, optionale gemeinsame Rezeptbibliothek der Instanz
- **Küchengeräte** und Geräte „heute verfügbar“; Rezepte lassen sich nach Geräten filtern
- **Wochenplan** mit Personen, Portionsfaktoren, Abwesenheitsregeln, Gästen,
  Vorlieben/Allergien, Einkaufstagen; Speiseplan als **ICS-Kalenderfeed**
- **Einkaufsliste** aus dem Plan (abzüglich Vorrat) plus eigene Extras
- **Angebote** aus Prospekten erfassen und bei Vorschlägen und Einkauf berücksichtigen
- **Haushalte** mit Mitgliedern und Einladungen, mehrere Haushalte pro Instanz
  (Mandantentrennung per Postgres Row-Level-Security)
- **Datenschutz-Werkzeuge:** Datenexport (JSON), Selbstlöschung von Konto oder Haushalt
- **Admin-Bereich:** Nutzer, Zutaten-Kuratierung, Fehlermeldungen, Kennzahlen
- **Connector für Claude (MCP mit OAuth 2.1):** Claude übernimmt im Chat Prospekte, Fotos
  und Rezepttexte und speichert über typisierte Werkzeuge Angebote, Vorrat, Geräte, Rezepte,
  Wochenplan und Kochmodus-Schritte; Topfplan rechnet Abgleich, Einkaufsliste und
  Vorschläge. Dafür braucht die Instanz keinen eigenen KI-Schlüssel (Ausnahme:
  Rezeptbilder). Zusätzlich persönliche Zugriffstokens, z. B. für Claude Code.
  Siehe [`docs/mcp-connector.md`](docs/mcp-connector.md).

Mit konfiguriertem KI-Anbieter zusätzlich:

- Chat-Assistent mit Zugriff auf Vorrat, Plan und Rezepte
- Rezept-Generator aus Vorrat, Geräten, Vorlieben und Angeboten
- Rezept-Import aus Links, eingefügtem Text, Screenshots und PDFs
- Vorrat und Geräte per Foto erfassen (immer mit Prüfschritt, nichts wird ungeprüft gespeichert)
- Prospekt-Import (PDF/Foto) inklusive Produktausschnitten
- Kochmodus mit Schritt-für-Schritt-Anleitung, Timern und Rückfragen
- Zubereitung an die eigenen Geräte anpassen
- optional Rezeptbilder generieren und Spracheingabe

Ohne KI-Anbieter blendet die Web-App alle KI-Knöpfe aus; der Rest funktioniert vollständig.

## Schnellstart mit Docker Compose

Voraussetzung: Docker mit Compose-Plugin.

```bash
git clone <repo-url> topfplan && cd topfplan
cp .env.example .env
# In .env mindestens setzen:
#   POSTGRES_PASSWORD=<sicheres Passwort>
#   APP_DB_PASSWORD=<weiteres sicheres Passwort>      # Rolle koch_app, kein Superuser
#   DATABASE_URL=postgresql://koch_app:<APP_DB_PASSWORD>@db:5432/koch
#   ADMIN_BOOTSTRAP_TOKEN=<einmaliger Zufallswert>   # erster Signup damit = Admin
docker compose up -d --build
```

- Web-App: <http://localhost:8096> – beim ersten Registrieren das `ADMIN_BOOTSTRAP_TOKEN`
  angeben, dann wird dieses Konto Plattform-Admin.
- API: <http://localhost:8095> (Health-Check `/health`, interaktive Doku `/docs`)

`schema.sql` und `db/02-app-rolle.sh` werden beim ersten Start (leeres Datenbank-Volume)
automatisch eingespielt. Die App verbindet sich als `koch_app` ohne Superuser-Rechte, weil
ein Superuser die Row-Level-Security und damit die Haushaltstrennung umgehen würde.
`docker compose down -v` setzt die Datenbank zurück.

Für den Betrieb im Internet gehört ein Reverse-Proxy mit HTTPS davor (z. B. Caddy, Traefik,
nginx). Die Web-App spricht relativ mit `/api/...`; der nginx des Frontend-Containers
proxyt `/api` an den Backend-Container.

### Entwicklung ohne Docker

```bash
# Backend
pip install -r app/requirements.txt
uvicorn app.main:app --port 8093

# Frontend
cd koch-web && npm install && npm run dev   # http://localhost:5173, proxyt /api -> :8093
```

## Konfiguration

Das Backend wird ausschließlich über Umgebungsvariablen konfiguriert; alle Variablen mit
Erläuterung stehen in [`.env.example`](.env.example) bzw. `app/config.py`.

| Variable | Zweck |
|---|---|
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `DATABASE_URL`, `DB_SCHEMA` | Datenbank (Pflicht) |
| `APP_BASE_URL` | öffentliche URL der Web-App (Links in E-Mails) |
| `ADMIN_BOOTSTRAP_TOKEN` | macht den ersten Signup mit diesem Token zum Plattform-Admin |
| `CORS_ORIGINS`, `TRUSTED_PROXY_HOPS` | Herkunft der Web-App, Anzahl vertrauenswürdiger Proxys (Client-IP für Rate-Limits) |
| `RESEND_API_KEY`, `MAIL_FROM`, `OPERATOR_NAME`, `SUPPORT_EMAIL` | E-Mail-Versand (optional; ohne Key werden Mails nur geloggt) |
| `KALENDER_TOKEN`, `WEB_BASE_URL` | ICS-Speiseplan-Feed (optional) |
| `KI_*` | KI-Anbieter (optional, s. u.) |
| `MCP_ENABLED`, `PUBLIC_URL`, `OAUTH_*` | MCP-Connector mit OAuth 2.1 (Standard: an), öffentliche HTTPS-Adresse, Redirect-/Token-Einstellungen |
| `SENTRY_DSN` | Fehler-Monitoring (optional) |

Frontend-Build-Variablen (`VITE_*`, u. a. Betreiberangaben fürs Impressum) stehen in
[`koch-web/.env.example`](koch-web/.env.example).

### KI mit eigenem Schlüssel

Alle Text- und Bildeingaben laufen über eine **OpenAI-kompatible Chat-Completions-API**.
Das funktioniert mit OpenAI, OpenRouter, LiteLLM, Ollama, vLLM, dem OpenAI-kompatiblen
Endpunkt von Google Gemini und vielen weiteren Anbietern.

| Variable | Bedeutung |
|---|---|
| `KI_BASE_URL` | Basis-URL der API, z. B. `https://api.openai.com/v1` oder `http://ollama:11434/v1` |
| `KI_API_KEY` | Schlüssel (bei lokalen Anbietern leer lassen) |
| `KI_MODEL_DEFAULT` | Standardmodell für Chat, Rezepte, Kochmodus |
| `KI_MODEL_VISION` | Modell für Bildeingaben; leer = Standardmodell, `aus` = keine Foto-Funktionen |
| `KI_MODEL_FLYER` | Modell für den Prospekt-Import (ein Aufruf je Seite); leer = Vision-Modell |
| `KI_IMAGE_MODEL` (+ `KI_IMAGE_BASE_URL`, `KI_IMAGE_API_KEY`, `KI_IMAGE_SIZE`, `KI_IMAGE_STYLE`) | Rezeptbilder über die OpenAI-Images-API (optional) |
| `KI_TRANSCRIBE_MODEL` (+ `KI_TRANSCRIBE_BASE_URL`, `KI_TRANSCRIBE_API_KEY`) | Spracheingabe über `/audio/transcriptions`, z. B. Whisper (optional) |
| `KI_WEBSUCHE_GEMINI_API_KEY`, `KI_WEBSUCHE_MODEL` | experimentelle Online-Angebotssuche über die Gemini-API mit Google-Suche (optional, derzeit ohne Oberfläche) |
| `KI_PERSONENNAMEN` | `1` = Klarnamen der Haushaltsmitglieder an die KI geben (Standard: Pseudonyme) |

Beispiele:

```env
# OpenAI
KI_BASE_URL=https://api.openai.com/v1
KI_API_KEY=sk-...
KI_MODEL_DEFAULT=gpt-4o-mini
KI_IMAGE_MODEL=gpt-image-1
KI_TRANSCRIBE_MODEL=whisper-1

# Ollama im selben Compose-Netz (Vision nur mit multimodalem Modell)
KI_BASE_URL=http://ollama:11434/v1
KI_MODEL_DEFAULT=<lokales Modell>
KI_MODEL_VISION=aus
```

Die Web-App fragt `GET /api/ki/status` ab und zeigt nur die Funktionen, die eingerichtet
sind. Nicht eingerichtete KI-Routen antworten mit HTTP 503 (`ki_nicht_konfiguriert`).
Plattform-Admins können die KI-Nutzung einzelner Nutzer im Admin-Bereich abschalten. Prompts und Bilder gehen an den konfigurierten Anbieter – wähle ihn passend zu
deinen Datenschutzanforderungen.

### Claude und andere MCP-Clients

Unter `https://<deine-instanz>/mcp` läuft ein MCP-Server (Streamable HTTP). Claude bindet ihn
als eigenen Connector ein: In Claude *Customize → Connectors → Add custom connector*, die
URL eintragen, in Topfplan anmelden und zustimmen. Topfplan ist dabei selbst der
OAuth-Server (Dynamic Client Registration, PKCE, Refresh-Rotation, Widerruf); jedes Token
gilt nur für einen Nutzer und dessen Haushalt. Claude Code kann alternativ ein persönliches
Zugriffstoken aus den Einstellungen nutzen.

Voraussetzung: Die Instanz ist per HTTPS aus dem Internet erreichbar, denn die Aufrufe
kommen von Anthropics Servern. Einrichtung, Werkzeugliste, Beispiel-Prompts und Grenzen
(Claude kann Dateien nicht an Werkzeuge übergeben, Fotos und PDFs liest Claude selbst):
[`docs/mcp-connector.md`](docs/mcp-connector.md).

### Datenbank

- `schema.sql`: vollständiges Schema für frische Installationen (Schema `koch`,
  Mandantentrennung per Row-Level-Security).
- `migration_*.sql`: historische, inkrementelle Migrationen für ältere Datenbanken.
  `migration_mcp_oauth.sql` ergänzt die Tabellen für den MCP-Connector.
  `migration_ohne_abrechnung.sql` entfernt Abrechnungsreste aus Datenbanken, die mit dem
  früheren Schema angelegt wurden; frische Installationen brauchen sie nicht.

### Rechtstexte

Impressum, Datenschutzerklärung und Nutzungsbedingungen in
`koch-web/src/components/Rechtliches.jsx` sind **Mustertexte**. Wer die App für andere
betreibt, muss die Betreiberangaben über `VITE_IMPRESSUM_*` setzen und die Texte an den
eigenen Betrieb (Hosting, E-Mail-Versand, KI-Anbieter) anpassen und rechtlich prüfen lassen.

## Architektur

```
koch-web/   React + Vite + Tailwind (SPA/PWA), nginx-Container; optionale Android-Hülle (Capacitor)
app/        Backend: FastAPI + asyncpg
  rest.py        REST-API (/api/...)
  services.py    Kernlogik (Vorrat-Abgleich, Einkaufsliste, Plan, Vorschläge, ...)
  userauth.py    Konten, Login, Haushalte
  ki/            KI-Anbieter-Abstraktion (Text/Vision, Bild, Transkription)
  chat.py, vision.py, guided.py, rezept_link.py, angebote_import.py, ...  KI-Funktionen
  pdf.py         PDF-Rendering und Text (pypdfium2)
  mcp_server.py  MCP-Werkzeuge und -Prompts (Connector für Claude)
  mcp_dienste.py Batch/Vorschau/Idempotenz-Logik der Werkzeuge
  oauth.py       OAuth-2.1-Server, persönliche Zugriffstokens; mcp_auth.py setzt den Haushalt je Aufruf
  schemas.py     Pydantic-Modelle der Werkzeug-Eingaben
brand/      Platzhalter-Icons und deren Generator
tests/      Backend-Tests (laufen ohne Datenbank und ohne Netz)
tests_db/   Integrationstests gegen Postgres (RLS, OAuth-Ablauf, MCP-Werkzeuge)
docs/       Connector-Anleitung
```

## Tests

```bash
pip install -r app/requirements.txt pytest pytest-asyncio
python -m pytest -q tests
# Integrationstests: brauchen ein WEGWERF-Postgres 16 (Schema koch wird neu angelegt)
TEST_DATABASE_URL_ADMIN=postgresql://koch:<pw>@localhost:5432/koch python -m pytest -q tests_db
```

## Persönliche Daten

Das Repository enthält keine personenbezogenen Daten und keine Zugangsdaten. Eigene Werte
gehören in `.env` (wird nicht eingecheckt).

## Lizenz

Topfplan steht unter der **GNU Affero General Public License v3.0** (siehe
[`LICENSE`](LICENSE) und [`NOTICE`](NOTICE)). Wer eine veränderte Fassung als
Netzwerkdienst anbietet, muss den Nutzern den Quellcode dieser Fassung zugänglich machen.
Die mitgelieferte Schrift `brand/fraunces-display.ttf` steht unter der SIL Open Font
License 1.1 ([`brand/OFL.txt`](brand/OFL.txt)).

---

## English

**Topfplan** is a self-hosted kitchen planner for households: pantry, recipes, weekly meal
plan, shopping list and supermarket offers in one web app (PWA) that runs on your own
server. There is no billing, no quota and no telemetry.

- **Quick start:** `cp .env.example .env`, set `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`,
  `DATABASE_URL` (role `koch_app`, not a superuser, so row-level security applies) and
  `ADMIN_BOOTSTRAP_TOKEN`, then `docker compose up -d --build`. Web app on port 8096, API on
  8095. The first sign-up that provides the bootstrap token becomes the platform admin.
- **AI is optional and bring-your-own-key:** set `KI_BASE_URL`, `KI_API_KEY` and
  `KI_MODEL_DEFAULT` for any OpenAI-compatible chat-completions API (OpenAI, OpenRouter,
  LiteLLM, Ollama, vLLM, …). Optional: `KI_MODEL_VISION`, `KI_MODEL_FLYER`,
  `KI_IMAGE_MODEL` (OpenAI images API) and `KI_TRANSCRIBE_MODEL` (Whisper-compatible).
  Without configuration all AI buttons are hidden and everything else keeps working.
- **MCP connector for Claude:** `https://<your-host>/mcp` (Streamable HTTP) with a built-in
  OAuth 2.1 server (dynamic client registration, PKCE S256, refresh-token rotation,
  revocation) and personal access tokens. Add it in Claude as a custom connector; Claude
  does the AI work (reading flyers, photos, recipes) and Topfplan stores structured data
  and computes matching, shopping lists and suggestions. Needs public HTTPS. Claude cannot
  pass uploaded files to tools, so it reads photos/PDFs itself. See
  `docs/mcp-connector.md` (German).
- **Licence:** GNU AGPL-3.0 (see `LICENSE`, `NOTICE`); bundled font under SIL OFL 1.1.
- The UI and most code comments are in German.
