import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { Spinner } from '../ui.jsx'

const euro = (c) => ((c || 0) / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'
const eurF = (v) => (v || 0).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'

const FUNKTION_LABEL = {
  'chat': 'Chat-Assistent',
  'foto-erkennung': 'Foto-Erkennung',
  'guided-cooking': 'Geführtes Kochen',
  'guided-frage': 'Koch-Assistent (Frage)',
  'rezept-link': 'Rezept-Import (Link)',
  'rezept-import-datei': 'Rezept-Import (Datei)',
  'rezept-bild': 'Bildgenerierung',
  'spracheingabe': 'Spracheingabe',
}

function Kpi({ label, wert, sub }) {
  return (
    <div className="rounded-xl border border-line bg-card/60 p-3">
      <div className="label-mono text-muted">{label}</div>
      <div className="mt-1 font-mono text-2xl font-bold leading-none">{wert}</div>
      {sub && <div className="mt-1 font-mono text-xs text-muted2">{sub}</div>}
    </div>
  )
}

// Admin-Dashboard: Geschäfts-KPIs auf einen Blick.
export default function AdminDashboard({ notify }) {
  const [k, setK] = useState(null)
  const [err, setErr] = useState(false)
  const [cloud, setCloud] = useState(null)  // null=lädt, {…}=da
  const lade = useCallback(() => {
    setErr(false)
    api.adminKennzahlen().then(setK).catch(() => { setErr(true); notify?.('Kennzahlen laden fehlgeschlagen', 'err') })
    api.adminCloudKosten().then(setCloud).catch(() => setCloud({ verfuegbar: false, hinweis: 'Kosten konnten nicht geladen werden.' }))
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
        <Kpi label="Nutzer" wert={k.nutzer_gesamt} sub={`${k.nutzer_aktiv} aktiv`} />
        <Kpi label="Haushalte" wert={k.haushalte} />
        <Kpi label="MRR" wert={euro(k.mrr_cents)} sub={`${k.abos_gesamt} Abos`} />
        <Kpi label="Neu (30 T.)" wert={k.neu_30d} sub={`${k.neu_7d} in 7 T.`} />
        <Kpi label="KI-aktiv (30 T.)" wert={k.aktiv_ki_30d} sub={`${k.aktiv_ki_7d} in 7 T.`} />
        <Kpi label="KI-Nutzung (30 T.)" wert={euro(k.ki_nutzung_30d_cents)} sub={`${euro(k.ki_nutzung_7d_cents)} in 7 T.`} />
      </div>

      <div className="rounded-xl border border-line bg-card/60 p-3">
        <p className="mb-2 flex items-center justify-between gap-2 font-display text-sm">
          <span>Google-Cloud-Kosten <span className="font-mono text-xs text-muted2">echte Projektkosten</span></span>
          {cloud?.verfuegbar && cloud?.stand && <span className="font-mono text-[11px] text-muted2">Stand {new Date(cloud.stand).toLocaleDateString('de-DE')}</span>}
        </p>
        {cloud === null ? (
          <div className="py-4 text-center"><Spinner /></div>
        ) : !cloud.verfuegbar ? (
          <p className="text-sm text-muted">{cloud.hinweis || 'Noch keine Kostendaten.'}</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Kpi label="Monat" wert={eurF(cloud.monat_eur)} />
              <Kpi label="30 Tage" wert={eurF(cloud.dreissig_tage_eur)} />
              <Kpi label="7 Tage" wert={eurF(cloud.sieben_tage_eur)} />
            </div>
            {cloud.nach_service?.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-sm">
                {cloud.nach_service.map((s) => (
                  <li key={s.service} className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-muted">{s.service}</span>
                    <span className="shrink-0 font-mono font-semibold text-terracotta">{eurF(s.eur)}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <div className="rounded-xl border border-line bg-card/60 p-3">
        <p className="mb-2 font-display text-sm">Abos je Tarif</p>
        {k.abos.length === 0 ? <p className="text-sm text-muted">Noch keine aktiven Abos.</p> : (
          <ul className="space-y-1.5 text-sm">
            {k.abos.map((a) => (
              <li key={a.code} className="flex items-center justify-between">
                <span className="capitalize">{a.name} <span className="font-mono text-xs text-muted2">({euro(a.preis_cents)}/Mo)</span></span>
                <span className="text-muted"><span className="font-mono">{a.anzahl}×</span> · <span className="font-mono font-semibold text-olive">{euro(a.mrr_cents)}</span></span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-xl border border-line bg-card/60 p-3">
        <p className="mb-2 font-display text-sm">Nutzung je Funktion (30 Tage)</p>
        {(!k.nach_funktion || k.nach_funktion.length === 0) ? <p className="text-sm text-muted">Keine Nutzung.</p> : (
          <ul className="space-y-1.5 text-sm">
            {k.nach_funktion.map((f) => (
              <li key={f.zweck} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{FUNKTION_LABEL[f.zweck] || f.zweck} <span className="font-mono text-xs text-muted2">×{f.anzahl}</span></span>
                <span className="shrink-0 font-mono font-semibold text-olive">{euro(f.kosten_cents)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-xl border border-line bg-card/60 p-3">
        <p className="mb-2 font-display text-sm">Top-Verbraucher (30 Tage)</p>
        {k.top_verbraucher.length === 0 ? <p className="text-sm text-muted">Keine Nutzung.</p> : (
          <ul className="space-y-1.5 text-sm">
            {k.top_verbraucher.map((t) => (
              <li key={t.user_id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-muted">{t.email || <span className="font-mono">{`#${t.user_id}`}</span>}</span>
                <span className="shrink-0 font-mono font-semibold text-terracotta">{euro(t.kosten_cents)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-xs text-muted2">
        Guthaben aller Konten zusammen: {euro(k.guthaben_summe_cents)}. „KI-Nutzung" ist der abgerechnete
        Nutzungswert (inkl. Aufschlag); die tatsächlichen Anbieterkosten liegen darunter.
      </p>
    </div>
  )
}
