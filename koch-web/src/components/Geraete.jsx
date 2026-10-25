import { useEffect, useState, useRef } from 'react'
import { api } from '../api.js'
import { Card, Button, Field, input, Modal, Spinner, Empty, confirmDialog } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { IST_NATIVE } from '../native.js'
import { nativeFoto } from '../nativeFoto.js'
import { useKi } from '../kiStatus.js'

export default function Geraete({ notify }) {
  const ki = useKi()
  const [geraete, setGeraete] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(null) // null | {mode:'add'} | {mode:'edit', geraet}
  const [adapt, setAdapt] = useState(null) // Job-Status beim Anpassen
  const [fotoBusy, setFotoBusy] = useState(false)
  const [vorschlag, setVorschlag] = useState(null) // null | [{name, typ, sel}]
  const [speichern, setSpeichern] = useState(false)
  const fotoRef = useRef(null)

  async function verarbeiteFoto(file) {
    if (!file) return
    setFotoBusy(true)
    try {
      const res = await api.geraeteFoto(file)
      const gefunden = (res.vorschlag || []).map((g) => ({ name: g.name || '', typ: g.typ || null, sel: true }))
      if (gefunden.length === 0) { notify('Keine Geräte erkannt – bitte manuell anlegen.'); return }
      setVorschlag(gefunden)
    } catch {
      notify('Foto-Erkennung fehlgeschlagen', 'err')
    } finally {
      setFotoBusy(false)
    }
  }
  function fotoGewaehlt(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    verarbeiteFoto(file)
  }
  async function fotoAufnehmen() {
    if (IST_NATIVE) {
      const file = await nativeFoto()
      if (file) verarbeiteFoto(file)
    } else {
      fotoRef.current?.click()
    }
  }

  async function vorschlagSpeichern() {
    const zu = (vorschlag || []).filter((g) => g.sel && g.name.trim())
    if (!zu.length) { setVorschlag(null); return }
    setSpeichern(true)
    try {
      const neu = []
      for (const g of zu) {
        const saved = await api.geraetAnlegen({ name: g.name.trim(), typ: g.typ || null, standard: true })
        neu.push(saved)
      }
      setGeraete((p) => [...p, ...neu])
      notify(`${neu.length} Gerät${neu.length === 1 ? '' : 'e'} hinzugefügt`)
      setVorschlag(null)
    } catch {
      notify('Hinzufügen fehlgeschlagen', 'err')
    } finally {
      setSpeichern(false)
    }
  }

  async function anpassen() {
    if (!(await confirmDialog('Die Zubereitung aller Rezepte per KI an die aktuellen Geräte anpassen?\n\nVorhandene Schritte bleiben, fehlende Geräte-Varianten werden ergänzt. Läuft im Hintergrund.'))) return
    setAdapt({ status: 'laeuft', index: 0, total: 0, angepasst: 0 })
    try {
      const { job_id } = await api.rezepteGeraeteAnpassen()
      pollAdapt(job_id)
    } catch {
      notify('Anpassen konnte nicht gestartet werden', 'err')
      setAdapt(null)
    }
  }

  function pollAdapt(jobId) {
    api.rezepteGeraeteAnpassenStatus(jobId).then((job) => {
      setAdapt(job)
      if (job.status === 'fertig') {
        notify(`${job.angepasst} angepasst${job.uebersprungen ? `, ${job.uebersprungen} schon abgestimmt` : ''}`)
        setTimeout(() => setAdapt(null), 5000)
      } else if (job.status === 'fehler') {
        notify('Anpassen fehlgeschlagen', 'err')
        setTimeout(() => setAdapt(null), 8000)
      } else {
        setTimeout(() => pollAdapt(jobId), 1500)
      }
    }).catch(() => setTimeout(() => pollAdapt(jobId), 2500))
  }

  async function lade() {
    setLoading(true)
    try {
      setGeraete(await api.geraete())
    } catch {
      notify('Geräte konnten nicht geladen werden', 'err')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    lade()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loeschen(g) {
    if (!(await confirmDialog(`„${g.name}" löschen? Das Gerät wird auch aus allen Rezepten entfernt.`))) return
    try {
      await api.geraetLoeschen(g.id)
      setGeraete((p) => p.filter((x) => x.id !== g.id))
      notify('Gerät gelöscht')
    } catch {
      notify('Löschen fehlgeschlagen', 'err')
    }
  }

  if (loading)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    )

  const alltag = geraete.filter((g) => g.standard)
  const situativ = geraete.filter((g) => !g.standard)

  const zeile = (g) => (
    <Card key={g.id} className="flex items-center justify-between gap-3 p-3">
      <div className="min-w-0">
        <p className="truncate font-dish text-xl leading-tight">{g.name}</p>
        {(g.typ || g.notizen) && (
          <p className="truncate text-sm text-muted">{[g.typ, g.notizen].filter(Boolean).join(' · ')}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          onClick={() => setForm({ mode: 'edit', geraet: g })}
          className="rounded-full px-3 py-1.5 text-sm font-semibold text-muted hover:bg-ink/5"
        >
          Bearbeiten
        </button>
        <button
          onClick={() => loeschen(g)}
          className="rounded-full px-3 py-1.5 text-sm text-terracotta-deep hover:bg-terracotta/10"
        >
          Löschen
        </button>
      </div>
    </Card>
  )

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 hero-card flex flex-wrap items-center justify-between gap-3 rounded-[22px] p-5">
          <div className="hero-glow" />
          <div className="relative min-w-0">
            <h2 className="font-dish text-3xl leading-tight text-ink">Küchengeräte</h2>
            <p className="label-mono mt-1.5 text-muted2">{ki.vision ? 'Ausstattung · Foto-Erfassung' : 'Ausstattung'}</p>
          </div>
          <div className="relative flex flex-wrap justify-end gap-2">
            {ki.vision && <Button variant="kiGhost" onClick={fotoAufnehmen} disabled={fotoBusy}>
              {fotoBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="camera" size={16} /> Foto</span>}
            </Button>}
            <Button onClick={() => setForm({ mode: 'add' })}>+ Gerät</Button>
          </div>
        </div>
        <input ref={fotoRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={fotoGewaehlt} />

        {ki.text && geraete.length > 0 && (
          <button
            onClick={anpassen}
            disabled={adapt && adapt.status === 'laeuft'}
            className="mb-4 inline-flex w-full items-center justify-center gap-1 rounded-xl border border-terracotta/50 px-3 py-2 text-sm font-semibold text-terracotta transition hover:bg-terracotta/10 disabled:opacity-50"
          >
            <Icon name="wrench" size={16} /> Rezepte an Geräte anpassen
          </button>
        )}

        {adapt && (
          <div className={`mb-4 flex items-center gap-3 rounded-xl border p-3 text-sm ${
            adapt.status === 'fehler' ? 'border-terracotta/40 bg-terracotta/10 text-terracotta-deep'
              : adapt.status === 'fertig' ? 'border-olive/40 bg-olive/10 text-olive'
              : 'border-olive/30 bg-olive/10 text-olive'}`}>
            {adapt.status === 'laeuft' && <Spinner />}
            <span className="flex-1 font-semibold">
              {adapt.status === 'fertig' ? `${adapt.angepasst} angepasst${adapt.uebersprungen ? `, ${adapt.uebersprungen} schon abgestimmt` : ''}`
                : adapt.status === 'fehler' ? ('Fehler: ' + (adapt.error || 'unbekannt'))
                : adapt.total > 0 ? `Rezepte werden angepasst … ${adapt.index}/${adapt.total} (${adapt.angepasst || 0} geändert, ${adapt.uebersprungen || 0} ok)`
                : 'Anpassung startet …'}
            </span>
          </div>
        )}

        {geraete.length === 0 && <Empty>Noch keine Geräte angelegt.</Empty>}

        {alltag.length > 0 && (
          <div className="mb-5">
            <p className="mb-1.5 label-mono text-muted2">Alltag</p>
            <div className="space-y-2">{alltag.map(zeile)}</div>
          </div>
        )}

        {situativ.length > 0 && (
          <div>
            <p className="mb-1.5 label-mono text-muted2">Nur bei Bedarf</p>
            <div className="space-y-2">{situativ.map(zeile)}</div>
          </div>
        )}
      </section>

      {vorschlag && (
        <Modal open onClose={() => setVorschlag(null)} title="Erkannte Geräte">
          <div className="space-y-3">
            <p className="text-sm text-muted">Die KI hat diese Küchengeräte erkannt. Wähle aus, korrigiere die Namen und füge sie hinzu.</p>
            <ul className="space-y-2">
              {vorschlag.map((g, i) => (
                <li key={i} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={g.sel}
                    onChange={() => setVorschlag((v) => v.map((x, j) => (j === i ? { ...x, sel: !x.sel } : x)))}
                    className="h-4 w-4 shrink-0 accent-olive"
                  />
                  <input
                    className={input + ' flex-1'}
                    value={g.name}
                    onChange={(e) => setVorschlag((v) => v.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                  />
                  {g.typ && <span className="shrink-0 text-xs text-muted2">{g.typ}</span>}
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setVorschlag(null)}>Abbrechen</Button>
              <Button onClick={vorschlagSpeichern} disabled={speichern}>
                {speichern ? <Spinner /> : `${vorschlag.filter((g) => g.sel && g.name.trim()).length} hinzufügen`}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {form && (
        <GeraetForm
          notify={notify}
          geraet={form.mode === 'edit' ? form.geraet : null}
          onClose={() => setForm(null)}
          onSaved={(saved, mode) => {
            setGeraete((p) =>
              mode === 'edit' ? p.map((x) => (x.id === saved.id ? saved : x)) : [...p, saved],
            )
            setForm(null)
          }}
        />
      )}
    </div>
  )
}

function GeraetForm({ notify, geraet, onClose, onSaved }) {
  const editing = !!geraet
  const [f, setF] = useState(() => ({
    name: geraet?.name || '',
    typ: geraet?.typ || '',
    notizen: geraet?.notizen || '',
    standard: geraet?.standard ?? true,
  }))

  async function speichern() {
    if (!f.name.trim()) {
      notify('Name nötig', 'err')
      return
    }
    const payload = {
      name: f.name.trim(),
      typ: f.typ.trim() || null,
      notizen: f.notizen.trim() || null,
      standard: !!f.standard,
    }
    try {
      const saved = editing
        ? await api.geraetUpdate(geraet.id, payload)
        : await api.geraetAnlegen(payload)
      notify(editing ? 'Gerät aktualisiert' : 'Gerät angelegt')
      onSaved(saved, editing ? 'edit' : 'add')
    } catch {
      notify('Speichern fehlgeschlagen', 'err')
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? 'Gerät bearbeiten' : 'Neues Gerät'}>
      <div className="space-y-3">
        <Field label="Name">
          <input className={input} value={f.name} placeholder="z.B. Thermomix" onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Typ (optional)">
          <input className={input} value={f.typ} placeholder="z.B. Mixer, Backofen, Airfryer" onChange={(e) => setF({ ...f, typ: e.target.value })} />
        </Field>
        <Field label="Notizen (optional)">
          <textarea className={input + ' min-h-[70px] resize-y'} value={f.notizen} onChange={(e) => setF({ ...f, notizen: e.target.value })} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-ink/80">
          <input
            type="checkbox"
            checked={f.standard}
            onChange={(e) => setF({ ...f, standard: e.target.checked })}
            className="h-4 w-4 accent-terracotta"
          />
          Alltagsgerät (in „Heute" automatisch vorausgewählt)
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button onClick={speichern}>Speichern</Button>
        </div>
      </div>
    </Modal>
  )
}
