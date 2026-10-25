"""Kündigungsbutton nach § 312k BGB – zweistufig mit Bestätigungslink.

Die Vorschrift verlangt für über eine Website geschlossene Verträge einen dauerhaft
verfügbaren, gut lesbaren Kündigungsbutton, der **ohne Anmeldung** erreichbar ist, zu einer
Bestätigungsseite führt und dem Verbraucher den Zugang seiner Erklärung **sofort in Textform**
bestätigt – mit Inhalt, Datum/Uhrzeit des Zugangs und dem Vertragsende.

Umsetzung (zweistufig seit der Behebung von S-1, Vorbild Kontolöschung `kontoloeschung.py`):
  • Stufe 1 – `POST /auth/kuendigung`: Jede Erklärung wird **sofort** in `kuendigung`
    protokolliert (Nachweis, append-only; Zugang und Fristwahrung bleiben erhalten) – auch
    wenn zur angegebenen E-Mail kein Konto existiert. Die HTTP-Antwort ist für „Konto
    vorhanden" und „kein Konto" identisch (keine Abo-Enumeration, S-2) und enthält keine
    kontoabhängigen Angaben. Kontosuche, Bestätigungs-Token und Mailversand laufen
    entkoppelt im Hintergrund (BackgroundTasks), damit auch die Antwortzeit nichts verrät.
    Besteht zur E-Mail ein Konto, geht eine Mail mit Bestätigungslink raus (Token: 256 Bit
    zufällig, nur sha256-Hash in `passwort_reset`, Präfix `kd1-` zur Zweckbindung, 1 Stunde
    gültig, einmalig). Diese Mail enthält bereits die Zugangsbestätigung in Textform
    (Inhalt der Erklärung + Eingangszeitpunkt).
  • Stufe 2 – `POST /auth/kuendigung/bestaetigen`: Erst der Klick auf den Link kündigt das
    laufende Stripe-Abo zum Periodenende (`stripe_pay.kuendige_abo`) und vervollständigt die
    Nachweiszeile (Wirkung, Vertragsende, Bestätigungszeit). Das Zielkonto wird aus dem
    Token (dessen Nutzer) ermittelt – **nie** aus dem Request. Anschließend geht die
    eigentliche Kündigungsbestätigung per Mail raus (inkl. Vertragsende, § 312k).

Missbrauchs-Abwägung: Der Endpunkt ist notwendigerweise ohne Login erreichbar – ein
Login-Zwang wäre der Vorschrift zuwider. Seit der S-1-Behebung kann aber niemand mehr ein
fremdes Abo allein mit Kenntnis der E-Mail-Adresse kündigen: die Wirkung erfordert den
Zugriff auf das Postfach (Link-Klick). Rate-Limits je IP und je E-Mail in `rest.py` bremsen
Flut/E-Mail-Bombing. Die Tokens sind zweckgebunden: ein Kündigungslink setzt nie ein
Passwort zurück und löscht nie ein Konto – umgekehrt gilt dasselbe.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from . import mailer, stripe_pay
from .db import acquire

log = logging.getLogger("koch")

ARTEN = ("ordentlich", "ausserordentlich")
TOKEN_GUELTIG_STUNDEN = 1
EMAIL_MAX_ZEICHEN = 254                  # RFC 5321: längste zulässige Adresse (K-2)
VERTRAG_TEXT = "Sapio-Abo"               # K-3: fester Vertragstext für unauthentifizierte Link-Mail

# Wirkungs-Stände der Nachweiszeile in `kuendigung`:
WIRKUNG_WARTET = "wartet_bestaetigung"   # Zugang protokolliert, Bestätigung steht aus
WIRKUNG_LINK = "link_versandt"           # Bestätigungslink zugestellt, Klick steht aus
WIRKUNG_KEIN_KONTO = "kein_konto"        # zur E-Mail existiert kein Konto
WIRKUNG_FEHLER = "fehler"                # Stripe-Aufruf fehlgeschlagen (K-4: Link bleibt
                                         # freigegeben, die Zeile kann erneut abgeschlossen
                                         # werden – kein stiller Fehlschlag)

# K-3: Der freie Text `grund` stammt vom unauthentifizierten Absender. In der Link-Mail
# (Stufe 1) wird er gekappt, damit niemand ~2 KB eigenen Text als Absender „Sapio" an
# fremde Adressen schicken kann. Vollständig steht er erst in der Bestätigungsmail (Stufe 2),
# die nach dem Klick – also an den nachgewiesenen Postfach-Inhaber – geht.
GRUND_KURZ_ZEICHEN = 200

# K-1: Der Bestätigungs-Token trägt die id seiner Nachweiszeile (`kd1-<kid>.<random>`),
# damit Stufe 2 genau die Zeile abschließt, zu der der Link gehört – nicht „die jüngste
# wartende Zeile dieser E-Mail", die ein Dritter nachgeschoben haben könnte.
TOKEN_KID_MAX_STELLEN = 19               # bigint; längere Ziffernfolgen sind kein kid

# K-6: `asyncio.create_task` ohne Referenz kann vom GC eingesammelt werden, bevor er läuft.
_hintergrund_tasks: set[asyncio.Task] = set()


def _clean(s, maxlen: int) -> str | None:
    """Freitext-Feld auf `maxlen` kappen. K-7: Nur `str` gilt – ein JSON-Wert wie
    `{"name": 5}` zählt als leer (→ 400 wegen fehlender Pflichtangabe, nie 500)."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    return s[:maxlen] or None


