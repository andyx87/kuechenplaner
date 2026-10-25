import { useEffect, useMemo, useState } from 'react'
import DOMPurify from 'dompurify'
import { api } from '../api.js'
import { Modal, Spinner } from '../ui.jsx'

// Rechtstexte – Fallback. Die verbindlichen Texte kommen live von der IT-Recht Kanzlei:
// Datenschutz über api.rechtstext (DB), Impressum über das ITRK-Embed (RechtSeite unten).
// Die Texte hier erscheinen nur, wenn beides nicht lädt.
//
// BETREIBER-HINWEIS: Name, Anschrift und Kontakt kommen aus den Build-Variablen
// VITE_IMPRESSUM_* (siehe koch-web/.env.example). Wer die App betreibt, MUSS diese Werte
// setzen und die Fallback-Texte (Impressum, Datenschutz, Nutzungsbedingungen) rechtlich
// prüfen und an den eigenen Betrieb anpassen. Ohne Konfiguration erscheinen Platzhalter.
const ENV = import.meta.env
const BETREIBER = {
  name: ENV.VITE_IMPRESSUM_NAME || '[Name des Betreibers]',
  strasse: ENV.VITE_IMPRESSUM_STRASSE || '[Straße und Hausnummer]',
  ort: ENV.VITE_IMPRESSUM_ORT || '[PLZ Ort]',
  land: ENV.VITE_IMPRESSUM_LAND || 'Deutschland',
  email: ENV.VITE_IMPRESSUM_EMAIL || '[E-Mail-Adresse]',
  ust: ENV.VITE_IMPRESSUM_UST || '[Angaben zur Umsatzsteuer, z. B. USt-IdNr. oder Kleinunternehmer-Hinweis]',
}
const BETREIBER_KONFIGURIERT = Boolean(ENV.VITE_IMPRESSUM_NAME && ENV.VITE_IMPRESSUM_STRASSE && ENV.VITE_IMPRESSUM_ORT)

function Abschnitt({ titel, children }) {
  return (
    <div>
      <h4 className="mb-1 font-display text-base">{titel}</h4>
      <div className="space-y-1 text-sm leading-relaxed text-ink/75">{children}</div>
    </div>
  )
}

