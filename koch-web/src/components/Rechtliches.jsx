import { useState } from 'react'
import { Modal } from '../ui.jsx'

// Rechtstexte als VORLAGE für selbst betriebene Instanzen.
//
// BETREIBER-HINWEIS: Name, Anschrift und Kontakt kommen aus den Build-Variablen
// VITE_IMPRESSUM_* (siehe koch-web/.env.example). Wer eine Instanz öffentlich oder für
// Dritte betreibt, MUSS diese Werte setzen und die Texte (Impressum, Datenschutz,
// Nutzungsbedingungen) an den eigenen Betrieb anpassen und rechtlich prüfen lassen –
// insbesondere Hosting, E-Mail-Versand und einen ggf. konfigurierten KI-Anbieter.
// Ohne Konfiguration erscheinen Platzhalter. Der sichtbare Vorlagen-Hinweis lässt sich
// nach der Prüfung mit VITE_RECHTSTEXTE_GEPRUEFT=1 ausblenden.
const ENV = import.meta.env
const BETREIBER = {
  name: ENV.VITE_IMPRESSUM_NAME || '[Name des Betreibers]',
  strasse: ENV.VITE_IMPRESSUM_STRASSE || '[Straße und Hausnummer]',
  ort: ENV.VITE_IMPRESSUM_ORT || '[PLZ Ort]',
  land: ENV.VITE_IMPRESSUM_LAND || 'Deutschland',
  email: ENV.VITE_IMPRESSUM_EMAIL || '[E-Mail-Adresse]',
  telefon: ENV.VITE_IMPRESSUM_TELEFON || '',
  ust: ENV.VITE_IMPRESSUM_UST || '',
}
const BETREIBER_KONFIGURIERT = Boolean(ENV.VITE_IMPRESSUM_NAME && ENV.VITE_IMPRESSUM_STRASSE && ENV.VITE_IMPRESSUM_ORT)
const GEPRUEFT = ['1', 'true', 'ja'].includes(String(ENV.VITE_RECHTSTEXTE_GEPRUEFT || '').toLowerCase())
const STAND = ENV.VITE_RECHTSTEXTE_STAND || ''

function Abschnitt({ titel, children }) {
  return (
    <div>
      <h4 className="mb-1 font-display text-base">{titel}</h4>
      <div className="space-y-1 text-sm leading-relaxed text-ink/75">{children}</div>
    </div>
  )
}

// Sichtbarer Hinweis: Die Texte sind eine Vorlage und vom Betreiber anzupassen.
function VorlagenHinweis() {
  if (GEPRUEFT && BETREIBER_KONFIGURIERT) return null
  return (
    <div className="rounded-xl border border-terracotta/40 bg-terracotta/10 p-3 text-sm text-terracotta-deep">
      <p className="font-semibold">Hinweis: Mustertext für Betreiber</p>
      <p className="mt-1">
        Dieser Text ist eine allgemeine Vorlage der Open-Source-Software „Küchenplaner" und keine
        Rechtsberatung. Der Betreiber dieser Instanz muss ihn an seinen Betrieb anpassen
        (Hosting, E-Mail-Versand, KI-Anbieter, Kontaktdaten) und rechtlich prüfen lassen.
        {!BETREIBER_KONFIGURIERT && ' Die Betreiberangaben sind noch nicht konfiguriert (VITE_IMPRESSUM_* setzen).'}
      </p>
    </div>
  )
}

function Anschrift() {
  return (
    <p>
      {BETREIBER.name}<br />
      {BETREIBER.strasse}<br />
      {BETREIBER.ort}, {BETREIBER.land}<br />
      E-Mail: {BETREIBER.email}
      {BETREIBER.telefon && <><br />Telefon: {BETREIBER.telefon}</>}
    </p>
  )
}