def _text(s) -> str:
    """K-7: String-Eingabe normalisieren, alles andere als leer behandeln."""
    return s.strip() if isinstance(s, str) else ""


def _kid_aus_token(token: str) -> int | None:
    """K-1: `kid` aus `kd1-<kid>.<random>` lesen; None, wenn der Token keine Zeilen-
    Bindung trägt (z. B. Alt-Link oder Anlage ohne Nachweiszeile). Die Ziffernfolge ist
    hart begrenzt, damit eine Megabyte-„id" nicht in `int()` läuft."""
    from .userauth import KUEND_TOKEN_PREFIX

    if not isinstance(token, str) or not token.startswith(KUEND_TOKEN_PREFIX):
        return None
    rest = token[len(KUEND_TOKEN_PREFIX):]
    kid_txt, punkt, _zufall = rest.partition(".")
    if not punkt or not kid_txt or len(kid_txt) > TOKEN_KID_MAX_STELLEN:
        return None
    if not kid_txt.isdigit():
        return None
    try:
        return int(kid_txt)
    except ValueError:  # pragma: no cover – über isdigit()/Stellenzahl nicht erreichbar
        return None


async def annehmen(daten: dict, ip: str | None = None, background=None) -> dict:
    """Stufe 1: Nimmt eine Kündigungserklärung an und protokolliert den Zugang sofort.

    Gibt für JEDE gültige Eingabe dieselbe Antwort zurück – ohne `vertrag_bis` und ohne
    sonstige kontoabhängige Felder (S-2: keine Abo-Enumeration). Kontosuche, Token-Anlage
    und Mailversand laufen über `background` (FastAPI-`BackgroundTasks`) entkoppelt nach
    der Antwort; `background=None` (z. B. Tests) weicht auf `asyncio.create_task` aus.
    Bei ungültiger Eingabe: {"error": ...}."""
    email = _text(daten.get("email")).lower()
    # K-2/K-7: nur Strings und höchstens 254 Zeichen (RFC-5321-Maximum einer Adresse) –
    # eine Megabyte-„E-Mail" wird abgewiesen, statt in Nachweis, Mail und Rate-Limit zu
    # landen. Formatfehler sind keine Existenz-Auskunft, die Antwort bleibt neutral (S-2).
    if "@" not in email or "." not in email or len(email) > EMAIL_MAX_ZEICHEN:
        return {"error": "Bitte die E-Mail-Adresse deines Sapio-Kontos angeben."}
    art = _text(daten.get("art")).lower() or "ordentlich"
    if art not in ARTEN:
        art = "ordentlich"
    name = _clean(daten.get("name"), 120)
    vertrag = _clean(daten.get("vertrag"), 120) or VERTRAG_TEXT
    grund = _clean(daten.get("grund"), 2000)
    if art == "ausserordentlich" and not grund:
        return {"error": "Für eine außerordentliche Kündigung bitte einen Grund angeben."}
    zum = daten.get("zum_datum") or None
    zum_datum = None
    if isinstance(zum, str) and zum:
        try:
            zum_datum = date.fromisoformat(zum[:10])
        except ValueError:
            zum_datum = None
    elif isinstance(zum, date):
        zum_datum = zum

    # 1) Nachweis schreiben – IMMER und SOFORT (§ 312k: Zugang und Fristwahrung hängen am
    #    Eingang der Erklärung, nicht an der Bestätigung). `account_id`, `wirkung` und
    #    `vertrag_bis` werden im Hintergrund bzw. nach der Bestätigung ergänzt.
    eingegangen = None
    kid = None
    try:
        async with acquire(bypass=True) as con:
            row = await con.fetchrow(
                """INSERT INTO kuendigung
                     (email, name, vertrag, art, grund, zum_datum, wirkung, ip)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   RETURNING id, eingegangen""",
                email, name, vertrag, art, grund, zum_datum, WIRKUNG_WARTET, _clean(ip, 60))
        kid, eingegangen = row["id"], row["eingegangen"]
    except Exception as e:  # noqa: BLE001
        # Ohne Tabelle o. Ä.: wenigstens ins Log, damit die Erklärung nicht verloren geht.
        log.error("kuendigung: NACHWEIS FEHLGESCHLAGEN – %s | %s | %s | %s",
                  email, art, vertrag, e)

    # 2) Entkoppelt (gleiche Antwortzeit für alle – kein Existenz-Seitenkanal, S-2):
    #    Konto suchen → Bestätigungs-Token anlegen → Link-Mail mit Zugangsbestätigung.
    auftrag = {"email": email, "name": name, "vertrag": vertrag, "art": art,
               "grund": grund, "eingegangen": eingegangen}
    if background is not None:
        background.add_task(_link_versenden, kid, auftrag)
    else:
        # K-6: Referenz halten, sonst kann CPython den Task vor dem Lauf einsammeln
        # (heute nur der Test-Pfad; produktiv läuft alles über BackgroundTasks).
        task = asyncio.create_task(_link_versenden(kid, auftrag))
        _hintergrund_tasks.add(task)
        task.add_done_callback(_hintergrund_tasks.discard)

    # 3) Empfangsbestätigung – bewusst identisch für „Konto vorhanden" und „kein Konto".
    return {
        "ok": True,
        "eingegangen": (eingegangen or datetime.now()).isoformat(timespec="seconds"),
        "vertrag": vertrag,
        "art": art,
        "hinweis": ("Deine Kündigung ist eingegangen und gilt als zu diesem Zeitpunkt "
                    "erklärt. Wir haben dir eine E-Mail geschickt: Falls zu dieser Adresse "
                    "ein Sapio-Konto besteht, enthält sie einen Bestätigungslink – erst "
                    "dein Klick darauf beendet das Abo zum Ende der bereits bezahlten "
                    "Laufzeit. Bitte prüfe auch den Spam-Ordner."),
    }


