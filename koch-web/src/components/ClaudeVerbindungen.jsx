import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Button, input, confirmDialog } from '../ui.jsx'
import { Icon } from '../icons.jsx'

// Einstellungen → Claude & MCP: MCP-Adresse, verbundene Apps (OAuth) und persönliche
// Zugriffstokens für Clients, die einen festen Header nutzen (Claude Code, Desktop-Konfig).
export default function ClaudeVerbindungen({ notify }) {
  const [daten, setDaten] = useState(null)
  const [aus, setAus] = useState(false)
  const [name, setName] = useState('Claude Code')
  const [nurLesen, setNurLesen] = useState(false)
  const [neu, setNeu] = useState(null)

  function laden() {
    api.verbindungen().then(setDaten).catch((e) => { if (e?.status === 404) setAus(true) })
  }
  useEffect(laden, [])

  if (aus) return null
  if (!daten) return null

  async function widerrufenApp(app) {
    if (!(await confirmDialog({ title: 'Verbindung trennen', message: `${app.client_name} verliert den Zugriff.`, confirmLabel: 'Trennen' }))) return
    try { await api.verbindungWiderrufen(app.id); notify('Verbindung getrennt'); laden() } catch (e) { notify(e.message, 'err') }
  }
  async function widerrufenToken(t) {
    if (!(await confirmDialog({ title: 'Token widerrufen', message: `„${t.name}“ funktioniert danach nicht mehr.`, confirmLabel: 'Widerrufen' }))) return
    try { await api.tokenWiderrufen(t.id); notify('Token widerrufen'); laden() } catch (e) { notify(e.message, 'err') }
  }
  async function erstellen() {
    try {
      const t = await api.tokenErstellen(name.trim() || 'Zugriffstoken', nurLesen ? ['read'] : ['read', 'write'])
      setNeu(t); laden()
    } catch (e) { notify(e.message, 'err') }
  }
  async function kopieren(text) {
    try { await navigator.clipboard.writeText(text); notify('Kopiert') } catch { notify('Bitte manuell kopieren', 'err') }
  }

  const fmt = (iso) => (iso ? new Date(iso).toLocaleDateString('de-DE') : '–')

  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <p className="inline-flex items-center gap-1 text-sm font-semibold"><Icon name="bot" size={18} /> Claude &amp; MCP</p>
      <p className="text-sm text-ink/60">
        In Claude unter „Connectors → Eigenen Connector hinzufügen“ diese Adresse eintragen. Claude übernimmt die
        KI-Arbeit, Küchenplaner speichert die Ergebnisse.
      </p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-lg bg-ink/5 px-2 py-1.5 text-xs">{daten.mcp_url}</code>
        <button onClick={() => kopieren(daten.mcp_url)} className="shrink-0 rounded-lg border border-line px-2 py-1 text-xs font-semibold">Kopieren</button>
      </div>

      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-ink/40">Verbundene Apps</p>
        {daten.apps.length === 0 && <p className="text-sm text-ink/50">Noch keine.</p>}
        {daten.apps.map((a) => (
          <div key={a.id} className="mt-1 flex items-center justify-between gap-2 text-sm">
            <span className="min-w-0">
              <span className="font-semibold">{a.client_name}</span>
              <span className="block text-xs text-ink/50">{a.scopes.includes('write') ? 'Lesen + Schreiben' : 'Nur lesen'} · seit {fmt(a.erstellt)} · zuletzt {fmt(a.zuletzt_genutzt)}</span>
            </span>
            <button onClick={() => widerrufenApp(a)} className="shrink-0 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-terracotta-deep">Trennen</button>
          </div>
        ))}
      </div>

      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-ink/40">Persönliche Zugriffstokens</p>
        {daten.tokens.map((t) => (
          <div key={t.id} className="mt-1 flex items-center justify-between gap-2 text-sm">
            <span className="min-w-0">
              <span className="font-semibold">{t.name}</span>
              <span className="block text-xs text-ink/50">{t.anzeige} · {t.scopes.includes('write') ? 'Lesen + Schreiben' : 'Nur lesen'} · zuletzt {fmt(t.zuletzt_genutzt)}</span>
            </span>
            <button onClick={() => widerrufenToken(t)} className="shrink-0 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-terracotta-deep">Widerrufen</button>
          </div>
        ))}
        {neu ? (
          <div className="mt-2 space-y-2 rounded-lg bg-ink/5 p-2 text-sm">
            <p className="font-semibold">Token „{neu.name}“ – wird nur jetzt angezeigt:</p>
            <code className="block break-all text-xs">{neu.token}</code>
            <p className="text-xs text-ink/60">Claude Code: <code className="break-all">claude mcp add --transport http kuechenplaner {daten.mcp_url} --header "Authorization: Bearer {neu.token}"</code></p>
            <div className="flex gap-2">
              <Button onClick={() => kopieren(neu.token)}>Token kopieren</Button>
              <Button variant="ghost" onClick={() => setNeu(null)}>Fertig</Button>
            </div>
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input className={input + ' min-w-0 flex-1'} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} aria-label="Name des Tokens" />
            <label className="inline-flex items-center gap-1 text-xs"><input type="checkbox" checked={nurLesen} onChange={(e) => setNurLesen(e.target.checked)} /> nur lesen</label>
            <Button onClick={erstellen}>Token erstellen</Button>
          </div>
        )}
      </div>
    </div>
  )
}
