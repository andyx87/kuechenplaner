"""Öffentliche Kontolöschung per Bestätigungslink (DSGVO Art. 17).

Neben dem In-App-Weg (Mehr → Konto löschen, POST /konto/loeschen) gibt es eine
öffentliche Web-Adresse, über die die Kontolöschung angefordert werden kann:
<APP_BASE_URL>/konto-loeschen (ohne Anmeldung).

Ablauf – bewusst zweistufig, die Löschung ist NICHT umkehrbar:
  1. Formular → POST /auth/konto-loeschen-anfordern: legt einen einmaligen,
     1 Stunde gültigen Token an und mailt den Bestätigungslink. Die Antwort ist
     neutral und verrät nicht, ob zur E-Mail ein Konto existiert (F7-Linie,
     wie beim Passwort-Reset).
  2. Link-Klick → POST /auth/konto-loeschen: führt die Löschung mit derselben
     Logik wie POST /konto/loeschen (Modus 'selbst') aus.

Die Löschung erfolgt also NIE allein auf Basis der eingegebenen E-Mail, sondern
erst, wenn der Inhaber des Postfachs den Link anklickt. Wer keinen Zugriff auf
das Postfach hat, kann nichts löschen; ein Rate-Limit in rest.py bremst
zusätzlich (Mail-Flooding / Enumeration).

Token-Speicherung ohne neue Tabelle/DDL: dieselbe Tabelle wie die Passwort-Reset-
Tokens (passwort_reset, s. migration_mail_tokens.sql). Die Zweckbindung läuft über
das Präfix userauth.LOESCH_TOKEN_PREFIX: dieser Ablauf erzeugt und akzeptiert nur
Präfix-Tokens, userauth.passwort_reset_ausfuehren lehnt sie umgekehrt ab. Ein
Reset-Link kann damit nie eine Löschung auslösen und ein Löschlink nie ein
Passwort zurücksetzen.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from .db import acquire

log = logging.getLogger("koch")

TOKEN_GUELTIG_STUNDEN = 1

_HINWEIS_NEUTRAL = (
    "Falls zu dieser E-Mail-Adresse ein Topfplan-Konto besteht, haben wir dir einen "
    "Bestätigungslink geschickt. Die Löschung wird erst ausgeführt, wenn du diesen "
    "Link anklickst. Der Link ist 1 Stunde gültig. Bitte prüfe auch den Spam-Ordner."
)


async def anfordern(email: str) -> dict:
    """Nimmt die Lösch-Anfrage an: Token anlegen + Bestätigungslink mailen.
    Gibt aus Sicherheitsgründen IMMER dieselbe neutrale Antwort zurück
    (keine Auskunft, ob die E-Mail existiert – wie passwort_reset_anfordern)."""
    from .userauth import LOESCH_TOKEN_PREFIX, _hash_token

    email = (email or "").strip().lower()
    token = None
    try:
        if "@" in email and "." in email:
            async with acquire(bypass=True) as con:
                u = await con.fetchrow(
                    "SELECT id FROM app_user WHERE lower(email::text)=$1 AND aktiv", email)
                if u:
                    token = LOESCH_TOKEN_PREFIX + secrets.token_urlsafe(32)
                    ablauf = (datetime.now(timezone.utc)
                              + timedelta(hours=TOKEN_GUELTIG_STUNDEN))
                    await con.execute(
                        "INSERT INTO passwort_reset (user_id, token_hash, ablauf) "
                        "VALUES ($1,$2,$3)",
                        int(u["id"]), _hash_token(token), ablauf)
    except Exception as e:  # noqa: BLE001 – nie 500, immer neutrale Antwort
        log.warning("kontoloeschung: Token-Anlage fehlgeschlagen: %s", e)
        token = None
    if token:
        # S2 (Sicherheitsprüfung AND-24): Versand entkoppelt vom Request – Treffer- und
        # Nein-Zweig antworten gleich schnell (keine Enumeration über die Antwortzeit),
        # und die Resend-Laufzeit (Timeout bis 20 s) blockiert den Endpoint nicht.
        # Fehler loggt mailer.im_hintergrund; der Token läuft im Fehlerfall einfach ab.
        from . import mailer
        mailer.im_hintergrund(mailer.send_konto_loeschung(email, token))
    return {"ok": True, "hinweis": _HINWEIS_NEUTRAL}


async def bestaetigen(token: str) -> dict:
    """Führt die Löschung aus – NUR mit gültigem, unbenutztem Präfix-Token aus der
    Bestätigungsmail. Dieselbe Logik wie POST /konto/loeschen (Modus 'selbst'):
    eigene Mitgliedschaft + eigener Login weg; war es der letzte Nutzer, wird der
    ganze Haushalt entfernt (services.loesche_eigenes_konto)."""
    from .userauth import LOESCH_TOKEN_PREFIX, _hash_token

    if not token or not token.startswith(LOESCH_TOKEN_PREFIX):
        # Zweckbindung: u. a. Passwort-Reset-Tokens sind hier grundsätzlich ungültig.
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}
    th = _hash_token(token)
    jetzt = datetime.now(timezone.utc)
    try:
        async with acquire(bypass=True) as con:
            async with con.transaction():
                # FOR UPDATE: zwei parallele Klicks auf denselben Link werden
                # serialisiert, der zweite sieht benutzt=true.
                r = await con.fetchrow(
                    "SELECT id, user_id, ablauf, benutzt FROM passwort_reset "
                    "WHERE token_hash=$1 FOR UPDATE", th)
                if not r or r["benutzt"] or r["ablauf"] < jetzt:
                    return {"error": "Dieser Link ist ungültig oder abgelaufen."}
                await con.execute(
                    "UPDATE passwort_reset SET benutzt=true WHERE id=$1", r["id"])
                uid = int(r["user_id"])
                acc = await con.fetchval(
                    "SELECT account_id FROM account_mitglied WHERE user_id=$1 "
                    "ORDER BY account_id LIMIT 1", uid)
                email = await con.fetchval(
                    "SELECT email::text FROM app_user WHERE id=$1", uid)
                if acc is None:
                    # Sonderfall Login ohne (noch) eine Mitgliedschaft: nur den
                    # verwaisten Login entfernen – dieselben Guards wie in
                    # services.loesche_eigenes_konto (keine Mitgliedschaft, kein
                    # Super-Admin).
                    await con.fetchval(
                        "DELETE FROM app_user u WHERE u.id = $1 "
                        "AND NOT EXISTS (SELECT 1 FROM account_mitglied m "
                        "                WHERE m.user_id = u.id) "
                        "AND u.plattform_rolle IS DISTINCT FROM 'super_admin' "
                        "RETURNING id", uid)
    except Exception as e:  # noqa: BLE001
        log.warning("kontoloeschung: Token-Prüfung fehlgeschlagen: %s", e)
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}

    if acc is not None:
        # Denselben Pfad wie der In-App-Löschbutton nutzen: Kontext setzen und die
        # bestehende Self-Service-Löschung aufrufen (Modus 'selbst').
        from . import services
        from .userauth import current_account, current_user
        current_user.set(uid)
        current_account.set(acc)
        try:
            res = await services.loesche_eigenes_konto("selbst")
        except Exception as e:  # noqa: BLE001
            log.error("kontoloeschung: Löschung fehlgeschlagen (user %s): %s", uid, e)
            # S5 (AND-24): Der Token ist bereits als benutzt committet – „erneut versuchen"
            # wäre irreführend, der Link ist verbraucht.
            return {"error": "Die Löschung ist fehlgeschlagen. Bitte fordere einen neuen "
                             "Link an oder melde dich bei uns."}
        if res.get("error"):
            log.warning("kontoloeschung: Löschung abgelehnt (user %s): %s", uid, res["error"])
            return {"error": "Die Löschung ist fehlgeschlagen. Bitte fordere einen neuen "
                             "Link an oder melde dich bei uns."}

    if email:
        # Abschlussbestätigung ins Postfach (Nachweis) – tolerant, die Löschung
        # selbst ist zu diesem Zeitpunkt bereits durch.
        try:
            from . import mailer
            await mailer.send_konto_geloescht(email)
        except Exception as e:  # noqa: BLE001
            log.warning("kontoloeschung: Löschbestätigung an %s fehlgeschlagen: %s", email, e)
    return {
        "ok": True,
        "geloescht": True,
        # Bewusst neutral: bestätigt keine Konto-Details.
        "hinweis": ("Dein Topfplan-Konto wurde gelöscht. Du erhältst eine Bestätigung "
                    "per E-Mail."),
    }
