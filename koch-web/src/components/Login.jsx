import { useState } from 'react'
import { api } from '../api.js'
import { Button, input, Spinner } from '../ui.jsx'
import { RechtFooter } from './Rechtliches.jsx'

// Cloche-Emblem (Servierglocke + Kräuter-Sprig + Schaltkreis-Knoten) – Marken-Emblem
// aus dem Redesign. Kupfer + Grün fest, da die Kachel in beiden Themes dunkel bleibt.
function ClocheEmblem({ size = 74 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" className="relative" aria-hidden>
      <g stroke="#7bc492" strokeWidth="1.6" opacity=".7">
        <path d="M16 96h12M92 96h12M22 96v-8M98 96v-8" strokeLinecap="round" />
        <circle cx="22" cy="86" r="2.4" fill="#7bc492" stroke="none" />
        <circle cx="98" cy="86" r="2.4" fill="#7bc492" stroke="none" />
      </g>
      <path d="M28 86a32 32 0 0 1 64 0" stroke="#e3a86a" strokeWidth="5" strokeLinecap="round" />
      <circle cx="60" cy="48" r="4.5" fill="#e3a86a" />
      <path d="M60 52v6" stroke="#e3a86a" strokeWidth="4" strokeLinecap="round" />
      <path d="M52 70c8-11 16-11 24 0" stroke="#7bc492" strokeWidth="4.5" strokeLinecap="round" />
      <rect x="24" y="86" width="72" height="6" rx="3" fill="#e3a86a" />
    </svg>
  )
}

function EmblemKachel({ large = false }) {
  return (
    <div className={`login-emblem relative flex shrink-0 items-center justify-center overflow-hidden ${large ? 'h-[108px] w-[108px] rounded-[26px]' : 'h-28 w-28 rounded-[30px]'}`}>
      <span className="pointer-events-none absolute h-20 w-20 rounded-full" style={{ background: 'radial-gradient(circle, rgba(227,168,106,.28), transparent 68%)' }} />
      <ClocheEmblem size={large ? 74 : 86} />
    </div>
  )
}

function FeldLabel({ label, children }) {
  return (
    <label className="block">
      <span className="label-mono mb-2 block text-muted2">{label}</span>
      {children}
    </label>
  )
}

function FeaturePill({ tone = 'copper', children }) {
  const c = tone === 'green'
    ? 'border-olive/30 bg-olive/12 text-olive'
    : 'border-terracotta/30 bg-terracotta/12 text-terracotta'
  return <span className={`label-mono rounded-full border px-3 py-1.5 ${c}`}>{children}</span>
}

