/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)',
        ink: 'var(--ink)',
        terracotta: 'var(--terracotta)',
        'terracotta-deep': 'var(--terracotta-deep)',
        'accent-top': 'var(--accent-top)',
        'on-accent': 'var(--on-accent)',
        olive: 'var(--olive)',
        butter: 'var(--butter)',
        card: 'var(--card)',
        card2: 'var(--card2)',
        surface: 'var(--surface)',
        line: 'var(--line)',
        muted: 'var(--muted)',
        muted2: 'var(--muted2)',
        akzent: 'var(--akzent)',
      },
      fontFamily: {
        // Sans (UI/Buttons/Labels) – „Verstand"
        display: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        body: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        // Serif (Gerichtsnamen/große Aussagen) – „Genuss"
        serif: ['"Instrument Serif"', 'Georgia', 'serif'],
        // Mono (Kennzahlen/Status/Uppercase-Labels) – „Verstand"
        mono: ['"Space Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        soft: '0 1px 2px rgba(43,34,24,0.04), 0 10px 30px -16px rgba(43,34,24,0.28)',
        // Kupfer-Glow für Primär-Buttons/Akzent-Flächen
        glow: '0 10px 26px -10px rgba(227,168,106,0.6)',
      },
    },
  },
  plugins: [],
}
