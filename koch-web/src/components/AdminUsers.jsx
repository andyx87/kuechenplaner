import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { Spinner, input } from '../ui.jsx'

const PRO_SEITE = 25

const SORT = [
  ['id_desc', 'Neueste ID'],
  ['neu', 'Neu angemeldet'],
  ['email', 'E-Mail'],
  ['name', 'Name'],
]

// Backoffice: Nutzer verwalten – mit Suche, Pagination und Sortierung (skaliert bei vielen Nutzern).
export default function AdminUsers({ notify, superAdmin = false }) {
  const [users, setUsers] = useState(null)
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('id_desc')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(null)

  const lade = useCallback(() => {
    return api.adminUsers({ q, sort, limit: PRO_SEITE, offset })
      .then((res) => { setUsers(res.users || []); setTotal(res.total || 0) })
      .catch(() => notify('Nutzer laden fehlgeschlagen', 'err'))
  }, [q, sort, offset, notify])

  // Suche entprellt; bei Suche/Sortierung zurück auf Seite 1.
  useEffect(() => {
    const t = setTimeout(() => { lade() }, q ? 300 : 0)
    return () => clearTimeout(t)
  }, [lade, q])

  function patch(id, fields) { setUsers((l) => l.map((x) => (x.id === id ? { ...x, ...fields } : x))) }

  async function toggleUpload(u) {
    setBusy(u.id)
    try { await api.adminUserUploadSetzen(u.id, !u.darf_angebote_upload); patch(u.id, { darf_angebote_upload: !u.darf_angebote_upload }) }
    catch { notify('Speichern fehlgeschlagen', 'err') } finally { setBusy(null) }
  }
  async function toggleKi(u) {
    const neu = u.ki_erlaubt === false
    setBusy(u.id)
    try { await api.adminUserKiSetzen(u.id, neu); patch(u.id, { ki_erlaubt: neu }) }
    catch { notify('Speichern fehlgeschlagen', 'err') } finally { setBusy(null) }
  }
  async function toggleSupport(u) {
    const neu = u.plattform_rolle === 'support' ? null : 'support'
    setBusy(u.id)
    try { await api.adminUserRolleSetzen(u.id, neu); patch(u.id, { plattform_rolle: neu }) }
    catch { notify('Rolle setzen fehlgeschlagen', 'err') } finally { setBusy(null) }
  }
  async function toggleAktiv(u) {
    const sperren = u.aktiv !== false   // aktuell aktiv → jetzt sperren
    const ok = window.confirm(sperren
      ? `Nutzer „${u.email}" sperren?\nEr kann sich dann nicht mehr einloggen und wird sofort ausgeloggt.`
      : `Nutzer „${u.email}" wieder entsperren?`)
    if (!ok) return
    setBusy(u.id)
    try {
      const res = await api.adminUserAktivSetzen(u.id, !sperren)
      if (res?.error) { notify(res.error, 'err') }
      else { patch(u.id, { aktiv: !sperren }); notify(sperren ? 'Nutzer gesperrt' : 'Nutzer entsperrt') }
    } catch { notify('Sperren fehlgeschlagen', 'err') } finally { setBusy(null) }
  }
  const seite = Math.floor(offset / PRO_SEITE) + 1
  const seiten = Math.max(1, Math.ceil(total / PRO_SEITE))

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input className={input + ' min-w-[12rem] flex-1'} placeholder="Suche: E-Mail, Name, Konto, ID…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0) }} />
        <select className={input + ' w-auto'} value={sort} onChange={(e) => { setSort(e.target.value); setOffset(0) }}>
          {SORT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <span className="font-mono text-xs text-muted2">{total} Nutzer</span>
      </div>

      {!users ? <div className="py-8 text-center"><Spinner /></div> : (
        users.length === 0 ? <p className="py-8 text-center text-sm text-muted">Keine Treffer.</p> : (
          <ul className="space-y-2">
            {users.map((u) => {
              const su = u.plattform_rolle === 'super_admin'
              return (
                <li key={u.id} className="rounded-lg border border-line/60 bg-card/60 p-2.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{u.name || u.email} <span className="font-mono text-xs font-normal text-muted2">#{u.id}</span>{u.aktiv === false && <span className="ml-1.5 rounded bg-terracotta/15 px-1.5 py-0.5 text-[10px] font-semibold text-terracotta-deep align-middle">gesperrt</span>}</span>
                      <span className="block truncate text-xs text-muted">
                        {u.email}{u.account_name ? ` · ${u.account_name}` : ''}
                        {u.plattform_rolle ? ` · ${u.plattform_rolle}` : ''}
                      </span>
                    </span>
                  </div>
                  {superAdmin && !su && (
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line/40 pt-2 text-xs">
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={u.ki_erlaubt !== false} disabled={busy === u.id} onChange={() => toggleKi(u)} className="h-3.5 w-3.5 accent-terracotta" />
                        <span className="text-muted">KI erlaubt</span>
                      </label>
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={!!u.darf_angebote_upload} disabled={busy === u.id} onChange={() => toggleUpload(u)} className="h-3.5 w-3.5 accent-terracotta" />
                        <span className="text-muted">Angebote-Upload</span>
                      </label>
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={u.plattform_rolle === 'support'} disabled={busy === u.id} onChange={() => toggleSupport(u)} className="h-3.5 w-3.5 accent-terracotta" />
                        <span className="text-muted">Support</span>
                      </label>
                      <button onClick={() => toggleAktiv(u)} disabled={busy === u.id}
                        className={`ml-auto rounded-md border px-2 py-0.5 font-semibold disabled:opacity-40 ${u.aktiv === false ? 'border-olive/50 text-olive hover:bg-olive/10' : 'border-terracotta/50 text-terracotta hover:bg-terracotta/10'}`}>
                        {busy === u.id ? '…' : (u.aktiv === false ? 'entsperren' : 'sperren')}
                      </button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )
      )}

      {seiten > 1 && (
        <div className="mt-3 flex items-center justify-center gap-3 text-sm">
          <button onClick={() => setOffset(Math.max(0, offset - PRO_SEITE))} disabled={seite <= 1}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40">‹ Zurück</button>
          <span className="font-mono text-muted">Seite {seite} / {seiten}</span>
          <button onClick={() => setOffset(offset + PRO_SEITE)} disabled={seite >= seiten}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40">Weiter ›</button>
        </div>
      )}
    </div>
  )
}
