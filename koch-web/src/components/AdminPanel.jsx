import { useState } from 'react'
import { createPortal } from 'react-dom'
import AdminDashboard from './AdminDashboard.jsx'
import AdminUsers from './AdminUsers.jsx'
import AdminTarife from './AdminTarife.jsx'
import AdminZutaten from './AdminZutaten.jsx'
import AdminBugreports from './AdminBugreports.jsx'
import AdminGuthabenEinladung from './AdminGuthabenEinladung.jsx'
import AdminPreise from './AdminPreise.jsx'
import { Icon } from '../icons.jsx'

// Dedizierter Admin-Bereich (Vollbild) mit eigener Unter-Navigation.
// Super-Admin sieht alles; Support nur Dashboard, Nutzer, Bugreports.
export default function AdminPanel({ notify, rolle, onClose }) {
  const superAdmin = rolle === 'super_admin'
  const TABS = [
    ['dashboard', 'bar-chart', 'Übersicht', true],
    ['nutzer', 'users', 'Nutzer', true],
    ['bugreports', 'bug', 'Bugreports', true],
    ['tarife', 'credit-card', 'Tarife', superAdmin],
    ['preise', 'euro', 'Preise', superAdmin],
    ['zutaten', 'carrot', 'Zutaten', superAdmin],
    ['einladungen', 'ticket', 'Einladungen', superAdmin],
  ].filter(([, , , show]) => show)
  const [tab, setTab] = useState('dashboard')

  return createPortal(
    <div className="fixed inset-0 z-[60] flex flex-col bg-paper pt-[env(safe-area-inset-top,0px)]">
      <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-card/90 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 font-display text-xl"><Icon name="wrench" size={18} /> Admin</span>
          <span className="label-mono rounded-full bg-terracotta/15 px-2 py-0.5 text-[10px] text-terracotta">
            {superAdmin ? 'Super-Admin' : 'Support'}
          </span>
        </div>
        <button onClick={onClose} aria-label="Schließen" className="rounded-full p-1.5 text-muted hover:bg-ink/5"><Icon name="x" size={16} /></button>
      </header>

      <nav className="flex gap-1 overflow-x-auto border-b border-line bg-card/60 px-2 py-2">
        {TABS.map(([k, icon, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-3.5 py-1.5 text-sm font-medium transition ${tab === k ? 'bg-terracotta text-on-accent shadow-soft' : 'text-muted hover:text-ink'}`}>
            <Icon name={icon} size={16} /> {label}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto max-w-3xl">
          {tab === 'dashboard' && <AdminDashboard notify={notify} />}
          {tab === 'nutzer' && <AdminUsers notify={notify} superAdmin={superAdmin} />}
          {tab === 'bugreports' && <AdminBugreports notify={notify} />}
          {tab === 'tarife' && superAdmin && <AdminTarife notify={notify} />}
          {/* War seit jeher gebaut, aber nie eingebunden (Befund Admin-Review 2026-07-26) –
              hierüber sind Foto-Pack, Overage und Bild-Basispreise ohne Deploy pflegbar. */}
          {tab === 'preise' && superAdmin && <AdminPreise notify={notify} />}
          {tab === 'zutaten' && superAdmin && <AdminZutaten notify={notify} />}
          {tab === 'einladungen' && superAdmin && <AdminGuthabenEinladung notify={notify} />}
        </div>
      </main>
    </div>,
    document.body,
  )
}
