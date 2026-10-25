import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Card, Button, Field, input, Modal, Spinner, Empty, confirmDialog } from '../ui.jsx'
import { Icon } from '../icons.jsx'
import { WEB_URL } from '../native.js'

function fmtFaktor(n) {
  const x = Number(n)
  return Number.isInteger(x) ? x : Math.round(x * 100) / 100
}

// Tag-Editor für kommagetrennte Vorlieben: Chips mit × entfernen, + zum Hinzufügen.
function TagEdit({ value, onChange, placeholder, chipClass = 'bg-olive/15 text-olive' }) {
  const [neu, setNeu] = useState('')
  const tags = (value || '').split(',').map((t) => t.trim()).filter(Boolean)
  function add() {
    const t = neu.trim()
    if (!t) return
    if (!tags.some((x) => x.toLowerCase() === t.toLowerCase())) onChange([...tags, t].join(', '))
    setNeu('')
  }
  function remove(t) { onChange(tags.filter((x) => x !== t).join(', ')) }
  return (
    <div>
      {tags.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span key={t} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-sm font-semibold ${chipClass}`}>
              {t}
              <button onClick={() => remove(t)} className="text-base leading-none opacity-60 hover:opacity-100" aria-label={`${t} entfernen`}>×</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input
          className={input + ' flex-1'}
          value={neu}
          placeholder={placeholder}
          onChange={(e) => setNeu(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        />
        <button onClick={add} disabled={!neu.trim()} className="shrink-0 rounded-xl border border-terracotta/40 px-3.5 text-lg font-bold text-terracotta transition hover:bg-terracotta/10 disabled:opacity-40" aria-label="Hinzufügen">+</button>
      </div>
    </div>
  )
}

export default function Personen({ notify }) {
  const [personen, setPersonen] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(null) // null | {mode:'add'} | {mode:'edit', person}
  const [inviteOffen, setInviteOffen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteBusy, setInviteBusy] = useState(false)

  async function emailEinladen() {
    const email = inviteEmail.trim().toLowerCase()
    if (!email || !email.includes('@') || !email.includes('.')) { notify('Bitte eine gültige E-Mail angeben', 'err'); return }
    setInviteBusy(true)
    try {
      const res = await api.einladungErstellen(email)
      if (res?.error) { notify(res.error, 'err'); return }
      if (res?.mail_versendet) notify(`Einladung an ${email} gesendet`)
      else notify('Einladung erstellt, aber die E-Mail konnte nicht versendet werden – nutze den Teilen-Link.', 'err')
      setInviteOffen(false); setInviteEmail('')
    } catch (e) {
      notify(e.message || 'Einladung fehlgeschlagen', 'err')
    } finally {
      setInviteBusy(false)
    }
  }

  async function lade() {
    setLoading(true)
    try {
      setPersonen(await api.personen())
    } catch {
      notify('Personen konnten nicht geladen werden', 'err')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    lade()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loeschen(p) {
    if (!(await confirmDialog(`„${p.name}" aus dem Haushalt entfernen?`))) return
    try {
      await api.personLoeschen(p.id)
      setPersonen((arr) => arr.filter((x) => x.id !== p.id))
      notify('Person entfernt')
    } catch {
      notify('Löschen fehlgeschlagen', 'err')
    }
  }

  if (loading)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    )

  const erwachsene = personen.filter((p) => p.rolle !== 'kind')
  const kinder = personen.filter((p) => p.rolle === 'kind')

  const zeile = (p) => {
    const info = `Portion ×${fmtFaktor(p.portionsfaktor)}`
    const prefs = [
      p.ernaehrung && { t: p.ernaehrung, c: 'bg-surface text-muted2' },
      p.allergien && { t: p.allergien, c: 'bg-terracotta/15 text-terracotta-deep' },
      p.mag_nicht && { t: 'nicht: ' + p.mag_nicht, c: 'bg-surface text-muted2' },
      p.mag_gern && { t: 'gern: ' + p.mag_gern, c: 'bg-olive/15 text-olive' },
    ].filter(Boolean)
    return (
      <Card key={p.id} className="flex items-start justify-between gap-3 p-3">
        <div className="min-w-0">
          <p className="truncate font-dish text-2xl leading-tight">{p.name}</p>
          <p className="truncate font-mono text-sm text-muted">{info}</p>
          {prefs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {prefs.map((pr, i) => (
                <span key={i} className={`rounded-full px-2 py-0.5 text-xs font-medium ${pr.c}`}>
                  {pr.t}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => setForm({ mode: 'edit', person: p })}
            className="rounded-full px-3 py-1.5 text-sm font-semibold text-muted hover:bg-ink/5"
          >
            Bearbeiten
          </button>
          <button
            onClick={() => loeschen(p)}
            className="rounded-full px-3 py-1.5 text-sm text-terracotta-deep hover:bg-terracotta/10"
          >
            Löschen
          </button>
        </div>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-4 hero-card flex flex-wrap items-center justify-between gap-3 rounded-[22px] p-5">
          <div className="hero-glow" />
          <div className="relative min-w-0">
            <h2 className="font-dish text-3xl leading-tight text-ink">Haushalt</h2>
            <p className="label-mono mt-1.5 text-muted2">Personen · Portionen · Allergien</p>
          </div>
          <Button className="relative shrink-0" onClick={() => setForm({ mode: 'add' })}>+ Person</Button>
        </div>
        <p className="mb-4 text-sm text-muted">
          Wer mitisst – für die Mengen- und Rezeptplanung. Vorlieben/Allergien je Person,
          Kinder über einen kleineren Portionsfaktor.
        </p>

        {personen.length === 0 && <Empty>Noch niemand angelegt.</Empty>}

        {erwachsene.length > 0 && (
          <div className="mb-5">
            <p className="mb-1.5 label-mono text-muted2">Erwachsene</p>
            <div className="space-y-2">{erwachsene.map(zeile)}</div>
          </div>
        )}

        {kinder.length > 0 && (
          <div>
            <p className="mb-1.5 label-mono text-muted2">Kinder</p>
            <div className="space-y-2">{kinder.map(zeile)}</div>
          </div>
        )}

        <div className="mt-5 space-y-2 border-t border-line/60 pt-4">
          <button
            onClick={() => { setInviteEmail(''); setInviteOffen(true) }}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-line p-3 text-left hover:bg-ink/5"
          >
            <span>
              <span className="inline-flex items-center gap-1 font-semibold"><Icon name="mail" size={16} /> Per E-Mail einladen</span>
              <span className="mt-0.5 block text-sm text-muted">Wir senden eine Einladungs-E-Mail mit Link. Der Eingeladene legt Name &amp; Passwort selbst an.</span>
            </span>
            <span className="shrink-0 text-muted2">›</span>
          </button>
          <button
            onClick={async () => {
              try {
                const inv = await api.einladungErstellen('')
                const url = `${WEB_URL}/?einladung=${inv.token}`
                const shareData = { title: 'Sapio', text: 'Tritt unserem Haushalt bei Sapio bei:', url }
                if (navigator.share) { try { await navigator.share(shareData) } catch { /* abgebrochen */ } }
                else if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(url); notify('Einladungslink kopiert') }
                else notify(`Einladungslink: ${url}`)
              } catch (e) { notify(e.message || 'Einladung fehlgeschlagen', 'err') }
            }}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-line p-3 text-left hover:bg-ink/5"
          >
            <span>
              <span className="inline-flex items-center gap-1 font-semibold"><Icon name="users" size={16} /> Einladungslink teilen</span>
              <span className="mt-0.5 block text-sm text-muted">Link per WhatsApp, Messenger … weitergeben.</span>
            </span>
            <span className="shrink-0 text-muted2">›</span>
          </button>
        </div>
      </section>

      <Modal open={inviteOffen} onClose={() => { if (!inviteBusy) { setInviteOffen(false); setInviteEmail('') } }} title="Per E-Mail einladen">
        <div className="space-y-3">
          <p className="text-sm text-muted">Wir senden eine Einladung an diese Adresse. Die eingeladene Person legt damit Name &amp; Passwort fest und tritt eurem Haushalt bei.</p>
          <Field label="E-Mail-Adresse">
            <input
              className={input}
              type="email"
              autoFocus
              placeholder="name@beispiel.de"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !inviteBusy) emailEinladen() }}
            />
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => { setInviteOffen(false); setInviteEmail('') }} disabled={inviteBusy}>Abbrechen</Button>
            <Button onClick={emailEinladen} disabled={inviteBusy}>{inviteBusy ? <Spinner /> : 'Einladung senden'}</Button>
          </div>
        </div>
      </Modal>

      {form && (
        <PersonForm
          notify={notify}
          person={form.mode === 'edit' ? form.person : null}
          onClose={() => setForm(null)}
          onSaved={(saved, mode) => {
            setPersonen((arr) =>
              mode === 'edit' ? arr.map((x) => (x.id === saved.id ? saved : x)) : [...arr, saved],
            )
            setForm(null)
          }}
        />
      )}
    </div>
  )
}

