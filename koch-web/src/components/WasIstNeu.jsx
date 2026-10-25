import { Modal, Button } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { usePreise, euro, kontingent } from '../preise.js'

// Einmalige „Was ist neu"-Präsentation nach der Umstellung aufs Abo-/Kontingent-Modell.
// Wird über App.jsx bei Login gezeigt (localStorage-gemerkt, erscheint nur einmal).
export default function WasIstNeu({ onClose }) {
  const p = usePreise()
  const Punkt = ({ icon, farbe, titel, text }) => (
    <div className="flex items-start gap-2">
      <Icon name={icon} size={18} className={`mt-0.5 shrink-0 ${farbe}`} />
      <span><b>{titel}:</b> {text}</span>
    </div>
  )
  return (
    <Modal open onClose={onClose} title="Was ist neu bei Sapio">
      <div className="space-y-3 text-sm">
        <p className="text-muted">Wir haben Sapio umgestellt – hier das Wichtigste:</p>
        <div className="space-y-2.5">
          {/* Preise/Kontingente kommen aus der Preisliste; solange sie lädt, bleiben die
              Punkte ohne Zahlen aus – lieber keine Angabe als eine veraltete. */}
          {p && (
            <>
              <Punkt icon="rocket" farbe="text-terracotta" titel={`Sapio-Abo (${euro(p.abo.preis_cents)}/Monat)`}
                text={`alle KI-Funktionen, Text ${kontingent(p.abo.ki_limit)}, ${kontingent(p.abo.bild_limit, 'Rezeptbilder')} pro Monat. Kein Guthaben-Aufladen mehr.`} />
              <Punkt icon="check" farbe="text-olive" titel="Gratis nutzbar"
                text={`alle Nicht-KI-Funktionen frei, plus ${p.gratis.ki_limit} KI-Aktionen + ${p.gratis.bild_limit} Bilder pro Monat zum Ausprobieren.`} />
              <Punkt icon="image" farbe="text-olive" titel="Foto-Credits"
                text={`mehr Bilder gefällig? ${p.foto_pack.credits} Credits für ${euro(p.foto_pack.preis_cents)} – einmalig, kein Abo nötig.`} />
            </>
          )}
          <Punkt icon="soup" farbe="text-terracotta" titel="Vorrat light (neu)"
            text="keine Lust, den Vorrat zu pflegen? In den Einstellungen auf „Light“ stellen – dann gibst du beim Rezept-Erstellen einfach ein, was du gerade da hast." />
        </div>
        <Button onClick={onClose} className="w-full">Alles klar</Button>
      </div>
    </Modal>
  )
}
