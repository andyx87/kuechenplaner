import { Component } from 'react'

// Fängt Renderfehler ab, damit statt eines weißen Bildschirms eine Meldung mit
// Neuladen-Knopf erscheint (wichtig in der nativen App: dort gibt es keine Adresszeile).
export default class Fehlergrenze extends Component {
  constructor(props) {
    super(props)
    this.state = { fehler: null }
  }

  static getDerivedStateFromError(fehler) {
    return { fehler }
  }

  componentDidCatch(fehler, info) {
    console.error('Renderfehler', fehler, info?.componentStack)
  }

  render() {
    if (!this.state.fehler) return this.props.children
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="font-display text-2xl">Da ist etwas schiefgelaufen</p>
        <p className="max-w-xs text-sm text-muted">Deine Daten sind sicher gespeichert. Lade Sapio neu, dann geht es weiter.</p>
        <button onClick={() => window.location.reload()}
          className="rounded-xl bg-terracotta px-5 py-2.5 text-sm font-semibold text-on-accent">
          Neu laden
        </button>
      </div>
    )
  }
}
