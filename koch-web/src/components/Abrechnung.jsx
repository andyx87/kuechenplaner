import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { Modal, Spinner, confirmDialog } from '../ui.jsx'
import { ABO_AKTIV } from '../settings.js'
import { IST_NATIVE } from '../native.js'
import { usePreise, kontingent } from '../preise.js'
import { Icon } from '../icons.jsx'

const STUFE_LABEL = { schnell: 'Schnell', standard: 'Standard', pro: 'Pro' }
const CODE_NAME = { basis: 'Basis', plus: 'Plus', max: 'Max', payg: 'Pay-as-you-go' }
const dt = (d) => (d ? new Date(d + 'T00:00:00').toLocaleDateString('de-DE') : '')
const PRESETS = [{ k: '7', l: '7 Tage' }, { k: '30', l: '30 Tage' }, { k: 'monat', l: 'Dieser Monat' }, { k: 'custom', l: 'Zeitraum…' }]

const euro = (c) => ((c || 0) / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'
const monatLabel = (d) => new Date(d + 'T00:00:00').toLocaleDateString('de-DE', { month: 'long', year: 'numeric' })
const isoLocal = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function rangeFor(preset) {
  const today = new Date()
  if (preset === '7') { const v = new Date(today); v.setDate(v.getDate() - 6); return { von: isoLocal(v), bis: isoLocal(today) } }
  if (preset === '30') { const v = new Date(today); v.setDate(v.getDate() - 29); return { von: isoLocal(v), bis: isoLocal(today) } }
  if (preset === 'monat') { return { von: isoLocal(new Date(today.getFullYear(), today.getMonth(), 1)), bis: isoLocal(today) } }
  return {}
}

function buildQs(f) {
  const p = new URLSearchParams()
  if (f.von) p.set('von', f.von)
  if (f.bis) p.set('bis', f.bis)
  return p.toString()
}

// Verbrauchsbalken für ein Volumen-Fenster (Tag/Woche). limit==null → kein Balken.
// Bewusst ohne €-Beträge – nur Auslastung als Balken + Prozent.
function VolumenBar({ label, used, limit }) {
  if (limit == null) return null
  const pct = Math.min(100, Math.round(((used || 0) / Math.max(1, limit)) * 100))
  const voll = (used || 0) >= limit
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted">{label}</span>
        <span className={`font-mono font-medium ${voll ? 'text-terracotta' : 'text-muted2'}`}>{pct} %</span>
      </div>
      <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-line/40">
        <div className={`h-full rounded-full ${voll ? 'bg-terracotta' : 'bg-olive/70'}`} style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  )
}

