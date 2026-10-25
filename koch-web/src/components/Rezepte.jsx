import { useEffect, useState, useRef, useMemo } from 'react'
import { Generator } from './Start.jsx'
import { api } from '../api.js'
import { Card, Button, Field, input, Modal, Spinner, Empty, Chip, SkeletonCards, confirmDialog, importBildEntscheidung } from '../ui.jsx'
import { isoHeute } from '../utils.js'
import { getVorratAktiv } from '../settings.js'
import { IST_NATIVE, WEB_URL } from '../native.js'
import PortionenWahl from './PortionenWahl.jsx'
import GuidedCooking from './GuidedCooking.jsx'
import { Icon } from '../icons.jsx'
import { registerOverlay } from '../backnav.js'

const MAHLZEITEN = ['Frühstück', 'Mittag', 'Abendessen', 'Snack', 'Unterwegs']

function fmt(m) {
  const n = Number(m)
  return Number.isInteger(n) ? n : Math.round(n * 100) / 100
}

const STERN_VOLL = '#d4a454'
const STERN_LEER = '#d1c5b4'

function Sternebewertung({ sterne, onChange, readonly = false }) {
  const [hover, setHover] = useState(0)
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          disabled={readonly}
          onMouseEnter={() => !readonly && setHover(n)}
          onMouseLeave={() => !readonly && setHover(0)}
          onClick={() => !readonly && onChange?.(n)}
          className={`text-2xl leading-none transition-transform ${readonly ? '' : 'hover:scale-110'}`}
          title={readonly ? `${sterne} Stern${sterne !== 1 ? 'e' : ''}` : `${n} Stern${n !== 1 ? 'e' : ''}`}
        >
          <span style={{ color: (hover || sterne) >= n ? STERN_VOLL : STERN_LEER }}><Icon name="star" size={24} fill="currentColor" /></span>
        </button>
      ))}
    </div>
  )
}

