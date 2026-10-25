import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Eindeutige Build-Kennung pro Build: wird in die App eingebacken (__BUILD_ID__)
// UND als /version.json ausgeliefert. Die App vergleicht beides → erkennt neue Versionen.
const BUILD_ID = String(Date.now())

export default defineConfig({
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
  plugins: [
    react(),
    {
      name: 'version-json',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify({ build: BUILD_ID }) })
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8093',
      '/mcp': 'http://localhost:8093',
    },
  },
})
