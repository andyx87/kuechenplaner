"""E-Mail-Versand über Resend (https://resend.com).

Ohne RESEND_API_KEY ist der Versand ein No-Op (wird nur geloggt) – die App
bleibt voll funktionsfähig. So kann der Code deployt werden, bevor das Resend-
Konto/der Key existiert. Sobald der Key (Umgebungsvariable RESEND_API_KEY)
gesetzt ist, werden echte Mails verschickt.
"""
import asyncio
import logging
import html as _html

import httpx

from . import config

log = logging.getLogger("koch")

_RESEND_URL = "https://api.resend.com/emails"

# Referenzen auf laufende Hintergrund-Versände (Schutz vor Garbage Collection).
_offene_tasks: set[asyncio.Task] = set()


def _hintergrund_fertig(task: asyncio.Task) -> None:
    _offene_tasks.discard(task)
    if not task.cancelled() and task.exception():
        log.warning("mailer: Versand im Hintergrund fehlgeschlagen: %s", task.exception())


def im_hintergrund(coro) -> asyncio.Task:
    """Führt einen Versand entkoppelt vom Request aus (S2, Sicherheitsprüfung AND-24).

    Die Antwort auf token-auslösende Requests (Kontolöschung, Passwort-Reset) darf nicht
    auf den HTTP-Call an Resend (Timeout bis 20 s) warten: Der Versand passiert nur, wenn
    das Konto existiert – unterschiedliche Antwortzeiten würden sonst verraten, welche
    E-Mail-Adressen Topfplan-Konten haben (Enumeration). Fehler landen im Log; `send` selbst
    wirft ohnehin nicht."""
    task = asyncio.create_task(coro)
    _offene_tasks.add(task)
    task.add_done_callback(_hintergrund_fertig)
    return task


async def send(to: str, subject: str, html_body: str, text_body: str | None = None) -> dict:
    """Schickt EINE E-Mail. Gibt {ok, id?|skipped|error} zurück (wirft nicht)."""
    to = (to or "").strip()
    if not to:
        return {"ok": False, "error": "keine Empfängeradresse"}
    if not config.RESEND_API_KEY:
        log.info("mailer: RESEND_API_KEY fehlt – Mail an %s (%r) wird NICHT versendet (No-Op)", to, subject)
        return {"ok": False, "skipped": True}
    payload = {
        "from": config.MAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                json=payload,
            )
        if r.status_code >= 400:
            log.warning("mailer: Resend-Fehler %s an %s: %s", r.status_code, to, r.text[:300])
            return {"ok": False, "error": f"resend {r.status_code}"}
        return {"ok": True, "id": (r.json() or {}).get("id")}
    except Exception as e:  # noqa: BLE001 – Versand darf den Request nie crashen
        log.warning("mailer: Versand an %s fehlgeschlagen: %s", to, e)
        return {"ok": False, "error": str(e)}


# ---------- Layout ----------

def _layout(titel: str, intro: str, button_text: str, button_url: str, hinweis: str = "") -> str:
    """Schlichtes, markenkonformes HTML-Template (Kupfer-Akzent, dunkle Emblem-Optik)."""
    t, i, b = _html.escape(titel), intro, _html.escape(button_text)
    u = _html.escape(button_url, quote=True)
    base = _html.escape(config.APP_BASE_URL, quote=True)
    _fuss = ['<b style="color:#6f6657">Topfplan</b>']
    if config.OPERATOR_NAME:
        _fuss.append(_html.escape(config.OPERATOR_NAME))
    if config.SUPPORT_EMAIL:
        _m = _html.escape(config.SUPPORT_EMAIL, quote=True)
        _fuss.append(f'<a href="mailto:{_m}" style="color:#9c9384">{_m}</a>')
    fusszeile = " · ".join(_fuss)
    extra = f'<p style="margin:18px 0 0;color:#9c9384;font-size:13px;line-height:1.6">{hinweis}</p>' if hinweis else ""
    return f"""\
<!doctype html><html lang="de"><body style="margin:0;background:#f7f1e8;font-family:'Segoe UI',Helvetica,Arial,sans-serif">
  <div style="max-width:520px;margin:0 auto;padding:32px 22px">
    <div style="text-align:center;margin-bottom:24px">
      <img src="{base}/icon-192.png" width="64" height="64" alt="Topfplan"
           style="display:inline-block;border-radius:16px;border:0" />
      <div style="font-weight:800;letter-spacing:-.02em;font-size:24px;color:#c8823c;margin-top:10px">Topfplan</div>
          </div>
    <div style="background:#fff;border:1px solid rgba(40,30,15,.1);border-radius:18px;padding:30px 28px;box-shadow:0 10px 30px -16px rgba(80,60,30,.25)">
      <h1 style="margin:0 0 14px;font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:24px;color:#2a2018">{t}</h1>
      <div style="color:#5a5346;font-size:15px;line-height:1.65">{intro}</div>
      <div style="text-align:center;margin:28px 0 8px">
        <a href="{u}" style="display:inline-block;background:linear-gradient(180deg,#d99a55,#c8823c);background-color:#c8823c;color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:14px 30px;border-radius:12px">{b}</a>
      </div>
      <p style="margin:16px 0 0;color:#9c9384;font-size:12px;word-break:break-all">Falls der Button nicht funktioniert, kopiere diesen Link:<br /><a href="{u}" style="color:#c8823c">{u}</a></p>
      {extra}
    </div>
    <div style="text-align:center;color:#9c9384;font-size:12px;line-height:1.7;margin-top:22px">
      <p style="margin:0 0 4px">Diese E-Mail wurde im Zusammenhang mit deinem Topfplan-Konto versendet.</p>
      <p style="margin:0 0 4px">{fusszeile}</p>
      <p style="margin:0"><a href="{base}/?recht=impressum" style="color:#9c9384;text-decoration:underline">Impressum</a> &nbsp;·&nbsp; <a href="{base}/?recht=datenschutz" style="color:#9c9384;text-decoration:underline">Datenschutz</a></p>
    </div>
  </div>
</body></html>"""


