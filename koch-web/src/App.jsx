import { useState, useCallback, useEffect, useRef } from 'react'
import Vorrat from './components/Vorrat.jsx'
import { RechtFooter } from './components/Rechtliches.jsx'
import Rezepte from './components/Rezepte.jsx'
import Haushalt from './components/Haushalt.jsx'
import Planen from './components/Planen.jsx'
import SpontanesKochen from './components/SpontanesKochen.jsx'
import Einkaufsliste from './components/Einkaufsliste.jsx'
import Angebote from './components/Angebote.jsx'
import Start from './components/Start.jsx'
import Chat from './components/Chat.jsx'
import Onboarding from './components/Onboarding.jsx'
import AdminPanel from './components/AdminPanel.jsx'
import InstallHinweis from './components/InstallHinweis.jsx'
import BugReport from './components/BugReport.jsx'
import { Modal, Spinner, ConfirmHost, confirmDialog } from './ui.jsx'
import { Icon } from './icons.jsx'
import * as backnav from './backnav.js'
import { api, KI_NICHT_EINGERICHTET } from './api.js'
import { useChat } from './useChat.js'
import { useKi, ladeKiStatus } from './kiStatus.js'
import { getVorratAktiv, setVorratAktiv, getAbhakModus, setAbhakModus, getTheme, setTheme } from './settings.js'
import { posKey, ladeErledigt, bereinigeErledigt } from './einkaufErledigt.js'

// Alle Haupt-Bereiche (flache Navigation). Die untere Tab-Leiste zeigt die ersten vier
// + "Mehr"; Vorrat/Haushalt erreicht man über "Mehr".
const ALLE_GRUPPEN = ['start', 'rezepte', 'planen', 'angebote', 'vorrat', 'haushalt']
// Primäre Tabs der unteren Leiste (icon, label). "mehr" ist ein Sonderfall (öffnet Sheet).
const HAUPT_TABS = [
  ['start',    'Start',    'home'],
  ['rezepte',  'Rezepte',  'book-open'],
  ['planen',   'Planen',   'calendar'],
  ['angebote', 'Angebote', 'tag'],
]
// In "Mehr" untergebrachte Bereiche → die Tab-Leiste hebt dann "Mehr" hervor.
const MEHR_GRUPPEN = ['vorrat', 'haushalt']

function MehrLink({ icon, label, hint, onClick, badge }) {
  return (
    <button onClick={onClick} className="flex w-full items-center gap-3 rounded-2xl border border-line bg-surface p-3 text-left transition hover:border-terracotta/40 hover:bg-terracotta/5">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-terracotta/15 text-terracotta">
        <Icon name={icon} size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-display font-semibold">{label}</span>
        {hint && <span className="block text-xs text-muted2">{hint}</span>}
      </span>
      {badge != null
        ? <span className="flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full bg-terracotta px-1.5 text-xs font-bold text-on-accent">{badge}</span>
        : <Icon name="chevron-right" size={18} className="shrink-0 text-muted2" />}
    </button>
  )
}

