import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { Modal, Button, input, Spinner, confirmDialog } from '../ui.jsx'
import { isoHeute } from '../utils.js'
import { getVorratAktiv, getAbhakModus } from '../settings.js'
import { posKey, ladeErledigt, speichereErledigt, bereinigeErledigt } from '../einkaufErledigt.js'
import { Icon } from '../icons.jsx'

function fmt(m) {
  if (m == null) return ''
  const n = Number(m)
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '').replace('.', ',')
}

// Erledigte (übernommene/abgehakte) Positionen: Schlüsselformat und Speicherung liegen
// zentral in einkaufErledigt.js – identisch mit dem Warenkorb-Badge in App.jsx.

// ── Einkaufsliste (geplant nach Einkaufstagen + manuell) ──
// Zwei Abhak-Modi (per Einstellung wählbar):
//  · popup  – Klick auf die Checkbox fragt je Artikel die gekaufte Menge ab.
//  · inline – Menge je Artikel direkt in der Liste editierbar, ein Sammel-Button
//             am Ende übernimmt alle nicht übersprungenen Artikel in den Vorrat.
export default function Einkaufsliste({ datum, nurNaechster = false, onClose, notify, vorratAktiv, abhakModus }) {
  const vorratOn = vorratAktiv ?? getVorratAktiv()
  const modus = abhakModus ?? getAbhakModus()
  const heute = isoHeute()
  const d = datum || heute
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [alleZeigen, setAlleZeigen] = useState(!nurNaechster)
  const [neuerArtikel, setNeuerArtikel] = useState('')
  const [extraBusy, setExtraBusy] = useState(false)
  const [genBusy, setGenBusy] = useState(false)               // "Geplante Rezepte übernehmen"
  // "done" → aus Liste gefiltert; beim Öffnen abgelaufene Haken (Einkaufstag vorbei) räumen
  const [erledigt, setErledigt] = useState(() => bereinigeErledigt(ladeErledigt(), isoHeute()))
  const [mengen, setMengen] = useState({})                    // key → editierte Menge (inline)
  const [uebersprungen, setUebersprungen] = useState(() => new Set()) // key (inline: nicht in Vorrat)
  const [mengeDialog, setMengeDialog] = useState(null)        // {key,name,einheit,menge,type,manualId,zutatId} – Popup
  const [uebernahmeBusy, setUebernahmeBusy] = useState(false)
  const [sammelBusy, setSammelBusy] = useState(false)
  const [marktEdit, setMarktEdit] = useState(false)
  const [marktOptionen, setMarktOptionen] = useState([])
  const [marktAuswahl, setMarktAuswahl] = useState([])
  const [marktBusy, setMarktBusy] = useState(false)

  const lade = useCallback(() => {
    return api.einkaufsliste(d)
      .then(setData)
      .catch(() => notify('Einkaufsliste laden fehlgeschlagen', 'err'))
  }, [d, notify])

  useEffect(() => { lade().finally(() => setLoading(false)) }, [lade])

  // Nächster Einkaufstag ab heute (für Markt + Angebots-Logik).
  const naechsterEinkauf = data?.perioden?.find((p) => p.ist_einkaufstag && p.von >= heute) || null
  const aktMarkt = naechsterEinkauf?.markt || null

  async function oeffneMarktEdit() {
    if (!naechsterEinkauf) return
    try {
      const m = await api.angeboteMaerkte(naechsterEinkauf.von)
      setMarktOptionen((m || []).map((x) => (typeof x === 'string' ? x : (x.haendler || x.name))).filter(Boolean))
    } catch { setMarktOptionen([]) }
    setMarktAuswahl(aktMarkt ? aktMarkt.split(',').map((s) => s.trim()).filter(Boolean) : [])
    setMarktEdit(true)
  }
  function toggleMarkt(h) {
    setMarktAuswahl((a) => (a.includes(h) ? a.filter((x) => x !== h) : [...a, h]))
  }
  async function speichereMarkt() {
    if (!naechsterEinkauf) return
    setMarktBusy(true)
    try {
      await api.einkaufstagHaendler(naechsterEinkauf.von, marktAuswahl)
      setMarktEdit(false)
      await lade()
      notify('Markt aktualisiert')
    } catch { notify('Markt speichern fehlgeschlagen', 'err') } finally { setMarktBusy(false) }
  }
  const einkaufDatum = naechsterEinkauf?.von || null

  function angebotBadge(a) {
    if (!a) return null
    const preis = a.preis_angebot != null ? ` ${fmt(a.preis_angebot)} €` : ''
    const hdl = a.haendler ? ` · ${a.haendler}` : ''
    return <span className="ml-1 inline-flex items-center gap-1 rounded bg-terracotta/15 px-1.5 py-0.5 text-[10px] font-semibold text-terracotta-deep align-middle"><Icon name="tag" size={16} className="text-terracotta-deep" /> {a.name}{preis}{hdl}</span>
  }

  function markDone(keys) {
    setErledigt((prev) => {
      const next = new Set(prev)
      keys.forEach((k) => next.add(k))
      speichereErledigt(next)
      return next
    })
  }

  // Ohne Vorratsverwaltung gibt es nur einfaches Abhaken (kein Popup, kein Inline-Übernehmen).
  const effModus = vorratOn ? modus : 'popup'

  // Relevante Perioden: bei nurNaechster nur die nächste Einkaufs-Periode ab heute
  const perioden = (() => {
    if (!data?.perioden) return []
    if (alleZeigen) return data.perioden
    const naechste = data.perioden.find(p => p.ist_einkaufstag && p.von >= heute)
    return naechste ? [naechste] : data.perioden
  })()

  // Sichtbare Items je Periode (erledigte herausgefiltert).
  function itemsOf(periode) {
    return periode.positionen
      .map((pos) => ({
        key: posKey(periode, pos),
        name: pos.zutat, einheit: pos.einheit, planMenge: pos.kaufen,
        type: 'computed', zutatId: pos.zutat_id, angebot: pos.angebot || null,
      }))
      .filter((it) => !erledigt.has(it.key))
  }
  const manualItems = (data?.manuell || [])
    .map((m) => ({ key: `extra:${m.id}`, name: m.name, einheit: m.einheit, planMenge: m.menge, type: 'manual', manualId: m.id }))
    .filter((it) => !erledigt.has(it.key))
  const alleSichtbar = [...perioden.flatMap(itemsOf), ...manualItems]
  const offeneAnzahl = alleSichtbar.filter((it) => !uebersprungen.has(it.key)).length

  // ── Popup-Modus ──
  function popupStart(item) {
    setMengeDialog({ ...item, menge: item.planMenge != null ? fmt(item.planMenge) : '' })
  }
  // Gemeinsamer Abschluss: optional in den Vorrat, dann aus der Liste entfernen.
  async function erledigeItem(item, vorrat /* {menge,einheit} | null */) {
    if (vorrat) await api.vorratHinzufuegen([{ name: item.name, menge: vorrat.menge, einheit: vorrat.einheit }])
    if (item.type === 'manual') { await api.einkaufExtraLoeschen(item.manualId); await lade() }
    else markDone([item.key])
  }
  async function popupNurAbhaken() {
    if (!mengeDialog) return
    setUebernahmeBusy(true)
    try { await erledigeItem(mengeDialog, null); setMengeDialog(null) }
    catch { notify('Abhaken fehlgeschlagen', 'err') }
    finally { setUebernahmeBusy(false) }
  }
  async function popupInVorrat() {
    if (!mengeDialog) return
    const menge = Number(String(mengeDialog.menge).replace(',', '.'))
    if (!menge || menge <= 0) { notify('Bitte eine gekaufte Menge eingeben', 'err'); return }
    setUebernahmeBusy(true)
    try {
      await erledigeItem(mengeDialog, { menge, einheit: mengeDialog.einheit || 'Stück' })
      notify(`${mengeDialog.name}: ${fmt(menge)} ${mengeDialog.einheit || 'Stück'} in den Vorrat übernommen`)
      setMengeDialog(null)
    } catch {
      notify('Übernahme in den Vorrat fehlgeschlagen', 'err')
    } finally {
      setUebernahmeBusy(false)
    }
  }

  // ── Inline-Modus ──
  const mengeWert = (it) => (mengen[it.key] ?? (it.planMenge != null ? fmt(it.planMenge) : ''))
  const setMenge = (key, v) => setMengen((prev) => ({ ...prev, [key]: v }))
  function toggleSkip(key) {
    setUebersprungen((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  }

  async function sammelUebernahme() {
    const vorratItems = []
    const manualDeletes = []
    const doneKeys = []
    let skip = 0
    for (const it of alleSichtbar) {
      const sk = uebersprungen.has(it.key)
      if (sk) {
        skip++
        if (it.type === 'computed') doneKeys.push(it.key)
        else if (it.type === 'manual') manualDeletes.push(it.manualId)  // bewusst übersprungen → von Liste nehmen
        continue
      }
      const menge = Number(String(mengeWert(it)).replace(',', '.'))
      if (menge > 0) {
        vorratItems.push({ name: it.name, menge, einheit: it.einheit || 'Stück' })
        // Manuellen Artikel nur löschen, wenn er wirklich in den Vorrat übernommen wurde.
        if (it.type === 'manual') manualDeletes.push(it.manualId)
      }
      // Manueller Artikel ohne Menge: bleibt auf der Liste (kein stiller Datenverlust, F2).
    }
    if (!vorratItems.length && !manualDeletes.length && !doneKeys.length) return
    setSammelBusy(true)
    try {
      if (vorratItems.length) await api.vorratHinzufuegen(vorratItems)
      if (manualDeletes.length) await Promise.all(manualDeletes.map((id) => api.einkaufExtraLoeschen(id)))
      if (doneKeys.length) markDone(doneKeys)
      setUebersprungen(new Set())
      setMengen({})
      await lade()
      notify(`${vorratItems.length} in den Vorrat übernommen${skip ? `, ${skip} übersprungen` : ''}`)
    } catch {
      notify('Übernahme fehlgeschlagen', 'err')
    } finally {
      setSammelBusy(false)
    }
  }

  // ── Manuell ergänzte Artikel ──
  // Zutaten aller offenen (geplant, noch nicht gekocht, noch nicht im Wagen)
  // Rezepte der Woche auf die Liste holen.
  async function geplanteUebernehmen() {
    setGenBusy(true)
    try {
      const plan = await api.wochenplan(d)
      const offen = (plan || []).filter((e) => e.rezept_id && !e.gekocht && !e.im_warenkorb)
      // pro Rezept nur einmal übernehmen
      const rezeptIds = [...new Set(offen.map((e) => e.rezept_id))]
      if (!rezeptIds.length) {
        notify('Keine offenen geplanten Rezepte – alles schon im Wagen oder gekocht.')
        return
      }
      let n = 0
      for (const rid of rezeptIds) {
        try { await api.rezeptInWarenkorb(rid); n++ } catch { /* einzelne überspringen */ }
      }
      await lade()
      notify(`Zutaten aus ${n} Rezept${n === 1 ? '' : 'en'} auf die Liste gesetzt`)
    } catch {
      notify('Übernehmen fehlgeschlagen', 'err')
    } finally {
      setGenBusy(false)
    }
  }

  async function manuellHinzufuegen() {
    const name = neuerArtikel.trim()
    if (!name) return
    setExtraBusy(true)
    try { await api.einkaufExtraHinzufuegen([{ name }]); setNeuerArtikel(''); await lade() }
    catch { notify('Hinzufügen fehlgeschlagen', 'err') }
    finally { setExtraBusy(false) }
  }
  async function manuellLoeschen(it) {
    try {
      await api.einkaufExtraLoeschen(it.manualId)
      await lade()
      notify(`„${it.name}" entfernt`, 'ok', {
        label: 'Rückgängig',
        onClick: async () => {
          try { await api.einkaufExtraHinzufuegen([{ name: it.name, menge: it.planMenge, einheit: it.einheit }]); await lade() }
          catch { notify('Wiederherstellen fehlgeschlagen', 'err') }
        },
      })
    } catch { notify('Entfernen fehlgeschlagen', 'err') }
  }
  // Alle MANUELL ergänzten Artikel löschen.
  async function alleManuellLoeschen() {
    const ids = (data?.manuell || []).map((m) => m.id)
    if (!ids.length) return
    if (!(await confirmDialog(`Alle ${ids.length} manuell ergänzten Artikel löschen?`))) return
    try { await Promise.all(ids.map((id) => api.einkaufExtraLoeschen(id))); await lade(); notify('Manuelle Artikel gelöscht') }
    catch { notify('Löschen fehlgeschlagen', 'err') }
  }
  // Alle AUTOMATISCH (aus dem Plan) berechneten Positionen von der Liste nehmen (abhaken).
  async function alleGeplanteEntfernen() {
    const keys = perioden.flatMap(itemsOf).map((it) => it.key)
    if (!keys.length) return
    if (!(await confirmDialog('Alle automatisch geplanten Positionen von der Liste entfernen?'))) return
    markDone(keys)
    notify('Geplante Positionen entfernt')
  }
  // Ganzen Einkaufswagen leeren (automatisch + manuell).
  async function alleLeeren() {
    if (!(await confirmDialog('Den ganzen Einkaufswagen leeren (geplante + manuelle Artikel)?'))) return
    const keys = perioden.flatMap(itemsOf).map((it) => it.key)
    if (keys.length) markDone(keys)
    const ids = (data?.manuell || []).map((m) => m.id)
    try {
      if (ids.length) await Promise.all(ids.map((id) => api.einkaufExtraLoeschen(id)))
      await lade()
      notify('Einkaufswagen geleert')
    } catch { notify('Leeren fehlgeschlagen', 'err') }
  }

  // Eine Listenzeile – je nach Modus mit Checkbox (popup) oder Mengenfeld + Skip (inline).
  function zeile(it) {
    const sk = uebersprungen.has(it.key)
    return (
      <li key={it.key} className="flex items-center gap-2 border-b border-line/40 py-1 text-sm">
        {effModus === 'popup' ? (
          <>
            <input type="checkbox" checked={false} onChange={() => (vorratOn ? popupStart(it) : markDone([it.key]))} className="h-4 w-4 shrink-0 accent-olive" />
            <span className="flex-1"><span className="capitalize">{it.name}</span>{angebotBadge(it.angebot)}</span>
            <span className="font-mono text-xs text-muted">{fmt(it.planMenge)} {it.einheit}</span>
          </>
        ) : (
          <>
            <span className="flex-1">
              <span className={`capitalize ${sk ? 'text-ink/35 line-through' : ''}`}>{it.name}</span>
              {!sk && angebotBadge(it.angebot)}
              {sk && <span className="ml-2 rounded bg-ink/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink/50">nicht in Vorrat</span>}
            </span>
            {!sk && (
              <>
                <input
                  className={input + ' !w-16 px-2 py-1 text-right'}
                  inputMode="decimal"
                  value={mengeWert(it)}
                  onChange={(e) => setMenge(it.key, e.target.value)}
                />
                <span className="w-10 shrink-0 font-mono text-xs text-muted2">{it.einheit}</span>
              </>
            )}
            <button
              onClick={() => toggleSkip(it.key)}
              className={`shrink-0 rounded px-1 ${sk ? 'text-olive' : 'text-ink/30 hover:text-ink/70'}`}
              title={sk ? 'Doch in den Vorrat übernehmen' : 'Überspringen (nicht in den Vorrat)'}
            >{sk ? '↩' : '⊘'}</button>
          </>
        )}
        {it.type === 'manual' && (
          <button onClick={() => manuellLoeschen(it)} className="shrink-0 rounded px-1.5 text-ink/30 hover:text-terracotta-deep" title="Entfernen"><Icon name="x" size={16} /></button>
        )}
      </li>
    )
  }

  const titel = `Einkaufsliste ${data ? new Date(data.montag + 'T00:00:00').toLocaleDateString('de-DE', { day: 'numeric', month: 'short' }) + ' – ' + new Date(data.sonntag + 'T00:00:00').toLocaleDateString('de-DE', { day: 'numeric', month: 'short' }) : ''}`

  return (
    <>
    <Modal open onClose={onClose} title={titel}>
      {loading ? <div className="flex justify-center py-8"><Spinner /></div> : (
        <div className="space-y-4">
          {/* Nächster Einkaufstag + Markt – hier direkt änderbar */}
          {naechsterEinkauf && (
            <div className="rounded-xl border border-line bg-card/60 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1">
                  <Icon name="shopping-cart" size={16} /> Einkauf am <b>{new Date(naechsterEinkauf.von + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' })}</b>
                  {' · '}
                  {aktMarkt
                    ? <b className="text-terracotta">{aktMarkt}</b>
                    : <span className="text-ink/50">— ohne Markt —</span>}
                </span>
                {!marktEdit && (
                  <button onClick={oeffneMarktEdit} className="shrink-0 inline-flex items-center gap-1 rounded-full bg-line/40 px-2.5 py-1 text-xs font-semibold text-ink/70 hover:bg-line/70"><Icon name="pencil" size={16} /> Markt ändern</button>
                )}
              </div>
              {marktEdit && (
                <div className="mt-2 space-y-2 border-t border-line/50 pt-2">
                  <div className="flex flex-wrap gap-1.5">
                    {[...new Set([...marktOptionen, ...marktAuswahl])].map((h) => (
                      <button key={h} onClick={() => toggleMarkt(h)}
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${marktAuswahl.includes(h) ? 'bg-terracotta text-on-accent' : 'bg-line/40 text-ink/70 hover:bg-line/70'}`}>{h}</button>
                    ))}
                    {marktOptionen.length === 0 && marktAuswahl.length === 0 && (
                      <span className="text-xs text-ink/45">Keine Märkte mit Angeboten an dem Tag – unten eintippen.</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <input className={input + ' flex-1 py-1 text-sm'} placeholder="Anderen Markt eintippen + Enter"
                      onKeyDown={(e) => { const v = e.target.value.trim(); if (e.key === 'Enter' && v) { if (!marktAuswahl.includes(v)) setMarktAuswahl([...marktAuswahl, v]); e.target.value = '' } }} />
                    <Button onClick={speichereMarkt} disabled={marktBusy}>{marktBusy ? '…' : 'Speichern'}</Button>
                    <Button variant="ghost" onClick={() => setMarktEdit(false)}>Abbrechen</Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Zutaten aus geplanten Rezepten übernehmen – nur ohne Vorratsfunktion
              (mit Vorrat werden die Positionen automatisch berechnet). */}
          {!vorratOn && (
            <Button variant="ghost" onClick={geplanteUebernehmen} disabled={genBusy} className="w-full">
              {genBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="wand" size={16} /> Zutaten geplanter Rezepte auf die Liste</span>}
            </Button>
          )}

          {/* Liste leeren */}
          {alleSichtbar.length > 0 && (
            <div className="flex items-center justify-end gap-4 text-xs">
              {perioden.flatMap(itemsOf).length > 0 && (
                <button onClick={alleGeplanteEntfernen} className="text-ink/45 hover:text-terracotta-deep">Geplante entfernen</button>
              )}
              <button onClick={alleLeeren} className="inline-flex items-center gap-1 font-semibold text-terracotta-deep hover:underline"><Icon name="trash" size={16} /> Alles leeren</button>
            </div>
          )}

          {nurNaechster && !alleZeigen && data?.perioden && !data.perioden.find(p => p.ist_einkaufstag && p.von >= heute) && (
            <div className="rounded-xl bg-surface p-3 text-sm">
              <p className="font-semibold">Kein Einkaufstag in dieser Woche markiert.</p>
              <p className="mt-0.5 text-ink/60">Markiere Einkaufstage in der Wochenleiste oben.</p>
            </div>
          )}
          {nurNaechster && !alleZeigen && perioden.length > 0 && data?.perioden?.length > 1 && (
            <div className="flex items-center justify-between text-xs text-ink/45">
              <span>Nur nächster Einkauf ({new Date(perioden[0]?.von + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })})</span>
              <button onClick={() => setAlleZeigen(true)} className="text-terracotta hover:underline">Ganze Woche anzeigen</button>
            </div>
          )}

          {/* Manuell ergänzte Artikel – gehören zum nächsten Einkauf (oben) */}
          <div className="rounded-xl border border-line p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="inline-flex items-center gap-1 text-sm font-semibold"><Icon name="edit" size={18} /> Für den nächsten Einkauf</p>
              {manualItems.length > 0 && (
                <button onClick={alleManuellLoeschen} className="text-xs text-ink/45 hover:text-terracotta-deep">Alle löschen</button>
              )}
            </div>
            {manualItems.length > 0 && (
              <ul className="mb-2 space-y-1">{manualItems.map(zeile)}</ul>
            )}
            <div className="flex gap-2">
              <input
                className={input + ' flex-1'}
                value={neuerArtikel}
                placeholder="z.B. Klopapier, Spülmittel …"
                onChange={(e) => setNeuerArtikel(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') manuellHinzufuegen() }}
              />
              <Button onClick={manuellHinzufuegen} disabled={extraBusy || !neuerArtikel.trim()}>
                {extraBusy ? <Spinner /> : '+'}
              </Button>
            </div>
          </div>

          {perioden.map((periode, idx) => {
            const items = itemsOf(periode)
            return (
              <div key={idx} className="rounded-xl border border-line p-3">
                <div className="mb-2">
                  <p className="inline-flex items-center gap-1 font-semibold text-sm">
                    {periode.ist_einkaufstag ? <Icon name="shopping-cart" size={16} /> : null}
                    {new Date(periode.von + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })}
                    {' – '}
                    {new Date(periode.bis + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })}
                  </p>
                  <p className="font-mono text-xs text-muted2">{items.length} offene Positionen</p>
                </div>
                {items.length === 0 ? (
                  <p className="inline-flex items-center gap-1 text-sm text-olive"><Icon name="check" size={16} className="text-olive" /> Nichts offen</p>
                ) : (
                  <ul className="space-y-1">{items.map(zeile)}</ul>
                )}
              </div>
            )
          })}

          {/* Sammel-Übernahme (Inline-Modus) */}
          {effModus === 'inline' && alleSichtbar.length > 0 && (
            <Button onClick={sammelUebernahme} disabled={sammelBusy} className="w-full">
              {sammelBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="shopping-cart" size={16} /> {offeneAnzahl} Artikel in den Vorrat übernehmen</span>}
            </Button>
          )}

        </div>
      )}
    </Modal>

    {mengeDialog && (
      <Modal open onClose={() => setMengeDialog(null)} title={mengeDialog.name}>
        <div className="space-y-4">
          <p className="text-sm text-ink/60">Wie viel hast du gekauft? Die Menge wird in den Vorrat übernommen (ohne Lagerort).</p>
          <div className="flex gap-2">
            <input
              className={input + ' flex-1'}
              autoFocus
              inputMode="decimal"
              value={mengeDialog.menge}
              placeholder="Menge"
              onChange={(e) => setMengeDialog((m) => ({ ...m, menge: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') popupInVorrat() }}
            />
            <input
              className={input + ' !w-28'}
              value={mengeDialog.einheit}
              placeholder="Einheit"
              onChange={(e) => setMengeDialog((m) => ({ ...m, einheit: e.target.value }))}
            />
          </div>
          <div className="flex flex-col gap-2 pt-1">
            <Button onClick={popupInVorrat} disabled={uebernahmeBusy || !String(mengeDialog.menge).trim()}>
              {uebernahmeBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="check" size={16} /> In Vorrat übernehmen & abhaken</span>}
            </Button>
            <Button variant="ghost" onClick={popupNurAbhaken} disabled={uebernahmeBusy}>Nur abhaken (ohne Vorrat)</Button>
          </div>
        </div>
      </Modal>
    )}
    </>
  )
}