async def _link_versenden(kid: int | None, auftrag: dict) -> None:
    """Hintergrund-Schritt zu Stufe 1: Konto zur E-Mail suchen, einmaligen Bestätigungs-
    Token anlegen (256 Bit, nur Hash in `passwort_reset`, Präfix kd1-, K-1: mit der id der
    Nachweiszeile als `kd1-<kid>.<random>`) und die Link-Mail schicken. Ohne Konto wird die
    Nachweiszeile nur auf `kein_konto` ergänzt – es geht bewusst KEINE Mail raus (neutrale
    Linie wie bei der Kontolöschung, keine Auskunft)."""
    from .userauth import KUEND_TOKEN_PREFIX, _hash_token

    email = auftrag["email"]
    token = None
    try:
        async with acquire(bypass=True) as con:
            # Der Nutzer kann Mitglied mehrerer Haushalte sein – Ziel ist das Konto, dessen
            # Owner er ist, sonst das erste zugeordnete (wie vor der Zweistufigkeit).
            # K-5: nur aktive Logins, analog `kontoloeschung.anfordern` – deaktivierte
            # Konten sollen über den öffentlichen Weg kein Abo mehr kündigen können.
            row = await con.fetchrow(
                """SELECT u.id AS user_id, m.account_id
                     FROM app_user u
                     JOIN account_mitglied m ON m.user_id = u.id
                    WHERE lower(u.email::text) = $1
                      AND u.aktiv
                    ORDER BY (m.rolle = 'owner') DESC, m.account_id
                    LIMIT 1""", email)
            if row is None:
                if kid:
                    await con.execute(
                        "UPDATE kuendigung SET wirkung = $2 WHERE id = $1",
                        kid, WIRKUNG_KEIN_KONTO)
                return
            if kid:
                await con.execute(
                    "UPDATE kuendigung SET account_id = $2 WHERE id = $1",
                    kid, int(row["account_id"]))
            zufall = secrets.token_urlsafe(32)   # 256 Bit, base64url (enthält nie einen Punkt)
            token = (f"{KUEND_TOKEN_PREFIX}{kid}.{zufall}" if kid
                     else KUEND_TOKEN_PREFIX + zufall)
            ablauf = (datetime.now(timezone.utc)
                      + timedelta(hours=TOKEN_GUELTIG_STUNDEN))
            await con.execute(
                "INSERT INTO passwort_reset (user_id, token_hash, ablauf) "
                "VALUES ($1,$2,$3)",
                int(row["user_id"]), _hash_token(token), ablauf)
    except Exception as e:  # noqa: BLE001 – nie 500; ohne Token läuft der Link ins Leere
        log.warning("kuendigung: Bestätigungslink-Vorbereitung für %s fehlgeschlagen: %s",
                    email, e)
        return
    try:
        res = await mailer.send_kuendigung_link(email, token, auftrag)
        if res.get("ok") and kid:
            async with acquire(bypass=True) as con:
                await con.execute(
                    "UPDATE kuendigung SET wirkung = $2 WHERE id = $1", kid, WIRKUNG_LINK)
    except Exception as e:  # noqa: BLE001 – Token läuft einfach ab
        log.warning("kuendigung: Link-Mail an %s fehlgeschlagen: %s", email, e)


