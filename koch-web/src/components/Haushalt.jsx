import { useState } from 'react'
import Personen from './Personen.jsx'
import Geraete from './Geraete.jsx'
import Zutaten from './Zutaten.jsx'

const SUB = [
  ['personen', 'Personen'],
  ['geraete', 'Geräte'],
  ['zutaten', 'Zutaten'],
]

export default function Haushalt({ notify, superAdmin = false }) {
  const [sub, setSub] = useState('personen')
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap justify-center gap-2">
        {SUB.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setSub(k)}
            className={`rounded-full px-3.5 py-1.5 text-sm font-bold transition ${
              sub === k
                ? 'bg-olive text-on-accent shadow-soft'
                : 'border border-line bg-card text-muted hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {sub === 'personen' && <Personen notify={notify} />}
      {sub === 'geraete' && <Geraete notify={notify} />}
      {sub === 'zutaten' && <Zutaten notify={notify} superAdmin={superAdmin} />}
    </div>
  )
}