export default function Abrechnung({ onClose, notify }) {
  const preise = usePreise()   // Preise/Kontingente aus der Preisliste, nicht aus dem Code
  const [preset, setPreset] = useState('30')
  const [filter, setFilter] = useState({ ...rangeFor('30') })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tarife, setTarife] = useState(null)
  const [tarifPicker, setTarifPicker] = useState(false)
  const [tarifBusy, setTarifBusy] = useState(false)
  const [ladenBusy, setLadenBusy] = useState(false)
  const [kont, setKont] = useState(null)

  const [kuendBusy, setKuendBusy] = useState(false)
  async function kuendigen() {
    const ok = await confirmDialog({
      title: 'Abo kündigen?',
      message: 'Dein Zugang bleibt bis zum Ende der bereits bezahlten Laufzeit erhalten. '
        + 'Danach läuft dein Konto in der kostenlosen Version weiter – Rezepte, Pläne und '
        + 'Vorräte bleiben erhalten.',
      confirmLabel: 'Jetzt kündigen',
      cancelLabel: 'Behalten',
    })
    if (!ok) return
    setKuendBusy(true)
    try {
      const res = await api.aboKuendigen()
      notify(res?.bis ? `Gekündigt – Zugang bis ${res.bis}` : 'Abo gekündigt')
      // Zugangs-Status neu holen, damit die Karte den gekündigten Stand zeigt.
      api.kontingent().then(setKont).catch(() => { /* still */ })
    } catch (e) { notify(e?.message || 'Kündigung fehlgeschlagen', 'err') }
    finally { setKuendBusy(false) }
  }

  async function aufladen(betragCents) {
    setLadenBusy(true)
    try {
      const res = await api.guthabenCheckout(betragCents)
      if (res?.url) { window.location.href = res.url; return }
      notify('Aufladung konnte nicht gestartet werden', 'err')
    } catch (e) { notify(e?.message || 'Aufladung fehlgeschlagen', 'err') }
    finally { setLadenBusy(false) }
  }

  async function starteAbo() {
    setLadenBusy(true)
    try {
      const res = await api.aboCheckout()
      if (res?.url) { window.location.href = res.url; return }
      notify('Abo konnte nicht gestartet werden', 'err')
    } catch (e) { notify(e?.message || 'Abo fehlgeschlagen', 'err') }
    finally { setLadenBusy(false) }
  }

  async function kaufeCredits() {
    setLadenBusy(true)
    try {
      const res = await api.creditsCheckout()
      if (res?.url) { window.location.href = res.url; return }
      notify('Kauf konnte nicht gestartet werden', 'err')
    } catch (e) { notify(e?.message || 'Kauf fehlgeschlagen', 'err') }
    finally { setLadenBusy(false) }
  }

  const qs = buildQs(filter)

  const laden = useCallback(() => {
    setLoading(true)
    api.abrechnung(qs)
      .then(setData)
      .catch(() => notify('Verbrauch laden fehlgeschlagen', 'err'))
      .finally(() => setLoading(false))
  }, [qs, notify])

  useEffect(() => { laden() }, [laden])

  // v4-Kontingentstatus (Tarif, Monatsnutzung, Bild-Credits) – nur im neuen Modell.
  useEffect(() => {
    if (!ABO_AKTIV) return
    api.kontingent().then(setKont).catch(() => { /* still */ })
  }, [])

  function setRange(k) {
    setPreset(k)
    if (k !== 'custom') setFilter(() => ({ ...rangeFor(k) }))
  }

  function oeffneTarifPicker() {
    setTarifPicker(true)
    if (!tarife) api.tarife().then(setTarife).catch(() => notify('Tarife laden fehlgeschlagen', 'err'))
  }

  async function waehleTarif(code) {
    setTarifBusy(true)
    try {
      const res = await api.tarifSetzen(code)
      setTarifPicker(false)
      notify(code === 'payg' ? 'Tarif geändert' : 'Tarif gebucht', 'ok')
      // Nach Buchung eines Abos: empfohlene KI-Stufen anbieten (ohne Preise/Token).
      const emp = res?.empfehlung
      if (code !== 'payg' && emp) {
        const tarifName = (tarife?.find((x) => x.code === code)?.name) || code
        const ok = await confirmDialog({
          title: 'KI-Modelle einstellen?',
          message: `Empfohlene KI-Einstellung für ${tarifName}:\n\n• Antwort-Modell: ${emp.modell_label}\n• Bild-Qualität: ${emp.bild_label}\n\nJetzt so übernehmen?`,
          confirmLabel: 'Übernehmen',
          cancelLabel: 'Behalten',
        })
        if (ok) {
          try {
            await Promise.all([api.modellStufeSetzen(emp.modell_stufe), api.bildStufeSetzen(emp.bild_stufe)])
            notify('KI-Modelle eingestellt', 'ok')
          } catch { notify('KI-Einstellung fehlgeschlagen', 'err') }
        }
      }
      laden()
    } catch (e) { notify(e.message || 'Tarifwechsel fehlgeschlagen', 'err') }
    finally { setTarifBusy(false) }
  }

  async function paygOverageAus() {
    setTarifBusy(true)
    try { await api.paygOverageSetzen(false); laden() }
    catch { notify('Konnte nicht ändern', 'err') }
    finally { setTarifBusy(false) }
  }

  const t = data?.tarif
  const limitTxt = { tag: 'Tagesvolumen', woche: 'Wochenvolumen' }

  return (
    <Modal open onClose={onClose} title={ABO_AKTIV ? 'Verbrauch & Tarif' : 'Verbrauch & Guthaben'}>
      <div className="space-y-4">
        {/* Nativ (IST_NATIVE) keine Kauf-Karte und kein Verweis auf die Web-Version – nur der
            Stand unten (Google-Play-Payments-Richtlinie). Kündigen bleibt erlaubt. */}
        {ABO_AKTIV && !IST_NATIVE && preise && (
          <div className="rounded-2xl border border-terracotta/30 bg-terracotta/5 p-4">
            <p className="label-mono text-muted2">Sapio-Abo</p>
            <p className="mt-1 text-sm text-muted">
              Alle KI-Funktionen · Text {kontingent(preise.abo.ki_limit)} · {kontingent(preise.abo.bild_limit, 'Bilder')}/Monat. Über dem Limit: Foto-Credits.
            </p>
            <div className="mt-3 space-y-2">
              <button onClick={starteAbo} disabled={ladenBusy}
                className="w-full rounded-xl border border-terracotta/40 bg-terracotta/10 py-2.5 text-sm font-semibold text-terracotta hover:bg-terracotta/20 disabled:opacity-50">
                Sapio abonnieren – {euro(preise.abo.preis_cents)}/Monat
              </button>
              <button onClick={kaufeCredits} disabled={ladenBusy}
                className="w-full rounded-xl border border-olive/40 bg-olive/10 py-2.5 text-sm font-semibold text-olive hover:bg-olive/20 disabled:opacity-50">
                Foto-Credits kaufen – {preise.foto_pack.credits} für {euro(preise.foto_pack.preis_cents)}
              </button>
            </div>
          </div>
        )}
        {/* v4: Kontingent-Status (Tarif, Monatsnutzung, Bild-Credits) */}
        {ABO_AKTIV && kont && (
          <div className="rounded-2xl border border-line p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="label-mono text-muted2">Dein Zugang</p>
              <span className="rounded-full bg-olive/10 px-2 py-0.5 text-xs font-semibold text-olive">
                {kont.modus === 'abo' ? (kont.trial ? 'Sapio · Testphase' : 'Sapio') : 'Gratis'}
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {[['KI-Aktionen', kont.monats_ki, kont.ki_limit], ['Bilder', kont.monats_bilder, kont.bild_limit]].map(([lbl, used, lim]) => (
                <div key={lbl}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="text-muted">{lbl} diesen Monat</span>
                    <span className="font-mono text-muted2">{used}{lim != null ? ` / ${lim}` : ' · unbegrenzt'}</span>
                  </div>
                  {lim != null && (
                    <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-line/40">
                      <div className={`h-full rounded-full ${used >= lim ? 'bg-terracotta' : 'bg-olive/70'}`}
                        style={{ width: `${Math.min(100, Math.round((used / Math.max(1, lim)) * 100))}%` }} />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted2">
              Foto-Credits: <b className="text-ink">{kont.bild_credits}</b>
              {kont.abo_bezahlt_bis && kont.modus === 'abo' && !kont.trial && ` · Abo bis ${kont.abo_bezahlt_bis}`}
              {kont.trial && kont.trial_bis && ` · Testphase bis ${kont.trial_bis}`}
            </p>
            {/* Kündigung für Angemeldete. Zusätzlich – nicht ersatzweise – zum öffentlichen
                Kündigungsbutton im Footer: § 312k verlangt ihn ohne Anmeldung erreichbar.
                Nur bei echtem Abo anbieten; in der Testphase gibt es nichts zu kündigen. */}
            {kont.modus === 'abo' && !kont.trial && (
              <button onClick={kuendigen} disabled={kuendBusy}
                className="mt-3 w-full rounded-xl border border-line py-2 text-xs font-semibold text-muted transition hover:border-terracotta/40 hover:text-terracotta-deep disabled:opacity-50">
                {kuendBusy ? 'wird gekündigt …' : 'Abo kündigen'}
              </button>
            )}
          </div>
        )}
        {/* Guthaben (nur im alten €-Modell) */}
        {!ABO_AKTIV && !IST_NATIVE && (
        <div className="rounded-2xl border border-olive/30 bg-olive/5 p-4 text-center">
          <p className="label-mono text-muted2">Guthaben</p>
          <p className="mt-1 font-mono text-4xl font-bold text-olive">{euro(data?.guthaben_cents)}</p>
          <p className="mt-1 text-xs text-muted2">
            <span className="font-semibold text-terracotta">KI-Aktionen</span> nutzen KI und kosten etwas vom Guthaben –
            der genaue Preis erscheint direkt nach jeder Aktion.
          </p>
          <div className="mt-3 flex items-center justify-center gap-2">
            {[5, 10, 20].map((eur) => (
              <button key={eur} onClick={() => aufladen(eur * 100)} disabled={ladenBusy}
                className="rounded-full bg-olive px-4 py-2 font-mono text-sm font-bold text-on-accent shadow-soft transition hover:opacity-90 disabled:opacity-50">
                +{eur} €
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-muted2">Sichere Zahlung über Stripe</p>
        </div>
        )}

        {loading && !data ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !data ? (
          <p className="py-6 text-center text-muted">Keine Daten.</p>
        ) : (
          <>
            {/* Tarif-Karte */}
            {t && (
              <div className="rounded-xl border border-line p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold">Tarif</p>
                  <span className="shrink-0 rounded-full bg-olive/10 px-2 py-0.5 text-xs font-semibold text-olive">{t.status === 'aktiv' ? 'aktiv' : t.status}</span>
                </div>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <p className="text-2xl font-bold">
                    {t.name}
                    {/* Nativ ohne Preisangabe – in der App steht nur der Tarifname (AND-13). */}
                    {!t.ist_payg && !IST_NATIVE && <span className="font-mono text-sm font-normal text-muted2"> · {euro(t.preis_cents)}/Monat</span>}
                  </p>
                  {!ABO_AKTIV && !IST_NATIVE && (
                    <button onClick={oeffneTarifPicker} className="shrink-0 rounded-full bg-terracotta/15 px-3 py-1 text-xs font-semibold text-terracotta hover:bg-terracotta/25">
                      Tarif wechseln
                    </button>
                  )}
                </div>
                {!t.ist_payg && t.abo?.aktiv && (
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                    <span>
                      {t.abo.gekuendigt || t.abo.naechster_tarif === 'payg'
                        ? `Gekündigt – aktiv bis ${dt(t.abo.bezahlt_bis)}, danach Pay-as-you-go.`
                        : t.abo.naechster_tarif
                          ? `Wechselt am ${dt(t.abo.bezahlt_bis)} zu ${CODE_NAME[t.abo.naechster_tarif] || t.abo.naechster_tarif}.`
                          : `Aktiv bis ${dt(t.abo.bezahlt_bis)} · verlängert sich automatisch.`}
                    </span>
                    {/* Nativ keine Inline-Tarifwechsel anbieten – „kündigen" und „weiterführen"
                        bleiben dem Web vorbehalten (AND-13, S-01). „Abo kündigen" oben (aboKuendigen) bleibt erlaubt. */}
                    {!IST_NATIVE && !t.abo.gekuendigt && t.abo.naechster_tarif !== 'payg' && (
                      <button onClick={() => waehleTarif('payg')} disabled={tarifBusy} className="font-semibold text-terracotta underline">
                        kündigen
                      </button>
                    )}
                    {!IST_NATIVE && (t.abo.gekuendigt || t.abo.naechster_tarif) && (
                      <button onClick={() => waehleTarif(t.abo.tarif_code)} disabled={tarifBusy} className="font-semibold text-olive underline">
                        weiterführen
                      </button>
                    )}
                  </p>
                )}
                {t.ist_payg ? (
                  <p className="mt-2 text-xs text-muted">Pay-as-you-go: keine Grundgebühr. Jede Nutzung wird direkt vom Guthaben abgebucht.</p>
                ) : (
                  <div className="mt-3 space-y-2">
                    <VolumenBar label="Tagesvolumen (letzte 24 h)" used={t.verbrauch?.tag} limit={t.tages_limit_cents} />
                    <VolumenBar label="Wochenvolumen (letzte 7 Tage)" used={t.verbrauch?.woche} limit={t.wochen_limit_cents} />
                  </div>
                )}

                {t.payg_overage && (
                  <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-terracotta/10 px-2.5 py-1.5 text-xs text-terracotta">
                    <span className="inline-flex items-center gap-1"><Icon name="zap" size={14} /> Pay-as-you-go-Überlauf aktiv (über das Volumen hinaus aus dem Guthaben)</span>
                    <button onClick={paygOverageAus} disabled={tarifBusy} className="shrink-0 font-semibold underline">deaktivieren</button>
                  </div>
                )}
                {!t.ist_payg && t.limit_erreicht && !t.payg_overage && (
                  <p className="mt-2 rounded-lg bg-terracotta/10 px-2.5 py-1.5 text-xs text-terracotta">
                    {limitTxt[t.limit_erreicht] || 'Limit'} erreicht — KI pausiert bis zum Reset.{!IST_NATIVE && ' Tarif aufstocken oder Guthaben aufladen & Pay-as-you-go aktivieren.'}
                  </p>
                )}

                {t.buchungen?.length > 0 && (
                  <ul className="mt-2 space-y-1 text-sm">
                    {t.buchungen.map((bu, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 border-b border-line/40 py-1">
                        <span className="capitalize">{monatLabel(bu.zeitraum)}</span>
                        {/* Nativ ohne €-Betrag; der Monatseintrag bleibt, damit die Liste
                            weiterhin zeigt, für welche Monate Buchungen vorliegen (AND-13). */}
                        {!IST_NATIVE && <span className="w-16 shrink-0 text-right font-mono text-muted">{euro(bu.betrag_cents)}</span>}
                      </li>
                    ))}
                  </ul>
                )}

                {ABO_AKTIV && tarifPicker && !IST_NATIVE && (
                  <div className="mt-3 space-y-2 rounded-xl border border-terracotta/30 bg-terracotta/5 p-2.5">
                    <p className="text-xs font-semibold text-muted">Tarif wählen</p>
                    {!tarife ? <Spinner /> : tarife.map((tt) => (
                      <button key={tt.code} onClick={() => waehleTarif(tt.code)} disabled={tarifBusy || tt.code === t.code}
                        className={`flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm ${tt.code === t.code ? 'border-olive/40 bg-olive/10' : 'border-line hover:bg-line/30'}`}>
                        <span>
                          <b>{tt.name}</b>
                          {tt.code === t.code && <span className="ml-1 text-xs text-olive">· aktuell</span>}
                          <span className="block text-[11px] text-muted2">
                            {tt.ist_payg ? 'keine Grundgebühr · zahlst nur, was du nutzt' : 'inkl. Tages- & Wochenvolumen'}
                          </span>
                        </span>
                        <span className="shrink-0 font-mono font-semibold">{tt.ist_payg ? '—' : euro(tt.preis_cents) + '/Mon.'}</span>
                      </button>
                    ))}
                    <button onClick={() => setTarifPicker(false)} className="w-full rounded-lg py-1 text-xs text-muted hover:text-ink">abbrechen</button>
                  </div>
                )}
              </div>
            )}

            {/* Zeitraum + €-Gesamtsumme – nur im alten €-Modell (im Kontingent-Modell irrelevant) */}
            {!ABO_AKTIV && !IST_NATIVE && (
            <div className="space-y-2 rounded-xl border border-line p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {PRESETS.map((p) => (
                  <button key={p.k} onClick={() => setRange(p.k)}
                    className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${preset === p.k ? 'bg-terracotta text-on-accent' : 'bg-surface text-muted2 hover:bg-line/70'}`}>
                    {p.l}
                  </button>
                ))}
              </div>
              {preset === 'custom' && (
                <div className="flex items-center gap-2 text-sm">
                  <input type="date" value={filter.von || ''} max={filter.bis || undefined}
                    onChange={(e) => setFilter((f) => ({ ...f, von: e.target.value }))}
                    className="rounded-lg border border-line bg-card px-2 py-1 font-mono text-ink" />
                  <span className="text-muted2">bis</span>
                  <input type="date" value={filter.bis || ''} min={filter.von || undefined}
                    onChange={(e) => setFilter((f) => ({ ...f, bis: e.target.value }))}
                    className="rounded-lg border border-line bg-card px-2 py-1 font-mono text-ink" />
                </div>
              )}
              <div className="flex items-baseline justify-between gap-2 pt-1">
                <span className="text-sm text-muted">KI-Nutzung in diesem Zeitraum</span>
                <span className="font-mono text-2xl font-bold text-olive">{euro(data?.bereich?.kosten_cents)}</span>
              </div>
            </div>
            )}

          </>
        )}
      </div>
    </Modal>
  )
}