# K-1: Abschluss der Nachweiszeile, auf die der Token zeigt. `id` UND E-Mail müssen
# stimmen, damit ein Token nie eine fremde Zeile derselben Adresse abschließt.
# `wirkung='fehler'` zählt als offen, damit ein nach K-4 freigegebener Link die Zeile beim
# zweiten Versuch vervollständigen kann.
_ABSCHLUSS_GEBUNDEN = """UPDATE kuendigung
      SET wirkung = $3, vertrag_bis = $4, bestaetigt_am = now()
    WHERE id = $1
      AND lower(email) = lower($2)
      AND wirkung IN ($5, $6, $7)
    RETURNING name, vertrag, art, grund, eingegangen"""

# Fallback ohne Zeilen-Bindung (Nachweis-INSERT fehlgeschlagen, oder Link aus einer
# Fassung vor K-1): wie bisher die jüngste offene Erklärung derselben Adresse.
_ABSCHLUSS_JUENGSTE = """UPDATE kuendigung
      SET wirkung = $2, vertrag_bis = $3, bestaetigt_am = now()
    WHERE id = (SELECT id FROM kuendigung
                 WHERE lower(email) = lower($1)
                   AND wirkung IN ($4, $5)
                 ORDER BY eingegangen DESC
                 LIMIT 1)
    RETURNING name, vertrag, art, grund, eingegangen"""

# K-4: Meldung, wenn die Wirkung (Stripe) fehlgeschlagen ist – statt eines `ok: true`,
# das eine gekündigte Abo-Laufzeit vorgaukelt, die es nicht gibt.
FEHLER_WIRKUNG = (
    "Deine Kündigung ist bei uns eingegangen und bleibt gültig – wir konnten dein Abo "
    "aber gerade nicht umstellen. Bitte klick den Bestätigungslink in der E-Mail noch "
    "einmal an. Klappt es erneut nicht, schreib uns kurz an den Support (siehe Impressum), dann "
    "kündigen wir es für dich. Es wird nichts doppelt berechnet.")


