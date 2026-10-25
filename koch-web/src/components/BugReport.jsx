import { useState } from 'react'
import { api } from '../api.js'
import { Modal, Button, input, Spinner } from '../ui.jsx'
import { Icon } from '../icons.jsx'

// Schwebender Bug-Button (überall sichtbar) → Meldung an die Bugreport-DB.
export default function BugReport({ notify, seite }) {
  const [offen, setOffen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function senden() {
    const t = text.trim()
    if (!t) return
    setBusy(true)
    try {
      await api.bugreportSenden(t, seite || '')
      setText('')
      setOffen(false)
      notify && notify('Danke! Deine Meldung ist angekommen.')
    } catch {
      notify && notify('Senden fehlgeschlagen', 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOffen(true)}
        title="Fehler melden"
        aria-label="Fehler melden"
        className="fixed right-4 z-40 flex h-10 w-10 items-center justify-center rounded-full border border-line bg-card text-muted shadow-soft transition hover:scale-105 hover:bg-paper"
        style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 9rem)' }}
      >
        <Icon name="bug" size={20} />
      </button>

      {offen && (
        <Modal open onClose={() => setOffen(false)} title="Fehler melden">
          <div className="space-y-4">
            <p className="text-sm text-muted">
              Was hat nicht funktioniert? Beschreibe es kurz – das hilft enorm.
            </p>
            <textarea
              className={input + ' min-h-[120px] w-full'}
              autoFocus
              value={text}
              placeholder="z.B. „Beim Speichern des Rezepts passiert nichts …“"
              onChange={(e) => setText(e.target.value)}
            />
            {seite && <p className="text-[11px] text-muted2">Seite: {seite}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setOffen(false)} disabled={busy}>Abbrechen</Button>
              <Button onClick={senden} disabled={busy || !text.trim()}>
                {busy ? <Spinner /> : 'Senden'}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
