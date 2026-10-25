import { useState, useEffect, useCallback } from 'react'
import { api } from './api.js'

// Chat-Zustand auf App-Ebene: läuft weiter, auch wenn das Chat-Fenster zu ist.
// Die laufende Anfrage wird serverseitig als Job ausgeführt und hier gepollt.

const STORAGE_KEY = 'koch-chat-v1'
const JOB_KEY = 'koch-chat-job'
const TTL_MS = 60 * 60 * 1000 // 60 Min Inaktivität
const MAX_MSGS = 25

const persistierbar = (msgs) => msgs.slice(-MAX_MSGS).map(({ role, content, tools }) => ({ role, content, tools }))

function ladeVerlauf() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const { messages, ts } = JSON.parse(raw)
    if (!ts || Date.now() - ts > TTL_MS) { localStorage.removeItem(STORAGE_KEY); return [] }
    return Array.isArray(messages) ? messages : []
  } catch { return [] }
}

// Laufenden Job über Reloads hinweg merken (Tab schließen/neu laden).
function ladeJob() {
  try {
    const raw = localStorage.getItem(JOB_KEY)
    if (!raw) return null
    const { id, ts } = JSON.parse(raw)
    if (!id || !ts || Date.now() - ts > 10 * 60 * 1000) { localStorage.removeItem(JOB_KEY); return null }
    return { id }
  } catch { return null }
}

export function useChat(notify) {
  const [messages, setMessages] = useState(ladeVerlauf)
  const [job, setJob] = useState(ladeJob)
  const loading = !!job

  // Verlauf + Job persistieren
  useEffect(() => {
    try {
      if (messages.length === 0) localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, JSON.stringify({ messages: persistierbar(messages), ts: Date.now() }))
    } catch { /* ignore */ }
  }, [messages])

  useEffect(() => {
    try {
      if (job) localStorage.setItem(JOB_KEY, JSON.stringify({ id: job.id, ts: Date.now() }))
      else localStorage.removeItem(JOB_KEY)
    } catch { /* ignore */ }
  }, [job])

  // Auto-Löschung des Verlaufs nach Inaktivität
  useEffect(() => {
    if (messages.length === 0 || job) return
    const t = setTimeout(() => setMessages([]), TTL_MS)
    return () => clearTimeout(t)
  }, [messages, job])

  // Laufenden Job pollen (auch bei geschlossenem Fenster)
  useEffect(() => {
    if (!job) return
    let cancel = false
    let busy = false   // F18: verhindert überlappende Polls (Antwort sonst evtl. doppelt)
    let done = false   // F18: terminaler Status wird genau einmal verarbeitet
    const iv = setInterval(async () => {
      if (cancel || done || busy) return
      busy = true
      try {
        const s = await api.chatStatus(job.id)
        if (cancel || done) return
        if (s.status === 'fertig') {
          done = true
          setMessages((m) => [...m, { role: 'assistant', content: s.antwort || '(keine Antwort)', tools: s.tools_genutzt || [] }])
          setJob(null)
        } else if (s.status === 'fehler') {
          done = true
          setMessages((m) => [...m, { role: 'assistant', content: 'Fehler: ' + (s.error || ''), tools: [] }])
          setJob(null)
        }
      } catch {
        if (cancel || done) return
        // Job weg (Server-Neustart o.ä.) → Polling beenden
        done = true
        setMessages((m) => [...m, { role: 'assistant', content: 'Die Anfrage ist verloren gegangen (evtl. Server-Neustart). Bitte erneut senden.', tools: [] }])
        setJob(null)
      } finally {
        busy = false
      }
    }, 1500)
    return () => { cancel = true; clearInterval(iv) }
  }, [job])

  const senden = useCallback(async (frage, anhaenge = []) => {
    const f = (frage || '').trim()
    if ((!f && anhaenge.length === 0) || job) return
    const userMsg = {
      role: 'user',
      content: f,
      anhaenge: anhaenge.map((a) => ({ media_type: a.media_type, name: a.name, data: a.data })),
    }
    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    const images = anhaenge.map((a) => ({ data: a.data, media_type: a.media_type, filename: a.name }))
    setMessages((m) => [...m, userMsg])
    try {
      const { job_id } = await api.chatStart(history, f, images.length ? images : undefined)
      setJob({ id: job_id })
    } catch (e) {
      notify?.(e.message || 'Chat-Fehler', 'err')
      setMessages((m) => [...m, { role: 'assistant', content: 'Fehler: ' + (e.message || ''), tools: [] }])
    }
  }, [messages, job, notify])

  const leeren = useCallback(() => setMessages([]), [])

  return { messages, loading, senden, leeren }
}