const DOKUMENTE = {
  impressum: {
    titel: 'Impressum',
    inhalt: (
      <>
        <Abschnitt titel="Angaben gemäß § 5 DDG">
          <Anschrift />
        </Abschnitt>
        {BETREIBER.ust && (
          <Abschnitt titel="Umsatzsteuer">
            <p>{BETREIBER.ust}</p>
          </Abschnitt>
        )}
        <Abschnitt titel="Verantwortlich i. S. d. § 18 Abs. 2 MStV">
          <p>{BETREIBER.name}, Anschrift wie oben.</p>
        </Abschnitt>
        <Abschnitt titel="Software">
          <p>
            Diese Instanz nutzt die Open-Source-Software „Küchenplaner". Betrieben wird sie
            eigenverantwortlich von dem oben genannten Betreiber; die Entwickler der
            Software sind nicht Anbieter dieser Instanz.
          </p>
        </Abschnitt>
      </>
    ),
  },
  datenschutz: {
    titel: 'Datenschutzerklärung',
    inhalt: (
      <>
        <Abschnitt titel="1. Verantwortlicher">
          <p>
            Verantwortlich für die Verarbeitung personenbezogener Daten im Rahmen dieser
            Instanz der App „Küchenplaner" (nachfolgend „App") ist:
          </p>
          <Anschrift />
          <p>
            Bei Fragen zum Datenschutz kannst du dich jederzeit unter den o. g.
            Kontaktdaten an den Betreiber wenden.
          </p>
        </Abschnitt>

        <Abschnitt titel="2. Grundlegendes & Rechtsgrundlagen">
          <p>
            Personenbezogene Daten werden nur im Rahmen der gesetzlichen Vorgaben (DSGVO,
            BDSG, TDDDG) verarbeitet. Soweit nachfolgend keine spezielle Grundlage genannt
            ist, gilt: Einwilligung (Art. 6 Abs. 1 lit. a, ggf. Art. 9 Abs. 2 lit. a
            DSGVO), Bereitstellung der Nutzung (Art. 6 Abs. 1 lit. b), rechtliche
            Verpflichtung (Art. 6 Abs. 1 lit. c) sowie berechtigtes Interesse an einem
            sicheren, funktionsfähigen Angebot (Art. 6 Abs. 1 lit. f DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="3. Hosting & Server-Logfiles">
          <p>
            Die App wird auf eigener Infrastruktur des Betreibers bzw. bei einem
            Hosting-Dienstleister des Betreibers betrieben. Beim Aufruf werden technisch
            notwendige Server-Logs verarbeitet (u. a. IP-Adresse, Datum/Uhrzeit,
            abgerufene Ressource, HTTP-Status, übertragene Datenmenge,
            Browser/Betriebssystem). Zweck ist die Auslieferung, Stabilität und
            Sicherheit der App; Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Setzt der
            Betreiber einen Hosting-Dienstleister ein, geschieht dies im Rahmen einer
            Auftragsverarbeitung (Art. 28 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="4. Nutzerkonto & Anmeldung">
          <p>
            Für die Nutzung legst du ein Konto an. Verarbeitet werden dazu E-Mail-Adresse,
            Name sowie ein Passwort, das nur als Hash gespeichert wird (das
            Klartext-Passwort ist nicht bekannt). Die Anmeldung erfolgt über ein
            Sicherheits-Token, das lokal in deinem Browser (localStorage) gespeichert
            wird. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO.
          </p>
        </Abschnitt>

        <Abschnitt titel="5. Haushalt, Personen & Einladungen">
          <p>
            In deinem Haushalt kannst du weitere Personen anlegen (z. B. Familien-
            mitglieder, Gäste) und Einladungen verwalten. Dabei können Angaben wie Name,
            Rolle, Portions-/Kalorienziele sowie Vorlieben und Notizen gespeichert
            werden. Gibst du dabei <b>Gesundheitsdaten</b> wie Allergien oder
            Unverträglichkeiten an (besondere Kategorie nach Art. 9 DSGVO), werden diese
            ausschließlich zur Anpassung von Rezepten und Empfehlungen auf Grundlage
            deiner Einwilligung (Art. 9 Abs. 2 lit. a DSGVO) verarbeitet, die du durch die
            freiwillige Eingabe erteilst und jederzeit durch Löschen der Angabe
            widerrufen kannst. Lege Daten anderer Personen nur an, wenn du dazu berechtigt
            bist.
          </p>
        </Abschnitt>

        <Abschnitt titel="6. Rezepte, Vorrat & eigene Inhalte">
          <p>
            Von dir angelegte oder importierte Inhalte (Rezepte, Vorratsartikel,
            Bewertungen, hochgeladene oder erzeugte Bilder, Fehlermeldungen) werden
            gespeichert, um dir die Funktionen der App bereitzustellen (Art. 6 Abs. 1
            lit. b DSGVO). Veröffentlichst du ein Rezept, ist es für andere Nutzer dieser
            Instanz sichtbar.
          </p>
        </Abschnitt>

        <Abschnitt titel="7. KI-Funktionen (falls aktiviert)">
          <p>
            Hat der Betreiber KI-Funktionen eingerichtet (z. B. Rezeptvorschläge,
            Chat/Kochassistent, Anpassung an deine Küchengeräte, Texterkennung aus
            Fotos/PDFs, Bildgenerierung), werden die jeweils erforderlichen Eingaben an
            den vom Betreiber konfigurierten KI-Anbieter übermittelt – das kann ein lokal
            betriebenes Modell oder ein externer Dienst sein. Übermittelt werden nur die
            für die Anfrage nötigen Daten, z. B. dein Vorrat, deine Eingaben sowie
            hochgeladene Fotos oder PDFs. Zweck ist die Erbringung der von dir
            aufgerufenen Funktion (Art. 6 Abs. 1 lit. b DSGVO). Welcher Anbieter genutzt
            wird und ob dabei Daten außerhalb der EU verarbeitet werden, ergänzt der
            Betreiber hier. Gib keine Daten ein, deren Übermittlung an einen KI-Dienst du
            nicht möchtest.
          </p>
        </Abschnitt>

        <Abschnitt titel="8. Rezept-Import aus Links">
          <p>
            Wenn du einen Link zum Import übergibst, ruft der Server die öffentlich
            abrufbare Seite auf und verarbeitet deren Textinhalt, um daraus ein Rezept zu
            erstellen. Eine Anmeldung an der jeweiligen Plattform findet nicht statt.
            Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO.
          </p>
        </Abschnitt>

        <Abschnitt titel="9. Lokale Speicherung & Cookies">
          <p>
            Die App setzt <b>keine Tracking-, Analyse- oder Werbe-Cookies</b> ein und
            bindet keine externen Analysedienste ein. Technisch notwendige Informationen
            (Anmelde-Token und Einstellungen wie Design oder Ansichtsoptionen) werden im
            localStorage deines Geräts gespeichert (§ 25 Abs. 2 TDDDG). Die App ist als
            PWA installierbar; der dafür genutzte Service Worker dient nur der
            Installierbarkeit.
          </p>
        </Abschnitt>

        <Abschnitt titel="10. E-Mail-Versand (falls konfiguriert)">
          <p>
            Für transaktionale E-Mails (z. B. Haushalts-Einladungen, Passwort
            zurücksetzen, Bestätigungs-Mails) nutzt die App den E-Mail-Versanddienst des
            Betreibers, sofern einer eingerichtet ist. Dabei werden die Empfängeradresse
            und der Inhalt der Nachricht verarbeitet (Art. 6 Abs. 1 lit. b und f DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="11. Empfänger">
          <p>
            Empfänger sind nur die oben genannten, vom Betreiber eingesetzten
            Dienstleister (Hosting, E-Mail-Versand, KI-Anbieter – jeweils soweit
            vorhanden). Eine darüber hinausgehende Weitergabe an Dritte erfolgt nicht.
            Findet dabei eine Übermittlung in Drittländer statt, benennt der Betreiber
            hier die Garantien nach Art. 44 ff. DSGVO.
          </p>
        </Abschnitt>

        <Abschnitt titel="12. Speicherdauer">
          <p>
            Daten werden gespeichert, solange dein Konto besteht bzw. solange es für die
            genannten Zwecke erforderlich ist. Nach Löschung deines Kontos werden sie
            entfernt, soweit keine gesetzlichen Aufbewahrungspflichten entgegenstehen.
            Server-Logs werden nur kurzfristig vorgehalten.
          </p>
        </Abschnitt>

        <Abschnitt titel="13. Deine Rechte">
          <p>
            Du hast das Recht auf Auskunft (Art. 15), Berichtigung (Art. 16), Löschung
            (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit
            (Art. 20) sowie Widerruf erteilter Einwilligungen mit Wirkung für die Zukunft
            (Art. 7 Abs. 3 DSGVO). Dein Konto kannst du jederzeit selbst in der App oder
            über die Seite „Konto löschen" entfernen. Im Übrigen genügt eine Nachricht an
            die oben genannten Kontaktdaten.
          </p>
        </Abschnitt>

        <Abschnitt titel="14. Widerspruchsrecht">
          <p className="font-semibold text-ink">
            Soweit Daten auf Grundlage berechtigter Interessen (Art. 6 Abs. 1 lit. f
            DSGVO) verarbeitet werden, hast du das Recht, aus Gründen, die sich aus deiner
            besonderen Situation ergeben, jederzeit Widerspruch gegen diese Verarbeitung
            einzulegen (Art. 21 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="15. Beschwerderecht">
          <p>
            Du hast das Recht, dich bei einer Datenschutz-Aufsichtsbehörde zu beschweren,
            insbesondere in dem Mitgliedstaat deines Aufenthaltsorts oder des mutmaßlichen
            Verstoßes (Art. 77 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="16. Automatisierte Entscheidungen & Sicherheit">
          <p>
            Eine ausschließlich automatisierte Entscheidung mit rechtlicher Wirkung dir
            gegenüber i. S. d. Art. 22 DSGVO findet nicht statt. Der Betreiber sollte die
            Übertragung verschlüsseln (TLS) und geeignete technische und organisatorische
            Maßnahmen treffen (Art. 32 DSGVO).
          </p>
          {STAND && <p className="text-xs text-muted">Stand: {STAND}</p>}
        </Abschnitt>
      </>
    ),
  },
  agb: {
    titel: 'Nutzungsbedingungen',
    inhalt: (
      <>
        <Abschnitt titel="1. Geltungsbereich & Betreiber">
          <p>
            Diese Nutzungsbedingungen gelten für die Nutzung dieser Instanz der
            Web-Anwendung „Küchenplaner" (nachfolgend „App"). Betreiber ist {BETREIBER.name},
            {' '}{BETREIBER.ort} (vollständige Anschrift siehe Impressum), E-Mail:
            {' '}{BETREIBER.email} (nachfolgend „Betreiber"). Mit der Registrierung
            erkennst du diese Bedingungen an.
          </p>
        </Abschnitt>

        <Abschnitt titel="2. Leistungsbeschreibung">
          <p>
            Küchenplaner ist ein Küchenassistent mit Rezeptverwaltung, Wochen- und
            Essensplanung, Vorrats- und Einkaufslistenverwaltung, Angebotsübersicht sowie
            einem Schritt-für-Schritt-Kochmodus. Sofern der Betreiber einen KI-Anbieter
            eingerichtet hat, stehen zusätzlich KI-gestützte Funktionen zur Verfügung.
          </p>
          <p>
            Die Nutzung ist unentgeltlich. Es besteht kein Anspruch auf bestimmte
            Funktionen; der Betreiber kann die Software aktualisieren, Funktionen ändern
            oder den Betrieb der Instanz einstellen.
          </p>
        </Abschnitt>

        <Abschnitt titel="3. Konto & Haushalt">
          <p>
            Für die Nutzung ist ein Konto erforderlich. Mache wahre Angaben, halte deine
            Zugangsdaten geheim und melde einen Missbrauch unverzüglich dem Betreiber. In
            einem Haushalt können mehrere Personen geführt und weitere Nutzer eingeladen
            werden.
          </p>
        </Abschnitt>

        <Abschnitt titel="4. Zulässige Nutzung">
          <p>
            Nutze die App nicht missbräuchlich: keine rechtswidrigen, beleidigenden oder
            rechteverletzenden Inhalte, kein Umgehen von Schutzmechanismen und keine
            automatisierten Abfragen, die die Funktionsfähigkeit beeinträchtigen. Für
            deine eingegebenen Inhalte bist du selbst verantwortlich. Der Betreiber kann
            Konten bei Verstößen sperren.
          </p>
        </Abschnitt>

        <Abschnitt titel="5. KI-Funktionen">
          <p>
            KI-generierte Ausgaben (z. B. Rezepte, Mengen, Nährwert-, Allergen- oder
            Angebotsangaben) können <b>fehlerhaft oder unvollständig</b> sein. Sie dienen
            der Unterstützung und stellen keine medizinische, ernährungswissenschaftliche
            oder sonstige fachliche Beratung dar. Prüfe insbesondere bei Allergien,
            Unverträglichkeiten und Hygiene stets eigenverantwortlich.
          </p>
        </Abschnitt>

        <Abschnitt titel="6. Verfügbarkeit">
          <p>
            Eine bestimmte Verfügbarkeit wird nicht zugesichert. Wartung, Störungen oder
            die Einstellung des Betriebs können die Erreichbarkeit einschränken. Sichere
            wichtige Daten bei Bedarf selbst.
          </p>
        </Abschnitt>

        <Abschnitt titel="7. Haftung">
          <p>
            Der Betreiber haftet unbeschränkt bei Vorsatz und grober Fahrlässigkeit sowie
            bei Verletzung von Leben, Körper oder Gesundheit. Im Übrigen ist die Haftung
            für die unentgeltliche Bereitstellung im gesetzlich zulässigen Umfang
            ausgeschlossen.
          </p>
        </Abschnitt>

        <Abschnitt titel="8. Beendigung">
          <p>
            Du kannst dein Konto jederzeit in den Einstellungen oder über die Seite
            „Konto löschen" entfernen; deine Daten werden dann nach Maßgabe der
            Datenschutzerklärung gelöscht. Der Betreiber kann die Nutzung mit
            angemessener Frist oder bei schwerwiegenden Verstößen sofort beenden.
          </p>
        </Abschnitt>

        <Abschnitt titel="9. Schlussbestimmungen">
          <p>
            Es gilt das Recht der Bundesrepublik Deutschland; zwingende
            Verbraucherschutzvorschriften deines Wohnsitzstaates bleiben unberührt.
            Sollten einzelne Bestimmungen unwirksam sein, bleibt die Wirksamkeit der
            übrigen Bestimmungen unberührt.
          </p>
          {STAND && <p className="text-xs text-muted">Stand: {STAND}</p>}
        </Abschnitt>
      </>
    ),
  },
}

// Footer-Zeile mit Links, die das jeweilige Dokument als Modal öffnen.
// Überall einsetzbar (Login, Einladung, „Mehr"-Bereich) – bringt eigenen State mit.
export function RechtFooter({ className = '' }) {
  const [offen, setOffen] = useState(null)
  const L = ({ k, children }) => (
    <button onClick={() => setOffen(k)} className="transition hover:text-ink hover:underline">{children}</button>
  )
  return (
    <>
      <div className={`flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-muted2 ${className}`}>
        <L k="impressum">Impressum</L>
        <span aria-hidden>·</span>
        <L k="datenschutz">Datenschutz</L>
        <span aria-hidden>·</span>
        <L k="agb">Nutzungsbedingungen</L>
        <span aria-hidden>·</span>
        {/* Öffentliche Web-Adresse für die Kontolöschung (zusätzlich zum In-App-Weg
            „Mehr → Konto löschen"). */}
        <a href="/konto-loeschen" className="font-semibold text-muted transition hover:text-ink hover:underline">
          Konto löschen
        </a>
      </div>
      {offen && (
        <Modal open onClose={() => setOffen(null)} title={DOKUMENTE[offen].titel}>
          <RechtInhalt doc={offen} />
        </Modal>
      )}
    </>
  )
}

// Rendert den Inhalt EINES Rechtsdokuments – genutzt vom Footer-Modal UND der
// Standalone-Seite, damit überall derselbe Text erscheint.
function RechtInhalt({ doc, withTitle = false }) {
  const d = DOKUMENTE[doc] || DOKUMENTE.datenschutz
  return (
    <>
      {withTitle && <h1 className="font-dish text-4xl leading-tight text-ink">{d.titel}</h1>}
      <div className={withTitle ? 'mt-5 space-y-4' : 'space-y-4'}>
        <VorlagenHinweis />
        {d.inhalt}
      </div>
    </>
  )
}

// Öffentliche Standalone-Seite für EIN Rechtsdokument (ohne Login) – für E-Mail-Links
// und feste URLs. Aufruf über /impressum, /datenschutz, /agb oder ?recht=….
export function RechtSeite({ doc, onClose }) {
  return (
    <div className="min-h-screen px-5 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <div className="kuechenplaner-wortmarke text-3xl leading-none">Küchenplaner</div>
            <div className="label-mono mt-1.5 text-terracotta">Genuss mit Verstand</div>
          </div>
          {onClose && (
            <button onClick={onClose} className="shrink-0 rounded-full border border-line px-3 py-1.5 text-sm font-semibold text-muted hover:text-ink">Schließen</button>
          )}
        </div>
        <RechtInhalt doc={doc} withTitle />
        <div className="mt-10 border-t border-line pt-5"><RechtFooter className="justify-start" /></div>
      </div>
    </div>
  )
}
