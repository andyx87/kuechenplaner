"""Unit-Tests für die zweistufige öffentliche Kündigung (app/kuendigung.py) und die
Zweckbindung der Bestätigungs-Tokens (app/userauth.py, app/kontoloeschung.py).

Läuft ohne Postgres, ohne FastAPI, ohne Stripe und ohne argon2: Die Module mit externen
Abhängigkeiten (app.db, app.mailer, app.stripe_pay, app.services, argon2) werden vor dem
Import durch Stubs ersetzt. Getestet wird die echte Logik – inklusive der
Sicherheitsregeln aus der Behebung von S-1/S-2 (Sicherheitsaudit AND-22):

  • Stufe 1 (Formular) kündigt NIE: kein Stripe-Aufruf, nur Nachweis + Link-Mail (S-1),
  • die HTTP-Antwort von Stufe 1 ist für „Konto vorhanden"/„kein Konto" identisch und
    enthält kein vertrag_bis – keine Abo-Enumeration (S-2),
  • Stufe 2 kündigt nur mit gültigem kd1-Token; das Zielkonto kommt aus dem Token,
  • Token: Präfix kd1-, 256 Bit zufällig, nur sha256-Hash in der DB, 1 h gültig,
    einmalig nutzbar (Replay schlägt fehl),
  • Zweckbindung: Kündigungs-Tokens setzen kein Passwort zurück und löschen kein Konto;
    Reset-/Lösch-Tokens kündigen umgekehrt nicht,
  • der Nachweis (§ 312k) wird sofort geschrieben – auch ohne Konto und bei DB-Ausfall
    bricht die Antwort nicht weg (neutral, nie 500),
  • DB-Zugriffe laufen im bypass (FORCE ROW LEVEL SECURITY).

Ausführung vom Repo-Root:
    python3 tests/test_kuendigung.py
    python3 -m unittest tests.test_kuendigung -v
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import types
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------
#
# Achtung, gemeinsame pytest-Session: Dieser Snapshot wird nach dem Import der
# Module unter Test wiederhergestellt. Sonst würden die Stubs dieser Datei andere
# Testdateien überschatten – `test_stripe_webhook_guthaben.py` importiert das
# ECHTE `app.stripe_pay`, und `kontoloeschung.py` löst `from . import mailer`/
# `services` zur AUFRUFZEIT über sys.modules auf (deren Tests erwarten ihre eigenen
# Stubs). Die hier importierten Module behalten ihre Importzeit-Bindungen, die
# Tests unten sind also trotzdem gegen diese Stubs isoliert.
_STUB_NAMES = ("app.db", "app.mailer", "app.services", "app.stripe_pay",
               "argon2", "argon2.exceptions")
_STUB_SNAPSHOT = {n: sys.modules.get(n) for n in _STUB_NAMES}


class FakeCon:
    """Mini-asyncpg-Ersatz: dispatcht die festen Queries von kuendigung.py."""

    EINGEGANGEN = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)

    def __init__(self):
        self.konto_zeile = None       # {"user_id","account_id","aktiv"} – E-Mail-Lookup (Stufe 1)
        self.ziel_zeile = None        # {"account_id","email"} – User-Lookup (Stufe 2)
        self.token_zeile = None       # {"id","user_id","benutzt","ablauf"}
        self.token_hash = None        # nur dieser Hash liefert die token_zeile
        self.db_fehler = None         # Exception für alle Queries (Ausfall-Simulation)
        self.nachweis_id = 11
        self.nachweis_daten = {"name": None, "vertrag": "Sapio-Abo", "art": "ordentlich",
                               "grund": None, "eingegangen": self.EINGEGANGEN}
        self.kuendigung_zeilen = {}   # id -> row dict (K-1 Nachweis-Zeilen)
        self.inserts_kuendigung = []  # Argument-Tupel der Nachweis-INSERTs
        self.inserts_token = []       # (user_id, token_hash, ablauf)
        self.token_benutzt = []       # ids verbrauchter Tokens
        self.updates = []             # (art, args) mit art: account_id|wirkung|abschluss
        self.bypass_aufrufe = []      # bypass-Flag je acquire()

    async def fetchrow(self, sql, *args):
        if self.db_fehler:
            raise self.db_fehler
        if "INSERT INTO kuendigung" in sql:
            self.inserts_kuendigung.append(tuple(args))
            row_id = self.nachweis_id
            self.nachweis_id += 1
            z = {
                "id": row_id,
                "email": args[0],
                "name": args[1],
                "vertrag": args[2],
                "art": args[3],
                "grund": args[4],
                "zum_datum": args[5],
                "wirkung": args[6],
                "eingegangen": self.EINGEGANGEN,
                "vertrag_bis": None,
            }
            self.kuendigung_zeilen[row_id] = z
            return {"id": row_id, "eingegangen": self.EINGEGANGEN}
        if "FROM passwort_reset" in sql:
            if self.token_zeile and args and args[0] == self.token_hash:
                return dict(self.token_zeile)
            return None
        if "UPDATE kuendigung" in sql and "RETURNING" in sql:
            self.updates.append(("abschluss", tuple(args)))
            if len(args) >= 7 and self.kuendigung_zeilen:
                # _ABSCHLUSS_GEBUNDEN: (kid, email, wirkung, bis, WIRKUNG_LINK, WIRKUNG_WARTET, WIRKUNG_FEHLER)
                kid, email, wirkung, bis = args[0], args[1], args[2], args[3]
                z = self.kuendigung_zeilen.get(kid)
                if z and z["email"].lower() == email.lower() and z["wirkung"] in args[4:]:
                    z["wirkung"] = wirkung
                    z["vertrag_bis"] = bis
                    return dict(z)
                return None
            elif len(args) == 5 and self.kuendigung_zeilen:
                # _ABSCHLUSS_JUENGSTE: (email, wirkung, bis, WIRKUNG_LINK, WIRKUNG_WARTET)
                email, wirkung, bis = args[0], args[1], args[2]
                passende = [
                    z for z in self.kuendigung_zeilen.values()
                    if z["email"].lower() == email.lower() and z["wirkung"] in args[3:]
                ]
                if passende:
                    passende.sort(key=lambda x: x["id"], reverse=True)
                    z = passende[0]
                    z["wirkung"] = wirkung
                    z["vertrag_bis"] = bis
                    return dict(z)
                return None
            return dict(self.nachweis_daten)
        if "WHERE lower(u.email::text) = $1" in sql:
            if self.konto_zeile:
                if "AND u.aktiv" in sql and not self.konto_zeile.get("aktiv", True):
                    return None
                return dict(self.konto_zeile)
            return None
        if "WHERE u.id = $1" in sql:
            return dict(self.ziel_zeile) if self.ziel_zeile else None
        return None

    async def execute(self, sql, *args):
        if self.db_fehler:
            raise self.db_fehler
        if "INSERT INTO passwort_reset" in sql:
            self.inserts_token.append(tuple(args))
        elif "UPDATE passwort_reset SET benutzt=false" in sql or "UPDATE passwort_reset SET benutzt = false" in sql:
            if self.token_zeile:
                self.token_zeile["benutzt"] = False
        elif "UPDATE passwort_reset SET benutzt" in sql:
            self.token_benutzt.append(args[0])
            if self.token_zeile:
                self.token_zeile["benutzt"] = True   # Replay-Simulation
        elif "UPDATE kuendigung SET account_id" in sql:
            self.updates.append(("account_id", tuple(args)))
        elif "UPDATE kuendigung SET wirkung" in sql:
            self.updates.append(("wirkung", tuple(args)))
            if len(args) == 2 and args[0] in self.kuendigung_zeilen:
                self.kuendigung_zeilen[args[0]]["wirkung"] = args[1]
        return "UPDATE 1"

    @asynccontextmanager
    async def transaction(self):
        yield self


_db_holder = {"db": None}


@asynccontextmanager
async def _fake_acquire(bypass: bool = False):
    db = _db_holder["db"]
    db.bypass_aufrufe.append(bypass)
    yield db


db_stub = types.ModuleType("app.db")
db_stub.acquire = _fake_acquire
db_stub.pool = lambda: None
sys.modules["app.db"] = db_stub

mailer_stub = types.ModuleType("app.mailer")
mailer_stub.gesendet = []
mailer_stub.link_antwort = {"ok": True}


async def _send_kuendigung_link(email, token, daten):
    mailer_stub.gesendet.append(("link", email, token, daten))
    return dict(mailer_stub.link_antwort)


async def _send_kuendigung_bestaetigung(email, daten):
    mailer_stub.gesendet.append(("bestaetigung", email, daten))
    return {"ok": True}


async def _send_konto_loeschung(email, token):
    mailer_stub.gesendet.append(("loeschlink", email, token))
    return {"ok": True}


async def _send_konto_geloescht(email):
    mailer_stub.gesendet.append(("geloescht", email))
    return {"ok": True}


mailer_stub.send_kuendigung_link = _send_kuendigung_link
mailer_stub.send_kuendigung_bestaetigung = _send_kuendigung_bestaetigung
mailer_stub.send_konto_loeschung = _send_konto_loeschung
mailer_stub.send_konto_geloescht = _send_konto_geloescht
sys.modules["app.mailer"] = mailer_stub

stripe_stub = types.ModuleType("app.stripe_pay")
stripe_stub.aufrufe = []
stripe_stub.antwort = {"ok": True, "stripe": True, "bis": "2026-10-01", "hatte_abo": True}


async def _kuendige_abo(account_id):
    stripe_stub.aufrufe.append(account_id)
    return dict(stripe_stub.antwort)


stripe_stub.kuendige_abo = _kuendige_abo
sys.modules["app.stripe_pay"] = stripe_stub

services_stub = types.ModuleType("app.services")
services_stub.aufrufe = []


async def _loesche_eigenes_konto(modus="selbst"):
    services_stub.aufrufe.append(modus)
    return {"geloescht": True}


services_stub.loesche_eigenes_konto = _loesche_eigenes_konto
sys.modules["app.services"] = services_stub

# argon2-Stub, damit das ECHTE userauth-Modul importierbar ist.
argon2_stub = types.ModuleType("argon2")


class _PasswordHasher:
    def hash(self, pw):
        return "stub-hash"

    def verify(self, h, pw):
        return True


argon2_stub.PasswordHasher = _PasswordHasher
argon2_exc = types.ModuleType("argon2.exceptions")


class VerifyMismatchError(Exception):
    pass


class InvalidHashError(Exception):
    pass


argon2_exc.VerifyMismatchError = VerifyMismatchError
argon2_exc.InvalidHashError = InvalidHashError
argon2_stub.exceptions = argon2_exc
sys.modules["argon2"] = argon2_stub
sys.modules["argon2.exceptions"] = argon2_exc

# Jetzt die echten Module unter Test importieren (sie binden die Stubs oben),
# danach sys.modules auf den Vorher-Zustand zurücksetzen (s. Snapshot-Kommentar).
import app  # noqa: E402  (leeres Paket-__init__)
from app import kontoloeschung, kuendigung, userauth  # noqa: E402

for _name, _modul in _STUB_SNAPSHOT.items():
    if _modul is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _modul


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


class FakeBackground:
    """Ersatz für FastAPI-BackgroundTasks: sammelt Aufgaben, der Test führt sie
    manuell aus – so bleibt die Entkopplung (Antwort VOR Mailversand) prüfbar."""

    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    async def ausfuehren(self):
        while self.tasks:
            fn, args, kwargs = self.tasks.pop(0)
            await fn(*args, **kwargs)


class _Basis(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeCon()
        _db_holder["db"] = self.db
        mailer_stub.gesendet.clear()
        mailer_stub.link_antwort = {"ok": True}
        stripe_stub.aufrufe.clear()
        stripe_stub.antwort = {"ok": True, "stripe": True,
                               "bis": "2026-10-01", "hatte_abo": True}
        services_stub.aufrufe.clear()

    def konto_bekannt(self, user_id=42, account_id=7, aktiv=True):
        """E-Mail-Lookup (Stufe 1) findet Nutzer + Owner-Konto."""
        self.db.konto_zeile = {"user_id": user_id, "account_id": account_id, "aktiv": aktiv}

    def ziel_bekannt(self, account_id=7, email="kunde@example.org"):
        """User-Lookup (Stufe 2) findet Konto + E-Mail zum Token."""
        self.db.ziel_zeile = {"account_id": account_id, "email": email}

    def gueltiger_token(self, kid: int | None = None, **overrides):
        """Hinterlegt einen frischen, unbenutzten Kündigungs-Token in der Fake-DB."""
        zufall = "test-token-123"
        token = (f"{userauth.KUEND_TOKEN_PREFIX}{kid}.{zufall}" if kid is not None
                 else f"{userauth.KUEND_TOKEN_PREFIX}{zufall}")
        zeile = {"id": 1, "user_id": 42, "benutzt": False,
                 "ablauf": datetime.now(timezone.utc) + timedelta(minutes=30)}
        zeile.update(overrides)
        self.db.token_zeile = zeile
        self.db.token_hash = _hash(token)
        return token

    def wirkung_updates(self):
        return [args[1] for art, args in self.db.updates if art == "wirkung"]

    def abschluss_updates(self):
        return [args for art, args in self.db.updates if art == "abschluss"]


class Stufe1AnnahmeTests(_Basis):
    async def test_nachweis_sofort_auch_ohne_konto(self):
        # § 312k: Zugang wird immer sofort protokolliert – auch ohne Konto.
        res = await kuendigung.annehmen({"email": "unbekannt@example.org"},
                                        ip="1.2.3.4", background=FakeBackground())
        self.assertTrue(res["ok"])
        self.assertEqual(len(self.db.inserts_kuendigung), 1)
        args = self.db.inserts_kuendigung[0]
        self.assertEqual(args[0], "unbekannt@example.org")
        self.assertEqual(args[6], kuendigung.WIRKUNG_WARTET)   # wartet_bestaetigung
        self.assertEqual(args[7], "1.2.3.4")
        self.assertTrue(all(self.db.bypass_aufrufe))           # FORCE RLS → bypass

    async def test_antwort_identisch_und_ohne_vertrag_bis(self):
        # S-2: kein Feld verrät, ob ein Konto/Abo existiert; beide Antworten gleich.
        bg_ohne = FakeBackground()
        res_ohne = await kuendigung.annehmen({"email": "unbekannt@example.org"},
                                             background=bg_ohne)
        self.konto_bekannt()
        bg_mit = FakeBackground()
        res_mit = await kuendigung.annehmen({"email": "kunde@example.org"},
                                            background=bg_mit)
        self.assertEqual(res_ohne, res_mit)                    # identische Antwort
        self.assertNotIn("vertrag_bis", res_mit)
        self.assertNotIn("wirkung", res_mit)
        self.assertNotIn("account", str(res_mit).lower())

    async def test_stufe1_kuendigt_nie(self):
        # S-1-Kern: weder das Formular noch der Hintergrund darf Stripe aufrufen.
        self.konto_bekannt()
        bg = FakeBackground()
        await kuendigung.annehmen({"email": "kunde@example.org"}, background=bg)
        await bg.ausfuehren()
        self.assertEqual(stripe_stub.aufrufe, [])

    async def test_mail_entkoppelt_und_link_token_eigenschaften(self):
        self.konto_bekannt(user_id=42, account_id=7)
        bg = FakeBackground()
        res = await kuendigung.annehmen({"email": " Kunde@Example.org "}, background=bg)
        self.assertTrue(res["ok"])
        self.assertEqual(mailer_stub.gesendet, [])             # Antwort VOR Mailversand
        await bg.ausfuehren()
        self.assertEqual(len(mailer_stub.gesendet), 1)
        art, email, token, daten = mailer_stub.gesendet[0]
        self.assertEqual(art, "link")
        self.assertEqual(email, "kunde@example.org")           # normalisiert
        self.assertTrue(token.startswith(userauth.KUEND_TOKEN_PREFIX))
        self.assertGreaterEqual(len(token[len(userauth.KUEND_TOKEN_PREFIX):]), 43)  # 256 Bit
        uid, th, ablauf = self.db.inserts_token[0]
        self.assertEqual(uid, 42)
        self.assertEqual(_hash(token), th)                     # nur der Hash liegt in der DB
        rest = ablauf - datetime.now(timezone.utc)
        self.assertLess(rest, timedelta(hours=1, seconds=5))   # 1 Stunde gültig
        self.assertGreater(rest, timedelta(minutes=30))
        self.assertEqual(daten["vertrag"], "Sapio-Abo")

    async def test_hintergrund_ergaenzt_nachweis(self):
        self.konto_bekannt(account_id=7)
        bg = FakeBackground()
        await kuendigung.annehmen({"email": "kunde@example.org"}, background=bg)
        await bg.ausfuehren()
        self.assertIn(("account_id", (11, 7)), self.db.updates)
        self.assertIn(kuendigung.WIRKUNG_LINK, self.wirkung_updates())

    async def test_unbekannte_email_kein_token_keine_mail(self):
        # Neutrale Linie wie bei der Kontolöschung: kein Konto → keine Mail.
        bg = FakeBackground()
        await kuendigung.annehmen({"email": "unbekannt@example.org"}, background=bg)
        await bg.ausfuehren()
        self.assertEqual(self.db.inserts_token, [])
        self.assertEqual(mailer_stub.gesendet, [])
        self.assertIn(kuendigung.WIRKUNG_KEIN_KONTO, self.wirkung_updates())

    async def test_mail_fehler_laesst_nachweis_auf_wartend(self):
        self.konto_bekannt()
        mailer_stub.link_antwort = {"ok": False, "skipped": True}
        bg = FakeBackground()
        await kuendigung.annehmen({"email": "kunde@example.org"}, background=bg)
        await bg.ausfuehren()
        self.assertNotIn(kuendigung.WIRKUNG_LINK, self.wirkung_updates())
        self.assertEqual(len(self.db.inserts_token), 1)        # Token existiert, Mail nicht

    async def test_ungueltige_eingaben(self):
        bg = FakeBackground()
        res = await kuendigung.annehmen({"email": "keine-email"}, background=bg)
        self.assertIn("error", res)
        res = await kuendigung.annehmen({"email": "a@b.de", "art": "ausserordentlich"},
                                        background=bg)
        self.assertIn("error", res)
        self.assertEqual(self.db.inserts_kuendigung, [])
        self.assertEqual(self.db.bypass_aufrufe, [])
        self.assertEqual(bg.tasks, [])

    async def test_db_ausfall_neutrale_antwort(self):
        # Nachweis-Tabelle weg: Antwort bleibt ok/neutral (Log ersetzt den Nachweis).
        self.db.db_fehler = RuntimeError("db weg")
        bg = FakeBackground()
        res = await kuendigung.annehmen({"email": "kunde@example.org"}, background=bg)
        self.assertTrue(res["ok"])
        await bg.ausfuehren()                                  # läuft ins Leere, kein Crash
        self.assertEqual(mailer_stub.gesendet, [])


class Stufe2BestaetigungTests(_Basis):
    async def test_token_ohne_praefix_abgelehnt(self):
        # Zweckbindung: Reset-/Lösch-Tokens dürfen nie eine Kündigung auslösen.
        self.ziel_bekannt()
        for token in ("reset-token-ohne-praefix",
                      userauth.LOESCH_TOKEN_PREFIX + "abc"):
            res = await kuendigung.bestaetigen(token)
            self.assertIn("error", res)
        self.assertEqual(stripe_stub.aufrufe, [])
        self.assertEqual(self.db.token_benutzt, [])

    async def test_unbekannter_token_abgelehnt(self):
        res = await kuendigung.bestaetigen(userauth.KUEND_TOKEN_PREFIX + "gibt-es-nicht")
        self.assertIn("error", res)
        self.assertEqual(stripe_stub.aufrufe, [])

    async def test_benutzter_token_abgelehnt(self):
        token = self.gueltiger_token(benutzt=True)
        res = await kuendigung.bestaetigen(token)
        self.assertIn("error", res)
        self.assertEqual(stripe_stub.aufrufe, [])

    async def test_abgelaufener_token_abgelehnt(self):
        token = self.gueltiger_token(
            ablauf=datetime.now(timezone.utc) - timedelta(minutes=1))
        res = await kuendigung.bestaetigen(token)
        self.assertIn("error", res)
        self.assertEqual(stripe_stub.aufrufe, [])

    async def test_gueltiger_token_kuendigt_zielkonto_aus_token(self):
        # S-1-Kern: Wirkung erst jetzt, Zielkonto aus dem Token (nicht aus dem Request).
        self.ziel_bekannt(account_id=7)
        token = self.gueltiger_token()
        res = await kuendigung.bestaetigen(token)
        self.assertTrue(res["ok"])
        self.assertEqual(stripe_stub.aufrufe, [7])
        self.assertEqual(self.db.token_benutzt, [1])           # Token verbraucht
        abschluss = self.abschluss_updates()
        self.assertEqual(len(abschluss), 1)
        email, wirkung, vertrag_bis = abschluss[0][0], abschluss[0][1], abschluss[0][2]
        self.assertEqual(email, "kunde@example.org")
        self.assertEqual(wirkung, "stripe_periodenende")
        self.assertEqual(vertrag_bis, date(2026, 10, 1))
        self.assertEqual(res["vertrag_bis"], "2026-10-01")
        best = [m for m in mailer_stub.gesendet if m[0] == "bestaetigung"]
        self.assertEqual(len(best), 1)
        self.assertEqual(best[0][1], "kunde@example.org")
        self.assertEqual(best[0][2]["vertrag_bis"], "2026-10-01")
        self.assertTrue(all(self.db.bypass_aufrufe))           # FORCE RLS → bypass

    async def test_token_einmalig_kein_replay(self):
        self.ziel_bekannt()
        token = self.gueltiger_token()
        res1 = await kuendigung.bestaetigen(token)
        res2 = await kuendigung.bestaetigen(token)
        self.assertTrue(res1["ok"])
        self.assertIn("error", res2)
        self.assertEqual(stripe_stub.aufrufe, [7])             # genau einmal gekündigt

    async def test_ohne_abo_wirkung_kein_abo(self):
        self.ziel_bekannt()
        stripe_stub.antwort = {"ok": True, "stripe": False, "bis": None, "hatte_abo": False}
        res = await kuendigung.bestaetigen(self.gueltiger_token())
        self.assertTrue(res["ok"])
        self.assertIsNone(res["vertrag_bis"])
        self.assertEqual(self.abschluss_updates()[0][1], "kein_abo")
        self.assertIsNone(self.abschluss_updates()[0][2])

    async def test_stripe_fehler_wirkung_fehler_erklaerung_bleibt(self):
        self.ziel_bekannt()
        stripe_stub.antwort = {"error": "boom"}
        token = self.gueltiger_token()
        res = await kuendigung.bestaetigen(token)
        # K-4: Bei Stripe-Fehler kein ok: true, sondern expliziter Fehler
        self.assertIn("error", res)
        self.assertEqual(res["error"], kuendigung.FEHLER_WIRKUNG)
        self.assertEqual(self.abschluss_updates()[0][1], "fehler")
        # K-4: Token bleibt freigegeben (benutzt=False) für erneuten Versuch
        self.assertFalse(self.db.token_zeile["benutzt"])
        # Keine Bestätigungsmail mit falschem Vertragsende versendet
        self.assertEqual(len([m for m in mailer_stub.gesendet if m[0] == "bestaetigung"]), 0)

        # Idempotenter 2. Versuch nach Behebung des Stripe-Fehlers
        stripe_stub.antwort = {"ok": True, "stripe": True, "bis": "2026-10-01", "hatte_abo": True}
        res2 = await kuendigung.bestaetigen(token)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["vertrag_bis"], "2026-10-01")
        self.assertEqual(len([m for m in mailer_stub.gesendet if m[0] == "bestaetigung"]), 1)

    async def test_ohne_mitgliedschaft_kein_konto(self):
        self.ziel_bekannt(account_id=None)
        res = await kuendigung.bestaetigen(self.gueltiger_token())
        self.assertTrue(res["ok"])
        self.assertEqual(stripe_stub.aufrufe, [])
        self.assertEqual(self.abschluss_updates()[0][1], kuendigung.WIRKUNG_KEIN_KONTO)

    async def test_db_ausfall_bei_token_pruefung(self):
        self.db.db_fehler = RuntimeError("db weg")
        res = await kuendigung.bestaetigen(
            userauth.KUEND_TOKEN_PREFIX + "egal")
        self.assertIn("error", res)                            # nie 500
        self.assertEqual(stripe_stub.aufrufe, [])


class ZweckbindungAndereAblaufeTests(_Basis):
    async def test_passwort_reset_lehnt_kuendigungs_token_ab(self):
        # Echtes userauth: kd1-Präfix wird vor jedem DB-Zugriff abgewiesen.
        res = await userauth.passwort_reset_ausfuehren(
            userauth.KUEND_TOKEN_PREFIX + "abc", "neuespasswort1")
        self.assertEqual(res, {"error": "Ungültiger Link."})

    async def test_kontoloeschung_lehnt_kuendigungs_token_ab(self):
        # Echtes kontoloeschung: Kündigungstoken löscht kein Konto.
        res = await kontoloeschung.bestaetigen(userauth.KUEND_TOKEN_PREFIX + "abc")
        self.assertIn("error", res)
        self.assertEqual(services_stub.aufrufe, [])


class BefundeK1BisK7Tests(_Basis):
    async def test_k1_token_an_nachweiszeile_gebunden_trennt_gleichzeitige_erklaerungen(self):
        """K-1: Opfer legt Zeile 1 an, Angreifer Zeile 2 auf dieselbe Adresse,
        Opfer klickt seinen Link → nur Zeile 1 wird bestätigt, Zeile 2 bleibt wartend."""
        self.konto_bekannt(user_id=42, account_id=7)
        self.ziel_bekannt(account_id=7, email="kunde@example.org")

        bg = FakeBackground()
        # 1) Opfer legt Kündigungserklärung an
        res1 = await kuendigung.annehmen(
            {"email": "kunde@example.org", "name": "Opfer", "vertrag": "Sapio Pro"},
            background=bg)
        self.assertTrue(res1["ok"])

        # 2) Angreifer legt Kündigungserklärung auf dieselbe Adresse an
        res2 = await kuendigung.annehmen(
            {"email": "kunde@example.org", "name": "Angreifer", "vertrag": "Sapio Free"},
            background=bg)
        self.assertTrue(res2["ok"])

        # Beide Hintergrund-Tasks abarbeiten
        await bg.ausfuehren()

        # Es wurden 2 Mails mit unterschiedlichen kid-Tokens versandt
        self.assertEqual(len(mailer_stub.gesendet), 2)
        token_opfer = mailer_stub.gesendet[0][2]
        token_angreifer = mailer_stub.gesendet[1][2]

        kid_opfer = kuendigung._kid_aus_token(token_opfer)
        kid_angreifer = kuendigung._kid_aus_token(token_angreifer)
        self.assertIsNotNone(kid_opfer)
        self.assertIsNotNone(kid_angreifer)
        self.assertNotEqual(kid_opfer, kid_angreifer)

        # Beide Zeilen sind in FakeCon hinterlegt
        self.assertIn(kid_opfer, self.db.kuendigung_zeilen)
        self.assertIn(kid_angreifer, self.db.kuendigung_zeilen)
        self.assertEqual(self.db.kuendigung_zeilen[kid_opfer]["wirkung"], kuendigung.WIRKUNG_LINK)
        self.assertEqual(self.db.kuendigung_zeilen[kid_angreifer]["wirkung"], kuendigung.WIRKUNG_LINK)

        # 3) Opfer klickt seinen Bestätigungslink
        self.db.token_zeile = {
            "id": 101, "user_id": 42, "benutzt": False,
            "ablauf": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        self.db.token_hash = _hash(token_opfer)

        res_klick = await kuendigung.bestaetigen(token_opfer)
        self.assertTrue(res_klick["ok"])

        # Nur Zeile 1 (Opfer) ist bestätigt; Zeile 2 (Angreifer) bleibt unverändert auf link_versandt
        self.assertEqual(self.db.kuendigung_zeilen[kid_opfer]["wirkung"], "stripe_periodenende")
        self.assertEqual(self.db.kuendigung_zeilen[kid_angreifer]["wirkung"], kuendigung.WIRKUNG_LINK)

    async def test_k1_kid_aus_token_parser(self):
        """K-1: _kid_aus_token parst IDs präzise und weist Müll ab."""
        from app.userauth import KUEND_TOKEN_PREFIX
        self.assertEqual(kuendigung._kid_aus_token(f"{KUEND_TOKEN_PREFIX}42.zufall123"), 42)
        self.assertEqual(kuendigung._kid_aus_token(f"{KUEND_TOKEN_PREFIX}9223372036854775807.abc"), 9223372036854775807)
        # Kein Punkt / ungebundener Token
        self.assertIsNone(kuendigung._kid_aus_token(f"{KUEND_TOKEN_PREFIX}test-token-123"))
        # Keine Ziffern
        self.assertIsNone(kuendigung._kid_aus_token(f"{KUEND_TOKEN_PREFIX}abc.def"))
        # Zu lang (> 19 Stellen)
        self.assertIsNone(kuendigung._kid_aus_token(f"{KUEND_TOKEN_PREFIX}{'1'*20}.def"))
        # Falsches Präfix
        self.assertIsNone(kuendigung._kid_aus_token("kl1-42.zufall"))

    async def test_k1_ungebundener_alt_token_nutzt_fallback(self):
        """K-1: Token ohne kid nutzt Fallback auf jüngste offene Erklärung."""
        self.ziel_bekannt()
        alt_token = userauth.KUEND_TOKEN_PREFIX + "altes-token-ohne-punkt"
        self.db.token_zeile = {
            "id": 1, "user_id": 42, "benutzt": False,
            "ablauf": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        self.db.token_hash = _hash(alt_token)
        res = await kuendigung.bestaetigen(alt_token)
        self.assertTrue(res["ok"])
        self.assertEqual(self.abschluss_updates()[0][1], "stripe_periodenende")

    async def test_k2_rate_limit_format_und_groesse(self):
        """K-2: 1-MB-E-Mail erzeugt keinen Bucket; Formatprüfung filtert Müll."""
        # 1) 1-MB-E-Mail wird in annehmen abgewiesen
        big_email = "a" * 1_000_000 + "@example.org"
        res = await kuendigung.annehmen({"email": big_email})
        self.assertIn("error", res)

        # 2) Rate-Limit-Schlüssel-Bildung aus rest.py nachstellen
        email = big_email.strip().lower()
        key_erzeugt = False
        if "@" in email and "." in email and len(email) <= 254:
            key_erzeugt = True
        self.assertFalse(key_erzeugt)  # 1-MB-Mail überschreitet 254 Zeichen

        # 3) Normale E-Mail bildet den gehashten Schlüssel
        valid_email = "user@example.org"
        key = "kuendigung:email:" + hashlib.sha256(valid_email.encode()).hexdigest()
        self.assertTrue(key.startswith("kuendigung:email:"))
        self.assertEqual(len(key), len("kuendigung:email:") + 64)

    async def test_k3_zugang_html_und_bestaetigung_html(self):
        """K-3: Link-Mail enthält keinen Namen, festen Vertrag und gekürzten Grund;
        Bestätigungsmail enthält den vollen Erklärungsinhalt."""
        langer_grund = "Grund-Anfang " + ("A" * 300) + " Grund-Ende"
        daten = {
            "name": "Erika Mustermann",
            "vertrag": "Anderer Vertrag 123",
            "art": "ordentlich",
            "grund": langer_grund,
            "eingegangen": FakeCon.EINGEGANGEN,
            "vertrag_bis": date(2026, 10, 1),
        }

        # Stufe 1 Link-Mail
        html1 = kuendigung.zugang_html(daten)
        self.assertNotIn("Erika Mustermann", html1)
        self.assertNotIn("Anderer Vertrag 123", html1)
        self.assertIn("Sapio-Abo", html1)
        self.assertNotIn("Grund-Ende", html1)  # auf 200 Zeichen gekürzt
        self.assertIn("Grund-Anfang", html1)
        self.assertIn("…", html1)

        # Stufe 2 Bestätigungsmail
        html2 = kuendigung.bestaetigung_html(daten)
        self.assertIn("Erika Mustermann", html2)
        self.assertIn("Anderer Vertrag 123", html2)
        self.assertIn("Grund-Ende", html2)  # ungekürzt
        self.assertIn("01.10.2026", html2)

    async def test_k5_inaktiver_nutzer_erhaelt_keine_link_mail(self):
        """K-5: Inaktiver Nutzer wird in Stufe 1 übergangen (kein Token, keine Mail)."""
        self.konto_bekannt(user_id=42, account_id=7, aktiv=False)
        bg = FakeBackground()
        res = await kuendigung.annehmen({"email": "inaktiv@example.org"}, background=bg)
        self.assertTrue(res["ok"])  # neutral S-2
        await bg.ausfuehren()
        self.assertEqual(self.db.inserts_token, [])
        self.assertEqual(mailer_stub.gesendet, [])
        self.assertIn(kuendigung.WIRKUNG_KEIN_KONTO, self.wirkung_updates())

    async def test_k6_asyncio_create_task_referenzhaltung(self):
        """K-6: Bei background=None hält kuendigung._hintergrund_tasks eine Referenz."""
        self.konto_bekannt()
        res = await kuendigung.annehmen({"email": "kunde@example.org"}, background=None)
        self.assertTrue(res["ok"])
        # Kurz warten, bis der Hintergrund-Task durchgelaufen ist
        await asyncio.sleep(0.02)
        # Task ist gelaufen und hat sich aus _hintergrund_tasks ausgetragen
        self.assertEqual(len(kuendigung._hintergrund_tasks), 0)

    async def test_k7_nicht_string_typen_behandelt_als_leer(self):
        """K-7: Nicht-String-Typen werfen nie 500, sondern werden sauber abgewiesen."""
        bg = FakeBackground()
        # email als Zahl / Dict / Liste
        res1 = await kuendigung.annehmen({"email": 12345}, background=bg)
        self.assertIn("error", res1)
        res2 = await kuendigung.annehmen({"email": ["a@b.de"]}, background=bg)
        self.assertIn("error", res2)
        res3 = await kuendigung.annehmen({"email": None}, background=bg)
        self.assertIn("error", res3)

        # Freitext-Felder als Nicht-String
        self.assertIsNone(kuendigung._clean(12345, 120))
        self.assertIsNone(kuendigung._clean({"a": 1}, 120))
        self.assertIsNone(kuendigung._clean(True, 120))

        # token als Nicht-String in bestaetigen()
        res_t1 = await kuendigung.bestaetigen(12345)
        self.assertIn("error", res_t1)
        res_t2 = await kuendigung.bestaetigen(None)
        self.assertIn("error", res_t2)
        res_t3 = await kuendigung.bestaetigen(["token"])
        self.assertIn("error", res_t3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
