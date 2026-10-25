import { useState } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { Icon } from '../icons.jsx'

// Kündigungsseite nach § 312k BGB – erreichbar über /kuendigen, bewusst OHNE Anmeldung.
// Die Vorschrift verlangt: ein dauerhaft verfügbarer, gut lesbarer Kündigungsbutton
// („Verträge hier kündigen", s. RechtFooter), der auf diese Bestätigungsseite führt, hier die
// Angaben zur Kündigung aufnimmt, einen eindeutig beschrifteten Bestätigungsbutton
// („Jetzt kündigen") bereitstellt und den Zugang sofort in Textform bestätigt.
//
// Zweistufig (Sicherheitsfix S-1): Dieses Formular protokolliert die Kündigung nur und mailt
// einen Bestätigungslink (POST /auth/kuendigung). Gekündigt wird erst, wenn der Link aus dem
// Postfach mit /kuendigen#bestaetigen=<token> geöffnet UND hier erneut bestätigt wird – nie
// allein auf Basis der eingegebenen E-Mail und nie automatisch beim Laden des Links (damit
// z. B. Mail-Scanner keine Kündigung auslösen). Die Kündigung gilt als zum Zeitpunkt des
// Eingangs erklärt; die Antwort hier ist neutral (verrät nicht, ob ein Konto existiert, S-2).
// Das Token steckt im URL-Fragment und wird beim Lesen aus der Adresszeile entfernt
// (AuthGate.jsx), damit es nicht in Logs oder der Browser-History landet.
export default function Kuendigung({ token, onClose }) {
  return token ? <Bestaetigen token={token} onClose={onClose} /> : <Anfordern onClose={onClose} />
}

