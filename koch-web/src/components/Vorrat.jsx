import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { Card, Button, Field, input, Modal, Spinner, Empty, Chip, confirmDialog } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { useKi } from '../kiStatus.js'

const leer = { name: '', menge: '', einheit: '', ablaufdatum: '', lagerort_id: '' }

function fmt(m) {
  const n = Number(m)
  return Number.isInteger(n) ? n : Math.round(n * 100) / 100
}

// Einheiten-Umrechnung (clientseitig, konsistent mit Backend _basis_mit_gebinde)
const EINHEIT_BASIS = {
  g: ['masse', 1], gramm: ['masse', 1], mg: ['masse', 0.001], kg: ['masse', 1000],
  ml: ['volumen', 1], cl: ['volumen', 10], l: ['volumen', 1000], liter: ['volumen', 1000],
}
function einheitBasis(e) {
  const k = (e || '').trim().toLowerCase()
  return EINHEIT_BASIS[k] || [k || 'stk', 1]
}
// -> [klasse, basismenge]; rechnet Pack/Stück via Gebinde in masse/volumen um
function basisMitGebinde(menge, einheit, gm, ge) {
  const [klasse, fkt] = einheitBasis(einheit)
  const m = Number(menge) || 0
  if (klasse !== 'masse' && klasse !== 'volumen' && gm) {
    const [gk, gfkt] = einheitBasis(ge)
    if (gk === 'masse' || gk === 'volumen') return [gk, m * Number(gm) * gfkt]
  }
  return [klasse, m * fkt]
}
function fmtMenge(klasse, v) {
  if (klasse === 'masse') return v >= 1000 ? `${fmt(v / 1000)} kg` : `${fmt(v)} g`
  if (klasse === 'volumen') return v >= 1000 ? `${fmt(v / 1000)} l` : `${fmt(v)} ml`
  return `${fmt(v)} ${klasse}`
}

function tageBis(d) {
  if (!d) return null
  const heute = new Date()
  heute.setHours(0, 0, 0, 0)
  const dt = new Date(d + 'T00:00:00')
  return Math.round((dt - heute) / 86400000)
}

function mhdKlasse(ablaufdatum) {
  const t = tageBis(ablaufdatum)
  if (t === null) return ''
  if (t < 0) return 'text-terracotta-deep font-semibold'
  if (t <= 7) return 'text-terracotta'
  return 'text-ink/60'
}

