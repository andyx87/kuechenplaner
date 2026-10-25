import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Modal, Spinner } from '../ui.jsx'
import { isoHeute, istAnwesend } from '../utils.js'
import { Icon } from '../icons.jsx'

export default function SpontanesKochen({ onClose, notify, onRezeptOpen }) {
  const [geraete, setGeraete] = useState([])
  const [geraeteHeute, setGeraeteHeute] = useState(new Set())
  const [personen, setPersonen] = useState([])
  const [selPersonen, setSelPersonen] = useState(new Set())
  const [rezepte, setRezepte] = useState([])
  const [selRezept, setSelRezept] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function laden() {
      const [g, gh, pers, rez] = await Promise.all([
        api.geraete(),
        api.geraeteHeute(),
        api.personen(),
        api.vorschlaege(10),
      ])
      setGeraete(g)
      setGeraeteHeute(new Set(gh.map((x) => x.id)))
      setPersonen(pers)
      const heute = isoHeute()
      setSelPersonen(new Set(
        pers.filter((p) => istAnwesend(p, heute, 'Abendessen')).map((p) => p.id)
      ))
      // API gibt rezept_id / rezept zurück
      setRezepte(rez)
      setLoading(false)
    }
    laden().catch(() => setLoading(false))
  }, [])

  async function toggleGeraet(id) {
    const neu = new Set(geraeteHeute)
    neu.has(id) ? neu.delete(id) : neu.add(id)
    setGeraeteHeute(neu)
    await api.setGeraeteHeute([...neu])
    const rez = await api.vorschlaege(10)
    setRezepte(rez)
    setSelRezept(null)
  }

  function togglePerson(id) {
    setSelPersonen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  function rezeptOeffnen() {
    if (!selRezept) return
    onClose()
    onRezeptOpen(selRezept.rezept_id)
  }

  const compPortionen = personen
    .filter((p) => selPersonen.has(p.id))
    .reduce((s, p) => s + Number(p.portionsfaktor), 0)

  return (
    <Modal open onClose={onClose} title="Spontan kochen">
      {loading ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : (
        <div className="space-y-4">

          {/* Geräte */}
          <div>
            <p className="mb-1.5 label-mono font-bold text-muted2">Verfügbare Geräte</p>
            <div className="flex flex-wrap gap-1.5">
              {geraete.map((g) => {
                const aktiv = geraeteHeute.has(g.id)
                return (
                  <button
                    key={g.id}
                    onClick={() => toggleGeraet(g.id)}
                    className={`rounded-full border px-3 py-1 text-sm font-semibold transition ${
                      aktiv
                        ? 'border-terracotta bg-terracotta/10 text-terracotta'
                        : 'border-line bg-card text-ink/50'
                    }`}
                  >
                    {g.name}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Personen */}
          <div>
            <p className="mb-1.5 label-mono font-bold text-muted2">Wer isst mit?</p>
            <div className="flex flex-wrap gap-1.5">
              {personen.map((p) => {
                const sel = selPersonen.has(p.id)
                const anwesend = istAnwesend(p, isoHeute(), 'Abendessen')
                return (
                  <button
                    key={p.id}
                    onClick={() => togglePerson(p.id)}
                    title={!anwesend ? 'Laut Regelplan nicht zuhause' : undefined}
                    className={`rounded-full border px-3 py-1 text-sm font-semibold transition ${
                      sel
                        ? 'border-terracotta bg-terracotta/10 text-terracotta'
                        : 'border-line bg-card text-ink/50'
                    } ${!anwesend ? 'opacity-40' : ''}`}
                  >
                    <span className="inline-flex items-center gap-1">{p.name}{!anwesend && <Icon name="home" size={14} />}</span>
                  </button>
                )
              })}
            </div>
            {compPortionen > 0 && (
              <p className="mt-1 font-mono text-xs text-muted2">{compPortionen.toFixed(1)} Portionen</p>
            )}
          </div>

          {/* Rezeptvorschläge */}
          <div>
            <p className="mb-1.5 label-mono font-bold text-muted2">Passende Rezepte</p>
            {rezepte.length === 0 ? (
              <p className="text-sm text-ink/40">Keine Vorschläge – Geräte auswählen?</p>
            ) : (
              <div className="max-h-56 space-y-1.5 overflow-y-auto">
                {rezepte.map((r) => {
                  const sel = selRezept?.rezept_id === r.rezept_id
                  return (
                    <button
                      key={r.rezept_id}
                      onClick={() => setSelRezept(sel ? null : r)}
                      className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                        sel
                          ? 'border-terracotta bg-terracotta/10'
                          : 'border-line bg-card hover:border-terracotta/40'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-dish text-xl leading-tight">{r.rezept}</span>
                        <div className="flex shrink-0 items-center gap-2 font-mono text-xs text-muted2">
                          {r.fehlend > 0 && (
                            <span className="text-terracotta">−{r.fehlend} fehlt</span>
                          )}
                          {r.fehlend === 0 && (
                            <span className="inline-flex items-center gap-1 text-olive"><Icon name="check" size={14} /> alles da</span>
                          )}
                          {r.sterne > 0 && <span className="inline-flex items-center gap-0.5">{Array.from({ length: r.sterne }).map((_, i) => <Icon key={i} name="star" size={12} fill="currentColor" />)}</span>}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Kochen-Button */}
          <button
            onClick={rezeptOeffnen}
            disabled={!selRezept}
            className="w-full rounded-full bg-terracotta py-3 text-sm font-bold text-on-accent shadow-soft transition hover:opacity-90 disabled:opacity-40"
          >
            {selRezept ? `${selRezept.rezept} öffnen →` : 'Rezept auswählen'}
          </button>

        </div>
      )}
    </Modal>
  )
}
