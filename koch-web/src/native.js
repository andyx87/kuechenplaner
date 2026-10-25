// Native-Kontext (Capacitor). Wichtig fürs Store-Companion-Modell: In der nativen App
// darf – Anti-Steering – NICHT auf Kauf/Abo verlinkt oder dafür geworben werden. Käufe
// laufen ausschließlich über die Web-Version (Stripe). Im Browser ist IST_NATIVE=false,
// dort bleiben die Kauf-Buttons wie gehabt.
import { Capacitor } from '@capacitor/core'
import { App as CapApp } from '@capacitor/app'

export const IST_NATIVE = (() => {
  try { return Capacitor.isNativePlatform() } catch { return false }
})()

// Basis für Links, die man teilt oder verschickt. In der App ist window.location.origin
// https://localhost (lokales Bundle) – für Empfänger wertlos, daher die öffentliche Web-Adresse.
export const WEB_URL = IST_NATIVE ? (import.meta.env.VITE_WEB_URL || '') : window.location.origin

// Android-Zurück-Taste: ohne Listener beendet sie die App bzw. tut auf der Startseite nichts.
// Mit Verlauf -> history.back() (backnav.js schließt so das oberste Overlay oder wechselt den
// Tab), ohne Verlauf -> App in den Hintergrund, wie bei nativen Apps üblich.
export function initNative() {
  if (!IST_NATIVE) return
  CapApp.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) window.history.back()
    else CapApp.minimizeApp()
  })
}
