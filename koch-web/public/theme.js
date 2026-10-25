// Theme früh setzen (kein Flash für App & Splash).
//
// Lag bis AND-34 inline in index.html. Als eigene Datei kommt die Content-Security-Policy
// (koch-web/nginx.conf) ohne 'unsafe-inline' für Skripte aus – ein Inline-Skript würde
// script-src 'self' brechen und damit das Theme vor dem ersten Render.
// Läuft synchron im <head> vor dem Bundle, hat keine Abhängigkeiten und darf keine
// Module-Imports nutzen (klassisches Skript).
try {
  var t = localStorage.getItem('theme');
  var d = t === 'dunkel' || ((t === null || t === 'system') && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', d ? 'dunkel' : 'hell');
} catch (e) { /* ohne localStorage (z. B. blockiert) bleibt das Standard-Theme */ }
