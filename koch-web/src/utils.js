/**
 * Gemeinsame Hilfsfunktionen für Datum und Personen-Verfügbarkeit.
 * Wird von Planen.jsx und SpontanesKochen.jsx genutzt.
 */

// Mahlzeit-Rang (muss mit Backend _MAHLZEIT_RANG übereinstimmen)
export const MAHLZEIT_RANG = {
  'Frühstück': 0,
  'Mittag': 1,
  'Abendessen': 2,
  'Snack': 3,
  'Unterwegs': 4,
}

/** Lokales ISO-Datum (kein UTC-Versatz wie bei toISOString) */
export function localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Heutiges Datum als ISO-String (lokal) */
export function isoHeute() {
  return localIso(new Date())
}

/** ISO-Wochennummer + Wochentag (1=Mo…7=So) für ein Datum-String */
export function getISOWoche(iso) {
  const d = new Date(iso + 'T00:00:00')
  // ISO-Donnerstag der Woche bestimmt die Wochennummer
  const do4 = new Date(d)
  do4.setDate(d.getDate() - (d.getDay() || 7) + 4)
  const jan1 = new Date(do4.getFullYear(), 0, 1)
  const kw = Math.ceil(((do4 - jan1) / 86400000 + 1) / 7)
  const wochentag = d.getDay() === 0 ? 7 : d.getDay()
  return { kw, wochentag }
}

/** Montag der Woche, die `iso` enthält */
export function getMontag(iso) {
  const d = new Date(iso + 'T00:00:00')
  const diff = d.getDay() === 0 ? -6 : 1 - d.getDay()
  d.setDate(d.getDate() + diff)
  return localIso(d)
}

/** ISO-Datum nach n Tagen */
export function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return localIso(d)
}

/**
 * Ist eine Person an `datum` (ISO) und `mahlzeit` anwesend?
 * Berücksichtigt ihre abwesenheit_regeln (aus der Personen-API).
 */
export function istAnwesend(person, datum, mahlzeit) {
  const regeln = person?.abwesenheit_regeln ?? []
  if (!regeln.length) return true

  const { kw, wochentag } = getISOWoche(datum)
  const mRang = MAHLZEIT_RANG[mahlzeit] ?? 2

  for (const r of regeln) {
    if (r.woche_typ === 'gerade'   && kw % 2 !== 0) continue
    if (r.woche_typ === 'ungerade' && kw % 2 === 0) continue

    // Montag dieser Woche berechnen
    const dObj = new Date(datum + 'T00:00:00')
    const montag = new Date(dObj)
    montag.setDate(dObj.getDate() - (wochentag - 1))

    const depDate = new Date(montag)
    depDate.setDate(montag.getDate() + (r.von_wochentag - 1))

    const retDate = new Date(montag)
    if (r.folgewoche) retDate.setDate(retDate.getDate() + 7)
    retDate.setDate(retDate.getDate() + (r.bis_wochentag - 1))

    const depStr = localIso(depDate)
    const retStr = localIso(retDate)
    const depRang = MAHLZEIT_RANG[r.von_mahlzeit] ?? 2
    const retRang = MAHLZEIT_RANG[r.bis_mahlzeit] ?? 2

    if (depStr < datum && datum < retStr) return false
    if (datum === depStr && mRang >= depRang) return false
    if (datum === retStr && mRang < retRang) return false
  }
  return true
}

/**
 * Gibt einen kurzen Abwesenheits-Text für eine Person an einem ganzen Tag zurück.
 * z.B. "<Name> weg" wenn die Person an mindestens einer Mahlzeit fehlt.
 */
export function abwesenheitsLabel(person, datum) {
  const mahlzeiten = ['Frühstück', 'Mittag', 'Abendessen']
  const fehlend = mahlzeiten.filter((m) => !istAnwesend(person, datum, m))
  if (!fehlend.length) return null
  if (fehlend.length === mahlzeiten.length) return `${person.name} nicht zuhause`
  if (fehlend.includes('Abendessen') && fehlend.includes('Mittag')) return `${person.name} ab Mittag weg`
  if (fehlend.includes('Abendessen')) return `${person.name} ab Abendessen weg`
  return `${person.name} weg`
}
