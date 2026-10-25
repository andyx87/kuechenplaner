import { useEffect, useState, useCallback } from 'react'
import { api } from '../api.js'
import { Button, Field, input, Modal, Spinner, Empty, Chip, confirmDialog } from '../ui.jsx'
import { localIso, isoHeute, getMontag, addDays, istAnwesend, abwesenheitsLabel } from '../utils.js'
import { getVorratAktiv } from '../settings.js'
import { Icon } from '../icons.jsx'
import { RezeptDetailInhalt } from './RezeptDetail.jsx'
import Einkaufsliste from './Einkaufsliste.jsx'
import WochenWizard from './WochenWizard.jsx'
import { useKi } from '../kiStatus.js'
import { registerOverlay } from '../backnav.js'

const MAHLZEITEN = ['Frühstück', 'Mittag', 'Abendessen', 'Snack', 'Unterwegs']
const MAHLZEIT_ICON_NAME = {
  'Frühstück': 'sunrise', 'Mittag': 'sun', 'Abendessen': 'moon', 'Snack': 'apple', 'Unterwegs': 'backpack'
}
function MahlzeitIcon({ mahlzeit, size = 16 }) {
  const name = MAHLZEIT_ICON_NAME[mahlzeit]
  return name ? <Icon name={name} size={size} /> : null
}


function fmtDatum(iso) {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })
}

function fmtKW(iso) {
  const d = new Date(iso + 'T00:00:00')
  const jan4 = new Date(d.getFullYear(), 0, 4)
  const startOfWeek1 = new Date(jan4)
  startOfWeek1.setDate(jan4.getDate() - (jan4.getDay() || 7) + 1)
  const kw = Math.ceil(((d - startOfWeek1) / 86400000 + 1) / 7)
  return `KW ${kw}`
}

function fmtMonate(montagIso) {
  const d1 = new Date(montagIso + 'T00:00:00')
  const d2 = new Date(montagIso + 'T00:00:00')
  d2.setDate(d2.getDate() + 6)
  const m1 = d1.toLocaleDateString('de-DE', { day: 'numeric', month: 'short' })
  const m2 = d2.toLocaleDateString('de-DE', { day: 'numeric', month: 'short' })
  return `${m1} – ${m2}`
}

function fmt(m) {
  const n = Number(m)
  return Number.isInteger(n) ? n : Math.round(n * 100) / 100
}

// Gewünschte Portionen eines Slots: manuelles Override, sonst Summe der
// Portionsfaktoren der mitessenden Personen (+ Gäste, falls gesetzt).
function slotPortionen(e, personen) {
  if (!e) return 1
  const gaeste = Number(e.gaeste || 0)
  if (e.portionen != null && e.portionen !== '') return Number(e.portionen) + gaeste
  const ids = new Set((e.person_ids || []).map(Number))
  const sum = personen.filter((p) => ids.has(p.id)).reduce((s, p) => s + Number(p.portionsfaktor || 1), 0)
  const basis = sum > 0 ? sum : (e.person_ids?.length || 1)
  return basis + gaeste
}

const WOCHENTAG_KURZ = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

// Kompaktes Label für einen belegten Slot: "3 Personen +2"
function slotPersonenLabel(e) {
  const n = e.person_ids?.length || 0
  const g = Number(e.gaeste || 0)
  if (n === 0 && g === 0) return ''
  return `${n} Person${n !== 1 ? 'en' : ''}${g > 0 ? ` +${g}` : ''}`
}


