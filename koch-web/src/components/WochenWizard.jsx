import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Modal, Button, Spinner } from '../ui.jsx'
import { istAnwesend } from '../utils.js'
import { Icon } from '../icons.jsx'
import { useKi } from '../kiStatus.js'

const MAHLZEITEN = ['Frühstück', 'Mittag', 'Abendessen', 'Snack', 'Unterwegs']
const MAHLZEIT_ICON_NAME = { 'Frühstück': 'sunrise', 'Mittag': 'sun', 'Abendessen': 'moon', 'Snack': 'apple', 'Unterwegs': 'backpack' }
function MahlzeitIcon({ mahlzeit, size = 16 }) {
  const name = MAHLZEIT_ICON_NAME[mahlzeit]
  return name ? <Icon name={name} size={size} /> : null
}
const dlabel = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })

// Geführter Wochenplanungs-Assistent: Einkaufstage+Märkte → Mahlzeiten+Personen →
// KI generiert je Mahlzeit ein Rezept → Review → speichern & in den Plan eintragen.
export default function WochenWizard({ tage, personen, onClose, onDone, notify }) {
  const ki = useKi()
  const [step, setStep] = useState(1)
  const [tagMaerkte, setTagMaerkte] = useState({})          // datum -> [{haendler,anzahl}]
  const [einkauf, setEinkauf] = useState({})                // datum -> { aktiv, haendler:[] }
  const [meals, setMeals] = useState(() => new Set())       // "datum|mahlzeit"
  const [tagPersonen, setTagPersonen] = useState({})        // datum -> Set(personIds)
  const [results, setResults] = useState([])                // [{datum, mahlzeit, person_ids, rezept, busy, error}]
  const [genN, setGenN] = useState(0)
  const [saving, setSaving] = useState(false)
  // Bilder beim Übernehmen erzeugen? Konto-Einstellung ist nur die Vorbelegung – hier
  // abwählbar, denn bei einer ganzen Woche wären das gleich mehrere Bild-Generierungen.
  const [bildWunsch, setBildWunsch] = useState(false)
  useEffect(() => { api.autoBild().then((r) => setBildWunsch(!!r.aktiv)).catch(() => {}) }, [])

  // Märkte je Tag laden (für die Händler-Auswahl)
  useEffect(() => {
    let ok = true
    Promise.all(tage.map((d) => api.angeboteMaerkte(d).then((m) => [d, m || []]).catch(() => [d, []])))
      .then((arr) => { if (ok) setTagMaerkte(Object.fromEntries(arr)) })
    return () => { ok = false }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleTag = (d) => setEinkauf((e) => ({ ...e, [d]: { aktiv: !(e[d]?.aktiv), haendler: e[d]?.haendler || [] } }))
  const toggleHaendler = (d, h) => setEinkauf((e) => {
    const cur = e[d]?.haendler || []
    return { ...e, [d]: { aktiv: true, haendler: cur.includes(h) ? cur.filter((x) => x !== h) : [...cur, h] } }
  })
  const unionHaendler = () => {
    const s = new Set()
    Object.values(einkauf).forEach((d) => d?.aktiv && (d.haendler || []).forEach((h) => s.add(h)))
    return [...s]
  }

  const defaultPersonen = (datum, mahlzeit) => {
    const anwesend = personen.filter((p) => istAnwesend(p, datum, mahlzeit))
    return new Set((anwesend.length ? anwesend : personen).map((p) => p.id))
  }
  const mealKey = (d, m) => `${d}|${m}`
  function toggleMeal(d, m) {
    setMeals((s) => {
      const n = new Set(s); const k = mealKey(d, m)
      if (n.has(k)) n.delete(k); else { n.add(k); if (!tagPersonen[d]) setTagPersonen((tp) => ({ ...tp, [d]: defaultPersonen(d, m) })) }
      return n
    })
  }
  const togglePerson = (d, pid) => setTagPersonen((tp) => {
    const cur = new Set(tp[d] || defaultPersonen(d, 'Mittag')); cur.has(pid) ? cur.delete(pid) : cur.add(pid)
    return { ...tp, [d]: cur }
  })

  async function weiterVonEinkauf() {
    // Einkaufstage + Märkte speichern (markiert die Tage als Einkaufstag)
    try {
      for (const [d, v] of Object.entries(einkauf)) {
        if (v?.aktiv) await api.einkaufstagHaendler(d, v.haendler || [])
      }
    } catch { /* nicht blockierend */ }
    setStep(2)
  }

  async function generiereAlle() {
    const items = [...meals].sort().map((k) => {
      const [datum, mahlzeit] = k.split('|')
      const pids = [...(tagPersonen[datum] || defaultPersonen(datum, mahlzeit))]
      return { datum, mahlzeit, person_ids: pids, rezept: null, busy: true, error: null }
    })
    if (!items.length) { notify('Bitte mindestens eine Mahlzeit wählen', 'err'); return }
    setResults(items); setStep(3); setGenN(0)
    const haendler = unionHaendler()
    for (let i = 0; i < items.length; i++) {
      setGenN(i + 1)
      try {
        const res = await api.rezeptGenerieren(null, haendler.length ? haendler : null, true,
          items[i].person_ids.length ? items[i].person_ids : null, null)
        items[i] = { ...items[i], rezept: res?.rezept || null, busy: false, error: res?.error || null }
      } catch { items[i] = { ...items[i], busy: false, error: 'Fehlgeschlagen' } }
      setResults([...items])
    }
    setStep(4)
  }

  async function neuGenerieren(i) {
    setResults((r) => r.map((x, j) => (j === i ? { ...x, busy: true } : x)))
    const haendler = unionHaendler()
    try {
      const it = results[i]
      const res = await api.rezeptGenerieren(null, haendler.length ? haendler : null, true,
        it.person_ids.length ? it.person_ids : null, null)
      setResults((r) => r.map((x, j) => (j === i ? { ...x, rezept: res?.rezept || x.rezept, busy: false, error: res?.error || null } : x)))
    } catch { setResults((r) => r.map((x, j) => (j === i ? { ...x, busy: false } : x))) }
  }

  async function uebernehmen() {
    setSaving(true)
    let n = 0
    try {
      for (const it of results) {
        if (!it.rezept) continue
        const neu = await api.rezeptAnlegen({
          name: it.rezept.name, beschreibung: it.rezept.beschreibung || null,
          portionen: Number(it.rezept.portionen) || 2, dauer_minuten: it.rezept.dauer_minuten || null,
          quelle: 'Wochenplanung', zutaten: it.rezept.zutaten || [], geraete: it.rezept.geraete || [],
          zubereitung: it.rezept.zubereitung || [],
        })
        await api.planEintragAnlegen({ datum: it.datum, mahlzeit: it.mahlzeit, rezept_id: neu.id, person_ids: it.person_ids })
        if (bildWunsch && ki.bild) api.rezeptBildGenerieren(neu.id).catch(() => {})  // Bild im Hintergrund
        n++
      }
      notify(`Woche geplant – ${n} Rezept${n === 1 ? '' : 'e'} erstellt & eingetragen`)
      onDone && onDone(); onClose()
    } catch { notify('Übernehmen fehlgeschlagen', 'err'); setSaving(false) }
  }

  const aktiveTage = tage.filter((d) => einkauf[d]?.aktiv)

  return (
    <Modal open onClose={onClose} title="Woche planen">
      <div className="space-y-4">
        {/* Fortschritt */}
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4].map((s) => <div key={s} className={`h-1.5 flex-1 rounded-full ${s <= step ? 'bg-terracotta' : 'bg-line'}`} />)}
        </div>

        {/* Schritt 1: Einkaufstage + Märkte */}
        {step === 1 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Wann & wo kaufst du ein?</h3>
            <p className="text-sm text-muted">Tippe die Einkaufstage an und wähle je Tag die Märkte (Mehrfachauswahl). Die KI bevorzugt dann deren Angebote.</p>
            <div className="space-y-2">
              {tage.map((d, i) => {
                const v = einkauf[d] || {}
                const maerkte = tagMaerkte[d] || []
                return (
                  <div key={d} className={`rounded-xl border p-2.5 ${v.aktiv ? 'border-terracotta bg-terracotta/5' : 'border-line'}`}>
                    <button onClick={() => toggleTag(d)} className="flex w-full items-center justify-between text-sm font-semibold">
                      <span className="inline-flex items-center gap-1">{v.aktiv ? <Icon name="shopping-cart" size={16} /> : '·'} <span className="font-mono">{dlabel(d)}</span></span>
                      <span className="text-muted2">{v.aktiv ? 'Einkaufstag' : 'antippen'}</span>
                    </button>
                    {v.aktiv && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {maerkte.length === 0 && <span className="text-xs text-muted2">Keine Angebote an dem Tag</span>}
                        {maerkte.map((m) => {
                          const an = (v.haendler || []).includes(m.haendler)
                          return (
                            <button key={m.haendler} onClick={() => toggleHaendler(d, m.haendler)}
                              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs ${an ? 'border-terracotta bg-terracotta/10 font-semibold text-terracotta-deep' : 'border-line text-muted'}`}>
                              {an ? <Icon name="check" size={16} /> : null}{m.haendler} <span className="text-muted2">({m.anzahl})</span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
              <Button onClick={weiterVonEinkauf}>Weiter</Button>
            </div>
          </div>
        )}

        {/* Schritt 2: Mahlzeiten + Personen */}
        {step === 2 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Welche Mahlzeiten soll die KI planen?</h3>
            <p className="text-sm text-muted">Kreuze Tage &amp; Mahlzeiten an. Personen sind standardmäßig alle Anwesenden – pro Tag anpassbar.</p>
            <div className="space-y-2">
              {tage.map((d, i) => {
                const tagMeals = MAHLZEITEN.filter((m) => meals.has(mealKey(d, m)))
                return (
                  <div key={d} className="rounded-xl border border-line p-2.5">
                    <p className="mb-1.5 font-mono text-sm font-semibold">{dlabel(d)}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {MAHLZEITEN.map((m) => {
                        const an = meals.has(mealKey(d, m))
                        return (
                          <button key={m} onClick={() => toggleMeal(d, m)}
                            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${an ? 'border-terracotta bg-terracotta text-on-accent' : 'border-line text-muted'}`}>
                            <MahlzeitIcon mahlzeit={m} /> {m}
                          </button>
                        )
                      })}
                    </div>
                    {tagMeals.length > 0 && personen.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5 border-t border-line/40 pt-2">
                        {personen.map((p) => {
                          const sel = (tagPersonen[d] || defaultPersonen(d, 'Mittag')).has(p.id)
                          return (
                            <button key={p.id} onClick={() => togglePerson(d, p.id)}
                              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs ${sel ? 'border-olive bg-olive/15 text-olive' : 'border-line text-muted2'}`}>
                              {sel ? <Icon name="check" size={16} /> : null}{p.name}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="flex justify-between gap-2">
              <Button variant="ghost" onClick={() => setStep(1)}>Zurück</Button>
              <Button variant="ki" onClick={generiereAlle} disabled={meals.size === 0} className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /> {meals.size} Rezepte generieren</Button>
            </div>
          </div>
        )}

        {/* Schritt 3: Generierung läuft */}
        {step === 3 && (
          <div className="space-y-3 py-6 text-center">
            <Spinner />
            <p className="inline-flex items-center justify-center gap-1 text-sm text-muted"><Icon name="chef-hat" size={16} /> Erstelle Rezept <span className="font-mono">{genN}</span> von <span className="font-mono">{results.length}</span> …</p>
            <p className="text-xs text-muted2">Das kann einen Moment dauern.</p>
          </div>
        )}

        {/* Schritt 4: Review */}
        {step === 4 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Passt das so?</h3>
            <div className="space-y-2">
              {results.map((it, i) => (
                <div key={i} className="rounded-xl border border-line p-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="inline-flex items-center gap-1 label-mono text-[11px] text-muted2"><MahlzeitIcon mahlzeit={it.mahlzeit} /> {dlabel(it.datum)} · {it.mahlzeit}</p>
                      <p className="truncate font-dish text-2xl leading-tight">{it.busy ? '… wird erstellt' : (it.rezept?.name || (it.error ? <span className="inline-flex items-center gap-1 font-display text-base"><Icon name="alert-triangle" size={16} /> fehlgeschlagen</span> : '—'))}</p>
                      {it.rezept?.beschreibung && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{it.rezept.beschreibung}</p>}
                    </div>
                    <button onClick={() => neuGenerieren(i)} disabled={it.busy}
                      className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-terracotta disabled:opacity-40 hover:bg-terracotta/10">
                      {it.busy ? '…' : <><Icon name="refresh" size={16} /> Neu</>}
                    </button>
                  </div>
                </div>
              ))}
            </div>
            {ki.bild && <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input type="checkbox" checked={bildWunsch} onChange={(e) => setBildWunsch(e.target.checked)} className="mt-0.5 h-4 w-4 accent-terracotta" />
              <span>
                <span className="inline-flex items-center gap-1"><Icon name="image" size={16} /> Bilder zu den Rezepten erzeugen</span>
                <span className="block text-[11px] text-muted2">Je Rezept ein KI-Bild. Später jederzeit nachholbar.</span>
              </span>
            </label>}
            <div className="flex justify-between gap-2">
              <Button variant="ghost" onClick={() => setStep(2)}>Zurück</Button>
              <Button onClick={uebernehmen} disabled={saving || !results.some((r) => r.rezept)} className="inline-flex items-center gap-1">
                {saving ? <Spinner /> : <><Icon name="check" size={16} /> Übernehmen & einplanen</>}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
