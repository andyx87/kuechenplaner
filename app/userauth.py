"""Authentifizierung (E-Mail + Passwort), Konten, Sessions.

Konten = Familien-Mandanten. Der ERSTE registrierte Nutzer wird super_admin und
uebernimmt das bestehende Konto 1 (Altdaten). Weitere Registrierungen legen ein
eigenes Konto an. Sessions per Bearer-Token (sha256 gehasht in der DB).

Die ContextVars current_account/current_user werden vom Auth-Dependency gesetzt
und in Deploy B (RLS) zur Mandantentrennung genutzt.
"""
from __future__ import annotations

import hashlib
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from . import config
from .db import pool, acquire

current_account: ContextVar[int | None] = ContextVar("current_account", default=None)
current_user: ContextVar[int | None] = ContextVar("current_user", default=None)

_ph = PasswordHasher()
SESSION_TAGE = 60

# Zweckbindung für Tokens in passwort_reset: Kontolösch-Bestätigungslinks (s.
# kontoloeschung.py) und Kündigungs-Bestätigungslinks (s. kuendigung.py) tragen diese
# Präfixe und werden vom Passwort-Reset abgelehnt – umgekehrt akzeptiert jeder Ablauf
# nur Tokens mit dem eigenen Präfix. Ohne DDL, da alle Abläufe dieselbe Tabelle nutzen.
LOESCH_TOKEN_PREFIX = "kl1-"
KUEND_TOKEN_PREFIX = "kd1-"

# Konstanter Dummy-Hash: bei unbekannter/inaktiver E-Mail wird trotzdem eine argon2-
# Verifikation ausgeführt, damit die Antwortzeit keine gültigen Konten verrät (F6).
_DUMMY_HASH = _ph.hash("timing-gleichlauf-dummy")


def _hash_token(t: str) -> str:
    return hashlib.sha256((t or "").encode()).hexdigest()


async def _me(con, uid: int, acc_id: int | None) -> dict:
    u = await con.fetchrow(
        "SELECT id, email, name, plattform_rolle, darf_angebote_upload FROM app_user WHERE id=$1", uid)
    rolle = None
    acc = None
    if acc_id:
        rolle = await con.fetchval(
            "SELECT rolle FROM account_mitglied WHERE user_id=$1 AND account_id=$2", uid, acc_id)
        acc = await con.fetchrow("SELECT id, name, guthaben_cents, abo_status FROM account WHERE id=$1", acc_id)
    su = bool(u and u["plattform_rolle"] == "super_admin")
    return {
        "user": {"id": u["id"], "email": str(u["email"]), "name": u["name"],
                 "plattform_rolle": u["plattform_rolle"],
                 "darf_angebote_upload": su or bool(u["darf_angebote_upload"])} if u else None,
        "account": (dict(acc) if acc else None),
        "rolle": rolle,
    }


async def _neue_session(con, uid: int, acc_id: int | None) -> dict:
    token = secrets.token_urlsafe(32)
    ablauf = datetime.now(timezone.utc) + timedelta(days=SESSION_TAGE)
    await con.execute(
        "INSERT INTO app_session (user_id, account_id, token_hash, ablauf) VALUES ($1,$2,$3,$4)",
        uid, acc_id, _hash_token(token), ablauf)
    me = await _me(con, uid, acc_id)
    return {"token": token, **me}


async def beta_info(slug: str | None) -> dict | None:
    """Öffentlicher Status eines Beta-Kanals für die Anmeldeseite /beta/<slug>.
    None = Kanal unbekannt oder abgeschaltet (Seite zeigt dann die normale Registrierung)."""
    s = (slug or "").strip().lower()
    if not s:
        return None
    try:
        async with pool().acquire() as con:
            q = await con.fetchrow(
                "SELECT slug, name, max_konten, trial_tage FROM beta_quelle "
                "WHERE slug = $1 AND aktiv", s)
            if q is None:
                return None
            belegt = await con.fetchval(
                "SELECT count(*) FROM account WHERE beta_quelle = $1 "
                "AND trial_bis IS NOT NULL AND trial_bis >= current_date", s) or 0
    except Exception:
        # Tabelle noch nicht migriert o. Ä.: kein Beta-Kanal, normale Registrierung greift.
        return None
    frei = max(0, int(q["max_konten"]) - int(belegt))
    return {"slug": q["slug"], "name": q["name"], "trial_tage": int(q["trial_tage"]),
            "plaetze": int(q["max_konten"]), "belegt": int(belegt), "frei": frei,
            "offen": frei > 0}


