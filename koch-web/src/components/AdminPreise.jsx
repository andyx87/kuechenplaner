import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { preiseVergessen } from '../preise.js'
import { Icon } from '../icons.jsx'

// Super-Admin: Plattform-Preise (Abo in €, API-Aufschlag in %).
export default function AdminPreise({ notify }) {
  const [p, setP] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.adminPreise()
      .then((d) => setP({
        einzel: (d.abo_einzel_cents / 100).toString().replace('.', ','),
        mehrere: (d.abo_mehrere_cents / 100).toString().replace('.', ','),
        markup: String(d.api_markup_prozent).replace('.', ','),
        overage: String(d.overage_markup_prozent ?? 65).replace('.', ','),
        bildSchnell: ((d.bild_schnell_cents ?? 5) / 100).toString().replace('.', ','),
        bildStandard: ((d.bild_standard_cents ?? 9) / 100).toString().replace('.', ','),
        packPreis: ((d.foto_pack_cents ?? 1299) / 100).toString().replace('.', ','),
        packCredits: String(d.foto_pack_credits ?? 75),
      }))
      .catch(() => notify('Preise laden fehlgeschlagen', 'err'))
  }, [notify])

  const num = (s) => Number(String(s).replace(',', '.'))

  async function speichern() {
    const einzelC = Math.round(num(p.einzel) * 100)
    const mehrereC = Math.round(num(p.mehrere) * 100)
    const markup = num(p.markup)
    const bildSchnellC = Math.round(num(p.bildSchnell) * 100)
    const bildStandardC = Math.round(num(p.bildStandard) * 100)
    const overage = num(p.overage)
    const packPreisC = Math.round(num(p.packPreis) * 100)
    const packCredits = Math.round(num(p.packCredits))
    if ([einzelC, mehrereC, markup, overage, bildSchnellC, bildStandardC, packPreisC].some((v) => Number.isNaN(v) || v < 0)) {
      notify('Bitte gültige Werte eingeben', 'err'); return
    }
    if (!Number.isFinite(packCredits) || packCredits < 1) {
      notify('Das Foto-Pack muss mindestens 1 Bild-Credit enthalten', 'err'); return
    }
    setBusy(true)
    try {
      await api.adminPreiseSetzen({
        abo_einzel_cents: einzelC, abo_mehrere_cents: mehrereC, api_markup_prozent: markup,
        overage_markup_prozent: overage,
        bild_schnell_cents: bildSchnellC, bild_standard_cents: bildStandardC,
        foto_pack_cents: packPreisC, foto_pack_credits: packCredits,
      })
      // Der Cache im Frontend hält die Preisliste – nach dem Speichern verwerfen,
      // sonst zeigen Onboarding/Limit-Dialog bis zum Reload die alten Zahlen.
      preiseVergessen()
      notify('Preise gespeichert')
    } catch { notify('Speichern fehlgeschlagen', 'err') }
    finally { setBusy(false) }
  }

  if (!p) return null

  return (
    <div className="rounded-xl border border-terracotta/40 bg-terracotta/5 p-3">
      <p className="mb-2 inline-flex items-center gap-1 font-display text-sm"><Icon name="wrench" size={16} /> Plattform-Preise <span className="text-xs font-normal text-muted">(Super-Admin)</span></p>
      <div className="space-y-2">
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Eine Person / Monat</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.einzel} onChange={(e) => setP({ ...p, einzel: e.target.value })} />
            <span className="text-muted2">€</span>
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Mehrere Personen / Monat</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.mehrere} onChange={(e) => setP({ ...p, mehrere: e.target.value })} />
            <span className="text-muted2">€</span>
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Aufschlag Abo-Überlauf (Guthaben nach Volumen)</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.overage} onChange={(e) => setP({ ...p, overage: e.target.value })} />
            <span className="text-muted2">%</span>
          </span>
        </label>
        <p className="label-mono pt-1 text-muted">Foto-Pack (nutzersichtbar)</p>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Preis je Pack</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.packPreis} onChange={(e) => setP({ ...p, packPreis: e.target.value })} />
            <span className="text-muted2">€</span>
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Bild-Credits je Pack</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="numeric" value={p.packCredits} onChange={(e) => setP({ ...p, packCredits: e.target.value })} />
            <span className="text-muted2">Stk.</span>
          </span>
        </label>
        <p className="rounded-lg bg-surface px-2.5 py-2 text-xs text-muted2">
          Diese zwei Werte stehen in allen nutzersichtbaren Texten. <b>Wichtig:</b> Der Preis
          muss zum Stripe-Preis hinter <span className="font-mono">STRIPE_PRICE_CREDITS</span>
          passen – Stripe bucht seinen eigenen Betrag, hier wird nur angezeigt. Abopreis und
          Monatskontingente pflegst du unter „Tarife".
        </p>
        <p className="label-mono pt-1 text-muted">Bild-Basispreis (roh, vor Aufschlag)</p>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Schnell</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.bildSchnell} onChange={(e) => setP({ ...p, bildSchnell: e.target.value })} />
            <span className="text-muted2">€</span>
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Standard</span>
          <span className="flex items-center gap-1">
            <input className={input + ' !w-20 text-right font-mono'} inputMode="decimal" value={p.bildStandard} onChange={(e) => setP({ ...p, bildStandard: e.target.value })} />
            <span className="text-muted2">€</span>
          </span>
        </label>
      </div>
      <Button onClick={speichern} disabled={busy} className="mt-3 w-full">
        {busy ? <Spinner /> : 'Preise speichern'}
      </Button>
    </div>
  )
}
