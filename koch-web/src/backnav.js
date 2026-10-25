// Zentrale Steuerung des Browser-Zurück-Buttons: EIN popstate-Listener + ein
// Overlay-Stack. Jedes offene Modal/Overlay registriert sich (LIFO); "Zurück"
// schließt zuerst das oberste Overlay, sonst ruft es den Tab-Handler (App).
const stack = []          // [{ close }]
let tabHandler = null
let installed = false

function install() {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('popstate', (e) => {
    const top = stack.pop()
    if (top) {
      try { top.close() } catch { /* egal */ }
      return
    }
    if (tabHandler) tabHandler(e)
  })
}

export function setTabHandler(fn) { install(); tabHandler = fn }
export function pushState(state) { install(); window.history.pushState(state, '') }
export function replaceState(state) { install(); window.history.replaceState(state, '') }

// Overlay anmelden (beim Öffnen). Legt einen History-Eintrag an, damit "Zurück"
// es schließt. Rückgabe: Aufräum-Funktion für den Fall, dass es NICHT per Zurück
// (sondern per X/Esc/Klick) geschlossen wird.
export function registerOverlay(close) {
  install()
  const entry = { close }
  stack.push(entry)
  window.history.pushState({ overlay: true }, '')
  return () => {
    const i = stack.lastIndexOf(entry)
    if (i >= 0) stack.splice(i, 1)
  }
}
