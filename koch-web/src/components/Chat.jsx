import { useState, useRef, useEffect } from 'react'
import { Button, Spinner, input } from '../ui.jsx'
import { api } from '../api.js'
import { SPRACHE_AKTIV } from '../settings.js'
import { Icon } from '../icons.jsx'

const BEISPIELE = [
  'Was kann ich heute kochen?',
  'Was habe ich im Vorrat?',
  'Was steht diese Woche auf dem Plan?',
  'Was fehlt für die Thunfisch-Pasta?',
]

function fileToBase64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader()
    r.onload = () => res(String(r.result).split(',')[1])
    r.onerror = rej
    r.readAsDataURL(file)
  })
}

const istPdf = (a) =>
  a.media_type === 'application/pdf' || (a.name || '').toLowerCase().endsWith('.pdf')

function Anhang({ a, klein }) {
  const size = klein ? 'h-16 w-16' : 'h-20 w-20'
  if (istPdf(a)) {
    return (
      <div className={`flex ${size} flex-col items-center justify-center gap-1 rounded-lg border border-line bg-card2 p-1 text-center`}>
        <Icon name="file-text" size={18} />
        <span className="line-clamp-2 text-[10px] leading-tight text-muted">{a.name || 'PDF'}</span>
      </div>
    )
  }
  return <img src={`data:${a.media_type};base64,${a.data}`} alt="" className={`${size} rounded-lg object-cover`} />
}

