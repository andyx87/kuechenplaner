import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Card, Button, Modal, input, Field, Spinner, Empty } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { isoHeute } from '../utils.js'
import PortionenWahl from './PortionenWahl.jsx'
import { RezeptThumb } from './Rezepte.jsx'

const MAHLZEITEN = ['Frühstück', 'Mittag', 'Abendessen', 'Snack', 'Unterwegs']
const STERN_VOLL = '#d4a454'

function fmtPreis(p) {
  if (p == null) return null
  return Number(p).toFixed(2).replace('.', ',') + ' €'
}
function fmtMenge(m) {
  if (m == null) return ''
  const n = Number(m)
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '').replace('.', ',')
}

export default function Start({ notify, openRezept, vorratAktiv = true }) {
  const [data, setData] = useState(null)
  const [genOffen, setGenOffen] = useState(false)
  const [tab, setTab] = useState('vorrat')   // 'vorrat' | 'angebote'
  const [angMaerkte, setAngMaerkte] = useState([])
  const [angMarktWahl, setAngMarktWahl] = useState([])
  const [angVorrat, setAngVorrat] = useState(vorratAktiv)
  const [angRezepte, setAngRezepte] = useState([])
  const [angLoading, setAngLoading] = useState(false)
  const [angSort, setAngSort] = useState('angebote')   // 'angebote' | 'vorrat'
  const [vorratFreitext, setVorratFreitext] = useState('')   // Light: „Was hast du da?"
  const [genFreitext, setGenFreitext] = useState(null)       // != null -> Generator mit diesen Zutaten öffnen

  useEffect(() => {
    api.start().then(setData).catch(() => { setData({ angebote_vorlieben: [], sofort_kochbar: [], fast_kochbar: [] }); notify && notify('Startseite laden fehlgeschlagen', 'err') })
    api.angeboteMaerkte(isoHeute())
      .then((m) => setAngMaerkte((m || []).map((x) => (typeof x === 'string' ? x : (x.haendler || x.name))).filter(Boolean)))
      .catch(() => {})
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Ohne Vorratsverwaltung (light) gibt es keinen App-Vorrat zum Einbeziehen.
  const vorratEinbeziehen = vorratAktiv && angVorrat

  useEffect(() => {
    if (!angMarktWahl.length) { setAngRezepte([]); return }
    setAngLoading(true)
    const p = new URLSearchParams()
    p.set('markt', angMarktWahl.join(','))
    p.set('vorrat', vorratEinbeziehen ? '1' : '0')
    api.rezepteFilter(p.toString()).then((r) => setAngRezepte(r || [])).catch(() => setAngRezepte([])).finally(() => setAngLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [angMarktWahl, vorratEinbeziehen])

  // Externer Trigger (z.B. Onboarding-Abschluss „Erstes Rezept erstellen").
  useEffect(() => {
    const h = () => setGenOffen(true)
    window.addEventListener('koch:rezept-erstellen', h)
    return () => window.removeEventListener('koch:rezept-erstellen', h)
  }, [])

  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>

  const angebote = data.angebote_vorlieben || []
  const sofort = data.sofort_kochbar || []
  const fast = data.fast_kochbar || []
  const nm = data.naechste_mahlzeit || null

  // Neuer/leerer Zustand: noch kein Plan, keine kochbaren Rezepte, keine Angebote →
  // fokussierte Startseite mit EINER Hauptaktion (statt aller Tabs/Listen).
  const leer = !nm && sofort.length === 0 && fast.length === 0 && angebote.length === 0
  if (leer) {
    return (
      <div className="space-y-6">
        <div className="hero-card space-y-3 rounded-[22px] p-6 text-center">
          <div className="hero-glow" />
          <h2 className="font-dish text-4xl leading-tight text-ink">Was kochen wir heute?</h2>
          <p className="mx-auto max-w-md text-sm text-muted">
            Lass dir aus deinem Vorrat, deinen Geräten & aktuellen Angeboten ein Rezept erstellen –
            oder frag unten den Assistenten.
          </p>
          <Button variant="ki" className="mx-auto" onClick={() => setGenOffen(true)}><span className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /> Erstes Rezept erstellen</span></Button>
          <p className="mx-auto inline-flex max-w-md flex-wrap items-center gap-1 text-xs text-muted2">
            Tipp: Im <Icon name="message-circle" size={16} /> Assistenten (unten) kannst du auch ein Foto/PDF von Vorrat oder Prospekt anhängen.
          </p>
        </div>
        {genOffen && <Generator notify={notify} openRezept={openRezept} vorratAktiv={vorratAktiv} onClose={() => setGenOffen(false)} />}
      </div>
    )
  }

  const tagLabel = (iso) => {
    const heute = isoHeute()
    if (iso === heute) return 'Heute'
    const t = new Date(heute + 'T00:00:00'); t.setDate(t.getDate() + 1)
    const morgen = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
    if (iso === morgen) return 'Morgen'
    return new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'short' })
  }
  function toggleAngMarkt(m) {
    setAngMarktWahl((a) => (a.includes(m) ? a.filter((x) => x !== m) : [...a, m]))
  }
  async function markiereGekocht(id) {
    try { await api.planGekocht(id, true); setData(await api.start()) }
    catch { notify && notify('Konnte nicht als gekocht markieren', 'err') }
  }

  return (
    <div className="space-y-6">
      {/* Rezept-Generator – Hero */}
      <div className="hero-card flex items-center justify-between gap-3 rounded-[22px] p-5">
        <div className="hero-glow" />
        <div className="relative">
          <h3 className="font-dish text-2xl leading-tight text-ink">Was kochen wir heute?</h3>
          <p className="label-mono mt-1.5 text-muted2">Vorrat · Geräte · Angebote</p>
        </div>
        <Button variant="ki" className="relative shrink-0" onClick={() => setGenOffen(true)}><span className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /> Rezept erstellen</span></Button>
      </div>

      {/* Als Nächstes geplant – Kachelbreite passt sich der Anzahl an (1=voll, 2=halb, 3=Drittel), max. 3 */}
      {nm && nm.rezepte?.length > 0 && (() => {
        const liste = nm.rezepte.slice(0, 3)
        const cols = liste.length === 1 ? 'sm:grid-cols-1' : liste.length === 2 ? 'sm:grid-cols-2' : 'sm:grid-cols-3'
        return (
          <section>
            <h3 className="mb-2 flex items-center gap-2 font-display text-xl"><Icon name="calendar" size={18} /> Als Nächstes · {tagLabel(nm.datum)} · {nm.mahlzeit}</h3>
            <div className={`grid gap-3 ${cols}`}>
              {liste.map((r) => (
                <Card key={r.id} className="cursor-pointer border-olive/30 bg-olive/5 p-4 transition hover:-translate-y-0.5" onClick={() => openRezept && openRezept(r.rezept_id)}>
                  <RezeptThumb id={r.rezept_id} hatBild={r.hat_bild} bump={0} />
                  <h4 className="font-dish text-2xl leading-tight">{r.rezept}</h4>
                </Card>
              ))}
            </div>
          </section>
        )
      })()}

      {/* Unterrubriken – Segmented Control (Grün = „im Vorrat"-Signal) */}
      <div className="flex gap-2 rounded-2xl bg-surface p-1.5">
        <button onClick={() => setTab('vorrat')} className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-sm font-bold transition ${tab === 'vorrat' ? 'border border-olive/30 bg-olive/15 text-olive' : 'border border-transparent text-muted hover:text-ink'}`}><Icon name="chef-hat" size={16} /> Aus dem Vorrat</button>
        <button onClick={() => setTab('angebote')} className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-sm font-bold transition ${tab === 'angebote' ? 'border border-terracotta/40 bg-terracotta/15 text-terracotta' : 'border border-transparent text-muted hover:text-ink'}`}><Icon name="tag" size={16} /> Im Angebot</button>
      </div>

      {/* Im Angebot: Märkte wählen -> Rezepte aus deren Angeboten (+ Vorrat-Schalter) */}
      {tab === 'angebote' && (
      <section className="space-y-3">
        <h3 className="flex items-center gap-2 font-display text-xl"><Icon name="tag" size={18} /> Im Angebot kochen</h3>
        <div className="space-y-2 rounded-xl border border-line p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-bold uppercase tracking-wide text-ink/45">Märkte</span>
            {angMaerkte.length === 0
              ? <span className="text-xs text-ink/45">Aktuell keine Angebote hinterlegt.</span>
              : angMaerkte.map((m) => (
                <button key={m} onClick={() => toggleAngMarkt(m)}
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${angMarktWahl.includes(m) ? 'bg-terracotta text-on-accent' : 'bg-line/40 text-ink/70 hover:bg-line/70'}`}>{m}</button>
              ))}
          </div>
          {vorratAktiv && (
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" checked={angVorrat} onChange={(e) => setAngVorrat(e.target.checked)} className="h-4 w-4 accent-olive" />
              <span className="text-ink/70">Vorrat einbeziehen</span>
            </label>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wide text-ink/45">Sortieren</span>
            <select value={angSort} onChange={(e) => setAngSort(e.target.value)} className={input + ' max-w-[16rem] flex-1 py-1 text-sm'}>
              <option value="angebote">Anzahl Angebotsartikel</option>
              {vorratAktiv && <option value="vorrat">Zutaten vorhanden</option>}
            </select>
          </div>
        </div>

        {angMarktWahl.length === 0 ? (
          <p className="text-sm text-ink/50">Wähle oben einen oder mehrere Märkte – dann zeige ich Rezepte, die du mit deren Angeboten{vorratEinbeziehen ? ' + deinem Vorrat' : ''} kochen kannst.</p>
        ) : angLoading ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : angRezepte.length === 0 ? (
          <p className="text-sm text-ink/50">Keine Rezepte mit den Angeboten der gewählten Märkte gefunden.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-3">
            {[...angRezepte].sort((a, b) => vorratAktiv && angSort === 'vorrat'
              ? (b.vorrat_treffer || 0) - (a.vorrat_treffer || 0)
              : (b.angebot_treffer || 0) - (a.angebot_treffer || 0)).slice(0, 12).map((r) => (
              <Card key={r.id} className="cursor-pointer p-4 transition hover:-translate-y-0.5" onClick={() => openRezept && openRezept(r.id, { angebotMarkt: angMarktWahl.join(',') })}>
                <RezeptThumb id={r.id} hatBild={r.hat_bild} bump={0} />
                <h4 className="font-dish text-xl leading-tight">{r.name}</h4>
                <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-terracotta/15 px-2 py-0.5 text-xs font-semibold text-terracotta-deep">
                  <Icon name="tag" size={16} /> {r.angebot_treffer} Angebot{r.angebot_treffer === 1 ? '' : 'e'}{vorratEinbeziehen && r.vorrat_treffer ? <> · <Icon name="soup" size={16} /> {r.vorrat_treffer}</> : ''}
                </span>
              </Card>
            ))}
          </div>
        )}

        {angebote.length > 0 && (
          <details className="rounded-xl border border-line p-3">
            <summary className="cursor-pointer text-sm font-semibold text-ink/70">Aktuelle Angebote für euch ({angebote.length})</summary>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {angebote.map((a) => {
                const rabatt = a.preis_normal && a.preis_angebot ? Math.round((1 - a.preis_angebot / a.preis_normal) * 100) : null
                return (
                  <Card key={a.id} className="p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-semibold capitalize">{a.name}</p>
                        <p className="text-xs text-olive">für {a.fuer.join(', ')}</p>
                        {a.haendler && <p className="inline-flex items-center gap-1 text-xs text-ink/45"><Icon name="store" size={16} /> {a.haendler}</p>}
                      </div>
                      <div className="shrink-0 text-right">
                        {a.preis_angebot != null && <p className="font-bold text-terracotta">{fmtPreis(a.preis_angebot)}{a.einheit ? <span className="text-xs font-normal text-ink/50"> / {a.einheit}</span> : null}</p>}
                        {rabatt ? <span className="mt-0.5 inline-block rounded bg-terracotta/15 px-1.5 py-0.5 text-[10px] font-bold text-terracotta-deep">−{rabatt}%</span> : null}
                      </div>
                    </div>
                  </Card>
                )
              })}
            </div>
          </details>
        )}
      </section>
      )}

      {/* Aus dem Vorrat: sofort/knapp kochbar */}
      {tab === 'vorrat' && (vorratAktiv ? (
      <section>
        <h3 className="mb-2 flex items-center gap-2 font-display text-xl"><Icon name="chef-hat" size={18} /> Sofort kochbar</h3>
        {(() => {
          // sofort (0 fehlend) zuerst, dann knapp dran; nach rezept_id dedupen (Absicherung gegen Doppel-Anzeige)
          const alle = [...sofort, ...fast].filter((r, i, a) => a.findIndex((x) => x.rezept_id === r.rezept_id) === i)
          const top3 = alle.slice(0, 3)
          const weitere = alle.slice(3)
          if (alle.length === 0) {
            return <p className="text-sm text-ink/50">Gerade ist nichts aus dem Vorrat kochbar. Pflege deinen Vorrat oder lass dir ein Rezept erstellen.</p>
          }
          const badge = (r, sm) => r.fehlend === 0
            ? <span className={sm ? 'inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-olive' : 'mt-2 inline-flex items-center gap-1 rounded-full bg-olive/15 px-2 py-0.5 text-xs font-semibold text-olive'}><Icon name="check" size={16} /> {sm ? 'kochbar' : 'alles im Vorrat'}</span>
            : <span className={sm ? 'shrink-0 text-xs text-terracotta' : 'mt-2 inline-flex items-center gap-1 rounded-full bg-terracotta/15 px-2 py-0.5 text-xs font-semibold text-terracotta'}>{r.fehlend} {r.fehlend === 1 ? 'Zutat fehlt' : 'Zutaten fehlen'}</span>
          return (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                {top3.map((r) => (
                  <Card key={r.rezept_id} className="cursor-pointer p-4 transition hover:-translate-y-0.5" onClick={() => openRezept && openRezept(r.rezept_id)}>
                    <RezeptThumb id={r.rezept_id} hatBild={r.hat_bild} bump={0} />
                    <h4 className="font-dish text-xl leading-tight">{r.rezept}</h4>
                    {badge(r, false)}
                    {r.sterne ? <p className="mt-1 inline-flex gap-0.5" style={{ color: STERN_VOLL }}>{Array.from({ length: r.sterne }).map((_, si) => <Icon key={si} name="star" size={16} fill="currentColor" />)}</p> : null}
                  </Card>
                ))}
              </div>
              {weitere.length > 0 && (
                <ul className="mt-3 space-y-1.5 text-sm">
                  {weitere.map((r) => (
                    <li key={r.rezept_id}>
                      <button onClick={() => openRezept && openRezept(r.rezept_id)}
                        className="flex w-full items-center justify-between gap-2 rounded-xl border border-line bg-card px-3 py-2 text-left transition hover:-translate-y-0.5 hover:border-terracotta/40 hover:bg-terracotta/5">
                        <span className="min-w-0 truncate text-ink/80">{r.rezept}</span>
                        {badge(r, true)}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )
        })()}
      </section>
      ) : (
      <section className="space-y-2">
        <h3 className="flex items-center gap-2 font-display text-xl"><Icon name="chef-hat" size={18} /> Aus deinen Zutaten</h3>
        <p className="text-sm text-muted">Gib ein, was du gerade da hast – Sapio macht dir daraus einen Rezept-Vorschlag.</p>
        <textarea rows={2} value={vorratFreitext} onChange={(e) => setVorratFreitext(e.target.value)}
          placeholder="z.B. Kartoffeln, Zwiebeln, Hähnchenbrust, etwas Käse, Reis …"
          className={input + ' resize-none'} />
        <button onClick={() => setGenFreitext(vorratFreitext.trim())} disabled={!vorratFreitext.trim()}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-terracotta py-2.5 text-sm font-semibold text-on-accent transition hover:opacity-90 disabled:opacity-50">
          <Icon name="sparkles" size={16} /> Vorschlag aus diesen Zutaten
        </button>
      </section>
      ))}

      {genOffen && <Generator notify={notify} openRezept={openRezept} vorratAktiv={vorratAktiv} onClose={() => setGenOffen(false)} />}
      {genFreitext !== null && <Generator notify={notify} openRezept={openRezept} vorratAktiv={vorratAktiv} initialFreitext={genFreitext} onClose={() => setGenFreitext(null)} />}
    </div>
  )
}

// ── KI-Rezept-Generator ──
export function Generator({ notify, openRezept, vorratAktiv = true, onClose, initialWunsch = '', initialFreitext = '' }) {
  const [wunsch, setWunsch] = useState(initialWunsch)
  const [maerkte, setMaerkte] = useState([])                  // verfügbare Händler mit Angeboten
  const [haendler, setHaendler] = useState([])                // ausgewählte Händler (Mehrfach)
  const [vorrat, setVorrat] = useState(true)
  const [vorratModus, setVorratModus] = useState('voll')     // 'voll' (App-Vorrat) | 'light' (Freitext)
  const [freitext, setFreitext] = useState(initialFreitext)  // Vorrat-Light: frei eingegebene Zutaten
  const [bildWunsch, setBildWunsch] = useState(false)        // für DIESES Rezept: Bild erzeugen?
  const [zutatAngebote, setZutatAngebote] = useState({})      // Zutatname -> [Angebote] (nur Info)
  const [auswahl, setAuswahl] = useState({ personIds: [], gaeste: 0, portionen: 0 })
  const [busy, setBusy] = useState(false)
  const [rezept, setRezept] = useState(null)
  const [savedId, setSavedId] = useState(null)
  const saveRef = useRef(null)   // laufender/erledigter Speicher-Vorgang (verhindert Doppel-Insert)
  const [planOffen, setPlanOffen] = useState(false)
  const [planDatum, setPlanDatum] = useState(() => isoHeute())
  const [planMahlzeit, setPlanMahlzeit] = useState('Abendessen')

  // Die Konto-Einstellung ist nur die Vorbelegung – pro Rezept ist sie abwählbar.
  useEffect(() => { api.autoBild().then((r) => setBildWunsch(!!r.aktiv)).catch(() => {}) }, [])
  useEffect(() => { api.angeboteMaerkte(isoHeute()).then((m) => setMaerkte(m || [])).catch(() => {}) }, [])
  useEffect(() => { api.vorratModus().then((r) => setVorratModus(r.modus || 'voll')).catch(() => {}) }, [])
  // Von der Startseite mit Zutaten geöffnet -> direkt einen Vorschlag erstellen.
  useEffect(() => { if (initialFreitext && initialFreitext.trim()) generieren() }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const toggleHaendler = (h) => setHaendler((cur) => cur.includes(h) ? cur.filter((x) => x !== h) : [...cur, h])

  async function generieren() {
    setBusy(true); setRezept(null); setSavedId(null); saveRef.current = null; setPlanOffen(false); setZutatAngebote({})
    try {
      const freitextVal = freitext.trim() || null
      const res = await api.rezeptGenerieren(wunsch.trim() || null, haendler.length ? haendler : null, vorratAktiv ? vorrat : false, auswahl.personIds.length ? auswahl.personIds : null, auswahl.portionen > 0 ? auswahl.portionen : null, freitextVal)
      if (res.error) { notify(res.error, 'err'); return }
      setRezept(res.rezept)
      setZutatAngebote(res.zutat_angebote || {})
    } catch {
      notify('Rezept-Generierung fehlgeschlagen', 'err')
    } finally {
      setBusy(false)
    }
  }

  async function uebernehmen() {
    if (savedId) return savedId
    // Idempotent: parallele Klicks („In Bibliothek" + „Einplanen" / Doppelklick) teilen
    // sich EINEN Speicher-Vorgang, statt zwei Rezepte anzulegen.
    if (saveRef.current) return saveRef.current
    saveRef.current = (async () => {
      const r = await api.rezeptAnlegen({
        name: rezept.name,
        beschreibung: rezept.beschreibung || null,
        portionen: Number(rezept.portionen) || 4,
        dauer_minuten: rezept.dauer_minuten || null,
        quelle: 'KI-Vorschlag',
        gang: rezept.gang || null,
        kueche: rezept.kueche || null,
        zutaten: rezept.zutaten || [],
        geraete: rezept.geraete || [],
        zubereitung: rezept.zubereitung || [],
      })
      setSavedId(r.id)
      notify(`„${rezept.name}" in die Bibliothek übernommen`)
      if (bildWunsch) {
        api.rezeptBildGenerieren(r.id).then(() => notify('Bild zum Rezept erstellt')).catch(() => {})
      }
      return r.id
    })()
    try {
      return await saveRef.current
    } catch {
      saveRef.current = null   // Fehlschlag: erneuter Versuch erlaubt
      notify('Übernehmen fehlgeschlagen', 'err')
      return null
    }
  }

  const [bildBusy, setBildBusy] = useState(false)
  async function bildNeu() {
    if (!savedId) return
    const hatteBild = bildWunsch
    setBildBusy(true)
    try {
      await api.rezeptBildGenerieren(savedId)
      setBildWunsch(true)   // ab jetzt „Bild neu" statt „Bild erzeugen"
      notify(hatteBild ? 'Neues Bild erstellt' : 'Bild erstellt')
    } catch { notify('Bild-Erstellung fehlgeschlagen', 'err') }
    finally { setBildBusy(false) }
  }

  async function einplanen() {
    const id = await uebernehmen()
    if (!id) return
    try {
      await api.planEintragAnlegen({ datum: planDatum, mahlzeit: planMahlzeit, rezept_id: id })
      const tag = new Date(planDatum + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })
      notify(`Eingeplant für ${tag} (${planMahlzeit})`)
      onClose()
    } catch {
      notify('Einplanen fehlgeschlagen', 'err')
    }
  }

  return (
    <Modal open onClose={onClose} title="Rezept erstellen">
      <div className="space-y-4">
        <PortionenWahl onChange={setAuswahl} />
        <Field label="Besonderheiten / Wunsch (optional)">
          <textarea rows={3} className={input + ' resize-none'} value={wunsch} placeholder="z.B. asiatisch, schnell, Ofengericht, ohne Knoblauch, Dessert, Vorspeise, Lunchpaket für unterwegs …" onChange={(e) => setWunsch(e.target.value)} />
        </Field>
        {vorratModus === 'light' ? (
          <Field label="Was hast du da? (deine Zutaten)">
            <textarea rows={2} className={input + ' resize-none'} value={freitext}
              placeholder="z.B. viele Kartoffeln, Zwiebeln, Hähnchenbrust, etwas Käse, Reis …"
              onChange={(e) => setFreitext(e.target.value)} />
            <p className="mt-1 text-[11px] text-ink/45">Das Rezept wird aus diesen Zutaten geplant (statt aus dem App-Vorrat).</p>
          </Field>
        ) : vorratAktiv && (
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={vorrat} onChange={(e) => setVorrat(e.target.checked)} className="h-4 w-4 accent-terracotta" />
            <Icon name="soup" size={16} /> Vorhandenen Vorrat berücksichtigen
          </label>
        )}
        {maerkte.length > 0 && (
          <div>
            <p className="mb-1 inline-flex items-center gap-1 text-sm font-semibold"><Icon name="tag" size={16} /> Angebote berücksichtigen von …</p>
            <div className="flex flex-wrap gap-2">
              {maerkte.map((m) => {
                const an = haendler.includes(m.haendler)
                return (
                  <button
                    key={m.haendler}
                    type="button"
                    onClick={() => toggleHaendler(m.haendler)}
                    className={`rounded-full border px-3 py-1 text-sm transition ${an ? 'border-terracotta bg-terracotta/10 font-semibold text-terracotta-deep' : 'border-line bg-card text-ink/70 hover:border-terracotta/50'}`}
                  >
                    {an ? <Icon name="check" size={16} className="mr-1 inline align-text-bottom" /> : null}{m.haendler} <span className="text-xs text-ink/40">({m.anzahl})</span>
                  </button>
                )
              })}
            </div>
            <p className="mt-1 text-[11px] text-ink/45">Mehrfachauswahl möglich. Keine Auswahl = ohne Angebote.</p>
          </div>
        )}
        {/* Bild ist optional und zählt aufs monatliche Bild-Kontingent – pro Rezept abwählbar. */}
        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <input type="checkbox" checked={bildWunsch} onChange={(e) => setBildWunsch(e.target.checked)} className="mt-0.5 h-4 w-4 accent-terracotta" />
          <span>
            <span className="inline-flex items-center gap-1"><Icon name="image" size={16} /> Bild zum Rezept erzeugen</span>
            <span className="block text-[11px] text-ink/45">Zählt auf dein monatliches Bild-Kontingent. Du kannst jederzeit später eines erzeugen oder ein eigenes Foto hochladen.</span>
          </span>
        </label>
        <p className="text-xs text-ink/45">Heutige Küchengeräte und die Vorlieben/Allergien des Haushalts werden immer beachtet.</p>

        <Button variant="ki" onClick={generieren} disabled={busy} className="w-full">
          {busy ? <Spinner /> : (rezept ? <span className="inline-flex items-center gap-1"><Icon name="recycle" size={16} /> Neu generieren</span> : <span className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /> Rezept generieren</span>)}
        </Button>

        {busy && (
          <div className="space-y-1.5">
            <div className="ladebalken-track h-2 w-full rounded-full bg-terracotta/15">
              <div className="ladebalken-bar bg-terracotta" />
            </div>
            <p className="inline-flex w-full flex-wrap items-center justify-center gap-1 text-center text-xs text-ink/55"><Icon name="chef-hat" size={16} /> Dein Rezept wird erstellt … das dauert ein paar Sekunden</p>
          </div>
        )}

        {rezept && (
          <div className="space-y-3 rounded-xl border border-terracotta/30 bg-terracotta/5 p-3">
            <div>
              <h4 className="font-dish text-2xl leading-tight">{rezept.name}</h4>
              {rezept.beschreibung && <p className="mt-0.5 text-sm text-ink/70">{rezept.beschreibung}</p>}
              <p className="mt-1 text-xs text-ink/50">
                {[rezept.portionen ? `${rezept.portionen} Portionen` : null, rezept.dauer_minuten ? `${rezept.dauer_minuten} min` : null].filter(Boolean).join(' · ')}
              </p>
              {rezept.hinweis && <p className="mt-1 inline-flex items-center gap-1 text-xs italic text-olive"><Icon name="lightbulb" size={16} /> {rezept.hinweis}</p>}
            </div>

            {rezept.zutaten?.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-ink/55">Zutaten</p>
                <ul className="text-sm">
                  {rezept.zutaten.map((z, i) => {
                    const angs = zutatAngebote[z.name] || []
                    return (
                      <li key={i} className="border-b border-line/40 py-0.5">
                        <div className="flex justify-between">
                          <span className={z.optional ? 'text-ink/45' : ''}>{z.name}{z.optional ? ' (opt.)' : ''}</span>
                          <span className="text-ink/55">{z.menge != null ? `${fmtMenge(z.menge)} ${z.einheit || ''}` : ''}</span>
                        </div>
                        {angs.map((ang, j) => (
                          <div key={j} className="mt-0.5 text-xs text-olive">
                            {ang.status === 'vorrat'
                              ? <span className="inline-flex items-center gap-1"><Icon name="check" size={16} /> im Vorrat</span>
                              : <><Icon name="tag" size={16} className="inline align-text-bottom" /> im Angebot: {ang.artikel}
                                  {ang.preis_angebot != null ? ` – ${fmtPreis(ang.preis_angebot)}${ang.einheit ? ' / ' + ang.einheit : ''}` : ''}
                                  {ang.haendler ? ` (${ang.haendler})` : ''}</>}
                          </div>
                        ))}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {rezept.zubereitung?.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-ink/55">Zubereitung</p>
                <ol className="space-y-1 text-sm text-ink/80">
                  {rezept.zubereitung.map((k, i) => (
                    <li key={i}>
                      {k.titel && <span className="font-semibold">{k.titel}: </span>}
                      {(k.varianten?.[0]?.text || '')}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {savedId && (
              <div className="flex items-center gap-2 rounded-lg bg-olive/12 px-3 py-2 text-sm font-semibold text-olive">
                <Icon name="check" size={16} /> „{rezept.name}" ist in deiner Rezept-Bibliothek gespeichert
              </div>
            )}

            {!planOffen ? (
              <div className="flex flex-wrap gap-2">
                <Button onClick={uebernehmen} disabled={!!savedId}>{savedId ? <span className="inline-flex items-center gap-1"><Icon name="check" size={16} /> Gespeichert</span> : <span className="inline-flex items-center gap-1"><Icon name="download" size={16} /> In Bibliothek</span>}</Button>
                <Button variant="ghost" onClick={() => setPlanOffen(true)}><span className="inline-flex items-center gap-1"><Icon name="calendar" size={16} /> Einplanen</span></Button>
                {savedId && openRezept && <Button variant="ghost" onClick={() => { onClose(); openRezept(savedId) }}>Öffnen</Button>}
                {savedId && <Button variant="ghost" onClick={bildNeu} disabled={bildBusy}>{bildBusy ? <Spinner /> : (bildWunsch
                  ? <span className="inline-flex items-center gap-1"><Icon name="refresh" size={16} /> Bild neu</span>
                  : <span className="inline-flex items-center gap-1"><Icon name="image" size={16} /> Bild erzeugen</span>)}</Button>}
              </div>
            ) : (
              <div className="space-y-2 rounded-lg bg-card/70 p-2">
                <div className="flex gap-2">
                  <input className={input} type="date" value={planDatum} onChange={(e) => setPlanDatum(e.target.value)} />
                  <select className={input} value={planMahlzeit} onChange={(e) => setPlanMahlzeit(e.target.value)}>
                    {MAHLZEITEN.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setPlanOffen(false)}>Zurück</Button>
                  <Button onClick={einplanen}>Einplanen</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
