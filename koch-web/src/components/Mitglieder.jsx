import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner, Empty } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { WEB_URL } from '../native.js'

const linkFuer = (token) => `${WEB_URL}/?einladung=${token}`

export default function Mitglieder({ notify }) {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [liste, setListe] = useState(null)
  const [kopiert, setKopiert] = useState(null)

  function lade() {
    return api.einladungen().then(setListe).catch(() => setListe([]))
  }
  useEffect(() => { lade() }, [])

  async function einladen() {
    const e = email.trim()
    if (!e) return
    setBusy(true)
    try {
      const inv = await api.einladungErstellen(e)
      setEmail('')
      await lade()
      // Link zusätzlich anbieten (E-Mail geht automatisch raus)
      kopieren(inv.token)
      notify(inv?.mail_versendet ? 'Einladung per E-Mail gesendet – Link zusätzlich kopiert' : 'Einladung erstellt – Link kopiert')
    } catch (err) {
      notify(err.message || 'Einladen fehlgeschlagen', 'err')
    } finally {
      setBusy(false)
    }
  }

  async function kopieren(token) {
    try {
      await navigator.clipboard.writeText(linkFuer(token))
      setKopiert(token)
      setTimeout(() => setKopiert((t) => (t === token ? null : t)), 2500)
    } catch {
      notify('Konnte nicht kopieren – Link bitte manuell markieren', 'err')
    }
  }

  async function stornieren(id) {
    try { await api.einladungStornieren(id); await lade() }
    catch { notify('Stornieren fehlgeschlagen', 'err') }
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-1 font-display text-xl">Familienmitglieder einladen</h3>
        <p className="mb-3 text-sm text-muted">
          Lade Mitglieder mit eigener E-Mail in euren Haushalt ein – sie bekommen einen eigenen
          Login und teilen Rezepte, Vorrat & Planung. Das Einladen ist <b>kostenlos</b> und die
          Zahl der Mitglieder ändert den Preis nicht: Zugang und Kontingente gelten für den
          ganzen Haushalt, nicht je Person.
        </p>
        <div className="flex gap-2">
          <input
            className={input + ' flex-1'}
            type="email"
            placeholder="email@beispiel.de"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') einladen() }}
          />
          <Button onClick={einladen} disabled={busy || !email.trim()}>
            {busy ? <Spinner /> : 'Einladen'}
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-muted2">
          Die Einladung wird automatisch per E-Mail verschickt. Den Link bekommst du
          zusätzlich (z. B. zum Teilen per WhatsApp) – darüber legt das Mitglied Name +
          Passwort an.
        </p>
      </div>

      <div>
        <h4 className="mb-2 label-mono text-muted2">Offene Einladungen</h4>
        {liste === null ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : liste.length === 0 ? (
          <Empty>Keine offenen Einladungen.</Empty>
        ) : (
          <ul className="space-y-2">
            {liste.map((e) => (
              <li key={e.id} className="rounded-xl border border-line bg-card p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold">{e.email}</span>
                  <button onClick={() => stornieren(e.id)} className="shrink-0 text-sm text-muted2 hover:text-terracotta-deep" title="Einladung zurückziehen"><Icon name="x" size={16} /></button>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <input readOnly value={linkFuer(e.token)} onFocus={(ev) => ev.target.select()} className={input + ' flex-1 text-xs text-muted'} />
                  <Button variant="ghost" onClick={() => kopieren(e.token)}>
                    {kopiert === e.token ? <span className="inline-flex items-center gap-1"><Icon name="check" size={16} /> Kopiert</span> : 'Link kopieren'}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