async def _beta_platz_vergeben(con, account_id: int, slug: str | None) -> int | None:
    """Belegt innerhalb der laufenden Registrierungs-Transaktion einen Beta-Platz und setzt
    den Vollzugang (account.trial_bis). Gibt die Trial-Tage zurück oder None.

    Der Zeilen-Lock auf beta_quelle serialisiert Zählen und Belegen – ohne ihn könnten
    gleichzeitige Anmeldungen das Kontingent überziehen (50 Plätze wären dann 53)."""
    s = (slug or "").strip().lower()
    if not s:
        return None
    try:
        q = await con.fetchrow(
            "SELECT max_konten, trial_tage FROM beta_quelle WHERE slug = $1 AND aktiv FOR UPDATE", s)
        if q is None:
            return None
        belegt = await con.fetchval(
            "SELECT count(*) FROM account WHERE beta_quelle = $1 "
            "AND trial_bis IS NOT NULL AND trial_bis >= current_date", s) or 0
        if int(belegt) >= int(q["max_konten"]):
            return None      # Kanal voll → normale Registrierung, kein Trial
        tage = max(1, int(q["trial_tage"]))
        await con.execute(
            "UPDATE account SET beta_quelle = $2, trial_bis = (current_date + $3::integer) "
            "WHERE id = $1", account_id, s, tage)
        return tage
    except Exception:
        # Beta-Tabelle fehlt/fehlerhaft: Registrierung NICHT scheitern lassen.
        return None


async def beta_inaktive_bereinigen() -> dict:
    """Beta-Tester nach config.BETA_INAKTIV_TAGE Tagen ohne Aktivität zurückstufen:
    trial_bis wird gelöscht (Konto läuft als Gratis weiter, nichts wird gelöscht), der
    Beta-Platz wird dadurch frei (Zählung: nur laufende Trials belegen einen Platz).
    Die Kanal-Zuordnung (beta_quelle) bleibt für die Auswertung erhalten.

    Aktivität = account.zuletzt_aktiv (Stempel in context_from_token, max. stündlich).
    Fallback für Konten ohne Stempel (Spalte neu): jüngste Session-Erstellung der
    Mitglieder – so wird niemand zurückgestuft, der sich gerade erst registriert hat."""
    tage = int(config.BETA_INAKTIV_TAGE or 0)
    if tage <= 0:
        return {"aktiv": False}
    async with pool().acquire() as con:
        rows = await con.fetch(
            """UPDATE account a SET trial_bis = NULL
                WHERE a.beta_quelle IS NOT NULL
                  AND a.trial_bis IS NOT NULL AND a.trial_bis >= current_date
                  AND COALESCE(a.zuletzt_aktiv, '-infinity') < now() - ($1 || ' days')::interval
                  AND NOT EXISTS (
                        SELECT 1 FROM app_session s
                          JOIN account_mitglied m ON m.user_id = s.user_id
                         WHERE m.account_id = a.id
                           AND s.created_at >= now() - ($1 || ' days')::interval)
                RETURNING a.id, a.beta_quelle""", str(tage))
        # Abschieds-Mail an die Owner – tolerant, der Job darf daran nie scheitern.
        from . import mailer   # lokal wegen Import-Zyklus (wie in register/reset)
        for r in rows:
            try:
                mails = await con.fetch(
                    """SELECT u.email::text AS email FROM app_user u
                         JOIN account_mitglied m ON m.user_id = u.id
                        WHERE m.account_id = $1 AND m.rolle = 'owner'""", r["id"])
                for m in mails:
                    await mailer.send_beta_beendet(m["email"], tage)
            except Exception:
                pass
    return {"aktiv": True, "zurueckgestuft": len(rows),
            "konten": [int(r["id"]) for r in rows]}


