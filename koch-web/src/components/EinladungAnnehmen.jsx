import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { Logo } from '../icons.jsx'
import { RechtFooter } from './Rechtliches.jsx'

// Annahme-Seite für einen Einladungs-Link (?einladung=<token>): zeigt den Haushalt,
// lässt das neue Mitglied Name + Passwort setzen und loggt es direkt ein.
export default function EinladungAnnehmen({ token, onAuthed, onAbbruch }) {
  const [info, setInfo] = useState(null)     // null=lädt, false=ungültig, sonst {email,account_name,status}
  const [name, setName] = useState('')
  const [eingabeEmail, setEingabeEmail] = useState('')
  const [passwort, setPasswort] = useState('')
  const [passwort2, setPasswort2] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    api.einladungInfo(token)
      .then((i) => setInfo(i && i.status === 'offen' ? i : false))
      .catch(() => setInfo(false))
  }, [token])

  async function absenden() {
    setFehler('')
    const email = (info && info.email) ? info.email : eingabeEmail.trim()
    if (!info?.email && (!email.includes('@') || !email.includes('.'))) { setFehler('Bitte eine gültige E-Mail angeben.'); return }
    if (passwort.length < 8) { setFehler('Passwort: mindestens 8 Zeichen.'); return }
    if (passwort !== passwort2) { setFehler('Die Passwörter stimmen nicht überein.'); return }
    setBusy(true)
    try {
      const res = await api.einladungEinloesen(token, name.trim(), passwort, email)
      api.setToken(res.token)
      try { localStorage.setItem('onboarding_pending', '1') } catch { /* ignore */ }
      onAuthed(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Beitritt fehlgeschlagen')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-3xl border border-line bg-card p-6 shadow-soft">
        <div className="mb-4 flex justify-center">
          <Logo variant="full" className="rise w-full max-w-[300px]" />
        </div>
        <p className="label-mono tracking-[0.25em] text-terracotta">Einladung</p>

        {info === null ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : info === false ? (
          <div className="space-y-4">
            <p className="text-sm text-muted">Dieser Einladungs-Link ist ungültig oder wurde bereits eingelöst.</p>
            <Button onClick={onAbbruch} className="w-full">Zur Anmeldung</Button>
          </div>
        ) : (
          <>
            <p className="mb-5 text-sm text-muted">
              Du wurdest in den Haushalt <b className="text-ink">{info.account_name || 'Haushalt'}</b> eingeladen.
              Lege dein Passwort fest, um beizutreten.
            </p>
            <div className="space-y-3">
              {info.email ? (
                <input className={input + ' bg-paper/60 text-muted'} value={info.email} readOnly />
              ) : (
                <input className={input} type="email" autoComplete="email" placeholder="Deine E-Mail"
                  value={eingabeEmail} onChange={(e) => setEingabeEmail(e.target.value)} />
              )}
              <input className={input} placeholder="Dein Name, z.B. Max Mustermann" value={name} onChange={(e) => setName(e.target.value)} />
              <input
                className={input}
                type="password"
                autoComplete="new-password"
                placeholder="Passwort (min. 8 Zeichen)"
                value={passwort}
                onChange={(e) => setPasswort(e.target.value)}
              />
              <input
                className={input}
                type="password"
                autoComplete="new-password"
                placeholder="Passwort wiederholen"
                value={passwort2}
                onChange={(e) => setPasswort2(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') absenden() }}
              />
              {fehler && <p className="text-sm font-semibold text-terracotta-deep">{fehler}</p>}
              <Button onClick={absenden} disabled={busy} className="w-full">
                {busy ? <Spinner /> : 'Beitreten & loslegen'}
              </Button>
            </div>
            <p className="mt-4 text-center text-sm text-muted">
              <button onClick={onAbbruch} className="font-semibold text-terracotta hover:underline">Stattdessen anmelden</button>
            </p>
          </>
        )}
        <RechtFooter className="mt-5 border-t border-line pt-4" />
      </div>
    </div>
  )
}
