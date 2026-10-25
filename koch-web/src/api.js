const BASE = import.meta.env.VITE_API_BASE || ''
const TOKEN_KEY = 'koch_token'

// Antwortet das Backend mit 503 {fehler:'ki_nicht_konfiguriert'}, ist die KI-Funktion auf
// dieser Instanz nicht eingerichtet → freundliche Meldung statt Rohfehler.
export const KI_NICHT_EINGERICHTET = 'Diese KI-Funktion ist auf diesem Server nicht eingerichtet.'
function kiFehler(status, body) {
  if (status === 503 && body && body.fehler === 'ki_nicht_konfiguriert') {
    const e = new Error(KI_NICHT_EINGERICHTET); e.status = 503; e.body = body; e.kiNichtEingerichtet = true
    // App zeigt die Meldung zentral und lädt /ki/status neu (s. App.jsx).
    try { window.dispatchEvent(new CustomEvent('koch:ki-fehlt', { detail: body })) } catch { /* ignore */ }
    return e
  }
  return null
}
// Fehlerbehandlung für die direkten fetch()-Aufrufe (Upload-Endpunkte).
async function fetchFehler(r, fallback) {
  let body = null
  try { if ((r.headers.get('content-type') || '').includes('application/json')) body = await r.json() } catch { /* ignore */ }
  const ki = kiFehler(r.status, body)
  if (ki) return ki
  const e = new Error((body && (body.meldung || body.fehler || body.detail)) || fallback); e.status = r.status; e.body = body
  return e
}

function getToken() { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } }
function setToken(t) { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } }
export function authHeader() { const t = getToken(); return t ? { Authorization: 'Bearer ' + t } : {} }