// Stufe 1: Kündigungsformular → Nachweis + Bestätigungslink per E-Mail.
function Anfordern({ onClose }) {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [art, setArt] = useState('ordentlich')
  const [grund, setGrund] = useState('')
  const [zumDatum, setZumDatum] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [quittung, setQuittung] = useState(null)

  async function kuendigen() {
    setFehler('')
    if (!email.trim()) { setFehler('Bitte die E-Mail-Adresse deines Topfplan-Kontos angeben.'); return }
    if (art === 'ausserordentlich' && !grund.trim()) {
      setFehler('Für eine außerordentliche Kündigung bitte einen Grund angeben.'); return
    }
    setBusy(true)
    try {
      const res = await api.kuendigungSenden({
        email: email.trim(), name: name.trim(), art, grund: grund.trim(),
        zum_datum: zumDatum || null, vertrag: 'Topfplan-Abo',
      })
      setQuittung(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Senden fehlgeschlagen')
    } finally { setBusy(false) }
  }

  // Empfangsbestätigung auf der Seite – zusätzlich zur Bestätigung per E-Mail.
  // Bewusst ohne kontoabhängige Angaben (S-2): kein Vertragsende, keine Existenz-Auskunft.
  if (quittung) {
    const dt = (s) => { try { return new Date(s).toLocaleString('de-DE') } catch { return s } }
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
        <div className="rounded-2xl border border-olive/40 bg-olive/10 p-6">
          <p className="flex items-center gap-2 font-display text-xl text-olive">
            <Icon name="circle-check" size={20} /> Kündigung eingegangen
          </p>
          <dl className="mt-4 space-y-1.5 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-muted2">Vertrag</dt><dd className="font-semibold">{quittung.vertrag}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted2">Art</dt><dd className="font-semibold">{quittung.art === 'ausserordentlich' ? 'außerordentlich' : 'ordentlich'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted2">Eingegangen am</dt><dd className="font-semibold">{dt(quittung.eingegangen)}</dd></div>
          </dl>
          <p className="mt-4 text-sm text-ink/80">{quittung.hinweis}</p>
          <p className="mt-2 text-xs text-muted2">
            Deine Kündigung gilt als zu dem oben genannten Eingangszeitpunkt erklärt. Dein Abo
            beenden wir erst, wenn du den Bestätigungslink in der E-Mail anklickst.
          </p>
        </div>
        <button onClick={onClose} className="mt-6 text-sm text-muted2 hover:text-ink hover:underline">
          Zurück zu Topfplan
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
      <h1 className="font-dish text-4xl leading-tight text-ink">Vertrag kündigen</h1>
      <p className="mt-3 text-sm text-muted">
        Hier kündigst du dein Topfplan-Abo – ohne Anmeldung. Fülle die Felder aus und bestätige
        unten. Wir protokollieren deine Kündigung sofort und schicken dir eine E-Mail mit
        einem Bestätigungslink; erst dein Klick darauf beendet das Abo. So kann niemand
        allein mit deiner E-Mail-Adresse eine Kündigung auslösen.
      </p>

      <div className="mt-8 space-y-4">
        <label className="block">
          <span className="label-mono mb-2 block text-muted2">Art der Kündigung</span>
          <div className="space-y-2">
            {[['ordentlich', 'Ordentliche Kündigung', 'Zum Ende der bezahlten Laufzeit.'],
              ['ausserordentlich', 'Außerordentliche Kündigung', 'Aus wichtigem Grund – bitte unten angeben.']].map(([k, t, h]) => (
              <button key={k} type="button" onClick={() => setArt(k)}
                className={`w-full rounded-xl border p-3 text-left transition ${art === k ? 'border-terracotta bg-terracotta/5' : 'border-line hover:border-terracotta/40'}`}>
                <p className="font-semibold">{t}</p>
                <p className="text-xs text-muted2">{h}</p>
              </button>
            ))}
          </div>
        </label>

        <label className="block">
          <span className="label-mono mb-2 block text-muted2">E-Mail deines Topfplan-Kontos *</span>
          <input className={input} type="email" autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="du@beispiel.de" />
        </label>

        <label className="block">
          <span className="label-mono mb-2 block text-muted2">Name (optional)</span>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <label className="block">
          <span className="label-mono mb-2 block text-muted2">
            Kündigung zum (optional){art === 'ausserordentlich' ? '' : ' – sonst zum Laufzeitende'}
          </span>
          <input className={input} type="date" value={zumDatum} onChange={(e) => setZumDatum(e.target.value)} />
        </label>

        <label className="block">
          <span className="label-mono mb-2 block text-muted2">
            Grund {art === 'ausserordentlich' ? '*' : '(optional)'}
          </span>
          <textarea rows={3} className={input + ' resize-none'} value={grund}
            onChange={(e) => setGrund(e.target.value)}
            placeholder={art === 'ausserordentlich' ? 'Wichtiger Grund für die außerordentliche Kündigung' : 'Freiwillig – hilft uns, Topfplan besser zu machen.'} />
        </label>

        {fehler && <p className="rounded-xl border border-terracotta/40 bg-terracotta/10 px-3 py-2 text-sm text-terracotta-deep">{fehler}</p>}

        {/* Eindeutig beschrifteter Bestätigungsbutton (§ 312k) */}
        <Button onClick={kuendigen} disabled={busy} className="w-full py-3.5 text-base">
          {busy ? <Spinner /> : 'Jetzt kündigen'}
        </Button>

        <p className="text-xs text-muted2">
          Deine Kündigung wird mit Datum und Uhrzeit protokolliert und gilt als zu diesem
          Eingangszeitpunkt erklärt. Nach dem Vertragsende läuft dein Konto in der kostenlosen
          Version weiter – Rezepte, Pläne und Vorräte bleiben erhalten. Das Konto selbst
          löschst du in den Einstellungen.
        </p>
        {/* Abgrenzung: Kündigung beendet das Abo, Löschung entfernt das Konto (Play:
            öffentliche Web-Adresse für die Kontolöschung). */}
        <p className="text-xs text-muted2">
          Du willst nicht nur das Abo beenden, sondern dein Konto dauerhaft löschen?{' '}
          <a href="/konto-loeschen" className="font-semibold text-terracotta-deep hover:underline">
            Konto löschen
          </a>
        </p>
        <button onClick={onClose} className="w-full py-1 text-sm text-muted2 hover:text-ink hover:underline">
          Abbrechen
        </button>
      </div>
    </div>
  )
}

// Stufe 2: Bestätigungslink aus der Mail (#bestaetigen=<token>) → Abo zum Periodenende
// kündigen, aber erst nach ausdrücklichem Klick (kein Auto-Submit beim Laden).
function Bestaetigen({ token, onClose }) {
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [quittung, setQuittung] = useState(null)

  async function jetztKuendigen() {
    setFehler('')
    setBusy(true)
    try {
      const res = await api.kuendigungBestaetigen(token)
      setQuittung(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Kündigen fehlgeschlagen')
    } finally { setBusy(false) }
  }

  if (quittung) {
    const dt = (s) => { try { return new Date(s).toLocaleString('de-DE') } catch { return s } }
    const d = (s) => { try { return new Date(s + 'T00:00:00').toLocaleDateString('de-DE') } catch { return s } }
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
        <div className="rounded-2xl border border-olive/40 bg-olive/10 p-6">
          <p className="flex items-center gap-2 font-display text-xl text-olive">
            <Icon name="circle-check" size={20} /> Kündigung bestätigt
          </p>
          <dl className="mt-4 space-y-1.5 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-muted2">Vertrag</dt><dd className="font-semibold">{quittung.vertrag}</dd></div>
            {quittung.eingegangen && (
              <div className="flex justify-between gap-4"><dt className="text-muted2">Eingegangen am</dt><dd className="font-semibold">{dt(quittung.eingegangen)}</dd></div>
            )}
            {quittung.vertrag_bis && (
              <div className="flex justify-between gap-4"><dt className="text-muted2">Vertrag endet am</dt><dd className="font-semibold">{d(quittung.vertrag_bis)}</dd></div>
            )}
          </dl>
          <p className="mt-4 text-sm text-ink/80">{quittung.hinweis}</p>
        </div>
        <button onClick={onClose} className="mt-6 text-sm text-muted2 hover:text-ink hover:underline">
          Zurück zu Topfplan
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-12">
      <h1 className="font-dish text-4xl leading-tight text-ink">Kündigung bestätigen</h1>
      <p className="mt-3 text-sm text-muted">
        Du hast die Kündigung deines Topfplan-Abos angefordert – sie gilt bereits als zum
        Zeitpunkt des Eingangs erklärt. Bestätige hier, damit wir das Abo zum Ende der
        bereits bezahlten Laufzeit beenden. Dein Konto läuft danach in der kostenlosen
        Version weiter; Rezepte, Pläne und Vorräte bleiben erhalten. Die Bestätigung mit
        dem Vertragsende schicken wir dir per E-Mail.
      </p>

      <div className="mt-8 space-y-4">
        {fehler && <p className="rounded-xl border border-terracotta/40 bg-terracotta/10 px-3 py-2 text-sm text-terracotta-deep">{fehler}</p>}

        <Button onClick={jetztKuendigen} disabled={busy} className="w-full py-3.5 text-base">
          {busy ? <Spinner /> : 'Abo jetzt kündigen'}
        </Button>

        <button onClick={onClose} className="w-full py-1 text-sm text-muted2 hover:text-ink hover:underline">
          Abbrechen – Abo behalten
        </button>
      </div>
    </div>
  )
}
