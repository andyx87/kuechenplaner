import { useState } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { Icon } from '../icons.jsx'

// Öffentliche Kontolösch-Seite – erreichbar über /konto-loeschen, bewusst OHNE Anmeldung
// (zusätzlich zum In-App-Weg „Mehr → Konto löschen"; DSGVO Art. 17).
//
// Zweistufig: Dieses Formular mailt nur einen Bestätigungslink (POST
// /auth/konto-loeschen-anfordern). Gelöscht wird erst, wenn der Link aus dem Postfach
// mit #loesch=<token> geöffnet UND hier erneut bestätigt wird – nie allein auf Basis
// der eingegebenen E-Mail und nie automatisch beim Laden des Links (damit z. B.
// Mail-Scanner keine Löschung auslösen).
export default function KontoLoeschen({ token, onClose }) {
  return token ? <Bestaetigen token={token} onClose={onClose} /> : <Anfordern onClose={onClose} />
}

// Stufe 1: E-Mail-Formular → Bestätigungslink anfordern.
function Anfordern({ onClose }) {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [quittung, setQuittung] = useState(null)

  async function anfordern() {
    setFehler('')
    if (!email.trim()) { setFehler('Bitte die E-Mail-Adresse deines Topfplan-Kontos angeben.'); return }
    setBusy(true)
    try {
      const res = await api.kontoLoeschenAnfordern(email.trim())
      setQuittung(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Senden fehlgeschlagen')
    } finally { setBusy(false) }
  }

  // Neutrale Quittung – verrät bewusst nicht, ob zu der E-Mail ein Konto existiert.
  if (quittung) {
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
        <div className="rounded-2xl border border-olive/40 bg-olive/10 p-6">
          <p className="flex items-center gap-2 font-display text-xl text-olive">
            <Icon name="circle-check" size={20} /> Anfrage ist raus
          </p>
          <p className="mt-4 text-sm text-ink/80">{quittung.hinweis}</p>
        </div>
        <button onClick={onClose} className="mt-6 text-sm text-muted2 hover:text-ink hover:underline">
          Zurück zu Topfplan
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
      <h1 className="font-dish text-4xl leading-tight text-ink">Konto löschen</h1>
      <p className="mt-3 text-sm text-muted">
        Hier löschst du dein Topfplan-Konto dauerhaft – ohne Anmeldung. Aus Sicherheitsgründen
        löschen wir nie allein auf Basis dieser Eingabe: Du bekommst zuerst einen
        Bestätigungslink per E-Mail, erst dein Klick darauf führt die Löschung aus.
      </p>

      <div className="mt-6 grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-xl border border-line p-4">
          <p className="label-mono mb-2 text-terracotta">Was gelöscht wird</p>
          <ul className="list-inside list-disc space-y-1 text-muted">
            <li>Dein Login</li>
            <li>Rezepte, Pläne, Vorräte</li>
            <li>Persönliche Angaben</li>
          </ul>
          <p className="mt-2 text-xs text-muted2">
            Bist du der letzte Nutzer deines Haushalts, wird der komplette Haushalt entfernt.
            Das kann nicht rückgängig gemacht werden.
          </p>
        </div>
        <div className="rounded-xl border border-line p-4">
          <p className="label-mono mb-2 text-olive">Was bleibt</p>
          <ul className="list-inside list-disc space-y-1 text-muted">
            <li>Nur Daten, deren Aufbewahrung gesetzlich vorgeschrieben ist (falls zutreffend)</li>
          </ul>
        </div>
      </div>

      <p className="mt-4 text-sm text-muted">
        In der App geht es auch direkt über <span className="font-semibold text-ink">Mehr → Konto löschen</span>.
      </p>

      <div className="mt-8 space-y-4">
        <label className="block">
          <span className="label-mono mb-2 block text-muted2">E-Mail deines Topfplan-Kontos *</span>
          <input className={input} type="email" autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="du@beispiel.de"
            onKeyDown={(e) => { if (e.key === 'Enter') anfordern() }} />
        </label>

        {fehler && <p className="rounded-xl border border-terracotta/40 bg-terracotta/10 px-3 py-2 text-sm text-terracotta-deep">{fehler}</p>}

        <Button onClick={anfordern} disabled={busy} className="w-full py-3.5 text-base">
          {busy ? <Spinner /> : 'Bestätigungslink anfordern'}
        </Button>

        <button onClick={onClose} className="w-full py-1 text-sm text-muted2 hover:text-ink hover:underline">
          Abbrechen
        </button>
      </div>
    </div>
  )
}

// Stufe 2: Bestätigungslink aus der Mail (#loesch=<token>) → endgültige Löschung,
// aber erst nach ausdrücklichem Klick (kein Auto-Submit beim Laden).
function Bestaetigen({ token, onClose }) {
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [quittung, setQuittung] = useState(null)

  async function loeschen() {
    setFehler('')
    setBusy(true)
    try {
      const res = await api.kontoLoeschenBestaetigen(token)
      setQuittung(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Löschen fehlgeschlagen')
    } finally { setBusy(false) }
  }

  if (quittung) {
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
        <div className="rounded-2xl border border-olive/40 bg-olive/10 p-6">
          <p className="flex items-center gap-2 font-display text-xl text-olive">
            <Icon name="circle-check" size={20} /> Konto gelöscht
          </p>
          <p className="mt-4 text-sm text-ink/80">{quittung.hinweis}</p>
        </div>
        <button onClick={onClose} className="mt-6 text-sm text-muted2 hover:text-ink hover:underline">
          Zurück zu Topfplan
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
      <h1 className="font-dish text-4xl leading-tight text-ink">Kontolöschung bestätigen</h1>
      <p className="mt-3 text-sm text-muted">
        Du hast angefordert, dein Topfplan-Konto dauerhaft zu löschen. Dieser Schritt ist
        endgültig: Dein Login, deine Rezepte, Pläne, Vorräte und persönlichen Daten werden
        entfernt. Bist du der letzte Nutzer deines Haushalts, wird der komplette Haushalt
        gelöscht. Erhalten bleiben nur Daten mit gesetzlicher Aufbewahrungspflicht (falls zutreffend).
      </p>

      <div className="mt-8 space-y-4">
        {fehler && <p className="rounded-xl border border-terracotta/40 bg-terracotta/10 px-3 py-2 text-sm text-terracotta-deep">{fehler}</p>}

        <Button onClick={loeschen} disabled={busy} className="w-full py-3.5 text-base">
          {busy ? <Spinner /> : 'Konto endgültig löschen'}
        </Button>

        <button onClick={onClose} className="w-full py-1 text-sm text-muted2 hover:text-ink hover:underline">
          Abbrechen – Konto behalten
        </button>
      </div>
    </div>
  )
}
