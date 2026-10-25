import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { Spinner } from '../ui.jsx'

function Kpi({ label, wert, sub }) {
  return (
    <div className="rounded-xl border border-line bg-card/60 p-3">
      <div className="label-mono text-muted">{label}</div>
      <div className="mt-1 font-mono text-2xl font-bold leading-none">{wert ?? 0}</div>
      {sub && <div className="mt-1 font-mono text-xs text-muted2">{sub}</div>}
    </div>
  )
}

// Admin-Dashboard: Nutzungs-Kennzahlen der Instanz auf einen Blick.
export default function AdminDashboard({ notify }) {
  const [k, setK] = useState(null)
  const [err, setErr] = useState(false)
  const lade = useCallback(() => {
    setErr(false)
    api.adminKennzahlen().then(setK).catch(() => { setErr(true); notify?.('Kennzahlen laden fehlgeschlagen', 'err') })
  }, [notify])
  useEffect(() => { lade() }, [lade])

  if (err) return (
    <div className="py-10 text-center text-sm text-muted">
      Kennzahlen konnten nicht geladen werden.{' '}
      <button onClick={lade} className="font-semibold text-terracotta underline">Erneut versuchen</button>
    </div>
  )
  if (!k) return <div className="py-10 text-center"><Spinner /></div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Kpi label="Nutzer" wert={k.nutzer_gesamt} sub={`${k.nutzer_aktiv ?? 0} aktiv`} />
        <Kpi label="Neu (30 T.)" wert={k.neu_30d} sub={`${k.neu_7d ?? 0} in 7 T.`} />
        <Kpi label="Haushalte" wert={k.haushalte} />
        <Kpi label="Aktive Haushalte (30 T.)" wert={k.aktiv_30d} sub={`${k.aktiv_7d ?? 0} in 7 T.`} />
        <Kpi label="Rezepte" wert={k.rezepte} sub={`${k.rezepte_oeffentlich ?? 0} öffentlich`} />
        <Kpi label="Offene Bugreports" wert={k.bugreports_offen} />
      </div>
      <p className="text-xs text-muted2">
        „Aktive Haushalte" zählt Haushalte, in denen in den letzten 7 bzw. 30 Tagen etwas genutzt wurde.
      </p>
    </div>
  )
}