export default function App({ auth, onLogout }) {
  // Aktiven Bereich über Reload hinweg merken (sonst springt die App auf "Start").
  const [gruppe, setGruppe] = useState(() => {
    let s = localStorage.getItem('nav_gruppe')
    if (s === 'kochen') s = localStorage.getItem('nav_kochTab') || 'rezepte'  // Migration alte 2-Ebenen-Nav
    return ALLE_GRUPPEN.includes(s) ? s : 'start'
  })
  const [mehrOffen, setMehrOffen] = useState(false)
  useEffect(() => { localStorage.setItem('nav_gruppe', gruppe) }, [gruppe])
  const [openRezeptId, setOpenRezeptId] = useState(null)   // Overlay-Host (über aktuellem Tab)
  const [angebotMarkt, setAngebotMarkt] = useState(null)   // Markt-Kontext fürs Detail (Angebots-Markierung)
  const [openInTabId, setOpenInTabId] = useState(null)     // im Rezepte-Tab öffnen ("Öffnen & kochen")
  const [toast, setToast] = useState(null)
  const [spontan, setSpontan] = useState(false)
  const [einkaufOffen, setEinkaufOffen] = useState(false)
  const [chatOffen, setChatOffen] = useState(false)
  const [settingsOffen, setSettingsOffen] = useState(false)
  const [adminOffen, setAdminOffen] = useState(false)
  const [onboardingOffen, setOnboardingOffen] = useState(false)
  const [warenkorbAnzahl, setWarenkorbAnzahl] = useState(0)
  const [warenkorbSpaeter, setWarenkorbSpaeter] = useState(false)

  // ---- Browser-Navigation: Tabs + Overlays an die History koppeln ----
  // Overlays (Modals) registrieren sich selbst im Back-Stack (siehe ui.Modal);
  // "Zurück" schließt zuerst ein offenes Overlay, sonst blättert es durch die Tabs.
  // (Reload bleibt via localStorage auf dem Tab.)
  const navSeeded = useRef(false)
  const navFromPop = useRef(false)
  const navReplaceNext = useRef(false)   // (reserviert) nächster Tab-Wechsel als replace
  useEffect(() => {
    if (!navSeeded.current) {
      navSeeded.current = true
      backnav.replaceState({ gruppe })
      return
    }
    if (navFromPop.current) { navFromPop.current = false; return }
    if (navReplaceNext.current) { navReplaceNext.current = false; backnav.replaceState({ gruppe }); return }
    backnav.pushState({ gruppe })
  }, [gruppe])
  useEffect(() => {
    backnav.setTabHandler((e) => {
      const s = e.state
      if (s && s.gruppe) {
        navFromPop.current = true
        setGruppe(s.gruppe)
      }
    })
  }, [])
  // Chat ist kein Modal -> manuell als Overlay registrieren, damit "Zurück" es schließt.
  useEffect(() => {
    if (!chatOffen) return
    return backnav.registerOverlay(() => setChatOffen(false))
  }, [chatOffen])

  // Warenkorb-Zähler (manuell ergänzte Artikel) – beim Schließen des Einkaufs aktualisieren.
  const ladeWarenkorb = useCallback(() => {
    // Badge = offene Artikel des NÄCHSTEN Einkaufstags (geplant + manuell, abzgl. abgehakter);
    // warenkorbSpaeter = es gibt zusätzlich Artikel für spätere Einkaufstage.
    const heute = new Date().toLocaleDateString('en-CA')
    api.einkaufsliste(heute).then((data) => {
      // Schlüsselformat + Bereinigung zentral in einkaufErledigt.js – identisch zur Liste,
      // sonst zählt der Badge anders als die Einkaufsliste anzeigt.
      const erledigt = bereinigeErledigt(ladeErledigt(), heute)
      const perioden = data?.perioden || []
      const next = perioden.find((p) => p.ist_einkaufstag && p.von >= heute) || null
      const offenePos = (p) => (p?.positionen || []).filter((pos) => !erledigt.has(posKey(p, pos))).length
      const manualOpen = (data?.manuell || []).filter((m) => !erledigt.has(`extra:${m.id}`)).length
      setWarenkorbAnzahl((next ? offenePos(next) : 0) + manualOpen)
      setWarenkorbSpaeter(perioden.filter((p) => p !== next).reduce((s, p) => s + offenePos(p), 0) > 0)
    }).catch(() => {})
  }, [])
  useEffect(() => { ladeWarenkorb() }, [ladeWarenkorb])
  useEffect(() => { if (!einkaufOffen) ladeWarenkorb() }, [einkaufOffen, ladeWarenkorb])

  // Onboarding: direkt nach Registrierung/Einladung (Flag 'onboarding_pending'),
  // sonst einmalig bei noch leerem Haushalt.
  useEffect(() => {
    // „Gesehen" pro KONTO (nicht pro Browser) – sonst bekommt ein neuer Account auf
    // einem bereits genutzten Browser nie das Onboarding.
    const seenKey = auth?.account?.id ? `onboarding_seen_${auth.account.id}` : 'onboarding_seen'
    let pending = false, seen = false
    try {
      pending = localStorage.getItem('onboarding_pending') === '1'
      seen = localStorage.getItem(seenKey) === '1'
    } catch { /* ignore */ }
    if (pending) {
      try { localStorage.removeItem('onboarding_pending') } catch { /* ignore */ }
      setOnboardingOffen(true)
      return
    }
    if (seen) return
    api.personen().then((p) => { if (!p || p.length === 0) setOnboardingOffen(true) }).catch(() => {})
  }, [])

  const [chatMemory, setChatMemory] = useState(null)
  useEffect(() => {
    if (settingsOffen && chatMemory === null) {
      api.chatMemory().then((r) => setChatMemory(!!r.aktiv)).catch(() => setChatMemory(true))
    }
  }, [settingsOffen, chatMemory])
  function toggleChatMemory(v) {
    setChatMemory(v)
    api.chatMemorySetzen(v).catch(() => { setChatMemory(!v); notify('Speichern fehlgeschlagen', 'err') })
  }
  const [autoBild, setAutoBild] = useState(null)
  useEffect(() => {
    if (settingsOffen && autoBild === null) {
      api.autoBild().then((r) => setAutoBild(!!r.aktiv)).catch(() => setAutoBild(false))
    }
  }, [settingsOffen, autoBild])
  function toggleAutoBild(v) {
    setAutoBild(v)
    api.autoBildSetzen(v).catch(() => { setAutoBild(!v); notify('Speichern fehlgeschlagen', 'err') })
  }
  // Vorrat-Modus: 'voll' (App-Vorrat) | 'light' (Freitext bei der Rezept-Generierung)
  const [vorratModus, setVorratModus] = useState(null)
  useEffect(() => {
    if (settingsOffen && vorratModus === null) {
      api.vorratModus().then((r) => setVorratModus(r.modus || 'voll')).catch(() => setVorratModus('voll'))
    }
  }, [settingsOffen, vorratModus])
  function waehleVorratModus(m) {
    const alt = vorratModus
    setVorratModus(m)
    api.vorratModusSetzen(m).catch(() => { setVorratModus(alt); notify('Speichern fehlgeschlagen', 'err') })
  }
  const [vorratAktiv, setVorratAktivState] = useState(getVorratAktiv)
  // Der Konto-Modus (Server) ist führend: lokalen Vorrat-Schalter beim Start angleichen.
  // Der Schalter lag bisher nur im localStorage des Geräts – wer z.B. in der App
  // „Vorrat light" wählt, sah im Browser trotzdem weiter „Sofort kochbar" & Co.
  useEffect(() => {
    api.vorratModus().then((r) => {
      const modus = r.modus || 'voll'
      setVorratModus(modus)
      const voll = modus !== 'light'
      if (voll !== getVorratAktiv()) toggleVorrat(voll)
    }).catch(() => { /* offline/Fehler: lokaler Stand bleibt */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [abhakModus, setAbhakModusState] = useState(getAbhakModus)
  const [theme, setThemeState] = useState(getTheme)
  function waehleTheme(t) { setThemeState(t); setTheme(t) }

  function toggleVorrat(v) {
    setVorratAktiv(v)
    setVorratAktivState(v)
    if (!v && gruppe === 'vorrat') setGruppe('planen')
  }

  // Eine Entweder-Oder-Wahl: 'voll' = volle Vorratsfunktion (lokale Verwaltung an, Server-Modus voll),
  // 'light' = nichts gespeichert (Verwaltung aus, Eingabe beim Generieren).
  function waehleVorrat(m) {
    const voll = m === 'voll'
    toggleVorrat(voll)
    waehleVorratModus(voll ? 'voll' : 'light')
  }

  function waehleAbhakModus(m) {
    setAbhakModus(m)
    setAbhakModusState(m)
  }

  // KI-Fähigkeiten der Instanz: nach Login bzw. Konto-/Nutzerwechsel neu laden.
  const ki = useKi()
  useEffect(() => { ladeKiStatus() }, [auth?.account?.id, auth?.user?.id])
  // Schlägt ein KI-Aufruf mit „nicht eingerichtet" fehl (s. api.js), zeigt App EINE
  // freundliche Meldung; generische Fehler-Toasts der Aufrufer kurz danach werden unterdrückt.
  const kiFehltBis = useRef(0)

  const notify = useCallback((text, kind = 'ok', action = null) => {
    if (kind === 'err' && Date.now() < kiFehltBis.current && text !== KI_NICHT_EINGERICHTET) return
    const id = Date.now() + Math.random()
    setToast({ text, kind, id, action })
    setTimeout(() => setToast((t) => (t && t.id === id ? null : t)), action ? 6500 : 5000)
  }, [])

  useEffect(() => {
    const h = () => {
      kiFehltBis.current = 0
      notify(KI_NICHT_EINGERICHTET, 'err')
      kiFehltBis.current = Date.now() + 2500
      ladeKiStatus()   // Status könnte veraltet sein → UI blendet die Funktion danach aus
    }
    window.addEventListener('koch:ki-fehlt', h)
    return () => window.removeEventListener('koch:ki-fehlt', h)
  }, [notify])
  // Chat ohne Text-KI schließen (z. B. nach Status-Neuladen).
  useEffect(() => { if (!ki.text) setChatOffen(false) }, [ki.text])

  // Chat-Zustand auf App-Ebene: läuft weiter, auch wenn das Fenster zu ist.
  const chat = useChat(notify)
  const [chatHinweis, setChatHinweis] = useState(null) // 'laeuft' | 'fertig' | null
  const prevChatLoading = useRef(false)
  useEffect(() => {
    if (chatOffen) {
      setChatHinweis(null)
    } else if (chat.loading) {
      setChatHinweis('laeuft')
    } else if (prevChatLoading.current) {
      setChatHinweis('fertig')   // wurde fertig, während das Fenster zu war
    }
    prevChatLoading.current = chat.loading
  }, [chat.loading, chatOffen])

  const openRezept = useCallback((id, opts = {}) => {
    setAngebotMarkt(opts.angebotMarkt || null)
    if (opts.bleibe) {
      // "Öffnen & kochen": in die Rezepte-Rubrik wechseln und dort öffnen.
      setGruppe('rezepte')
      setOpenInTabId(id)
    } else {
      // Normaler Klick (z.B. aus der Startübersicht): als Overlay ÜBER dem
      // aktuellen Tab öffnen – kein Tab-Wechsel, "Zurück" landet wieder dort.
      setOpenRezeptId(id)
    }
  }, [])

  // Deep-Link aus dem Kalender o.ä.: ?rezept=<id> öffnet das Rezept als Overlay.
  useEffect(() => {
    const rid = new URLSearchParams(window.location.search).get('rezept')
    if (rid && /^\d+$/.test(rid)) {
      setOpenRezeptId(Number(rid))
      window.history.replaceState(window.history.state, '', window.location.pathname)
    }
  }, [])

  // Onboarding-Abschluss „Erstes Rezept erstellen" → auf den Start-Tab wechseln
  // (dort fängt Start das Event ab und öffnet den Generator).
  useEffect(() => {
    const h = () => setGruppe('start')
    window.addEventListener('koch:rezept-erstellen', h)
    return () => window.removeEventListener('koch:rezept-erstellen', h)
  }, [])

  return (
    <div className="relative z-10 mx-auto max-w-3xl px-4 pb-28 pt-4 sm:pt-12">
      <InstallHinweis />
      <header className="mb-3 flex items-start justify-between gap-3 sm:mb-6">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="topfplan-wortmarke text-3xl leading-none sm:text-4xl">Topfplan</h1>
            <p className="label-mono mt-1 text-terracotta">Genuss mit Verstand</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 pt-1">
          <button
            onClick={() => setEinkaufOffen(true)}
            title="Einkaufsliste" aria-label="Einkaufsliste"
            className="relative rounded-full border border-line bg-card px-3 py-2 text-lg transition hover:border-olive/50"
          >
            <Icon name="shopping-cart" size={20} />
            {warenkorbAnzahl > 0 && (
              <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-terracotta px-1.5 text-xs font-bold text-on-accent shadow" title="Artikel für den nächsten Einkauf">{warenkorbAnzahl}</span>
            )}
            {warenkorbSpaeter && (
              <span className="absolute -left-1 -top-1 flex h-3 w-3 items-center justify-center rounded-full bg-terracotta text-[8px] text-on-accent shadow" title="Weitere Artikel für spätere Einkaufstage">⋯</span>
            )}
          </button>
          <button
            onClick={() => setSettingsOffen(true)}
            title="Einstellungen" aria-label="Einstellungen"
            className="rounded-full border border-line bg-card px-3 py-2 text-lg text-ink/60 transition hover:text-ink"
          >
            <Icon name="settings" size={20} />
          </button>
        </div>
      </header>

      <main key={gruppe} className="rise">
        {gruppe === 'start' && <Start notify={notify} openRezept={openRezept} vorratAktiv={vorratAktiv} />}
        {gruppe === 'rezepte' && (
          <Rezepte notify={notify} openRezeptId={openInTabId} clearOpen={() => setOpenInTabId(null)} defaultPortionen={2} onSpontan={() => setSpontan(true)} auth={auth} />
        )}
        {gruppe === 'planen' && <Planen notify={notify} openRezept={openRezept} />}
        {gruppe === 'vorrat' && <Vorrat notify={notify} />}
        {gruppe === 'angebote' && <Angebote notify={notify} auth={auth} openRezept={openRezept} />}
        {gruppe === 'haushalt' && <Haushalt notify={notify} superAdmin={auth?.user?.plattform_rolle === 'super_admin'} />}
      </main>

      {/* Assistent als schwebender Button über der Tab-Leiste (nur mit Text-KI) */}
      {ki.text && <button
        onClick={() => setChatOffen(true)}
        aria-label="Assistent öffnen" title="Assistent"
        className={`fixed right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full text-2xl shadow-glow transition ${
          chatHinweis === 'fertig' ? 'bg-olive text-white' : 'bg-terracotta text-on-accent hover:bg-terracotta-deep'
        } ${chatHinweis === 'laeuft' ? 'animate-pulse' : ''}`}
        style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 4.9rem)' }}
      >
        {chatHinweis === 'laeuft' ? <Spinner /> : <Icon name="message-circle" size={26} />}
      </button>}

      {/* Untere Tab-Leiste (Haupt-Navigation) */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-card/95 shadow-soft backdrop-blur">
        {ki.text && chatHinweis && !chatOffen && (
          <button
            onClick={() => setChatOffen(true)}
            className={`flex w-full items-center justify-center gap-2 border-b border-line px-4 py-1.5 text-xs font-semibold ${
              chatHinweis === 'laeuft' ? 'bg-terracotta/15 text-terracotta' : 'bg-olive/15 text-olive'
            }`}
          >
            {chatHinweis === 'laeuft'
              ? <><Spinner /> <span className="inline-flex items-center gap-1"><Icon name="bot" size={16} /> Assistent arbeitet im Hintergrund …</span></>
              : <span className="inline-flex items-center gap-1"><Icon name="circle-check" size={16} /> Assistent hat geantwortet – tippen zum Öffnen</span>}
          </button>
        )}
        <nav
          className="mx-auto grid max-w-3xl grid-cols-5"
          style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
        >
          {HAUPT_TABS.map(([k, label, icon]) => (
            <button
              key={k}
              onClick={() => { setMehrOffen(false); setGruppe(k) }}
              className={`flex flex-col items-center gap-0.5 py-2 text-[11px] transition ${
                gruppe === k ? 'font-bold text-terracotta' : 'font-semibold text-muted2 hover:text-ink'
              }`}
            >
              <Icon name={icon} size={22} className="leading-none" />
              {label}
            </button>
          ))}
          <button
            onClick={() => setMehrOffen(true)}
            className={`flex flex-col items-center gap-0.5 py-2 text-[11px] transition ${
              MEHR_GRUPPEN.includes(gruppe) || mehrOffen ? 'font-bold text-terracotta' : 'font-semibold text-muted2 hover:text-ink'
            }`}
          >
            <Icon name="menu" size={22} className="leading-none" />
            Mehr
          </button>
        </nav>
      </div>

      {mehrOffen && (
        <Modal open onClose={() => setMehrOffen(false)} title="Mehr">
          <div className="space-y-2">
            {vorratAktiv && (
              <MehrLink icon="package" label="Vorrat" hint="Bestand verwalten" onClick={() => { setMehrOffen(false); setGruppe('vorrat') }} />
            )}
            <MehrLink icon="users" label="Haushalt" hint="Personen & Einladungen" onClick={() => { setMehrOffen(false); setGruppe('haushalt') }} />
            <MehrLink icon="shopping-cart" label="Einkaufsliste" hint="Aktueller Einkauf" badge={warenkorbAnzahl > 0 ? warenkorbAnzahl : null} onClick={() => { setMehrOffen(false); setEinkaufOffen(true) }} />
            <MehrLink icon="settings" label="Einstellungen" onClick={() => { setMehrOffen(false); setSettingsOffen(true) }} />
            {(auth?.user?.plattform_rolle === 'super_admin' || auth?.user?.plattform_rolle === 'support') && (
              <MehrLink icon="wrench" label="Admin-Bereich" hint="Backoffice & Kennzahlen" onClick={() => { setMehrOffen(false); setAdminOffen(true) }} />
            )}
          </div>
          <RechtFooter className="mt-4 border-t border-line pt-4" />
        </Modal>
      )}

      {einkaufOffen && (
        <Einkaufsliste onClose={() => setEinkaufOffen(false)} notify={notify} vorratAktiv={vorratAktiv} abhakModus={abhakModus} />
      )}

      {settingsOffen && (
        <Modal open onClose={() => setSettingsOffen(false)} title="Einstellungen">
          <div className="space-y-4">
            {auth?.user && (
              <div className="hero-card flex items-center justify-between gap-3 rounded-[22px] p-5">
                <div className="hero-glow" />
                <div className="relative min-w-0">
                  <p className="truncate font-dish text-2xl leading-tight text-ink">{auth.user.name || auth.user.email}</p>
                  <p className="label-mono mt-1.5 truncate text-muted2">
                    {auth.account?.name ? auth.account.name : 'Haushalt'}
                    {auth.user.plattform_rolle ? ` · ${auth.user.plattform_rolle}` : ''}
                  </p>
                </div>
                <button onClick={onLogout} className="relative shrink-0 rounded-full border border-line px-3 py-1.5 text-sm font-semibold text-ink/70 hover:bg-ink/5">Abmelden</button>
              </div>
            )}

            <p className="pt-2 text-xs font-bold uppercase tracking-wide text-ink/40">App</p>

            <div className="rounded-xl border border-line p-3">
              <p className="mb-2 inline-flex items-center gap-1 text-sm font-semibold"><Icon name="palette" size={18} /> Design</p>
              <div className="flex gap-2">
                {[['hell', 'Hell', 'sun'], ['dunkel', 'Dunkel', 'moon'], ['system', 'System', 'monitor']].map(([k, t, ic]) => (
                  <button key={k} onClick={() => waehleTheme(k)}
                    className={`flex-1 inline-flex items-center justify-center gap-1 rounded-lg border px-2 py-1.5 text-sm font-semibold transition ${theme === k ? 'border-terracotta bg-terracotta/10 text-terracotta-deep' : 'border-line text-ink/60 hover:text-ink'}`}>
                    <Icon name={ic} size={16} /> {t}
                  </button>
                ))}
              </div>
            </div>

            {/* Nur wo die Notification-API existiert – in der Android-App (WebView) fehlt sie. */}
            {'Notification' in window && (
              <button
                onClick={async () => {
                  if (!('Notification' in window)) { notify('Benachrichtigungen werden von diesem Browser nicht unterstützt', 'err'); return }
                  try {
                    const perm = await Notification.requestPermission()
                    if (perm === 'granted') { notify('Benachrichtigungen aktiviert'); try { new Notification('Topfplan', { body: 'Benachrichtigungen sind aktiv – z.B. für Koch-Timer.', icon: '/icon-192.png' }) } catch { /* ignore */ } }
                    else notify('Benachrichtigungen nicht erlaubt', 'err')
                  } catch { notify('Konnte Benachrichtigungen nicht aktivieren', 'err') }
                }}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-line p-3 text-left hover:bg-ink/5"
              >
                <span>
                  <span className="inline-flex items-center gap-1 font-semibold"><Icon name="bell" size={18} /> Benachrichtigungen</span>
                  <span className="mt-0.5 block text-sm text-ink/60">Erlaube Hinweise, z.B. wenn ein Koch-Timer abgelaufen ist.</span>
                </span>
                <span className="shrink-0 text-ink/40">›</span>
              </button>
            )}

            <button
              onClick={() => { setSettingsOffen(false); setOnboardingOffen(true) }}
              className="flex w-full items-center justify-between gap-3 rounded-xl border border-line p-3 text-left hover:bg-ink/5"
            >
              <span>
                <span className="inline-flex items-center gap-1 font-semibold"><Icon name="rocket" size={18} /> Einrichtung starten</span>
                <span className="mt-0.5 block text-sm text-ink/60">Personen, Geräte, Vorrat & KI-Funktionen in wenigen Schritten einrichten.</span>
              </span>
              <span className="shrink-0 text-ink/40">›</span>
            </button>
            {vorratModus !== null && (() => {
              const wahl = (vorratModus === 'light' || vorratAktiv === false) ? 'light' : 'voll'
              return (
                <div className="rounded-xl border border-line p-3">
                  <p className="mb-1 text-sm font-semibold">Vorrat</p>
                  <p className="mb-2 text-xs text-ink/55">Wähle, wie Topfplan deinen Vorrat nutzt.</p>
                  <label className="flex cursor-pointer items-start gap-2 py-1">
                    <input type="radio" name="vorratwahl" checked={wahl === 'voll'} onChange={() => waehleVorrat('voll')} className="mt-0.5 accent-terracotta" />
                    <span><span className="font-medium">Vollständige Funktion</span><br /><span className="text-xs text-ink/55">Vorrat in der App pflegen: beim Einkauf-Abhaken die gekaufte Menge erfassen &amp; übernehmen; Rezepte werden aus deinem gespeicherten Vorrat geplant.</span></span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2 py-1">
                    <input type="radio" name="vorratwahl" checked={wahl === 'light'} onChange={() => waehleVorrat('light')} className="mt-0.5 accent-terracotta" />
                    <span><span className="font-medium">Light</span><br /><span className="text-xs text-ink/55">Nichts wird gespeichert. Beim Rezept-Erstellen gibst du ein, was du verwerten willst – die Vorschläge beziehen sich darauf. Einkaufsliste ohne Mengen-Abfrage.</span></span>
                  </label>
                  {wahl === 'voll' && (
                    <div className="mt-2 border-t border-line pt-2">
                      <p className="mb-1 text-xs font-semibold text-muted">Einkaufsliste abhaken</p>
                      <label className="flex cursor-pointer items-start gap-2 py-1">
                        <input type="radio" name="abhakmodus" checked={abhakModus === 'popup'} onChange={() => waehleAbhakModus('popup')} className="mt-0.5 accent-terracotta" />
                        <span><span className="font-medium">Einzeln mit Popup</span><br /><span className="text-xs text-ink/55">Beim Abhaken fragt ein Fenster je Artikel die gekaufte Menge ab.</span></span>
                      </label>
                      <label className="flex cursor-pointer items-start gap-2 py-1">
                        <input type="radio" name="abhakmodus" checked={abhakModus === 'inline'} onChange={() => waehleAbhakModus('inline')} className="mt-0.5 accent-terracotta" />
                        <span><span className="font-medium">Mengen in der Liste + Sammel-Button</span><br /><span className="text-xs text-ink/55">Menge je Artikel direkt bearbeiten, am Ende alles auf einmal in den Vorrat übernehmen.</span></span>
                      </label>
                    </div>
                  )}
                </div>
              )
            })()}

            <p className="pt-2 text-xs font-bold uppercase tracking-wide text-ink/40">KI-Assistent</p>
            {ki.text && chatMemory !== null && (
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={chatMemory}
                  onChange={(e) => toggleChatMemory(e.target.checked)}
                  className="mt-0.5 h-5 w-5 shrink-0 accent-terracotta"
                />
                <span>
                  <span className="font-semibold">Assistent darf sich Personen-Infos merken</span>
                  <span className="mt-0.5 block text-sm text-ink/60">
                    Nennst du im Chat personenbezogene Vorlieben/Infos, speichert der Assistent sie automatisch
                    bei der Person (im Haushalt → Person einsehbar & änderbar). Aus: nur auf ausdrückliche Ansage.
                  </span>
                </span>
              </label>
            )}

            {ki.bild && autoBild !== null && (
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={autoBild}
                  onChange={(e) => toggleAutoBild(e.target.checked)}
                  className="mt-0.5 h-5 w-5 shrink-0 accent-terracotta"
                />
                <span>
                  <span className="inline-flex items-center gap-1 font-semibold"><Icon name="image" size={18} /> Rezeptbilder automatisch erzeugen</span>
                  <span className="mt-0.5 block text-sm text-ink/60">
                    Vorbelegung für neue KI-Rezepte: beim Übernehmen wird ein Bild erstellt.
                    Im Rezept-Erstellen-Dialog kannst du das für einzelne Rezepte abwählen –
                    übernommene Rezepte aus der öffentlichen Bibliothek bringen ihr Bild mit.
                  </span>
                </span>
              </label>
            )}

            {(auth?.user?.plattform_rolle === 'super_admin' || auth?.user?.plattform_rolle === 'support') && (
              <button
                onClick={() => { setSettingsOffen(false); setAdminOffen(true) }}
                className="flex w-full items-center justify-between gap-3 rounded-2xl border border-terracotta/30 bg-terracotta/[0.04] p-3 text-left hover:bg-terracotta/10"
              >
                <span className="flex items-center gap-2 text-sm font-bold text-terracotta-deep">
                  <Icon name="wrench" size={18} className="text-terracotta-deep" /> Admin-Bereich öffnen
                  <span className="rounded-full bg-terracotta/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                    {auth.user.plattform_rolle === 'super_admin' ? 'Super-Admin' : 'Support'}
                  </span>
                </span>
                <span className="shrink-0 text-terracotta/50">›</span>
              </button>
            )}

            <p className="pt-2 text-xs font-bold uppercase tracking-wide text-terracotta/70">Gefahrenzone</p>
            <button
              onClick={async () => {
                const ok = await confirmDialog({
                  title: 'Konto löschen',
                  message: 'Dein Login wird dauerhaft gelöscht. Bist du der letzte Nutzer dieses Haushalts, werden auch alle Haushalts-Daten (Rezepte, Vorrat, Plan …) unwiderruflich entfernt.\n\nFortfahren?',
                  confirmLabel: 'Konto löschen',
                })
                if (!ok) return
                try { await api.kontoLoeschen('selbst'); notify('Konto gelöscht'); onLogout() }
                catch (e) { notify(e.message || 'Löschen fehlgeschlagen', 'err') }
              }}
              className="flex w-full items-center justify-between gap-3 rounded-xl border border-terracotta/40 p-3 text-left text-terracotta-deep hover:bg-terracotta/10"
            >
              <span>
                <span className="inline-flex items-center gap-1 font-semibold"><Icon name="trash" size={18} /> Konto löschen</span>
                <span className="mt-0.5 block text-sm text-terracotta-deep/70">Entfernt deinen Login. Letzter Nutzer → ganzer Haushalt wird gelöscht.</span>
              </span>
              <span className="shrink-0 text-terracotta/50">›</span>
            </button>
            {auth?.rolle === 'owner' && (
              <button
                onClick={async () => {
                  const ok = await confirmDialog({
                    title: 'Ganzen Haushalt löschen',
                    message: 'Der GESAMTE Haushalt inkl. aller Daten (Rezepte, Vorrat, Plan, Angebote …) und aller Mitglieder wird unwiderruflich gelöscht. Das kann nicht rückgängig gemacht werden.\n\nWirklich den ganzen Haushalt löschen?',
                    confirmLabel: 'Haushalt löschen',
                  })
                  if (!ok) return
                  try { await api.kontoLoeschen('haushalt'); notify('Haushalt gelöscht'); onLogout() }
                  catch (e) { notify(e.message || 'Löschen fehlgeschlagen', 'err') }
                }}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-terracotta/40 bg-terracotta/5 p-3 text-left text-terracotta-deep hover:bg-terracotta/15"
              >
                <span>
                  <span className="inline-flex items-center gap-1 font-semibold"><Icon name="trash" size={18} /> Ganzen Haushalt löschen</span>
                  <span className="mt-0.5 block text-sm text-terracotta-deep/70">Löscht den kompletten Haushalt inkl. aller Mitglieder und Daten.</span>
                </span>
                <span className="shrink-0 text-terracotta/50">›</span>
              </button>
            )}

            <div className="flex justify-end">
              <button onClick={() => setSettingsOffen(false)} className="rounded-full bg-ink px-5 py-2 text-sm font-semibold text-paper">Fertig</button>
            </div>
          </div>
        </Modal>
      )}

      {adminOffen && (auth?.user?.plattform_rolle === 'super_admin' || auth?.user?.plattform_rolle === 'support') && (
        <AdminPanel notify={notify} rolle={auth.user.plattform_rolle} onClose={() => setAdminOffen(false)} />
      )}

      {onboardingOffen && (
        <Onboarding
          onClose={() => {
            setOnboardingOffen(false)
            try { localStorage.setItem(auth?.account?.id ? `onboarding_seen_${auth.account.id}` : 'onboarding_seen', '1') } catch { /* ignore */ }
          }}
          notify={notify}
          vorratAktiv={vorratAktiv}
          onVorratChange={toggleVorrat}
        />
      )}

      {spontan && (
        <SpontanesKochen
          onClose={() => setSpontan(false)}
          notify={notify}
          onRezeptOpen={(id) => { setSpontan(false); openRezept(id) }}
        />
      )}

      {chatOffen && ki.text && (
        <div className="fixed inset-0 z-[90] flex items-end justify-center sm:items-center sm:p-4">
          <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" onClick={() => setChatOffen(false)} />
          <div className="relative z-10 flex h-[88vh] w-full flex-col rounded-t-3xl border border-line bg-card p-4 shadow-soft sm:h-[80vh] sm:max-w-2xl sm:rounded-3xl">
            <Chat
              messages={chat.messages}
              loading={chat.loading}
              senden={chat.senden}
              leeren={chat.leeren}
              notify={notify}
              onClose={() => setChatOffen(false)}
              heightClass="h-full"
            />
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed inset-x-0 bottom-20 z-[110] flex justify-center px-4">
          <div
            className={`flex items-center gap-3 rounded-full border px-5 py-2.5 text-sm font-semibold shadow-soft ${
              toast.kind === 'err'
                ? 'border-terracotta-deep bg-terracotta text-on-accent'
                : 'border-ink bg-ink text-paper'
            }`}
          >
            <span>{toast.text}</span>
            {toast.action && (
              <button
                onClick={() => { toast.action.onClick(); setToast(null) }}
                className="shrink-0 rounded-full bg-paper/20 px-3 py-1 text-xs font-bold underline"
              >
                {toast.action.label}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Rezept-Detail als Overlay über dem aktuellen Tab (z.B. aus der Startübersicht) –
          öffnet das Rezept OHNE Tab-Wechsel; "Zurück" landet wieder auf der Startseite. */}
      <Rezepte
        detailOnly
        notify={notify}
        openRezeptId={openRezeptId}
        angebotMarkt={angebotMarkt}
        clearOpen={() => { setOpenRezeptId(null); setAngebotMarkt(null) }}
        onDetailClose={() => { setOpenRezeptId(null); setAngebotMarkt(null) }}
        defaultPortionen={2}
        auth={auth}
      />

      <ConfirmHost />
      <BugReport notify={notify} seite={gruppe} />
    </div>
  )
}
