import { useState } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'
import { Button, Spinner, input } from '../ui.jsx'
import { WEB_URL } from '../native.js'

// Super-Admin: erzeugt einmalig gültige Einladungslinks mit variablem Freiguthaben.
// Der Link (…/?guthaben=CODE) schreibt dem Konto, das ihn öffnet, das Guthaben gut.
export default function AdminGuthabenEinladung({ notify }) {
  const [betrag, setBetrag] = useState('5,00')
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState('')

  async function erzeugen() {
    const cents = Math.round(parseFloat(String(betrag).replace(',', '.')) * 100)
    if (!Number.isFinite(cents) || cents <= 0) { notify('Bitte einen gültigen Betrag eingeben', 'err'); return }
    setBusy(true)
    try {
      const res = await api.guthabenEinladungErzeugen(cents)
      const url = `${WEB_URL}/?guthaben=${res.code}`
      setLink(url)
      try { await navigator.clipboard.writeText(url); notify('Einladungslink erzeugt & kopiert') }
      catch { notify('Einladungslink erzeugt') }
    } catch (e) { notify(e.message || 'Erzeugen fehlgeschlagen', 'err') }
    finally { setBusy(false) }
  }

  return (
    <div className="rounded-xl border border-line p-3">
      <p className="mb-1 inline-flex items-center gap-1.5 text-sm font-semibold"><Icon name="gift" size={16} /> Guthaben-Einladung</p>
      <p className="mb-2 text-[11px] text-muted">
        Erzeugt einen <b>einmalig</b> gültigen Link. Wer ihn öffnet (eingeloggt oder neu registriert),
        bekommt das Freiguthaben gutgeschrieben.
      </p>
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1">
          <input className={input + ' !w-24 text-right font-mono'} inputMode="decimal" value={betrag}
            onChange={(e) => setBetrag(e.target.value)} />
          <span className="text-muted2">€</span>
        </span>
        <Button variant="olive" onClick={erzeugen} disabled={busy}>{busy ? <Spinner /> : 'Link erzeugen'}</Button>
      </div>
      {link && (
        <div className="mt-2 flex items-center gap-2 rounded-lg bg-olive/10 p-2 text-xs">
          <input readOnly value={link} onFocus={(e) => e.target.select()}
            className="flex-1 bg-transparent font-mono text-muted outline-none" />
          <button onClick={() => { navigator.clipboard?.writeText(link); notify('Kopiert') }}
            className="shrink-0 font-semibold text-olive underline">kopieren</button>
        </div>
      )}
    </div>
  )
}
