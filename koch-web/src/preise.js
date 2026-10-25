// Preisliste – EINE Quelle für alle Preis- und Kontingenttexte im Frontend.
//
// Vorher standen „9,99 €", „50 Bilder/Monat", „Text unbegrenzt", „10 KI-Aktionen" und
// „75 für 12,99 €" als fester Text an 16 Stellen. Eine Preisänderung war damit eine
// Code-Änderung samt Deploy – und konnte auseinanderlaufen (angezeigter vs. gebuchter Preis).
// Jetzt kommt alles aus GET /api/preise (Tabelle `tarif` + `plattform_einstellung`),
// pflegbar im Admin-Bereich ohne Deploy.
import { useEffect, useState } from 'react'
import { api } from './api.js'

// Modulweiter Cache: die Preisliste ändert sich während einer Sitzung praktisch nie,
// also genau EIN Request pro Seitenaufruf, egal wie viele Komponenten sie brauchen.
let _cache = null

export function ladePreise() {
  if (!_cache) {
    _cache = api.preise().catch((e) => { _cache = null; throw e })
  }
  return _cache
}

// Nach einer Admin-Änderung den Cache verwerfen, damit die Texte sofort stimmen.
export function preiseVergessen() { _cache = null }

// Liefert die Preisliste oder null, solange sie lädt bzw. wenn der Abruf scheitert.
// Aufrufer rendern bei null KEINE Zahl – lieber nichts als eine falsche Angabe.
export function usePreise() {
  const [p, setP] = useState(null)
  useEffect(() => {
    let weg = false
    ladePreise().then((d) => { if (!weg) setP(d) }).catch(() => {})
    return () => { weg = true }
  }, [])
  return p
}

// „999" -> „9,99 €" (Endpreis; Beträge kommen immer in Cent vom Server).
export function euro(cents) {
  if (cents == null) return ''
  return (Number(cents) / 100).toLocaleString('de-DE', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }) + ' €'
}

// Kontingent als Text. limit === null bedeutet unbegrenzt – wird das Abo später gedeckelt,
// steht die Zahl automatisch im Text, ohne dass hier etwas geändert werden muss.
export function kontingent(limit, einheit = 'KI-Aktionen') {
  if (limit == null) return 'unbegrenzt'
  return `${limit} ${einheit}`
}

// „unbegrenzt" bzw. „100 KI-Aktionen pro Monat" – für Aufzählungen in Onboarding & Co.
export function kontingentProMonat(limit, einheit = 'KI-Aktionen') {
  if (limit == null) return 'unbegrenzt'
  return `${limit} ${einheit} pro Monat`
}