function PersonForm({ notify, person, onClose, onSaved }) {
  const editing = !!person
  const [f, setF] = useState(() => ({
    name: person?.name || '',
    rolle: person?.rolle || 'erwachsener',
    kcal_ziel: person?.kcal_ziel ?? '',
    eiweiss_pct: person?.eiweiss_pct ?? 30,
    fett_pct: person?.fett_pct ?? 30,
    kh_pct: person?.kh_pct ?? 40,
    portionsfaktor: person?.portionsfaktor ?? 1.0,
    ernaehrung: person?.ernaehrung || '',
    allergien: person?.allergien || '',
    mag_nicht: person?.mag_nicht || '',
    mag_gern: person?.mag_gern || '',
  }))

  function setRolle(rolle) {
    setF((s) => {
      const next = { ...s, rolle }
      // bequeme Voreinstellung des Portionsfaktors beim Rollenwechsel
      if (rolle === 'kind' && Number(s.portionsfaktor) === 1) next.portionsfaktor = 0.5
      if (rolle === 'erwachsener' && Number(s.portionsfaktor) === 0.5) next.portionsfaktor = 1
      return next
    })
  }

  async function speichern() {
    if (!f.name.trim()) {
      notify('Name nötig', 'err')
      return
    }
    const payload = {
      name: f.name.trim(),
      rolle: f.rolle,
      kcal_ziel: f.kcal_ziel !== '' ? Number(f.kcal_ziel) : null,
      eiweiss_pct: Number(f.eiweiss_pct) || 0,
      fett_pct: Number(f.fett_pct) || 0,
      kh_pct: Number(f.kh_pct) || 0,
      portionsfaktor: Number(f.portionsfaktor) || 1,
      aktiv: true,
      ernaehrung: f.ernaehrung.trim(),
      allergien: f.allergien.trim(),
      mag_nicht: f.mag_nicht.trim(),
      mag_gern: f.mag_gern.trim(),
    }
    try {
      const saved = editing ? await api.personUpdate(person.id, payload) : await api.personAnlegen(payload)
      notify(editing ? 'Person aktualisiert' : 'Person angelegt')
      onSaved(saved, editing ? 'edit' : 'add')
    } catch {
      notify('Speichern fehlgeschlagen', 'err')
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? 'Person bearbeiten' : 'Neue Person'}>
      <div className="space-y-3">
        <Field label="Name">
          <input className={input} value={f.name} placeholder="z.B. Max Mustermann" onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>

        <Field label="Rolle">
          <div className="flex gap-2">
            {[['erwachsener', 'Erwachsene/r'], ['kind', 'Kind']].map(([val, label]) => (
              <button
                key={val}
                onClick={() => setRolle(val)}
                className={`flex-1 rounded-xl border px-3 py-2 text-sm font-semibold transition ${
                  f.rolle === val ? 'border-terracotta bg-terracotta text-on-accent' : 'border-line bg-card text-ink hover:border-terracotta/50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Portionsfaktor">
          <input
            type="number"
            step="0.1"
            className={input}
            value={f.portionsfaktor}
            onChange={(e) => setF({ ...f, portionsfaktor: e.target.value })}
          />
          <span className="mt-1 block font-mono text-xs text-muted">1,0 = volle Portion · Kinder z.B. 0,5</span>
        </Field>

        <div className="border-t border-line pt-3">
          <p className="mb-2 label-mono text-muted2">
            Präferenzen (optional)
          </p>
          <div className="space-y-3">
            <Field label="Ernährungsform">
              <input
                className={input}
                value={f.ernaehrung}
                placeholder="z.B. omnivor, vegetarisch, vegan"
                onChange={(e) => setF({ ...f, ernaehrung: e.target.value })}
              />
            </Field>
            <Field label="Allergien / Unverträglichkeiten">
              <TagEdit
                value={f.allergien}
                onChange={(v) => setF({ ...f, allergien: v })}
                placeholder="z.B. Laktose – mit + hinzufügen"
                chipClass="bg-terracotta/15 text-terracotta-deep"
              />
              <span className="mt-1 block text-xs text-muted">
                Wird bei Vorschlägen strikt ausgeschlossen.
              </span>
            </Field>
            <Field label="Mag nicht">
              <TagEdit
                value={f.mag_nicht}
                onChange={(v) => setF({ ...f, mag_nicht: v })}
                placeholder="z.B. Pilze – mit + hinzufügen"
                chipClass="bg-surface text-muted2"
              />
            </Field>
            <Field label="Mag gern">
              <TagEdit
                value={f.mag_gern}
                onChange={(v) => setF({ ...f, mag_gern: v })}
                placeholder="z.B. Pasta – mit + hinzufügen"
                chipClass="bg-olive/15 text-olive"
              />
            </Field>
          </div>
        </div>

        {editing && <PersonNotizen personId={person.id} notify={notify} />}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button onClick={speichern}>Speichern</Button>
        </div>
      </div>
    </Modal>
  )
}

// Personen-Memory: personenbezogene Notizen (Chat-gespeichert + manuell), einsehbar/editierbar.
function PersonNotizen({ personId, notify }) {
  const [notizen, setNotizen] = useState(null)
  const [neu, setNeu] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.personNotizen(personId).then(setNotizen).catch(() => setNotizen([]))
  }, [personId])

  async function add() {
    const t = neu.trim()
    if (!t) return
    setBusy(true)
    try {
      const n = await api.personNotizAdd(personId, t)
      setNotizen((l) => [n, ...(l || [])])
      setNeu('')
    } catch { notify('Notiz speichern fehlgeschlagen', 'err') } finally { setBusy(false) }
  }
  async function del(id) {
    try { await api.personNotizLoeschen(id); setNotizen((l) => l.filter((x) => x.id !== id)) }
    catch { notify('Löschen fehlgeschlagen', 'err') }
  }

  return (
    <div className="border-t border-line pt-3">
      <p className="mb-1 label-mono text-muted2">Notizen (Memory)</p>
      <p className="mb-2 text-xs text-muted">Personenbezogene Infos, die der Assistent sich merkt – hier einsehbar & bearbeitbar.</p>
      {notizen === null ? (
        <div className="py-2"><Spinner /></div>
      ) : notizen.length === 0 ? (
        <p className="mb-2 text-sm text-muted2">Noch keine Notizen.</p>
      ) : (
        <ul className="mb-2 space-y-1">
          {notizen.map((n) => (
            <li key={n.id} className="flex items-start justify-between gap-2 rounded-lg border border-line/60 bg-card/60 px-2.5 py-1.5 text-sm">
              <span className="min-w-0">{n.text}{n.quelle === 'chat' && <span className="ml-1 inline-flex items-center gap-1 text-xs text-muted2" title="vom Assistenten gemerkt">· <Icon name="message-circle" size={12} /></span>}</span>
              <button onClick={() => del(n.id)} className="shrink-0 text-base leading-none text-ink/40 hover:text-terracotta-deep" aria-label="Notiz löschen">×</button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input className={input + ' flex-1'} value={neu} placeholder="Notiz hinzufügen…" onChange={(e) => setNeu(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
        <button onClick={add} disabled={busy || !neu.trim()} className="shrink-0 rounded-xl border border-terracotta/40 px-3.5 text-lg font-bold text-terracotta hover:bg-terracotta/10 disabled:opacity-40" aria-label="Hinzufügen">+</button>
      </div>
    </div>
  )
}