async def register(email: str, password: str, name: str, bootstrap_token: str | None = None,
                   beta: str | None = None) -> dict:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        return {"error": "Bitte eine gültige E-Mail angeben."}
    if not password or len(password) < 8:
        return {"error": "Passwort muss mindestens 8 Zeichen haben."}
    name = (name or "").strip()
    pw_hash = _ph.hash(password)
    async with pool().acquire() as con:
        # F7: Existenz NICHT bestätigen. Ist die E-Mail schon vergeben, verschicken wir
        # out-of-band einen Hinweis an den echten Inhaber und geben eine neutrale, nicht
        # bestätigende Meldung zurück (kein Konto/keine Session wird angelegt).
        if await con.fetchrow("SELECT 1 FROM app_user WHERE email=$1", email):
            try:
                from . import mailer
                await mailer.send_konto_existiert(email)
            except Exception:
                pass
            return {"error": "Registrierung mit diesen Angaben nicht möglich. Falls du bereits "
                             "ein Konto hast, melde dich an oder nutze die Passwort-vergessen-Funktion."}
        async with con.transaction():
            if await con.fetchrow("SELECT 1 FROM app_user WHERE email=$1", email):
                # Race: zwischen Vorabprüfung und Transaktion angelegt → gleiche neutrale Meldung.
                return {"error": "Registrierung mit diesen Angaben nicht möglich. Falls du bereits "
                                 "ein Konto hast, melde dich an oder nutze die Passwort-vergessen-Funktion."}
            # F8: super_admin + Übernahme von Konto 1 wird NICHT mehr allein durch die
            # Registrierungs-Reihenfolge vergeben (sonst könnte ein Fremder auf einem frischen
            # Deploy den Admin abgreifen). Nötig ist zusätzlich ein per Env gesetztes
            # Bootstrap-Token (ADMIN_BOOTSTRAP_TOKEN), das der Betreiber genau einmal beim
            # Erstsetup mitgibt. Ohne (gültiges) Token bekommt auch der erste Nutzer ein
            # normales, eigenes Konto ohne Sonderrechte.
            erster = (await con.fetchval("SELECT count(*) FROM app_user")) == 0
            darf_bootstrap = (
                erster and bool(config.ADMIN_BOOTSTRAP_TOKEN)
                and secrets.compare_digest(bootstrap_token or "", config.ADMIN_BOOTSTRAP_TOKEN)
            )
            uid = await con.fetchval(
                "INSERT INTO app_user (email, password_hash, name, plattform_rolle) "
                "VALUES ($1,$2,$3,$4) RETURNING id",
                email, pw_hash, name, ("super_admin" if darf_bootstrap else None))
            if darf_bootstrap:
                acc_id = 1
                await con.execute(
                    "UPDATE account SET name = COALESCE(NULLIF($1,''), name) WHERE id=1",
                    (name + "s Haushalt") if name else "")
            else:
                acc_id = await con.fetchval(
                    "INSERT INTO account (name) VALUES ($1) RETURNING id",
                    (name + "s Haushalt") if name else "Haushalt")
            await con.execute(
                "INSERT INTO account_mitglied (account_id, user_id, rolle) VALUES ($1,$2,'owner') "
                "ON CONFLICT DO NOTHING", acc_id, uid)
            # Beta-Link (/beta/<slug>): Platz belegen und Vollzugang setzen. Ist der Kanal
            # voll oder unbekannt, entsteht ein normales Gratis-Konto – die Registrierung
            # scheitert daran nie.
            beta_tage = await _beta_platz_vergeben(con, acc_id, beta)
            sess = await _neue_session(con, uid, acc_id)
    # NACH dem Commit: Bestätigungs-Token + Mail – komplett tolerant. Die Registrierung
    # darf hieran NIE scheitern (z. B. wenn die email_verify-Tabelle noch fehlt).
    try:
        async with pool().acquire() as con2:
            verify_token = await _verify_token_erzeugen(con2, uid)
        from . import mailer
        await mailer.send_verifizierung(email, verify_token)
    except Exception:
        pass
    if beta_tage:
        sess = {**sess, "beta": {"quelle": (beta or "").strip().lower(), "trial_tage": beta_tage}}
    return sess


