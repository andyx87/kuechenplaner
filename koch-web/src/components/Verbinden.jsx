import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Button, Spinner } from '../ui.jsx'
import { Icon } from '../icons.jsx'

// Zustimmungsseite für OAuth-Clients (z. B. den Claude-Connector). Der Server leitet
// /authorize hierher um (?anfrage=…); der Nutzer ist mit seiner normalen Sitzung angemeldet.
export default function Verbinden({ anfrage, auth, onFertig }) {
  const [info, setInfo] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [schreiben, setSchreiben] = useState(true)
  const [laeuft, setLaeuft] = useState(false)

  useEffect(() => {
    api.oauthAnfrage(anfrage)
      .then((d) => { setInfo(d); setSchreiben(d.scopes.some((s) => s.scope === 'write')) })
      .catch((e) => setFehler(e?.body?.detail || e.message || 'Anfrage nicht gefunden.'))
  }, [anfrage])

  async function entscheiden(ja) {
    setLaeuft(true)
    try {
      const scopes = schreiben ? ['read', 'write'] : ['read']
      const res = await api.oauthEntscheiden(anfrage, ja, scopes)
      window.location.href = res.redirect_url
    } catch (e) {
      setFehler(e?.body?.detail || e.message || 'Fehler')
      setLaeuft(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md space-y-5 rounded-[22px] border border-line bg-card p-6 shadow-soft">
        <p className="inline-flex items-center gap-2 font-display text-2xl"><Icon name="link" size={22} /> App verbinden</p>
        {fehler && (
          <div className="space-y-3">
            <p className="text-sm text-terracotta-deep">{fehler}</p>
            <Button variant="ghost" onClick={onFertig}>Zur App</Button>
          </div>
        )}
        {!fehler && !info && <Spinner />}
        {!fehler && info && (
          <>
            <p className="text-sm text-ink/80">
              <strong>{info.client_name}</strong> möchte auf deinen Haushalt <strong>{info.haushalt || 'Haushalt'}</strong> zugreifen
              {auth?.user?.email ? <> (angemeldet als {auth.user.email})</> : null}.
            </p>
            <div className="rounded-xl border border-line p-3 text-sm">
              <p className="text-ink/60">Antwort geht an</p>
              <p className="font-semibold break-all">{info.redirect_host}</p>
              {info.nur_loopback && (
                <p className="mt-2 text-terracotta-deep">
                  Achtung: Das ist eine Adresse auf diesem Gerät. Nur zustimmen, wenn du gerade selbst ein
                  Programm wie Claude Code verbindest.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked disabled className="mt-1" />
                <span>{info.scopes.find((s) => s.scope === 'read')?.text || 'Lesen'}</span>
              </label>
              {info.scopes.some((s) => s.scope === 'write') && (
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" checked={schreiben} onChange={(e) => setSchreiben(e.target.checked)} className="mt-1" />
                  <span>{info.scopes.find((s) => s.scope === 'write')?.text}</span>
                </label>
              )}
            </div>
            <p className="text-xs text-ink/50">Du kannst den Zugriff jederzeit unter Einstellungen → Claude &amp; MCP widerrufen.</p>
            <div className="flex gap-2">
              <Button onClick={() => entscheiden(true)} disabled={laeuft}>Zulassen</Button>
              <Button variant="ghost" onClick={() => entscheiden(false)} disabled={laeuft}>Ablehnen</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
