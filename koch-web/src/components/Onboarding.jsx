import { useState, useEffect } from 'react'
import { api } from '../api.js'
import { Modal, Button, input, Spinner } from '../ui.jsx'
import { Icon } from '../icons.jsx'

const GERAETE_VORSCHLAEGE = ['Backofen', 'Herd', 'Mikrowelle', 'Heißluftfritteuse', 'Thermomix', 'Standmixer', 'Toaster', 'Wasserkocher']

// Geführter Einrichtungs-Assistent für neue Haushalte.
export default function Onboarding({ onClose, notify, vorratAktiv, onVorratChange }) {
  const STEPS = ['Willkommen', 'Personen', 'Geräte', 'Vorrat', 'Assistent', 'Fertig']
  const [step, setStep] = useState(0)
  const [personen, setPersonen] = useState([])
  const [geraete, setGeraete] = useState([])
  const [pName, setPName] = useState('')
  const [pRolle, setPRolle] = useState('erwachsener')
  const [gName, setGName] = useState('')
  const [busy, setBusy] = useState(false)
  const [fotoBusy, setFotoBusy] = useState(false)

  useEffect(() => {
    api.personen().then((p) => setPersonen(p || [])).catch(() => {})
    api.geraete().then((g) => setGeraete(g || [])).catch(() => {})
  }, [])

  async function geraeteFoto(e) {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file) return
    setFotoBusy(true)
    try {
      const res = await api.geraeteFoto(file)
      const namen = (res?.vorschlag || []).map((v) => (typeof v === 'string' ? v : v?.name)).filter(Boolean)
      let n = 0
      for (const nm of namen) {
        if (!geraete.some((g) => g.name.toLowerCase() === nm.toLowerCase())) { await addGeraet(nm); n++ }
      }
      notify && notify(n ? `${n} Gerät${n === 1 ? '' : 'e'} erkannt` : 'Keine neuen Geräte erkannt')
    } catch { notify && notify('Foto-Erkennung fehlgeschlagen', 'err') }
    finally { setFotoBusy(false) }
  }

  async function addPerson() {
    const name = pName.trim()
    if (!name) return
    setBusy(true)
    try {
      const p = await api.personAnlegen({
        name, rolle: pRolle, portionsfaktor: pRolle === 'kind' ? 0.5 : 1.0,
        eiweiss_pct: 30, fett_pct: 30, kh_pct: 40, aktiv: true,
        ernaehrung: '', allergien: '', mag_nicht: '', mag_gern: '',
      })
      setPersonen((l) => [...l, p]); setPName('')
    } catch { notify && notify('Anlegen fehlgeschlagen', 'err') } finally { setBusy(false) }
  }
  async function delPerson(id) {
    try { await api.personLoeschen(id); setPersonen((l) => l.filter((x) => x.id !== id)) } catch { /* ignore */ }
  }
  async function addGeraet(name) {
    const n = (name || '').trim()
    if (!n || geraete.some((g) => g.name.toLowerCase() === n.toLowerCase())) { setGName(''); return }
    setBusy(true)
    try { const g = await api.geraetAnlegen({ name: n, standard: true }); setGeraete((l) => [...l, g]); setGName('') }
    catch { notify && notify('Anlegen fehlgeschlagen', 'err') } finally { setBusy(false) }
  }
  async function delGeraet(id) {
    try { await api.geraetLoeschen(id); setGeraete((l) => l.filter((x) => x.id !== id)) } catch { /* ignore */ }
  }

  function fertig() {
    try { localStorage.setItem('onboarding_seen', '1') } catch { /* ignore */ }
    onClose()
  }

  // Abschluss mit direktem Aha-Moment: Onboarding schließen und den Rezept-Generator öffnen.
  function fertigMitRezept() {
    fertig()
    try { window.dispatchEvent(new CustomEvent('koch:rezept-erstellen')) } catch { /* ignore */ }
  }

  const offeneVorschlaege = GERAETE_VORSCHLAEGE.filter((v) => !geraete.some((g) => g.name.toLowerCase() === v.toLowerCase()))

  return (
    <Modal open onClose={fertig} title="Einrichtung">
      <div className="space-y-4">
        {/* Fortschritt */}
        <div className="flex items-center gap-1">
          {STEPS.map((s, i) => (
            <div key={s} className={`h-1.5 flex-1 rounded-full ${i <= step ? 'bg-terracotta' : 'bg-line'}`} />
          ))}
        </div>
        <p className="label-mono text-muted2">Schritt {step + 1} von {STEPS.length} · {STEPS[step]}</p>

        {step === 0 && (
          <div className="space-y-3">
            <h3 className="inline-flex items-center gap-1.5 font-dish text-4xl leading-tight text-ink">Willkommen bei Topfplan! <Icon name="hand" size={20} /></h3>
            <p className="text-sm text-muted">In wenigen Schritten ist alles startklar: wer mitisst, welche Küchengeräte ihr habt und ob du den Vorrat pflegen möchtest. Danach zeige ich dir kurz die KI-Funktionen.</p>
            <p className="inline-flex items-center gap-1 text-xs text-muted2">Du kannst jederzeit überspringen und später in den <Icon name="settings" size={16} /> Einstellungen erneut starten.</p>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Wer isst alles mit?</h3>
            <p className="text-sm text-muted">Lege <b>alle Personen</b> eures Haushalts an, die mitessen – das steuert Portionen und Vorschläge. Vorlieben/Allergien kannst du später ergänzen.</p>
            {personen.length > 0 && (
              <ul className="space-y-1">
                {personen.map((p) => (
                  <li key={p.id} className="flex items-center justify-between rounded-lg border border-line/60 bg-card/60 px-2.5 py-1.5 text-sm">
                    <span>{p.name} <span className="text-xs text-muted2">· {p.rolle === 'kind' ? 'Kind' : 'Erwachsene/r'}</span></span>
                    <button onClick={() => delPerson(p.id)} className="text-muted2 hover:text-terracotta-deep">×</button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex gap-2">
              {[['erwachsener', 'Erwachsene/r'], ['kind', 'Kind']].map(([v, l]) => (
                <button key={v} onClick={() => setPRolle(v)} className={`rounded-full px-3 py-1 text-xs font-semibold ${pRolle === v ? 'bg-terracotta text-on-accent' : 'border border-line text-muted'}`}>{l}</button>
              ))}
            </div>
            <div className="flex gap-2">
              <input className={input + ' flex-1'} value={pName} placeholder="Name, z.B. Max Mustermann" onChange={(e) => setPName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addPerson() }} />
              <Button onClick={addPerson} disabled={busy || !pName.trim()}>+ Person</Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Eure Küchengeräte</h3>
            <p className="text-sm text-muted">Tippe an, was ihr habt – das passt die Zubereitungs-Schritte der Rezepte an. Oder lass die KI eure Geräte per Foto erkennen.</p>
            <label className={`flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-olive/40 bg-olive/5 px-3 py-2 text-sm font-semibold text-olive hover:bg-olive/10 ${fotoBusy ? 'opacity-60' : ''}`}>
              {fotoBusy ? <Spinner /> : <><Icon name="camera" size={16} /> Geräte per Foto erkennen</>}
              <input type="file" accept="image/*" capture="environment" className="hidden" disabled={fotoBusy} onChange={geraeteFoto} />
            </label>
            {geraete.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {geraete.map((g) => (
                  <span key={g.id} className="inline-flex items-center gap-1 rounded-full bg-olive/15 px-2.5 py-1 text-sm font-semibold text-olive">
                    {g.name}<button onClick={() => delGeraet(g.id)} className="opacity-60 hover:opacity-100">×</button>
                  </span>
                ))}
              </div>
            )}
            {offeneVorschlaege.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {offeneVorschlaege.map((v) => (
                  <button key={v} onClick={() => addGeraet(v)} disabled={busy} className="rounded-full border border-line bg-card px-2.5 py-1 text-sm text-muted hover:border-olive/50">+ {v}</button>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input className={input + ' flex-1'} value={gName} placeholder="Anderes Gerät …" onChange={(e) => setGName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addGeraet(gName) }} />
              <Button onClick={() => addGeraet(gName)} disabled={busy || !gName.trim()}>+</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Vorratsverwaltung</h3>
            <p className="text-sm text-muted">Möchtest du euren Vorrat pflegen? Dann kannst du beim Einkauf abhaken, Mengen erfassen und siehst, welche Rezepte sofort kochbar sind.</p>
            <p className="inline-flex items-center gap-1 rounded-lg bg-surface px-2.5 py-1.5 text-xs text-muted2"><Icon name="camera" size={16} /> <span>Vorräte kannst du später bequem <b>per Foto/KI</b> erfassen – einfach im Assistenten (unten) ein Foto anhängen.</span></p>
            <div className="space-y-2">
              <button onClick={() => onVorratChange && onVorratChange(true)} className={`w-full rounded-xl border p-3 text-left ${vorratAktiv ? 'border-terracotta bg-terracotta/5' : 'border-line'}`}>
                <p className="inline-flex items-center gap-1 font-semibold"><Icon name="circle-check" size={16} /> Ja, Vorrat pflegen</p>
                <p className="text-xs text-muted2">Einkauf abhaken & in den Vorrat übernehmen, Verfügbarkeit prüfen.</p>
              </button>
              <button onClick={() => onVorratChange && onVorratChange(false)} className={`w-full rounded-xl border p-3 text-left ${!vorratAktiv ? 'border-terracotta bg-terracotta/5' : 'border-line'}`}>
                <p className="font-semibold">Nein, ohne Vorrat</p>
                <p className="text-xs text-muted2">Einfacher: nur Einkaufsliste abhaken, kein Vorrat.</p>
              </button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <h3 className="font-display text-xl">Deine KI-Funktionen</h3>
            <ul className="space-y-2 text-sm text-muted">
              <li className="flex items-start gap-1.5"><Icon name="message-circle" size={16} className="mt-0.5 shrink-0" /> <span><b>Assistent</b> (unten): Fragen zu Vorrat, Plan, Rezepten & Einkauf – oder Foto/PDF anhängen, um Vorräte, Rezepte oder Prospekte zu erfassen.</span></li>
              <li className="flex items-start gap-1.5"><Icon name="sparkles" size={16} className="mt-0.5 shrink-0" /> <span><b>Rezept erstellen</b> (Start): Ein Rezept passend zu Vorrat, Geräten, Angeboten & Vorlieben – auf Wunsch direkt mit Bild.</span></li>
              <li className="flex items-start gap-1.5"><Icon name="image" size={16} className="mt-0.5 shrink-0" /> <span><b>Rezeptbilder</b>: beim Erstellen erzeugen lassen (abwählbar) oder eigenes Foto hochladen. Übernimmst du ein Rezept aus der Bibliothek, kommt sein Bild mit.</span></li>
              <li className="flex items-start gap-1.5"><Icon name="tag" size={16} className="mt-0.5 shrink-0" /> <span><b>Angebote</b>: Prospekt fotografieren/hochladen → die KI erkennt die Angebote und macht Koch-Vorschläge.</span></li>
            </ul>
            <p className="inline-flex items-center gap-1 text-[11px] text-muted2"><Icon name="sparkles" size={14} className="text-terracotta" /> Mit dem Funkel-Symbol markierte Aktionen nutzen KI – sofern der Betreiber dieser Instanz einen KI-Anbieter eingerichtet hat.</p>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-4 text-center">
            <p className="flex justify-center text-terracotta"><Icon name="party-popper" size={20} /></p>
            <h3 className="font-dish text-4xl leading-tight text-ink">Fertig – los geht's!</h3>
            <p className="text-sm text-muted">
              {personen.length} {personen.length === 1 ? 'Person' : 'Personen'} · {geraete.length} {geraete.length === 1 ? 'Gerät' : 'Geräte'} · Vorrat {vorratAktiv ? 'an' : 'aus'}.
              Du kannst alles jederzeit im Haushalt und in den Einstellungen anpassen.
            </p>
            <Button variant="ki" className="mx-auto inline-flex items-center gap-1" onClick={fertigMitRezept}><Icon name="sparkles" size={16} /> Erstes Rezept erstellen</Button>
            <p className="text-xs text-muted2">… oder unten rechts „Loslegen" und in Ruhe umsehen.</p>
          </div>
        )}

        {/* Navigation */}
        <div className="flex items-center justify-between gap-2 pt-1">
          {step > 0 ? <Button variant="ghost" onClick={() => setStep((s) => s - 1)}>Zurück</Button> : <button onClick={fertig} className="text-sm text-muted2 hover:text-ink">Überspringen</button>}
          {step < STEPS.length - 1
            ? <Button onClick={() => setStep((s) => s + 1)}>Weiter</Button>
            : <Button onClick={fertig}>Loslegen</Button>}
        </div>
      </div>
    </Modal>
  )
}