async def _nachweis_abschliessen(kid: int | None, email: str, wirkung: str,
                                 vertrag_bis: str | None) -> dict:
    """Schließt die Nachweiszeile ab (Wirkung, Vertragsende, Bestätigungszeit) und liefert
    ihren Inhalt für die Bestätigungsmail. Mit `kid` (K-1) wird exakt die Zeile des Tokens
    getroffen und zusätzlich auf dieselbe E-Mail geprüft; ohne `kid` greift der Fallback
    auf die jüngste offene Zeile dieser Adresse. Nie 500: schlägt der Abschluss fehl, ist
    die Wirkung trotzdem eingetreten und die leere Bestätigung geht ins Log."""
    bis = None
    if vertrag_bis:
        try:
            bis = date.fromisoformat(vertrag_bis)
        except ValueError:
            log.warning("kuendigung: Vertragsende %r nicht lesbar", vertrag_bis)
    try:
        async with acquire(bypass=True) as con:
            if kid is not None:
                row = await con.fetchrow(
                    _ABSCHLUSS_GEBUNDEN, kid, email, wirkung, bis,
                    WIRKUNG_LINK, WIRKUNG_WARTET, WIRKUNG_FEHLER)
            else:
                row = await con.fetchrow(
                    _ABSCHLUSS_JUENGSTE, email, wirkung, bis,
                    WIRKUNG_LINK, WIRKUNG_WARTET)
            return dict(row) if row else {}
    except Exception as e:  # noqa: BLE001
        log.warning("kuendigung: Nachweis-Abschluss für %s fehlgeschlagen: %s", email, e)
        return {}


async def _token_freigeben(token_id: int | None) -> None:
    """K-4: macht einen Bestätigungslink nach einem fehlgeschlagenen Stripe-Aufruf erneut
    nutzbar. Unbedenklich, weil nur der Postfach-Inhaber den Token kennt und
    `kuendige_abo` idempotent ist (`cancel_at_period_end`)."""
    if not token_id:
        return
    try:
        async with acquire(bypass=True) as con:
            await con.execute(
                "UPDATE passwort_reset SET benutzt=false WHERE id=$1", token_id)
    except Exception as e:  # noqa: BLE001 – Link bleibt verbraucht, Support greift ein
        log.warning("kuendigung: Token %s nicht freigegeben: %s", token_id, e)


