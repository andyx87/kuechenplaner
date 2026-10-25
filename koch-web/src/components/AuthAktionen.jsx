import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { LogoMark } from '../icons.jsx'

// Gemeinsamer, zentrierter Rahmen (mobil-gestapelt wie die Login-Seite).
function Rahmen({ children }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 py-10">
      <div className="mb-8 flex flex-col items-center text-center">
        <LogoMark size={88} />
        <div className="topfplan-wortmarke mt-5 text-3xl">Topfplan</div>
        <div className="label-mono mt-1.5 text-terracotta">Genuss mit Verstand</div>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  )
}

// Seite für ?reset=<token> – neues Passwort vergeben.
export function PasswortReset({ token, onFertig }) {
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [fertig, setFertig] = useState(false)

  async function absenden() {
    setFehler('')
    if (pw.length < 8) { setFehler('Passwort: mindestens 8 Zeichen.'); return }
    if (pw !== pw2) { setFehler('Die Passwörter stimmen nicht überein.'); return }
    setBusy(true)
    try {
      await api.passwortReset(token, pw)
      setFertig(true)
    } catch (e) {
      setFehler(String(e.message || e) || 'Fehlgeschlagen')
    } finally {
      setBusy(false)
    }
  }

  if (fertig) {
    return (
      <Rahmen>
        <h2 className="font-dish text-3xl leading-tight text-ink">Passwort geändert.</h2>
        <p className="mt-2 text-sm text-muted">Du kannst dich jetzt mit deinem neuen Passwort anmelden.</p>
        <Button className="mt-6 w-full py-4 text-base" onClick={onFertig}>Zur Anmeldung</Button>
      </Rahmen>
    )
  }

  return (
    <Rahmen>
      <h2 className="font-dish text-3xl leading-tight text-ink">Neues Passwort wählen</h2>
      <p className="mt-2 text-sm text-muted">Vergib ein neues Passwort für dein Topfplan-Konto.</p>
      <div className="mt-6 space-y-4">
        <label className="block">
          <span className="label-mono mb-2 block text-muted2">Neues Passwort</span>
          <input className={input} type="password" autoComplete="new-password" placeholder="••••••••" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="block">
          <span className="label-mono mb-2 block text-muted2">Passwort wiederholen</span>
          <input className={input} type="password" autoComplete="new-password" placeholder="••••••••" value={pw2} onChange={(e) => setPw2(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') absenden() }} />
        </label>
        {fehler && <p className="text-sm font-semibold text-terracotta">{fehler}</p>}
        <Button onClick={absenden} disabled={busy} className="w-full py-4 text-base">
          {busy ? <Spinner /> : 'Passwort speichern'}
        </Button>
        <button onClick={onFertig} className="block w-full text-center text-sm text-muted hover:text-ink">Zurück zur Anmeldung</button>
      </div>
    </Rahmen>
  )
}

// Seite für ?verify=<token> – E-Mail-Adresse bestätigen (prüft beim Laden).
export function EmailVerify({ token, onFertig }) {
  const [status, setStatus] = useState('pruefe')  // 'pruefe' | 'ok' | 'fehler'
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    api.emailVerifizieren(token)
      .then(() => setStatus('ok'))
      .catch((e) => { setFehler(String(e.message || e)); setStatus('fehler') })
  }, [token])

  return (
    <Rahmen>
      {status === 'pruefe' && (
        <div className="flex flex-col items-center gap-3 text-center">
          <Spinner />
          <p className="text-sm text-muted">E-Mail wird bestätigt …</p>
        </div>
      )}
      {status === 'ok' && (
        <div className="text-center">
          <h2 className="font-dish text-3xl leading-tight text-ink">E-Mail bestätigt ✓</h2>
          <p className="mt-2 text-sm text-muted">Danke! Deine E-Mail-Adresse ist jetzt bestätigt.</p>
          <Button className="mt-6 w-full py-4 text-base" onClick={onFertig}>Weiter zu Topfplan</Button>
        </div>
      )}
      {status === 'fehler' && (
        <div className="text-center">
          <h2 className="font-dish text-3xl leading-tight text-ink">Bestätigung fehlgeschlagen</h2>
          <p className="mt-2 text-sm text-muted">{fehler || 'Der Link ist ungültig oder abgelaufen.'}</p>
          <Button className="mt-6 w-full py-4 text-base" onClick={onFertig}>Weiter</Button>
        </div>
      )}
    </Rahmen>
  )
}
