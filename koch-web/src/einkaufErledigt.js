// Erledigt-Verwaltung der Einkaufsliste – EIN Ort für Schlüsselformat und Speicherung,
// genutzt von Einkaufsliste.jsx (Liste) und App.jsx (Warenkorb-Badge). Vorher bauten beide
// die Schlüssel selbst und konnten auseinanderlaufen.
//
// Schlüsselformat geplanter Positionen: `${periode.bis}|${zutat_id}|${einheit}`.
//  · periode.bis = der EINKAUFSTAG der Periode. Der ist über die Woche stabil – das früher
//    verwendete periode.von wandert täglich mit (von = max(heute, wochenstart)), wodurch
//    montags gesetzte Haken dienstags wirkungslos waren (Befund UX-Review 2026-07-26).
//  · zutat_id statt Anzeigename, damit Umbenennungen den Haken nicht lösen (Fallback Name).
// Manuelle Artikel: `extra:${id}` (unverändert).
//
// Bewusst weiterhin geräte-lokal (localStorage): der serverseitige, haushaltsweite
// Abhak-Status ist ein eigener Umbau (s. Review, 2-3 PT) und ersetzt dieses Modul dann.

export const EINKAUF_ERLEDIGT_KEY = 'einkauf_erledigt'

export function posKey(periode, pos) {
  return `${periode.bis}|${pos.zutat_id ?? pos.zutat}|${pos.einheit || ''}`
}

export function ladeErledigt() {
  try { return new Set(JSON.parse(localStorage.getItem(EINKAUF_ERLEDIGT_KEY) || '[]')) }
  catch { return new Set() }
}

export function speichereErledigt(set) {
  try { localStorage.setItem(EINKAUF_ERLEDIGT_KEY, JSON.stringify([...set])) } catch { /* ignore */ }
}

// Abgelaufene Einträge entfernen (Einkaufstag vorbei) – vorher wuchs der localStorage
// unbegrenzt, weil nie bereinigt wurde. Gibt dasselbe Set zurück (in-place).
export function bereinigeErledigt(set, heuteIso) {
  let geaendert = false
  for (const k of [...set]) {
    const m = /^(\d{4}-\d{2}-\d{2})\|/.exec(k)
    if (m && m[1] < heuteIso) { set.delete(k); geaendert = true }
  }
  if (geaendert) speichereErledigt(set)
  return set
}
