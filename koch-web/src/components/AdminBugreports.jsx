import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'

// Backoffice: Bugreports ansehen und auf erledigt setzen.
export default function AdminBugreports({ notify }) {
  const [list, setList] = useState(null)
  const [nurOffen, setNurOffen] = useState(true)
  const [busy, setBusy] = useState(null)
  const [auf, setAuf] = useState(false)

  function lade() {
    return api.adminBugreports(nurOffen).then(setList).catch(() => notify('Bugreports laden fehlgeschlagen', 'err'))
  }
  useEffect(() => { if (auf) lade() }, [auf, nurOffen])  // eslint-disable-line react-hooks/exhaustive-deps

  async function setStatus(b, status) {
    setBusy(b.id)
    try {
      await api.adminBugreportStatus(b.id, status)
      await lade()
    } catch { notify('Speichern fehlgeschlagen', 'err') } finally { setBusy(null) }
  }

  const datum = (s) => new Date(s).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  const offenN = (list || []).filter((b) => b.status === 'offen').length

  return (
    <div className="rounded-xl border border-terracotta/40 bg-terracotta/5 p-3">
      <button onClick={() => setAuf((v) => !v)} className="flex w-full items-center justify-between text-sm font-semibold">
        <span className="inline-flex items-center gap-1"><Icon name="bug" size={16} /> Bugreports{list ? ` (${offenN} offen)` : ''}</span>
        <span className="text-muted2">{auf ? '▲' : '▼'}</span>
      </button>

      {auf && (
        <div className="mt-2 space-y-2">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={nurOffen} onChange={() => setNurOffen((v) => !v)} className="h-3.5 w-3.5 accent-terracotta" />
            nur offene
          </label>

          {!list ? (
            <p className="py-2 text-center text-xs text-muted2">lädt …</p>
          ) : list.length === 0 ? (
            <p className="flex items-center justify-center gap-1 py-2 text-center text-xs text-muted2">Keine Meldungen <Icon name="party-popper" size={14} /></p>
          ) : (
            <ul className="space-y-2">
              {list.map((b) => (
                <li key={b.id} className={`rounded-lg border p-2.5 text-sm ${b.status === 'erledigt' ? 'border-line/50 bg-card/40 opacity-60' : 'border-line/60 bg-card/60'}`}>
                  <p className="whitespace-pre-line">{b.text}</p>
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px] text-muted2">
                    <span className="min-w-0 truncate">
                      <span className="font-mono">{datum(b.erstellt_am)}</span> · {b.account_name || '—'}{b.user_email ? ` · ${b.user_email}` : ''}{b.seite ? ` · ${b.seite}` : ''}
                    </span>
                    {b.status === 'offen' ? (
                      <button onClick={() => setStatus(b, 'erledigt')} disabled={busy === b.id} className="shrink-0 font-semibold text-olive hover:underline">
                        {busy === b.id ? '…' : <span className="inline-flex items-center gap-1"><Icon name="check" size={14} /> erledigt</span>}
                      </button>
                    ) : (
                      <button onClick={() => setStatus(b, 'offen')} disabled={busy === b.id} className="shrink-0 text-terracotta hover:underline">
                        {busy === b.id ? '…' : '↩ wieder öffnen'}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