# ---------- Konkrete Mails ----------

async def send_einladung(email: str, token: str, haushalt: str | None = None,
                         eingeladen_von: str | None = None) -> dict:
    link = f"{config.APP_BASE_URL}/?einladung={token}"
    wer = f" von <b>{_html.escape(eingeladen_von)}</b>" if eingeladen_von else ""
    hh = f" zum Haushalt <b>{_html.escape(haushalt)}</b>" if haushalt else ""
    intro = (f"Du wurdest{wer} eingeladen, bei <b>Topfplan</b>{hh} mitzumachen – dem KI-Küchenassistenten "
             f"für Rezepte aus Vorrat, Angeboten und für eure Geräte. Klick auf den Button, "
             f"um Name und Passwort festzulegen.")
    return await send(email, "Deine Einladung zu Topfplan",
                      _layout("Willkommen bei Topfplan!", intro, "Einladung annehmen", link,
                              "Du hast diese Einladung nicht erwartet? Dann ignoriere diese E-Mail einfach."))


async def send_passwort_reset(email: str, token: str) -> dict:
    link = f"{config.APP_BASE_URL}/?reset={token}"
    intro = ("Du hast angefragt, dein Topfplan-Passwort zurückzusetzen. Über den Button kannst du "
             "ein neues Passwort vergeben. Der Link ist aus Sicherheitsgründen begrenzt gültig.")
    return await send(email, "Passwort zurücksetzen",
                      _layout("Passwort zurücksetzen", intro, "Neues Passwort wählen", link,
                              "Wenn du das nicht warst, kannst du diese E-Mail ignorieren – dein Passwort bleibt unverändert."))


async def send_konto_existiert(email: str) -> dict:
    """Out-of-Band-Hinweis (F7): Bei einer Registrierung/Einladungs-Annahme mit einer bereits
    vergebenen E-Mail bestätigt die API-Antwort die Existenz NICHT. Stattdessen bekommt der
    Inhaber der Adresse hier den Hinweis, sich anzumelden oder das Passwort zurückzusetzen."""
    link = f"{config.APP_BASE_URL}/?reset=anfordern"
    intro = ("für diese E-Mail-Adresse besteht bereits ein Topfplan-Konto. Falls du das warst und "
             "dich anmelden möchtest, nutze deine Zugangsdaten – oder setze über den Button ein "
             "neues Passwort. Warst du das nicht, kannst du diese E-Mail einfach ignorieren.")
    return await send(email, "Dein Topfplan-Konto",
                      _layout("Du hast bereits ein Konto", intro, "Passwort zurücksetzen", link,
                              "Diese Nachricht erhältst du, weil jemand versucht hat, sich mit dieser "
                              "Adresse zu registrieren."))


async def send_verifizierung(email: str, token: str) -> dict:
    link = f"{config.APP_BASE_URL}/?verify={token}"
    intro = ("Schön, dass du dabei bist! Bitte bestätige deine E-Mail-Adresse, "
             "damit dein Topfplan-Konto vollständig aktiv ist.")
    return await send(email, "E-Mail-Adresse bestätigen",
                      _layout("E-Mail bestätigen", intro, "E-Mail bestätigen", link,
                              "Wenn du dich nicht bei Topfplan registriert hast, ignoriere diese E-Mail."))


async def send_konto_loeschung(email: str, token: str) -> dict:
    """Bestätigungslink für die öffentliche Kontolöschung (/konto-loeschen).
    Gelöscht wird erst nach dem Klick – niemals allein durch die Formular-Eingabe."""
    # S3 (Sicherheitsprüfung AND-24): Token im URL-FRAGMENT statt im Query. Fragmente
    # werden nicht an den Server übermittelt (keine Proxy-/nginx-Zugriffslogs, kein
    # Referer-Leak); das Frontend entfernt den Zusatz nach dem Lesen aus der Adresszeile
    # (AuthGate.jsx, history.replaceState).
    link = f"{config.APP_BASE_URL}/konto-loeschen#loesch={token}"
    intro = ("du hast angefordert, dein <b>Topfplan-Konto dauerhaft zu löschen</b>. Bitte "
             "bestätige das über den Button – erst dann wird gelöscht. Deine Rezepte, "
             "Pläne, Vorräte und persönlichen Daten werden dabei entfernt; dieser "
             "Schritt kann nicht rückgängig gemacht werden.")
    return await send(email, "Kontolöschung bestätigen",
                      _layout("Konto löschen bestätigen", intro, "Konto endgültig löschen", link,
                              "Warst du das nicht? Dann ignoriere diese E-Mail – es wird nichts "
                              "gelöscht. Der Link ist aus Sicherheitsgründen 1 Stunde gültig."))


async def send_konto_geloescht(email: str) -> dict:
    """Abschlussbestätigung, nachdem die Kontolöschung ausgeführt wurde (Nachweis)."""
    intro = ("dein <b>Topfplan-Konto wurde gelöscht</b>. Deine Rezepte, Pläne, Vorräte und "
             "persönlichen Daten sind entfernt.")
    return await send(email, "Dein Topfplan-Konto wurde gelöscht",
                      _layout("Konto gelöscht", intro, "Zu Topfplan", config.APP_BASE_URL,
                              "Schade, dass du gehst. Diese E-Mail dient dir als Bestätigung. "
                              "Fragen? Antworte einfach auf diese E-Mail."))
