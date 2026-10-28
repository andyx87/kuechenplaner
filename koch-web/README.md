# Küchenplaner – Web-App

React + Vite + Tailwind, selbst gehostete Fonts (kein externes CDN). Die App spricht
relativ mit `/api/...`; im Betrieb liegt sie hinter demselben nginx wie die API (kein CORS),
in der Entwicklung proxyt der Vite-Devserver auf `:8093`.

## Entwicklung

```bash
npm install
npm run dev          # http://localhost:5173, proxyt /api -> localhost:8093
```

Läuft die API auf einem anderen Origin, `VITE_API_BASE` setzen (siehe `.env.example`) und
den API-Host in `nginx.conf` unter `connect-src` ergänzen.

## Betrieb

Der `Dockerfile` baut die App und serviert sie per nginx; `nginx.conf` proxyt `/api` und
`/mcp` an den Backend-Container `koch-mcp`. Frontend und Backend laufen deshalb in derselben
Compose (siehe `docker-compose.yml` im Wurzelverzeichnis).

## Android

`android/` enthält die Capacitor-Hülle (`npx cap sync android`, danach mit Gradle bauen).
App-ID und Name stehen in `capacitor.config.json`.

## Hinweise

- Foto-Erkennung ist zweistufig: Vorschlag → Korrektur → Übernahme. Nichts wird ungeprüft gespeichert.
- Beim Kochen meldet die App zurück, falls eine Zutat im Vorrat nicht ausgereicht hat.
- Mobile-first, funktioniert aber auch am Desktop.
