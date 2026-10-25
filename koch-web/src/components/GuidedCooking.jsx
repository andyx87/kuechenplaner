import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api.js'
import { getVorratAktiv, SPRACHSTEUERUNG_MOEGLICH } from '../settings.js'
import { useKi } from '../kiStatus.js'
import { registerOverlay } from '../backnav.js'
import { Icon } from '../icons.jsx'

const fmt = (m) => { const n = Number(m); return Number.isInteger(n) ? n : Math.round(n * 100) / 100 }
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.max(0, s % 60)).padStart(2, '0')}`

// Geräte-Verfügbarkeit wie in ZubereitungAnsicht (für die Default-Variantenwahl).
function geraetVerfuegbar(geraetName, heuteNamen) {
  if (!geraetName) return true
  const gn = geraetName.toLowerCase()
  return [...(heuteNamen || [])].some((hn) => gn.includes(hn.toLowerCase()) || hn.toLowerCase().includes(gn))
}

// Ohne Text-KI (oder wenn die KI-Aufbereitung scheitert): Schritte direkt aus dem Rezept
// bilden – je Zeile der gewählten Variante ein Schritt, „x Min." ergibt einen Timer.
function lokaleSchritte(detail, varianten) {
  const schritte = []
  const ausText = (text, komponente) => {
    String(text || '').replace(/\\n/g, '\n').split(/\n+/)
      .map((z) => z.replace(/^\s*(\d+[.)]|[-•*])\s*/, '').trim())
      .filter(Boolean)
      .forEach((t) => {
        const m = t.match(/(\d+)\s*(?:-\s*\d+\s*)?(?:Min\b|Min\.|Minuten)/i)
        schritte.push({ text: t, komponente: komponente || null, ...(m ? { timer: true, dauer_minuten: Number(m[1]) } : {}) })
      })
  }
  const komps = detail?.zubereitung || []
  if (komps.length) {
    komps.forEach((k, i) => {
      const vs = k.varianten || []
      const v = vs[(varianten && varianten[i]) || 0] || vs[0]
      ausText(v?.text, k.titel)
    })
  } else {
    ausText(detail?.anleitung, null)
  }
  return schritte.length ? { schritte, portionen: detail?.portionen || null } : false
}

// Buntes Konfetti zum Abschluss (reines CSS, einmalig zufällig erzeugt).
function Konfetti() {
  const stuecke = useMemo(() => {
    const farben = ['var(--terracotta)', 'var(--butter)', 'var(--olive)', 'var(--akzent)', 'var(--terracotta-deep)']
    return Array.from({ length: 70 }, (_, i) => ({
      left: Math.random() * 100,
      dx: `${(Math.random() - 0.5) * 220}px`,
      delay: Math.random() * 0.5,
      dur: 2.4 + Math.random() * 1.8,
      farbe: farben[i % farben.length],
      rund: Math.random() > 0.6,
    }))
  }, [])
  return (
    <div className="gc-confetti pointer-events-none absolute inset-0 z-10 overflow-hidden" aria-hidden="true">
      {stuecke.map((s, i) => (
        <i key={i} style={{
          left: `${s.left}%`, background: s.farbe,
          animationDuration: `${s.dur}s`, animationDelay: `${s.delay}s`,
          borderRadius: s.rund ? '9999px' : '2px', '--dx': s.dx,
        }} />
      ))}
    </div>
  )
}

// Vollbild-Kochmodus: KI-strukturierte Schritte, Timer, Wake-Lock, Vorlesen,
// Sprachbefehle und KI-Assistent. Mengen werden auf die Zielportionen skaliert.
export default function GuidedCooking({ detail, portionen, heuteNamen, onClose, notify }) {
  const ki = useKi()
  const vorratAktiv = getVorratAktiv()

  // Geräte, für die das Rezept Varianten anbietet (sonst ist eine Wahl sinnlos).
  const geraeteOptionen = useMemo(() => {
    const s = new Set()
    for (const k of (detail?.zubereitung || [])) for (const v of (k.varianten || [])) if (v.geraet) s.add(v.geraet)
    return [...s]
  }, [detail])
  const brauchtSetup = geraeteOptionen.length > 0

  // Geräte-Auswahl: null = noch nicht bestätigt (zeigt das Setup), sonst Set gewählter Gerätenamen.
  const [chosen, setChosen] = useState(null)
  const [startSel, setStartSel] = useState(null)  // vorläufige Auswahl im Setup

  // Vorbelegen bzw. automatisch bestätigen, wenn es nichts zu wählen gibt.
  useEffect(() => {
    if (!detail?.id) return
    if (!brauchtSetup) { setChosen(new Set(heuteNamen || [])); return }
    const pre = new Set(geraeteOptionen.filter((g) => geraetVerfuegbar(g, heuteNamen)))
    setStartSel(pre.size ? pre : new Set(geraeteOptionen))
  }, [detail?.id, brauchtSetup])  // eslint-disable-line react-hooks/exhaustive-deps

  const varianten = useMemo(() => {
    if (chosen === null) return null
    return (detail?.zubereitung || []).map((k) => {
      const i = (k.varianten || []).findIndex((v) => !v.geraet || geraetVerfuegbar(v.geraet, chosen))
      return i >= 0 ? i : 0
    })
  }, [detail, chosen])

  const [daten, setDaten] = useState(null)   // null=lädt, false=Fehler, sonst {schritte, portionen}
  const [idx, setIdx] = useState(0)
  const [dir, setDir] = useState('next')     // Richtung des letzten Wechsels (Übergangs-Animation)
  const [vorlesen, setVorlesen] = useState(false)
  const [hoeren, setHoeren] = useState(false)
  const [timers, setTimers] = useState([])   // [{id,label,endTs,total}]
  const [, setTick] = useState(0)            // erzwingt Re-Render fürs Countdown
  const [frageOffen, setFrageOffen] = useState(false)
  const [frage, setFrage] = useState('')
  const [antwort, setAntwort] = useState('')
  const [frageBusy, setFrageBusy] = useState(false)
  const [fertig, setFertig] = useState(false)
  const [sterne, setSterne] = useState(0)

  const wakeRef = useRef(null)
  const recogRef = useRef(null)
  const audioRef = useRef(null)

  // Schritte laden (KI-strukturiert, gecacht) – erst nach bestätigter Geräte-Auswahl.
  // Ohne Text-KI bzw. bei Fehlern: Schritte lokal aus dem Rezepttext.
  useEffect(() => {
    if (!detail?.id || varianten === null || !ki.geladen) return
    if (!ki.text) { setDaten(lokaleSchritte(detail, varianten)); return }
    setDaten(null)
    api.guidedHolen(detail.id, varianten)
      .then((d) => setDaten(d && Array.isArray(d.schritte) && d.schritte.length ? d : lokaleSchritte(detail, varianten)))
      .catch(() => setDaten(lokaleSchritte(detail, varianten)))
  }, [detail?.id, chosen, ki.geladen, ki.text])  // eslint-disable-line react-hooks/exhaustive-deps

  // Geräte-/Browser-Zurück schließt den Kochmodus (statt die Rubrik zu wechseln).
  useEffect(() => {
    const unregister = registerOverlay(() => onClose?.())
    return () => unregister()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Bildschirm wach halten.
  useEffect(() => {
    let aktiv = true
    const anfordern = async () => {
      try { if (aktiv && 'wakeLock' in navigator) wakeRef.current = await navigator.wakeLock.request('screen') } catch { /* ignore */ }
    }
    anfordern()
    const onVis = () => { if (document.visibilityState === 'visible') anfordern() }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      aktiv = false
      document.removeEventListener('visibilitychange', onVis)
      try { wakeRef.current?.release?.() } catch { /* ignore */ }
      try { window.speechSynthesis?.cancel() } catch { /* ignore */ }
      try { recogRef.current?.stop?.() } catch { /* ignore */ }
    }
  }, [])

  // Countdown-Ticker.
  useEffect(() => {
    if (!timers.length) return
    const iv = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(iv)
  }, [timers.length])

  // Abgelaufene Timer melden (Ton + Vibration) und entfernen.
  useEffect(() => {
    const jetzt = Date.now()
    const faellig = timers.filter((t) => t.endTs <= jetzt)
    if (!faellig.length) return
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      if (AC) {
        const ctx = audioRef.current || (audioRef.current = new AC())
        const o = ctx.createOscillator(); const g = ctx.createGain()
        o.connect(g); g.connect(ctx.destination); o.frequency.value = 880
        o.start(); g.gain.setValueAtTime(0.2, ctx.currentTime)
        o.stop(ctx.currentTime + 0.6)
      }
    } catch { /* ignore */ }
    try { navigator.vibrate?.([300, 150, 300]) } catch { /* ignore */ }
    try {
      if (window.Notification && Notification.permission === 'granted') {
        new Notification('Timer abgelaufen', { body: faellig.map((t) => t.label).join(', '), icon: '/icon-192.png' })
      }
    } catch { /* ignore */ }
    notify?.(`Timer abgelaufen: ${faellig.map((t) => t.label).join(', ')}`)
    setTimers((ts) => ts.filter((t) => t.endTs > jetzt))
  })  // läuft bei jedem Tick

  const schritte = daten && daten.schritte ? daten.schritte : []
  const basis = (daten && daten.portionen) || detail?.portionen || 1
  const faktor = basis ? (portionen || basis) / basis : 1
  const schritt = schritte[idx]
  const fortschritt = schritte.length ? Math.round(((fertig ? schritte.length : idx + 1) / schritte.length) * 100) : 0

  // Aktuellen Schritt vorlesen, wenn aktiviert.
  useEffect(() => {
    if (!vorlesen || !schritt || fertig) return
    try {
      window.speechSynthesis?.cancel()
      const u = new SpeechSynthesisUtterance(schritt.text)
      u.lang = 'de-DE'
      window.speechSynthesis?.speak(u)
    } catch { /* ignore */ }
  }, [idx, vorlesen, fertig])  // eslint-disable-line react-hooks/exhaustive-deps

  function weiter() {
    setDir('next')
    setIdx((i) => { if (i >= schritte.length - 1) { setFertig(true); return i } return i + 1 })
  }
  function zurueck() { setDir('prev'); setFertig(false); setIdx((i) => Math.max(0, i - 1)) }

  function timerStarten(s) {
    if (!s?.dauer_minuten) return
    const id = `${s.nr}-${Date.now()}`
    setTimers((ts) => [...ts, { id, label: `Schritt ${s.nr}`, endTs: Date.now() + s.dauer_minuten * 60000, total: s.dauer_minuten * 60 }])
    notify?.(`Timer gestartet: ${s.dauer_minuten} Min`)
  }

  // Sprachbefehle.
  function toggleHoeren() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { notify?.('Spracherkennung wird von diesem Browser nicht unterstützt', 'err'); return }
    if (hoeren) { try { recogRef.current?.stop?.() } catch { /* ignore */ } setHoeren(false); return }
    const r = new SR()
    r.lang = 'de-DE'; r.continuous = true; r.interimResults = false
    r.onresult = (e) => {
      const txt = (e.results[e.results.length - 1][0].transcript || '').toLowerCase()
      if (/(weiter|nächste|naechste|fertig)/.test(txt)) weiter()
      else if (/(zurück|zurueck|vorherige)/.test(txt)) zurueck()
      else if (/(wiederhol|nochmal|noch mal)/.test(txt)) { if (vorlesen && schritt) { try { window.speechSynthesis?.cancel(); const u = new SpeechSynthesisUtterance(schritt.text); u.lang = 'de-DE'; window.speechSynthesis?.speak(u) } catch { /* ignore */ } } }
      else if (/(timer|wecker)/.test(txt)) timerStarten(schritt)
    }
    r.onend = () => { if (recogRef.current === r && r._aktiv) { try { r.start() } catch { /* ignore */ } } }
    r._aktiv = true
    recogRef.current = r
    try { r.start(); setHoeren(true); notify?.('Sprachsteuerung an: „weiter", „zurück", „wiederholen", „Timer"') }
    catch { setHoeren(false) }
  }
  useEffect(() => () => { if (recogRef.current) { recogRef.current._aktiv = false; try { recogRef.current.stop() } catch { /* ignore */ } } }, [])

  async function frageSenden() {
    const f = frage.trim()
    if (!f) return
    setFrageBusy(true); setAntwort('')
    try {
      const r = await api.guidedFrage(detail.id, schritt?.text || '', f)
      setAntwort(r.antwort || '—')
    } catch (e) { notify?.(e.message || 'Frage fehlgeschlagen', 'err') }
    finally { setFrageBusy(false) }
  }

  async function abschliessen({ verbuchen }) {
    try {
      if (verbuchen) { await api.kochenBestaetigen(detail.id, faktor); notify?.('Vorrat verbucht') }
      if (sterne > 0) { await api.rezeptBewertungSetzen(detail.id, sterne) }
    } catch (e) { notify?.(e.message || 'Speichern fehlgeschlagen', 'err') }
    onClose?.()
  }

  // Swipe-Navigation.
  const touch = useRef(null)
  const onTouchStart = (e) => { touch.current = e.touches[0].clientX }
  const onTouchEnd = (e) => {
    if (touch.current == null) return
    const dx = e.changedTouches[0].clientX - touch.current
    if (dx < -50) weiter(); else if (dx > 50) zurueck()
    touch.current = null
  }

  const istLetzter = idx >= schritte.length - 1
  const iconBtn = 'rounded-full p-2 transition active:scale-90'

  return createPortal((
    <div className="gc-bg fixed inset-0 z-[120] flex flex-col pt-[env(safe-area-inset-top,0px)] text-ink">
      {chosen === null && brauchtSetup ? (
        <>
          {/* Geräte-Setup vor dem Kochen */}
          <div className="flex items-center gap-2 px-4 pb-2 pt-3">
            <button onClick={onClose} aria-label="Schließen" className={`${iconBtn} text-ink/60 hover:bg-ink/5`}><Icon name="x" size={18} /></button>
            <p className="truncate font-display text-sm font-semibold">{detail?.name}</p>
          </div>
          <div className="relative flex-1 overflow-y-auto px-5">
            <div className="grid min-h-full place-items-center">
              <div className="gc-stagger flex max-w-md flex-col items-center gap-5 py-8 text-center">
                <div className="gc-glow gc-float grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-terracotta to-terracotta-deep text-on-accent shadow-soft"><Icon name="wrench" size={28} /></div>
                <div>
                  <p className="font-dish text-3xl text-ink">Womit kochst du?</p>
                  <p className="mt-1 text-sm text-muted">Wähle deine Geräte – die Schritte passen sich daran an.</p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {geraeteOptionen.map((g) => {
                    const on = !!startSel?.has(g)
                    return (
                      <button key={g} onClick={() => setStartSel((s) => { const n = new Set(s); n.has(g) ? n.delete(g) : n.add(g); return n })}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-semibold transition active:scale-95 ${on ? 'border-olive/40 bg-olive/15 text-olive' : 'border-line text-muted'}`}>
                        <Icon name={on ? 'check' : 'wrench'} size={16} /> {g}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 border-t border-line bg-card/80 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
            <button onClick={() => setChosen(new Set(startSel || []))}
              className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-terracotta to-terracotta-deep px-4 py-3.5 text-sm font-bold text-on-accent shadow-soft transition active:scale-[0.98]">
              Loskochen <Icon name="arrow-right" size={18} />
            </button>
          </div>
        </>
      ) : (
      <>
      {/* Kopf */}
      <div className="flex items-center gap-2 px-4 pb-2 pt-3">
        <button onClick={onClose} aria-label="Schließen" className={`${iconBtn} text-ink/60 hover:bg-ink/5`}><Icon name="x" size={18} /></button>
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-sm font-semibold">{detail?.name}</p>
          {!fertig && schritte.length > 0 && <p className="font-mono text-xs text-muted2">Schritt {idx + 1} von {schritte.length}</p>}
        </div>
        {/* Vorlesen nur, wo es SpeechSynthesis gibt – die Android-WebView hat sie nicht. */}
        {'speechSynthesis' in window && (
          <button onClick={() => setVorlesen((v) => { if (v) try { window.speechSynthesis?.cancel() } catch { /* ignore */ } ; return !v })}
            title="Vorlesen" aria-label="Vorlesen"
            className={`${iconBtn} ${vorlesen ? 'bg-terracotta text-on-accent shadow-glow' : 'border border-line text-muted'}`}><Icon name="volume" size={17} /></button>
        )}
        {SPRACHSTEUERUNG_MOEGLICH && (
          <button onClick={toggleHoeren} title="Sprachsteuerung" aria-label="Sprachsteuerung"
            className={`${iconBtn} ${hoeren ? 'gc-ring bg-terracotta text-on-accent' : 'border border-line text-muted'}`}><Icon name="mic" size={17} /></button>
        )}
      </div>

      {/* Fortschrittsbalken */}
      {schritte.length > 0 && (
        <div className="px-4 pb-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink/10">
            <div className="gc-progress h-full rounded-full" style={{ width: `${fortschritt}%` }} />
          </div>
        </div>
      )}

      {/* Timer-Leiste */}
      {timers.length > 0 && (
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {timers.map((t) => {
            const rem = Math.max(0, Math.round((t.endTs - Date.now()) / 1000))
            const pct = t.total ? Math.max(0, Math.min(100, (rem / t.total) * 100)) : 0
            const knapp = rem <= 10
            return (
              <span key={t.id} className={`relative flex items-center gap-2 overflow-hidden rounded-full bg-card px-3 py-1.5 text-sm font-semibold shadow-soft ${knapp ? 'gc-ring' : ''}`}>
                <Icon name="timer" size={16} className="text-terracotta" />
                <span className="font-mono tabular-nums">{t.label}: {mmss(rem)}</span>
                <button onClick={() => setTimers((ts) => ts.filter((x) => x.id !== t.id))} className="text-muted2 transition hover:text-terracotta active:scale-90"><Icon name="x" size={15} /></button>
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-terracotta transition-[width] duration-1000 ease-linear" style={{ width: `${pct}%` }} />
              </span>
            )
          })}
        </div>
      )}

      {/* Inhalt */}
      <div className="relative flex-1 overflow-y-auto px-5" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        {daten === null ? (
          <div className="flex h-full flex-col items-center justify-center gap-5 text-ink/60">
            <div className="relative">
              <div className="gc-steam absolute -top-4 left-1/2 flex -translate-x-1/2 gap-1.5">
                <span className="block h-4 w-1 rounded-full bg-ink/25" style={{ animationDelay: '0s' }} />
                <span className="block h-5 w-1 rounded-full bg-ink/25" style={{ animationDelay: '.5s' }} />
                <span className="block h-4 w-1 rounded-full bg-ink/25" style={{ animationDelay: '1s' }} />
              </div>
              <div className="grid h-20 w-20 place-items-center rounded-3xl border border-line bg-card shadow-soft">
                <Icon name="chef-hat" size={36} className="text-terracotta" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="gc-dot h-2 w-2 rounded-full bg-terracotta" style={{ animationDelay: '0s' }} />
              <span className="gc-dot h-2 w-2 rounded-full bg-terracotta" style={{ animationDelay: '.15s' }} />
              <span className="gc-dot h-2 w-2 rounded-full bg-olive" style={{ animationDelay: '.3s' }} />
            </div>
            <p className="font-display text-sm">Deine Schritte werden vorbereitet …</p>
          </div>
        ) : daten === false ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-ink/60">
            <Icon name="alert-triangle" size={28} className="text-terracotta" />
            <p>Die Schritt-für-Schritt-Anleitung konnte nicht erstellt werden.</p>
            <button onClick={onClose} className="rounded-full bg-ink px-5 py-2 text-sm font-semibold text-paper transition active:scale-95">Schließen</button>
          </div>
        ) : fertig ? (
          <>
            <Konfetti />
            <div className="relative z-20 mx-auto flex max-w-md flex-col items-center gap-5 py-8 text-center">
              <div className="gc-pop grid h-24 w-24 place-items-center rounded-full bg-gradient-to-br from-olive to-akzent text-on-accent shadow-soft">
                <Icon name="party-popper" size={44} />
              </div>
              <p className="gc-pop font-dish text-5xl text-ink" style={{ animationDelay: '.1s' }}>Guten Appetit!</p>
              <p className="text-muted">Wie war’s? (optional)</p>
              <div className="flex gap-1.5 text-4xl">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} onClick={() => setSterne(n)} aria-label={`${n} Sterne`}
                    className={`transition active:scale-90 ${n <= sterne ? 'gc-starpop' : ''}`}
                    style={{ color: n <= sterne ? 'var(--butter)' : 'var(--line)' }}>
                    <Icon name="star" size={34} fill="currentColor" />
                  </button>
                ))}
              </div>
              <div className="flex w-full flex-col gap-2">
                {vorratAktiv && (
                  <button onClick={() => abschliessen({ verbuchen: true })} className="w-full rounded-2xl bg-olive px-4 py-3.5 font-semibold text-on-accent shadow-soft transition active:scale-95">Fertig &amp; Vorrat verbuchen</button>
                )}
                <button onClick={() => abschliessen({ verbuchen: false })} className="w-full rounded-2xl border border-line px-4 py-3.5 font-semibold text-muted transition active:scale-95">{vorratAktiv ? 'Nur schließen' : 'Fertig'}</button>
              </div>
            </div>
          </>
        ) : schritt ? (
          <div key={idx} className="relative grid min-h-full place-items-center">
            {/* Riesige Schrittnummer als lebendiger Deko-Hintergrund */}
            <span aria-hidden="true" className="gc-ghost pointer-events-none absolute inset-0 flex select-none items-center justify-center font-display font-bold leading-none"
              style={{ color: 'var(--ink)', opacity: 0.06, fontSize: 'min(48vh, 72vw)' }}>{idx + 1}</span>

            <div className={`gc-stagger gc-${dir} relative z-10 flex max-w-2xl flex-col items-center px-1 py-6 text-center`}>
              <span className="gc-glow gc-float grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-terracotta to-terracotta-deep font-display text-2xl font-extrabold text-on-accent shadow-glow">{idx + 1}</span>

              <span className="label-mono mt-4 text-terracotta">
                {schritt.komponente || `Schritt ${idx + 1}`}
              </span>

              <p className="mt-5 whitespace-pre-wrap font-dish text-3xl leading-snug sm:text-4xl">{schritt.text}</p>

              {(schritt.zutaten?.length > 0 || schritt.geraete?.length > 0) && (
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {schritt.zutaten?.map((z, i) => (
                    <span key={'z' + i} className="inline-flex items-center gap-1.5 rounded-full bg-olive/10 px-3 py-1.5 text-sm font-medium text-olive">
                      <Icon name="carrot" size={14} />
                      {z.name}{z.menge != null ? ` · ${fmt(z.menge * faktor)} ${z.einheit || ''}`.trimEnd() : ''}
                    </span>
                  ))}
                  {schritt.geraete?.map((g, i) => (
                    <span key={'g' + i} className="inline-flex items-center gap-1.5 rounded-full bg-terracotta/12 px-3 py-1.5 text-sm font-medium text-terracotta"><Icon name="wrench" size={14} /> {g}</span>
                  ))}
                </div>
              )}

              {schritt.timer && schritt.dauer_minuten ? (
                <button onClick={() => timerStarten(schritt)} className="mt-7 inline-flex items-center gap-2 rounded-2xl border border-terracotta/50 bg-terracotta/10 px-5 py-3 text-sm font-semibold text-terracotta transition hover:bg-terracotta/15 active:scale-95">
                  <Icon name="timer" size={18} /> Timer starten · <span className="font-mono">{schritt.dauer_minuten} Min</span>
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      {/* KI-Assistent */}
      {frageOffen && ki.text && (
        <div className="border-t border-line bg-card/95 px-4 py-3 backdrop-blur">
          {(antwort || frageBusy) && (
            <p className={`mb-2 rounded-2xl bg-terracotta/10 p-3 text-sm text-ink/80 ${frageBusy ? 'gc-pulse' : ''}`}>
              {frageBusy ? 'Topfplan denkt nach …' : antwort}
            </p>
          )}
          <div className="flex gap-2">
            <input value={frage} onChange={(e) => setFrage(e.target.value)} placeholder="Frage zum Schritt …"
              onKeyDown={(e) => { if (e.key === 'Enter') frageSenden() }}
              className="flex-1 rounded-xl border border-line bg-paper/60 px-3 py-2 text-sm outline-none focus:border-terracotta" />
            <button onClick={frageSenden} disabled={frageBusy} className="rounded-xl bg-terracotta px-4 py-2 text-sm font-semibold text-on-accent transition active:scale-95 disabled:opacity-50">
              {frageBusy ? '…' : 'Fragen'}
            </button>
          </div>
        </div>
      )}

      {/* Fußzeile */}
      {!fertig && schritte.length > 0 && (
        <div className="flex items-center gap-2 border-t border-line bg-card/80 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
          <button onClick={zurueck} disabled={idx === 0} className="rounded-2xl border border-line px-4 py-3.5 text-sm font-semibold text-muted transition active:scale-95 disabled:opacity-40">Zurück</button>
          {ki.text && <button onClick={() => { setFrageOffen((o) => !o); setAntwort('') }} aria-label="Frage stellen"
            className={`rounded-2xl border border-terracotta/50 px-3.5 py-3.5 text-sm font-semibold text-terracotta transition active:scale-95 ${frageOffen ? 'bg-terracotta/10' : ''}`}><Icon name="sparkles" size={18} /></button>}
          <button onClick={weiter} className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-terracotta to-terracotta-deep px-4 py-3.5 text-sm font-bold text-on-accent shadow-soft transition active:scale-[0.98]">
            {istLetzter ? <>Fertig <Icon name="check" size={18} /></> : <>Weiter <Icon name="arrow-right" size={18} /></>}
          </button>
        </div>
      )}
      </>
      )}
    </div>
  ), document.body)
}
