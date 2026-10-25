import { useState } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'
import { input, confirmDialog } from '../ui.jsx'

// Backoffice (Super-Admin): Account-eigene Master-Zutaten in die globale DB
// überführen – entweder global machen oder in einen bestehenden globalen Master
// zusammenführen (Rezepte werden mit angepasst).
export default function AdminZutaten({ notify }) {
  const [data, setData] = useState(null)   // { kandidaten, globale_master }
  const [auf, setAuf] = useState(false)
  const [busy, setBusy] = useState(null)
  const [kuratierName, setKuratierName] = useState({})   // kandidatId -> Ziel-Name (Freitext)

  function lade() {
    return api.adminZutatenKuratierung().then(setData).catch(() => notify('Kandidaten laden fehlgeschlagen', 'err'))
  }
  function toggle() { setAuf((v) => { if (!v && !data) lade(); return !v }) }

  async function globalMachen(k) {
    if (!(await confirmDialog({ title: 'Global machen?', message: `„${k.name}" für alle Haushalte global verfügbar machen?`, confirmLabel: 'Global machen' }))) return
    setBusy(k.id)
    try {
      const res = await api.adminZutatGlobal(k.id)
      if (res?.error) notify(res.error, 'err')
      else { notify(`„${k.name}" ist jetzt global`); await lade() }
    } catch { notify('Fehlgeschlagen', 'err') } finally { setBusy(null) }
  }

  const zielName = (k) => (kuratierName[k.id] ?? (k.global_exakt?.name || k.global_aehnlich?.name || k.name))

  async function kuratieren(k) {
    const nm = zielName(k).trim()
    if (!nm) { notify('Bitte einen Ziel-Namen eingeben', 'err'); return }
    if (!(await confirmDialog({
      title: 'Kuratieren?',
      message: `„${k.name}" unter dem globalen Namen „${nm}" übernehmen?\n\nGibt es diesen globalen Master schon, wird zusammengeführt (Rezepte/Vorrat/Angebote umgehängt, „${k.name}" gelöscht); sonst wird die Zutat unter diesem Namen neu global angelegt.`,
      confirmLabel: 'Übernehmen',
    }))) return
    setBusy(k.id)
    try {
      const res = await api.adminZutatKuratieren(k.id, nm)
      if (res?.error) notify(res.error, 'err')
      else { notify(res.merged ? `„${k.name}" → „${nm}" zusammengeführt` : `„${nm}" global angelegt`); await lade() }
    } catch { notify('Fehlgeschlagen', 'err') } finally { setBusy(null) }
  }

  const kandidaten = data?.kandidaten || []
  const globale = data?.globale_master || []

  return (
    <div className="rounded-xl border border-terracotta/40 bg-terracotta/5 p-3">
      <button onClick={toggle} className="flex w-full items-center justify-between text-sm font-semibold">
        <span className="inline-flex items-center gap-1.5"><Icon name="flask" size={16} /> Zutaten-Kuratierung{data ? ` (${kandidaten.length})` : ''}</span>
        <span className="text-muted2">{auf ? '▲' : '▼'}</span>
      </button>

      {auf && (
        <div className="mt-2 space-y-2">
          <p className="text-[11px] text-muted">Account-eigene Master-Zutaten → in die globale DB überführen. Ziel-Name eingeben: gleichnamiger globaler Master = zusammenführen, sonst neu global.</p>
          <datalist id="kuratier-globale">
            {globale.map((g) => <option key={g.id} value={g.name} />)}
          </datalist>
          {!data ? (
            <p className="py-2 text-center text-xs text-muted2">lädt …</p>
          ) : kandidaten.length === 0 ? (
            <p className="py-2 text-center text-xs text-muted2">Keine offenen Kandidaten</p>
          ) : (
            <ul className="space-y-2">
              {kandidaten.map((k) => {
                const vorschlag = k.global_exakt || k.global_aehnlich
                return (
                  <li key={k.id} className="rounded-lg border border-line/60 bg-card/60 p-2.5 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate font-medium capitalize">{k.name}</span>
                        <span className="block truncate text-[11px] text-muted">
                          {k.account_name || '—'} · <span className="font-mono">{k.rezept_count}</span> Rezepte · <span className="font-mono">{k.vorrat_count}</span> Vorrat{k.kinder_count ? <> · <span className="font-mono">{k.kinder_count}</span> Kinder</> : ''}
                        </span>
                      </span>
                      <button
                        onClick={() => globalMachen(k)}
                        disabled={busy === k.id || !!k.global_exakt}
                        title={k.global_exakt ? 'Globale Zutat mit gleichem Namen existiert – stattdessen zusammenführen' : ''}
                        className="shrink-0 rounded-lg border border-olive/40 px-2 py-1 text-xs font-semibold text-olive disabled:opacity-40 hover:bg-olive/10"
                      >
                        → Global
                      </button>
                    </div>

                    {vorschlag && (
                      <p className="mt-1 text-[11px] text-muted2">
                        Vorschlag: {k.global_exakt ? 'exakter' : 'ähnlicher'} globaler Master „{vorschlag.name}"
                      </p>
                    )}

                    <div className="mt-2 flex items-center gap-2 border-t border-line/40 pt-2">
                      <input
                        className={input + ' min-w-0 flex-1 py-1 text-xs'}
                        list="kuratier-globale"
                        placeholder="Ziel-Name (global)"
                        value={zielName(k)}
                        onChange={(e) => setKuratierName((m) => ({ ...m, [k.id]: e.target.value }))}
                      />
                      <button
                        onClick={() => kuratieren(k)}
                        disabled={busy === k.id || !zielName(k).trim()}
                        className="shrink-0 rounded-lg border border-terracotta/50 px-2 py-1 text-xs font-semibold text-terracotta-deep disabled:opacity-40 hover:bg-terracotta/10"
                      >
                        {busy === k.id ? '…' : 'Übernehmen'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
