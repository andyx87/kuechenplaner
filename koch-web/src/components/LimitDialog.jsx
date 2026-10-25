import { useState } from 'react'
import { api } from '../api.js'
import { Modal, Button, Spinner } from '../ui.jsx'
import { ABO_AKTIV } from '../settings.js'
import { IST_NATIVE } from '../native.js'
import { usePreise, kontingent } from '../preise.js'
import { Icon } from '../icons.jsx'

const euro = (c) => ((c || 0) / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'
const FENSTER = { tag: 'Tagesvolumen', woche: 'Wochenvolumen' }

// Das Monatskontingent zählt pro Kalendermonat (ai_nutzung, date_trunc('month')).
function naechsterMonatserster() {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth() + 1, 1).toLocaleDateString('de-DE', { day: 'numeric', month: 'long' })
}

// Auslastungsbalken (ohne €-Beträge) – nur Balken + Prozent.
function LimitBar({ label, used, limit }) {
  if (limit == null) return null
  const pct = Math.min(100, Math.round(((used || 0) / Math.max(1, limit)) * 100))
  const voll = (used || 0) >= limit
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted">{label}</span>
        <span className={`font-mono ${voll ? 'text-terracotta' : 'text-muted2'}`}>{pct} %</span>
      </div>
      <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-line/40">
        <div className={`h-full rounded-full ${voll ? 'bg-terracotta' : 'bg-olive/70'}`} style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  )
}

