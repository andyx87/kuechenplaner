import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'
import { Button, input, Spinner } from '../ui.jsx'
import { preiseVergessen } from '../preise.js'

// Super-Admin: Tarif-Definitionen (Preis, Aufschlag %, Tages-/Wochenvolumen).
// Beträge in € (intern Cent), Aufschlag in %. Tages-/Wochenvolumen leer = kein Limit.
const eur = (c) => (c == null ? '' : (c / 100).toString().replace('.', ','))
const num = (s) => Number(String(s).replace(',', '.'))
const toC = (s) => (String(s).trim() === '' ? null : Math.round(num(s) * 100))

export default function AdminTarife({ notify }) {
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.adminTarife()
      .then((d) => setRows(d.map((t) => ({
        code: t.code, name: t.name, ist_payg: t.ist_payg, aktiv: t.aktiv, sortierung: t.sortierung,
        preis: eur(t.preis_cents), markup: String(Math.round(t.markup_prozent)),
        tag: eur(t.tages_limit_cents), woche: eur(t.wochen_limit_cents),
        // Monatskontingente des Abo-Modells: leer = unbegrenzt
        kiLimit: t.monats_ki_limit == null ? '' : String(t.monats_ki_limit),
        bildLimit: t.monats_bild_limit == null ? '' : String(t.monats_bild_limit),
      })))).catch(() => notify('Tarife laden fehlgeschlagen', 'err'))
  }, [notify])

  function upd(i, k, v) { setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r))) }

  async function speichern() {
    // Rohwerte prüfen, BEVOR NaN via "|| 0" bzw. JSON.stringify(NaN)=null still
    // zu 0 € / gelöschtem Limit wird. Leeres Limit-Feld = kein Limit (erlaubt),
    // aber ein ungültiger Eintrag (z. B. "1,2x") darf nicht das Limit löschen.
    const ungueltig = rows.some((r) => {
      const preis = r.ist_payg ? 0 : num(r.preis)   // PAYG hat keinen Grundpreis
      const markup = num(r.markup)
      const tag = toC(r.tag)                          // null = leer/kein Limit
      const woche = toC(r.woche)
      if (!r.ist_payg && (Number.isNaN(preis) || preis < 0)) return true
      if (Number.isNaN(markup) || markup < 0) return true
      if (tag !== null && (Number.isNaN(tag) || tag < 0)) return true
      if (woche !== null && (Number.isNaN(woche) || woche < 0)) return true
      // Monatskontingente: leer = unbegrenzt, sonst ganze Zahl >= 0
      for (const s of [r.kiLimit, r.bildLimit]) {
        if (String(s).trim() === '') continue
        const n = num(s)
        if (Number.isNaN(n) || n < 0 || !Number.isInteger(n)) return true
      }
      return false
    })
    if (ungueltig) {
      notify('Bitte gültige Zahlen eingeben (Limit-Feld leer lassen = kein Limit)', 'err'); return
    }
    const ganz = (s) => (String(s).trim() === '' ? null : Math.round(num(s)))
    const payload = rows.map((r) => ({
      code: r.code, name: r.name, aktiv: r.aktiv, sortierung: r.sortierung,
      preis_cents: r.ist_payg ? 0 : (toC(r.preis) || 0), markup_prozent: num(r.markup),
      tages_limit_cents: toC(r.tag), wochen_limit_cents: toC(r.woche),
      monats_ki_limit: ganz(r.kiLimit), monats_bild_limit: ganz(r.bildLimit),
    }))
    setBusy(true)
    try {
      await api.adminTarifeSetzen(payload)
      // Preisliste im Frontend neu holen – sonst zeigen die Texte die alten Zahlen.
      preiseVergessen()
      notify('Tarife gespeichert')
    } catch { notify('Speichern fehlgeschlagen', 'err') }
    finally { setBusy(false) }
  }

  if (!rows) return null

  return (
    <div className="rounded-xl border border-terracotta/40 bg-terracotta/5 p-3">
      <p className="mb-2 inline-flex items-center gap-1.5 font-display text-sm"><Icon name="sliders" size={16} /> Tarife <span className="text-xs font-normal text-muted">(Super-Admin)</span></p>
      <p className="mb-2 text-[11px] text-muted">Aufschlag = Token-/Bild-Marge der Stufe. Tages-/Wochenvolumen = inkludierte Nutzung (Verbrauch inkl. Aufschlag); leer = kein Limit. Pay-as-you-go: nur Aufschlag relevant.</p>
      <div className="space-y-3">
        {rows.map((r, i) => (
          <div key={r.code} className="rounded-lg border border-line bg-paper/60 p-2.5">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <input className={input + ' flex-1'} value={r.name} onChange={(e) => upd(i, 'name', e.target.value)} />
              <label className="flex shrink-0 items-center gap-1 text-xs text-muted">
                <input type="checkbox" checked={r.aktiv} onChange={(e) => upd(i, 'aktiv', e.target.checked)} /> aktiv
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">Preis/Mon.</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="decimal" disabled={r.ist_payg} value={r.preis} onChange={(e) => upd(i, 'preis', e.target.value)} /><span className="text-muted2">€</span></span>
              </label>
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">Aufschlag</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="decimal" value={r.markup} onChange={(e) => upd(i, 'markup', e.target.value)} /><span className="text-muted2">%</span></span>
              </label>
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">Tagesvol.</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="decimal" disabled={r.ist_payg} value={r.tag} onChange={(e) => upd(i, 'tag', e.target.value)} placeholder="—" /><span className="text-muted2">€</span></span>
              </label>
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">Wochenvol.</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="decimal" disabled={r.ist_payg} value={r.woche} onChange={(e) => upd(i, 'woche', e.target.value)} placeholder="—" /><span className="text-muted2">€</span></span>
              </label>
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">KI/Monat</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="numeric" value={r.kiLimit} onChange={(e) => upd(i, 'kiLimit', e.target.value)} placeholder="∞" /><span className="text-muted2">Stk.</span></span>
              </label>
              <label className="flex items-center justify-between gap-1">
                <span className="text-muted">Bilder/Monat</span>
                <span className="flex items-center gap-1"><input className={input + ' !w-16 text-right font-mono'} inputMode="numeric" value={r.bildLimit} onChange={(e) => upd(i, 'bildLimit', e.target.value)} placeholder="∞" /><span className="text-muted2">Stk.</span></span>
              </label>
            </div>
          </div>
        ))}
      </div>
      <Button onClick={speichern} disabled={busy} className="mt-3 w-full">
        {busy ? <Spinner /> : 'Tarife speichern'}
      </Button>
    </div>
  )
}