export function ZubereitungAnsicht({ komponenten, heuteNamen }) {
  const geraetVerfuegbar = (geraetName) => {
    if (!geraetName) return true
    const gn = geraetName.toLowerCase()
    return [...heuteNamen].some((hn) => gn.includes(hn.toLowerCase()) || hn.toLowerCase().includes(gn))
  }

  const [wahl, setWahl] = useState(() =>
    komponenten.map((k) => {
      const i = (k.varianten || []).findIndex((v) => geraetVerfuegbar(v.geraet))
      return i >= 0 ? i : 0
    }),
  )
  return (
    <div className="space-y-4">
      {komponenten.map((k, ki) => {
        const varianten = k.varianten || []
        const aktiv = varianten[wahl[ki]] || varianten[0]
        return (
          <div key={ki}>
            {k.titel && <p className="mb-1 font-bold">{k.titel}</p>}
            {varianten.length > 1 && (
              <div className="mb-1.5 flex flex-wrap gap-1.5">
                {varianten.map((v, vi) => {
                  const verfuegbar = geraetVerfuegbar(v.geraet)
                  const sel = wahl[ki] === vi
                  return (
                    <button
                      key={vi}
                      onClick={() => setWahl((w) => w.map((x, j) => (j === ki ? vi : x)))}
                      title={verfuegbar ? '' : 'heute nicht ausgewählt'}
                      className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition ${
                        sel
                          ? 'border-terracotta bg-terracotta text-on-accent'
                          : verfuegbar
                            ? 'border-line bg-card text-ink hover:border-terracotta/50'
                            : 'border-line bg-card text-muted2'
                      }`}
                    >
                      {v.geraet || 'Standard'}
                    </button>
                  )
                })}
              </div>
            )}
            {aktiv && (
              <p className="whitespace-pre-wrap text-sm text-ink/80">{(aktiv.text || '').replace(/\\n/g, '\n')}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function Rezepte({ notify, openRezeptId, clearOpen, defaultPortionen = 2, onSpontan, auth, onDetailClose, detailOnly = false, angebotMarkt = null }) {
  const istAdmin = auth?.user?.plattform_rolle === 'super_admin'
  const vorratAktiv = getVorratAktiv()
  const [list, setList] = useState([])
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('name')   // name | bewertung | fehlend
  const [ansicht, setAnsicht] = useState('eigene')   // eigene | oeffentlich
  const [suchQuery, setSuchQuery] = useState('')
  const [suchBusy, setSuchBusy] = useState(false)
  const [suchTreffer, setSuchTreffer] = useState(null)   // null = Suche inaktiv, [] = keine Treffer
  const [suchAktivQuery, setSuchAktivQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null)
  const [add, setAdd] = useState(false)
  const [view, setView] = useState('hub')        // 'hub' | 'liste'
  const [hubStep, setHubStep] = useState(null)   // null | 'kategorie' (Eigene/Öffentlich wählen)

  // Geräte-/Browser-Zurück geht eine Ebene zurück (Liste → Übersicht, Kategorie-Wahl →
  // Übersicht), statt die Rubrik/den Tab zu wechseln.
  useEffect(() => {
    if (view !== 'liste') return
    const unregister = registerOverlay(() => { setView('hub'); setHubStep(null) })
    return () => unregister()
  }, [view])
  useEffect(() => {
    if (view !== 'hub' || hubStep !== 'kategorie') return
    const unregister = registerOverlay(() => setHubStep(null))
    return () => unregister()
  }, [view, hubStep])
  const [addChooser, setAddChooser] = useState(false)  // 3-Wege-Popup „Rezept hinzufügen"
  const [edit, setEdit] = useState(null)
  const [kochen, setKochen] = useState(null)
  const [heuteNamen, setHeuteNamen] = useState(() => new Set())
  const [kochPortionen, setKochPortionen] = useState(defaultPortionen)
  const [portionenOffen, setPortionenOffen] = useState(false)  // „Für wen" einklappbar
  const [guidedOffen, setGuidedOffen] = useState(false)
  const [anpassBusy, setAnpassBusy] = useState(false)
  const [anpassKarteBusy, setAnpassKarteBusy] = useState(null)   // Rezept-ID, die gerade aus der Übersicht angepasst wird
  const [importBusyId, setImportBusyId] = useState(null)         // Rezept-ID, die gerade importiert wird (Doppelklick-Schutz)

  async function anpassenEines() {
    if (!detail) return
    setAnpassBusy(true)
    try {
      const r = await api.rezeptAnGeraeteAnpassen(detail.id)
      const frisch = await api.rezept(detail.id)
      setDetail(frisch)
      notify(r?.angepasst ? 'An deine Küche angepasst' : 'Bereits passend – nichts anzupassen')
    } catch (e) { if (e?.status !== 402) notify(e.message || 'Anpassen fehlgeschlagen', 'err') }
    finally { setAnpassBusy(false) }
  }

  // Anpassen direkt aus der Rezeptübersicht (Button auf der Karte, ohne Detail zu öffnen).
  async function anpassenAusListe(r) {
    setAnpassKarteBusy(r.id)
    try {
      const res = await api.rezeptAnGeraeteAnpassen(r.id)
      setList((l) => l.map((x) => (x.id === r.id ? { ...x, geraete_abgestimmt: true } : x)))
      setKiTreffer((t) => t && t.map((x) => (x.id === r.id ? { ...x, geraete_abgestimmt: true } : x)))
      notify(res?.angepasst ? 'An deine Küche angepasst' : 'Bereits passend – nichts anzupassen')
    } catch (e) { if (e?.status !== 402) notify(e.message || 'Anpassen fehlgeschlagen', 'err') }
    finally { setAnpassKarteBusy(null) }
  }
  const [vorratCheck, setVorratCheck] = useState(null)
  const [einkaufBusy, setEinkaufBusy] = useState(false)   // Mehrfachklick-Schutz Einkaufsliste
  const [angebotMark, setAngebotMark] = useState({})   // zutat_id -> Angebotsinfo (aus Start „Im Angebot")
  const [bewertungSterne, setBewertungSterne] = useState(0)
  const [bewertungKommentar, setBewertungKommentar] = useState('')
  const [bildBusy, setBildBusy] = useState(false)
  const [bildBump, setBildBump] = useState(0)   // erzwingt Thumbnail-Aktualisierung nach Bildänderung
  const [bildOptionenOffen, setBildOptionenOffen] = useState(false)
  const [detailMenu, setDetailMenu] = useState(false)        // „Mehr"-Sheet im Rezept-Detail
  const [kochPlanSheet, setKochPlanSheet] = useState(false)  // „Loslegen" → Jetzt kochen / Einplanen
  const bildRef = useRef(null)
  const [planFor, setPlanFor] = useState(null)   // Rezept, das eingeplant wird
  const [planDatum, setPlanDatum] = useState(() => isoHeute())
  const [planMahlzeit, setPlanMahlzeit] = useState('Abendessen')
  const [planBusy, setPlanBusy] = useState(false)
  const [gangF, setGangF] = useState('')
  const [kuecheF, setKuecheF] = useState('')
  const [kuecheEingabe, setKuecheEingabe] = useState('')
  const [zutatenF, setZutatenF] = useState([])
  const [zutEingabe, setZutEingabe] = useState('')
  const [marktF, setMarktF] = useState('')
  const [filterOffen, setFilterOffen] = useState(false)
  const [kategorien, setKategorien] = useState({ gaenge: [], kuechen: [] })
  const [maerkte, setMaerkte] = useState([])
  const [masterZutaten, setMasterZutaten] = useState([])
  const [genOffen, setGenOffen] = useState(false)
  const [linkOffen, setLinkOffen] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkDateien, setLinkDateien] = useState([])   // [{data, media_type, name}] – Screenshots/PDFs
  const linkFileRef = useRef(null)

  function oeffnePlan(r) {
    setPlanFor(r)
    setPlanDatum(isoHeute())
    setPlanMahlzeit('Abendessen')
  }

  async function einplanen() {
    if (!planFor) return
    setPlanBusy(true)
    try {
      await api.planEintragAnlegen({ datum: planDatum, mahlzeit: planMahlzeit, rezept_id: planFor.id })
      const tag = new Date(planDatum + 'T00:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' })
      notify(`„${planFor.name}" für ${tag} (${planMahlzeit}) eingeplant`)
      setPlanFor(null)
    } catch {
      notify('Einplanen fehlgeschlagen', 'err')
    } finally {
      setPlanBusy(false)
    }
  }

  const zutMatches = useMemo(() => {
    const t = zutEingabe.trim().toLowerCase()
    if (!t) return []
    return (masterZutaten || [])
      .filter((m) => (m.name || '').toLowerCase().includes(t) && !zutatenF.includes(m.name))
      .sort((a, b) => {
        const ap = a.name.toLowerCase().startsWith(t) ? 0 : 1
        const bp = b.name.toLowerCase().startsWith(t) ? 0 : 1
        return ap - bp || a.name.length - b.name.length
      })
      .slice(0, 6)
  }, [zutEingabe, masterZutaten, zutatenF])

  const kuecheMatches = useMemo(() => {
    const t = kuecheEingabe.trim().toLowerCase()
    if (!t) return []
    return (kategorien.kuechen_genutzt || [])
      .filter((k) => (k.wert || '').toLowerCase().includes(t) && k.wert !== kuecheF)
      .slice(0, 8)
  }, [kuecheEingabe, kategorien, kuecheF])

  const aktiveFilter = (gangF ? 1 : 0) + (kuecheF ? 1 : 0) + zutatenF.length + (marktF ? 1 : 0)

  function buildRezeptQuery() {
    const p = new URLSearchParams()
    if (q.trim()) p.set('query', q.trim())
    if (gangF) p.set('gang', gangF)
    if (kuecheF) p.set('kueche', kuecheF)
    if (zutatenF.length) p.set('zutaten', zutatenF.join(','))
    if (marktF) p.set('markt', marktF)
    p.set('vorrat', vorratAktiv ? '1' : '0')
    return p.toString()
  }
  async function lade() {
    setLoading(true)
    try {
      setList(await api.rezepteFilter(buildRezeptQuery()))
    } catch {
      notify('Rezepte laden fehlgeschlagen', 'err')
    } finally {
      setLoading(false)
    }
  }

  async function suchen() {
    const wunsch = suchQuery.trim()
    if (wunsch.length < 2) return
    setSuchBusy(true)
    try {
      // Lexikalische Suche im Backend – kein KI-Aufruf, kein Kontingent-Verbrauch.
      const res = await api.rezeptSuche(wunsch, ansicht === 'eigene')
      setSuchTreffer(res.treffer || [])
      setSuchAktivQuery(wunsch)
    } catch (e) {
      notify(e.message || 'Suche fehlgeschlagen', 'err')
    } finally {
      setSuchBusy(false)
    }
  }
  function sucheZuruecksetzen() { setSuchTreffer(null); setSuchQuery(''); setSuchAktivQuery('') }

  async function oeffne(id, opts = {}) {
    try {
      const r = await api.rezept(id)
      setDetail(r)
      setKochPortionen(defaultPortionen || r.portionen || 2)
      setVorratCheck(null)
      setBewertungSterne(r.bewertung?.sterne || 0)
      setBewertungKommentar(r.bewertung?.kommentar || '')
      setBildOptionenOffen(false)
      // Direkt in den Schritt-für-Schritt-Modus, wenn von der Kachel "Kochen" kommt.
      if (opts.guided && (r.zubereitung?.length > 0 || (r.anleitung || '').trim())) setGuidedOffen(true)
      // Verfügbarkeits-Check nur bei aktiver Vorratsverwaltung.
      if (vorratAktiv) api.rezeptVorratCheck(id).then((c) => setVorratCheck(c)).catch(() => setVorratCheck({ zutaten: [] }))
    } catch {
      notify('Rezept laden fehlgeschlagen', 'err')
    }
  }

  async function importiere(r) {
    // Doppelklick-Schutz: der Import macht mehrere KI-Aufrufe nacheinander – ein zweiter
    // Tap in dieser Zeit erzeugte vorher eine zweite Kopie (plus Server-Dedupe als Netz).
    if (importBusyId) return
    setImportBusyId(r.id)
    try {
      const neu = await api.rezeptImportieren(r.id)
      if (neu?.error) { notify(neu.error, 'err'); return }
      if (neu?.bereits_vorhanden) {
        // Schon in der Bibliothek (Server-Dedupe): eigene Kopie öffnen statt duplizieren.
        notify(`„${r.name}" ist schon in deiner Bibliothek – ich öffne deine Kopie.`)
        setAnsicht('eigene'); lade('')
        await oeffne(neu.id)
        return
      }
      notify(`„${r.name}" übernommen – wird an deine Geräte angepasst …`)
      // An die eigenen Küchengeräte anpassen (KI). Bei Limit zeigt die App den 402-Dialog.
      try { await api.rezeptAnGeraeteAnpassen(neu.id) } catch (e) { if (e?.status !== 402) { /* trotzdem importiert */ } }
      // Hatte die Vorlage ein Bild, wird es mitkopiert (kein Kontingent-Verbrauch).
      // Nur ohne Bild wird gefragt, ob eines erzeugt werden soll.
      if (neu?.bild_uebernommen) {
        setBildBump((b) => b + 1)   // Thumbnails zeigen das übernommene Bild sofort
      } else {
        const wantBild = await importBildEntscheidung()
        if (wantBild) {
          try { await api.rezeptBildGenerieren(neu.id); setBildBump((b) => b + 1) }
          catch (e) { if (e?.status !== 402) notify('Bild erzeugen fehlgeschlagen', 'err') }
        }
      }
      notify(`„${r.name}" ist in deiner Bibliothek`)
      setAnsicht('eigene'); lade('')
      // Direkt auf die EIGENE Kopie umschalten – sonst zeigt das (fremde) Original
      // weiter „übernehmen" und erneutes Klicken würde Duplikate anlegen.
      if (neu?.id) { await oeffne(neu.id) } else { setDetail(null) }
    } catch { notify('Import fehlgeschlagen', 'err') }
    finally { setImportBusyId(null) }
  }

  function dateiZuBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(String(r.result).split(',')[1] || '')
      r.onerror = reject
      r.readAsDataURL(file)
    })
  }
  async function linkDateienWaehlen(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    for (const f of files) {
      try {
        const data = await dateiZuBase64(f)
        setLinkDateien((a) => [...a, { data, media_type: f.type || 'application/octet-stream', name: f.name }])
      } catch { notify('Datei konnte nicht gelesen werden', 'err') }
    }
  }

  async function importiereLink() {
    const hatDateien = linkDateien.length > 0
    const url = linkUrl.trim()
    if (!hatDateien && !url) return
    setLinkBusy(true)
    try {
      const res = hatDateien ? await api.rezeptAusDateien(linkDateien) : await api.rezeptAusLink(url)
      if (res?.status === 'ok' && res.rezept) {
        const neu = res.rezept
        notify(`„${neu.name}" importiert`)
        setLinkOffen(false); setLinkUrl(''); setLinkDateien([]); setAnsicht('eigene'); lade('')
        // An die eigenen Geräte anpassen (KI). Bei Limit zeigt die App den 402-Dialog.
        try { await api.rezeptAnGeraeteAnpassen(neu.id) } catch (e) { if (e?.status !== 402) { /* trotzdem importiert */ } }
        const wantBild = await importBildEntscheidung()
        if (wantBild) { try { await api.rezeptBildGenerieren(neu.id) } catch (e) { if (e?.status !== 402) notify('Bild erzeugen fehlgeschlagen', 'err') } }
        lade('')
      } else {
        // kein_rezept / keine_caption / nicht_unterstuetzt
        notify(res?.meldung || 'Kein Rezept erkannt – versuch einen klareren Screenshot oder den Text.', 'err')
      }
    } catch (e) {
      if (e?.status !== 402) notify(e?.message || 'Import fehlgeschlagen', 'err')
    } finally { setLinkBusy(false) }
  }

  useEffect(() => {
    api.geraeteHeute().then((gs) => setHeuteNamen(new Set(gs.map((g) => g.name)))).catch(() => {})
    api.rezeptKategorien().then(setKategorien).catch(() => {})
    api.angeboteMaerkte(isoHeute()).then((m) => setMaerkte(m || [])).catch(() => {})
    api.zutatenMaster().then((z) => setMasterZutaten(z || [])).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Liste (neu) laden, wenn sich Suche/Filter ändern – mit kleiner Entprellung.
  useEffect(() => {
    if (detailOnly) return   // im Overlay-Modus keine Liste laden
    const t = setTimeout(lade, 200)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, gangF, kuecheF, zutatenF, marktF, vorratAktiv])

  useEffect(() => {
    if (openRezeptId) {
      oeffne(openRezeptId)
      clearOpen()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRezeptId])

  // Angebots-Markierung: welche Zutaten sind aktuell im Angebot? Mit gewähltem Markt (aus
  // „Im Angebot") nur dieser, sonst marktübergreifend alle aktuellen Angebote.
  useEffect(() => {
    if (!detail) { setAngebotMark({}); return }
    api.rezeptAngebote(detail.id, angebotMarkt || '').then((m) => setAngebotMark(m || {})).catch(() => setAngebotMark({}))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, angebotMarkt])

  // Wenn das Detail geschlossen wird, App benachrichtigen (zurück zur Herkunft, z.B. Start).
  const prevDetailRef = useRef(null)
  useEffect(() => {
    if (prevDetailRef.current && !detail) onDetailClose && onDetailClose()
    prevDetailRef.current = detail
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail])

  async function speicherBewertung() {
    if (!bewertungSterne) return
    try {
      await api.rezeptBewertungSetzen(detail.id, bewertungSterne, bewertungKommentar || null)
      setDetail((d) => ({ ...d, bewertung: { sterne: bewertungSterne, kommentar: bewertungKommentar } }))
      notify('Bewertung gespeichert')
    } catch {
      notify('Bewertung speichern fehlgeschlagen', 'err')
    }
  }

  async function bildGenerieren() {
    if (!detail) return
    setBildBusy(true)
    try {
      const res = await api.rezeptBildGenerieren(detail.id)
      setDetail((d) => ({ ...d, bild: res.bild }))
      setBild(detail.id, res.bild); setBildBump((b) => b + 1)   // Thumbnails überall live aktualisieren
      lade('')
      notify('Bild erstellt')
    } catch { notify('Bildgenerierung fehlgeschlagen (LiteLLM erreichbar?)', 'err') }
    finally { setBildBusy(false) }
  }
  async function bildUpload(e) {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file || !detail) return
    setBildBusy(true)
    try {
      const res = await api.rezeptBildUpload(detail.id, file)
      setDetail((d) => ({ ...d, bild: res.bild })); setBild(detail.id, res.bild); setBildBump((b) => b + 1); lade('')
      notify('Bild gespeichert')
    } catch { notify('Bild-Upload fehlgeschlagen', 'err') }
    finally { setBildBusy(false) }
  }
  async function bildLoeschen() {
    if (!detail) return
    try { await api.rezeptBildLoeschen(detail.id); setDetail((d) => ({ ...d, bild: null })); setBild(detail.id, null); setBildBump((b) => b + 1); lade('') }
    catch { notify('Entfernen fehlgeschlagen', 'err') }
  }

  function dataUrlToFile(dataUrl, filename) {
    try {
      const [meta, b64] = dataUrl.split(',')
      const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/jpeg'
      const bin = atob(b64)
      const arr = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
      return new File([arr], filename, { type: mime })
    } catch { return null }
  }

  async function teilen() {
    if (!detail) return
    const z = (detail.zutaten || [])
      .map((zt) => `• ${zt.menge != null ? String(zt.menge).replace('.', ',') + ' ' + (zt.einheit || '') + ' ' : ''}${zt.zutat || zt.name}`)
      .join('\n')
    const schritte = (detail.zubereitung || [])
      .map((k, i) => `${i + 1}. ${k.titel ? k.titel + ': ' : ''}${k.varianten?.[0]?.text || ''}`)
      .join('\n')
    const appUrl = WEB_URL
    const pr = `\n\n— — —\nErstellt mit Sapio: KI plant deine Woche, behält Vorrat & Angebote im Blick und erstellt Rezepte auf Knopfdruck.\nJetzt ausprobieren ${appUrl}`
    const text = `${detail.name}\n${detail.beschreibung || ''}\n\nZutaten:\n${z}${schritte ? `\n\nZubereitung:\n${schritte}` : ''}${pr}`
    const shareData = { title: detail.name, text, url: appUrl }
    // Generiertes Bild mitteilen, wenn vorhanden und vom Gerät unterstützt.
    if (detail.bild) {
      const file = dataUrlToFile(detail.bild, `${(detail.name || 'rezept').replace(/[^\w]+/g, '_')}.jpg`)
      if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
        shareData.files = [file]
      }
    }
    try {
      if (navigator.share) {
        await navigator.share(shareData)
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(text)
        notify('Rezept in die Zwischenablage kopiert')
      } else {
        notify('Teilen wird hier nicht unterstützt', 'err')
      }
    } catch { /* abgebrochen */ }
  }

  function druckePdf() {
    if (!detail) return
    const esc = (s) => String(s || '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
    const mng = (m) => (m == null ? '' : String(m).replace('.', ','))
    const zut = (detail.zutaten || []).map((z) =>
      `<li>${z.menge != null ? mng(z.menge) + ' ' + esc(z.einheit || '') + ' ' : ''}${esc(z.zutat || z.name)}${z.optional ? ' (optional)' : ''}</li>`).join('')
    const zub = (detail.zubereitung || []).map((k) =>
      `<li>${k.titel ? '<b>' + esc(k.titel) + ':</b> ' : ''}${esc(k.varianten?.[0]?.text || '')}</li>`).join('')
    const meta = [detail.portionen ? detail.portionen + ' Portionen' : '', detail.dauer_minuten ? detail.dauer_minuten + ' min' : ''].filter(Boolean).join(' · ')
    const html = `<!doctype html><html lang="de"><head><meta charset="utf-8"><title>${esc(detail.name)}</title>
<style>body{font-family:Georgia,'Times New Roman',serif;max-width:720px;margin:32px auto;padding:0 20px;color:#2B2218;line-height:1.5}
h1{font-size:30px;margin:0 0 6px} h2{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#9E3A24;margin:26px 0 8px}
.meta{color:#777;font-size:13px;margin:0 0 4px} ul,ol{padding-left:20px;margin:0} li{margin:5px 0}
img{max-width:100%;border-radius:12px;margin:12px 0}</style></head>
<body><h1>${esc(detail.name)}</h1>
${detail.beschreibung ? `<p>${esc(detail.beschreibung)}</p>` : ''}
<p class="meta">${meta}</p>
${detail.bild ? `<img src="${detail.bild}" alt="">` : ''}
<h2>Zutaten</h2><ul>${zut}</ul>
<h2>Zubereitung</h2><ol>${zub}</ol>
${detail.anleitung ? `<h2>Hinweise</h2><p>${esc(detail.anleitung)}</p>` : ''}
</body></html>`
    const w = window.open('', '_blank')
    if (!w) { notify('Pop-up wurde blockiert – bitte für diese Seite erlauben.', 'err'); return }
    w.document.write(html); w.document.close(); w.focus()
    setTimeout(() => w.print(), 350)
  }

  async function freigeben(val, globalisieren = false) {
    try {
      const res = await api.rezeptVeroeffentlichen(detail.id, val, globalisieren)
      if (res?.benoetigt_globalisierung) {
        const liste = res.nicht_global.join(', ')
        const ok = await confirmDialog({
          title: 'Zutaten global machen?',
          message: `Dieses Rezept nutzt ${res.nicht_global.length} nicht-globale Zutat(en):\n${liste}\n\nVeröffentlichte Rezepte dürfen nur globale Zutaten nutzen. Sollen diese in die globale Zutaten-DB überführt werden?`,
          confirmLabel: 'Global machen & freigeben',
        })
        if (ok) return freigeben(val, true)
        return
      }
      if (res?.error) { notify(res.error, 'err'); return }
      setDetail((d) => ({ ...d, veroeffentlicht: val }))
      lade('')
      notify(val ? 'Rezept für alle freigegeben' : 'Veröffentlichung zurückgezogen')
    } catch {
      notify('Freigabe fehlgeschlagen', 'err')
    }
  }

  async function loescheBewertung() {
    try {
      await api.rezeptBewertungLoeschen(detail.id)
      setBewertungSterne(0)
      setBewertungKommentar('')
      setDetail((d) => ({ ...d, bewertung: null }))
      notify('Bewertung entfernt')
    } catch {
      notify('Entfernen fehlgeschlagen', 'err')
    }
  }

  async function starteKochen() {
    try {
      const v = await api.kochenVorschau(detail.id)
      const faktor = kochPortionen / (detail.portionen || 1)
      setKochen({ vorschau: v, faktor })
    } catch {
      notify('Vorschau fehlgeschlagen', 'err')
    }
  }

  async function fehlendeAufEinkaufsliste() {
    if (!detail || einkaufBusy) return
    const faktor = kochPortionen / (detail.portionen || 1)
    const items = []
    for (const z of detail.zutaten || []) {
      if (z.optional) continue
      const scaled = z.menge != null ? z.menge * faktor : null
      const ci = vorratCheck?.zutaten?.find((c) => c.zutat_id === z.zutat_id)
      const sameUnit = ci && (ci.vorhanden_einheit || '').toLowerCase() === (z.einheit || '').toLowerCase()
      let status
      if (!ci || ci.vorhanden_menge == null) status = 'fehlt'
      else if (sameUnit) status = ci.vorhanden_menge >= (scaled || 0) ? 'ok' : 'knapp'
      else status = ci.status === 'aehnlich' ? 'aehnlich' : 'vorhanden'
      if (status === 'ok' || status === 'vorhanden' || status === 'aehnlich') continue
      // fehlt oder knapp -> auf die Liste
      let menge = scaled
      if (status === 'knapp' && sameUnit && ci.vorhanden_menge != null) {
        menge = Math.max(0, (scaled || 0) - ci.vorhanden_menge)
      }
      items.push({
        name: z.zutat,
        menge: menge != null ? Math.round(menge * 100) / 100 : null,
        einheit: z.einheit || null,
      })
    }
    if (items.length === 0) { notify('Nichts fehlt – alles im Vorrat'); return }
    setEinkaufBusy(true)
    try {
      await api.einkaufExtraHinzufuegen(items)
      notify(`${items.length} Zutat(en) auf die Einkaufsliste gesetzt`)
    } catch {
      notify('Auf die Liste setzen fehlgeschlagen', 'err')
    } finally { setEinkaufBusy(false) }
  }

  // Ohne Vorratsverwaltung: alle (nicht-optionalen) Zutaten auf die Liste – ohne Verfügbarkeits-Check.
  async function alleAufEinkaufsliste() {
    if (!detail || einkaufBusy) return
    const faktor = kochPortionen / (detail.portionen || 1)
    const items = (detail.zutaten || []).filter((z) => !z.optional).map((z) => ({
      name: z.zutat,
      menge: z.menge != null ? Math.round(z.menge * faktor * 100) / 100 : null,
      einheit: z.einheit || null,
    }))
    if (items.length === 0) { notify('Keine Zutaten'); return }
    setEinkaufBusy(true)
    try {
      await api.einkaufExtraHinzufuegen(items)
      notify(`${items.length} Zutat(en) auf die Einkaufsliste gesetzt`)
    } catch {
      notify('Auf die Liste setzen fehlgeschlagen', 'err')
    } finally { setEinkaufBusy(false) }
  }

  async function bestaetigeKochen() {
    try {
      const r = await api.kochenBestaetigen(detail.id, Number(kochen.faktor) || 1)
      const unmet = (r.reduziert || []).filter((x) => x.nicht_gedeckt > 0)
      setKochen(null)
      setDetail(null)
      notify(unmet.length ? `Gekocht – ${unmet.length} Zutat(en) reichten nicht` : 'Gekocht & Vorrat reduziert')
    } catch {
      notify('Abzug fehlgeschlagen', 'err')
    }
  }

  async function loeschenRezept() {
    if (!detail) return
    if (!(await confirmDialog(`„${detail.name}" wirklich löschen?`))) return
    try {
      await api.rezeptLoeschen(detail.id)
      setDetail(null)
      notify('Rezept gelöscht')
      lade(q)
    } catch {
      notify('Löschen fehlgeschlagen', 'err')
    }
  }

  const meinKonto = auth?.account?.id
  const sichtbar = list.filter((r) => ansicht === 'oeffentlich'
    ? (r.veroeffentlicht && r.account_id !== meinKonto)
    : (r.account_id === meinKonto))

  return (
    <div className="space-y-4">
      {!detailOnly && (view === 'hub' ? (
        <div className="rise space-y-4">
          <h2 className="font-dish text-4xl leading-tight text-ink">Rezepte</h2>
          {hubStep === 'kategorie' ? (
            <div className="space-y-2.5">
              <p className="text-sm text-muted">Welche Rezepte möchtest du sehen?</p>
              <button onClick={() => { setAnsicht('eigene'); sucheZuruecksetzen(); setView('liste') }}
                className="flex w-full items-center gap-4 rounded-[18px] border border-line bg-card p-5 text-left transition hover:-translate-y-0.5 hover:border-terracotta/40 active:scale-[0.99]">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-terracotta/15 text-terracotta"><Icon name="notebook" size={24} /></span>
                <span><span className="block font-bold text-ink">Eigene Rezepte</span><span className="block text-sm text-muted">Deine gespeicherte Bibliothek</span></span>
              </button>
              <button onClick={() => { setAnsicht('oeffentlich'); sucheZuruecksetzen(); setView('liste') }}
                className="flex w-full items-center gap-4 rounded-[18px] border border-line bg-card p-5 text-left transition hover:-translate-y-0.5 hover:border-terracotta/40 active:scale-[0.99]">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-terracotta/15 text-terracotta"><Icon name="globe" size={24} /></span>
                <span><span className="block font-bold text-ink">Öffentliche Rezepte</span><span className="block text-sm text-muted">Von der Community – zum Übernehmen</span></span>
              </button>
              <button onClick={() => setHubStep(null)} className="inline-flex items-center gap-1 pt-1 text-sm font-semibold text-muted2 hover:text-ink"><Icon name="chevron-left" size={16} /> Zurück</button>
            </div>
          ) : (
            <div className="grid gap-4">
              <button onClick={() => setAddChooser(true)}
                className="hero-card relative flex items-center gap-4 overflow-hidden rounded-[22px] p-6 text-left transition hover:-translate-y-0.5 active:scale-[0.99] sm:p-7">
                <span className="hero-glow" />
                <span className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-terracotta/15 text-terracotta sm:h-16 sm:w-16"><Icon name="plus" size={30} /></span>
                <span className="relative"><span className="block text-xl font-bold text-ink sm:text-2xl">Rezept hinzufügen</span><span className="mt-0.5 block text-sm text-muted">Mit KI, importieren oder selbst anlegen</span></span>
              </button>
              <button onClick={() => setHubStep('kategorie')}
                className="flex items-center gap-4 rounded-[22px] border border-line bg-card p-6 text-left transition hover:-translate-y-0.5 hover:border-terracotta/40 active:scale-[0.99] sm:p-7">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-terracotta/15 text-terracotta sm:h-16 sm:w-16"><Icon name="book-open" size={30} /></span>
                <span><span className="block text-xl font-bold text-ink sm:text-2xl">Rezepte anzeigen</span><span className="mt-0.5 block text-sm text-muted">Eigene & öffentliche durchstöbern</span></span>
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button onClick={() => { setView('hub'); setHubStep(null) }} aria-label="Zurück" className="rounded-full border border-line p-2 text-muted transition hover:border-terracotta/40 hover:text-terracotta active:scale-95"><Icon name="chevron-left" size={18} /></button>
            <h2 className="flex-1 font-dish text-3xl leading-tight">{ansicht === 'eigene' ? 'Eigene Rezepte' : 'Öffentliche Rezepte'}</h2>
            <button onClick={() => setFilterOffen(true)} aria-label="Filtern & sortieren" className="relative rounded-full border border-line p-2 text-muted transition hover:border-terracotta/40 hover:text-terracotta active:scale-95">
              <Icon name="sliders" size={18} />
              {aktiveFilter > 0 && <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-terracotta px-1 text-[10px] font-bold text-on-accent">{aktiveFilter}</span>}
            </button>
          </div>

          <div className="rounded-2xl border border-line bg-card/50 p-2.5">
            <div className="flex items-center gap-2">
              <span className="pl-1 text-terracotta"><Icon name="search" size={18} /></span>
              <input
                className="min-w-0 flex-1 bg-transparent px-1 py-1.5 text-sm text-ink placeholder:text-muted2 focus:outline-none"
                placeholder="Suchen: Name oder Zutat, z. B. „Hähnchen“ oder „schnell ohne Ofen“"
                value={suchQuery}
                onChange={(e) => setSuchQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !suchBusy) suchen() }}
              />
              <Button variant="primary" className="shrink-0" onClick={suchen} disabled={suchBusy || suchQuery.trim().length < 2}>
                {suchBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="search" size={16} /> Suchen</span>}
              </Button>
            </div>
            {suchTreffer !== null && (
              <div className="mt-2 flex items-center justify-between gap-2 px-1 text-xs text-muted2">
                <span className="min-w-0 truncate">Suche „{suchAktivQuery}“ · {suchTreffer.length} Treffer</span>
                <button onClick={sucheZuruecksetzen} className="shrink-0 font-semibold text-terracotta hover:underline">zurücksetzen</button>
              </div>
            )}
          </div>

          {loading ? (
            <SkeletonCards count={6} />
          ) : (suchTreffer !== null && suchTreffer.length === 0) ? (
            <Empty>Keine passenden Rezepte zu „{suchAktivQuery}“. Formuliere es anders oder setze die Suche zurück.</Empty>
          ) : (suchTreffer === null && sichtbar.length === 0) ? (
            (q || gangF || kuecheF || zutatenF.length || marktF) ? (
              <Empty>Keine Rezepte für diese Auswahl.</Empty>
            ) : ansicht === 'oeffentlich' ? (
              <Empty>Noch keine öffentlichen Rezepte verfügbar.</Empty>
            ) : (
              <div className="rounded-2xl border border-dashed border-line p-8 text-center">
                <p className="flex justify-center text-3xl"><Icon name="utensils" size={32} /></p>
                <p className="mt-2 font-semibold">Noch keine Rezepte</p>
                <p className="mt-0.5 text-sm text-muted2">Tippe oben links auf „Zurück" und dann „Rezept hinzufügen".</p>
              </div>
            )
          ) : (
            <div className="grid gap-3 stagger sm:grid-cols-2">
              {(suchTreffer !== null ? suchTreffer : [...sichtbar].sort((a, b) => {
                if (marktF) return 0
                const s = (!vorratAktiv && sort === 'fehlend') ? 'name' : sort
                const fa = a.fehlend ?? 99, fb = b.fehlend ?? 99
                const sa = a.sterne || 0, sb = b.sterne || 0
                if (s === 'bewertung') return sb - sa || fa - fb || a.name.localeCompare(b.name, 'de')
                if (s === 'fehlend') return fa - fb || sb - sa || a.name.localeCompare(b.name, 'de')
                if (s === 'neu') return (b.id || 0) - (a.id || 0)
                if (s === 'dauer') return (a.dauer_minuten ?? 1e9) - (b.dauer_minuten ?? 1e9) || a.name.localeCompare(b.name, 'de')
                return a.name.localeCompare(b.name, 'de')
              })).map((r) => (
                <Card key={r.id} onClick={() => oeffne(r.id)} className="flex cursor-pointer flex-col p-4 transition hover:-translate-y-0.5">
                  <RezeptThumb id={r.id} hatBild={r.hat_bild} bump={bildBump} />
                  <h3 className="font-dish text-2xl leading-tight">{r.name}</h3>
                  <p className="mt-1 font-mono text-xs text-muted">
                    {[r.portionen ? `${r.portionen} Port.` : null, r.dauer_minuten ? `${r.dauer_minuten} min` : null].filter(Boolean).join(' · ') || '—'}
                  </p>
                  {(r.gang || r.kueche) && (
                    <p className="mt-1 flex flex-wrap gap-1">
                      {r.gang && <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-muted2">{r.gang}</span>}
                      {r.kueche && <span className="rounded-full bg-terracotta/15 px-2 py-0.5 text-[11px] font-semibold text-terracotta">{r.kueche}</span>}
                    </p>
                  )}
                  {marktF && r.angebot_treffer != null && (
                    <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-terracotta/15 px-2 py-0.5 text-xs font-semibold text-terracotta-deep">
                      <Icon name="tag" size={16} /> {r.angebot_treffer} Angebot{r.angebot_treffer === 1 ? '' : 'e'}{vorratAktiv && r.vorrat_treffer ? <> · <Icon name="soup" size={16} /> {r.vorrat_treffer}</> : ''}
                    </span>
                  )}
                  {r.sterne ? (
                    <p className="mt-1 flex items-center gap-0.5 text-sm" style={{ color: STERN_VOLL }}>
                      {Array.from({ length: r.sterne }).map((_, i) => <Icon key={`v${i}`} name="star" size={16} fill="currentColor" />)}
                      {Array.from({ length: 5 - r.sterne }).map((_, i) => <Icon key={`e${i}`} name="star" size={16} />)}
                    </p>
                  ) : null}
                  {vorratAktiv && r.fehlend != null && (
                    <span className={`mt-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${r.fehlend === 0 ? 'bg-olive/15 text-olive' : 'bg-terracotta/15 text-terracotta-deep'}`}>
                      {r.fehlend === 0 ? <><Icon name="check" size={16} /> alles im Vorrat</> : <><Icon name="x" size={16} /> {r.fehlend} {r.fehlend === 1 ? 'Zutat fehlt' : 'Zutaten fehlen'}</>}
                    </span>
                  )}
                  {r.account_id === meinKonto && r.geraete_abgestimmt === false && (
                    <button onClick={(e) => { e.stopPropagation(); anpassenAusListe(r) }} disabled={anpassKarteBusy === r.id}
                      className="mt-2 inline-flex items-center justify-center gap-1 rounded-full border border-terracotta/50 bg-terracotta/10 px-2.5 py-1 text-xs font-semibold text-terracotta transition hover:bg-terracotta/20 disabled:opacity-50">
                      <Icon name="wrench" size={16} /> {anpassKarteBusy === r.id ? 'wird angepasst …' : 'An deine Küche anpassen'}
                    </button>
                  )}
                  {ansicht === 'oeffentlich' && r.account_id !== meinKonto && (
                    <button onClick={(e) => { e.stopPropagation(); importiere(r) }} disabled={importBusyId !== null}
                      className="mt-3 flex w-full items-center justify-center gap-1 rounded-xl border border-olive/40 bg-olive/5 px-3 py-1.5 text-sm font-semibold text-olive transition hover:bg-olive/10 disabled:opacity-50">
                      <Icon name="download" size={16} /> {importBusyId === r.id ? 'wird übernommen …' : 'In meine Bibliothek'}
                    </button>
                  )}
                </Card>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* „Rezept hinzufügen" – ein Einstieg, drei Wege */}
      {!detailOnly && (
        <Modal open={addChooser} onClose={() => setAddChooser(false)} title="Rezept hinzufügen">
          <div className="grid gap-3">
            <button onClick={() => { setAddChooser(false); setGenOffen(true) }}
              className="flex items-center gap-3 rounded-2xl bg-terracotta p-4 text-left text-on-accent shadow-soft transition hover:bg-terracotta-deep active:scale-[0.99]">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15"><Icon name="sparkles" size={22} /></span>
              <span><span className="block font-bold">Mit KI erstellen</span><span className="block text-sm text-white/80">Aus Zutaten, Idee oder Foto</span></span>
            </button>
            <button onClick={() => { setAddChooser(false); setLinkOffen(true) }}
              className="flex items-center gap-3 rounded-2xl border border-terracotta/40 bg-terracotta/5 p-4 text-left text-terracotta transition hover:bg-terracotta/10 active:scale-[0.99]">
              <Icon name="download" size={22} className="shrink-0" />
              <span><span className="block font-bold">Importieren</span><span className="block text-sm text-terracotta/70">Link, Foto, Text, PDF</span></span>
            </button>
            <button onClick={() => { setAddChooser(false); setAdd(true) }}
              className="flex items-center gap-3 rounded-2xl border border-line bg-card p-4 text-left transition hover:border-terracotta/40 active:scale-[0.99]">
              <Icon name="plus" size={22} className="shrink-0 text-terracotta" />
              <span><span className="block font-bold">Selbst hinzufügen</span><span className="block text-sm text-muted2">Manuell eingeben</span></span>
            </button>
          </div>
        </Modal>
      )}

      {/* Filter & Sortierung – Sheet (über das Filtersymbol) */}
      {!detailOnly && (
        <Modal open={filterOffen} onClose={() => setFilterOffen(false)} title="Filter & Sortierung">
          <div className="space-y-3">
            <input className={input} placeholder="Rezept suchen…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && lade(q)} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-16 shrink-0 label-mono font-bold text-muted2">Sortieren</span>
              <select className={input + ' max-w-[16rem] flex-1 py-1 text-sm'} value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="name">Name (A–Z)</option>
                <option value="bewertung">Beste Bewertung</option>
                <option value="neu">Neueste zuerst</option>
                <option value="dauer">Dauer (kurz zuerst)</option>
                {vorratAktiv && <option value="fehlend">Zutaten vorhanden</option>}
              </select>
            </div>
            {kategorien.gaenge?.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="w-16 shrink-0 label-mono font-bold text-muted2">Gang</span>
                <Chip active={!gangF} onClick={() => setGangF('')}>Alle</Chip>
                {kategorien.gaenge.map((g) => (<Chip key={g} active={gangF === g} onClick={() => setGangF(gangF === g ? '' : g)}>{g}</Chip>))}
              </div>
            )}
            <div>
              <div className="flex items-center gap-2">
                <span className="w-16 shrink-0 label-mono font-bold text-muted2">Küche</span>
                <div className="relative flex-1">
                  <input className={input + ' w-full py-1 text-sm'} placeholder="Küche suchen…" value={kuecheEingabe} onChange={(e) => setKuecheEingabe(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); const m = kuecheMatches[0]; if (m) { setKuecheF(m.wert); setKuecheEingabe('') } } }} />
                  {kuecheMatches.length > 0 && (
                    <div className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-xl border border-line bg-card shadow-soft">
                      {kuecheMatches.map((m) => (<button key={m.wert} onClick={() => { setKuecheF(m.wert); setKuecheEingabe('') }} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-olive/10"><span>{m.wert}</span><span className="text-xs text-muted2">{m.anzahl}</span></button>))}
                    </div>
                  )}
                </div>
              </div>
              {kuecheF && (<div className="mt-1.5 flex flex-wrap items-center gap-1.5"><span className="inline-flex items-center gap-1 rounded-full bg-olive/15 px-2 py-0.5 text-xs font-semibold text-olive">{kuecheF}<button onClick={() => setKuecheF('')} className="text-olive/60 hover:text-olive"><Icon name="x" size={16} /></button></span></div>)}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="w-16 shrink-0 label-mono font-bold text-muted2">Zutaten</span>
                <div className="relative flex-1">
                  <input className={input + ' w-full py-1 text-sm'} placeholder="Zutat suchen…" value={zutEingabe} onChange={(e) => setZutEingabe(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); const m = zutMatches[0]; if (m) { setZutatenF([...new Set([...zutatenF, m.name])]); setZutEingabe('') } } }} />
                  {zutMatches.length > 0 && (
                    <div className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-xl border border-line bg-card shadow-soft">
                      {zutMatches.map((m) => (<button key={m.id} onClick={() => { setZutatenF([...new Set([...zutatenF, m.name])]); setZutEingabe('') }} className="block w-full px-3 py-1.5 text-left text-sm hover:bg-olive/10">{m.name}</button>))}
                    </div>
                  )}
                </div>
              </div>
              {zutatenF.length > 0 && (<div className="mt-1.5 flex flex-wrap items-center gap-1.5">{zutatenF.map((z) => (<span key={z} className="inline-flex items-center gap-1 rounded-full bg-olive/15 px-2 py-0.5 text-xs font-semibold text-olive">{z}<button onClick={() => setZutatenF(zutatenF.filter((x) => x !== z))} className="text-olive/60 hover:text-olive"><Icon name="x" size={16} /></button></span>))}<span className="text-[11px] text-muted2">(alle müssen vorkommen)</span></div>)}
            </div>
            {maerkte.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-16 shrink-0 label-mono font-bold text-muted2">Angebote</span>
                <select className={input + ' max-w-[14rem] py-1 text-sm'} value={marktF} onChange={(e) => setMarktF(e.target.value)}>
                  <option value="">— kein Markt —</option>
                  {maerkte.map((m) => { const h = typeof m === 'string' ? m : (m.haendler || m.name); return <option key={h} value={h}>{h}</option> })}
                </select>
                {marktF && <span className="text-[11px] text-muted2">sortiert nach {vorratAktiv ? 'Angeboten + Vorrat' : 'Angeboten'}</span>}
              </div>
            )}
            <div className="flex justify-end pt-1"><Button onClick={() => setFilterOffen(false)}>Fertig</Button></div>
          </div>
        </Modal>
      )}

      {/* Rezept-Detail */}
      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.name || ''}>
        {detail && (
          <div className="space-y-4">
            {detail.beschreibung && <p className="text-sm text-muted">{detail.beschreibung}</p>}
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {detail.dauer_minuten ? <span className="rounded-full bg-surface px-2.5 py-1 font-mono text-xs text-muted">{detail.dauer_minuten} MIN</span> : null}
              {detail.geraete?.map((g) => (
                <span key={g.geraet_id} className="rounded-full bg-olive/15 px-2.5 py-1 text-olive">{g.geraet}</span>
              ))}
              {detail.veroeffentlicht && (
                <span className="inline-flex items-center gap-1 rounded-full bg-terracotta/15 px-2.5 py-1 font-semibold text-terracotta-deep"><Icon name="megaphone" size={16} /> Veröffentlicht</span>
              )}
              <button onClick={() => setDetailMenu(true)} className="ml-auto inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:border-terracotta/40 hover:text-terracotta"><Icon name="menu" size={16} /> Mehr</button>
            </div>

            {/* Rezeptbild (Aktionen liegen im „Mehr"-Sheet) */}
            {detail.bild
              ? <img src={detail.bild} alt={detail.name} className="aspect-square w-full rounded-xl object-cover" />
              : (detail.account_id === meinKonto && (
                  <div className="flex items-stretch gap-2">
                    <Button variant="kiGhost" className="flex-1 py-3.5 text-base" onClick={bildGenerieren} disabled={bildBusy}>{bildBusy ? <Spinner /> : <span className="inline-flex items-center gap-1"><Icon name="sparkles" size={16} /> Bild hinzufügen</span>}</Button>
                    <Button variant="ghost" className="flex-1 py-3.5 text-base" onClick={() => bildRef.current?.click()} disabled={bildBusy}><span className="inline-flex items-center gap-1"><Icon name="camera" size={16} /> Eigenes Bild</span></Button>
                  </div>
                ))}
            <input ref={bildRef} type="file" accept="image/*" className="hidden" onChange={bildUpload} />

            {/* „Für wen" – kompakt & einklappbar (weniger prominent) */}
            <div>
              <button onClick={() => setPortionenOffen((o) => !o)}
                className="flex w-full items-center justify-between gap-2 rounded-xl border border-line bg-card/50 px-3 py-2 text-sm transition hover:border-terracotta/40">
                <span className="inline-flex items-center gap-1.5 text-muted"><Icon name="users" size={16} /> Für <b className="text-ink">{fmt(kochPortionen)}</b> Portion{kochPortionen !== 1 ? 'en' : ''}</span>
                <span className="inline-flex items-center gap-1 text-xs font-semibold text-terracotta">{portionenOffen ? 'Fertig' : 'anpassen'} <Icon name={portionenOffen ? 'chevron-left' : 'chevron-right'} size={14} /></span>
              </button>
              {portionenOffen && (
                <div className="mt-2">
                  <PortionenWahl onChange={({ portionen }) => setKochPortionen(Math.max(1, Math.round((portionen || 1) * 100) / 100))} />
                  {detail.portionen && <p className="mt-1 text-right text-xs text-muted2">Rezept-Basis: {detail.portionen} Portionen</p>}
                </div>
              )}
            </div>

            {/* Zutaten mit Vorrat-Check */}
            <div>
              <div className="mb-1 flex items-center gap-2">
                <h4 className="label-mono font-bold text-muted2">Zutaten</h4>
                {vorratAktiv && !vorratCheck && <Spinner />}
              </div>
              <ul className="text-sm">
                {detail.zutaten?.map((z) => {
                  const faktor = kochPortionen / (detail.portionen || 1)
                  const scaled = z.menge != null ? z.menge * faktor : null
                  const ci = vorratCheck?.zutaten?.find((c) => c.zutat_id === z.zutat_id)
                  let status = ci
                    ? ci.vorhanden_menge === null
                      ? 'fehlt'
                      : (ci.vorhanden_einheit || '').toLowerCase() === (ci.einheit || '').toLowerCase()
                        ? ci.vorhanden_menge >= (scaled || 0) ? 'ok' : 'knapp'
                        : ci.status === 'aehnlich' ? 'aehnlich' : 'vorhanden'
                    : null
                  const optional = z.optional
                  return (
                    <li key={z.zutat_id} className="flex items-start justify-between gap-2 border-b border-line/60 py-1.5">
                      <span className="flex items-center gap-1.5">
                        {(status === 'ok' || status === 'vorhanden') && <Icon name="check" size={16} className="text-olive" />}
                        {(status === 'knapp' || status === 'aehnlich') && <Icon name="alert-triangle" size={16} className="text-terracotta" />}
                        {status === 'fehlt' && !optional && <Icon name="x" size={16} className="text-terracotta-deep" />}
                        <span className={optional ? 'text-muted2' : ''}>{z.zutat}{optional ? ' (opt.)' : ''}</span>
                        {angebotMark[z.zutat_id] && (
                          <span title={`Im Angebot${angebotMark[z.zutat_id].haendler ? ' bei ' + angebotMark[z.zutat_id].haendler : ''}`}
                            className="inline-flex items-center gap-0.5 rounded-full bg-terracotta/15 px-1.5 py-0.5 text-[10px] font-bold text-terracotta"><Icon name="tag" size={16} /> Angebot</span>
                        )}
                      </span>
                      <span className="flex flex-col items-end text-right text-muted">
                        {scaled != null ? <span className="font-medium">{fmt(scaled)} {z.einheit}</span> : null}
                        {ci && (() => {
                          const sameUnit = (ci.vorhanden_einheit || '').toLowerCase() === (z.einheit || '').toLowerCase()
                          const rem = sameUnit && ci.vorhanden_menge != null ? ci.vorhanden_menge - (scaled || 0) : null
                          if (status === 'fehlt') return <span className="text-xs text-terracotta-deep">nicht vorhanden</span>
                          if (status === 'aehnlich') return <span className="text-xs text-muted2">≈ {ci.matched_name}</span>
                          if (!sameUnit && ci.vorhanden_menge != null) return <span className="text-xs text-muted2">{fmt(ci.vorhanden_menge)} {ci.vorhanden_einheit} da</span>
                          if (rem != null && rem >= 0) return <span className="text-xs text-olive/80">danach noch {fmt(rem)} {z.einheit}</span>
                          if (rem != null) return <span className="text-xs text-terracotta font-semibold">fehlt {fmt(-rem)} {z.einheit}</span>
                          return null
                        })()}
                      </span>
                    </li>
                  )
                })}
              </ul>
              {vorratAktiv && vorratCheck && (
                <button
                  onClick={fehlendeAufEinkaufsliste}
                  disabled={einkaufBusy}
                  className="mt-2 w-full rounded-xl border border-terracotta/40 px-3 py-2 text-sm font-semibold text-terracotta hover:bg-terracotta/10 disabled:opacity-50"
                >
                  <span className="inline-flex items-center justify-center gap-1"><Icon name="shopping-cart" size={16} /> {einkaufBusy ? '…' : 'Fehlende Zutaten auf die Einkaufsliste'}</span>
                </button>
              )}
              {!vorratAktiv && (
                <button
                  onClick={alleAufEinkaufsliste}
                  disabled={einkaufBusy}
                  className="mt-2 w-full rounded-xl border border-terracotta/40 px-3 py-2 text-sm font-semibold text-terracotta hover:bg-terracotta/10 disabled:opacity-50"
                >
                  <span className="inline-flex items-center justify-center gap-1"><Icon name="shopping-cart" size={16} /> {einkaufBusy ? '…' : 'Zutaten auf die Einkaufsliste'}</span>
                </button>
              )}
            </div>
            {/* Großer Haupt-Button direkt unter den Zutaten */}
            {detail.account_id != null && detail.account_id === auth?.account?.id ? (
              <Button variant="ki" className="w-full py-5 text-lg" onClick={() => setKochPlanSheet(true)}>
                <span className="inline-flex items-center gap-2"><Icon name="chef-hat" size={20} /> Loslegen</span>
              </Button>
            ) : (
              <Button variant="primary" className="w-full py-5 text-lg" onClick={() => importiere(detail)} disabled={importBusyId !== null}>
                <span className="inline-flex items-center gap-2"><Icon name="download" size={20} /> {importBusyId === detail.id ? 'wird übernommen …' : 'In meine Bibliothek übernehmen'}</span>
              </Button>
            )}
            {guidedOffen && (
              <GuidedCooking
                detail={detail}
                portionen={kochPortionen}
                heuteNamen={heuteNamen}
                notify={notify}
                onClose={() => setGuidedOffen(false)}
              />
            )}
            {/* Zubereitung als Referenz darunter */}
            {detail.zubereitung && detail.zubereitung.length > 0 ? (
              <div>
                <h4 className="mb-2 label-mono font-bold text-muted2">Zubereitung</h4>
                <ZubereitungAnsicht key={detail.id} komponenten={detail.zubereitung} heuteNamen={heuteNamen} />
              </div>
            ) : (
              detail.anleitung && (
                <div>
                  <h4 className="mb-1 label-mono font-bold text-muted2">Zubereitung</h4>
                  <p className="whitespace-pre-wrap text-sm text-ink/80">{detail.anleitung.replace(/\\n/g, '\n')}</p>
                </div>
              )
            )}
          </div>
        )}
      </Modal>

      {/* „Loslegen" – Jetzt kochen / Einplanen */}
      <Modal open={kochPlanSheet} onClose={() => setKochPlanSheet(false)} title="Loslegen">
        {detail && (
          <div className="grid gap-3">
            <button onClick={() => { setKochPlanSheet(false); (detail.zubereitung?.length > 0 || (detail.anleitung || '').trim()) ? setGuidedOffen(true) : starteKochen() }}
              className="flex items-center gap-3 rounded-2xl bg-terracotta p-4 text-left text-on-accent shadow-soft transition hover:bg-terracotta-deep active:scale-[0.99]">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15"><Icon name="chef-hat" size={22} /></span>
              <span><span className="block font-bold">Jetzt kochen</span><span className="block text-sm text-white/80">Schritt für Schritt durchs Rezept</span></span>
            </button>
            <button onClick={() => { setKochPlanSheet(false); oeffnePlan(detail) }}
              className="flex items-center gap-3 rounded-2xl border border-line bg-card p-4 text-left transition hover:border-terracotta/40 active:scale-[0.99]">
              <Icon name="calendar" size={22} className="shrink-0 text-terracotta" />
              <span><span className="block font-bold">Einplanen</span><span className="block text-sm text-muted2">In den Wochenplan legen</span></span>
            </button>
          </div>
        )}
      </Modal>

      {/* „Mehr" – Sekundär-Aktionen zum Rezept */}
      <Modal open={detailMenu} onClose={() => setDetailMenu(false)} title="Mehr">
        {detail && (
          <div className="space-y-3">
            <div className="grid gap-2">
              <button onClick={() => { setDetailMenu(false); teilen() }} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40"><Icon name="upload" size={18} className="text-muted" /> Teilen</button>
              {/* Drucken braucht window.open – das liefert in der Android-WebView kein Fenster. */}
              {!IST_NATIVE && <button onClick={() => { setDetailMenu(false); druckePdf() }} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40"><Icon name="printer" size={18} className="text-muted" /> Als PDF</button>}
              {detail.account_id === meinKonto && detail.bild && (
                <>
                  <button onClick={() => { setDetailMenu(false); bildGenerieren() }} disabled={bildBusy} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40 disabled:opacity-50"><Icon name="sparkles" size={18} className="text-terracotta" /> Neues KI-Bild</button>
                  <button onClick={() => { setDetailMenu(false); bildRef.current?.click() }} disabled={bildBusy} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40 disabled:opacity-50"><Icon name="camera" size={18} className="text-muted" /> Eigenes Bild</button>
                  <button onClick={() => { setDetailMenu(false); bildLoeschen() }} disabled={bildBusy} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold text-terracotta-deep hover:border-terracotta/40 disabled:opacity-50"><Icon name="trash" size={18} /> Bild entfernen</button>
                </>
              )}
              {detail.account_id === meinKonto && detail.zubereitung?.length > 0 && !detail.geraete_abgestimmt && (
                <button onClick={() => { setDetailMenu(false); anpassenEines() }} disabled={anpassBusy} className="flex items-center gap-2 rounded-xl border border-terracotta/50 bg-terracotta/5 px-3 py-2.5 text-left text-sm font-semibold text-terracotta hover:bg-terracotta/10 disabled:opacity-50"><Icon name="wrench" size={18} /> An deine Küche anpassen</button>
              )}
              {istAdmin && !(detail.importiert && !detail.veroeffentlicht) && (
                <button onClick={() => { setDetailMenu(false); freigeben(!detail.veroeffentlicht) }} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40"><Icon name="globe" size={18} className="text-muted" /> {detail.veroeffentlicht ? 'Freigabe zurückziehen' : 'Öffentlich freigeben'}</button>
              )}
              {!istAdmin && detail.veroeffentlicht && detail.account_id === meinKonto && (
                <button onClick={() => { setDetailMenu(false); freigeben(false) }} className="flex items-center gap-2 rounded-xl border border-line bg-card px-3 py-2.5 text-left text-sm font-semibold hover:border-terracotta/40"><Icon name="globe" size={18} className="text-muted" /> Wieder auf privat schalten</button>
              )}
            </div>

            {/* Bewertung */}
            <div className="rounded-xl border border-line p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h4 className="label-mono font-bold text-muted2">Bewertung</h4>
                {detail.bewertung_anzahl > 0 && (
                  <span className="text-sm"><Icon name="star" size={16} fill="currentColor" style={{ color: STERN_VOLL }} className="inline align-text-bottom" /> <b>{Number(detail.bewertung_schnitt).toFixed(1).replace('.', ',')}</b><span className="text-xs text-muted2"> · {detail.bewertung_anzahl} {detail.bewertung_anzahl === 1 ? 'Bewertung' : 'Bewertungen'}</span></span>
                )}
              </div>
              <Sternebewertung sterne={bewertungSterne} onChange={setBewertungSterne} />
              {bewertungSterne > 0 && (
                <div className="mt-2.5 space-y-2">
                  <input className={input} placeholder="Notiz (optional)" value={bewertungKommentar} onChange={(e) => setBewertungKommentar(e.target.value)} />
                  <div className="flex items-center gap-3">
                    <Button onClick={speicherBewertung}>Speichern</Button>
                    {detail.bewertung && (<button onClick={loescheBewertung} className="text-sm text-muted2 hover:text-terracotta-deep">Entfernen</button>)}
                  </div>
                </div>
              )}
            </div>

            {detail.account_id != null && detail.account_id === auth?.account?.id && (
              <div className="flex gap-2">
                <Button variant="ghost" className="flex-1" onClick={() => { setDetailMenu(false); setEdit(detail); setDetail(null) }}>Bearbeiten</Button>
                <Button variant="ghost" className="flex-1 text-terracotta-deep" onClick={() => { setDetailMenu(false); loeschenRezept() }}>Löschen</Button>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Koch-Bestätigung / Vorratsabzug */}
      <Modal open={!!kochen} onClose={() => setKochen(null)} title="Aus dem Vorrat abziehen?">
        {kochen && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted">Portionen-Faktor</span>
              <input
                className={input + ' !w-24'}
                type="number"
                step="0.5"
                min="0.5"
                value={kochen.faktor}
                onChange={(e) => setKochen({ ...kochen, faktor: e.target.value })}
              />
            </div>
            {kochen.vorschau.abzug.length === 0 ? (
              <Empty>Keine Zutaten mit Mengen hinterlegt.</Empty>
            ) : (
              <ul className="text-sm">
                {kochen.vorschau.abzug.map((a) => (
                  <li key={a.zutat_id} className="flex justify-between border-b border-line/60 py-1.5">
                    <span>{a.zutat}</span>
                    <span className="text-muted">{fmt((Number(a.menge) || 0) * (Number(kochen.faktor) || 1))} {a.einheit}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setKochen(null)}>Nein</Button>
              <Button onClick={bestaetigeKochen}>Ja, abziehen</Button>
            </div>
          </div>
        )}
      </Modal>

      {!detailOnly && genOffen && (
        <Generator notify={notify} vorratAktiv={vorratAktiv}
          openRezept={(id) => { setGenOffen(false); oeffne(id) }}
          onClose={() => { setGenOffen(false); lade() }} />
      )}
      {!detailOnly && (add || edit) && (
        <RezeptForm
          notify={notify}
          kategorien={kategorien}
          rezept={edit}
          onClose={() => { setAdd(false); setEdit(null) }}
          onSaved={() => { setAdd(false); setEdit(null); lade(q) }}
        />
      )}

      {/* Rezept importieren – Link (Webseite/Social Media), Text, Screenshots/Fotos oder PDF.
          Bewusst OHNE Plattform-Markennamen in der UI (Urheber-/Markenrecht) – die Funktion
          selbst bleibt generisch für beliebige Quellen. */}
      <Modal open={linkOffen} onClose={() => { if (!linkBusy) { setLinkOffen(false); setLinkUrl(''); setLinkDateien([]) } }} title="Rezept importieren">
        <div className="space-y-3">
          <p className="text-sm text-muted">
            Füge eine Quelle ein – ich erkenne das Rezept und lege es an:
          </p>
          <ul className="-mt-1 space-y-0.5 text-sm text-muted">
            <li className="flex items-center gap-1.5"><Icon name="link" size={16} /> <span><b>Link</b> zu einem Rezept (Webseite oder Blog)</span></li>
            <li className="flex items-center gap-1.5"><Icon name="smartphone" size={16} /> <span><b>Social-Media</b>-Beitrag oder -Reel</span></li>
            <li className="flex items-center gap-1.5"><Icon name="image" size={16} /> <span><b>Screenshots/Fotos</b> oder <b>PDF</b> (mehrere möglich)</span></li>
            <li className="flex items-center gap-1.5"><Icon name="edit" size={16} /> <span>oder den <b>Rezepttext</b> direkt einfügen</span></li>
          </ul>
          <textarea
            className={input + ' min-h-[90px] w-full'}
            placeholder="https://… oder Rezepttext hier einfügen"
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
          />
          <input ref={linkFileRef} type="file" accept="image/*,application/pdf" multiple className="hidden" onChange={linkDateienWaehlen} />
          <button
            onClick={() => linkFileRef.current?.click()}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line px-3 py-2.5 text-sm font-semibold text-muted hover:border-terracotta/40 hover:text-terracotta"
          >
            <Icon name="image" size={16} /> Screenshots / Fotos / PDF hinzufügen
          </button>
          {linkDateien.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {linkDateien.map((d, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full border border-line bg-card px-2.5 py-1 text-xs">
                  {d.media_type === 'application/pdf' || /\.pdf$/i.test(d.name) ? <Icon name="file-text" size={16} /> : <Icon name="image" size={16} />} <span className="max-w-[10rem] truncate">{d.name || 'Datei'}</span>
                  <button onClick={() => setLinkDateien((a) => a.filter((_, j) => j !== i))} className="text-muted2 hover:text-terracotta"><Icon name="x" size={16} /></button>
                </span>
              ))}
            </div>
          )}
          <p className="text-xs text-muted2">
            Steht ein Rezept nur im Video, mach einfach einen Screenshot davon. Mehrere Seiten/Fotos werden zusammen ausgewertet.
          </p>
          <p className="text-xs text-muted2">
            Importierte Rezepte bleiben privat in deiner Bibliothek und können nicht veröffentlicht werden.
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => { setLinkOffen(false); setLinkUrl(''); setLinkDateien([]) }} disabled={linkBusy}>Abbrechen</Button>
            <Button variant="ki" onClick={importiereLink} disabled={linkBusy || (!linkUrl.trim() && linkDateien.length === 0)}>{linkBusy ? <Spinner /> : 'Importieren'}</Button>
          </div>
        </div>
      </Modal>

      {/* In die Essensplanung aufnehmen */}
      <Modal open={!!planFor} onClose={() => setPlanFor(null)} title={planFor ? `„${planFor.name}" einplanen` : ''}>
        {planFor && (
          <div className="space-y-3">
            <Field label="Tag">
              <input className={input} type="date" value={planDatum} onChange={(e) => setPlanDatum(e.target.value)} />
            </Field>
            <Field label="Mahlzeit">
              <select className={input} value={planMahlzeit} onChange={(e) => setPlanMahlzeit(e.target.value)}>
                {MAHLZEITEN.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </Field>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setPlanFor(null)}>Abbrechen</Button>
              <Button onClick={einplanen} disabled={planBusy}>{planBusy ? <Spinner /> : 'Einplanen'}</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function RezeptForm({ notify, onClose, onSaved, rezept, kategorien = { gaenge: [], kuechen: [] } }) {
  const editing = !!rezept
  const [geraete, setGeraete] = useState([])
  const [selG, setSelG] = useState(() => new Set((rezept?.geraete || []).map((g) => g.geraet_id)))
  const [f, setF] = useState(() => ({
    name: rezept?.name || '',
    beschreibung: rezept?.beschreibung || '',
    anleitung: rezept?.anleitung || '',
    portionen: rezept?.portionen ?? 2,
    dauer_minuten: rezept?.dauer_minuten ?? '',
    quelle: rezept?.quelle || '',
    gang: rezept?.gang || '',
    kueche: rezept?.kueche || '',
  }))
  const [zutaten, setZutaten] = useState(() => {
    const zs = (rezept?.zutaten || []).map((z) => ({
      name: z.zutat, menge: z.menge ?? '', einheit: z.einheit || '', optional: !!z.optional,
    }))
    return zs.length ? zs : [{ name: '', menge: '', einheit: '', optional: false }]
  })

  const [alleZutaten, setAlleZutaten] = useState([])
  useEffect(() => {
    api.geraete().then(setGeraete).catch(() => {})
    api.zutaten().then(setAlleZutaten).catch(() => {})
  }, [])

  const setZ = (i, patch) => setZutaten((z) => z.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const addZ = () => setZutaten((z) => [...z, { name: '', menge: '', einheit: '', optional: false }])
  const rmZ = (i) => setZutaten((z) => z.filter((_, j) => j !== i))

  const [komp, setKomp] = useState(() =>
    (rezept?.zubereitung || []).map((k) => ({
      titel: k.titel || '',
      varianten: (k.varianten || []).map((v) => ({ geraet: v.geraet || '', text: v.text || '' })),
    })),
  )
  const addKomponente = () => setKomp((ks) => [...ks, { titel: '', varianten: [{ geraet: '', text: '' }] }])
  const rmKomponente = (i) => setKomp((ks) => ks.filter((_, j) => j !== i))
  const setKompTitel = (i, titel) => setKomp((ks) => ks.map((x, j) => (j === i ? { ...x, titel } : x)))
  const setVariante = (ki, vi, patch) =>
    setKomp((ks) => ks.map((k, j) => (j === ki
      ? { ...k, varianten: k.varianten.map((v, m) => (m === vi ? { ...v, ...patch } : v)) }
      : k)))
  const addVariante = (ki) =>
    setKomp((ks) => ks.map((k, j) => (j === ki ? { ...k, varianten: [...k.varianten, { geraet: '', text: '' }] } : k)))
  const rmVariante = (ki, vi) =>
    setKomp((ks) => ks.map((k, j) => (j === ki ? { ...k, varianten: k.varianten.filter((_, m) => m !== vi) } : k)))

  async function speichern() {
    if (!f.name.trim()) {
      notify('Name nötig', 'err')
      return
    }
    const payload = {
      name: f.name.trim(),
      beschreibung: f.beschreibung || null,
      anleitung: f.anleitung || null,
      portionen: Number(f.portionen) || 2,
      dauer_minuten: f.dauer_minuten ? Number(f.dauer_minuten) : null,
      quelle: f.quelle || null,
      gang: f.gang || null,
      kueche: f.kueche || null,
      zutaten: zutaten
        .filter((z) => z.name.trim())
        .map((z) => ({
          name: z.name.trim(),
          menge: z.menge !== '' ? Number(z.menge) : null,
          einheit: z.einheit || null,
          optional: !!z.optional,
        })),
      geraete: [...selG].map((id) => ({ geraet_id: id, pflicht: true })),
      zubereitung: komp
        .map((k) => ({
          titel: k.titel.trim(),
          varianten: k.varianten
            .filter((v) => v.text.trim())
            .map((v) => ({ geraet: v.geraet || null, text: v.text })),
        }))
        .filter((k) => k.varianten.length > 0),
    }
    try {
      if (editing) await api.rezeptUpdate(rezept.id, payload)
      else await api.rezeptAnlegen(payload)
      notify(editing ? 'Rezept aktualisiert' : 'Rezept gespeichert')
      onSaved()
    } catch {
      notify('Speichern fehlgeschlagen', 'err')
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? 'Rezept bearbeiten' : 'Neues Rezept'}>
      <div className="space-y-3">
        <Field label="Name"><input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Beschreibung"><input className={input} value={f.beschreibung} onChange={(e) => setF({ ...f, beschreibung: e.target.value })} /></Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Portionen"><input className={input} type="number" value={f.portionen} onChange={(e) => setF({ ...f, portionen: e.target.value })} /></Field>
          <Field label="Dauer (min)"><input className={input} type="number" value={f.dauer_minuten} onChange={(e) => setF({ ...f, dauer_minuten: e.target.value })} /></Field>
          <Field label="Quelle"><input className={input} value={f.quelle} onChange={(e) => setF({ ...f, quelle: e.target.value })} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Gang">
            <select className={input} value={f.gang} onChange={(e) => setF({ ...f, gang: e.target.value })}>
              <option value="">—</option>
              {(kategorien.gaenge || []).map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </Field>
          <Field label="Küche">
            <select className={input} value={f.kueche} onChange={(e) => setF({ ...f, kueche: e.target.value })}>
              <option value="">—</option>
              {(kategorien.kuechen || []).map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>
        </div>

        <div>
          <h4 className="mb-1 label-mono font-bold text-muted2">Zutaten</h4>
          <div className="space-y-2">
            {zutaten.map((z, i) => (
              <div key={i} className="space-y-2 rounded-xl border border-line p-2">
                <div className="flex items-center gap-2">
                  <ZutatInput
                    value={z.name}
                    alle={alleZutaten}
                    onChange={(v) => setZ(i, { name: v })}
                    onPick={(zt) => setZ(i, { name: zt.name, einheit: z.einheit || zt.standard_einheit || '' })}
                  />
                  <button onClick={() => rmZ(i)} className="shrink-0 rounded-full px-2 py-1 text-muted2 hover:bg-ink/5" aria-label="Entfernen"><Icon name="x" size={16} /></button>
                </div>
                <div className="flex items-center gap-2">
                  <input className={input} type="number" placeholder="Menge" value={z.menge} onChange={(e) => setZ(i, { menge: e.target.value })} />
                  <input className={input} placeholder="Einheit" value={z.einheit} onChange={(e) => setZ(i, { einheit: e.target.value })} />
                  <label className="flex shrink-0 items-center gap-1.5 text-sm text-muted">
                    <input type="checkbox" checked={z.optional} onChange={(e) => setZ(i, { optional: e.target.checked })} className="h-4 w-4 accent-[var(--terracotta)]" />
                    optional
                  </label>
                </div>
              </div>
            ))}
          </div>
          <button onClick={addZ} className="mt-2 text-sm font-bold text-terracotta hover:underline">+ Zutat</button>
        </div>

        <div>
          <h4 className="mb-1 label-mono font-bold text-muted2">Benötigte Geräte</h4>
          <div className="flex flex-wrap gap-2">
            {geraete.map((g) => (
              <Chip
                key={g.id}
                active={selG.has(g.id)}
                onClick={() =>
                  setSelG((s) => {
                    const n = new Set(s)
                    n.has(g.id) ? n.delete(g.id) : n.add(g.id)
                    return n
                  })
                }
              >
                {g.name}
              </Chip>
            ))}
            {geraete.length === 0 && <span className="text-sm text-muted2">Keine Geräte angelegt.</span>}
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <h4 className="label-mono font-bold text-muted2">Zubereitung nach Gerät</h4>
            <button onClick={addKomponente} className="text-sm font-bold text-terracotta hover:underline">+ Komponente</button>
          </div>
          <p className="mb-2 text-xs text-muted2">
            Pro Schritt (z.B. „Reis") mehrere Geräte-Varianten anlegen. Angezeigt wird später automatisch die passende.
          </p>
          <div className="space-y-3">
            {komp.map((k, ki) => (
              <div key={ki} className="rounded-xl border border-line p-3">
                <div className="mb-2 flex items-center gap-2">
                  <input className={input} placeholder="Komponente (z.B. Reis)" value={k.titel} onChange={(e) => setKompTitel(ki, e.target.value)} />
                  <button onClick={() => rmKomponente(ki)} className="shrink-0 rounded-full px-2 py-1 text-muted2 hover:bg-ink/5" aria-label="Komponente entfernen"><Icon name="x" size={16} /></button>
                </div>
                <div className="space-y-2">
                  {k.varianten.map((v, vi) => (
                    <div key={vi} className="rounded-lg bg-paper/50 p-2">
                      <div className="mb-1.5 flex items-center gap-2">
                        <select className={input + ' max-w-[12rem]'} value={v.geraet} onChange={(e) => setVariante(ki, vi, { geraet: e.target.value })}>
                          <option value="">ohne Gerät</option>
                          {geraete.map((g) => <option key={g.id} value={g.name}>{g.name}</option>)}
                        </select>
                        <button onClick={() => rmVariante(ki, vi)} className="shrink-0 rounded-full px-2 py-1 text-muted2 hover:bg-ink/5" aria-label="Variante entfernen"><Icon name="x" size={16} /></button>
                      </div>
                      <textarea className={input + ' min-h-[70px] resize-y'} placeholder="Zubereitungstext für dieses Gerät" value={v.text} onChange={(e) => setVariante(ki, vi, { text: e.target.value })} />
                    </div>
                  ))}
                  <button onClick={() => addVariante(ki)} className="text-xs font-bold text-terracotta hover:underline">+ Variante</button>
                </div>
              </div>
            ))}
            {komp.length === 0 && <p className="text-sm text-muted2">Noch keine Komponenten – „+ Komponente" für geräteabhängige Schritte, oder unten Freitext nutzen.</p>}
          </div>
        </div>

        <Field label="Zubereitung (Freitext, Fallback)">
          <textarea className={input + ' min-h-[110px] resize-y'} value={f.anleitung} onChange={(e) => setF({ ...f, anleitung: e.target.value })} />
        </Field>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button onClick={speichern}>Speichern</Button>
        </div>
      </div>
    </Modal>
  )
}

// Lazy-geladenes Vorschaubild für eine Rezeptkachel (Bild owner-only via API).
const _bildCache = {}
const _bildSubs = new Set()
// Bild eines Rezepts setzen + ALLE gemounteten Thumbnails dieses Rezepts live updaten
// (z.B. Startseiten-Kachel, während das Rezept im Overlay geöffnet ist).
export function setBild(id, bild) {
  _bildCache[id] = bild || null
  _bildSubs.forEach((fn) => { try { fn(id) } catch { /* ignore */ } })
}
export function RezeptThumb({ id, hatBild, bump }) {
  const [src, setSrc] = useState(() => (_bildCache[id] !== undefined ? _bildCache[id] : null))
  const [loading, setLoading] = useState(hatBild && _bildCache[id] === undefined)
  useEffect(() => {
    // Live-Update: reagiert, wenn das Bild dieses Rezepts geändert wird (setBild).
    const fn = (changedId) => { if (changedId === id) { setSrc(_bildCache[id] ?? null); setLoading(false) } }
    _bildSubs.add(fn)
    return () => { _bildSubs.delete(fn) }
  }, [id])
  useEffect(() => {
    let ok = true
    // Cache kennt das Bild (auch null = bewusst keins) -> direkt nutzen, auch wenn hatBild=false
    // (so erscheint ein frisch generiertes Bild ohne Reload).
    if (_bildCache[id] !== undefined) { setSrc(_bildCache[id]); setLoading(false); return }
    if (!hatBild) { setSrc(null); setLoading(false); return }
    setLoading(true)
    api.rezeptBild(id)
      .then((r) => { if (ok) { _bildCache[id] = r?.bild || null; setSrc(r?.bild || null); setLoading(false) } })
      .catch(() => { if (ok) setLoading(false) })
    return () => { ok = false }
  }, [id, hatBild, bump])
  return (
    <div className="-mx-4 -mt-4 mb-3 flex aspect-[16/9] items-center justify-center overflow-hidden rounded-t-2xl bg-ink/5">
      {src
        ? <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
        : loading
          ? <div className="h-full w-full animate-pulse bg-ink/10" />
          : <img src="/rezept-platzhalter.jpg" alt="" loading="lazy" className="h-full w-full object-cover" />}
    </div>
  )
}

// Zutat-Eingabe mit Autovervollständigung: durchsucht bestehende Zutaten
// (global bevorzugt), Dropdown zur Auswahl. Bei Enter ohne exakten Treffer
// wird gefragt, ob die Zutat neu angelegt werden soll.
function ZutatInput({ value, alle, onChange, onPick }) {
  const [open, setOpen] = useState(false)
  const q = (value || '').trim().toLowerCase()

  const matches = useMemo(() => {
    if (!q) return []
    const m = (alle || []).filter((z) => (z.name || '').toLowerCase().includes(q))
    m.sort((a, b) => {
      const ap = a.name.toLowerCase().startsWith(q) ? 0 : 1
      const bp = b.name.toLowerCase().startsWith(q) ? 0 : 1
      if (ap !== bp) return ap - bp                       // Präfix zuerst
      const ag = a.account_id == null ? 0 : 1
      const bg = b.account_id == null ? 0 : 1
      if (ag !== bg) return ag - bg                       // global vor eigene
      return a.name.length - b.name.length
    })
    return m.slice(0, 8)
  }, [q, alle])

  const exact = (alle || []).find((z) => (z.name || '').toLowerCase() === q)

  function pick(z) { onPick(z); setOpen(false) }

  async function onKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (exact) { setOpen(false); return }              // exakte Zutat -> übernehmen
      if (!q) return
      const ok = await confirmDialog({
        title: 'Neue Zutat?',
        message: `„${value.trim()}" ist noch nicht in der Zutatenliste.\n\nAls neue Zutat anlegen?`,
        confirmLabel: 'Neu anlegen',
      })
      if (ok) setOpen(false)                              // Name bleibt -> wird beim Speichern angelegt
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative flex-1">
      <input
        className={input + ' w-full'}
        placeholder="Zutat"
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {open && matches.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-xl border border-line bg-card shadow-soft">
          {matches.map((z) => (
            <li key={z.id}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(z)}
                className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-ink/5"
              >
                <span className="truncate capitalize">{z.name}</span>
                <span className="shrink-0 text-[11px] text-muted2">
                  {z.account_id == null ? 'global' : 'eigene'}{z.standard_einheit ? ` · ${z.standard_einheit}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
