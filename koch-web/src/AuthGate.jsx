import { useEffect, useState } from 'react'
import { api } from './api.js'
import App from './App.jsx'
import Login from './components/Login.jsx'
import EinladungAnnehmen from './components/EinladungAnnehmen.jsx'
import KontoLoeschen from './components/KontoLoeschen.jsx'
import Verbinden from './components/Verbinden.jsx'
import { PasswortReset, EmailVerify } from './components/AuthAktionen.jsx'
import { RechtSeite } from './components/Rechtliches.jsx'
import { Spinner, Button } from './ui.jsx'

// Entscheidet: lädt -> Spinner, Einladung/Reset/Verify-Link -> jeweilige Seite,
// nicht angemeldet -> Login, Server nicht erreichbar -> Wiederholen, sonst -> App.

// Öffentliche Kontolösch-Seite: /konto-loeschen (Anfrage) bzw. mit #loesch=<token>
// (Bestätigungslink aus der Mail). Ohne Anmeldung erreichbar, zusätzlich zum In-App-Weg.
function istKontoLoeschenPfad() {
  return /^\/konto-loeschen\/?$/.test(window.location.pathname)
}

// S3 (Sicherheitsprüfung AND-24): Das Lösch-Token reist im URL-Fragment – Fragmente
// gehen nicht an den Server (keine Zugriffslogs, kein Referer-Leak). Ältere Links mit
// ?loesch= (Query) werden während der Übergangszeit weiter erkannt; der Query-Weg wird
// serverseitig nicht mehr erzeugt.
function loeschTokenAusUrl() {
  const m = window.location.hash.match(/[#&]loesch=([^&#]+)/)
  if (m) return decodeURIComponent(m[1])
  return new URLSearchParams(window.location.search).get('loesch')
}

// Öffentliche Rechtstext-Seiten als echte Pfade: /datenschutz, /impressum, /agb
// (z. B. als feste Datenschutz-URL). nginx liefert für jeden Pfad die
// index.html, die Zuordnung passiert hier. Der Query-Weg ?recht=… bleibt gültig
// (Bestandslinks in Mails); steht beides da, gewinnt der Query-Parameter.
function rechtDocAusPfad() {
  const m = window.location.pathname.match(/^\/(datenschutz|impressum|agb)\/?$/)
  return m ? m[1] : null
}

// OAuth-Zustimmung (Claude-Connector & Co.): /verbinden?anfrage=… – der Server leitet
// /authorize hierher. Nicht angemeldet → erst Login, danach zurück zur Zustimmung.
function verbindenAnfrage() {
  if (!/^\/verbinden\/?$/.test(window.location.pathname)) return null
  return new URLSearchParams(window.location.search).get('anfrage')
}

export default function AuthGate() {
  const params = new URLSearchParams(window.location.search)
  const rechtPfad = rechtDocAusPfad()
  const rechtDoc = params.get('recht') || rechtPfad
  const einladungToken = params.get('einladung')
  const resetToken = params.get('reset')
  const verifyToken = params.get('verify')
  const kontoLoeschen = istKontoLoeschenPfad()
  const loeschToken = kontoLoeschen ? loeschTokenAusUrl() : null
  const start = kontoLoeschen ? 'konto-loeschen'
    : rechtDoc ? 'recht' : einladungToken ? 'einladung' : resetToken ? 'reset' : verifyToken ? 'verify' : 'laedt'
  const [zustand, setZustand] = useState(start)  // 'laedt'|'recht'|'einladung'|'reset'|'verify'|'konto-loeschen'|'login'|'app'
  const [auth, setAuth] = useState(null)
  const anfrage = verbindenAnfrage()

  const linkFlow = kontoLoeschen || rechtDoc || einladungToken || resetToken || verifyToken
  const zurPathname = () => { window.location.href = window.location.pathname }
  const zurStartseite = () => { window.location.href = '/' }

  useEffect(() => {
    if (linkFlow) return  // Öffentliche/Link-Flows (Recht/Einladung/Reset/Verify) haben Vorrang
    if (!api.getToken()) { setZustand('login'); return }
    pruefeSitzung()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // S3 (Sicherheitsprüfung AND-24): Lösch-Token sofort nach dem Lesen aus der Adresszeile
  // entfernen – nicht in Browser-Historie, Screen-Shares oder geteilten Geräten stehen
  // lassen. Das Fragment erreicht den Server ohnehin nie (kein Zugriffslog-Eintrag).
  useEffect(() => {
    if (kontoLoeschen && loeschToken) window.history.replaceState(null, '', '/konto-loeschen')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Nur ein echtes 401 meldet ab. Netzwerkfehler/Kaltstart/5xx behalten das Token und
  // zeigen einen Wiederholen-Bildschirm, statt den Nutzer kommentarlos auszuloggen.
  function pruefeSitzung() {
    setZustand('laedt')
    api.authMe()
      .then((me) => { setAuth(me); setZustand('app') })
      .catch((e) => {
        if (e?.status === 401) { api.setToken(null); setZustand('login') } else setZustand('offline')
      })
  }

  function nachAuth(me) {
    window.history.replaceState({}, '', window.location.pathname)  // ?einladung entfernen
    setAuth(me)
    setZustand('app')
  }

  async function logout() {
    try { await api.authLogout() } catch { /* ignore */ }
    api.setToken(null)
    setAuth(null)
    setZustand('login')
  }

  if (zustand === 'konto-loeschen') return <KontoLoeschen token={loeschToken} onClose={zurStartseite} />
  // Rechtstext per Pfad (/datenschutz …): „Schließen" geht zur Startseite, sonst würde
  // dieselbe Adresse neu geladen. Per Query (?recht=…): nur den Query entfernen.
  if (zustand === 'recht') return <RechtSeite doc={rechtDoc} onClose={rechtPfad ? zurStartseite : zurPathname} />
  if (zustand === 'einladung') return (
    <EinladungAnnehmen
      token={einladungToken}
      onAuthed={nachAuth}
      onAbbruch={zurPathname}
    />
  )
  if (zustand === 'reset') return <PasswortReset token={resetToken} onFertig={zurPathname} />
  if (zustand === 'verify') return <EmailVerify token={verifyToken} onFertig={zurPathname} />
  if (zustand === 'laedt') return <div className="flex min-h-screen items-center justify-center"><Spinner /></div>
  if (zustand === 'offline') return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="font-display text-2xl">Keine Verbindung</p>
      <p className="max-w-xs text-sm text-muted">Topfplan ist gerade nicht erreichbar. Prüfe deine Internetverbindung und versuch es noch einmal.</p>
      <Button onClick={pruefeSitzung}>Erneut versuchen</Button>
    </div>
  )
  if (anfrage && zustand === 'app') return <Verbinden anfrage={anfrage} auth={auth} onFertig={zurStartseite} />
  if (zustand === 'login') return (
    <Login onAuthed={(me) => { setAuth(me); setZustand('app') }} />
  )
  return <App auth={auth} onLogout={logout} />
}
