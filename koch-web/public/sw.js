// Service-Worker (v3, 2026-06-19): Installierbarkeit + ZWANGS-Update.
// KEIN dauerhaftes Caching. Beim Aktivieren werden alte Caches geleert und alle offenen
// Clients einmal neu geladen, damit hängengebliebene (PWA-)Versionen sofort frisch werden.
const SW_VERSION = 'v23-2026-06-24-rechtsseiten'

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (e) => e.waitUntil((async () => {
  try { for (const k of await caches.keys()) await caches.delete(k) } catch { /* ignore */ }
  await self.clients.claim()
  // Bestehende Fenster einmal neu laden -> holen die frische index.html (no-cache) + neues Bundle.
  try {
    const cs = await self.clients.matchAll({ type: 'window' })
    for (const c of cs) { try { c.navigate(c.url) } catch { /* ignore */ } }
  } catch { /* ignore */ }
})()))

// Navigations IMMER network-first (frische index.html), sonst Default-Netzwerk.
self.addEventListener('fetch', (e) => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)))
  }
})
