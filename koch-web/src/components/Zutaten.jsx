import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Card, Button, input, Modal, Spinner, Empty, confirmDialog } from '../ui.jsx'
import { Icon } from '../icons.jsx'

export default function Zutaten({ notify, superAdmin = false }) {
  const [alle, setAlle] = useState([])
  const [unmapped, setUnmapped] = useState([])
  const [master, setMaster] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [picker, setPicker] = useState(null)   // Zutat, die (neu) zugeordnet wird
  const [rename, setRename] = useState(null)   // {id, name}
  const [offen, setOffen] = useState({})
  const [msuche, setMsuche] = useState('')

  async function load() {
    try {
      const [a, u, m] = await Promise.all([api.zutaten(), api.zutatenUnmapped(), api.zutatenMaster()])
      setAlle(a); setUnmapped(u); setMaster(m)
    } catch (e) {
      notify('Laden fehlgeschlagen: ' + e.message, 'err')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const byId = useMemo(() => {
    const m = {}
    for (const z of alle) m[z.id] = z
    return m
  }, [alle])

  // Kinder je Master-id (aus der vollen Zutatenliste)
  const kinderVon = useMemo(() => {
    const g = {}
    for (const z of alle) {
      if (z.kanonische_zutat_id == null) continue
      ;(g[z.kanonische_zutat_id] ||= []).push(z)
    }
    for (const k of Object.keys(g)) g[k].sort((a, b) => a.name.localeCompare(b.name, 'de'))
    return g
  }, [alle])

  const vorschlaege = useMemo(
    () => alle.filter((z) => z.kanonische_zutat_id != null && !z.kanonisch_fixiert)
      .sort((a, b) => a.name.localeCompare(b.name, 'de')),
    [alle],
  )

  // Master-Liste (mit rezept_zutat-Flag aus der Master-Query), durchsuchbar
  const masterListe = useMemo(() => {
    const q = msuche.trim().toLowerCase()
    return master
      .filter((m) => !q || m.name.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name, 'de'))
  }, [master, msuche])

  async function run(fn, okMsg) {
    try {
      const res = await fn()
      if (res && res.error) { notify(res.error, 'err'); return false }
      if (okMsg) notify(okMsg)
      await load()
      return true
    } catch (e) {
      notify('Fehler: ' + e.message, 'err')
      return false
    }
  }

  const bestaetigen = (z) => { setBusy(z.id); run(() => api.zutatKanonisch(z.id, z.kanonische_zutat_id, true), `„${z.name}" bestätigt`).finally(() => setBusy(null)) }
  const trennen = (z) => { setBusy(z.id); run(() => api.zutatKanonisch(z.id, null, false), `„${z.name}" getrennt`).finally(() => setBusy(null)) }

  async function zuordnen(zutatId, m, name) {
    setBusy(zutatId)
    const ok = await run(() => api.zutatKanonisch(zutatId, m.id, true), `„${name}" → ${m.name}`)
    if (ok) setPicker(null)
    setBusy(null)
  }

  async function speichernRename() {
    const ok = await run(() => api.zutatUmbenennen(rename.id, rename.name), 'Umbenannt')
    if (ok) setRename(null)
  }

  async function loeschen(m) {
    const anzahl = (kinderVon[m.id] || []).length
    const txt = anzahl > 0
      ? `„${m.name}" löschen? ${anzahl} zugeordnete Artikel werden wieder eigenständig.`
      : `„${m.name}" löschen?`
    if (!(await confirmDialog(txt))) return
    setBusy(m.id)
    run(() => api.zutatLoeschen(m.id), 'Gelöscht').finally(() => setBusy(null))
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner /></div>

  return (
    <div className="space-y-5">
      <div className="hero-card flex flex-wrap items-center justify-between gap-3 rounded-[22px] p-5">
        <div className="hero-glow" />
        <div className="relative min-w-0">
          <h2 className="font-dish text-3xl leading-tight text-ink">Zutaten</h2>
          <p className="label-mono mt-1.5 text-muted2">Master · Zuordnung</p>
        </div>
      </div>
      <p className="text-sm text-muted">
        Markenartikel werden auf eine generische Zutat („Master") abgebildet, damit Vorrat und
        Einkaufsliste sie als dasselbe erkennen.
      </p>

      {/* Vorschläge prüfen (nur Super-Admin – Master-Kuratierung) */}
      {superAdmin && vorschlaege.length > 0 && (
        <Card className="overflow-hidden">
          <div className="border-b border-line bg-olive/10 px-4 py-3">
            <h2 className="font-display text-xl">Vorschläge prüfen</h2>
            <p className="text-xs text-muted2">{vorschlaege.length} automatische Zuordnung(en) warten auf Bestätigung</p>
          </div>
          <ul className="divide-y divide-line">
            {vorschlaege.map((z) => (
              <li key={z.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{z.name}</span>
                  <span className="block truncate text-xs text-muted2">→ {byId[z.kanonische_zutat_id]?.name || '?'}</span>
                </div>
                <Button variant="olive" className="px-3 py-1.5" disabled={busy === z.id} onClick={() => bestaetigen(z)}><Icon name="check" size={16} /></Button>
                <Button variant="ghost" className="px-3 py-1.5" disabled={busy === z.id} onClick={() => trennen(z)}><Icon name="x" size={16} /></Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Noch zuzuordnen (nur Super-Admin – Master-Kuratierung) */}
      {superAdmin && (
      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3">
          <h2 className="font-display text-xl">Noch zuzuordnen</h2>
          <p className="text-xs text-muted2">Vorratsartikel ohne Master, die in keinem Rezept vorkommen</p>
        </div>
        {unmapped.length === 0 ? (
          <Empty><span className="inline-flex items-center gap-1">Alles zugeordnet <Icon name="party-popper" size={16} /></span></Empty>
        ) : (
          <ul className="divide-y divide-line">
            {unmapped.map((z) => (
              <li key={z.id} className="flex items-center gap-3 px-4 py-3">
                <span className="min-w-0 flex-1 truncate text-sm">{z.name}</span>
                <Button variant="ghost" className="px-3 py-1.5" onClick={() => setPicker(z)}>Zuordnen</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      )}

      {/* Master-Zutaten verwalten */}
      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3">
          <h2 className="font-display text-xl">Master-Zutaten</h2>
          <p className="text-xs text-muted2">{master.length} Master{superAdmin ? ' · umbenennen, löschen, zugeordnete Artikel verwalten' : ''}</p>
        </div>
        <div className="border-b border-line p-3">
          <input className={input} placeholder="Master suchen…" value={msuche} onChange={(e) => setMsuche(e.target.value)} />
        </div>
        {masterListe.length === 0 ? (
          <Empty>Kein Master gefunden</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {masterListe.map((m) => {
              const kinder = kinderVon[m.id] || []
              const auf = offen[m.id]
              return (
                <li key={m.id}>
                  <div className="flex items-center gap-2 px-4 py-3">
                    <button
                      onClick={() => kinder.length && setOffen((o) => ({ ...o, [m.id]: !o[m.id] }))}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      <span className="min-w-0 truncate text-sm font-semibold">{m.name}</span>
                      {m.rezept_zutat && <span className="shrink-0 rounded-full bg-terracotta/10 px-2 py-0.5 text-xs text-terracotta-deep">Rezept</span>}
                      {kinder.length > 0 && (
                        <span className="shrink-0 rounded-full bg-surface px-2 py-0.5 text-xs text-muted2">{kinder.length}</span>
                      )}
                      {kinder.length > 0 && <span className={`shrink-0 text-muted2 transition ${auf ? 'rotate-90' : ''}`}>›</span>}
                    </button>
                    {superAdmin && (
                      <button onClick={() => setRename({ id: m.id, name: m.name })} disabled={busy === m.id}
                        className="shrink-0 rounded-full px-2 py-1 text-xs text-muted2 hover:bg-surface">umbenennen</button>
                    )}
                    {superAdmin && (
                      <button onClick={() => loeschen(m)} disabled={busy === m.id}
                        className="shrink-0 rounded-full px-2 py-1 text-xs text-muted2 hover:bg-terracotta/10 hover:text-terracotta-deep">löschen</button>
                    )}
                  </div>
                  {auf && kinder.length > 0 && (
                    <ul className="bg-paper/40 pb-1">
                      {kinder.map((k) => (
                        <li key={k.id} className="flex items-center gap-2 py-1.5 pl-7 pr-4">
                          <span className="min-w-0 flex-1 truncate text-sm text-muted">
                            {k.name}
                            {!k.kanonisch_fixiert && <span className="ml-2 text-xs text-olive">(Vorschlag)</span>}
                          </span>
                          {superAdmin && (
                            <button onClick={() => setPicker(k)} disabled={busy === k.id}
                              className="rounded-full px-2 py-1 text-xs text-muted2 hover:bg-surface">ändern</button>
                          )}
                          {superAdmin && (
                            <button onClick={() => trennen(k)} disabled={busy === k.id}
                              className="rounded-full px-2 py-1 text-xs text-muted2 hover:bg-surface hover:text-terracotta-deep">trennen</button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      {picker && (
        <MasterPicker
          zutat={picker}
          master={master}
          busy={busy === picker.id}
          onClose={() => setPicker(null)}
          onPick={(m) => zuordnen(picker.id, m, picker.name)}
        />
      )}

      <Modal open={!!rename} onClose={() => setRename(null)} title="Master umbenennen">
        {rename && (
          <div className="space-y-3">
            <input className={input} autoFocus value={rename.name}
              onChange={(e) => setRename({ ...rename, name: e.target.value })}
              onKeyDown={(e) => e.key === 'Enter' && speichernRename()} />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setRename(null)}>Abbrechen</Button>
              <Button onClick={speichernRename}>Speichern</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function MasterPicker({ zutat, master, busy, onClose, onPick }) {
  const [suche, setSuche] = useState('')
  const treffer = useMemo(() => {
    const q = suche.trim().toLowerCase()
    return master
      .filter((m) => m.id !== zutat.id)
      .filter((m) => !q || m.name.toLowerCase().includes(q))
      .sort((a, b) => {
        if (!!b.rezept_zutat !== !!a.rezept_zutat) return b.rezept_zutat ? 1 : -1
        return a.name.localeCompare(b.name, 'de')
      })
      .slice(0, 60)
  }, [master, suche, zutat.id])

  return (
    <Modal open onClose={onClose} title="Master wählen">
      <p className="mb-3 text-sm text-muted">„{zutat.name}" zuordnen auf:</p>
      <input className={input} placeholder="Master suchen…" autoFocus value={suche} onChange={(e) => setSuche(e.target.value)} />
      <ul className="mt-3 max-h-[50vh] divide-y divide-line overflow-y-auto rounded-xl border border-line">
        {treffer.length === 0 ? (
          <li className="px-3 py-6 text-center text-sm text-muted">Kein Master gefunden</li>
        ) : (
          treffer.map((m) => (
            <li key={m.id}>
              <button disabled={busy} onClick={() => onPick(m)}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-surface disabled:opacity-50">
                <span className="min-w-0 flex-1 truncate">{m.name}</span>
                {m.rezept_zutat && <span className="rounded-full bg-terracotta/10 px-2 py-0.5 text-xs text-terracotta-deep">Rezept</span>}
              </button>
            </li>
          ))
        )}
      </ul>
    </Modal>
  )
}
