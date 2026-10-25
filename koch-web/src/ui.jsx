import { useEffect, useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { registerOverlay } from './backnav.js'
import { Icon } from './icons.jsx'

// Ein Akzent = Kupfer. „Blau" ist aus dem System entfernt; KI-Aktionen nutzen denselben
// Kupfer-Akzent (solide = Hauptaktion, kiGhost = Kupfer-Outline für Nebenaktionen).
const variants = {
  primary: 'btn-accent shadow-glow',
  ghost: 'bg-transparent text-ink hover:bg-ink/5 border border-line',
  olive: 'bg-olive text-on-accent hover:brightness-110 shadow-soft',
  ki: 'btn-accent shadow-glow',
  kiGhost: 'bg-transparent text-terracotta border border-terracotta/45 hover:bg-terracotta/10',
}

export function Button({ children, variant = 'primary', className = '', ...p }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-2.5 text-sm font-bold transition active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 ${variants[variant]} ${className}`}
      {...p}
    >
      {children}
    </button>
  )
}

export function Card({ children, className = '', ...p }) {
  return (
    <div className={`rounded-2xl border border-line bg-card shadow-soft ${className}`} {...p}>
      {children}
    </div>
  )
}

export function Chip({ active, children, ...p }) {
  return (
    <button
      {...p}
      className={`rounded-full border px-3.5 py-2 text-sm font-medium transition active:scale-95 ${
        active
          ? 'border-terracotta bg-terracotta text-on-accent shadow-soft'
          : 'border-line bg-card text-ink hover:border-terracotta/50'
      }`}
    >
      {children}
    </button>
  )
}

export function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-bold uppercase tracking-wide text-ink/55">{label}</span>
      {children}
    </label>
  )
}

export const input =
  'w-full rounded-xl border border-line bg-paper/60 px-3 py-2 text-sm text-ink placeholder:text-ink/40 outline-none transition focus:border-terracotta focus:ring-2 focus:ring-terracotta/20'

export function Modal({ open, onClose, title, children }) {
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    if (!open) return
    const close = () => onCloseRef.current && onCloseRef.current()
    const h = (e) => e.key === 'Escape' && close()
    window.addEventListener('keydown', h)
    // Browser-Zurück schließt dieses Modal (registriert sich im Back-Stack).
    const unregister = registerOverlay(close)
    return () => { window.removeEventListener('keydown', h); unregister() }
  }, [open])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 max-h-[92vh] w-full overflow-y-auto rounded-t-3xl border border-line bg-card p-5 shadow-soft rise sm:max-w-lg sm:rounded-3xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h3 className="font-display text-2xl leading-tight">{title}</h3>
          <button onClick={onClose} aria-label="Schließen" className="-mr-1 rounded-full p-1.5 text-ink/60 hover:bg-ink/5"><Icon name="x" size={16} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export function Spinner() {
  return <div className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-terracotta" />
}

export function Empty({ children }) {
  return <p className="py-12 text-center text-ink/50">{children}</p>
}

// Lade-Platzhalter (Skeleton) – ruhiger als ein Spinner bei Listen/Karten.
export function Skeleton({ className = '' }) {
  return <div className={`animate-pulse rounded-xl bg-ink/10 ${className}`} />
}

export function SkeletonCards({ count = 4, className = 'grid gap-3 sm:grid-cols-2' }) {
  return (
    <div className={className}>
      {Array.from({ length: count }).map((_, i) => <Skeleton key={i} className="h-24" />)}
    </div>
  )
}

// Einheitlicher Bestätigungsdialog – ersetzt window.confirm.
// Aufruf: const ok = await confirmDialog({ message, title?, confirmLabel?, variant? })
// oder kurz: await confirmDialog('Wirklich löschen?')
// Optional: checkbox: { label, storageKey } – zeigt eine „nicht mehr anzeigen"-Checkbox.
//   Ist storageKey in localStorage gesetzt, wird der Dialog übersprungen (resolve(true)).
let _confirmFn = null
export function confirmDialog(opts) {
  const o = typeof opts === 'string' ? { message: opts } : (opts || {})
  const key = o.checkbox?.storageKey
  if (key) {
    try { if (localStorage.getItem(key) === '1') return Promise.resolve(true) } catch { /* ignore */ }
  }
  if (_confirmFn) return _confirmFn(o)
  return Promise.resolve(window.confirm(o.message || 'Fortfahren?'))
}

export function ConfirmHost() {
  const [state, setState] = useState(null) // { opts, resolve }
  const [checked, setChecked] = useState(false)
  useEffect(() => {
    _confirmFn = (opts) => new Promise((resolve) => { setChecked(false); setState({ opts, resolve }) })
    return () => { _confirmFn = null }
  }, [])
  if (!state) return null
  const { opts, resolve } = state
  const close = (v) => {
    // returnState: Auswahl + Haken-Status zurückgeben (Aufrufer merkt sich die Wahl selbst).
    if (opts.checkbox?.returnState) { resolve({ ok: v, remember: checked }); setState(null); return }
    const key = opts.checkbox?.storageKey
    if (v && checked && key) { try { localStorage.setItem(key, '1') } catch { /* ignore */ } }
    resolve(v); setState(null)
  }
  return (
    <Modal open title={opts.title || 'Bestätigen'} onClose={() => close(false)}>
      <div className="space-y-5">
        <p className="whitespace-pre-line text-sm text-ink/70">{opts.message}</p>
        {opts.checkbox && (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink/70">
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="h-4 w-4 accent-olive" />
            {opts.checkbox.label || 'Diesen Hinweis nicht mehr anzeigen'}
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => close(false)}>{opts.cancelLabel || 'Abbrechen'}</Button>
          <Button variant={opts.variant || 'primary'} onClick={() => close(true)}>{opts.confirmLabel || 'OK'}</Button>
        </div>
      </div>
    </Modal>
  )
}

// Frage beim Rezept-Import: KI-Bild erzeugen? Auswahl per Haken merkbar (3 Zustände:
// fragen / immer / nie). Gibt true/false zurück.
const IMPORT_BILD_KEY = 'import_bild_pref'   // 'an' | 'aus' | (unset = fragen)
export async function importBildEntscheidung() {
  let pref = null
  try { pref = localStorage.getItem(IMPORT_BILD_KEY) } catch { /* ignore */ }
  if (pref === 'an') return true
  if (pref === 'aus') return false
  const res = await confirmDialog({
    title: 'Bild fürs Rezept?',
    message: 'Soll für das importierte Rezept ein KI-Bild erzeugt werden? '
      + 'Du kannst auch jederzeit später eines hinzufügen.',
    confirmLabel: 'Bild erzeugen',
    cancelLabel: 'Ohne Bild',
    variant: 'ki',
    checkbox: { label: 'Auswahl merken – beim Import nicht mehr fragen', returnState: true },
  })
  const ok = typeof res === 'object' ? !!res.ok : !!res
  if (typeof res === 'object' && res.remember) {
    try { localStorage.setItem(IMPORT_BILD_KEY, ok ? 'an' : 'aus') } catch { /* ignore */ }
  }
  return ok
}
