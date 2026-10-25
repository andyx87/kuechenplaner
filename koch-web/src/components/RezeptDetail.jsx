import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Spinner, Button } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { ZubereitungAnsicht } from './Rezepte.jsx'
import GuidedCooking from './GuidedCooking.jsx'
import { getVorratAktiv } from '../settings.js'

function fmt(m) {
  const n = Number(m)
  return Number.isInteger(n) ? n : Math.round(n * 100) / 100
}

const STERN_VOLL = '#d4a454'
const STERN_LEER = '#d1c5b4'

// Volle Rezept-Anzeige (wiederverwendbar): Tags, Sterne, Zutaten mit Vorrat-Status
// (check / alert-triangle / x, "danach noch X"), Einkaufslisten-Button und Zubereitung.
// Mengen werden auf `portionen` skaliert (Basis = detail.portionen).
export function RezeptDetailInhalt({ detail, portionen, notify, heuteNamen: heuteNamenProp }) {
  const vorratAktiv = getVorratAktiv()
  const [vorratCheck, setVorratCheck] = useState(null)
  const [heuteNamen, setHeuteNamen] = useState(() => heuteNamenProp || new Set())
  const [angebote, setAngebote] = useState([])
  const [listeOffen, setListeOffen] = useState(false)
  const [checked, setChecked] = useState(null)         // Set<zutat_id> – ausgewählt
  const [marke, setMarke] = useState(() => new Set())  // Set<zutat_id> – als Markenprodukt kaufen
  const [adding, setAdding] = useState(false)
  const [guidedOffen, setGuidedOffen] = useState(false)

  const basis = detail?.portionen || 1
  const ziel = portionen || basis
  const faktor = basis ? ziel / basis : 1
  const sterne = detail?.bewertung?.sterne || detail?.sterne || 0

  useEffect(() => {
    if (!detail?.id) return
    setVorratCheck(null); setChecked(null); setMarke(new Set()); setListeOffen(false)
    // Verfügbarkeits-Check nur bei aktiver Vorratsverwaltung.
    if (vorratAktiv) api.rezeptVorratCheck(detail.id).then(setVorratCheck).catch(() => setVorratCheck({ zutaten: [] }))
  }, [detail?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (heuteNamenProp) { setHeuteNamen(heuteNamenProp); return }
    api.geraeteHeute().then((gs) => setHeuteNamen(new Set(gs.map((g) => g.name)))).catch(() => {})
  }, [heuteNamenProp])

  useEffect(() => {
    api.angebote().then((a) => setAngebote(a || [])).catch(() => setAngebote([]))
  }, [])

  // Bestes Angebot (niedrigster Angebotspreis) je Master-Zutat.
  const angebotProMaster = useMemo(() => {
    const m = new Map()
    for (const a of angebote) {
      if (a.master_zutat_id == null) continue
      const prev = m.get(a.master_zutat_id)
      if (!prev || (a.preis_angebot ?? Infinity) < (prev.preis_angebot ?? Infinity)) m.set(a.master_zutat_id, a)
    }
    return m
  }, [angebote])

  // Vorrat-Status einer Zutat, skaliert auf die Zielportionen.
  function statusFuer(z) {
    const scaled = z.menge != null ? z.menge * faktor : null
    if (!vorratAktiv) return { scaled, ci: null, sameUnit: false, status: 'aus' }
    const ci = vorratCheck?.zutaten?.find((c) => c.zutat_id === z.zutat_id)
    const sameUnit = !!ci && (ci.vorhanden_einheit || '').toLowerCase() === (z.einheit || '').toLowerCase()
    let status
    if (!ci || ci.vorhanden_menge == null) status = 'fehlt'
    else if (sameUnit) status = ci.vorhanden_menge >= (scaled || 0) ? 'ok' : 'knapp'
    else status = ci.status === 'aehnlich' ? 'aehnlich' : 'vorhanden'
    return { scaled, ci, sameUnit, status }
  }
  const istFehlend = (s) => s === 'fehlt' || s === 'knapp'
  // Konflikt: Bestand vorhanden, aber Einheit nicht vergleichbar (z.B. Rezept in EL,
  // Vorrat in g) oder nur Namens-/Aehnlichkeits-Treffer -> Deckung unklar.
  const istKonflikt = (s) => s === 'vorhanden' || s === 'aehnlich'

  // Default-Auswahl: mit Vorrat nur fehlende, ohne Vorratsverwaltung alle nicht-optionalen.
  useEffect(() => {
    if (checked !== null || !detail) return
    if (vorratAktiv && !vorratCheck) return  // auf Check warten
    const sel = new Set()
    for (const z of detail.zutaten || []) {
      if (z.optional) continue
      if (!vorratAktiv || istFehlend(statusFuer(z).status)) sel.add(z.zutat_id)
    }
    setChecked(sel)
  }, [vorratCheck, detail?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  function toggleCheck(id) {
    setChecked((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function toggleMarke(id) {
    setMarke((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function aufEinkaufsliste() {
    const items = []
    for (const z of detail.zutaten || []) {
      if (!checked?.has(z.zutat_id)) continue
      const { scaled, ci, sameUnit, status } = statusFuer(z)
      let menge = scaled
      if (status === 'knapp' && sameUnit && ci?.vorhanden_menge != null) menge = Math.max(0, (scaled || 0) - ci.vorhanden_menge)
      // Standard: Master-Zutat. Nur wenn explizit angehakt: das Markenprodukt aus dem Angebot.
      const ang = angebotProMaster.get(z.master_zutat_id)
      const name = ang && marke.has(z.zutat_id) ? ang.name : (z.master_name || z.zutat)
      items.push({ name, menge: menge != null ? Math.round(menge * 100) / 100 : null, einheit: z.einheit || null, rezept_id: detail.id })
    }
    if (!items.length) { notify && notify('Nichts ausgewählt'); return }
    setAdding(true)
    try {
      await api.einkaufExtraHinzufuegen(items)
      notify && notify(`${items.length} Artikel auf die Einkaufsliste gesetzt`)
      setListeOffen(false)
    } catch {
      notify && notify('Auf die Liste setzen fehlgeschlagen', 'err')
    } finally {
      setAdding(false)
    }
  }

  if (!detail) return null

  return (
    <div className="space-y-3">
      {detail.beschreibung && <p className="text-sm text-muted">{detail.beschreibung}</p>}

      <div className="flex flex-wrap items-center gap-2">
        {detail.dauer_minuten ? <span className="inline-flex items-center gap-1.5 rounded-xl bg-surface px-2.5 py-1.5 font-mono text-xs text-muted"><Icon name="timer" size={14} /> {detail.dauer_minuten} MIN</span> : null}
        {detail.geraete?.map((g) => (
          <span key={g.geraet_id} className="inline-flex items-center rounded-xl bg-olive/15 px-2.5 py-1.5 font-mono text-xs text-olive">{g.geraet}</span>
        ))}
        {sterne > 0 && (
          <span className="ml-auto inline-flex items-center gap-0.5 whitespace-nowrap" title={`${sterne} Stern${sterne !== 1 ? 'e' : ''}`}>
            {Array.from({ length: sterne }).map((_, i) => <Icon key={`v${i}`} name="star" size={16} fill="currentColor" style={{ color: STERN_VOLL }} />)}
            {Array.from({ length: 5 - sterne }).map((_, i) => <Icon key={`l${i}`} name="star" size={16} style={{ color: STERN_LEER }} />)}
          </span>
        )}
      </div>

      <p className="font-mono text-xs text-muted">
        für <span className="font-bold text-ink">{fmt(ziel)}</span> Portion{ziel !== 1 ? 'en' : ''}
        <span className="text-muted2"> · Basis: {fmt(basis)}</span>
      </p>

      {(detail.zubereitung?.length > 0 || (detail.anleitung || '').trim()) && (
        <Button onClick={() => setGuidedOffen(true)} className="w-full">
          <Icon name="chef-hat" size={16} /> Schritt für Schritt kochen
        </Button>
      )}
      {guidedOffen && (
        <GuidedCooking
          detail={detail}
          portionen={ziel}
          heuteNamen={heuteNamen}
          notify={notify}
          onClose={() => setGuidedOffen(false)}
        />
      )}

      <div>
        <div className="mb-1 flex items-center gap-2">
          <h4 className="label-mono text-muted2">Zutaten</h4>
          {vorratAktiv && !vorratCheck && <Spinner />}
        </div>
        <ul className="text-sm">
          {detail.zutaten?.map((z) => {
            const scaled = z.menge != null ? z.menge * faktor : null
            const ci = vorratCheck?.zutaten?.find((c) => c.zutat_id === z.zutat_id)
            const optional = z.optional
            const ang = angebotProMaster.get(z.master_zutat_id)
            const angRabatt = ang && ang.preis_normal && ang.preis_angebot
              ? Math.round((1 - ang.preis_angebot / ang.preis_normal) * 100) : null
            const status = ci
              ? ci.vorhanden_menge === null
                ? 'fehlt'
                : (ci.vorhanden_einheit || '').toLowerCase() === (ci.einheit || '').toLowerCase()
                  ? ci.vorhanden_menge >= (scaled || 0) ? 'ok' : 'knapp'
                  : ci.status === 'aehnlich' ? 'aehnlich' : 'vorhanden'
              : null
            const vorhanden = status === 'ok' || status === 'vorhanden'
            return (
              <li key={z.zutat_id} className="flex items-start gap-3 border-b border-line/60 py-3">
                {vorhanden
                  ? <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-olive text-on-accent"><Icon name="check" size={13} /></span>
                  : <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-[1.6px] border-line ${(status === 'knapp' || status === 'aehnlich') ? 'text-terracotta' : status === 'fehlt' && !optional ? 'text-terracotta-deep' : ''}`}>
                      {(status === 'knapp' || status === 'aehnlich') && <Icon name="alert-triangle" size={13} />}
                      {status === 'fehlt' && !optional && <Icon name="x" size={13} />}
                    </span>}
                <span className="flex flex-1 flex-col gap-0.5">
                  <span className={optional ? 'text-muted2' : 'text-ink'}>{z.zutat}{optional ? ' (opt.)' : ''}</span>
                  {ang && !optional && (
                    <span className="inline-flex items-center gap-1 font-mono text-xs text-olive"><Icon name="tag" size={14} /> im Angebot: {ang.name}{angRabatt ? ` (−${angRabatt}%)` : ''} · {ang.haendler}</span>
                  )}
                </span>
                <span className="flex flex-col items-end text-right">
                  {scaled != null ? <span className="font-mono text-sm text-ink">{fmt(scaled)} {z.einheit}</span> : null}
                  {ci && (() => {
                    const sameUnit = (ci.vorhanden_einheit || '').toLowerCase() === (z.einheit || '').toLowerCase()
                    const rem = sameUnit && ci.vorhanden_menge != null ? ci.vorhanden_menge - (scaled || 0) : null
                    if (status === 'fehlt') return <span className="font-mono text-xs text-terracotta-deep">nicht vorhanden</span>
                    if (status === 'aehnlich') return <span className="font-mono text-xs text-muted2">≈ {ci.matched_name}</span>
                    if (!sameUnit && ci.vorhanden_menge != null) return <span className="font-mono text-xs text-muted2">{fmt(ci.vorhanden_menge)} {ci.vorhanden_einheit} da</span>
                    if (rem != null && rem >= 0) return <span className="font-mono text-xs text-olive">Rest {fmt(rem)} {z.einheit} im Vorrat</span>
                    if (rem != null) return <span className="font-mono text-xs font-bold text-terracotta">fehlt {fmt(-rem)} {z.einheit}</span>
                    return null
                  })()}
                </span>
              </li>
            )
          })}
        </ul>
        {(vorratCheck || !vorratAktiv) && !listeOffen && (
          <button
            onClick={() => setListeOffen(true)}
            className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-xl border border-terracotta/40 px-3 py-2 text-sm font-semibold text-terracotta hover:bg-terracotta/10"
          >
            <Icon name="shopping-cart" size={16} /> Zutaten auf die Einkaufsliste …
          </button>
        )}
        {(vorratCheck || !vorratAktiv) && listeOffen && (
          <div className="mt-2 rounded-xl border border-terracotta/30 bg-terracotta/5 p-3">
            <p className="mb-2 text-xs text-ink/55">
              {vorratAktiv
                ? <>Angehakte Zutaten kommen auf die Einkaufsliste – fehlende sind vorausgewählt. Bei <b>Einheiten-/Mengenkonflikt</b> (<Icon name="alert-triangle" size={16} className="inline align-text-bottom" />, ganz oben) ist nichts vorausgewählt: Bestand vorhanden, aber andere Einheit – prüfe selbst und hake bei Bedarf an. Im Angebot kannst du das Markenprodukt nehmen.</>
                : 'Angehakte Zutaten kommen auf die Einkaufsliste (alle vorausgewählt). Im Angebot kannst du das Markenprodukt nehmen.'}
            </p>
            <ul className="space-y-1.5">
              {[...(detail.zutaten || [])]
                .map((z) => ({ z, st: statusFuer(z).status }))
                .sort((a, b) => {
                  const rang = (s) => (istKonflikt(s) ? 0 : istFehlend(s) ? 1 : 2)
                  return rang(a.st) - rang(b.st)
                })
                .map(({ z, st: status }) => {
                const { scaled } = statusFuer(z)
                const konflikt = istKonflikt(status)
                const ang = angebotProMaster.get(z.master_zutat_id)
                const an = !!checked?.has(z.zutat_id)
                const rabatt = ang && ang.preis_normal && ang.preis_angebot
                  ? Math.round((1 - ang.preis_angebot / ang.preis_normal) * 100) : null
                return (
                  <li key={z.zutat_id} className="border-b border-line/40 pb-1.5 last:border-0 last:pb-0">
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={an} onChange={() => toggleCheck(z.zutat_id)} className="h-4 w-4 shrink-0 accent-terracotta" />
                      <span className="flex-1">
                        {status === 'fehlt' && <Icon name="x" size={16} className="mr-1 inline align-text-bottom text-terracotta-deep" />}
                        {status === 'knapp' && <Icon name="alert-triangle" size={16} className="mr-1 inline align-text-bottom text-terracotta" />}
                        {konflikt && <Icon name="alert-triangle" size={16} className="mr-1 inline align-text-bottom text-terracotta" />}
                        {status === 'ok' && <Icon name="check" size={16} className="mr-1 inline align-text-bottom text-olive" />}
                        <span className={z.optional ? 'text-ink/45' : ''}>{z.zutat}{z.optional ? ' (opt.)' : ''}</span>
                      </span>
                      {scaled != null && <span className="whitespace-nowrap text-ink/55">{fmt(scaled)} {z.einheit}</span>}
                    </label>
                    {konflikt && (
                      <p className="ml-6 mt-0.5 inline-flex items-center gap-1 text-xs font-semibold text-terracotta"><Icon name="alert-triangle" size={16} /> Einheiten-/Mengenkonflikt – Bestand vorhanden, aber andere Einheit. Nicht vorausgewählt.</p>
                    )}
                    {ang && an && (
                      <label className="ml-6 mt-1 flex items-start gap-2 text-xs text-olive">
                        <input type="checkbox" checked={marke.has(z.zutat_id)} onChange={() => toggleMarke(z.zutat_id)} className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-olive" />
                        <span className="inline-flex items-center gap-1"><Icon name="tag" size={16} /> Im Angebot: <span className="font-semibold">{ang.name}</span>{rabatt ? ` (−${rabatt}%)` : ''} – als Markenprodukt kaufen</span>
                      </label>
                    )}
                  </li>
                )
              })}
            </ul>
            <div className="mt-3 flex gap-2">
              <button onClick={() => setListeOffen(false)} className="flex-1 rounded-xl border border-line px-3 py-2 text-sm font-semibold text-ink/60 hover:bg-line/20">Abbrechen</button>
              <button
                onClick={aufEinkaufsliste}
                disabled={adding || !checked?.size}
                className="flex-1 rounded-xl bg-terracotta px-3 py-2 text-sm font-semibold text-on-accent hover:opacity-90 disabled:opacity-40"
              >
                {adding ? '…' : `${checked?.size || 0} hinzufügen`}
              </button>
            </div>
          </div>
        )}
      </div>

      {detail.zubereitung && detail.zubereitung.length > 0 ? (
        <div>
          <h4 className="mb-2 label-mono text-muted2">Zubereitung</h4>
          <ZubereitungAnsicht key={detail.id} komponenten={detail.zubereitung} heuteNamen={heuteNamen} />
        </div>
      ) : (
        detail.anleitung && (
          <div>
            <h4 className="mb-1 label-mono text-muted2">Zubereitung</h4>
            <p className="whitespace-pre-wrap text-sm text-muted">{detail.anleitung.replace(/\\n/g, '\n')}</p>
          </div>
        )
      )}
    </div>
  )
}
