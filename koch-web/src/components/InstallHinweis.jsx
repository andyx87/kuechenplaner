import { useEffect, useState } from 'react'
import { Icon } from '../icons.jsx'

// Zeigt nur im BROWSER (nicht in der installierten App) einen dezenten Hinweis zum
// Installieren. Chrome/Android/Desktop: nativer Installdialog über beforeinstallprompt.
// iOS Safari (kein solches Event): manuelle Anleitung „Teilen → Zum Home-Bildschirm".
const KEY = 'install_hint_dismissed'

function istInstalliert() {
  try {
    return window.matchMedia?.('(display-mode: standalone)')?.matches || window.navigator.standalone === true
  } catch { return false }
}

export default function InstallHinweis() {
  const [prompt, setPrompt] = useState(null)   // gespeichertes beforeinstallprompt-Event
  const [iosHint, setIosHint] = useState(false)
  const [weg, setWeg] = useState(() => { try { return localStorage.getItem(KEY) === '1' } catch { return false } })

  useEffect(() => {
    if (weg || istInstalliert()) return
    const onBIP = (e) => { e.preventDefault(); setPrompt(e) }
    const onInstalled = () => { setPrompt(null); setIosHint(false); schliessen() }
    window.addEventListener('beforeinstallprompt', onBIP)
    window.addEventListener('appinstalled', onInstalled)
    // iOS Safari erkennen (kein beforeinstallprompt) → manuellen Hinweis zeigen.
    const ua = navigator.userAgent || ''
    if (/iphone|ipad|ipod/i.test(ua) && /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua)) {
      setIosHint(true)
    }
    return () => {
      window.removeEventListener('beforeinstallprompt', onBIP)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [weg])

  function schliessen() { try { localStorage.setItem(KEY, '1') } catch { /* ignore */ } setWeg(true) }

  async function installieren() {
    if (!prompt) return
    prompt.prompt()
    try { await prompt.userChoice } catch { /* ignore */ }
    setPrompt(null); schliessen()
  }

  if (weg || istInstalliert() || (!prompt && !iosHint)) return null

  return (
    <div className="fixed inset-x-0 bottom-0 z-[130] px-3 pb-[calc(env(safe-area-inset-bottom)+12px)] pt-3">
      <div className="mx-auto flex max-w-lg items-center gap-3 rounded-2xl border border-line bg-card/95 p-3 shadow-soft backdrop-blur">
        <img src="/icon-192.png" alt="" className="h-10 w-10 shrink-0 rounded-xl" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Als App installieren</p>
          <p className="mt-0.5 text-xs text-muted">
            {prompt
              ? 'Schnellzugriff vom Startbildschirm, Vollbild & Koch-Timer-Hinweise.'
              : 'In Safari: Teilen-Symbol → „Zum Home-Bildschirm".'}
          </p>
        </div>
        {prompt && (
          <button onClick={installieren} className="shrink-0 rounded-full bg-terracotta px-3.5 py-2 text-sm font-bold text-on-accent">
            Installieren
          </button>
        )}
        <button onClick={schliessen} aria-label="Schließen" className="shrink-0 rounded-full p-1.5 text-muted2 hover:bg-ink/5"><Icon name="x" size={16} /></button>
      </div>
    </div>
  )
}