async function req(path, opts = {}) {
  const res = await fetch(BASE + '/api' + path, {
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...(opts.headers || {}) },
    ...opts,
  })
  if (!res.ok) {
    if (res.status === 401) { const e = new Error('nicht angemeldet'); e.status = 401; throw e }
    const ctErr = res.headers.get('content-type') || ''
    if (ctErr.includes('application/json')) {
      // strukturierter Fehler → body + status anhängen
      let body = null
      try { body = await res.json() } catch { /* ignore */ }
      const ki = kiFehler(res.status, body)
      if (ki) throw ki
      const e = new Error((body && (body.fehler || body.detail)) || res.statusText)
      e.status = res.status; e.body = body; throw e
    }
    let msg = res.statusText
    try { msg = (await res.text()) || msg } catch { /* ignore */ }
    const e = new Error(msg); e.status = res.status; throw e
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const api = {
  // Auth
  getToken,
  setToken,
  authMe: () => req('/auth/me'),
  authLogin: (email, password) => req('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  authRegister: (email, password, name) => req('/auth/register', { method: 'POST', body: JSON.stringify({ email, password, name }) }),
  authLogout: () => req('/auth/logout', { method: 'POST' }),
  passwortResetAnfordern: (email) => req('/auth/passwort-reset-anfordern', { method: 'POST', body: JSON.stringify({ email }) }),
  passwortReset: (token, password) => req('/auth/passwort-reset', { method: 'POST', body: JSON.stringify({ token, password }) }),
  emailVerifizieren: (token) => req('/auth/email-verifizieren', { method: 'POST', body: JSON.stringify({ token }) }),
  // Einladungen (Familienmitglieder)
  einladungen: () => req('/einladungen'),
  einladungErstellen: (email = '') => req('/einladungen', { method: 'POST', body: JSON.stringify({ email }) }),
  einladungStornieren: (id) => req('/einladungen/' + id, { method: 'DELETE' }),
  einladungInfo: (token) => req('/auth/einladung/' + encodeURIComponent(token)),
  einladungEinloesen: (token, name, password, email) =>
    req('/auth/einladung-einloesen', { method: 'POST', body: JSON.stringify({ token, name, password, email }) }),
  kontoLoeschen: (modus = 'selbst') => req('/konto/loeschen', { method: 'POST', body: JSON.stringify({ modus }) }),
  // Öffentliche Kontolöschung /konto-loeschen (ohne Login): erst Link anfordern,
  // dann per Bestätigungstoken aus der Mail ausführen – nie allein per E-Mail-Eingabe.
  kontoLoeschenAnfordern: (email) => req('/auth/konto-loeschen-anfordern', { method: 'POST', body: JSON.stringify({ email }) }),
  kontoLoeschenBestaetigen: (token) => req('/auth/konto-loeschen', { method: 'POST', body: JSON.stringify({ token }) }),
  adminUsers: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.limit != null) qs.set('limit', params.limit)
    if (params.offset != null) qs.set('offset', params.offset)
    if (params.sort) qs.set('sort', params.sort)
    const s = qs.toString()
    return req('/admin/users' + (s ? '?' + s : ''))
  },
  adminKennzahlen: () => req('/admin/kennzahlen'),
  adminUserUploadSetzen: (uid, erlaubt) => req('/admin/users/' + uid + '/angebote-upload', { method: 'PUT', body: JSON.stringify({ erlaubt }) }),
  adminUserKiSetzen: (uid, erlaubt) => req('/admin/users/' + uid + '/ki', { method: 'PUT', body: JSON.stringify({ erlaubt }) }),
  adminUserRolleSetzen: (uid, rolle) => req('/admin/users/' + uid + '/rolle', { method: 'PUT', body: JSON.stringify({ rolle }) }),
  adminUserAktivSetzen: (uid, aktiv) => req('/admin/users/' + uid + '/aktiv', { method: 'PUT', body: JSON.stringify({ aktiv }) }),

  // Bugreports
  bugreportSenden: (text, seite) => req('/bugreport', { method: 'POST', body: JSON.stringify({ text, seite }) }),
  adminBugreports: (nurOffen = false) => req('/admin/bugreports' + (nurOffen ? '?nur_offen=true' : '')),
  adminBugreportStatus: (id, status) => req('/admin/bugreports/' + id, { method: 'PUT', body: JSON.stringify({ status }) }),

  // Zutaten-Kuratierung (Super-Admin)
  adminZutatenKuratierung: () => req('/admin/zutaten-kuratierung'),
  adminZutatGlobal: (zid) => req('/admin/zutaten/' + zid + '/global', { method: 'POST' }),
  adminZutatMerge: (zid, zielId) => req('/admin/zutaten/' + zid + '/merge', { method: 'POST', body: JSON.stringify({ ziel_id: zielId }) }),
  adminZutatKuratieren: (zid, name) => req('/admin/zutaten/' + zid + '/kuratieren', { method: 'POST', body: JSON.stringify({ name }) }),
  // Geräte
  geraete: () => req('/geraete'),
  geraetAnlegen: (g) => req('/geraete', { method: 'POST', body: JSON.stringify(g) }),
  geraetUpdate: (id, g) => req('/geraete/' + id, { method: 'PUT', body: JSON.stringify(g) }),
  geraetLoeschen: (id) => req('/geraete/' + id, { method: 'DELETE' }),
  geraeteHeute: () => req('/geraete/heute'),
  setGeraeteHeute: (ids) => req('/geraete/heute', { method: 'PUT', body: JSON.stringify({ geraet_ids: ids }) }),

  // Personen / Haushalt
  personen: () => req('/personen'),
  personAnlegen: (p) => req('/personen', { method: 'POST', body: JSON.stringify(p) }),
  personUpdate: (id, p) => req('/personen/' + id, { method: 'PUT', body: JSON.stringify(p) }),
  personLoeschen: (id) => req('/personen/' + id, { method: 'DELETE' }),
  personNotizen: (pid) => req('/personen/' + pid + '/notizen'),
  personNotizAdd: (pid, text) => req('/personen/' + pid + '/notizen', { method: 'POST', body: JSON.stringify({ text }) }),
  personNotizLoeschen: (nid) => req('/personen/notizen/' + nid, { method: 'DELETE' }),
  chatMemory: () => req('/konto/chat-memory'),
  chatMemorySetzen: (aktiv) => req('/konto/chat-memory', { method: 'PUT', body: JSON.stringify({ aktiv }) }),
  autoBild: () => req('/konto/auto-bild'),
  autoBildSetzen: (aktiv) => req('/konto/auto-bild', { method: 'PUT', body: JSON.stringify({ aktiv }) }),
  personenHeute: () => req('/personen/heute'),
  abwesenheitRegeln: (pid) => req('/personen/' + pid + '/abwesenheit'),
  abwesenheitAnlegen: (pid, r) => req('/personen/' + pid + '/abwesenheit', { method: 'POST', body: JSON.stringify(r) }),
  abwesenheitLoeschen: (rid) => req('/personen/abwesenheit/' + rid, { method: 'DELETE' }),
  setPersonenHeute: (ids) => req('/personen/heute', { method: 'PUT', body: JSON.stringify({ person_ids: ids }) }),

  // Vorrat
  vorrat: () => req('/vorrat'),
  vorratHinzufuegen: (items) => req('/vorrat', { method: 'POST', body: JSON.stringify(items) }),
  vorratUpdate: (id, v) => req('/vorrat/' + id, { method: 'PUT', body: JSON.stringify(v) }),
  vorratLoeschen: (id) => req('/vorrat/' + id, { method: 'DELETE' }),

  // Lagerorte
  lagerorte: () => req('/lagerorte'),
  lagerortAnlegen: (l) => req('/lagerorte', { method: 'POST', body: JSON.stringify(l) }),
  lagerortUpdate: (id, l) => req('/lagerorte/' + id, { method: 'PUT', body: JSON.stringify(l) }),
  lagerortLoeschen: (id) => req('/lagerorte/' + id, { method: 'DELETE' }),
  lagerortVorratLeeren: (id) => req('/lagerorte/' + id + '/vorrat', { method: 'DELETE' }),
  foto: (file) => {
    const fd = new FormData()
    fd.append('datei', file)
    return fetch(BASE + '/api/vorrat/foto', { method: 'POST', body: fd, headers: authHeader() }).then(async (r) => {
      if (!r.ok) throw await fetchFehler(r, 'Foto fehlgeschlagen')
      return r.json()
    })
  },
  geraeteFoto: (file) => {
    const fd = new FormData()
    fd.append('datei', file)
    return fetch(BASE + '/api/geraete/foto', { method: 'POST', body: fd, headers: authHeader() }).then(async (r) => {
      if (!r.ok) throw await fetchFehler(r, 'Foto fehlgeschlagen')
      return r.json()
    })
  },

  // Rezepte
  rezepte: (q) => req('/rezepte' + (q ? '?query=' + encodeURIComponent(q) : '')),
  rezepteFilter: (qs) => req('/rezepte' + (qs ? '?' + qs : '')),
  rezeptSuche: (query, nur_eigene = false) => req('/rezepte/suche', { method: 'POST', body: JSON.stringify({ query, nur_eigene }) }),
  rezeptAngebote: (id, markt) => req('/rezepte/' + id + '/angebote' + (markt ? '?markt=' + encodeURIComponent(markt) : '')),
  transkribiere: (blob) => {
    const fd = new FormData()
    fd.append('datei', blob, 'sprache.webm')
    return fetch(BASE + '/api/chat/transkribieren', { method: 'POST', body: fd, headers: authHeader() })
      .then(async (r) => { if (!r.ok) throw await fetchFehler(r, 'Transkription fehlgeschlagen'); return r.json() })
  },
  rezeptKategorien: () => req('/rezepte/kategorien'),
  rezept: (id) => req('/rezepte/' + id),
  rezeptVorratCheck: (id) => req('/rezepte/' + id + '/vorrat-check'),
  guidedHolen: (id, varianten = null, force = false) =>
    req('/rezepte/' + id + '/guided', { method: 'POST', body: JSON.stringify({ varianten, force }) }),
  guidedFrage: (id, schritt, frage) =>
    req('/rezepte/' + id + '/guided/frage', { method: 'POST', body: JSON.stringify({ schritt, frage }) }),
  rezeptBewertungSetzen: (id, sterne, kommentar = null) =>
    req('/rezepte/' + id + '/bewertung', { method: 'PUT', body: JSON.stringify({ sterne, kommentar }) }),
  rezeptBewertungLoeschen: (id) => req('/rezepte/' + id + '/bewertung', { method: 'DELETE' }),
  rezeptVeroeffentlichen: (id, veroeffentlicht, globalisieren = false) =>
    req('/rezepte/' + id + '/veroeffentlicht', { method: 'PUT', body: JSON.stringify({ veroeffentlicht, globalisieren }) }),
  rezeptInWarenkorb: (id) => req('/rezepte/' + id + '/in-warenkorb', { method: 'POST' }),
  rezeptBild: (id) => req('/rezepte/' + id + '/bild'),
  rezeptImportieren: (id) => req('/rezepte/' + id + '/importieren', { method: 'POST' }),
  rezeptAusLink: (url) => req('/rezepte/aus-link', { method: 'POST', body: JSON.stringify({ url }) }),
  rezeptAusDateien: (dateien) => req('/rezepte/aus-dateien', { method: 'POST', body: JSON.stringify({ dateien }) }),
  rezeptAnGeraeteAnpassen: (id) => req('/rezepte/' + id + '/an-geraete-anpassen', { method: 'POST' }),
  rezeptBildGenerieren: (id) => req('/rezepte/' + id + '/bild/generieren', { method: 'POST' }),
  rezeptBildLoeschen: (id) => req('/rezepte/' + id + '/bild', { method: 'DELETE' }),
  rezeptBildUpload: (id, file) => {
    const fd = new FormData(); fd.append('datei', file)
    return fetch(BASE + '/api/rezepte/' + id + '/bild', { method: 'POST', body: fd, headers: authHeader() }).then((r) => {
      if (!r.ok) throw new Error('Upload fehlgeschlagen'); return r.json()
    })
  },
  rezeptAnlegen: (r) => req('/rezepte', { method: 'POST', body: JSON.stringify(r) }),
  rezeptUpdate: (id, r) => req('/rezepte/' + id, { method: 'PUT', body: JSON.stringify(r) }),
  rezeptLoeschen: (id) => req('/rezepte/' + id, { method: 'DELETE' }),
  vorschlaege: (limit = 10) => req('/rezepte/vorschlagen?limit=' + limit),
  start: () => req('/start'),
  rezepteGeraeteAnpassen: () => req('/rezepte/geraete-anpassen', { method: 'POST' }),
  rezepteGeraeteAnpassenStatus: (jobId) => req('/rezepte/geraete-anpassen-status/' + jobId),
  rezeptGenerieren: (wunsch, haendler, vorrat = true, person_ids = null, portionen = null, freitext_vorrat = null) =>
    req('/rezepte/generieren', { method: 'POST', body: JSON.stringify({ wunsch, haendler, vorrat, person_ids, portionen, freitext_vorrat }) }),
  vorratModus: () => req('/konto/vorrat-modus'),
  vorratModusSetzen: (modus) => req('/konto/vorrat-modus', { method: 'PUT', body: JSON.stringify({ modus }) }),
  kochenVorschau: (id) => req('/rezepte/' + id + '/kochen/vorschau'),
  kochenBestaetigen: (id, faktor = 1) =>
    req('/rezepte/' + id + '/kochen', { method: 'POST', body: JSON.stringify({ faktor }) }),

  // Wochenplaner
  wochenplan: (datum) => req('/plan?datum=' + datum),
  planEintragAnlegen: (e) => req('/plan', { method: 'POST', body: JSON.stringify(e) }),
  planEintragUpdate: (id, e) => req('/plan/' + id, { method: 'PUT', body: JSON.stringify(e) }),
  planEintragLoeschen: (id) => req('/plan/' + id, { method: 'DELETE' }),
  planGekocht: (id, gekocht = true) => req('/plan/' + id + '/gekocht', { method: 'PUT', body: JSON.stringify({ gekocht }) }),
  einkaufstage: (datum) => req('/plan/einkaufstage?datum=' + datum),
  einkauftagToggle: (datum) => req('/plan/einkaufstage', { method: 'POST', body: JSON.stringify({ datum }) }),
  einkaufstagMarkt: (datum, haendler) => req('/plan/einkaufstage/markt', { method: 'POST', body: JSON.stringify({ datum, haendler }) }),
  einkaufstagHaendler: (datum, haendler) => req('/plan/einkaufstage/haendler', { method: 'POST', body: JSON.stringify({ datum, haendler }) }),
  einkaufsliste: (datum) => req('/plan/einkaufsliste?datum=' + datum),
  angebote: (datum) => req('/angebote' + (datum ? '?datum=' + datum : '')),
  angeboteUebersicht: () => req('/angebote/uebersicht'),
  angebotLoeschen: (id) => req('/angebote/' + id, { method: 'DELETE' }),
  angeboteBlattLoeschen: (haendler, von, bis) =>
    req('/angebote/blatt?gueltig_von=' + von + '&gueltig_bis=' + bis + (haendler ? '&haendler=' + encodeURIComponent(haendler) : ''), { method: 'DELETE' }),
  angeboteMaerkte: (datum) => req('/angebote/maerkte?datum=' + datum),
  rezepteAusAngeboten: (haendler, datum, limit = 8) =>
    req('/rezepte/aus-angeboten?haendler=' + encodeURIComponent(haendler) + '&datum=' + datum + '&limit=' + limit),
  angeboteImport: (eintraege) => req('/angebote/import', { method: 'POST', body: JSON.stringify(eintraege) }),
  angeboteImportDatei: (file, haendler, gueltig_von, gueltig_bis, onProgress, bilder = true) =>
    new Promise((resolve, reject) => {
      const fd = new FormData()
      fd.append('datei', file)
      fd.append('haendler', haendler)
      fd.append('gueltig_von', gueltig_von)
      fd.append('gueltig_bis', gueltig_bis)
      fd.append('bilder', bilder ? 'true' : 'false')
      const xhr = new XMLHttpRequest()
      xhr.open('POST', BASE + '/api/angebote/import-datei')
      { const h = authHeader(); if (h.Authorization) xhr.setRequestHeader('Authorization', h.Authorization) }
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)) }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) { try { resolve(JSON.parse(xhr.responseText)) } catch { resolve({}) } }
        else {
          let body = null
          try { body = JSON.parse(xhr.responseText) } catch { /* ignore */ }
          reject(kiFehler(xhr.status, body) || new Error(xhr.responseText || xhr.statusText))
        }
      }
      xhr.onerror = () => reject(new Error('Upload fehlgeschlagen'))
      xhr.send(fd)
    }),
  angeboteImportStatus: (jobId) => req('/angebote/import-status/' + jobId),
  angeboteImportFortsetzen: (jobId, body) =>
    req('/angebote/import-fortsetzen/' + jobId, { method: 'POST', body: JSON.stringify(body) }),

  einkaufExtraHolen: () => req('/plan/einkaufsliste/extra'),
  einkaufExtraHinzufuegen: (artikel) =>
    req('/plan/einkaufsliste/extra', { method: 'POST', body: JSON.stringify({ artikel }) }),
  einkaufExtraLoeschen: (id) => req('/plan/einkaufsliste/extra/' + id, { method: 'DELETE' }),

  zutaten: () => req('/zutaten'),
  zutatGrundzutat: (id, grundzutat) =>
    req('/zutaten/' + id + '/grundzutat', { method: 'PUT', body: JSON.stringify({ grundzutat }) }),

  zutatenMaster: () => req('/zutaten/master'),
  zutatenUnmapped: () => req('/zutaten/unmapped'),
  zutatenUnbestaetigt: () => req('/zutaten/unbestaetigt'),
  zutatKanonisch: (id, master_zutat_id, fixiert = false) =>
    req('/zutaten/' + id + '/kanonisch', { method: 'PUT', body: JSON.stringify({ master_zutat_id, fixiert }) }),
  zutatGebinde: (id, gebinde_menge, gebinde_einheit) =>
    req('/zutaten/' + id + '/gebinde', { method: 'PUT', body: JSON.stringify({ gebinde_menge, gebinde_einheit }) }),
  zutatUmbenennen: (id, name) =>
    req('/zutaten/' + id + '/name', { method: 'PUT', body: JSON.stringify({ name }) }),
  zutatLoeschen: (id) => req('/zutaten/' + id, { method: 'DELETE' }),

  // KI-Fähigkeiten dieser Instanz (s. kiStatus.js)
  kiStatus: () => req('/ki/status'),

  // Chat (In-App-Assistent)
  chat: (history, message, images) =>
    req('/chat', { method: 'POST', body: JSON.stringify({ history, message, images }) }),
  chatStart: (history, message, images) =>
    req('/chat/start', { method: 'POST', body: JSON.stringify({ history, message, images }) }),
  chatStatus: (jobId) => req('/chat/status/' + jobId),
}