// `beta` = Infos zum Anmeldelink /beta/<slug> (aus GET /auth/beta/<slug>) oder null.
// Mit freien Plätzen startet die Seite direkt im Registrieren-Modus und der Kanal wird
// mitgeschickt; das Backend setzt dann den Vollzugang. Ist der Kanal voll, bleibt es die
// normale Registrierung – der Hinweis sagt das offen.
export default function Login({ onAuthed, beta = null }) {
  const betaOffen = !!beta?.offen
  const [modus, setModus] = useState(beta ? 'register' : 'login')  // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [passwort, setPasswort] = useState('')
  const [passwort2, setPasswort2] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState('')
  const [info, setInfo] = useState('')

  async function passwortVergessen() {
    setFehler(''); setInfo('')
    if (!email.trim()) { setFehler('Bitte zuerst deine E-Mail oben eingeben.'); return }
    try { await api.passwortResetAnfordern(email.trim()) } catch { /* ignore */ }
    setInfo('Falls ein Konto mit dieser E-Mail existiert, haben wir dir einen Link zum Zurücksetzen geschickt.')
  }

  async function absenden() {
    setFehler(''); setInfo('')
    if (!email.trim() || !passwort) { setFehler('E-Mail und Passwort eingeben.'); return }
    if (modus === 'register' && passwort.length < 8) { setFehler('Passwort: mindestens 8 Zeichen.'); return }
    if (modus === 'register' && passwort !== passwort2) { setFehler('Die Passwörter stimmen nicht überein.'); return }
    setBusy(true)
    try {
      const res = modus === 'login'
        ? await api.authLogin(email.trim(), passwort)
        : await api.authRegister(email.trim(), passwort, name.trim(), betaOffen ? beta.slug : null)
      api.setToken(res.token)
      if (modus === 'register') { try { localStorage.setItem('onboarding_pending', '1') } catch { /* ignore */ } }
      onAuthed(res)
    } catch (e) {
      setFehler(String(e.message || e) || 'Fehlgeschlagen')
    } finally {
      setBusy(false)
    }
  }

  const istLogin = modus === 'login'

  return (
    <div className="min-h-screen lg:flex">
      {/* Brand-Panel (Desktop) */}
      <div className="login-brand relative hidden flex-col justify-center p-16 lg:flex lg:flex-1">
        <div className="login-brand-raster" />
        <div className="login-glow" />
        <div className="relative">
          <div className="flex items-center gap-5">
            <EmblemKachel large />
            <div>
              <div className="topfplan-wortmarke text-5xl">Topfplan</div>
              <div className="label-mono mt-2 text-terracotta">Genuss mit Verstand</div>
            </div>
          </div>
          <h1 className="font-dish mt-11 max-w-md text-6xl leading-[1.06] text-ink">
            {istLogin ? 'Willkommen zurück.' : 'Schön, dich kennenzulernen.'}
          </h1>
          <p className="mt-4 max-w-sm text-lg leading-relaxed text-muted">
            Koche schlau – aus deinem Vorrat, aktuellen Angeboten und für deine Geräte.
          </p>
          <div className="mt-8 flex flex-wrap gap-2.5">
            <FeaturePill tone="copper">Vorrat</FeaturePill>
            <FeaturePill tone="green">Angebote</FeaturePill>
            <FeaturePill tone="copper">Geführtes Kochen</FeaturePill>
          </div>
        </div>
      </div>

      {/* Formular-Panel */}
      <div className="flex min-h-screen w-full flex-col justify-center px-6 py-10 sm:px-10 lg:w-[520px] lg:flex-none lg:border-l lg:border-line lg:bg-card lg:px-14">
        {/* Marken-Kopf (Mobil) */}
        <div className="mb-8 flex flex-col items-center text-center lg:hidden">
          <EmblemKachel />
          <div className="topfplan-wortmarke mt-5 text-3xl">Topfplan</div>
          <div className="label-mono mt-1.5 text-terracotta">Genuss mit Verstand</div>
        </div>

        <div className="mx-auto w-full max-w-sm lg:max-w-none">
          <h2 className="font-dish text-4xl leading-tight text-ink">
            {betaOffen && !istLogin ? 'Willkommen zum Beta-Test.' : istLogin ? 'Melde dich an.' : 'Erstelle deinen Account.'}
          </h2>
          <p className="mt-2 text-sm text-muted">
            {betaOffen && !istLogin
              ? `Du testest Topfplan ${beta.trial_tage} Tage lang mit allen Funktionen – kostenlos und ohne Zahlungsdaten.`
              : istLogin ? 'Schön, dass du wieder da bist.' : 'In einer Minute startklar.'}
          </p>

          {/* Beta-Banner: nur auf den /beta/<slug>-Links. Zahlen kommen vom Server, damit
              hier nichts Falsches steht, wenn Plätze oder Laufzeit geändert werden. */}
          {beta && !istLogin && (
            betaOffen ? (
              <div className="mt-5 rounded-2xl border border-olive/40 bg-olive/10 p-4">
                <p className="label-mono text-olive">Beta · {beta.name}</p>
                <ul className="mt-2 space-y-1 text-sm text-ink/80">
                  <li>Voller Zugang für <b>{beta.trial_tage} Tage</b>, danach automatisch die Gratis-Version</li>
                  <li>Kein Abo, keine Zahlungsdaten, keine automatische Verlängerung</li>
                  <li>Noch <b>{beta.frei}</b> von {beta.plaetze} Plätzen frei</li>
                </ul>
                <p className="mt-2 text-xs text-muted2">
                  Im Gegenzug freuen wir uns über ehrliches Feedback – auch über das, was nicht gefällt.
                </p>
              </div>
            ) : (
              <div className="mt-5 rounded-2xl border border-line bg-surface p-4">
                <p className="label-mono text-muted2">Beta · {beta.name}</p>
                <p className="mt-2 text-sm text-ink/80">
                  Die {beta.plaetze} Beta-Plätze für diesen Link sind belegt. Du kannst Topfplan
                  trotzdem nutzen: Registriere dich normal – alle Funktionen ohne KI sind frei,
                  für die KI gibt es ein monatliches Gratis-Kontingent.
                </p>
              </div>
            )
          )}

          <div className="mt-8 space-y-4">
            {!istLogin && (
              <FeldLabel label="Name">
                <input className={input} placeholder="z. B. Max Mustermann" value={name} onChange={(e) => setName(e.target.value)} />
              </FeldLabel>
            )}
            <FeldLabel label="E-Mail">
              <input className={input} type="email" autoComplete="email" placeholder="name@beispiel.de" value={email} onChange={(e) => setEmail(e.target.value)} />
            </FeldLabel>
            <FeldLabel label="Passwort">
              <input
                className={input}
                type="password"
                autoComplete={istLogin ? 'current-password' : 'new-password'}
                placeholder="••••••••"
                value={passwort}
                onChange={(e) => setPasswort(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && istLogin) absenden() }}
              />
            </FeldLabel>
            {istLogin && (
              <div className="-mt-1 text-right">
                <button type="button" onClick={passwortVergessen} className="text-sm text-muted hover:text-ink hover:underline">Passwort vergessen?</button>
              </div>
            )}
            {!istLogin && (
              <FeldLabel label="Passwort wiederholen">
                <input
                  className={input}
                  type="password"
                  autoComplete="new-password"
                  placeholder="••••••••"
                  value={passwort2}
                  onChange={(e) => setPasswort2(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') absenden() }}
                />
              </FeldLabel>
            )}
            {fehler && <p className="text-sm font-semibold text-terracotta">{fehler}</p>}
            {info && <p className="text-sm font-semibold text-olive">{info}</p>}
            <Button onClick={absenden} disabled={busy} className="w-full py-4 text-base">
              {busy ? <Spinner /> : (istLogin ? 'Anmelden' : 'Account erstellen')}
            </Button>
          </div>

          <p className="mt-5 text-center text-sm text-muted">
            {istLogin ? (
              <>Noch kein Account? <button onClick={() => { setModus('register'); setFehler('') }} className="font-bold text-terracotta hover:underline">Registrieren</button></>
            ) : (
              <>Schon registriert? <button onClick={() => { setModus('login'); setFehler('') }} className="font-bold text-terracotta hover:underline">Anmelden</button></>
            )}
          </p>
          <RechtFooter className="mt-6 border-t border-line pt-5" />
        </div>
      </div>
    </div>
  )
}