const DOKUMENTE = {
  impressum: {
    titel: 'Impressum',
    inhalt: (
      <>
        {!BETREIBER_KONFIGURIERT && (
          <p className="text-sm font-semibold text-red-700">
            Hinweis für Betreiber: Die Impressumsangaben sind nicht konfiguriert
            (VITE_IMPRESSUM_* setzen).
          </p>
        )}
        <Abschnitt titel="Angaben gemäß § 5 DDG">
          <p>{BETREIBER.name}</p>
          <p>{BETREIBER.strasse}</p>
          <p>{BETREIBER.ort}</p>
        </Abschnitt>
        <Abschnitt titel="Kontakt">
          <p>E-Mail: {BETREIBER.email}</p>
        </Abschnitt>
        <Abschnitt titel="Umsatzsteuer">
          <p>{BETREIBER.ust}</p>
        </Abschnitt>
        <Abschnitt titel="Verantwortlich i. S. d. § 18 Abs. 2 MStV">
          <p>{BETREIBER.name}, Anschrift wie oben.</p>
        </Abschnitt>
        {/* Die EU-OS-Plattform wurde am 20.07.2025 eingestellt – daher kein Link mehr. */}
        <Abschnitt titel="Verbraucherstreitbeilegung">
          <p>
            Wir sind nicht verpflichtet und nicht bereit, an Streitbeilegungsverfahren vor
            einer Verbraucherschlichtungsstelle teilzunehmen.
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
            Verantwortlich für die Verarbeitung personenbezogener Daten im Rahmen der
            App „Topfplan" (nachfolgend „App") ist:
          </p>
          <p>
            {BETREIBER.name}<br />
            {BETREIBER.strasse}<br />
            {BETREIBER.ort}, {BETREIBER.land}<br />
            E-Mail: {BETREIBER.email}
          </p>
          <p>
            Ein Datenschutzbeauftragter ist gesetzlich nicht zu benennen. Bei Fragen zum
            Datenschutz kannst du dich jederzeit unter den o. g. Kontaktdaten an uns
            wenden.
          </p>
        </Abschnitt>

        <Abschnitt titel="2. Grundlegendes & Rechtsgrundlagen">
          <p>
            Wir verarbeiten personenbezogene Daten nur im Rahmen der gesetzlichen
            Vorgaben (DSGVO, BDSG, TDDDG). Soweit nachfolgend keine spezielle Grundlage
            genannt ist, gilt: Einwilligung (Art. 6 Abs. 1 lit. a, ggf. Art. 9 Abs. 2
            lit. a DSGVO), Vertragserfüllung bzw. vorvertragliche Maßnahmen (Art. 6
            Abs. 1 lit. b), rechtliche Verpflichtung (Art. 6 Abs. 1 lit. c) sowie
            berechtigtes Interesse an einem sicheren, funktionsfähigen Angebot (Art. 6
            Abs. 1 lit. f DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="3. Hosting & Server-Logfiles">
          <p>
            Die App wird auf <b>Google Cloud</b> betrieben (Google Cloud EMEA Ltd. /
            Google Ireland Ltd.). Anwendung (Cloud Run) und Datenbank (Cloud SQL,
            PostgreSQL) laufen in der Region <b>europe-west3 (Frankfurt, EU)</b>. Beim
            Aufruf werden technisch notwendige Server-Logs verarbeitet (u. a. IP-Adresse,
            Datum/Uhrzeit, abgerufene Ressource, HTTP-Status, übertragene Datenmenge,
            Browser/Betriebssystem). Zweck ist die Auslieferung, Stabilität und
            Sicherheit der App; Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Mit
            Google besteht ein Auftragsverarbeitungsvertrag (Art. 28 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="4. Nutzerkonto & Anmeldung">
          <p>
            Für die Nutzung legst du ein Konto an. Wir verarbeiten dazu E-Mail-Adresse,
            Name sowie ein verschlüsselt gespeichertes Passwort (als Hash; das Klartext-
            Passwort kennen wir nicht). Die Anmeldung erfolgt über ein Sicherheits-Token,
            das ausschließlich lokal in deinem Browser (localStorage) gespeichert wird –
            es werden hierfür keine Tracking-Cookies gesetzt. Rechtsgrundlage ist die
            Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="5. Haushalt, Personen & Einladungen">
          <p>
            In deinem Haushalt kannst du weitere Personen anlegen (z. B. Familien-
            mitglieder, Gäste) und Einladungen verwalten. Dabei können Angaben wie Name,
            Rolle, Portions-/Kalorienziele sowie Vorlieben und Notizen gespeichert
            werden. Gibst du dabei <b>Gesundheitsdaten</b> wie Allergien oder
            Unverträglichkeiten an (besondere Kategorie nach Art. 9 DSGVO), verarbeiten
            wir diese ausschließlich zur Anpassung von Rezepten und Empfehlungen auf
            Grundlage deiner Einwilligung (Art. 9 Abs. 2 lit. a DSGVO), die du durch die
            freiwillige Eingabe erteilst und jederzeit durch Löschen der Angabe
            widerrufen kannst. Für die übrigen Haushaltsdaten ist Art. 6 Abs. 1 lit. b
            DSGVO Grundlage. Lade nur Daten anderer Personen hoch, wenn du dazu berechtigt
            bist.
          </p>
        </Abschnitt>

        <Abschnitt titel="6. Rezepte, Vorrat & eigene Inhalte">
          <p>
            Von dir angelegte oder importierte Inhalte (Rezepte, Vorratsartikel,
            Bewertungen, hochgeladene oder KI-erzeugte Bilder, Bug-Reports) werden
            gespeichert, um dir die Funktionen der App bereitzustellen (Art. 6 Abs. 1
            lit. b DSGVO). Veröffentlichst du ein Rezept, ist es für andere Nutzer
            sichtbar.
          </p>
        </Abschnitt>

        <Abschnitt titel="7. KI-Funktionen (Google Vertex AI / Gemini)">
          <p>
            Für KI-gestützte Funktionen (Rezeptvorschläge, Chat/Kochassistent, Anpassung
            an deine Ausstattung, Texterkennung aus hochgeladenen Fotos/PDFs sowie
            Bildgenerierung) werden die jeweils erforderlichen Eingaben an
            <b> Google Vertex AI (Gemini-Modelle)</b> übermittelt und dort verarbeitet.
            Übermittelt werden nur die für die Anfrage nötigen Daten – z. B. dein
            Vorrat, deine Wünsche/Eingaben sowie hochgeladene Fotos oder PDFs. Zweck ist
            die Erbringung der von dir aufgerufenen Funktion (Art. 6 Abs. 1 lit. b
            DSGVO). Die Verarbeitung über das Vertex-Endpoint kann auch außerhalb der EU
            stattfinden (siehe Abschnitt 13). Bitte gib keine Daten ein, deren
            Übermittlung an einen KI-Dienst du nicht möchtest.
          </p>
        </Abschnitt>

        <Abschnitt titel="8. Angebots-Websuche">
          <p>
            Auf deine Anfrage hin sucht der Assistent aktuelle Markt-Angebote im Internet.
            Dazu werden Suchparameter (z. B. Markt/Region, Datum) über die Google-Search-
            Grounding-Funktion von Gemini an Google übermittelt. Rechtsgrundlage ist die
            Ausführung der von dir angeforderten Funktion (Art. 6 Abs. 1 lit. b DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="9. Rezept-Import aus Links">
          <p>
            Wenn du einen Link zum Import übergibst, ruft unser Server die öffentlich
            abrufbare Seite auf und übergibt den Textinhalt (z. B. die Caption) zur
            Strukturierung an die KI. Es findet keine Anmeldung an den jeweiligen
            Plattformen statt. Rechtsgrundlage ist die Ausführung der von dir
            angeforderten Funktion (Art. 6 Abs. 1 lit. b DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="10. Zahlungen & Abrechnung (Stripe)">
          <p>
            Guthaben-Aufladungen werden über den Zahlungsdienstleister <b>Stripe</b>
            (Stripe Payments Europe, Ltd., Irland) abgewickelt. Die Zahlungs- und
            Kartendaten gibst du direkt bei Stripe ein; wir erhalten keine vollständigen
            Kartendaten, sondern lediglich Status und Betrag der Transaktion. Wir
            speichern Aufladungen und den Verbrauch deines Guthabens zur Abrechnung und
            zur Erfüllung steuer-/handelsrechtlicher Pflichten. Rechtsgrundlage sind
            Art. 6 Abs. 1 lit. b und lit. c DSGVO. Es gelten ergänzend die
            Datenschutzhinweise von Stripe (stripe.com/de/privacy).
          </p>
        </Abschnitt>

        <Abschnitt titel="11. Lokale Speicherung, Cookies & App-Installation">
          <p>
            Wir setzen <b>keine Tracking-, Analyse- oder Werbe-Cookies</b> ein und nutzen
            keine externen Analyse- oder Reichweitenmessdienste. Technisch notwendige
            Informationen (Anmelde-Token und Einstellungen wie Theme oder
            Ansichtsoptionen) werden im <b>localStorage</b> deines Geräts gespeichert
            (Rechtsgrundlage § 25 Abs. 2 TDDDG bzw. Art. 6 Abs. 1 lit. f DSGVO). Die App
            ist als PWA installierbar; der dafür genutzte Service Worker dient nur der
            Installierbarkeit und speichert keine Inhalte zu Tracking-Zwecken.
          </p>
        </Abschnitt>

        <Abschnitt titel="12. E-Mail-Versand (Resend)">
          <p>
            Für den Versand transaktionaler E-Mails (z. B. Haushalts-Einladungen,
            Passwort-Zurücksetzen, Bestätigungs-Mails) nutzen wir den Dienstleister
            <b> Resend</b> (Resend, Inc., USA; Versand über die EU-Region). Dabei werden
            die Empfänger-E-Mail-Adresse und der Inhalt der jeweiligen Nachricht
            verarbeitet. Rechtsgrundlage ist die Vertragserfüllung bzw. unser berechtigtes
            Interesse an einer zuverlässigen Zustellung (Art. 6 Abs. 1 lit. b und f DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="13. Empfänger & Übermittlung in Drittländer">
          <p>
            Empfänger im Rahmen der Auftragsverarbeitung sind Google (Hosting,
            Datenbank, KI), Stripe (Zahlungen) und Resend (E-Mail-Versand). Soweit dabei
            – insbesondere bei den KI-Funktionen – Daten außerhalb der EU/des EWR (u. a.
            in den USA) verarbeitet werden, erfolgt dies auf Grundlage geeigneter
            Garantien nach Art. 44 ff. DSGVO, namentlich EU-Standardvertragsklauseln bzw.
            einer Zertifizierung unter dem EU-U.S. Data Privacy Framework. Eine darüber
            hinausgehende Weitergabe an Dritte erfolgt nicht.
          </p>
        </Abschnitt>

        <Abschnitt titel="14. Speicherdauer">
          <p>
            Wir speichern personenbezogene Daten, solange dein Konto besteht bzw. solange
            es für die genannten Zwecke erforderlich ist. Nach Löschung deines Kontos
            werden die Daten gelöscht, soweit keine gesetzlichen Aufbewahrungsfristen
            entgegenstehen (z. B. bis zu 10 Jahre für Abrechnungs-/Steuerunterlagen gem.
            HGB/AO). Server-Logs werden nur kurzfristig vorgehalten.
          </p>
        </Abschnitt>

        <Abschnitt titel="15. Deine Rechte">
          <p>
            Du hast das Recht auf Auskunft (Art. 15), Berichtigung (Art. 16), Löschung
            (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit
            (Art. 20) sowie Widerruf erteilter Einwilligungen mit Wirkung für die Zukunft
            (Art. 7 Abs. 3 DSGVO). Zur Ausübung genügt eine Nachricht an die oben
            genannten Kontaktdaten.
          </p>
        </Abschnitt>

        <Abschnitt titel="16. Widerspruchsrecht">
          <p className="font-semibold text-ink">
            Soweit wir Daten auf Grundlage berechtigter Interessen (Art. 6 Abs. 1 lit. f
            DSGVO) verarbeiten, hast du das Recht, aus Gründen, die sich aus deiner
            besonderen Situation ergeben, jederzeit Widerspruch gegen diese Verarbeitung
            einzulegen (Art. 21 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="17. Beschwerderecht">
          <p>
            Du hast das Recht, dich bei einer Datenschutz-Aufsichtsbehörde zu beschweren,
            insbesondere in dem Mitgliedstaat deines Aufenthaltsorts oder des mutmaßlichen
            Verstoßes (Art. 77 DSGVO). Eine Liste der Aufsichtsbehörden findest du unter
            www.bfdi.bund.de.
          </p>
        </Abschnitt>

        <Abschnitt titel="18. Automatisierte Entscheidungsfindung & Sicherheit">
          <p>
            Eine ausschließlich automatisierte Entscheidung mit rechtlicher Wirkung dir
            gegenüber i. S. d. Art. 22 DSGVO findet nicht statt. Die Übertragung erfolgt
            verschlüsselt (SSL/TLS); wir treffen geeignete technische und organisatorische
            Maßnahmen zum Schutz deiner Daten (Art. 32 DSGVO).
          </p>
        </Abschnitt>

        <Abschnitt titel="19. Stand & Änderungen">
          <p>
            Stand dieser Datenschutzerklärung: Juni 2026. Wir passen sie an, wenn sich
            die Verarbeitung oder die Rechtslage ändert.
          </p>
        </Abschnitt>
      </>
    ),
  },
  agb: {
    titel: 'Nutzungsbedingungen',
    inhalt: (
      <>
        <Abschnitt titel="1. Geltungsbereich & Anbieter">
          <p>
            Diese Nutzungsbedingungen gelten für die Nutzung der App und Web-Anwendung
            „Topfplan" (nachfolgend „App") in der jeweils bei Vertragsschluss gültigen
            Fassung. Anbieter und Vertragspartner ist {BETREIBER.name}, {BETREIBER.ort}
            (vollständige Anschrift siehe Impressum), E-Mail: {BETREIBER.email}
            (nachfolgend „wir").
          </p>
          <p>
            Die App richtet sich an Verbraucherinnen und Verbraucher. Mit der
            Registrierung erkennst du diese Bedingungen an.
          </p>
        </Abschnitt>

        <Abschnitt titel="2. Vertragsgegenstand & Leistungsbeschreibung">
          <p>
            Topfplan ist ein KI-gestützter Küchenassistent. Funktionen umfassen u. a.
            Rezeptverwaltung und -erstellung, Wochen- und Essensplanung, Vorrats- und
            Einkaufslistenverwaltung, das Finden von Angeboten sowie einen
            Schritt-für-Schritt-Kochmodus. Ein Teil der Funktionen nutzt
            KI-Dienste (Texterzeugung, Bilderzeugung, Sprachausgabe).
          </p>
          <p>
            Wir entwickeln die App fortlaufend weiter und können einzelne Funktionen
            ändern, ergänzen oder einstellen, soweit dies für dich zumutbar ist und der
            Kernzweck der App erhalten bleibt.
          </p>
        </Abschnitt>

        <Abschnitt titel="3. Registrierung, Konto & Haushalt">
          <p>
            Für die Nutzung ist ein Konto erforderlich. Du bist verpflichtet, wahre
            Angaben zu machen, deine Zugangsdaten geheim zu halten und uns einen
            Missbrauch unverzüglich mitzuteilen. In einem Haushalt können mehrere
            Personen geführt und weitere Nutzer eingeladen werden; die Kontoinhaberin
            bzw. der Kontoinhaber ist für die Nutzung durch eingeladene Personen
            mitverantwortlich.
          </p>
        </Abschnitt>

        <Abschnitt titel="4. Preise, Abo & Zahlung">
          <p>
            Die App ist in einer <b>kostenlosen Basisversion</b> nutzbar: Alle Funktionen
            ohne KI sind frei; für KI-Funktionen steht ein monatliches Gratis-Kontingent
            zur Verfügung (aktuell 10 KI-Text-Aktionen und 3 KI-Bilder pro Kalendermonat).
            Bei der Registrierung erhältst du zusätzlich einen <b>14-tägigen kostenlosen
            Vollzugang</b> (Testphase), der ohne Kündigung automatisch endet und nicht
            kostenpflichtig wird.
          </p>
          <p>
            Für die unbeschränkte Nutzung bieten wir das <b>Topfplan-Abo</b> (aktuell
            9,99 € pro Monat) an: alle KI-Funktionen inklusive, KI-Textnutzung ohne festes
            Limit sowie ein monatliches KI-Bild-Kontingent (aktuell 50 Bilder/Monat). Das
            Abo ist ein wiederkehrendes Abonnement mit monatlicher Laufzeit, das sich bis
            zur Kündigung automatisch um je einen Monat verlängert. Zusätzliche KI-Bilder
            über das jeweilige Kontingent hinaus kannst du über das einmalige
            <b> Foto-Paket</b> (aktuell 12,99 € für 75 Bild-Credits) erwerben; die Credits
            verfallen nicht und werden verbraucht, sobald ein Monatskontingent ausgeschöpft
            ist.
          </p>
          <p>
            Die jeweils gültigen Preise, Kontingente und dein aktueller Verbrauch werden
            dir vor dem Kauf und in der App transparent angezeigt. Die Zahlung wird über
            unseren Zahlungsdienstleister <b>Stripe</b> abgewickelt. {BETREIBER.ust} Käufe erfolgen
            ausschließlich über unsere Web-Anwendung; innerhalb einer etwaigen App-Store-
            Fassung wird kein Kauf angeboten.
          </p>
        </Abschnitt>

        <Abschnitt titel="5. Widerrufsrecht für Verbraucher">
          <p>
            Dir steht als Verbraucher ein gesetzliches Widerrufsrecht zu.
          </p>
          <p>
            <b>Widerrufsbelehrung.</b> Du hast das Recht, binnen vierzehn Tagen ohne
            Angabe von Gründen diesen Vertrag (Abschluss des Topfplan-Abos bzw. Kauf des
            Foto-Pakets) zu widerrufen. Die Widerrufsfrist beträgt vierzehn Tage ab dem Tag
            des Vertragsschlusses. Um dein Widerrufsrecht auszuüben, musst du uns ({BETREIBER.name},
            E-Mail: {BETREIBER.email}) mittels einer eindeutigen Erklärung
            (z. B. ein mit der Post versandter Brief oder eine E-Mail) über deinen
            Entschluss, diesen Vertrag zu widerrufen, informieren. Zur Wahrung der Frist
            genügt die rechtzeitige Absendung der Mitteilung. Im Falle eines wirksamen
            Widerrufs erstatten wir dir bereits geleistete Zahlungen unverzüglich zurück.
            Die kostenlose Basisnutzung und die Testphase lösen mangels Zahlung kein
            Widerrufsrecht aus.
          </p>
          <p>
            <b>Vorzeitiges Erlöschen / Wertersatz.</b> Bei der Bereitstellung digitaler
            Inhalte und Dienstleistungen erlischt das Widerrufsrecht, wenn wir mit der
            Ausführung begonnen haben, nachdem du ausdrücklich zugestimmt hast, dass wir vor
            Ablauf der Widerrufsfrist mit der Ausführung beginnen, und du deine Kenntnis
            davon bestätigt hast, dass du durch diese Zustimmung dein Widerrufsrecht
            verlierst. Verlangst du bei einer Dienstleistung (z. B. dem Abo) die Ausführung
            schon während der Widerrufsfrist, schuldest du bei wirksamem Widerruf einen
            angemessenen Wertersatz für die bis zum Widerruf bereits erbrachte Leistung
            (anteilig für den genutzten Zeitraum).
          </p>
          <p>
            <b>Muster-Widerrufsformular.</b> (Wenn du den Vertrag widerrufen willst, fülle
            dieses Formular aus und sende es zurück.) An: {BETREIBER.name},
            {BETREIBER.email} — Hiermit widerrufe(n) ich/wir den von mir/uns
            abgeschlossenen Vertrag über das Topfplan-Abo / das Foto-Paket der App „Topfplan" —
            Bestellt am: … — Name: … — Anschrift: … — Datum: … — (Unterschrift bei
            Mitteilung auf Papier).
          </p>
        </Abschnitt>

        <Abschnitt titel="6. Pflichten & zulässige Nutzung">
          <p>
            Du verpflichtest dich, die App nicht missbräuchlich zu nutzen, insbesondere
            keine rechtswidrigen, beleidigenden oder rechteverletzenden Inhalte
            einzugeben, keine Schutzmechanismen zu umgehen und die App nicht automatisiert
            in einem die Funktionsfähigkeit beeinträchtigenden Umfang abzufragen. Für von
            dir eingegebene Inhalte bist du selbst verantwortlich.
          </p>
        </Abschnitt>

        <Abschnitt titel="7. KI-Funktionen & Hinweise">
          <p>
            KI-generierte Ausgaben (z. B. Rezepte, Mengen, Nährwert-, Allergen- oder
            Angebotsangaben) können <b>fehlerhaft oder unvollständig</b> sein. Sie dienen
            der Unterstützung und stellen keine medizinische, ernährungswissenschaftliche
            oder sonstige fachliche Beratung dar. Prüfe insbesondere bei Allergien,
            Unverträglichkeiten und Hygiene stets eigenverantwortlich. Bei kritischen
            Fragen wende dich an qualifizierte Fachpersonen.
          </p>
        </Abschnitt>

        <Abschnitt titel="8. Verfügbarkeit">
          <p>
            Wir bemühen uns um eine hohe Verfügbarkeit, schulden diese aber nicht
            unterbrechungsfrei. Wartungsarbeiten, Störungen bei Dritt-Diensten (z. B.
            Hosting-, Zahlungs- oder KI-Anbietern) oder höhere Gewalt können die
            Erreichbarkeit vorübergehend einschränken.
          </p>
        </Abschnitt>

        <Abschnitt titel="9. Haftung">
          <p>
            Wir haften unbeschränkt bei Vorsatz und grober Fahrlässigkeit sowie bei
            Verletzung von Leben, Körper oder Gesundheit und nach dem
            Produkthaftungsgesetz. Bei einfacher Fahrlässigkeit haften wir nur bei
            Verletzung einer wesentlichen Vertragspflicht (Kardinalpflicht) und der Höhe
            nach begrenzt auf den vertragstypisch vorhersehbaren Schaden. Im Übrigen ist
            die Haftung ausgeschlossen.
          </p>
        </Abschnitt>

        <Abschnitt titel="10. Laufzeit & Kündigung">
          <p>
            Das Nutzungsverhältnis läuft auf unbestimmte Zeit. Das <b>Topfplan-Abo</b> hat
            eine monatliche Laufzeit und verlängert sich automatisch um je einen weiteren
            Monat, sofern es nicht gekündigt wird. Du kannst das Abo jederzeit zum Ende der
            laufenden Abrechnungsperiode kündigen (in den Konto-Einstellungen bzw. per
            Nachricht an {BETREIBER.email}); nach Ablauf wechselst du automatisch
            zurück in die kostenlose Basisversion, ohne dass Daten verloren gehen. Bereits
            erworbene Foto-Credits bleiben von einer Abo-Kündigung unberührt.
          </p>
          <p>
            Das Konto selbst kannst du jederzeit durch Löschung in den Einstellungen
            beenden; dabei werden deine Daten nach Maßgabe der Datenschutzerklärung entfernt
            und ein etwaiges laufendes Abo sowie verbleibende Credits enden. Wir können das
            Verhältnis mit angemessener Frist oder bei schwerwiegenden Verstößen
            außerordentlich kündigen.
          </p>
        </Abschnitt>

        <Abschnitt titel="11. Schlussbestimmungen">
          <p>
            Es gilt das Recht der Bundesrepublik Deutschland unter Ausschluss des
            UN-Kaufrechts; zwingende Verbraucherschutzvorschriften deines Wohnsitzstaates
            bleiben unberührt. Die Plattform der EU zur Online-Streitbeilegung findest du
            unter https://ec.europa.eu/consumers/odr/. Wir sind zur Teilnahme an einem
            Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle nicht
            verpflichtet und nicht bereit. Sollten einzelne Bestimmungen unwirksam sein,
            bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.
          </p>
          <p className="text-xs text-muted">Stand: Juli 2026</p>
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
        {/* § 312k BGB: dauerhaft verfügbar, gut lesbar und OHNE Anmeldung erreichbar.
            Deshalb ein echter Link auf /kuendigen statt eines Modals in der App. */}
        <a href="/kuendigen" className="font-semibold text-muted transition hover:text-ink hover:underline">
          Verträge hier kündigen
        </a>
        <span aria-hidden>·</span>
        {/* Google Play: öffentliche Web-Adresse für die Kontolöschung (zusätzlich zum
            In-App-Weg „Mehr → Konto löschen"). Kein Kauf-/Abo-Link (Anti-Steering). */}
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

// IT-Recht-Kanzlei JavaScript-Embeds je Dokument (laden + aktualisieren sich selbst).
// Pro Rechtstext eine eigene Embed-URL aus dem Mandantenportal eintragen.
// Optional per Build-Variable VITE_ITRK_IMPRESSUM_URL; leer = statischer Fallback oben.
const ITRK_EMBED = {
  ...(ENV.VITE_ITRK_IMPRESSUM_URL ? { impressum: ENV.VITE_ITRK_IMPRESSUM_URL } : {}),
  // datenschutz: nutzt den gespeicherten IT-Recht-Text (Tabelle rechtstext)
  // agb: 'https://itrk.legal/….html',
}

// Lädt & rendert den Inhalt EINES Rechtsdokuments einheitlich – genutzt vom Footer-Modal
// UND der Standalone-Seite, damit überall derselbe echte Text erscheint:
//   1) IT-Recht-Embed (z. B. Impressum)  2) in der DB gespeicherter Text (z. B. Datenschutz)
//   3) statischer Fallback aus DOKUMENTE (z. B. Nutzungsbedingungen).
function RechtInhalt({ doc, withTitle = false }) {
  const embedUrl = ITRK_EMBED[doc]
  const fallback = DOKUMENTE[doc] || DOKUMENTE.datenschutz
  const [extern, setExtern] = useState(undefined)  // undefined=lädt, null=keiner, {…}=da
  useEffect(() => {
    if (embedUrl) {
      // IT-Recht lädt den Text in die .itrk-legaltext-Div (Auto-Höhe via Skript).
      const s = document.createElement('script')
      s.src = 'https://www.it-recht-kanzlei.de/js/itrk-legaltext.js'
      s.async = true
      document.body.appendChild(s)
      return () => { try { document.body.removeChild(s) } catch { /* ignore */ } }
    }
    let aktiv = true
    api.rechtstext(doc).then((r) => aktiv && setExtern(r)).catch(() => aktiv && setExtern(null))
    return () => { aktiv = false }
  }, [doc, embedUrl])

  // S-4: Der Rechtstext kommt von außen (Push der IT-Recht Kanzlei auf /api/itrk) und wird
  // unten per dangerouslySetInnerHTML gerendert. Serverseitig wird er beim Speichern auf
  // eine Tag-/Attribut-Whitelist reduziert (app/itrk.py, nh3) – hier wird er ZUSÄTZLICH vor
  // dem Rendern bereinigt, damit auch vor dem Fix gespeicherte Alt-Texte keinen gespeicherten
  // XSS mehr tragen (der Session-Token liegt im localStorage).
  const sicherHtml = useMemo(
    () => DOMPurify.sanitize(extern?.html ?? '', { USE_PROFILES: { html: true } }),
    [extern],
  )

  const Titel = ({ children }) => (withTitle ? <h1 className="font-dish text-4xl leading-tight text-ink">{children}</h1> : null)
  if (embedUrl) return <div className="itrk-legaltext" data-itrk-legaltext-url={embedUrl} />
  if (extern === undefined) return <div className="flex justify-center py-16"><Spinner /></div>
  if (extern) return (
    <>
      <Titel>{extern.titel || fallback.titel}</Titel>
      <div className={`rechtstext-html text-sm leading-relaxed text-ink/80 ${withTitle ? 'mt-5' : ''}`} dangerouslySetInnerHTML={{ __html: sicherHtml }} />
    </>
  )
  return (
    <>
      <Titel>{fallback.titel}</Titel>
      <div className={withTitle ? 'mt-5 space-y-4' : 'space-y-4'}>{fallback.inhalt}</div>
    </>
  )
}

// Öffentliche Standalone-Seite für EIN Rechtsdokument (ohne Login) – für E-Mail-Links
// und die Play-Store-Datenschutz-URL. Aufruf über ?recht=datenschutz|impressum|agb.
export function RechtSeite({ doc, onClose }) {
  return (
    <div className="min-h-screen px-5 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <div className="topfplan-wortmarke text-3xl leading-none">Topfplan</div>
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
