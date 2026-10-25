import React from 'react'
import { createRoot } from 'react-dom/client'
// Redesign-Typografie: Sans (UI) = Plus Jakarta Sans, Serif (Gerichte) = Instrument
// Serif, Mono (Kennzahlen/Status) = Space Mono. Siehe index.css / tailwind.config.js.
import '@fontsource/plus-jakarta-sans/400.css'
import '@fontsource/plus-jakarta-sans/500.css'
import '@fontsource/plus-jakarta-sans/600.css'
import '@fontsource/plus-jakarta-sans/700.css'
import '@fontsource/plus-jakarta-sans/800.css'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/space-mono/400.css'
import '@fontsource/space-mono/700.css'
import './index.css'
import AuthGate from './AuthGate.jsx'
import Fehlergrenze from './Fehlergrenze.jsx'
import { applyTheme, initThemeWatcher } from './settings.js'
import { initVersionCheck } from './version.js'
import { IST_NATIVE, initNative } from './native.js'

applyTheme()        // Theme vor dem ersten Render setzen (kein Flash)
initThemeWatcher()  // auf System-Wechsel reagieren (bei 'system')
initVersionCheck()  // neue Deploys automatisch erkennen + nachladen
initNative()        // Android: Zurück-Taste (nur in der Capacitor-App)

// PWA: Service-Worker für Installierbarkeit registrieren (kein Caching, s. public/sw.js).
// In der nativen App unnötig – dort kommt alles aus dem lokalen Bundle.
if (!IST_NATIVE && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}) })
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Fehlergrenze>
      <AuthGate />
    </Fehlergrenze>
  </React.StrictMode>,
)

// Marken-Splash ausblenden, sobald die App gemountet ist.
requestAnimationFrame(() => setTimeout(() => {
  const sp = document.getElementById('splash')
  if (sp) { sp.classList.add('sp-hide'); setTimeout(() => sp.remove(), 500) }
}, 250))