async def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    async with pool().acquire() as con:
        u = await con.fetchrow(
            "SELECT id, password_hash, aktiv FROM app_user WHERE email=$1", email)
        if not u or not u["password_hash"] or not u["aktiv"]:
            # Timing angleichen: auch ohne Treffer eine argon2-Verifikation ausführen (F6).
            try:
                _ph.verify(_DUMMY_HASH, password or "")
            except Exception:
                pass
            return {"error": "E-Mail oder Passwort ist falsch."}
        try:
            _ph.verify(u["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            return {"error": "E-Mail oder Passwort ist falsch."}
        acc_id = await con.fetchval(
            "SELECT account_id FROM account_mitglied WHERE user_id=$1 ORDER BY account_id LIMIT 1", u["id"])
        return await _neue_session(con, u["id"], acc_id)


async def logout(token: str | None) -> dict:
    if token:
        async with pool().acquire() as con:
            await con.execute("DELETE FROM app_session WHERE token_hash=$1", _hash_token(token))
    return {"ok": True}


# ---------- Passwort-Reset ----------

async def passwort_reset_anfordern(email: str) -> dict:
    """Erzeugt einen Reset-Token und verschickt den Link. Gibt aus Sicherheitsgründen
    IMMER {ok: True} zurück (keine Auskunft, ob die E-Mail existiert)."""
    email = (email or "").strip().lower()
    token = None
    try:
        if "@" in email and "." in email:
            async with pool().acquire() as con:
                u = await con.fetchrow("SELECT id FROM app_user WHERE email=$1 AND aktiv", email)
                if u:
                    token = secrets.token_urlsafe(32)
                    ablauf = datetime.now(timezone.utc) + timedelta(hours=1)
                    await con.execute(
                        "INSERT INTO passwort_reset (user_id, token_hash, ablauf) VALUES ($1,$2,$3)",
                        u["id"], _hash_token(token), ablauf)
    except Exception:
        token = None  # z. B. Tabelle fehlt noch – nie 500, immer {ok: True}
    if token:
        # S2 (Sicherheitsprüfung AND-24): wie kontoloeschung.anfordern – Versand entkoppelt
        # vom Request, damit Treffer- und Nein-Zweig gleich schnell antworten (keine
        # Enumeration über die Antwortzeit). Fehler loggt mailer.im_hintergrund.
        from . import mailer
        mailer.im_hintergrund(mailer.send_passwort_reset(email, token))
    return {"ok": True}


async def passwort_reset_ausfuehren(token: str, password: str) -> dict:
    # Zweckbindung: Kontolösch-/Kündigungs-Tokens (Präfix, s. kontoloeschung.py bzw.
    # kuendigung.py) sind hier ungültig.
    if not token or token.startswith((LOESCH_TOKEN_PREFIX, KUEND_TOKEN_PREFIX)):
        return {"error": "Ungültiger Link."}
    if not password or len(password) < 8:
        return {"error": "Passwort muss mindestens 8 Zeichen haben."}
    th = _hash_token(token)
    try:
        async with pool().acquire() as con:
            async with con.transaction():
                r = await con.fetchrow(
                    "SELECT id, user_id, ablauf, benutzt FROM passwort_reset WHERE token_hash=$1", th)
                if not r or r["benutzt"] or r["ablauf"] < datetime.now(timezone.utc):
                    return {"error": "Dieser Link ist ungültig oder abgelaufen."}
                await con.execute("UPDATE app_user SET password_hash=$1 WHERE id=$2",
                                  _ph.hash(password), r["user_id"])
                await con.execute("UPDATE passwort_reset SET benutzt=true WHERE id=$1", r["id"])
                # Sicherheit: alle bestehenden Sessions des Nutzers beenden.
                await con.execute("DELETE FROM app_session WHERE user_id=$1", r["user_id"])
    except Exception:
        return {"error": "Dieser Link ist ungültig oder abgelaufen."}
    return {"ok": True}


# ---------- E-Mail-Bestätigung ----------

async def _verify_token_erzeugen(con, uid: int) -> str:
    token = secrets.token_urlsafe(24)
    ablauf = datetime.now(timezone.utc) + timedelta(days=7)
    await con.execute(
        "INSERT INTO email_verify (user_id, token_hash, ablauf) VALUES ($1,$2,$3)",
        uid, _hash_token(token), ablauf)
    return token


async def email_verifizieren(token: str) -> dict:
    if not token:
        return {"error": "Ungültiger Link."}
    th = _hash_token(token)
    try:
        async with pool().acquire() as con:
            async with con.transaction():
                r = await con.fetchrow(
                    "SELECT user_id, ablauf FROM email_verify WHERE token_hash=$1", th)
                if not r or r["ablauf"] < datetime.now(timezone.utc):
                    return {"error": "Dieser Bestätigungslink ist ungültig oder abgelaufen."}
                await con.execute("DELETE FROM email_verify WHERE user_id=$1", r["user_id"])
    except Exception:
        return {"error": "Dieser Bestätigungslink ist ungültig oder abgelaufen."}
    return {"ok": True}


async def context_from_token(token: str | None) -> dict | None:
    """Validiert den Bearer-Token -> {user_id, account_id} oder None."""
    if not token:
        return None
    async with pool().acquire() as con:
        s = await con.fetchrow(
            "SELECT s.user_id, s.account_id, s.ablauf "
            "FROM app_session s JOIN app_user u ON u.id = s.user_id "
            "WHERE s.token_hash=$1 AND u.aktiv", _hash_token(token))
        if s and s["ablauf"] >= datetime.now(timezone.utc) and s["account_id"]:
            # Aktivitäts-Stempel fürs Konto (Basis der Beta-Inaktivitäts-Regel). Gedrosselt:
            # schreibt höchstens einmal pro Stunde je Konto. Tolerant – die Spalte kann in
            # Produktion fehlen, bis die Migration lief; Auth darf daran nie scheitern.
            try:
                await con.execute(
                    "UPDATE account SET zuletzt_aktiv = now() WHERE id = $1 "
                    "AND (zuletzt_aktiv IS NULL OR zuletzt_aktiv < now() - interval '1 hour')",
                    s["account_id"])
            except Exception:
                pass
    if not s or s["ablauf"] < datetime.now(timezone.utc):
        return None
    return {"user_id": s["user_id"], "account_id": s["account_id"]}


async def ist_super_admin(user_id: int | None) -> bool:
    if not user_id:
        return False
    async with pool().acquire() as con:
        r = await con.fetchval("SELECT plattform_rolle FROM app_user WHERE id=$1", user_id)
    return r == "super_admin"


async def user_name(user_id: int | None) -> str | None:
    if not user_id:
        return None
    async with pool().acquire() as con:
        return await con.fetchval("SELECT name FROM app_user WHERE id=$1", user_id)


async def darf_angebote_upload(user_id: int | None) -> bool:
    """True, wenn der User eigene Angebote hochladen darf (Super-Admin immer)."""
    if not user_id:
        return True  # MCP/ohne User = Owner-Kontext
    async with pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT plattform_rolle, darf_angebote_upload FROM app_user WHERE id=$1", user_id)
    return bool(r and (r["plattform_rolle"] == "super_admin" or r["darf_angebote_upload"]))


async def darf_ki(user_id: int | None, account_id: int | None) -> bool:
    """Harte Barriere: True, wenn der User KI-Funktionen nutzen darf. Super-Admin und
    Haushalts-Owner immer; sonst account_mitglied.ki_erlaubt (Default true). Ohne
    User-Kontext (z.B. interne/MCP-Aufrufe) nicht blockieren."""
    if not user_id:
        return True
    async with pool().acquire() as con:
        plat = await con.fetchval("SELECT plattform_rolle FROM app_user WHERE id=$1", int(user_id))
        if plat == "super_admin":
            return True
        if account_id:
            row = await con.fetchrow(
                "SELECT rolle, ki_erlaubt FROM account_mitglied WHERE account_id=$1 AND user_id=$2",
                int(account_id), int(user_id))
            if row is not None:
                return row["rolle"] == "owner" or bool(row["ki_erlaubt"])
    return True  # kein Mitgliedseintrag → nicht blockieren


async def ist_admin_oder_support(user_id: int | None) -> bool:
    """True für Super-Admin ODER Support (dürfen z.B. Guthaben aufladen)."""
    if not user_id:
        return False
    async with pool().acquire() as con:
        r = await con.fetchval("SELECT plattform_rolle FROM app_user WHERE id=$1", user_id)
    return r in ("super_admin", "support")


async def account_fuer_user(user_id: int) -> int | None:
    async with pool().acquire() as con:
        return await con.fetchval(
            "SELECT account_id FROM account_mitglied WHERE user_id=$1 ORDER BY account_id LIMIT 1", int(user_id))


async def list_users() -> list[dict]:
    """Alle User für das Backoffice (Konto, Rolle, Upload-Recht, Guthaben)."""
    async with pool().acquire() as con:
        rows = await con.fetch(
            """SELECT u.id, u.email::text AS email, u.name, u.plattform_rolle,
                      u.darf_angebote_upload, u.aktiv,
                      am.account_id, am.ki_erlaubt, a.name AS account_name, a.guthaben_cents::float AS guthaben_cents
               FROM app_user u
               LEFT JOIN account_mitglied am ON am.user_id = u.id
               LEFT JOIN account a ON a.id = am.account_id
               ORDER BY u.id""")
    return [dict(r) for r in rows]


_USER_SORT = {
    "id": "u.id", "id_desc": "u.id DESC",
    "email": "u.email", "name": "u.name",
    "neu": "u.created_at DESC", "alt": "u.created_at",
    "guthaben": "a.guthaben_cents DESC NULLS LAST",
}


async def list_users_paged(q: str | None = None, limit: int = 25, offset: int = 0,
                           sort: str = "id_desc") -> dict:
    """Backoffice-Nutzerliste mit Suche (E-Mail/Name/Konto), Pagination und Sortierung.
    Gibt {users:[...], total:int} zurück – skaliert auch bei sehr vielen Nutzern."""
    limit = max(1, min(int(limit or 25), 100))
    offset = max(0, int(offset or 0))
    order = _USER_SORT.get(sort or "id_desc", "u.id DESC")
    such = (q or "").strip()
    where = ""
    args: list = []
    if such:
        args.append(f"%{such}%")
        where = ("WHERE u.email::text ILIKE $1 OR u.name ILIKE $1 "
                 "OR a.name ILIKE $1 OR u.id::text = $2")
        args.append(such if such.isdigit() else "-1")
    async with pool().acquire() as con:
        total = await con.fetchval(
            f"""SELECT COUNT(*) FROM app_user u
                LEFT JOIN account_mitglied am ON am.user_id = u.id
                LEFT JOIN account a ON a.id = am.account_id
                {where}""", *args)
        rows = await con.fetch(
            f"""SELECT u.id, u.email::text AS email, u.name, u.plattform_rolle,
                       u.darf_angebote_upload, u.aktiv, u.created_at,
                       am.account_id, am.ki_erlaubt, am.rolle AS konto_rolle,
                       a.name AS account_name, a.guthaben_cents::float AS guthaben_cents,
                       a.tarif_code, a.abo_bezahlt_bis
                FROM app_user u
                LEFT JOIN account_mitglied am ON am.user_id = u.id
                LEFT JOIN account a ON a.id = am.account_id
                {where}
                ORDER BY {order}
                LIMIT {limit} OFFSET {offset}""", *args)
    return {"users": [dict(r) for r in rows], "total": int(total or 0),
            "limit": limit, "offset": offset}


async def set_darf_angebote_upload(user_id: int, erlaubt: bool) -> dict:
    async with pool().acquire() as con:
        await con.execute(
            "UPDATE app_user SET darf_angebote_upload=$2 WHERE id=$1", int(user_id), bool(erlaubt))
    return {"id": int(user_id), "darf_angebote_upload": bool(erlaubt)}


async def set_mitglied_ki(user_id: int, erlaubt: bool) -> dict:
    """Super-Admin: KI-Nutzung eines Users (alle seine Mitgliedschaften) erlauben/sperren."""
    async with pool().acquire() as con:
        await con.execute(
            "UPDATE account_mitglied SET ki_erlaubt=$2 WHERE user_id=$1", int(user_id), bool(erlaubt))
    return {"id": int(user_id), "ki_erlaubt": bool(erlaubt)}


async def _ist_letzter_aktiver_super_admin(con, user_id: int) -> bool:
    """True, wenn user_id aktuell aktiver Super-Admin ist und es keinen weiteren aktiven
    Super-Admin gibt (B-3: Grundlage für Aussperr-Schutz bei Selbst-Änderung)."""
    row = await con.fetchrow("SELECT plattform_rolle, aktiv FROM app_user WHERE id=$1", user_id)
    if not row or row["plattform_rolle"] != "super_admin" or not row["aktiv"]:
        return False
    anzahl = await con.fetchval(
        "SELECT COUNT(*) FROM app_user WHERE plattform_rolle='super_admin' AND aktiv")
    return anzahl <= 1


async def set_plattform_rolle(user_id: int, rolle: str | None, actor_uid: int | None = None) -> dict:
    """Super-Admin vergibt/entzieht Plattform-Rollen. Erlaubt: 'support' oder normal (None).
    B-3: Der letzte aktive Super-Admin darf sich die super_admin-Rolle nicht selbst entziehen,
    sonst gäbe es niemanden mehr, der Super-Admin-Rechte vergeben könnte (Aussperr-Schutz)."""
    r = rolle if rolle in ("support", "super_admin") else None
    uid = int(user_id)
    async with pool().acquire() as con:
        alt = await con.fetchval("SELECT plattform_rolle FROM app_user WHERE id=$1", uid)
        if actor_uid is not None and uid == int(actor_uid) and r != "super_admin":
            if await _ist_letzter_aktiver_super_admin(con, uid):
                return {"error": "letzter_super_admin", "alt_rolle": alt}
        await con.execute("UPDATE app_user SET plattform_rolle=$2 WHERE id=$1", uid, r)
    return {"id": uid, "plattform_rolle": r, "alt_rolle": alt}


async def set_user_aktiv(user_id: int, aktiv: bool, actor_uid: int | None = None) -> dict:
    """Super-Admin sperrt/entsperrt einen Nutzer (app_user.aktiv). Ein gesperrter Nutzer
    kann sich nicht mehr einloggen (login prüft aktiv) und seine laufenden Sessions werden
    sofort beendet (context_from_token prüft aktiv zusätzlich pro Request). Schutz: man kann
    sich nicht selbst sperren und keinen Super-Admin sperren (Aussperr-Schutz). B-3: Der
    letzte aktive Super-Admin, der sich selbst deaktivieren will, bekommt einen eigenen
    Fehlercode ('letzter_super_admin'), damit die Route dafür 409 zurückgeben kann."""
    uid = int(user_id)
    async with pool().acquire() as con:
        row = await con.fetchrow("SELECT id, plattform_rolle, aktiv FROM app_user WHERE id=$1", uid)
        if not row:
            return {"error": "Nutzer nicht gefunden"}
        alt = bool(row["aktiv"])
        if not aktiv:
            if actor_uid is not None and uid == int(actor_uid):
                if await _ist_letzter_aktiver_super_admin(con, uid):
                    return {"error": "letzter_super_admin", "alt_aktiv": alt}
                return {"error": "Du kannst dich nicht selbst sperren.", "alt_aktiv": alt}
            if row["plattform_rolle"] == "super_admin":
                return {"error": "Ein Super-Admin kann nicht gesperrt werden.", "alt_aktiv": alt}
        await con.execute("UPDATE app_user SET aktiv=$2 WHERE id=$1", uid, bool(aktiv))
        if not aktiv:
            await con.execute("DELETE FROM app_session WHERE user_id=$1", uid)  # sofort ausloggen
    return {"id": uid, "aktiv": bool(aktiv), "alt_aktiv": alt}


# ---------- Einladungen (Familienmitglieder ins eigene Konto) ----------

async def create_einladung(email: str, eingeladen_von: int | None) -> dict:
    """Legt eine Einladung fürs aktive Konto an und gibt den Token zurück (Link baut
    das Frontend). Abgerechnet wird über den Haushalt (Personen-Pauschale)."""
    email = (email or "").strip().lower() or None
    async with acquire() as con:
        if email is not None:
            # Mit fester E-Mail: wie bisher (Login = diese E-Mail) inkl. Dubletten-Check.
            if "@" not in email or "." not in email:
                return {"error": "Bitte eine gültige E-Mail angeben."}
            if await con.fetchval("SELECT 1 FROM app_user WHERE email = $1", email):
                return {"error": "Diese E-Mail ist bereits registriert."}
            offen = await con.fetchrow(
                "SELECT id, token FROM einladung WHERE email = $1 AND status = 'offen'", email)
            if offen:
                return {"error": "Für diese E-Mail gibt es bereits eine offene Einladung."}
        # email=None → Link-only-Einladung: der Eingeladene gibt seine E-Mail beim Annehmen an.
        token = secrets.token_urlsafe(24)
        row = await con.fetchrow(
            """INSERT INTO einladung (email, token, eingeladen_von)
               VALUES ($1, $2, $3)
               RETURNING id, email::text AS email, token, status, erstellt""",
            email, token, eingeladen_von)
        # Namen für eine persönliche Einladungs-Mail (optional, Fehler tolerieren).
        haushalt_name = inviter_name = None
        if email is not None:
            try:
                haushalt_name = await con.fetchval(
                    "SELECT name FROM account WHERE id = nullif(current_setting('app.account_id', true), '')::int")
                if eingeladen_von:
                    inviter_name = await con.fetchval("SELECT name FROM app_user WHERE id = $1", eingeladen_von)
            except Exception:
                pass
    res = dict(row)
    if email is not None:
        # Versand außerhalb der DB-Verbindung; ohne RESEND_API_KEY ein No-Op.
        from . import mailer
        r = await mailer.send_einladung(email, res["token"], haushalt_name, inviter_name)
        res["mail_versendet"] = bool(r.get("ok"))
    return res


async def list_einladungen() -> list[dict]:
    async with acquire() as con:
        rows = await con.fetch(
            """SELECT id, email::text AS email, token, status, erstellt, eingeloest_am
               FROM einladung WHERE status = 'offen' ORDER BY erstellt DESC""")
    return [dict(r) for r in rows]


async def cancel_einladung(eid: int) -> dict:
    async with acquire() as con:
        await con.execute(
            "UPDATE einladung SET status = 'storniert' WHERE id = $1 AND status = 'offen'", int(eid))
    return {"ok": True}


async def einladung_info(token: str | None) -> dict | None:
    """Öffentlich: Infos zur Einladung für die Annahme-Seite (E-Mail, Haushalt, Status)."""
    if not token:
        return None
    async with acquire(bypass=True) as con:
        inv = await con.fetchrow(
            """SELECT e.email::text AS email, e.status, a.name AS account_name
               FROM einladung e LEFT JOIN account a ON a.id = e.account_id
               WHERE e.token = $1""", token)
    return dict(inv) if inv else None


async def einladung_einloesen(token: str | None, name: str, password: str,
                              email: str | None = None) -> dict:
    """Öffentlich: Einladung annehmen → neuer User + Beitritt zum einladenden Konto +
    direkt eingeloggt. bypass, da kontoübergreifend (kein Kontext des Einladers).
    Bei Link-only-Einladungen (keine E-Mail hinterlegt) gibt der Eingeladene seine
    eigene E-Mail an (Parameter `email`)."""
    if not token:
        return {"error": "Ungültiger Einladungslink."}
    if not password or len(password) < 8:
        return {"error": "Passwort muss mindestens 8 Zeichen haben."}
    name = (name or "").strip()
    async with acquire(bypass=True) as con:
        async with con.transaction():
            # F14: Zeile sperren (FOR UPDATE) → zwei parallele Einlösungen desselben Tokens
            # werden serialisiert; die zweite sieht dann status<>'offen' und bricht ab.
            inv = await con.fetchrow(
                "SELECT id, account_id, email::text AS email, status FROM einladung "
                "WHERE token = $1 FOR UPDATE", token)
            if not inv or inv["status"] != "offen":
                return {"error": "Dieser Einladungslink ist ungültig oder wurde bereits eingelöst."}
            # Feste E-Mail aus der Einladung; sonst die vom Eingeladenen angegebene.
            email = (inv["email"] or email or "").strip().lower()
            if "@" not in email or "." not in email:
                return {"error": "Bitte eine gültige E-Mail angeben."}
            if await con.fetchrow("SELECT 1 FROM app_user WHERE email = $1", email):
                return {"error": "Diese E-Mail ist bereits registriert. Bitte melde dich an."}
            pw_hash = _ph.hash(password)
            uid = await con.fetchval(
                "INSERT INTO app_user (email, password_hash, name, plattform_rolle) "
                "VALUES ($1, $2, $3, NULL) RETURNING id", email, pw_hash, name)
            await con.execute(
                "INSERT INTO account_mitglied (account_id, user_id, rolle) VALUES ($1, $2, 'member') "
                "ON CONFLICT DO NOTHING", inv["account_id"], uid)
            # Statuswechsel zusätzlich als Gate (belt-and-suspenders): nur wenn noch 'offen'.
            claimed = await con.fetchval(
                "UPDATE einladung SET status = 'eingeloest', eingeloest_am = now() "
                "WHERE id = $1 AND status = 'offen' RETURNING id", inv["id"])
            if claimed is None:
                return {"error": "Dieser Einladungslink ist ungültig oder wurde bereits eingelöst."}
            return await _neue_session(con, uid, inv["account_id"])


async def me_for_token(token: str | None) -> dict | None:
    ctx = await context_from_token(token)
    if not ctx:
        return None
    async with pool().acquire() as con:
        return await _me(con, ctx["user_id"], ctx["account_id"])
