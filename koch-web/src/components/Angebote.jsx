import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Spinner, Empty, Modal, Button, input, confirmDialog } from '../ui.jsx'
import { isoHeute } from '../utils.js'
import { Generator } from './Start.jsx'
import { Icon } from '../icons.jsx'

function fmtPreis(p) {
  if (p == null) return null
  return Number(p).toFixed(2).replace('.', ',') + ' €'
}
function fmtDatum(iso) {
  if (!iso) return ''
  return new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', { day: 'numeric', month: 'short' })
}
function fmtTag(iso) {
  if (!iso) return ''
  return new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })
}

// Übersicht der aktuellen UND kommenden Angebote: je Händler → Gültigkeit →
// Kategorie → Name, in aufklappbaren Kategorie-Gruppen.
export default function Angebote({ notify, auth, openRezept }) {
  const [genFuer, setGenFuer] = useState(null)   // Artikel -> Rezept mit Pflichtzutat erstellen
  const isAdmin = auth?.user?.plattform_rolle === 'super_admin'
  const darfUpload = isAdmin || !!auth?.user?.darf_angebote_upload
  const [angebote, setAngebote] = useState(null)
  const [suche, setSuche] = useState('')                // Volltextsuche über die Angebote
  const [offen, setOffen] = useState(() => new Set())   // aufgeklappte "markt|kategorie" (Default: zu)
  const [periodenZu, setPeriodenZu] = useState(() => new Set())   // eingeklappte Perioden
  const [marktAuf, setMarktAuf] = useState(() => new Set())   // aufgeklappte Händler (Default: zu)
  const [imWagen, setImWagen] = useState(() => new Set())   // schon in den Warenkorb gelegte Angebots-ids
  const [dialog, setDialog] = useState(null)            // {a, menge, einheit} – Mengen-Popup
  const [busy, setBusy] = useState(false)
  const [imp, setImp] = useState(null)                  // Modal offen? {phase:'form'|'progress', file, rf}
  const [job, setJob] = useState(null)                  // Live-Status des laufenden Imports
  const [jobId, setJobId] = useState(null)
  const [uploadPct, setUploadPct] = useState(0)
  const [setup, setSetup] = useState(null)        // {markt, von, bis} – Optionen vor dem Upload
  const fileRef = useRef(null)
  const queueRef = useRef(null)                   // {files, index, manuell} – Mehrfach-Upload
  // F18: genau EINE Poll-Kette. Timer + aktive Job-ID in Refs; bei Unmount abbrechen,
  // damit nach Tab-Wechsel/Remount keine zweite Kette für denselben Job startet.
  const pollTimerRef = useRef(null)
  const pollingJidRef = useRef(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (pollTimerRef.current) { clearTimeout(pollTimerRef.current); pollTimerRef.current = null }
    }
  }, [])

  function scheduleNext(jid, delay) {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    pollTimerRef.current = setTimeout(() => { pollTimerRef.current = null; pollStatus(jid) }, delay)
  }

  function lade() {
    return api.angeboteUebersicht()
      .then((a) => setAngebote(a || []))
      .catch(() => { setAngebote([]); notify && notify('Angebote laden fehlgeschlagen', 'err') })
  }

  useEffect(() => { lade() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Nur ein Markt vorhanden -> automatisch aufklappen (kein unnötiger Klick).
  useEffect(() => {
    if (!angebote || angebote.length === 0) return
    const maerkte = [...new Set(angebote.map((a) => (a.haendler || '').trim() || 'Ohne Markt'))]
    if (maerkte.length === 1) setMarktAuf((prev) => (prev.size ? prev : new Set(maerkte)))
  }, [angebote])

  function toggle(key) {
    setOffen((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  }
  function togglePeriode(key) {
    setPeriodenZu((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  }
  function toggleMarkt(key) {
    setMarktAuf((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  }

  function oeffneMenge(a) {
    // Offer-einheit ist eine Preis-Referenz (z.B. "100 g", "250-g-Becher") – nicht
    // als Mengen-Einheit vorbelegen. Menge sinnvoll mit 1 vorbelegen.
    setDialog({ a, menge: '1', einheit: '' })
  }

  // Löschbar: eigene Angebote (account_id gesetzt) oder Super-Admin (auch globale).
  const loeschbar = (a) => isAdmin || a.account_id != null
  async function loeschen(a) {
    if (!(await confirmDialog(`„${a.name}" löschen?`))) return
    try { await api.angebotLoeschen(a.id); notify && notify('Angebot gelöscht'); lade() }
    catch { notify && notify('Löschen fehlgeschlagen', 'err') }
  }

  // Ganzes Angebotsblatt (Markt + Zeitraum) löschen.
  async function blattLoeschen(haendler, von, bis, anzahl) {
    const ok = await confirmDialog({
      title: 'Angebotsblatt löschen',
      message: `Das komplette Blatt „${haendler || 'Ohne Markt'}" (${fmtDatum(von)}–${fmtDatum(bis)}) mit ${anzahl} Angebot${anzahl === 1 ? '' : 'en'} unwiderruflich löschen?`,
      confirmLabel: 'Blatt löschen', variant: 'primary',
    })
    if (!ok) return
    try {
      const r = await api.angeboteBlattLoeschen(haendler, von, bis)
      notify && notify(`${r.geloescht} Angebote gelöscht`)
      lade()
    } catch { notify && notify('Löschen fehlgeschlagen', 'err') }
  }

  async function bestaetigen() {
    if (!dialog) return
    const item = { name: dialog.a.name }
    const m = String(dialog.menge).trim()
    if (m) item.menge = Number(m.replace(',', '.'))
    if (dialog.einheit.trim()) item.einheit = dialog.einheit.trim()
    setBusy(true)
    try {
      await api.einkaufExtraHinzufuegen([item])
      if (dialog.a.id != null) setImWagen((prev) => new Set(prev).add(dialog.a.id))
      notify && notify(`„${dialog.a.name}" im Warenkorb`)
      setDialog(null)
    } catch {
      notify && notify('Hinzufügen fehlgeschlagen', 'err')
    } finally {
      setBusy(false)
    }
  }

  const JOB_KEY = 'angebote_import_job'

  // Nach einem Reload an einen noch laufenden Job wieder andocken.
  useEffect(() => {
    const jid = (() => { try { return localStorage.getItem(JOB_KEY) } catch { return null } })()
    if (!jid) return
    api.angeboteImportStatus(jid).then((j) => {
      if (!j || j.status === 'fertig' || j.status === 'fehler' || j.status === 'limit') {
        try { localStorage.removeItem(JOB_KEY) } catch { /* ignore */ }
        return
      }
      setJobId(jid); setJob(j); pollStatus(jid)
    }).catch(() => { try { localStorage.removeItem(JOB_KEY) } catch { /* ignore */ } })
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  function schliesseImport() { setImp(null) }  // Job läuft weiter; Banner bleibt sichtbar

  // Live-Text/Prozent zum aktuellen Job (für Banner und Modal).
  function statusText() {
    if (!job) return ''
    const b = batchInfo()
    const pre = b ? `Datei ${b.i}/${b.n} · ` : ''
    if (job.status === 'upload') return `${pre}Datei wird hochgeladen … ${uploadPct}%`
    if (job.status === 'fertig') return `${job.importiert} Angebote importiert${job.markt ? ' · ' + job.markt : ''}`
    if (job.status === 'fehler') return 'Fehler: ' + (job.error || 'unbekannt')
    if (job.status === 'limit') return 'KI-Limit erreicht – Import pausiert'
    if (job.status === 'rueckfrage') return `Markt/Zeitraum nicht erkannt – Eingabe nötig (${job.gefunden} Angebote)`
    if (job.phase === 'rendern') return `${pre}PDF wird gerendert …`
    if (job.phase === 'erkennen') return `${pre}Seite ${job.seite}/${job.seiten} wird gelesen … (${job.gefunden} Angebote)`
    if (job.phase === 'import') return `${pre}Angebote werden gespeichert …`
    return `${pre}Verarbeitung startet …`
  }
  function statusPct() {
    if (!job) return 0
    if (job.status === 'upload') return uploadPct
    if (job.status === 'fertig' || job.status === 'fehler' || job.status === 'limit') return 100
    if (job.phase === 'rendern') return 8
    if (job.phase === 'erkennen') return job.seiten ? Math.round((job.seite / job.seiten) * 100) : 30
    if (job.phase === 'import') return 96
    return 3
  }

  function starteBatch(files) {
    // PDFs dürfen größer sein (50 MB) – der Server rechnet sie ohnehin seitenweise klein;
    // Fotos/Bilder bleiben bei 20 MB.
    const istPdf = (f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf'
    const maxFuer = (f) => (istPdf(f) ? 50 : 20) * 1024 * 1024
    const zuGross = files.filter((f) => f.size > maxFuer(f))
    const ok = files.filter((f) => f.size <= maxFuer(f))
    if (zuGross.length) {
      notify && notify(`${zuGross.length} Datei(en) zu groß übersprungen – PDF max. 50 MB, Bilder max. 20 MB.`, 'err')
    }
    if (!ok.length) { setSetup(null); return }
    const m = setup || {}
    queueRef.current = { files: ok, index: 0, manuell: { markt: m.markt || '', von: m.von || '', bis: m.bis || '', bilder: false } }
    setSetup(null)
    setImp({ phase: 'progress' })
    startImport(ok[0])
  }

  function batchInfo() {
    const q = queueRef.current
    return q && q.files.length > 1 ? { i: q.index + 1, n: q.files.length } : null
  }

  function naechsteDatei() {
    const q = queueRef.current
    if (q && q.index + 1 < q.files.length) {
      q.index += 1
      startImport(q.files[q.index])
      return true
    }
    return false
  }

  async function startImport(file) {
    if (!file) return
    const m = (queueRef.current && queueRef.current.manuell) || {}
    setImp((s) => (s ? { ...s, phase: 'progress' } : { phase: 'progress', rf: null }))
    setJob({ status: 'upload' }); setUploadPct(0)
    try {
      const res = await api.angeboteImportDatei(file, m.markt || '', m.von || '', m.bis || '', (pct) => setUploadPct(pct), false)
      if (!res?.job_id) throw new Error('keine Job-ID')
      try { localStorage.setItem(JOB_KEY, res.job_id) } catch { /* ignore */ }
      setJobId(res.job_id)
      setJob({ status: 'verarbeitung', phase: 'warten', seite: 0, seiten: 0, gefunden: 0 })
      pollStatus(res.job_id)
    } catch {
      notify('Upload fehlgeschlagen', 'err')
      if (!naechsteDatei()) setJob(null)
    }
  }

  function pollStatus(jid) {
    pollingJidRef.current = jid   // F18: diese jid ist jetzt die aktive Kette
    api.angeboteImportStatus(jid).then((j) => {
      // Veraltete Antwort (Unmount oder inzwischen andere jid aktiv) verwerfen.
      if (!mountedRef.current || pollingJidRef.current !== jid) return
      setJob(j)
      if (j.status === 'rueckfrage') {
        setImp((s) => (s && !s.rf
          ? { ...s, rf: { markt: j.vorschlag?.markt || '', von: j.vorschlag?.gueltig_von || '', bis: j.vorschlag?.gueltig_bis || '' } }
          : s))
        return  // warten auf Nutzereingabe (Kette pausiert)
      }
      if (j.status === 'limit') {
        // KI-Limit erreicht → globalen LimitDialog (PAYG/Upgrade) zeigen, Batch stoppen.
        pollingJidRef.current = null
        try { localStorage.removeItem(JOB_KEY) } catch { /* ignore */ }
        try { if (j.limit) window.dispatchEvent(new CustomEvent('koch:limit', { detail: j.limit })) } catch { /* ignore */ }
        notify('KI-Limit erreicht – Import pausiert.', 'err')
        queueRef.current = null
        setTimeout(() => setJob((x) => (x && x.status === 'limit' ? null : x)), 8000)
        return
      }
      if (j.status === 'fertig') {
        pollingJidRef.current = null
        try { localStorage.removeItem(JOB_KEY) } catch { /* ignore */ }
        notify(`${j.importiert} Angebote importiert`)
        lade()
        if (!naechsteDatei()) setTimeout(() => setJob((x) => (x && x.status === 'fertig' ? null : x)), 5000)
      } else if (j.status === 'fehler') {
        pollingJidRef.current = null
        try { localStorage.removeItem(JOB_KEY) } catch { /* ignore */ }
        notify('Import fehlgeschlagen', 'err')
        if (!naechsteDatei()) setTimeout(() => setJob((x) => (x && x.status === 'fehler' ? null : x)), 8000)
      } else {
        scheduleNext(jid, 1500)
      }
    }).catch(() => {
      if (mountedRef.current && pollingJidRef.current === jid) scheduleNext(jid, 2500)
    })
  }

  async function importAbschliessen() {
    if (!jobId || !imp?.rf) return
    setJob((j) => ({ ...(j || {}), status: 'verarbeitung', phase: 'import' }))
    try {
      await api.angeboteImportFortsetzen(jobId, { haendler: imp.rf.markt, gueltig_von: imp.rf.von, gueltig_bis: imp.rf.bis })
      pollStatus(jobId)
    } catch {
      notify('Abschluss fehlgeschlagen', 'err')
    }
  }

  const heute = isoHeute()

  // Volltextsuche (Name, Beschreibung, Kategorie, Markt, Master-Zutat) + nach Markt gruppieren.
  const sucheLc = suche.trim().toLowerCase()
  const angeboteGefiltert = (angebote || []).filter((a) =>
    !sucheLc || [a.name, a.beschreibung, a.kategorie, a.haendler, a.master_zutat_name]
      .some((f) => (f || '').toLowerCase().includes(sucheLc)))
  const maerkte = {}
  for (const a of angeboteGefiltert) {
    const markt = (a.haendler || '').trim() || 'Ohne Markt'
    ;(maerkte[markt] ||= []).push(a)
  }
  // Märkte nach frühestem Startdatum (laufende zuerst).
  const marktListe = Object.entries(maerkte).sort((x, y) => {
    const vx = x[1].reduce((m, a) => (a.gueltig_von < m ? a.gueltig_von : m), '9999')
    const vy = y[1].reduce((m, a) => (a.gueltig_von < m ? a.gueltig_von : m), '9999')
    return vx.localeCompare(vy)
  })

  return (
    <>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-x-2 gap-y-3">
      <h2 className="font-display text-3xl">Angebote</h2>
      {darfUpload && <Button variant="ki" onClick={() => setSetup({ markt: '', von: '', bis: '' })}>+ Prospekt importieren</Button>}
    </div>
    {angebote && angebote.length > 0 && (
      <div className="mb-4">
        <input
          className={input}
          placeholder="Angebote durchsuchen… (Name, Markt, Kategorie)"
          value={suche}
          onChange={(e) => setSuche(e.target.value)}
        />
        {sucheLc && (
          <p className="mt-1 px-1 font-mono text-xs text-muted2">{angeboteGefiltert.length} Treffer für „{suche.trim()}"</p>
        )}
      </div>
    )}
    <input
      ref={fileRef}
      type="file"
      accept="image/*,application/pdf,application/json,.json"
      multiple
      className="hidden"
      onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ''; if (fs.length) starteBatch(fs) }}
    />

    {/* Persistenter Live-Hinweis zum laufenden Import (bleibt bis fertig) */}
    {job && !imp && (
      <button
        onClick={() => setImp({ phase: 'progress', rf: job.status === 'rueckfrage' ? { markt: job.vorschlag?.markt || '', von: job.vorschlag?.gueltig_von || '', bis: job.vorschlag?.gueltig_bis || '' } : null })}
        className={`mb-4 flex w-full items-center gap-3 rounded-xl border p-3 text-left text-sm ${
          job.status === 'fehler' || job.status === 'limit' ? 'border-terracotta/40 bg-terracotta/10 text-terracotta-deep'
            : job.status === 'fertig' ? 'border-olive/40 bg-olive/10 text-olive'
            : job.status === 'rueckfrage' ? 'border-line bg-surface text-muted2'
            : 'border-olive/30 bg-olive/10 text-olive'}`}
      >
        {job.status !== 'fertig' && job.status !== 'fehler' && job.status !== 'rueckfrage' && job.status !== 'limit' && <Spinner />}
        <span className="flex-1 inline-flex items-center gap-1 font-semibold"><Icon name="file-text" size={16} /> {statusText()}</span>
        {job.status === 'rueckfrage' ? <span className="text-xs underline">öffnen</span>
          : (job.status !== 'fertig' && job.status !== 'fehler' && job.status !== 'limit') ? <span className="text-xs opacity-70">{statusPct()}%</span> : null}
      </button>
    )}

    {angebote === null ? (
      <div className="flex justify-center py-10"><Spinner /></div>
    ) : angebote.length === 0 ? (
      <Empty>Keine aktuellen oder kommenden Angebote. Importiere oben einen Prospekt (Foto/PDF) – oder über den Assistenten.</Empty>
    ) : (
    <div className="space-y-8">
      {marktListe.map(([markt, items]) => {
        const perioden = [...new Set(items.map((a) => a.gueltig_von + '|' + a.gueltig_bis))]
          .map((k) => {
            const [von, bis] = k.split('|')
            return { von, bis, items: items.filter((a) => a.gueltig_von === von && a.gueltig_bis === bis) }
          })
          .sort((p, q) => {
            const pa = p.von <= heute && p.bis >= heute, qa = q.von <= heute && q.bis >= heute
            if (pa !== qa) return pa ? -1 : 1
            return p.von.localeCompare(q.von) || p.bis.localeCompare(q.bis)
          })
        return (
        <div key={markt}>
          <button onClick={() => toggleMarkt(markt)} className="mb-3 flex w-full items-center gap-2.5 rounded-2xl border border-line bg-card px-4 py-3 text-left shadow-soft transition hover:border-terracotta/40 active:scale-[0.99]">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-terracotta/12 text-terracotta"><Icon name="store" size={18} /></span>
            <span className="font-display text-xl">{markt}</span>
            <span className="ml-auto flex items-center gap-2 font-mono text-xs text-muted2">
              {items.length} Angebote
              <Icon name="chevron-right" size={18} className={`transition-transform ${marktAuf.has(markt) ? 'rotate-90' : ''}`} />
            </span>
          </button>

          {(sucheLc || marktAuf.has(markt)) && (
          <div className="space-y-5">
            {perioden.map(({ von, bis, items: pItems }) => {
              const aktivP = von <= heute && bis >= heute
              const kats = [...new Set(pItems.map((a) => (a.kategorie || 'Sonstiges').trim() || 'Sonstiges'))]
                .sort((a, b) => a.localeCompare(b, 'de'))
              const pkey = markt + '|p|' + von + bis
              const pZu = !sucheLc && periodenZu.has(pkey)
              return (
              <div key={von + bis}>
                <div className="mb-2 flex items-center gap-2">
                  <button onClick={() => togglePeriode(pkey)} className="flex flex-1 items-center gap-2 text-left">
                    <h3 className="inline-flex items-center gap-1 font-mono text-xs font-bold text-terracotta"><Icon name="calendar" size={16} className="text-terracotta" /> {fmtDatum(von)}–{fmtDatum(bis)}</h3>
                    <span className={`label-mono rounded-full px-1.5 py-0.5 ${aktivP ? 'bg-olive/15 text-olive' : 'bg-surface text-muted2'}`}>{aktivP ? 'läuft' : 'ab ' + fmtTag(von)}</span>
                    <span className="ml-auto flex items-center gap-2 font-mono text-xs text-muted2">{pItems.length}<Icon name="chevron-right" size={15} className={`transition-transform ${pZu ? '' : 'rotate-90'}`} /></span>
                  </button>
                  {loeschbar(pItems[0]) && (
                    <button onClick={() => blattLoeschen(pItems[0].haendler, von, bis, pItems.length)}
                      title="Ganzes Angebotsblatt löschen"
                      className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-terracotta/40 px-2 py-1 text-xs font-semibold text-terracotta-deep transition hover:bg-terracotta/10"><Icon name="trash" size={16} /> Blatt</button>
                  )}
                </div>
                {!pZu && (
                <div className="space-y-2">
                  {kats.map((kat) => {
                    const inKat = pItems
                      .filter((a) => ((a.kategorie || 'Sonstiges').trim() || 'Sonstiges') === kat)
                      .sort((a, b) => a.name.localeCompare(b.name, 'de'))
                    const key = markt + '|' + von + bis + '|' + kat
              const auf = !!sucheLc || offen.has(key)
              return (
                <div key={kat} className="overflow-hidden rounded-2xl border border-line bg-card">
                  <button
                    onClick={() => toggle(key)}
                    className="flex w-full items-center justify-between gap-2 px-3.5 py-3 text-left transition hover:bg-terracotta/5"
                  >
                    <span className="label-mono font-bold text-muted2">{kat}</span>
                    <span className="flex items-center gap-2 font-mono text-xs text-muted2">
                      <span>{inKat.length}</span>
                      <Icon name="chevron-right" size={16} className={`transition-transform ${auf ? 'rotate-90' : ''}`} />
                    </span>
                  </button>
                  {auf && (
                    <ul className="space-y-2 border-t border-line/60 p-3">
                      {inKat.map((a) => {
                        const rabatt = a.preis_normal && a.preis_angebot
                          ? Math.round((1 - a.preis_angebot / a.preis_normal) * 100) : null
                        return (
                          <li key={a.id} className="rounded-xl border border-line bg-card p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex min-w-0 flex-1 items-start gap-2.5">
                                {a.bild && (
                                  <img src={a.bild} alt="" loading="lazy"
                                    className="h-12 w-12 shrink-0 rounded-lg border border-line bg-paper object-cover" />
                                )}
                                <div className="min-w-0">
                                  <p className="font-dish text-xl capitalize leading-tight">{a.name}</p>
                                  {a.master_zutat_name && (
                                    <p className="text-xs text-muted2">↔ {a.master_zutat_name}</p>
                                  )}
                                  {a.kategorie && <p className="mt-0.5 font-mono text-xs text-muted2">{a.kategorie}</p>}
                                </div>
                              </div>
                              <div className="flex shrink-0 flex-col items-end gap-1.5">
                                <div className="max-w-[7.5rem] text-right">
                                  {a.preis_angebot != null && (
                                    <p className="font-mono font-bold leading-tight text-terracotta">
                                      {fmtPreis(a.preis_angebot)}
                                      {a.einheit ? <span className="text-xs font-normal text-muted2"> / {a.einheit}</span> : null}
                                    </p>
                                  )}
                                  {a.preis_normal != null && a.preis_angebot != null && (
                                    <p className="font-mono text-xs text-muted2 line-through">{fmtPreis(a.preis_normal)}</p>
                                  )}
                                  {rabatt ? <span className="mt-0.5 inline-block rounded bg-terracotta/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-terracotta-deep">−{rabatt}%</span> : null}
                                </div>
                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={() => oeffneMenge(a)}
                                    title={imWagen.has(a.id) ? 'Schon im Warenkorb – nochmal hinzufügen?' : 'In den Warenkorb'}
                                    className={`shrink-0 rounded-lg border px-2 py-1.5 text-sm font-semibold leading-none transition ${imWagen.has(a.id) ? 'border-olive/50 bg-olive/10 text-olive' : 'border-terracotta/40 text-terracotta hover:bg-terracotta/10'}`}
                                  >
                                    {imWagen.has(a.id) ? <Icon name="check" size={16} /> : <Icon name="shopping-cart" size={16} />}
                                  </button>
                                  {loeschbar(a) && (
                                    <button
                                      onClick={() => loeschen(a)}
                                      title={a.account_id == null ? 'Globales Admin-Angebot löschen' : 'Eigenes Angebot löschen'}
                                      className="shrink-0 rounded-lg border border-line px-2 py-1.5 text-sm leading-none text-ink/40 transition hover:border-terracotta/40 hover:text-terracotta"
                                    >
                                      <Icon name="trash" size={16} />
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })}
                </div>
                )}
              </div>
              )
            })}
          </div>
          )}
        </div>
        )
      })}
    </div>
    )}

    {dialog && (
      <Modal open onClose={() => setDialog(null)} title={dialog.a.name}>
        <div className="space-y-4">
          <p className="text-sm text-ink/60">In welcher Menge auf die Einkaufsliste?</p>
          <div className="flex items-end gap-2">
            <label className="flex-1">
              <span className="mb-1 block text-xs font-semibold text-ink/55">Menge</span>
              <input
                className={input}
                autoFocus
                inputMode="decimal"
                value={dialog.menge}
                placeholder="1"
                onChange={(e) => setDialog((d) => ({ ...d, menge: e.target.value }))}
                onKeyDown={(e) => { if (e.key === 'Enter') bestaetigen() }}
              />
            </label>
            <label className="w-36">
              <span className="mb-1 block text-xs font-semibold text-ink/55">Einheit</span>
              <input
                className={input}
                value={dialog.einheit}
                placeholder="z.B. Stück, g, Packung"
                onChange={(e) => setDialog((d) => ({ ...d, einheit: e.target.value }))}
              />
            </label>
          </div>
          {(dialog.a.preis_angebot != null || dialog.a.einheit) && (
            <p className="inline-flex items-center gap-1 text-xs text-ink/45">
              <Icon name="tag" size={16} /> Angebot{dialog.a.preis_angebot != null ? ': ' + fmtPreis(dialog.a.preis_angebot) : ''}
              {dialog.a.einheit ? ' / ' + dialog.a.einheit : ''}
            </p>
          )}
          <Button variant="ki" className="w-full inline-flex items-center justify-center gap-1" onClick={() => { const a = dialog.a; setDialog(null); setGenFuer(a) }}>
            <Icon name="sparkles" size={16} /> Rezept mit diesem Artikel erstellen
          </Button>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setDialog(null)}>Abbrechen</Button>
            <Button onClick={bestaetigen} disabled={busy}>
              {busy ? <Spinner /> : 'Hinzufügen'}
            </Button>
          </div>
        </div>
      </Modal>
    )}

    {genFuer && (
      <Generator
        notify={notify}
        openRezept={openRezept || (() => {})}
        vorratAktiv
        initialWunsch={`Das Rezept muss „${genFuer.master_zutat_name || genFuer.name}" als Zutat enthalten (Pflichtzutat aus dem aktuellen Angebot).`}
        onClose={() => setGenFuer(null)}
      />
    )}

    {setup && (
      <Modal open onClose={() => setSetup(null)} title="Prospekt importieren">
        <div className="space-y-3">
          <p className="text-sm text-ink/60">
            Lade ein oder <b>mehrere</b> Prospekte hoch – als Foto, PDF oder JSON. Markt und Zeitraum
            erkennt die KI automatisch; du kannst sie optional vorgeben. Wochenend-Angebote werden
            trotzdem je Angebot erkannt.
          </p>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-ink/55">Markt (optional)</span>
            <input className={input} placeholder="z.B. Supermarkt Beispiel" value={setup.markt} onChange={(e) => setSetup((s) => ({ ...s, markt: e.target.value }))} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-ink/55">Gültig von (optional)</span>
              <input className={input} type="date" value={setup.von} onChange={(e) => setSetup((s) => ({ ...s, von: e.target.value }))} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-ink/55">Gültig bis (optional)</span>
              <input className={input} type="date" value={setup.bis} onChange={(e) => setSetup((s) => ({ ...s, bis: e.target.value }))} />
            </label>
          </div>
          <Button variant="ki" onClick={() => fileRef.current?.click()} className="w-full">Dateien wählen & importieren</Button>
          <p className="text-xs text-ink/45">Mehrfachauswahl möglich · Formate: Foto (JPG/PNG), PDF, JSON.</p>
        </div>
      </Modal>
    )}

    {imp && (() => {
      const laeuft = job && job.status !== 'fertig' && job.status !== 'fehler' && job.status !== 'rueckfrage'
      const onClose = () => {
        if (laeuft) notify('Import läuft im Hintergrund weiter – der Hinweis oben bleibt, bis er fertig ist.')
        schliesseImport()
      }
      const setRf = (patch) => setImp((s) => ({ ...s, rf: { ...s.rf, ...patch } }))
      const fertig = job?.status === 'fertig'
      const fehler = job?.status === 'fehler' || job?.status === 'limit'
      return (
      <Modal open onClose={onClose} title="Prospekt importieren">
        {job?.status === 'rueckfrage' ? (
          <div className="space-y-3">
            <div className="rounded-xl bg-surface p-3 text-sm">
              <p className="font-semibold">Markt/Zeitraum nicht automatisch erkannt</p>
              <p className="mt-0.5 text-ink/60">{job.gefunden} Angebote gefunden. Bitte ergänze die fehlenden Angaben – dann wird importiert.</p>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-ink/55">Markt</span>
              <input className={input} placeholder="z.B. Supermarkt Beispiel" value={imp.rf?.markt || ''} onChange={(e) => setRf({ markt: e.target.value })} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-ink/55">Gültig von</span>
                <input className={input} type="date" value={imp.rf?.von || ''} onChange={(e) => setRf({ von: e.target.value })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-ink/55">Gültig bis</span>
                <input className={input} type="date" value={imp.rf?.bis || ''} onChange={(e) => setRf({ bis: e.target.value })} />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={schliesseImport}>Später</Button>
              <Button onClick={importAbschliessen} disabled={!imp.rf?.markt?.trim() || !imp.rf?.von || !imp.rf?.bis}>Import abschließen</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <p className={`text-sm font-semibold ${fehler ? 'text-terracotta-deep' : fertig ? 'text-olive' : 'text-ink/70'}`}>{statusText()}</p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-line/50">
              <div className={`h-full transition-all ${fehler ? 'bg-terracotta' : fertig ? 'bg-olive' : 'bg-terracotta'}`} style={{ width: statusPct() + '%' }} />
            </div>
            {!fertig && !fehler && (
              <div className="flex items-center gap-2 rounded-xl bg-olive/10 p-3 text-sm text-olive">
                <Spinner />
                <span><b>Verarbeitung läuft im Hintergrund.</b> Du kannst das Fenster schließen oder die Seite neu laden – der Hinweis oben bleibt sichtbar, bis der Import fertig ist.</span>
              </div>
            )}
            {(fertig || fehler) && (
              <div className="flex justify-end">
                <Button onClick={schliesseImport}>Schließen</Button>
              </div>
            )}
          </div>
        )}
      </Modal>
      )
    })()}
    </>
  )
}
