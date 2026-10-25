import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'
import { Chip, input } from '../ui.jsx'

function fmt(n) {
  const x = Number(n)
  return Number.isInteger(x) ? String(x) : x.toFixed(2).replace(/\.?0+$/, '').replace('.', ',')
}

// Wiederverwendbare Auswahl: Haushaltspersonen + Gäste -> Portionen.
// Gibt man Portionen MANUELL ein, werden Gäste auf 0 gesetzt und alle Personen
// abgewählt. onChange liefert { personIds:[...], gaeste, portionen }.
export default function PortionenWahl({ onChange, label = 'Für wen wird gekocht?' }) {
  const [personen, setPersonen] = useState([])
  const [sel, setSel] = useState(() => new Set())
  const [gaeste, setGaeste] = useState(0)
  const [manuell, setManuell] = useState('')  // '' = automatisch aus Personen + Gästen

  useEffect(() => {
    api.personen().then((ps) => {
      const aktive = (ps || []).filter((p) => p.aktiv)
      setPersonen(aktive)
      setSel(new Set(aktive.map((p) => p.id)))
    }).catch(() => {})
  }, [])

  const auto = personen.filter((p) => sel.has(p.id)).reduce((s, p) => s + Number(p.portionsfaktor || 1), 0) + Number(gaeste || 0)
  const portionen = manuell.trim() !== '' ? (Number(manuell.replace(',', '.')) || 0) : auto

  // Ergebnis nach oben melden.
  useEffect(() => {
    onChange && onChange({ personIds: [...sel], gaeste: Number(gaeste || 0), portionen: Math.max(portionen, 0) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, gaeste, manuell, personen])

  function togglePerson(id) {
    setManuell('')
    setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function aendereGaeste(delta) {
    setManuell('')
    setGaeste((g) => Math.max(0, Number(g || 0) + delta))
  }
  function aendereManuell(v) {
    setManuell(v)
    if (v.trim() !== '') { setSel(new Set()); setGaeste(0) }
  }

  return (
    <div className="space-y-2 rounded-xl border border-line bg-card/60 p-3">
      {personen.length > 0 && (
        <div>
          <span className="mb-1 block text-xs font-semibold text-muted2">{label}</span>
          <div className="flex flex-wrap gap-2">
            {personen.map((p) => (
              <Chip key={p.id} active={sel.has(p.id)} onClick={() => togglePerson(p.id)}>{p.name}</Chip>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold"><Icon name="party-popper" size={16} /> Gäste</span>
        <div className="flex items-center gap-2">
          <button onClick={() => aendereGaeste(-1)} className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-lg leading-none hover:bg-ink/5">−</button>
          <span className="w-6 text-center font-mono font-semibold">{gaeste}</span>
          <button onClick={() => aendereGaeste(1)} className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-lg leading-none hover:bg-ink/5">+</button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="shrink-0 text-sm text-muted">oder Portionen direkt:</span>
        <input
          className={input + ' !w-24'}
          type="number" step="0.5" min="0"
          value={manuell}
          placeholder={`Auto: ${fmt(auto)}`}
          onChange={(e) => aendereManuell(e.target.value)}
        />
      </div>
      <p className="text-right text-sm font-semibold text-terracotta">→ <span className="font-mono">{fmt(Math.max(portionen, 0))}</span> Portionen</p>
    </div>
  )
}