async def bestaetigen(token) -> dict:
    """Stufe 2: Führt die Kündigung aus – NUR mit gültigem, unbenutztem kd1-Token aus der
    Link-Mail. Das Zielkonto kommt aus dem Token (dessen Nutzer), nie aus dem Request:
    wer kein Postfach hat, kann kein fremdes Abo kündigen (S-1). K-1: Der Token trägt die
    id seiner Nachweiszeile (`kd1-<kid>.<random>`), abgeschlossen wird genau diese Zeile –
    eine von einem Dritten auf dieselbe Adresse nachgeschobene Erklärung bleibt offen."""
    from .userauth import KUEND_TOKEN_PREFIX, _hash_token

    # K-7: auch ein Nicht-String (z. B. {"token": 5}) zählt als ungültiger Link, nie 500.
    if not isinstance(token, str) or not token.startswith(KUEND_TOKEN_PREFIX):
        # Zweckbindung: u. a. Passwort-Reset- und Kontolösch-Tokens sind hier ungültig.
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}
    kid = _kid_aus_token(token)
    th = _hash_token(token)
    jetzt = datetime.now(timezone.utc)
    token_id = None
    ziel = None
    try:
        async with acquire(bypass=True) as con:
            async with con.transaction():
                # FOR UPDATE: zwei parallele Klicks auf denselben Link werden
                # serialisiert, der zweite sieht benutzt=true (einmalig nutzbar).
                r = await con.fetchrow(
                    "SELECT id, user_id, ablauf, benutzt FROM passwort_reset "
                    "WHERE token_hash=$1 FOR UPDATE", th)
                if not r or r["benutzt"] or r["ablauf"] < jetzt:
                    return {"error": "Dieser Link ist ungültig oder abgelaufen."}
                await con.execute(
                    "UPDATE passwort_reset SET benutzt=true WHERE id=$1", r["id"])
                token_id = int(r["id"])
                uid = int(r["user_id"])
                ziel = await con.fetchrow(
                    """SELECT m.account_id, u.email::text AS email
                         FROM app_user u
                         LEFT JOIN account_mitglied m ON m.user_id = u.id
                        WHERE u.id = $1
                        ORDER BY (m.rolle = 'owner') DESC NULLS LAST,
                                 m.account_id NULLS LAST
                        LIMIT 1""", uid)
    except Exception as e:  # noqa: BLE001
        log.warning("kuendigung: Token-Prüfung fehlgeschlagen: %s", e)
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}

    if ziel is None or not ziel["email"]:
        # Nutzer zwischen Anforderung und Klick gelöscht (Cascade nimmt auch den Token
        # mit) – rein defensiv, regulär unerreichbar.
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}
    email = ziel["email"]
    account_id = int(ziel["account_id"]) if ziel["account_id"] is not None else None

    # Wirkung herstellen: Stripe-Abo zum Periodenende kündigen (zieht ohne Abo nur den
    # Kontostand; die Erklärung gilt so oder so als bestätigt).
    wirkung, vertrag_bis = WIRKUNG_KEIN_KONTO, None
    if account_id is not None:
        try:
            res = await stripe_pay.kuendige_abo(account_id)
            if res.get("error"):
                wirkung = WIRKUNG_FEHLER
            else:
                vertrag_bis = res.get("bis")
                wirkung = "stripe_periodenende" if res.get("hatte_abo") else "kein_abo"
        except Exception as e:  # noqa: BLE001 – Erklärung bleibt wirksam, Support sieht es
            log.warning("kuendigung: Abo-Kündigung fehlgeschlagen (Konto %s): %s",
                        account_id, e)
            wirkung = WIRKUNG_FEHLER

    daten = await _nachweis_abschliessen(kid, email, wirkung, vertrag_bis)

    if wirkung == WIRKUNG_FEHLER:
        # K-4: kein stiller Fehlschlag einer bezahlrelevanten Aktion. Der Stripe-Aufruf
        # ist fehlgeschlagen, also gibt es kein `ok: true` und keine Bestätigungsmail mit
        # einem Vertragsende, das es nicht gibt. Der Link wird wieder freigegeben (die
        # Kündigung ist idempotent), der Nutzer sieht den Fehler und kann es erneut
        # versuchen; die Nachweiszeile bleibt mit `wirkung='fehler'` für den Support
        # auffindbar und kann beim zweiten Klick abgeschlossen werden.
        await _token_freigeben(token_id)
        return {"error": FEHLER_WIRKUNG}

    # Kündigungsbestätigung in Textform (§ 312k) – JETZT, mit Vertragsende (S-2: nur in
    # die Mail an den Postfach-Inhaber, nie in eine öffentliche Antwort).
    daten["vertrag_bis"] = vertrag_bis
    daten["wirkung"] = wirkung
    try:
        await mailer.send_kuendigung_bestaetigung(email, daten)
    except Exception as e:  # noqa: BLE001
        log.warning("kuendigung: Bestätigungsmail an %s fehlgeschlagen: %s", email, e)

    eing = daten.get("eingegangen")
    return {
        "ok": True,
        "gekuendigt": True,
        "eingegangen": eing.isoformat(timespec="seconds") if hasattr(eing, "isoformat") else None,
        "vertrag": daten.get("vertrag") or VERTRAG_TEXT,
        "vertrag_bis": vertrag_bis,
        "hinweis": ("Deine Kündigung ist bestätigt – die Einzelheiten stehen in der "
                    "Bestätigungsmail. Dein Abo endet zum Ende der bereits bezahlten "
                    "Laufzeit; dein Konto läuft danach kostenlos weiter und deine Rezepte, "
                    "Pläne und Vorräte bleiben erhalten."),
    }


def _tabelle(zeilen: list[tuple[str, str]]) -> str:
    """Gemeinsames Tabellen-Layout für beide Kündigungs-Mails."""
    return "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#9c9384;vertical-align:top">{k}</td>'
        f'<td style="padding:4px 0;color:#2a2018"><b>{v}</b></td></tr>'
        for k, v in zeilen)


def _art_txt(art: str | None) -> str:
    return "außerordentliche Kündigung" if art == "ausserordentlich" else "ordentliche Kündigung"


def _eingang_txt(eing) -> str:
    return eing.strftime("%d.%m.%Y um %H:%M Uhr") if hasattr(eing, "strftime") else "—"


def _vertragsende_txt(bis) -> str:
    if isinstance(bis, date):
        return bis.strftime("%d.%m.%Y")
    if isinstance(bis, str) and bis:
        try:
            return date.fromisoformat(bis).strftime("%d.%m.%Y")
        except ValueError:
            return bis
    return "—"


def _grund_kurz(d: dict) -> str | None:
    """K-3: `grund` für die Link-Mail – Leerzeichen geglättet und hart gekappt. Der
    vollständige Grund steht in der Bestätigungsmail nach dem Klick (Stufe 2)."""
    grund = d.get("grund")
    if not isinstance(grund, str):
        return None
    grund = " ".join(grund.split())
    if not grund:
        return None
    if len(grund) > GRUND_KURZ_ZEICHEN:
        return grund[:GRUND_KURZ_ZEICHEN] + " …"
    return grund


