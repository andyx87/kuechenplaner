// KI-Fähigkeiten dieser Instanz („bring your own key"): GET /api/ki/status.
// Kleiner globaler Store + Hook. Solange nicht geladen bzw. bei Fehler gilt: alles aus –
// KI-Bedienelemente bleiben dann verborgen, der Rest der App funktioniert ohne KI.
import { useSyncExternalStore } from 'react'
import { api } from './api.js'

const AUS = { text: false, vision: false, bild: false, spracheingabe: false, websuche: false, darf_ki: false }
let zustand = { ...AUS, geladen: false }
const hoerer = new Set()

function setze(neu) {
  zustand = neu
  hoerer.forEach((h) => h())
}

let laufend = null
// Lädt den Status (nach Login bzw. Kontowechsel erneut aufrufen).
export function ladeKiStatus() {
  const p = api.kiStatus()
    .then((s) => { if (laufend === p) setze({ ...AUS, ...(s || {}), geladen: true }) })
    .catch(() => { if (laufend === p) setze({ ...AUS, geladen: true }) })
  laufend = p
  return p
}

export function resetKiStatus() { laufend = null; setze({ ...AUS, geladen: false }) }

function abonnieren(h) { hoerer.add(h); return () => hoerer.delete(h) }
function lesen() { return zustand }

// Liefert die nutzbaren Fähigkeiten – bereits mit darf_ki verknüpft.
export function useKi() {
  const s = useSyncExternalStore(abonnieren, lesen, lesen)
  const darf = !!s.darf_ki
  return {
    geladen: s.geladen,
    text: darf && !!s.text,
    vision: darf && !!s.vision,
    bild: darf && !!s.bild,
    sprache: darf && !!s.spracheingabe,
    irgendwas: darf && !!(s.text || s.vision || s.bild || s.spracheingabe),
  }
}
