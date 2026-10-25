// Auto-Update: erkennt, wenn eine neue Frontend-Version deployt wurde.
// Statt hartem Neuladen: beim Zurückkommen in den Tab still neu laden – und
// während du auf der Seite bist, ein dezentes Band mit „Aktualisieren"-Knopf
// (ein Klick = normaler Reload, da index.html/version.json nie gecacht werden).
const CURRENT = typeof __BUILD_ID__ !== 'undefined' ? String(__BUILD_ID__) : 'dev'
let neueVersion = false
let bandGezeigt = false

async function pruefe() {
  try {
    const r = await fetch('/version.json?t=' + Date.now(), { cache: 'no-store' })
    if (!r.ok) return
    const d = await r.json()
    if (d && d.build && String(d.build) !== CURRENT) {
      neueVersion = true
      if (document.visibilityState === 'visible') zeigeBand()
    }
  } catch { /* offline o. ä. – einfach später erneut versuchen */ }
}

// Dezentes Update-Band unten einblenden (vanilla DOM, unabhängig von React).
function zeigeBand() {
  if (bandGezeigt) return
  bandGezeigt = true

  const bar = document.createElement('div')
  bar.setAttribute('role', 'status')
  bar.style.cssText = [
    'position:fixed', 'left:50%', 'bottom:max(16px,env(safe-area-inset-bottom))',
    'transform:translateX(-50%)', 'z-index:2147483647',
    'display:flex', 'align-items:center', 'gap:12px',
    'padding:10px 12px 10px 16px', 'border-radius:9999px',
    'background:var(--card,#1a1b22)', 'color:var(--ink,#f3ede3)',
    'border:1px solid var(--line,rgba(255,255,255,0.1))',
    'box-shadow:0 10px 30px -10px rgba(0,0,0,0.55)',
    'font-family:"Plus Jakarta Sans",system-ui,sans-serif', 'font-size:14px',
    'max-width:calc(100vw - 24px)',
  ].join(';')

  const text = document.createElement('span')
  text.textContent = 'Neue Version verfügbar'
  text.style.cssText = 'font-weight:600;white-space:nowrap'

  const btn = document.createElement('button')
  btn.textContent = 'Aktualisieren'
  btn.style.cssText = [
    'flex:none', 'cursor:pointer', 'border:0', 'border-radius:9999px',
    'padding:7px 16px', 'font-weight:700', 'font-size:14px',
    'background:var(--terracotta,#d99a55)', 'color:var(--on-accent,#241a0f)',
    'box-shadow:0 8px 20px -8px rgba(227,168,106,0.7)',
  ].join(';')
  btn.onclick = () => { neueVersion = false; location.reload() }

  bar.appendChild(text)
  bar.appendChild(btn)
  document.body.appendChild(bar)
}

export function initVersionCheck() {
  if (CURRENT === 'dev') return  // im Dev-Server nicht nötig
  pruefe()                                  // einmal beim Start (gleiche Version -> kein Reload)
  setInterval(pruefe, 60 * 1000)            // jede Minute im Hintergrund prüfen
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return
    if (neueVersion) { location.reload(); return }  // beim Zurückkommen: frische Version laden
    pruefe()
  })
}