// Wird bei HTTP 402 angezeigt. Drei Fälle:
//  grund='ki_kontingent'|'bild_kontingent' → Monatskontingent erschöpft (Abo-Modell v4).
//  grund='kein_guthaben' → kein aktives Abo & kein Guthaben → Abo abschließen / aufladen.
//  grund='limit'         → Abo-Volumen erschöpft → Pay-as-you-go weiter / Tarif aufstocken.
// In der nativen App (IST_NATIVE) nur neutrale Zustände: keine Preise, keine Kauf-/Upgrade-
// Aufforderung, kein Verweis auf die Web-Version (Google-Play-Payments-/Anti-Steering-Richtlinie).
export default function LimitDialog({ info, onClose, onUpgrade, notify }) {
  const [busy, setBusy] = useState(false)
  const preise = usePreise()   // Preise/Kontingente aus der Preisliste, nicht aus dem Code
  if (!info) return null
  const opt = info.optionen || {}
  const tarif = info.tarif || {}
  const keinGuthaben = info.grund === 'kein_guthaben'
  const istKontingent = info.grund === 'ki_kontingent' || info.grund === 'bild_kontingent'

  async function starteAbo() {
    setBusy(true)
    try {
      const r = await api.aboCheckout()
      if (r?.url) { window.location.href = r.url; return }
      notify?.('Abo konnte nicht gestartet werden.', 'err'); setBusy(false)
    } catch (e) { notify?.(e.message || 'Fehler', 'err'); setBusy(false) }
  }
  async function kaufeCredits() {
    setBusy(true)
    try {
      const r = await api.creditsCheckout()
      if (r?.url) { window.location.href = r.url; return }
      notify?.('Kauf konnte nicht gestartet werden.', 'err'); setBusy(false)
    } catch (e) { notify?.(e.message || 'Fehler', 'err'); setBusy(false) }
  }

  if (istKontingent && IST_NATIVE) {
    const istBild = info.grund === 'bild_kontingent'
    return (
      <Modal open onClose={onClose} title={istBild ? 'Bild-Kontingent aufgebraucht' : 'KI-Kontingent aufgebraucht'}>
        <div className="space-y-3">
          <p className="text-sm text-muted">
            {istBild
              ? <>Dein <b>Bild-Kontingent</b> für diesen Monat ist aufgebraucht ({info.monats_bilder}/{info.bild_limit}).</>
              : <>Dein <b>KI-Kontingent</b> für diesen Monat ist aufgebraucht ({info.monats_ki}/{info.ki_limit}).</>}
            {' '}Es erneuert sich am <b>{naechsterMonatserster()}</b>. Alle Funktionen ohne KI kannst du weiter nutzen.
          </p>
          <Button onClick={onClose} className="w-full">OK</Button>
        </div>
      </Modal>
    )
  }

  if (istKontingent) {
    const istBild = info.grund === 'bild_kontingent'
    const opt2 = info.optionen || {}
    return (
      <Modal open onClose={onClose} title={istBild ? 'Bild-Kontingent aufgebraucht' : 'KI-Kontingent aufgebraucht'}>
        <div className="space-y-3">
          <p className="text-sm text-muted">
            {istBild
              ? <>Dein <b>Bild-Kontingent</b> für diesen Monat ist aufgebraucht ({info.monats_bilder}/{info.bild_limit}).{preise && <> Mit <b>Topfplan</b> bekommst du {kontingent(preise.abo.bild_limit, 'Bilder')}/Monat</>} – oder kauf ein Foto-Credit-Pack.</>
              : <>Dein <b>Gratis-KI-Kontingent</b> ist diesen Monat erreicht ({info.monats_ki}/{info.ki_limit}).{preise && <> Mit <b>Topfplan</b> nutzt du KI-Funktionen {kontingent(preise.abo.ki_limit)}.</>}</>}
          </p>
          <div className="space-y-2">
            {opt2.abo_moeglich && !IST_NATIVE && preise && (
              <Button onClick={starteAbo} disabled={busy} className="w-full">
                {busy ? <Spinner /> : `Topfplan abonnieren – ${euro(preise.abo.preis_cents)}/Monat`}
              </Button>
            )}
            {istBild && opt2.credits_kaufen_moeglich && !IST_NATIVE && preise && (
              <button onClick={kaufeCredits} disabled={busy}
                className="w-full rounded-xl border border-olive/40 bg-olive/10 py-2.5 text-sm font-semibold text-olive hover:bg-olive/20 disabled:opacity-50">
                Foto-Credits kaufen – {preise.foto_pack.credits} für {euro(preise.foto_pack.preis_cents)}
              </button>
            )}
            <button onClick={onClose} className="w-full py-1 text-xs text-muted2 hover:text-ink">später</button>
          </div>
        </div>
      </Modal>
    )
  }

  async function payg() {
    setBusy(true)
    try {
      await api.paygOverageSetzen(true)
      notify?.('Pay-as-you-go aktiviert (gilt bis zur nächsten Freischaltung) — bitte die Aktion erneut auslösen.', 'ok')
      onClose()
    } catch (e) { notify?.(e.message || 'Fehler', 'err') }
    finally { setBusy(false) }
  }

  if (keinGuthaben && IST_NATIVE) {
    return (
      <Modal open onClose={onClose} title="KI nicht verfügbar">
        <div className="space-y-3">
          <p className="text-sm text-muted">
            Die KI-Funktionen sind für dein Konto gerade nicht freigeschaltet. Alle Funktionen ohne KI kannst du weiter nutzen.
          </p>
          <Button onClick={onClose} className="w-full">OK</Button>
        </div>
      </Modal>
    )
  }

  if (keinGuthaben) {
    return (
      <Modal open onClose={onClose} title="KI freischalten">
        <div className="space-y-3">
          <p className="text-sm text-muted">
            {ABO_AKTIV
              ? <>Für KI-Funktionen brauchst du ein <b>aktives Abo</b> oder <b>Guthaben</b>. Schließe ein Abo ab oder lade Guthaben auf, dann läuft die KI sofort weiter.</>
              : <>Für KI-Funktionen brauchst du <b>Guthaben</b>. Lade dein Guthaben auf, dann läuft die KI sofort weiter.</>}
          </p>
          <div className="space-y-2">
            {ABO_AKTIV && <Button onClick={() => { onClose(); onUpgrade?.() }} className="w-full">Abo abschließen</Button>}
            <button onClick={() => { onClose(); onUpgrade?.() }}
              className="w-full rounded-xl border border-olive/40 bg-olive/10 py-2.5 text-sm font-semibold text-olive hover:bg-olive/20">
              Guthaben aufladen
            </button>
            <button onClick={onClose} className="w-full py-1 text-xs text-muted2 hover:text-ink">später</button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal open onClose={onClose} title="Nutzungslimit erreicht">
      <div className="space-y-3">
        <p className="text-sm text-muted">
          Im Tarif <b>{tarif.name}</b> ist dein <b>{FENSTER[info.limit] || 'Limit'}</b> erreicht.
          Die KI pausiert, bis das Volumen zurückgesetzt wird.
        </p>
        {info.verbrauch && (
          <div className="space-y-2 rounded-xl border border-line p-3">
            <LimitBar label="Letzte 24 h" used={info.verbrauch.tag} limit={tarif.tages_limit_cents} />
            <LimitBar label="Letzte 7 Tage" used={info.verbrauch.woche} limit={tarif.wochen_limit_cents} />
          </div>
        )}
        <p className="flex items-start gap-1 rounded-lg bg-surface px-2.5 py-1.5 text-[11px] text-muted">
          <Icon name="image" size={16} className="shrink-0" /> Tipp: Bilder verbrauchen besonders viel Volumen — günstigere Bildstufe wählen. Größere KI-Modelle verbrauchen schneller.
        </p>
        <div className="space-y-2">
          {opt.payg_moeglich && !IST_NATIVE && (
            <Button onClick={payg} disabled={busy} className="w-full">
              {busy ? <Spinner /> : `Pay-as-you-go weiter (Guthaben: ${euro(info.guthaben_cents)})`}
            </Button>
          )}
          {opt.upgrade_moeglich && !IST_NATIVE && (
            <button onClick={() => { onClose(); onUpgrade?.() }}
              className="w-full rounded-xl border border-terracotta/40 bg-terracotta/10 py-2.5 text-sm font-semibold text-terracotta hover:bg-terracotta/20">
              Tarif aufstocken
            </button>
          )}
          {!opt.payg_moeglich && !IST_NATIVE && (
            <p className="text-center text-xs text-muted2">Kein Guthaben für Pay-as-you-go vorhanden — bitte Tarif aufstocken oder Guthaben aufladen.</p>
          )}
          <button onClick={onClose} className="w-full py-1 text-xs text-muted2 hover:text-ink">später</button>
        </div>
      </div>
    </Modal>
  )
}
