// Lokale App-Einstellungen (geräteweit, ohne Server).
const VORRAT_KEY = 'vorrat_aktiv'
const ABHAK_KEY = 'einkauf_abhak_modus'

// Sprachsteuerung im Kochmodus nutzt die Web Speech API des Browsers (kein Server). In der
// Android-WebView der Capacitor-App gibt es sie nicht – deshalb nur bei vorhandener API.
// Die Spracheingabe im Chat läuft dagegen über den Server und hängt an /api/ki/status
// (Fähigkeit „spracheingabe", s. kiStatus.js). Vorlesen (SpeechSynthesis) bleibt unabhängig.
export const SPRACHSTEUERUNG_MOEGLICH = typeof window !== 'undefined' &&
  ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

export function getVorratAktiv() {
  try { return localStorage.getItem(VORRAT_KEY) !== '0' } catch { return true }
}

export function setVorratAktiv(v) {
  try { localStorage.setItem(VORRAT_KEY, v ? '1' : '0') } catch { /* ignore */ }
}

// Abhak-Modus der Einkaufsliste: 'popup' (Menge je Artikel im Fenster) oder
// 'inline' (Mengen in der Liste + Sammel-Button). Nur relevant mit Vorratsverwaltung.
// Default seit UX-Review 2026-07-26: 'inline'. Gemessen am Handler-Fluss kostet ein
// 25-Artikel-Einkauf im Popup-Modus 50 Taps und ~29 Requests (je Artikel klappt die
// Handy-Tastatur auf), inline 1 Tap und 1 Batch-Request. Wer 'popup' bewusst gewählt
// hat, behält es (gespeicherte Wahl gewinnt).
export function getAbhakModus() {
  try { return localStorage.getItem(ABHAK_KEY) === 'popup' ? 'popup' : 'inline' } catch { return 'inline' }
}

export function setAbhakModus(m) {
  try { localStorage.setItem(ABHAK_KEY, m === 'inline' ? 'inline' : 'popup') } catch { /* ignore */ }
}

// Design / Theme: 'hell' | 'dunkel' | 'system'
const THEME_KEY = 'theme'

export function getTheme() {
  try { const t = localStorage.getItem(THEME_KEY); return ['hell', 'dunkel', 'system'].includes(t) ? t : 'system' } catch { return 'system' }
}

function _istDunkel(t) {
  if (t === 'dunkel') return true
  if (t === 'hell') return false
  return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(t = getTheme()) {
  try { document.documentElement.setAttribute('data-theme', _istDunkel(t) ? 'dunkel' : 'hell') } catch { /* ignore */ }
}

export function setTheme(t) {
  try { localStorage.setItem(THEME_KEY, t) } catch { /* ignore */ }
  applyTheme(t)
}

// Auf System-Wechsel reagieren, solange 'system' aktiv ist.
export function initThemeWatcher() {
  if (typeof window === 'undefined' || !window.matchMedia) return
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = () => { if (getTheme() === 'system') applyTheme('system') }
  mq.addEventListener ? mq.addEventListener('change', handler) : mq.addListener(handler)
}