function Bubble({ m }) {
  const user = m.role === 'user'
  return (
    <div className={`flex ${user ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
        user
          ? 'bg-terracotta text-on-accent rounded-br-md'
          : 'border border-line bg-card2 text-ink rounded-bl-md'
      }`}>
        {m.anhaenge && m.anhaenge.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1.5">
            {m.anhaenge.map((a, i) => <Anhang key={i} a={a} klein />)}
          </div>
        )}
        {m.content && <div className="whitespace-pre-wrap break-words">{m.content}</div>}
        {!user && m.tools && m.tools.length > 0 && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted2">
            <span className="inline-flex items-center gap-1"><Icon name="wrench" size={14} /> {m.tools.join(', ')}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// Präsentations-Komponente: Verlauf/Senden/Status kommen aus dem useChat-Hook (App-Ebene),
// damit eine laufende Anfrage das Schließen des Fensters überlebt.
export default function Chat({ messages, loading, senden, leeren, notify, onClose, heightClass = 'h-[72vh]' }) {
  const [text, setText] = useState('')
  const [anhaenge, setAnhaenge] = useState([]) // [{data, media_type, name}]
  const endRef = useRef(null)
  const fileRef = useRef(null)
  const textareaRef = useRef(null)
  const recRef = useRef(null)
  const [recording, setRecording] = useState(false)
  const [transkribiert, setTranskribiert] = useState(false)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 192) + 'px'
  }, [text])

  async function dateiWaehlen(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    for (const f of files) {
      try {
        const data = await fileToBase64(f)
        setAnhaenge((a) => [...a, { data, media_type: f.type || 'application/octet-stream', name: f.name }])
      } catch {
        notify?.('Datei konnte nicht gelesen werden', 'err')
      }
    }
  }

  const anhangEntfernen = (i) => setAnhaenge((a) => a.filter((_, j) => j !== i))

  // Spracheingabe: Audio aufnehmen -> Backend (Gemini) transkribiert -> Text einfuegen.
  async function toggleSpracheingabe() {
    if (recRef.current) { recRef.current.stop(); return }   // laufende Aufnahme stoppen
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      notify?.('Audioaufnahme wird von diesem Browser nicht unterstützt.', 'err'); return
    }
    let stream
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
    catch { notify?.('Kein Mikrofon-Zugriff.', 'err'); return }
    const mr = new MediaRecorder(stream)
    const chunks = []
    mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data) }
    mr.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      recRef.current = null; setRecording(false)
      const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' })
      if (!blob.size) return
      setTranskribiert(true)
      try {
        const res = await api.transkribiere(blob)
        const t = (res?.text || '').trim()
        if (t) setText((cur) => (cur ? cur.trim() + ' ' : '') + t)
        else notify?.('Es wurde nichts erkannt.', 'err')
      } catch { notify?.('Transkription fehlgeschlagen.', 'err') }
      finally { setTranskribiert(false) }
    }
    recRef.current = mr
    setRecording(true)
    mr.start()
  }

  function abschicken(vorgabe) {
    const frage = (vorgabe ?? text)
    if ((!frage.trim() && anhaenge.length === 0) || loading) return
    senden(frage, anhaenge)
    setText('')
    setAnhaenge([])
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      abschicken()
    }
  }

  return (
    <div className={`flex ${heightClass} flex-col`}>
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-display text-2xl">Assistent</h2>
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button onClick={leeren} className="text-xs text-muted hover:text-ink">
              Verlauf leeren
            </button>
          )}
          {onClose && (
            <button onClick={onClose} aria-label="Schließen" className="rounded-full p-1 text-muted hover:bg-ink/5"><Icon name="x" size={16} /></button>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-2xl border border-line bg-card/40 p-3">
        {messages.length === 0 && !loading && (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
            <p className="text-muted">
              Frag mich nach Vorrat, Wochenplan oder Rezepten – oder häng Fotos an,
              um Vorräte, Rezepte oder Angebote zu erfassen. Für Angebote am besten den
              Prospekt als PDF oder mehrere Fotos/Screenshots anhängen.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {BEISPIELE.map((b) => (
                <button
                  key={b}
                  onClick={() => abschicken(b)}
                  className="rounded-full border border-line bg-card px-3 py-1.5 text-xs text-ink/80 transition hover:border-terracotta/50"
                >
                  {b}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => <Bubble key={i} m={m} />)}

        {loading && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-line bg-card2 px-3.5 py-2.5 text-sm text-muted">
              <Spinner /> denkt nach…
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {anhaenge.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {anhaenge.map((a, i) => (
            <div key={i} className="relative">
              <Anhang a={a} />
              <button
                onClick={() => anhangEntfernen(i)}
                className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink text-xs text-paper"
                aria-label="Entfernen"
              ><Icon name="x" size={14} /></button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-end gap-2">
        <input ref={fileRef} type="file" accept="image/*,application/pdf" multiple className="hidden" onChange={dateiWaehlen} />
        <button
          onClick={() => fileRef.current?.click()}
          className="shrink-0 rounded-full border border-line bg-card px-3 py-2 text-lg hover:border-terracotta/50"
          aria-label="Fotos, Screenshots oder PDF anhängen (mehrere möglich)"
          title="Fotos, Screenshots oder PDF anhängen (mehrere möglich)"
        ><Icon name="paperclip" size={18} /></button>
        {SPRACHE_AKTIV && (
          <button
            onClick={toggleSpracheingabe}
            disabled={transkribiert}
            className={`shrink-0 rounded-full border px-3 py-2 text-lg transition disabled:opacity-60 ${recording ? 'animate-pulse border-terracotta bg-terracotta/15 text-terracotta' : 'border-line bg-card hover:border-terracotta/50'}`}
            aria-label="Spracheingabe"
            title={recording ? 'Aufnahme stoppen' : 'Spracheingabe (Mikrofon)'}
          >{transkribiert ? <Spinner /> : <Icon name="mic" size={18} />}</button>
        )}
        <textarea
          ref={textareaRef}
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Nachricht…  (Enter sendet, Shift+Enter neue Zeile)"
          className={input + ' max-h-48 min-h-[4.5rem] resize-none leading-relaxed'}
        />
        <Button variant="ki" onClick={() => abschicken()} disabled={loading || (!text.trim() && anhaenge.length === 0)}>
          Senden
        </Button>
      </div>
    </div>
  )
}
