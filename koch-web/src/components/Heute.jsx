import { useEffect, useState, useCallback } from 'react'
import { api } from '../api.js'
import { Card, Chip, Spinner, Empty } from '../ui.jsx'
import { Icon } from '../icons.jsx'

function fmtFaktor(n) {
  const x = Number(n)
  return Number.isInteger(x) ? x : Math.round(x * 100) / 100
}

export default function Heute({ notify, openRezept, portionen, setPortionen }) {
  const [geraete, setGeraete] = useState([])
  const [sel, setSel] = useState(new Set())
  const [personen, setPersonen] = useState([])
  const [selPersonen, setSelPersonen] = useState(new Set()) // Set von person.id (Zahlen)
  const [vorschlaege, setVorschlaege] = useState([])
  const [loading, setLoading] = useState(true)
  const [vLoading, setVLoading] = useState(false)

  const ladeVorschlaege = useCallback(async () => {
    setVLoading(true)
    try {
      setVorschlaege(await api.vorschlaege(12))
    } catch {
      notify('Vorschläge konnten nicht geladen werden', 'err')
    } finally {
      setVLoading(false)
    }
  }, [notify])

  useEffect(() => {
    ;(async () => {
      try {
        const [g, h, alle, heute] = await Promise.all([
          api.geraete(), api.geraeteHeute(), api.personen(), api.personenHeute(),
        ])
        setGeraete(g)
        setSel(new Set(h.map((x) => x.id)))
        setPersonen(alle)
        const heuteIds = new Set(heute.map((p) => p.id))
        setSelPersonen(heuteIds)
        // Portionen aus gewählten Personen berechnen
        const computed = heute.reduce((s, p) => s + Number(p.portionsfaktor), 0)
        if (computed > 0) setPortionen(Math.max(1, Math.round(computed * 10) / 10))
      } catch {
        notify('Laden fehlgeschlagen', 'err')
      } finally {
        setLoading(false)
      }
      ladeVorschlaege()
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function toggle(id) {
    const next = new Set(sel)
    next.has(id) ? next.delete(id) : next.add(id)
    setSel(next)
    try {
      await api.setGeraeteHeute([...next])
      ladeVorschlaege()
    } catch {
      notify('Speichern fehlgeschlagen', 'err')
    }
  }

  async function togglePerson(pid) {
    const next = new Set(selPersonen)
    next.has(pid) ? next.delete(pid) : next.add(pid)
    setSelPersonen(next)
    try {
      await api.setPersonenHeute([...next])
      // Portionen neu berechnen
      const gewaehlte = personen.filter((p) => next.has(p.id))
      const computed = gewaehlte.reduce((s, p) => s + Number(p.portionsfaktor), 0)
      setPortionen(Math.max(1, Math.round(computed * 10) / 10))
      ladeVorschlaege()
    } catch {
      notify('Speichern fehlgeschlagen', 'err')
    }
  }

  async function resetAlltag() {
    const ids = geraete.filter((g) => g.standard).map((g) => g.id)
    setSel(new Set(ids))
    try {
      await api.setGeraeteHeute(ids)
      ladeVorschlaege()
    } catch {
      notify('Zurücksetzen fehlgeschlagen', 'err')
    }
  }

  if (loading)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    )

  const erwachsene = personen.filter((p) => p.rolle !== 'kind')
  const kinder = personen.filter((p) => p.rolle === 'kind')

  return (
    <div className="space-y-8">
      {/* Wer isst mit? */}
      {personen.length > 0 && (
        <section>
          <div className="mb-1 flex items-end justify-between gap-3">
            <h2 className="font-display text-3xl">Wer isst mit?</h2>
            <span className="shrink-0 font-mono text-xs text-muted">
              {portionen} Portion{portionen !== 1 ? 'en' : ''}
            </span>
          </div>
          <p className="mb-3 text-sm text-ink/60">
            Haken setzen = isst heute mit. Portionen werden automatisch berechnet.
          </p>
          <div className="space-y-3">
            {[['Erwachsene', erwachsene], ['Kinder', kinder]].map(([label, group]) =>
              group.length > 0 ? (
                <div key={label}>
                  <p className="mb-1.5 label-mono font-bold text-muted2">{label}</p>
                  <div className="flex flex-wrap gap-2">
                    {group.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => togglePerson(p.id)}
                        className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-semibold transition ${
                          selPersonen.has(p.id)
                            ? 'border-terracotta bg-terracotta text-on-accent'
                            : 'border-line bg-card text-ink/50'
                        }`}
                      >
                        {selPersonen.has(p.id) ? <Icon name="check" size={16} /> : '○'}
                        {p.name}
                        {p.portionsfaktor !== 1 ? (
                          <span className={`font-mono text-xs ${selPersonen.has(p.id) ? 'text-on-accent/70' : 'text-ink/35'}`}>
                            ×{fmtFaktor(p.portionsfaktor)}
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </div>
          {/* Portionen manuell anpassen */}
          <div className="mt-3 flex items-center gap-3">
            <span className="text-sm text-ink/50">Manuell anpassen:</span>
            <div className="flex items-center gap-1.5 rounded-full border border-line bg-card px-3 py-1">
              <button onClick={() => setPortionen(Math.max(1, portionen - 0.5))} className="w-5 text-center text-ink/60 hover:text-ink">−</button>
              <span className="w-10 text-center font-mono text-sm font-bold">{portionen}</span>
              <button onClick={() => setPortionen(portionen + 0.5)} className="w-5 text-center text-ink/60 hover:text-ink">+</button>
            </div>
          </div>
        </section>
      )}

      {/* Geräteauswahl */}
      <section>
        <div className="mb-1 flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
          <h2 className="font-display text-3xl">Heute koche ich mit…</h2>
          {geraete.length > 0 && (
            <button onClick={resetAlltag} className="shrink-0 text-sm font-semibold text-terracotta hover:underline">
              Auf Alltag zurücksetzen
            </button>
          )}
        </div>
        <p className="mb-4 text-sm text-ink/60">
          Alltagsgeräte vorausgewählt – tippe ab, was heute nicht verfügbar ist.
        </p>

        {geraete.length === 0 ? (
          <p className="text-sm text-ink/50">Noch keine Geräte angelegt – lege sie im Bereich „Geräte" an.</p>
        ) : (
          <>
            {geraete.some((g) => g.standard) && (
              <div className="mb-3">
                <p className="mb-1.5 label-mono font-bold text-muted2">Alltag</p>
                <div className="flex flex-wrap gap-2">
                  {geraete.filter((g) => g.standard).map((g) => (
                    <Chip key={g.id} active={sel.has(g.id)} onClick={() => toggle(g.id)}>{g.name}</Chip>
                  ))}
                </div>
              </div>
            )}
            {geraete.some((g) => !g.standard) && (
              <div className="mb-3">
                <p className="mb-1.5 label-mono font-bold text-muted2">Nur bei Bedarf</p>
                <div className="flex flex-wrap gap-2">
                  {geraete.filter((g) => !g.standard).map((g) => (
                    <Chip key={g.id} active={sel.has(g.id)} onClick={() => toggle(g.id)}>{g.name}</Chip>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* Vorschläge */}
      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="font-display text-3xl">Vorschläge</h2>
          {vLoading && <Spinner />}
        </div>
        {!vLoading && vorschlaege.length === 0 && (
          <Empty>Keine passenden Rezepte – lege Rezepte an oder fülle den Vorrat.</Empty>
        )}
        <div className="grid gap-3 stagger sm:grid-cols-2">
          {vorschlaege.map((v) => (
            <Card
              key={v.rezept_id}
              className="cursor-pointer p-4 transition hover:-translate-y-0.5"
              onClick={() => openRezept(v.rezept_id)}
            >
              <h3 className="font-dish text-2xl leading-tight">{v.rezept}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                <span className="rounded-full bg-olive/15 px-2.5 py-0.5 font-mono text-xs font-semibold text-olive">
                  {v.davon_vorhanden}/{v.pflicht_zutaten} Zutaten da
                </span>
                {v.fehlend > 0 && <span className="font-mono text-xs text-muted">{v.fehlend} fehlen</span>}
                {portionen > 0 && (
                  <span className="font-mono text-xs text-muted2">für {portionen} Port.</span>
                )}
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}