def zugang_html(d: dict) -> str:
    """Inhalt der Link-Mail (Stufe 1): Zugangsbestätigung in Textform (§ 312k – Inhalt der
    Erklärung + Datum/Uhrzeit des Zugangs) und der Hinweis, dass das Abo erst nach der
    Bestätigung endet.

    K-3: Diese Mail geht an jede Adresse, für die ein Konto besteht – der Absender ist
    nicht authentifiziert. Deshalb stehen hier keine frei wählbaren Texte: `name` fällt
    weg, `vertrag` wird durch den festen Vertragstext ersetzt und `grund` ist auf
    `GRUND_KURZ_ZEICHEN` gekappt. So kann niemand mehrere Kilobyte eigenen Text (inklusive
    automatisch verlinkter URLs) als Absender „Sapio" an fremde Adressen zustellen. Der
    vollständige Inhalt der Erklärung folgt in der Bestätigungsmail nach dem Klick, die
    nachweislich an den Postfach-Inhaber geht."""
    def z(v):
        return _html.escape(str(v)) if v else "—"
    zeilen = [
        ("Vertrag", z(VERTRAG_TEXT)),
        ("Art der Kündigung", z(_art_txt(d.get("art")))),
        ("Eingegangen am", z(_eingang_txt(d.get("eingegangen")))),
    ]
    grund = _grund_kurz(d)
    if grund:
        zeilen.append(("Angegebener Grund (gekürzt)", z(grund)))
    return (
        "<p>deine Kündigungserklärung ist bei uns eingegangen – <b>sie gilt als zu dem "
        "unten genannten Eingangszeitpunkt erklärt</b>. Hier der Inhalt deiner Erklärung:</p>"
        f'<table style="border-collapse:collapse;font-size:14px;margin:14px 0">{_tabelle(zeilen)}</table>'
        "<p>Dein Abo beenden wir erst, wenn du es über den Button selbst bestätigst – so "
        "kann niemand nur mit deiner E-Mail-Adresse eine Kündigung auslösen. Nach der "
        "Bestätigung erhältst du eine weitere E-Mail mit dem vollständigen Inhalt deiner "
        "Erklärung und dem Vertragsende. Der Zugang zu allen Funktionen bleibt bis dahin "
        "erhalten; danach läuft dein Konto in der kostenlosen Version weiter – deine "
        "Rezepte, Pläne und Vorräte bleiben erhalten.</p>"
    )


def bestaetigung_html(d: dict) -> str:
    """Inhalt der Bestätigungsmail (Stufe 2): Erklärung + Zugangszeitpunkt + Vertragsende
    (§ 312k). Geht erst nach dem Klick auf den Bestätigungslink raus – also an den
    nachgewiesenen Postfach-Inhaber. Hier steht der vollständige Erklärungsinhalt
    (Name, Vertrag, Grund), den die Link-Mail bewusst nur gekürzt zeigt (K-3)."""
    def z(v):
        return _html.escape(str(v)) if v else "—"
    zeilen = [
        ("Vertrag", z(d.get("vertrag") or VERTRAG_TEXT)),
        ("Art der Kündigung", z(_art_txt(d.get("art")))),
        ("Eingegangen am", z(_eingang_txt(d.get("eingegangen")))),
        ("Vertrag endet am", z(_vertragsende_txt(d.get("vertrag_bis")))),
    ]
    if d.get("name"):
        zeilen.insert(0, ("Name", z(d.get("name"))))
    if d.get("grund"):
        zeilen.append(("Angegebener Grund", z(d.get("grund"))))
    return (
        "<p>wir bestätigen deine Kündigung. Hier der Inhalt deiner Erklärung:</p>"
        f'<table style="border-collapse:collapse;font-size:14px;margin:14px 0">{_tabelle(zeilen)}</table>'
        "<p>Der Zugang zu allen Funktionen bleibt bis zum Vertragsende erhalten. Danach läuft "
        "dein Konto in der kostenlosen Version weiter – deine Rezepte, Pläne und Vorräte "
        "bleiben dabei erhalten.</p>"
    )