function LagerortFeld({ lagerorte, value, onChange, onCreate }) {
  const [neu, setNeu] = useState('')
  const [modeNeu, setModeNeu] = useState(false)

  async function anlegen() {
    const name = neu.trim()
    if (!name) return
    const l = await onCreate(name)
    if (l) { onChange(String(l.id)); setNeu(''); setModeNeu(false) }
  }

  return (
    <div>
      <select
        className={input}
        value={modeNeu ? '__neu__' : value || ''}
        onChange={(e) => {
          if (e.target.value === '__neu__') setModeNeu(true)
          else { setModeNeu(false); onChange(e.target.value) }
        }}
      >
        <option value="">— kein Ort</option>
        {lagerorte.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        <option value="__neu__">+ Neuer Ort…</option>
      </select>
      {modeNeu && (
        <div className="mt-2 flex gap-2">
          <input className={input} placeholder="Name des Lagerorts" value={neu}
            onChange={(e) => setNeu(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && anlegen()} />
          <Button variant="ghost" onClick={anlegen}>Anlegen</Button>
        </div>
      )}
    </div>
  )
}

function LagerortZeile({ lo, anzahl, onRename, onDelete, onNeuErfassen }) {
  function umbenennen() {
    const n = window.prompt('Lagerort umbenennen:', lo.name)
    if (n && n.trim() && n.trim() !== lo.name) onRename(n.trim())
  }
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium capitalize">{lo.name}</span>
        <span className="shrink-0 font-mono text-xs text-muted2">{anzahl} Artikel</span>
      </div>
      <div className="mt-2 flex gap-2">
        <button onClick={umbenennen} className="flex-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink/70 transition hover:bg-line/20">
          Umbenennen
        </button>
        <button onClick={onNeuErfassen} className="flex-1 inline-flex items-center justify-center gap-1 rounded-lg border border-olive/40 px-3 py-1.5 text-xs font-semibold text-olive transition hover:bg-olive/10">
          <Icon name="recycle" size={16} className="text-olive" /> Neu erfassen
        </button>
        <button onClick={onDelete} className="flex-1 rounded-lg border border-terracotta/40 px-3 py-1.5 text-xs font-semibold text-terracotta-deep transition hover:bg-terracotta/10">
          Löschen
        </button>
      </div>
    </div>
  )
}

function VorratZeile({ it, onEdit, onLoeschen }) {
  const ortName = it.lagerort || it.ort
  const cls = mhdKlasse(it.ablaufdatum)
  const t = tageBis(it.ablaufdatum)
  return (
    <div className="flex items-center justify-between gap-3 px-3.5 py-3">
      <div className="min-w-0">
        <p className="truncate font-dish text-xl leading-tight">{it.zutat}</p>
        <p className="truncate font-mono text-xs text-muted">
          {fmt(it.menge)} {it.einheit}
          {ortName ? ` · ${ortName}` : ''}
          {it.ablaufdatum ? (
            <span className={cls}>{' · bis '}{it.ablaufdatum}{t < 0 ? ' (abgelaufen)' : ''}</span>
          ) : ''}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        <button onClick={() => onEdit(it)} className="rounded-full px-3 py-1.5 text-sm hover:bg-ink/5">Bearbeiten</button>
        <button onClick={() => onLoeschen(it.id)} className="rounded-full px-3 py-1.5 text-sm text-terracotta-deep hover:bg-terracotta/10">Löschen</button>
      </div>
    </div>
  )
}

export default function Vorrat({ notify }) {
  const ki = useKi()
  const [items, setItems] = useState([])
  const [zutaten, setZutaten] = useState([])
  const [lagerorte, setLagerorte] = useState([])
  const [loading, setLoading] = useState(true)
  const [add, setAdd] = useState(false)
  const [form, setForm] = useState(leer)
  const [edit, setEdit] = useState(null)

  const [suche, setSuche] = useState('')
  const [fOrt, setFOrt] = useState('alle')
  const [fMhd, setFMhd] = useState('alle')
  const [offen, setOffen] = useState(new Set())
  const [verwalten, setVerwalten] = useState(false)   // Lagerorte-Verwaltung
  const [mehrfach, setMehrfach] = useState(false)      // Add-Modal: Bereich neu erfassen
  const [anzeige, setAnzeige] = useState('lagerorte')  // 'zutaten' | 'lagerorte' (Lagerort = Standard)

  // Kamera-/KI-Erfassung (Foto -> Vorschlagsliste -> in den Vorrat)
  const fotoRef = useRef(null)
  const pendingOrt = useRef('')                        // Ziel-Lagerort der nächsten Foto-Erfassung
  const [fotoBusy, setFotoBusy] = useState(false)
  const [vorschlag, setVorschlag] = useState(null)     // null | { ort, items:[{name,menge,einheit,ablaufdatum,sel}] }
  const [vorschlagBusy, setVorschlagBusy] = useState(false)

  async function lade() {
    setLoading(true)
    try {
      const [v, lo, z] = await Promise.all([api.vorrat(), api.lagerorte(), api.zutaten()])
      setItems(v)
      setLagerorte(lo)
      setZutaten(z)
    } catch {
      notify('Vorrat laden fehlgeschlagen', 'err')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { lade() /* eslint-disable-next-line */ }, [])

  // Zutat-Map + Master-Auflösung (clientseitig)
  const byId = useMemo(() => {
    const m = {}
    for (const z of zutaten) m[z.id] = z
    return m
  }, [zutaten])

  const masterOf = (zutatId) => {
    const z = byId[zutatId]
    return z && z.kanonische_zutat_id != null ? z.kanonische_zutat_id : zutatId
  }
  const masterName = (mid, fallback) => byId[mid]?.name || fallback

  async function neuerLagerort(name) {
    try {
      const l = await api.lagerortAnlegen({ name })
      setLagerorte((arr) =>
        [...arr.filter((x) => x.id !== l.id), l].sort(
          (a, b) => a.sortierung - b.sortierung || a.name.localeCompare(b.name)
        )
      )
      return l
    } catch { notify('Lagerort anlegen fehlgeschlagen', 'err'); return null }
  }

  async function speichernNeu() {
    if (!form.name.trim() || !form.einheit.trim()) { notify('Name und Einheit nötig', 'err'); return }
    try {
      await api.vorratHinzufuegen([{
        name: form.name.trim(), menge: Number(form.menge) || 0,
        einheit: form.einheit.trim(), ablaufdatum: form.ablaufdatum || null,
        lagerort_id: form.lagerort_id ? Number(form.lagerort_id) : null,
      }])
      if (mehrfach) {
        // "Bereich neu erfassen": Ort behalten, Rest leeren, Modal offen lassen.
        setForm((f) => ({ ...leer, lagerort_id: f.lagerort_id }))
        lade(); notify('Hinzugefügt – weiter erfassen')
      } else {
        setAdd(false); setForm(leer); lade(); notify('Hinzugefügt')
      }
    } catch { notify('Speichern fehlgeschlagen', 'err') }
  }

  function schliesseAdd() {
    setAdd(false); setMehrfach(false); setForm(leer)
  }

  async function renameLagerort(id, name) {
    const n = (name || '').trim()
    if (!n) return
    try {
      const l = await api.lagerortUpdate(id, { name: n })
      setLagerorte((arr) => arr.map((x) => (x.id === id ? l : x)))
      lade(); notify('Lagerort umbenannt')
    } catch { notify('Umbenennen fehlgeschlagen', 'err') }
  }

  async function deleteLagerort(lo) {
    const n = items.filter((it) => it.lagerort_id === lo.id).length
    if (!(await confirmDialog(`Lagerort „${lo.name}" löschen?\n\n${n} Artikel bleiben erhalten, verlieren aber ihren Ort.`))) return
    try {
      await api.lagerortLoeschen(lo.id)
      setLagerorte((arr) => arr.filter((x) => x.id !== lo.id))
      if (fOrt === lo.id) setFOrt('alle')
      lade(); notify('Lagerort gelöscht')
    } catch { notify('Löschen fehlgeschlagen', 'err') }
  }

  async function neuErfassen(lo) {
    const n = items.filter((it) => it.lagerort_id === lo.id).length
    if (!(await confirmDialog(`„${lo.name}" komplett neu erfassen?\n\n${n} vorhandene Artikel an diesem Ort werden GELÖSCHT. Danach kannst du den Bereich frisch erfassen.`))) return
    try {
      await api.lagerortVorratLeeren(lo.id)
      await lade()
      setVerwalten(false)
      setForm({ ...leer, lagerort_id: String(lo.id) })
      setMehrfach(true)
      setAdd(true)
      notify(`„${lo.name}" geleert – jetzt neu erfassen`)
    } catch { notify('Leeren fehlgeschlagen', 'err') }
  }

  // --- Kamera-/KI-Erfassung ---------------------------------------------
  function startKamera(lagerortId) {
    pendingOrt.current = lagerortId ? String(lagerortId) : ''
    fotoRef.current?.click()
  }

  // „Neu erfassen" per Foto: Ort zuerst leeren, dann Kamera öffnen.
  async function kameraNeuErfassen(lo) {
    const n = items.filter((it) => it.lagerort_id === lo.id).length
    if (!(await confirmDialog(`„${lo.name}" komplett neu per Foto erfassen?\n\n${n} vorhandene Artikel an diesem Ort werden zuerst GELÖSCHT.`))) return
    try { await api.lagerortVorratLeeren(lo.id); await lade() }
    catch { notify('Leeren fehlgeschlagen', 'err'); return }
    setVerwalten(false)
    startKamera(lo.id)
  }

  async function fotoGewaehlt(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setFotoBusy(true)
    try {
      const res = await api.foto(file)
      const gefunden = (res.vorschlag || []).map((g) => ({
        name: g.name || '', menge: g.menge ?? '', einheit: g.einheit || '',
        ablaufdatum: g.ablaufdatum || '', sel: true,
      }))
      if (gefunden.length === 0) { notify('Nichts erkannt – bitte manuell hinzufügen.'); return }
      setVorschlag({ ort: pendingOrt.current, items: gefunden })
    } catch {
      notify('Foto-Erkennung fehlgeschlagen', 'err')
    } finally {
      setFotoBusy(false)
    }
  }

  function setVorschlagItem(i, patch) {
    setVorschlag((v) => v && ({ ...v, items: v.items.map((it, idx) => idx === i ? { ...it, ...patch } : it) }))
  }

  async function vorschlagSpeichern() {
    const zu = (vorschlag?.items || []).filter((g) => g.sel && g.name.trim())
    if (!zu.length) { setVorschlag(null); return }
    setVorschlagBusy(true)
    try {
      await api.vorratHinzufuegen(zu.map((g) => ({
        name: g.name.trim(), menge: Number(g.menge) || 0,
        einheit: (g.einheit || '').trim() || 'Stück',
        ablaufdatum: g.ablaufdatum || null,
        lagerort_id: vorschlag.ort ? Number(vorschlag.ort) : null,
      })))
      setVorschlag(null); await lade(); notify(`${zu.length} Artikel hinzugefügt`)
    } catch { notify('Speichern fehlgeschlagen', 'err') }
    finally { setVorschlagBusy(false) }
  }

  async function speichernEdit() {
    try {
      await api.vorratUpdate(edit.id, {
        menge: Number(edit.menge) || 0, einheit: edit.einheit,
        ablaufdatum: edit.ablaufdatum || null,
        lagerort_id: edit.lagerort_id ? Number(edit.lagerort_id) : null,
      })
      // Gebinde-Größe (Stammdatum der Zutat) nur schreiben, wenn geändert
      if (edit.zutat_id && (edit.gebinde_menge !== edit._gm0 || edit.gebinde_einheit !== edit._ge0)) {
        const gm = edit.gebinde_menge === '' ? null : Number(edit.gebinde_menge)
        await api.zutatGebinde(edit.zutat_id, gm, gm == null ? null : (edit.gebinde_einheit || 'g'))
      }
      setEdit(null); lade(); notify('Aktualisiert')
    } catch { notify('Aktualisieren fehlgeschlagen', 'err') }
  }

  async function loeschen(id) {
    try { await api.vorratLoeschen(id); setItems((p) => p.filter((x) => x.id !== id)) }
    catch { notify('Löschen fehlgeschlagen', 'err') }
  }

  function startEdit(it) {
    const z = byId[it.zutat_id] || {}
    setEdit({
      ...it,
      ablaufdatum: it.ablaufdatum || '',
      lagerort_id: it.lagerort_id ?? '',
      gebinde_menge: z.gebinde_menge ?? '',
      gebinde_einheit: z.gebinde_einheit ?? '',
      _gm0: z.gebinde_menge ?? '',
      _ge0: z.gebinde_einheit ?? '',
    })
  }

  function toggleOffen(key) {
    setOffen((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  }

  // Filter
  const sucheck = suche.toLowerCase()
  const matchSuche = (it) => {
    if (!suche) return true
    const zn = (it.zutat || '').toLowerCase()
    return zn.includes(sucheck) || sucheck.includes(zn)
  }
  const matchMhd = (it) => {
    if (fMhd === 'alle') return true
    if (fMhd === 'ohne') return !it.ablaufdatum
    const t = tageBis(it.ablaufdatum)
    if (t === null) return false
    if (fMhd === 'ueber') return t < 0        // überschritten
    if (fMhd === '3') return t <= 3           // innerhalb 3 Tage (inkl. überschritten)
    if (fMhd === '7') return t <= 7           // innerhalb 1 Woche
    if (fMhd === '28') return t <= 28         // innerhalb 4 Wochen
    return true
  }
  const matchOrt = (it) => {
    if (fOrt === 'alle') return true
    if (fOrt === 'kein') return !it.lagerort_id
    return it.lagerort_id === fOrt
  }

  const gefiltert = items.filter((it) => matchSuche(it) && matchMhd(it) && matchOrt(it))
  const istGruppiert = !suche  // bei Suche flach, sonst nach Master gruppieren

  // Master-IDs, die untergeordnete Zutaten haben (= echte Master mit Kindern)
  const kinderMasterIds = useMemo(() => {
    const s = new Set()
    for (const z of zutaten) if (z.kanonische_zutat_id != null) s.add(z.kanonische_zutat_id)
    return s
  }, [zutaten])

  // Gruppen nach Master-Zutat; eigenständige Artikel (kein Master, keine Kinder) -> "Ungruppiert"
  const gruppen = useMemo(() => {
    if (!istGruppiert) return []
    const map = new Map()
    const ungruppiert = { key: '__u__', mid: null, name: 'Ungruppiert', items: [], ungrouped: true }
    for (const it of gefiltert) {
      const mid = masterOf(it.zutat_id)
      const istMaster = mid !== it.zutat_id || kinderMasterIds.has(it.zutat_id)
      if (!istMaster) { ungruppiert.items.push(it); continue }
      const key = String(mid)
      if (!map.has(key)) map.set(key, { key, mid, name: masterName(mid, it.zutat), items: [] })
      map.get(key).items.push(it)
    }
    // Summe pro Einheiten-Klasse (g/ml via Gebinde umgerechnet, Rest separat)
    const sumString = (its) => {
      const s = {}
      for (const it of its) {
        const z = byId[it.zutat_id]
        const [klasse, basis] = basisMitGebinde(it.menge, it.einheit, z?.gebinde_menge, z?.gebinde_einheit)
        s[klasse] = (s[klasse] || 0) + basis
      }
      return Object.entries(s).map(([k, v]) => fmtMenge(k, v)).join(' · ')
    }
    const arr = [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'de'))
    for (const g of arr) g.summe = sumString(g.items)
    if (ungruppiert.items.length) {
      ungruppiert.items.sort((a, b) => (a.zutat || '').localeCompare(b.zutat || '', 'de'))
      arr.push(ungruppiert)
    }
    return arr
    // eslint-disable-next-line
  }, [gefiltert, istGruppiert, byId, kinderMasterIds])

  // Gruppierung nach Lagerort (alle Lagerorte zeigen, auch leere) + "ohne Lagerort".
  const lagerortGruppen = useMemo(() => {
    if (anzeige !== 'lagerorte') return []
    const byLo = new Map()
    for (const it of gefiltert) {
      const key = it.lagerort_id != null ? String(it.lagerort_id) : '__kein__'
      if (!byLo.has(key)) byLo.set(key, [])
      byLo.get(key).push(it)
    }
    const out = lagerorte.map((lo) => ({ key: 'lo' + lo.id, lo, name: lo.name, items: byLo.get(String(lo.id)) || [] }))
    if (byLo.has('__kein__')) out.push({ key: 'lo_kein', lo: null, name: 'ohne Lagerort', items: byLo.get('__kein__') })
    return out
  }, [anzeige, gefiltert, lagerorte])

  return (
    <div className="space-y-4">
      <div className="hero-card flex flex-wrap items-center justify-between gap-3 rounded-[22px] p-5">
        <div className="hero-glow" />
        <div className="relative min-w-0">
          <h2 className="font-dish text-3xl leading-tight text-ink">Vorrat</h2>
          <p className="label-mono mt-1.5 text-muted2">Bestand · Lagerorte · MHD</p>
        </div>
        <div className="relative flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setVerwalten(true)}><span className="inline-flex items-center gap-1"><Icon name="package" size={16} /> Lagerorte</span></Button>
          {ki.vision && <Button variant="kiGhost" onClick={() => startKamera('')} disabled={fotoBusy}>
            {fotoBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /><Icon name="camera" size={16} /> Erfassen</span>}
          </Button>}
          <Button onClick={() => { setForm(leer); setMehrfach(false); setAdd(true) }}>+ Hinzufügen</Button>
        </div>
      </div>

      {/* verstecktes Kamera-/Datei-Input für die Foto-KI-Erfassung */}
      <input ref={fotoRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={fotoGewaehlt} />

      {!loading && items.length > 0 && (
        <div className="space-y-2 rounded-2xl border border-line bg-card/60 p-3">
          <input
            className={input}
            placeholder="Suchen… (z.B. Öl findet Olivenöl)"
            value={suche}
            onChange={(e) => {
              const v = e.target.value
              setSuche(v)
              if (v) setAnzeige('zutaten')   // bei Suche automatisch in die Zutaten-Ansicht
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-16 shrink-0 label-mono font-bold text-muted2">Ansicht</span>
            <Chip active={anzeige === 'lagerorte'} onClick={() => setAnzeige('lagerorte')}>Nach Lagerort</Chip>
            <Chip active={anzeige === 'zutaten'} onClick={() => setAnzeige('zutaten')}>Zutaten</Chip>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-10 shrink-0 label-mono font-bold text-muted2">MHD</span>
            <Chip active={fMhd === 'alle'} onClick={() => setFMhd('alle')}>Alle</Chip>
            <Chip active={fMhd === 'ueber'} onClick={() => setFMhd('ueber')}>Überschritten</Chip>
            <Chip active={fMhd === '3'} onClick={() => setFMhd('3')}>3 Tage</Chip>
            <Chip active={fMhd === '7'} onClick={() => setFMhd('7')}>1 Woche</Chip>
            <Chip active={fMhd === '28'} onClick={() => setFMhd('28')}>4 Wochen</Chip>
            <Chip active={fMhd === 'ohne'} onClick={() => setFMhd('ohne')}>ohne MHD</Chip>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-20"><Spinner /></div>
      ) : items.length === 0 ? (
        <Empty>Vorrat ist leer. Füge etwas hinzu.</Empty>
      ) : anzeige === 'lagerorte' ? (
        <div className="space-y-2 stagger">
          {lagerortGruppen.map((g) => (
            <div key={g.key} className="overflow-hidden rounded-2xl border border-line">
              <div className="flex items-center justify-between gap-2 bg-card/80 px-4 py-3">
                <button onClick={() => toggleOffen(g.key)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                  <Icon name="package" size={18} className="text-ink/40" />
                  <span className="truncate font-semibold">{g.name}</span>
                  <span className="shrink-0 font-mono text-xs text-muted2">{g.items.length} Artikel</span>
                </button>
                <button onClick={() => toggleOffen(g.key)} className="shrink-0 px-1 text-base text-ink/55">{offen.has(g.key) ? '▼' : '▶'}</button>
              </div>
              {offen.has(g.key) && (
                <>
                  {g.lo && (
                    <div className="flex flex-wrap items-center gap-1.5 border-t border-line/50 bg-card/80 px-4 py-2">
                      <button title="Umbenennen"
                        onClick={() => { const n = window.prompt('Lagerort umbenennen:', g.lo.name); if (n && n.trim() && n.trim() !== g.lo.name) renameLagerort(g.lo.id, n.trim()) }}
                        className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-ink/60 hover:bg-line/30"><Icon name="pencil" size={16} /> Umbenennen</button>
                      {ki.vision && <>
                      <button title="Per Foto ergänzen" onClick={() => startKamera(g.lo.id)} disabled={fotoBusy}
                        className="inline-flex items-center gap-1 rounded-lg border border-terracotta/50 px-2 py-1 text-xs font-semibold text-terracotta hover:bg-terracotta/10 disabled:opacity-50"><Icon name="sparkles" size={16} /><Icon name="camera" size={16} /> ergänzen</button>
                      <button title="Per Foto neu erfassen (löscht vorhandene)" onClick={() => kameraNeuErfassen(g.lo)} disabled={fotoBusy}
                        className="inline-flex items-center gap-1 rounded-lg border border-terracotta/50 px-2 py-1 text-xs font-semibold text-terracotta hover:bg-terracotta/10 disabled:opacity-50"><Icon name="sparkles" size={16} /><Icon name="camera" size={16} /> neu erfassen</button>
                      </>}
                    </div>
                  )}
                  {g.items.length === 0
                    ? <p className="bg-paper/30 px-4 py-3 text-sm text-ink/45">{ki.vision
                        ? <>Noch nichts erfasst – „<Icon name="sparkles" size={16} className="inline align-text-bottom" /><Icon name="camera" size={16} className="inline align-text-bottom" /> ergänzen" zum Befüllen.</>
                        : 'Noch nichts erfasst – über „+ Hinzufügen" befüllen.'}</p>
                    : <div className="divide-y divide-line/50 bg-paper/30">{g.items.map((it) => <VorratZeile key={it.id} it={it} onEdit={startEdit} onLoeschen={loeschen} />)}</div>}
                </>
              )}
            </div>
          ))}
        </div>
      ) : istGruppiert ? (
        gruppen.length === 0 ? (
          <Empty>Keine Einträge für diesen Filter.</Empty>
        ) : (
          <div className="space-y-2 stagger">
            {gruppen.map((g) => {
              const auf = offen.has(g.key)
              return (
                <div key={g.key} className="overflow-hidden rounded-2xl border border-line">
                  <button
                    onClick={() => toggleOffen(g.key)}
                    className="flex w-full items-center justify-between gap-2 bg-card/80 px-4 py-3 text-left"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      {g.ungrouped && <span className="shrink-0 text-ink/40">▦</span>}
                      <span className="truncate font-semibold">{g.name}</span>
                      {!g.ungrouped && g.items.length > 1 && <span className="shrink-0 font-mono text-xs text-muted2">{g.items.length}×</span>}
                    </span>
                    <span className="flex shrink-0 items-center gap-2 font-mono text-xs text-muted">
                      {g.ungrouped ? `${g.items.length} Artikel` : (g.summe || `${g.items.length} Artikel`)}
                      <span className="text-base">{auf ? '▼' : '▶'}</span>
                    </span>
                  </button>
                  {auf && (
                    <div className="divide-y divide-line/50 bg-paper/30">
                      {g.items.map((it) => (
                        <VorratZeile key={it.id} it={it} onEdit={startEdit} onLoeschen={loeschen} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      ) : (
        gefiltert.length === 0 ? (
          <Empty>Keine Treffer für diesen Filter.</Empty>
        ) : (
          <div className="space-y-2 stagger">
            {gefiltert.map((it) => (
              <Card key={it.id} className="p-0">
                <VorratZeile it={it} onEdit={startEdit} onLoeschen={loeschen} />
              </Card>
            ))}
          </div>
        )
      )}

      {/* Modal: Neu */}
      <Modal open={add} onClose={schliesseAdd} title={mehrfach ? 'Bereich neu erfassen' : 'Zum Vorrat hinzufügen'}>
        <div className="space-y-3">
          {mehrfach && (
            <div className="rounded-xl bg-olive/10 p-3 text-sm">
              <p className="inline-flex items-center gap-1 font-semibold text-olive"><Icon name="package" size={16} className="text-olive" /> {lagerorte.find((l) => String(l.id) === String(form.lagerort_id))?.name || 'Lagerort'} neu erfassen</p>
              <p className="mt-0.5 text-ink/60">Artikel nacheinander erfassen – „+ Hinzufügen" speichert und lässt das Fenster offen, der Ort bleibt gesetzt. „Fertig" beendet.</p>
            </div>
          )}
          <Field label="Name"><input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Menge"><input className={input} type="number" value={form.menge} onChange={(e) => setForm({ ...form, menge: e.target.value })} /></Field>
            <Field label="Einheit"><input className={input} placeholder="g, ml, Stück, Packung" value={form.einheit} onChange={(e) => setForm({ ...form, einheit: e.target.value })} /></Field>
          </div>
          <Field label="Ablaufdatum (MHD)"><input className={input} type="date" value={form.ablaufdatum} onChange={(e) => setForm({ ...form, ablaufdatum: e.target.value })} /></Field>
          <Field label="Lagerort">
            <LagerortFeld lagerorte={lagerorte} value={form.lagerort_id} onChange={(v) => setForm({ ...form, lagerort_id: v })} onCreate={neuerLagerort} />
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={schliesseAdd}>{mehrfach ? 'Fertig' : 'Abbrechen'}</Button>
            <Button onClick={speichernNeu}>{mehrfach ? '+ Hinzufügen' : 'Speichern'}</Button>
          </div>
        </div>
      </Modal>

      {/* Modal: Foto-Erfassung – erkannte Artikel prüfen */}
      <Modal open={!!vorschlag} onClose={() => setVorschlag(null)} title="Erkannte Artikel">
        {vorschlag && (
          <div className="space-y-3">
            <Field label="Lagerort für diese Artikel">
              <LagerortFeld lagerorte={lagerorte} value={vorschlag.ort} onChange={(v) => setVorschlag((s) => s && ({ ...s, ort: v }))} onCreate={neuerLagerort} />
            </Field>
            <div className="space-y-2">
              {vorschlag.items.map((g, i) => (
                <div key={i} className={`rounded-xl border p-2.5 ${g.sel ? 'border-terracotta/40 bg-terracotta/5' : 'border-line opacity-60'}`}>
                  <div className="flex items-center gap-2">
                    <input type="checkbox" checked={g.sel} onChange={(e) => setVorschlagItem(i, { sel: e.target.checked })} className="h-4 w-4 accent-terracotta" />
                    <input className={input} value={g.name} placeholder="Name" onChange={(e) => setVorschlagItem(i, { name: e.target.value })} />
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <input className={input} type="number" placeholder="Menge" value={g.menge} onChange={(e) => setVorschlagItem(i, { menge: e.target.value })} />
                    <input className={input} placeholder="Einheit" value={g.einheit} onChange={(e) => setVorschlagItem(i, { einheit: e.target.value })} />
                    <input className={input} type="date" value={g.ablaufdatum} onChange={(e) => setVorschlagItem(i, { ablaufdatum: e.target.value })} />
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setVorschlag(null)}>Abbrechen</Button>
              <Button variant="ki" onClick={vorschlagSpeichern} disabled={vorschlagBusy}>
                {vorschlagBusy ? <Spinner /> : `${vorschlag.items.filter((g) => g.sel).length} übernehmen`}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal: Lagerorte verwalten */}
      <Modal open={verwalten} onClose={() => setVerwalten(false)} title="Lagerorte verwalten">
        <div className="space-y-2">
          {lagerorte.length === 0 ? (
            <Empty>Noch keine Lagerorte. Lege einen beim Hinzufügen eines Artikels an.</Empty>
          ) : (
            lagerorte.map((lo) => (
              <LagerortZeile
                key={lo.id}
                lo={lo}
                anzahl={items.filter((it) => it.lagerort_id === lo.id).length}
                onRename={(name) => renameLagerort(lo.id, name)}
                onDelete={() => deleteLagerort(lo)}
                onNeuErfassen={() => neuErfassen(lo)}
              />
            ))
          )}
          <p className="pt-1 text-xs text-ink/45">
            <b>Neu erfassen</b> löscht alle Artikel des Orts und öffnet die Erfassung. <b>Löschen</b> entfernt nur den Ort – die Artikel bleiben (dann ohne Ort).
          </p>
        </div>
      </Modal>

      {/* Modal: Bearbeiten */}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit ? `„${edit.zutat}" bearbeiten` : ''}>
        {edit && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Menge"><input className={input} type="number" value={edit.menge} onChange={(e) => setEdit({ ...edit, menge: e.target.value })} /></Field>
              <Field label="Einheit"><input className={input} value={edit.einheit} onChange={(e) => setEdit({ ...edit, einheit: e.target.value })} /></Field>
            </div>
            <Field label="Ablaufdatum (MHD)"><input className={input} type="date" value={edit.ablaufdatum} onChange={(e) => setEdit({ ...edit, ablaufdatum: e.target.value })} /></Field>
            <Field label="Lagerort">
              <LagerortFeld lagerorte={lagerorte} value={edit.lagerort_id} onChange={(v) => setEdit({ ...edit, lagerort_id: v })} onCreate={neuerLagerort} />
            </Field>
            <div className="rounded-xl border border-line/70 bg-paper/40 p-3">
              <p className="mb-2 label-mono font-bold text-muted2">Inhalt je {edit.einheit || 'Gebinde'} (für Mengen-Abgleich)</p>
              <div className="flex items-center gap-2">
                <input className={input + ' !w-24'} type="number" placeholder="z.B. 250" value={edit.gebinde_menge}
                  onChange={(e) => setEdit({ ...edit, gebinde_menge: e.target.value })} />
                <select className={input + ' !w-24'} value={edit.gebinde_einheit || ''}
                  onChange={(e) => setEdit({ ...edit, gebinde_einheit: e.target.value })}>
                  <option value="">—</option>
                  <option value="g">g</option>
                  <option value="ml">ml</option>
                </select>
                <span className="text-xs text-ink/50">leer = aus</span>
              </div>
              <p className="mt-1.5 text-xs text-ink/45">z.B. „1 Packung = 250 g" — dann zählt eine Packung im Rezept als 250 g.</p>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setEdit(null)}>Abbrechen</Button>
              <Button onClick={speichernEdit}>Speichern</Button>
            </div>
          </div>
        )}
      </Modal>

    </div>
  )
}
