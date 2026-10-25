# Sapio – KI-Küchenassistent

Sapio ist eine Web-App (PWA, optional als Android-App über Capacitor) für die Küche im
Haushalt:

- **Vorrat** verwalten – manuell oder per Foto (KI schlägt Positionen vor, du prüfst sie)
- **Rezepte** suchen, anlegen, aus dem Vorrat vorschlagen lassen, geführter Kochmodus
- **Wochenplanung** mit Personen, Abwesenheiten und Vorlieben/Allergien, Einkaufsliste,
  Speiseplan als ICS-Kalenderfeed
- **Angebote** aus Supermarkt-Prospekten (PDF/Fotos) erfassen und in der Planung bevorzugen
- **Chat-Assistent** für Fragen rund ums Kochen
- Mehrere Haushalte (Mandanten) mit Mitgliedern, optionale Abrechnung über Stripe

Code und Kommentare sind überwiegend auf Deutsch.

## Architektur

```
koch-web/   React + Vite + Tailwind (SPA/PWA), nginx-Container; Android-Hülle via Capacitor
app/        Backend: FastAPI + asyncpg
  rest.py        REST-API (/api/...) für die Web-App
  mcp_server.py  optionaler MCP-Endpunkt (/mcp) für KI-Clients, standardmäßig AUS
  services.py    Kernlogik (von REST und MCP gemeinsam genutzt)
  billing.py     Kontingente/Abrechnung, stripe_pay.py Stripe-Anbindung
  userauth.py    Konten, Login, Haushalte
  chat.py, vision.py, bilder.py, ...  KI-Funktionen (Google Vertex AI / Gemini)
schema.sql  vollständiges Postgres-Schema (Schema `koch`, Mandantentrennung per RLS)
migration_*.sql  inkrementelle Migrationen für bestehende Datenbanken
tests/      Backend-Tests (laufen ohne Datenbank)
```

Die Web-App spricht relativ mit `/api/...`; im Compose-Betrieb proxyt der nginx des
Frontends `/api` und `/mcp` an den Backend-Container.

## Lokal starten (docker compose)

Voraussetzung: Docker mit Compose-Plugin.

```bash
cp .env.example .env
# In .env mindestens POSTGRES_PASSWORD setzen und DATABASE_URL passend anpassen.
# Für KI-Funktionen zusätzlich GCP_PROJECT (und Google-Zugangsdaten, s. u.).
docker compose up -d --build
```

- Web-App: http://localhost:8096
- API: http://localhost:8095 (Health-Check `/health`, interaktive Doku `/docs`)

Die Compose-Datei startet eine eigene Postgres-Instanz; `schema.sql` wird beim ersten Start
(leeres Volume) automatisch eingespielt. `docker compose down -v` setzt die Datenbank zurück.

Frontend-Entwicklung ohne Docker:

```bash
cd koch-web
npm install
npm run dev   # http://localhost:5173, proxyt /api -> localhost:8093
```

## Konfiguration

Das Backend wird ausschließlich über Umgebungsvariablen konfiguriert; alle Variablen mit
Erläuterung stehen in [`.env.example`](.env.example) bzw. `app/config.py`. Wichtig:

| Variable | Zweck |
|---|---|
| `POSTGRES_PASSWORD`, `DATABASE_URL` | Datenbank (Pflicht) |
| `APP_BASE_URL` | öffentliche URL der Web-App (Links in Mails, Zahlungs-Redirects) |
| `GCP_PROJECT`, `VERTEX_LOCATION` | Google Vertex AI für alle KI-Funktionen (kein Default) |
| `ADMIN_BOOTSTRAP_TOKEN` | macht den ersten Signup mit diesem Token zum Plattform-Admin |
| `RESEND_API_KEY`, `MAIL_FROM` | E-Mail-Versand (optional; ohne Key wird nur geloggt) |
| `STRIPE_*` | Zahlungen (optional; ohne Keys sind Checkouts deaktiviert) |
| `MCP_ENABLED` | MCP-Endpunkt einschalten – nur in vertrauenswürdigen Netzen |

Die KI-Aufrufe authentifizieren sich über Google Application Default Credentials
(Service-Account oder lokal `gcloud auth application-default login`).

Frontend-Build-Variablen (`VITE_*`) stehen in [`koch-web/.env.example`](koch-web/.env.example).

### Rechtstexte

Impressum, Datenschutzerklärung und Nutzungsbedingungen in
`koch-web/src/components/Rechtliches.jsx` sind Vorlagen. Wer die App öffentlich betreibt,
muss die Betreiberangaben über `VITE_IMPRESSUM_*` setzen und die Texte rechtlich prüfen und
an den eigenen Betrieb (Hosting, Dienstleister, Preise, Umsatzsteuer) anpassen.

## Tests

```bash
pip install -r app/requirements.txt pytest pytest-asyncio
python -m pytest -q tests
```