// ── Slot-Editor (Popup) ────────────────────────────────────────────
function SlotEditor({ eintrag, datum, mahlzeit, personen, onClose, onSaved, onDeleted, notify, startPanel }) {
  const [rezeptSuche, setRezeptSuche] = useState('')
  const [suchErgebnisse, setSuchErgebnisse] = useState([])
  const [selectedRezept, setSelectedRezept] = useState(
    eintrag?.rezept_id ? { id: eintrag.rezept_id, name: eintrag.rezept_name } : null
  )
  const [rezDetail, setRezDetail] = useState(null)
  const [notiz, setNotiz] = useState(eintrag?.notiz || '')
  const verfuegbar = personen.filter((p) => istAnwesend(p, datum, mahlzeit))
  const [selPersonen, setSelPersonen] = useState(
    new Set(eintrag?.person_ids?.map(Number) || verfuegbar.map((p) => p.id))
  )
  const [gaeste, setGaeste] = useState(Number(eintrag?.gaeste || 0))
  // Override-Feld bewusst IMMER leer: sonst würde ein gespeicherter Portionswert
  // die Personen-Auswahl übersteuern. Manuelles Override gilt nur, wenn in dieser
  // Session aktiv eingetippt. Die Portionen ergeben sich sonst aus Personen + Gästen.
  const [portionenOverride, setPortionenOverride] = useState('')
  const [saving, setSaving] = useState(false)
  const [panel, setPanel] = useState(startPanel || (eintrag ? null : 'rezept')) // 'rezept' | 'personen' | null
  const [aendern, setAendern] = useState(false) // Suche/Wechsel-Bereich im Rezept-Panel offen?

  // Rezept-Suche (debounced)
  useEffect(() => {
    if (!rezeptSuche.trim()) { setSuchErgebnisse([]); return }
    const t = setTimeout(async () => {
      try { setSuchErgebnisse(await api.rezepte(rezeptSuche)) } catch {}
    }, 300)
    return () => clearTimeout(t)
  }, [rezeptSuche])

  // Rezept-Details für die Vorschau laden
  useEffect(() => {
    if (!selectedRezept?.id) { setRezDetail(null); return }
    let ok = true
    api.rezept(selectedRezept.id).then((r) => { if (ok) setRezDetail(r) }).catch(() => {})
    return () => { ok = false }
  }, [selectedRezept?.id])

  function togglePerson(id) {
    setPortionenOverride('')  // zurück in den Auto-Modus
    setSelPersonen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const compPortionen =
    (portionenOverride ? Number(portionenOverride) : personen.filter((p) => selPersonen.has(p.id)).reduce((s, p) => s + Number(p.portionsfaktor), 0)) + gaeste
  const vorschauPortionen = Math.max(compPortionen, 1)
  const basis = rezDetail?.portionen || 1
  const faktor = basis ? vorschauPortionen / basis : 1

  async function speichern() {
    setSaving(true)
    const payload = {
      datum, mahlzeit,
      rezept_id: selectedRezept?.id || null,
      notiz: notiz.trim() || null,
      person_ids: [...selPersonen],
      portionen: portionenOverride ? Number(portionenOverride) : null,
      gaeste,
    }
    try {
      const res = eintrag?.id
        ? await api.planEintragUpdate(eintrag.id, payload)
        : await api.planEintragAnlegen(payload)
      onSaved({ ...res, rezept_name: selectedRezept?.name ?? res.rezept_name ?? null })
    } catch { setSaving(false); notify && notify('Speichern fehlgeschlagen', 'err') }
  }

  async function loeschen() {
    if (!eintrag?.id) return
    try { await api.planEintragLoeschen(eintrag.id); onDeleted(eintrag.id) }
    catch { notify && notify('Löschen fehlgeschlagen', 'err') }
  }

  const personenLabel =
    `${selPersonen.size} Person${selPersonen.size !== 1 ? 'en' : ''}` +
    (gaeste > 0 ? ` + ${gaeste} ${gaeste === 1 ? 'Gast' : 'Gäste'}` : '')

  return (
    <Modal open onClose={onClose} title={`${mahlzeit} – ${fmtDatum(datum)}`}>
      <div className="space-y-3">
      {/* Rezept / Freitext */}
      <div className="overflow-hidden rounded-lg border border-line bg-card">
        <button onClick={() => setPanel(panel === 'rezept' ? null : 'rezept')}
          className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left hover:bg-ink/5">
          <span className="flex min-w-0 items-center gap-2">
            <Icon name="chef-hat" size={16} />
            <span className="truncate font-semibold">{selectedRezept ? selectedRezept.name : (notiz || 'Rezept wählen')}</span>
          </span>
          <span className={`shrink-0 text-ink/40 transition ${panel === 'rezept' ? 'rotate-90' : ''}`}>›</span>
        </button>
        {panel === 'rezept' && (
          <div className="space-y-2 border-t border-line p-2.5">
            {/* Volle Rezept-Ansicht (wie in der Rezepte-Rubrik), skaliert auf die Slot-Portionen */}
            {selectedRezept && rezDetail && (
              <RezeptDetailInhalt detail={rezDetail} portionen={vorschauPortionen} notify={notify} />
            )}
            {/* Ändern / Wählen */}
            {(!selectedRezept || aendern) ? (
              <div className={`space-y-2 ${selectedRezept ? 'border-t border-line/60 pt-2' : ''}`}>
                <input className={input} placeholder="Rezept suchen…" value={rezeptSuche} onChange={(e) => setRezeptSuche(e.target.value)} />
                {suchErgebnisse.length > 0 && (
                  <div className="rounded-lg border border-line bg-card shadow-soft">
                    {suchErgebnisse.slice(0, 6).map((r) => (
                      <button key={r.id} onClick={() => { setSelectedRezept(r); setRezeptSuche(''); setSuchErgebnisse([]); setAendern(false) }}
                        className="block w-full px-3 py-2 text-left text-sm hover:bg-ink/5">{r.name}</button>
                    ))}
                  </div>
                )}
                <input className={input} value={notiz} onChange={(e) => setNotiz(e.target.value)}
                  placeholder={selectedRezept ? 'Notiz (optional)' : 'oder Freitext: „Schulkantine", „Reste"…'} />
                {selectedRezept && (
                  <button onClick={() => { setSelectedRezept(null); setRezDetail(null) }} className="inline-flex items-center gap-1 text-xs text-terracotta-deep hover:underline"><Icon name="x" size={16} /> Rezept entfernen</button>
                )}
              </div>
            ) : (
              <button onClick={() => setAendern(true)} className="text-xs font-semibold text-terracotta hover:underline">Rezept ändern / wechseln</button>
            )}
          </div>
        )}
      </div>

      {/* Wer isst mit + Gäste */}
      <div className="overflow-hidden rounded-lg border border-line bg-card">
        <button onClick={() => setPanel(panel === 'personen' ? null : 'personen')}
          className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left hover:bg-ink/5">
          <span className="flex min-w-0 items-center gap-2"><Icon name="users" size={16} /><span className="truncate font-semibold">{personenLabel}</span></span>
          <span className={`shrink-0 text-ink/40 transition ${panel === 'personen' ? 'rotate-90' : ''}`}>›</span>
        </button>
        {panel === 'personen' && (
          <div className="space-y-3 border-t border-line p-2.5">
            {personen.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {personen.map((p) => {
                  const sel = selPersonen.has(p.id)
                  const anwesend = istAnwesend(p, datum, mahlzeit)
                  return (
                    <button key={p.id} onClick={() => togglePerson(p.id)} title={!anwesend ? 'Laut Regelplan nicht zuhause' : undefined}
                      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm font-semibold transition ${sel ? 'border-terracotta bg-terracotta text-on-accent' : 'border-line bg-card text-ink/50'} ${!anwesend ? 'opacity-40' : ''}`}>
                      <Icon name={sel ? 'check' : 'circle'} size={16} /> {p.name}{!anwesend ? <Icon name="home" size={16} /> : null}
                    </button>
                  )
                })}
              </div>
            )}
            <div className="flex items-center justify-between rounded-lg bg-paper/60 px-3 py-2">
              <span className="inline-flex items-center gap-1 text-sm font-semibold"><Icon name="party-popper" size={16} /> Gäste</span>
              <div className="flex items-center gap-3">
                <button onClick={() => { setPortionenOverride(''); setGaeste((g) => Math.max(0, g - 1)) }} className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-lg leading-none hover:bg-ink/5">−</button>
                <span className="w-6 text-center font-semibold">{gaeste}</span>
                <button onClick={() => { setPortionenOverride(''); setGaeste((g) => g + 1) }} className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-lg leading-none hover:bg-ink/5">+</button>
              </div>
            </div>
            <p className="text-xs text-ink/45">Berechnete Portionen: {fmt(compPortionen)}{portionenOverride ? ` · überschrieben mit ${portionenOverride}` : ''}</p>
            <Field label="Portionen manuell (optional, überschreibt)">
              <input className={input} type="number" step="0.5" min="0.5" value={portionenOverride} placeholder={compPortionen > 0 ? `Auto: ${fmt(compPortionen)}` : ''} onChange={(e) => { const v = e.target.value; setPortionenOverride(v); if (v.trim() !== '') { setSelPersonen(new Set()); setGaeste(0) } }} />
            </Field>
          </div>
        )}
      </div>

      {/* Aktionen */}
      <div className="flex items-center justify-between pt-0.5">
        {eintrag?.id ? (
          <button onClick={loeschen} className="text-sm text-terracotta-deep hover:underline">Löschen</button>
        ) : <div />}
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button onClick={speichern} disabled={saving}>{saving ? '…' : 'Speichern'}</Button>
        </div>
      </div>
      </div>
    </Modal>
  )
}


// ── Haupt-Komponente ───────────────────────────────────────────────
export default function Planen({ notify, openRezept }) {
  const [montag, setMontag] = useState(() => getMontag(isoHeute()))
  const [plan, setPlan] = useState([])        // alle Einträge der Woche
  const [einkaufstage, setEinkaufstage] = useState(new Set())  // ISO-Datums-Strings
  const [einkaufsMarkt, setEinkaufsMarkt] = useState(new Map()) // datum -> [haendler]
  const [marktDialog, setMarktDialog] = useState(null)          // {datum, maerkte}
  const [marktAuswahl, setMarktAuswahl] = useState([])          // gewählte Händler im Dialog
  const vorratAktiv = getVorratAktiv()
  const [personen, setPersonen] = useState([])
  const [loading, setLoading] = useState(true)
  const [offenerSlot, setOffenerSlot] = useState(null) // {datum, mahlzeit, eintrag?, startPanel?} – Slot-Popup
  const [wizardOffen, setWizardOffen] = useState(false)
  const ki = useKi()
  const [fokusTag, setFokusTag] = useState(() => isoHeute()) // gewählter Tag
  const [tagansicht, setTagansicht] = useState(false)        // false = 8-Button-Übersicht, true = Tag bearbeiten

  // Browser-/Geräte-Zurück schließt die Tagesansicht (zurück zur Wochenübersicht),
  // statt die Rubrik/den Tab zu wechseln.
  useEffect(() => {
    if (!tagansicht) return
    const unregister = registerOverlay(() => setTagansicht(false))
    return () => unregister()
  }, [tagansicht])

  async function lade() {
    setLoading(true)
    try {
      const [p, et, pers] = await Promise.all([
        api.wochenplan(montag),
        api.einkaufstage(montag),
        api.personen(),
      ])
      setPlan(p)
      setEinkaufstage(new Set(et.map((e) => e.datum)))
      setEinkaufsMarkt(new Map(et.map((e) => [e.datum, e.haendler_liste || (e.haendler ? [e.haendler] : [])])))
      setPersonen(pers)
    } catch {
      notify('Wochenplan laden fehlgeschlagen', 'err')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { lade() /* eslint-disable-next-line */ }, [montag])

  async function inWarenkorb(e) {
    if (!e.rezept_id) return
    try {
      const res = await api.rezeptInWarenkorb(e.rezept_id)
      notify(`${res.hinzugefuegt} Zutat${res.hinzugefuegt === 1 ? '' : 'en'} im Warenkorb`)
      lade()
    } catch { notify('In den Warenkorb fehlgeschlagen', 'err') }
  }

  async function toggleEinkaufstag(datum) {
    try {
      const res = await api.einkauftagToggle(datum)
      setEinkaufstage((s) => {
        const n = new Set(s)
        res.action === 'added' ? n.add(datum) : n.delete(datum)
        return n
      })
      if (res.action === 'added') oeffneMarktDialog(datum)
      else setEinkaufsMarkt((m) => { const n = new Map(m); n.delete(datum); return n })
    } catch { notify('Fehler', 'err') }
  }

  async function oeffneMarktDialog(datum) {
    try {
      const maerkte = await api.angeboteMaerkte(datum)
      if (!maerkte || maerkte.length === 0) {
        notify('An diesem Tag liegen keine Angebote vor – kein Markt wählbar')
        return
      }
      setMarktAuswahl(einkaufsMarkt.get(datum) || [])
      setMarktDialog({ datum, maerkte })
    } catch { notify('Märkte laden fehlgeschlagen', 'err') }
  }

  const toggleMarkt = (h) => setMarktAuswahl((cur) => cur.includes(h) ? cur.filter((x) => x !== h) : [...cur, h])

  async function speichereMaerkte() {
    const { datum } = marktDialog
    try {
      await api.einkaufstagHaendler(datum, marktAuswahl)
      setEinkaufsMarkt((m) => { const n = new Map(m); n.set(datum, [...marktAuswahl]); return n })
      setMarktDialog(null)
      notify(marktAuswahl.length ? `Einkauf bei ${marktAuswahl.join(', ')}` : 'Märkte freigelassen')
    } catch { notify('Märkte setzen fehlgeschlagen', 'err') }
  }

  // (reaktiviereTag entfernt: war toter Code – nirgends aufgerufen und ans alte,
  //  täglich wandernde Schlüsselformat gebunden. Befund UX-Review 2026-07-26.)

  function wocheVor() { setMontag(addDays(montag, -7)) }
  function wocheNach() { setMontag(addDays(montag, 7)) }
  function wocheHeute() { setMontag(getMontag(isoHeute())) }
  // Fokus-Tag innerhalb der angezeigten Woche halten (bei Wochenwechsel)
  useEffect(() => {
    const wt = Array.from({ length: 7 }, (_, i) => addDays(montag, i))
    setFokusTag((cur) => (wt.includes(cur) ? cur : (wt.includes(isoHeute()) ? isoHeute() : montag)))
  }, [montag])

  const eintraege = (datum, mahlzeit) =>
    plan.filter((e) => e.datum === datum && e.mahlzeit === mahlzeit)

  const tage = Array.from({ length: 7 }, (_, i) => addDays(montag, i))
  const heute = isoHeute()

  return (
    <div className="space-y-4">
      {/* Header: Wochennavigation */}
      <div className="flex flex-wrap items-end justify-between gap-x-2 gap-y-2">
        <div>
          <p className="label-mono text-terracotta">{fmtKW(montag)} · {fmtMonate(montag)}</p>
          <h2 className="mt-1 font-dish text-4xl leading-none text-ink">Wochenplan</h2>
        </div>
        <div className="flex items-center gap-1.5">
          {montag !== getMontag(heute) && (
            <button onClick={wocheHeute} className="rounded-full border border-terracotta/40 px-3 py-1.5 text-sm font-semibold text-terracotta transition hover:bg-terracotta/10 active:scale-95">
              Heute
            </button>
          )}
          <button onClick={wocheVor} aria-label="Vorige Woche" className="flex h-9 w-9 items-center justify-center rounded-full border border-line text-muted transition hover:border-terracotta/40 hover:text-terracotta active:scale-95"><Icon name="chevron-left" size={16} /></button>
          <button onClick={wocheNach} aria-label="Nächste Woche" className="flex h-9 w-9 items-center justify-center rounded-full border border-line text-muted transition hover:border-terracotta/40 hover:text-terracotta active:scale-95"><Icon name="chevron-right" size={16} /></button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><Spinner /></div>
      ) : !tagansicht ? (
        /* Übersicht: 8 große Buttons (Mit KI planen + 7 Tage) */
        <div className="stagger grid grid-cols-2 gap-3">
          {ki.text && <button onClick={() => setWizardOffen(true)}
            className="hero-card col-span-2 flex items-center gap-3.5 rounded-[18px] p-[17px] text-left transition active:scale-[0.99]">
            <div className="hero-glow" />
            <span className="relative flex h-[46px] w-[46px] shrink-0 items-center justify-center rounded-xl bg-terracotta/15 text-terracotta"><Icon name="sparkles" size={24} /></span>
            <span className="relative"><span className="block font-display text-base font-bold text-ink">Mit KI planen</span><span className="block text-sm text-muted">Ganze Woche automatisch vorschlagen lassen</span></span>
          </button>}
          {tage.map((d) => {
            const dt = new Date(d + 'T00:00:00')
            const anzahl = plan.filter((e) => e.datum === d).length
            const shop = einkaufstage.has(d)
            const istHeuteT = d === heute
            return (
              <button key={d} onClick={() => { setFokusTag(d); setTagansicht(true) }}
                className={`relative flex min-h-[104px] flex-col justify-between rounded-2xl border p-3.5 text-left transition active:scale-[0.98] ${istHeuteT ? 'border-terracotta bg-card hover:border-terracotta' : 'border-line bg-surface hover:border-terracotta/40'}`}>
                {shop && <span className="absolute right-2.5 top-2.5" title="Einkaufstag"><Icon name="shopping-cart" size={15} className="text-terracotta" /></span>}
                <div>
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="font-display text-[15px] font-bold capitalize leading-tight text-ink">{dt.toLocaleDateString('de-DE', { weekday: 'long' })}</p>
                    {istHeuteT && <span className="label-mono shrink-0 rounded bg-terracotta px-1.5 py-0.5 text-on-accent">Heute</span>}
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-muted2">{dt.toLocaleDateString('de-DE', { day: 'numeric', month: 'long' })}</p>
                </div>
                <p className={`mt-2 inline-flex items-center gap-1 text-sm font-semibold ${anzahl ? 'text-olive' : 'text-muted2'}`}>
                  {anzahl ? <><Icon name="chef-hat" size={15} /> {anzahl} geplant</> : <><Icon name="plus" size={15} /> planen</>}
                </p>
              </button>
            )
          })}
        </div>
      ) : (
        <div key={fokusTag} className="rise space-y-3">
          <button onClick={() => setTagansicht(false)} className="inline-flex items-center gap-1 text-sm font-semibold text-muted transition hover:text-terracotta active:scale-95"><Icon name="chevron-left" size={18} /> Wochenübersicht</button>
          {/* Kopf des gewählten Tages */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <h3 className={`font-dish text-3xl leading-none ${fokusTag === heute ? 'text-terracotta' : 'text-ink'}`}>
              {new Date(fokusTag + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' })}{fokusTag === heute ? ' · heute' : ''}
            </h3>
            <button onClick={() => toggleEinkaufstag(fokusTag)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold transition active:scale-95 ${einkaufstage.has(fokusTag) ? 'bg-terracotta text-on-accent' : 'border border-line text-ink/60 hover:border-terracotta/40'}`}>
              <Icon name="shopping-cart" size={16} /> {einkaufstage.has(fokusTag) ? ((einkaufsMarkt.get(fokusTag) || []).join(', ') || 'Einkaufstag') : 'Einkaufstag'}
            </button>
          </div>
          {einkaufstage.has(fokusTag) && (
            <button onClick={() => oeffneMarktDialog(fokusTag)} className="text-xs font-semibold text-terracotta hover:underline">Märkte wählen / ändern</button>
          )}
          {personen.flatMap((p) => {
            const lbl = abwesenheitsLabel(p, fokusTag)
            return lbl ? [<span key={p.id} className="mr-2 inline-flex items-center gap-1 text-xs text-muted2"><Icon name="home" size={14} /> {lbl}</span>] : []
          })}

          {/* Mahlzeiten – direkt bearbeitbar (kein Modus-Umschalten) */}
          <div className="stagger space-y-3">
            {MAHLZEITEN.map((mahlzeit) => {
              const slots = eintraege(fokusTag, mahlzeit)
              return (
                <div key={mahlzeit}>
                  <p className="label-mono mb-1.5 inline-flex items-center gap-1.5 text-muted2"><MahlzeitIcon mahlzeit={mahlzeit} /> {mahlzeit}</p>
                  {slots.length === 0 ? (
                    <button onClick={() => setOffenerSlot({ datum: fokusTag, mahlzeit, eintrag: null, startPanel: 'rezept' })}
                      className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-line py-3 text-sm text-muted2 transition hover:border-terracotta/50 hover:text-terracotta active:scale-[0.99]">
                      <Icon name="plus" size={16} /> {mahlzeit} planen
                    </button>
                  ) : (
                    <div className="space-y-1.5">
                      {slots.map((e) => (
                        <div key={e.id} className="flex gap-1.5">
                          <button onClick={() => setOffenerSlot({ datum: fokusTag, mahlzeit, eintrag: e, startPanel: null })}
                            className="flex flex-1 items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5 text-left transition hover:border-terracotta/40 active:scale-[0.99]">
                            <span className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-[10px] bg-terracotta/15 text-terracotta"><Icon name="chef-hat" size={18} /></span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate font-dish text-lg leading-tight text-ink">{e.rezept_name || e.notiz || 'Rezept wählen'}</span>
                              {slotPersonenLabel(e) && <span className="label-mono mt-0.5 block text-olive">{slotPersonenLabel(e)}</span>}
                            </span>
                          </button>
                          {!vorratAktiv && e.rezept_id && (
                            <button onClick={() => inWarenkorb(e)} title={e.im_warenkorb ? 'Zutaten schon auf der Liste – erneut hinzufügen' : 'Zutaten zur Einkaufsliste'}
                              className={`flex shrink-0 items-center gap-0.5 rounded-xl px-3 transition active:scale-95 ${e.im_warenkorb ? 'bg-olive/20 text-olive' : 'bg-olive/8 hover:bg-olive/15'}`}>
                              <Icon name="shopping-cart" size={16} />{e.im_warenkorb ? <Icon name="check" size={14} /> : null}
                            </button>
                          )}
                        </div>
                      ))}
                      <button onClick={() => setOffenerSlot({ datum: fokusTag, mahlzeit, eintrag: null, startPanel: 'rezept' })}
                        className="text-xs font-semibold text-terracotta hover:underline">+ weiterer Eintrag</button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}


      {/* Slot-Popup (Belegen/Bearbeiten inkl. Rezept-Vorschau) */}
      {offenerSlot && (
        <SlotEditor
          datum={offenerSlot.datum}
          mahlzeit={offenerSlot.mahlzeit}
          eintrag={offenerSlot.eintrag}
          startPanel={offenerSlot.startPanel}
          personen={personen}
          notify={notify}
          onClose={() => setOffenerSlot(null)}
          onSaved={() => { lade(); setOffenerSlot(null) }}
          onDeleted={(id) => { setPlan((p) => p.filter((e) => e.id !== id)); setOffenerSlot(null) }}
        />
      )}

      {/* Geführte Wochenplanung */}
      {wizardOffen && ki.text && (
        <WochenWizard
          tage={tage}
          personen={personen}
          notify={notify}
          onClose={() => setWizardOffen(false)}
          onDone={lade}
        />
      )}

      {/* Markt-Auswahl für einen Einkaufstag */}
      {marktDialog && (
        <Modal
          open
          onClose={() => setMarktDialog(null)}
          title={`Wo einkaufen am ${new Date(marktDialog.datum + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'short' })}?`}
        >
          <div className="space-y-2">
            <p className="text-sm text-ink/60">Märkte mit an diesem Tag gültigen Angeboten – <b>Mehrfachauswahl möglich</b>. Keine Auswahl = ohne Angebots-Logik.</p>
            {marktDialog.maerkte.map((m) => {
              const aktiv = marktAuswahl.includes(m.haendler)
              return (
                <button
                  key={m.haendler}
                  onClick={() => toggleMarkt(m.haendler)}
                  className={`flex w-full items-center justify-between gap-2 rounded-xl border px-4 py-3 text-left transition ${
                    aktiv ? 'border-terracotta bg-terracotta/10' : 'border-line bg-card hover:border-terracotta/50'
                  }`}
                >
                  <span className="inline-flex items-center gap-1 font-semibold">{aktiv ? <Icon name="check" size={16} /> : null}<Icon name="store" size={16} /> {m.haendler}</span>
                  <span className="text-xs text-ink/45">{m.anzahl} Angebote</span>
                </button>
              )
            })}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setMarktDialog(null)}>Abbrechen</Button>
              <Button onClick={speichereMaerkte}>Speichern</Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
