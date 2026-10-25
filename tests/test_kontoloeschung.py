"""Unit-Tests für die öffentliche Kontolöschung (app/kontoloeschung.py) und die
Zweckbindung der Reset-Tokens (app/userauth.py).

Läuft ohne Postgres, ohne FastAPI und ohne argon2: Die Module mit externen
Abhängigkeiten (app.db, app.mailer, app.services, app.stripe_pay, argon2) werden vor
dem Import durch Stubs ersetzt. Getestet wird die echte Logik von kontoloeschung.py und
userauth.py – inklusive der Sicherheitsregeln aus AND-10:

  • Löschung NIE allein auf Basis der E-Mail-Eingabe (erst Token-Klick),
  • neutrale Antwort der Anfrage (verrät keine Konto-Existenz, F7-Linie),
  • Zweckbindung: Reset-Tokens löschen nicht, Lösch-Tokens setzen kein Passwort zurück,
  • Token einmalig (benutzt) und befristet (ablauf),
  • Kontext (user_id/account_id) für services.loesche_eigenes_konto wird gesetzt,
  • DB-Zugriffe laufen im bypass (FORCE ROW LEVEL SECURITY),

und der Nachbesserungen aus der Sicherheitsprüfung AND-24:

  • S1: Kontolöschung beendet das Stripe-Abo (Fall A: sofort via Subscription.delete,
    Fall B: zum Periodenende via kuendige_abo), Stripe-Fehler blockieren die Löschung
    nicht (echtes app.services, nur db/stripe_pay gestubbt),
  • S2: Mailversand ist vom Request entkoppelt – identische, schnelle Antwort für
    Treffer- und Nein-Zweig (keine Enumeration über die Antwortzeit),
  • S5: Fehlertext nach verbrauchtem Token verlangt einen NEUEN Link,

und der Nachbesserungen aus der Delta-Sicherheitsprüfung AND-38 (AND-75):

  • D1: Fall B nullt stripe_customer_id am Account; stripe_subscription_id bleibt unverändert,
  • D3: Bestätigungstext und Lösch-Mail weisen auf sofortiges Abo-Ende und Verfall hin.

Ausführung vom Repo-Root:
    python3 -m pytest tests/ -q
    python3 -m unittest tests.test_kontoloeschung -v
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import time
import types
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------


class FakeDb:
    """Mini-asyncpg-Ersatz: dispatcht die festen Queries von kontoloeschung.py."""

    def __init__(self):
        self.user = None            # {"id": int} – aktiver User zur E-Mail (oder None)
        self.token_zeile = None     # {"id","user_id","benutzt","ablauf"}
        self.token_hash = None      # nur dieser Hash liefert die token_zeile
        self.account_id = 7         # Mitgliedschaft des Users (None = verwaister Login)
        self.email = "kunde@example.org"
        self.db_fehler = None       # Exception, die fetchrow wirft (Ausfall-Simulation)
        self.inserts = []           # (user_id, token_hash, ablauf)
        self.updates = []           # ids der als benutzt markierten Tokens
        self.orphan_deletes = []    # Löschungen verwaister Logins (user_id)
        self.bypass_aufrufe = []    # bypass-Flag je acquire()

    def fetchrow(self, sql, *args):
        if self.db_fehler:
            raise self.db_fehler
        if "FROM passwort_reset" in sql:
            if self.token_zeile and args and args[0] == self.token_hash:
                return dict(self.token_zeile)
            return None
        if "FROM app_user" in sql:
            return {"id": self.user["id"]} if self.user else None
        return None

    def fetchval(self, sql, *args):
        if self.db_fehler:
            raise self.db_fehler
        if "DELETE FROM app_user" in sql:
            self.orphan_deletes.append(args[0])
            return args[0]
        if "account_mitglied" in sql:
            return self.account_id
        if "email::text FROM app_user" in sql:
            return self.email
        return None

    def execute(self, sql, *args):
        if "INSERT INTO passwort_reset" in sql:
            self.inserts.append(tuple(args))
        elif "UPDATE passwort_reset SET benutzt" in sql:
            self.updates.append(args[0])
        return "DELETE 1"


class FakeCon(FakeDb):
    """Dasselbe Objekt wie FakeDb, zusätzlich mit transaction()-Kontextmanager.
    Die Query-Methoden sind hier async (await-bar) wie beim echten asyncpg."""

    async def fetchrow(self, sql, *args):  # noqa: D102
        return FakeDb.fetchrow(self, sql, *args)

    async def fetchval(self, sql, *args):  # noqa: D102
        return FakeDb.fetchval(self, sql, *args)

    async def execute(self, sql, *args):  # noqa: D102
        return FakeDb.execute(self, sql, *args)

    @asynccontextmanager
    async def transaction(self):
        yield self


class ServicesFakeDb:
    """Mini-asyncpg-Ersatz für das ECHTE services.loesche_eigenes_konto (S1-Tests):
    bedient den Stripe-Vorab-Check, die Mitgliedschafts-Abfragen und die Lösch-EXECUTEs.
    `uid` ist der löschende Nutzer (current_user), `acc` kommt aus current_account."""

    def __init__(self):
        self.sub_id = "sub_test123"   # stripe_subscription_id des Kontos (None = kein Abo)
        self.cust_id = "cus_test123"  # stripe_customer_id des Kontos (D1)
        self.rolle = "owner"          # Rolle des löschenden Nutzers im Haushalt
        self.mitglieder = [42]        # user_ids im Haushalt (Reihenfolge = beigetreten_am)
        self.uid = 42
        self.executes = []            # (sql, args) aller EXECUTEs
        self.bypass_aufrufe = []      # bypass-Flag je acquire()

    async def fetchrow(self, sql, *args):
        if "stripe_subscription_id AS sub" in sql:            # Vorab-Check (S1-Helfer)
            andere = [m for m in self.mitglieder if m != self.uid]
            return {"sub": self.sub_id,
                    "ist_owner": self.rolle == "owner" and self.uid in self.mitglieder,
                    "andere": len(andere)}
        if "rolle FROM account_mitglied" in sql:              # Lösch-Transaktion
            if self.uid in self.mitglieder:
                return {"rolle": self.rolle}
            return None
        return None

    async def fetch(self, sql, *args):
        if "user_id FROM account_mitglied" in sql:
            return [{"user_id": m} for m in self.mitglieder]
        return []

    async def fetchval(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        self.executes.append((sql, args))
        if "UPDATE account" in sql and "stripe_customer_id = NULL" in sql:
            self.cust_id = None
        return "DELETE 1"

    @asynccontextmanager
    async def transaction(self):
        yield self


_db_holder = {"db": None}


@asynccontextmanager
async def _fake_acquire(bypass: bool = False):
    db = _db_holder["db"]
    db.bypass_aufrufe.append(bypass)
    yield db


class _FakePool:
    """pool().acquire() wie beim echten asyncpg-Pool (userauth nutzt pool())."""

    def acquire(self):
        return _fake_acquire()


db_stub = types.ModuleType("app.db")
db_stub.acquire = _fake_acquire
db_stub.pool = lambda: _FakePool()
sys.modules["app.db"] = db_stub

mailer_stub = types.ModuleType("app.mailer")
mailer_stub.gesendet = []
mailer_stub.tasks = []           # geplante Hintergrund-Versände (S2)
mailer_stub.blockieren = None    # asyncio.Event: hält den Versand an (S2-Laufzeittest)


async def _warten_falls_blockiert():
    if mailer_stub.blockieren is not None:
        await mailer_stub.blockieren.wait()


async def _send_konto_loeschung(email, token):
    await _warten_falls_blockiert()
    mailer_stub.gesendet.append(("loeschlink", email, token))
    return {"ok": True}


async def _send_konto_geloescht(email):
    mailer_stub.gesendet.append(("geloescht", email))
    return {"ok": True}


async def _send_passwort_reset(email, token):
    await _warten_falls_blockiert()
    mailer_stub.gesendet.append(("resetlink", email, token))
    return {"ok": True}


def _im_hintergrund(coro):
    """Wie mailer.im_hintergrund (S2): entkoppelt via asyncio.create_task."""
    task = asyncio.create_task(coro)
    mailer_stub.tasks.append(task)
    return task


mailer_stub.send_konto_loeschung = _send_konto_loeschung
mailer_stub.send_konto_geloescht = _send_konto_geloescht
mailer_stub.send_passwort_reset = _send_passwort_reset
mailer_stub.im_hintergrund = _im_hintergrund
sys.modules["app.mailer"] = mailer_stub

services_stub = types.ModuleType("app.services")
services_stub.aufrufe = []
services_stub.fehler = None


async def _loesche_eigenes_konto(modus="selbst"):
    from app.userauth import current_account, current_user
    services_stub.aufrufe.append(
        {"modus": modus, "uid": current_user.get(), "acc": current_account.get()})
    if services_stub.fehler:
        return dict(services_stub.fehler)
    return {"geloescht": True, "modus": modus}


services_stub.loesche_eigenes_konto = _loesche_eigenes_konto
sys.modules["app.services"] = services_stub

# stripe_pay-Stub für die S1-Tests (echtes services.loesche_eigenes_konto ruft
# verfuegbar()/_stripe()/kuendige_abo() daraus auf).
stripe_pay_stub = types.ModuleType("app.stripe_pay")
stripe_pay_stub.kuendige_aufrufe = []
stripe_pay_stub.kuendige_ergebnis = {"ok": True, "stripe": True}
stripe_pay_stub.verfuegbar = lambda: True


class FakeSubscription:
    """Mitschnitt für stripe.Subscription.delete (S1, Fall A)."""
    deleted: list = []
    fehler: Exception | None = None

    @staticmethod
    def delete(sub_id):
        if FakeSubscription.fehler:
            raise FakeSubscription.fehler
        FakeSubscription.deleted.append(sub_id)
        return {"id": sub_id, "status": "canceled"}


stripe_pay_stub._stripe = lambda: types.SimpleNamespace(Subscription=FakeSubscription)


async def _kuendige_abo(acc):
    stripe_pay_stub.kuendige_aufrufe.append(acc)
    return dict(stripe_pay_stub.kuendige_ergebnis)


stripe_pay_stub.kuendige_abo = _kuendige_abo
sys.modules["app.stripe_pay"] = stripe_pay_stub

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

# Jetzt die echten Module unter Test importieren.
import app  # noqa: E402  (leeres Paket-__init__)
from app import kontoloeschung, userauth  # noqa: E402

# Für die S1-Tests (Stripe-Abbruch bei Kontolöschung) zusätzlich das ECHTE
# app.services laden – oben ist es als Stub registriert, weil die kontoloeschung-Tests
# ihn brauchen. Danach den Stub in sys.modules UND als Paket-Attribut wiederherstellen:
# `from . import services` in kontoloeschung.py liest sonst das echte Modul.
sys.modules.pop("app.services", None)
import app.services as services_echt  # noqa: E402
sys.modules["app.services"] = services_stub
app.services = services_stub


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


class _Basis(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeCon()  # FakeDb + transaction()-Kontextmanager
        _db_holder["db"] = self.db
        mailer_stub.gesendet.clear()
        mailer_stub.tasks.clear()
        mailer_stub.blockieren = None
        services_stub.aufrufe.clear()
        services_stub.fehler = None

    def gueltiger_token(self, **overrides):
        """Hinterlegt einen frischen, unbenutzten Lösch-Token in der Fake-DB."""
        token = userauth.LOESCH_TOKEN_PREFIX + "test-token-123"
        zeile = {"id": 1, "user_id": 42, "benutzt": False,
                 "ablauf": datetime.now(timezone.utc) + timedelta(minutes=30)}
        zeile.update(overrides)
        self.db.token_zeile = zeile
        self.db.token_hash = _hash(token)
        return token

    async def mails_abwarten(self):
        """Geplante Hintergrund-Versände ausführen (S2: Versand ist entkoppelt)."""
        if mailer_stub.tasks:
            await asyncio.gather(*mailer_stub.tasks)


class AnforderungTests(_Basis):
    async def test_bekanntes_konto_token_und_mail(self):
        self.db.user = {"id": 42}
        res = await kontoloeschung.anfordern("  Kunde@Example.org ")
        await self.mails_abwarten()                       # S2: Versand im Hintergrund
        self.assertTrue(res["ok"])
        self.assertEqual(len(self.db.inserts), 1)
        uid, th, ablauf = self.db.inserts[0]
        self.assertEqual(uid, 42)
        self.assertEqual(len(mailer_stub.gesendet), 1)
        art, email, token = mailer_stub.gesendet[0]
        self.assertEqual(art, "loeschlink")
        self.assertEqual(email, "kunde@example.org")          # normalisiert
        self.assertTrue(token.startswith(userauth.LOESCH_TOKEN_PREFIX))
        self.assertEqual(_hash(token), th)                    # nur der Hash liegt in der DB
        rest = ablauf - datetime.now(timezone.utc)
        self.assertLess(rest, timedelta(hours=1, seconds=5))  # 1 Stunde gültig
        self.assertGreater(rest, timedelta(minutes=30))
        self.assertEqual(self.db.bypass_aufrufe, [True])      # FORCE RLS → bypass

    async def test_antwort_neutral_verraet_kein_konto(self):
        ohne = await kontoloeschung.anfordern("unbekannt@example.org")
        self.db.user = {"id": 42}
        mit = await kontoloeschung.anfordern("kunde@example.org")
        await self.mails_abwarten()                       # S2: Versand im Hintergrund
        self.assertEqual(ohne, mit)                           # identische Antwort
        self.assertNotIn("kunde", str(ohne).lower())
        self.assertEqual(len(self.db.inserts), 1)             # nur beim echten Konto
        self.assertEqual(len(mailer_stub.gesendet), 1)        # nur eine Mail

    async def test_antwort_wartet_nicht_auf_mailversand(self):
        # S2 (AND-24): Der Versand ist vom Request entkoppelt – Treffer- und Nein-Zweig
        # antworten inhaltlich identisch UND gleich schnell. Blockierender Versand
        # simuliert den Resend-HTTP-Call (Timeout bis 20 s): die Antwort darf darauf
        # nicht warten, sonst wäre die Laufzeit ein Konto-Existenz-Oracle.
        start = time.monotonic()
        res_ohne = await kontoloeschung.anfordern("unbekannt@example.org")
        dauer_ohne = time.monotonic() - start
        self.db.user = {"id": 42}
        mailer_stub.blockieren = asyncio.Event()          # Versand „hängt" am HTTP-Call
        start = time.monotonic()
        res_mit = await kontoloeschung.anfordern("kunde@example.org")
        dauer_mit = time.monotonic() - start
        self.assertEqual(res_ohne, res_mit)                   # identische Antwort
        self.assertLess(dauer_ohne, 0.5)
        self.assertLess(dauer_mit, 0.5)                       # wartet NICHT auf den Versand
        self.assertEqual(mailer_stub.gesendet, [])            # Versand läuft noch
        self.assertEqual(len(mailer_stub.tasks), 1)           # nur im Treffer-Zweig geplant
        mailer_stub.blockieren.set()                          # Versand fertigstellen
        await self.mails_abwarten()
        self.assertEqual(len(mailer_stub.gesendet), 1)
        self.assertEqual(mailer_stub.gesendet[0][0], "loeschlink")

    async def test_unbekannte_email_kein_versand(self):
        res = await kontoloeschung.anfordern("unbekannt@example.org")
        self.assertTrue(res["ok"])
        self.assertEqual(self.db.inserts, [])
        self.assertEqual(mailer_stub.tasks, [])               # nichts geplant (S2)
        self.assertEqual(mailer_stub.gesendet, [])

    async def test_ungueltige_email_ohne_db_zugriff(self):
        res = await kontoloeschung.anfordern("keine-email")
        self.assertTrue(res["ok"])
        self.assertEqual(self.db.inserts, [])
        self.assertEqual(self.db.bypass_aufrufe, [])
        self.assertEqual(mailer_stub.gesendet, [])

    async def test_db_ausfall_ergibt_neutrale_antwort(self):
        self.db.db_fehler = RuntimeError("db weg")
        res = await kontoloeschung.anfordern("kunde@example.org")
        self.assertTrue(res["ok"])                            # nie 500, immer neutral
        self.assertEqual(mailer_stub.gesendet, [])


class ResetAnforderungTests(_Basis):
    """S2 (AND-24) gilt identisch für userauth.passwort_reset_anfordern."""

    async def test_passwort_reset_wartet_nicht_auf_mailversand(self):
        self.db.user = {"id": 42}
        mailer_stub.blockieren = asyncio.Event()          # Versand „hängt" am HTTP-Call
        start = time.monotonic()
        res = await userauth.passwort_reset_anfordern("kunde@example.org")
        dauer = time.monotonic() - start
        self.assertEqual(res, {"ok": True})                   # immer neutrale Antwort
        self.assertLess(dauer, 0.5)                           # wartet NICHT auf den Versand
        self.assertEqual(mailer_stub.gesendet, [])            # Versand läuft noch
        self.assertEqual(len(mailer_stub.tasks), 1)
        mailer_stub.blockieren.set()
        await self.mails_abwarten()
        self.assertEqual(len(mailer_stub.gesendet), 1)
        self.assertEqual(mailer_stub.gesendet[0][0], "resetlink")
        self.assertEqual(len(self.db.inserts), 1)             # Token liegt (gehasht) in der DB


class BestaetigungTests(_Basis):
    async def test_reset_token_ohne_praefix_abgelehnt(self):
        # Zweckbindung: ein Passwort-Reset-Token darf nie eine Löschung auslösen.
        self.db.user = {"id": 42}
        res = await kontoloeschung.bestaetigen("reset-token-ohne-praefix")
        self.assertIn("error", res)
        self.assertEqual(services_stub.aufrufe, [])
        self.assertEqual(self.db.updates, [])

    async def test_unbekannter_token_abgelehnt(self):
        res = await kontoloeschung.bestaetigen(
            userauth.LOESCH_TOKEN_PREFIX + "gibt-es-nicht")
        self.assertIn("error", res)
        self.assertEqual(services_stub.aufrufe, [])

    async def test_benutzter_token_abgelehnt(self):
        token = self.gueltiger_token(benutzt=True)
        res = await kontoloeschung.bestaetigen(token)
        self.assertIn("error", res)
        self.assertEqual(services_stub.aufrufe, [])

    async def test_abgelaufener_token_abgelehnt(self):
        token = self.gueltiger_token(
            ablauf=datetime.now(timezone.utc) - timedelta(minutes=1))
        res = await kontoloeschung.bestaetigen(token)
        self.assertIn("error", res)
        self.assertEqual(services_stub.aufrufe, [])

    async def test_gueltiger_token_loescht_mit_selbst_logik(self):
        token = self.gueltiger_token()
        res = await kontoloeschung.bestaetigen(token)
        self.assertTrue(res["ok"])
        self.assertTrue(res["geloescht"])
        self.assertEqual(self.db.updates, [1])                # Token verbraucht
        # Dieselbe Logik wie POST /konto/loeschen: Modus 'selbst', Kontext gesetzt.
        self.assertEqual(services_stub.aufrufe, [{"modus": "selbst", "uid": 42, "acc": 7}])
        self.assertIn(("geloescht", "kunde@example.org"), mailer_stub.gesendet)
        self.assertTrue(all(self.db.bypass_aufrufe))          # FORCE RLS → bypass

    async def test_verwaister_login_wird_ohne_haushalt_geloescht(self):
        token = self.gueltiger_token()
        self.db.account_id = None                             # keine Mitgliedschaft
        res = await kontoloeschung.bestaetigen(token)
        self.assertTrue(res["ok"])
        self.assertEqual(services_stub.aufrufe, [])            # kein Haushalts-Aufruf
        self.assertEqual(self.db.orphan_deletes, [42])         # nur der Login
        self.assertIn(("geloescht", "kunde@example.org"), mailer_stub.gesendet)

    async def test_service_fehler_wird_zum_error_und_token_bleibt_verbraucht(self):
        token = self.gueltiger_token()
        services_stub.fehler = {"error": "boom"}
        res = await kontoloeschung.bestaetigen(token)
        self.assertIn("error", res)
        # S5 (AND-24): Der Token ist zu diesem Zeitpunkt bereits verbraucht – die
        # Meldung muss zum Anfordern eines NEUEN Links auffordern, nicht zum erneuten
        # Versuch („erneut versuchen" wäre irreführend).
        self.assertIn("neuen Link", res["error"])
        self.assertNotIn("erneut", res["error"])
        self.assertEqual(self.db.updates, [1])                # kein Replay möglich


class StripeLoeschungTests(_Basis):
    """S1 (Sicherheitsprüfung AND-24): Kontolöschung beendet das Stripe-Abo.

    Getestet wird das ECHTE services.loesche_eigenes_konto (gemeinsamer Pfad von
    In-App POST /konto/loeschen und Web-Bestätigungslink); nur app.db und
    app.stripe_pay sind gestubbt."""

    def setUp(self):
        super().setUp()
        self.sdb = ServicesFakeDb()
        _db_holder["db"] = self.sdb
        FakeSubscription.deleted.clear()
        FakeSubscription.fehler = None
        stripe_pay_stub.kuendige_aufrufe.clear()
        stripe_pay_stub.kuendige_ergebnis = {"ok": True, "stripe": True}
        userauth.current_user.set(self.sdb.uid)
        userauth.current_account.set(7)

    def _konto_geloescht(self) -> bool:
        return any("DELETE FROM account WHERE id" in sql for sql, _ in self.sdb.executes)

    async def test_letzter_nutzer_beendet_stripe_abo_sofort(self):
        # Fall A: Haushalt wird komplett gelöscht → Subscription.delete (sofort), denn
        # nach dem Löschen der account-Zeile kann niemand mehr das Periodenende
        # auswerten und invoice.paid würde still weiter abbuchen.
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "haushalt"})
        self.assertEqual(FakeSubscription.deleted, ["sub_test123"])
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [])
        self.assertTrue(self._konto_geloescht())              # account-Zeile weg
        self.assertTrue(all(self.sdb.bypass_aufrufe))         # FORCE RLS → bypass

    async def test_haushalt_modus_beendet_stripe_abo_sofort(self):
        self.sdb.mitglieder = [42, 43]                        # Eigentümer löscht Haushalt
        res = await services_echt.loesche_eigenes_konto("haushalt")
        self.assertEqual(res, {"geloescht": True, "modus": "haushalt"})
        self.assertEqual(FakeSubscription.deleted, ["sub_test123"])
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [])
        self.assertTrue(self._konto_geloescht())

    async def test_loeschung_laeuft_trotz_stripe_fehler_durch(self):
        # Stripe-Ausfall darf die Löschung nie blockieren (wie in kuendige_abo) –
        # der Fehler wird nur protokolliert (log.error mit Sub-ID als Spur).
        FakeSubscription.fehler = RuntimeError("stripe nicht erreichbar")
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "haushalt"})
        self.assertEqual(FakeSubscription.deleted, [])
        self.assertTrue(self._konto_geloescht())

    async def test_eigentuemer_geht_haushalt_bleibt_kuendigt_zum_periodenende(self):
        # Fall B: Eigentümer/Zahler geht, Haushalt bleibt → kuendige_abo
        # (cancel_at_period_end): die bezahlte Periode bleibt dem Haushalt, es folgt
        # keine invoice.paid mehr, die abo_gekuendigt zurücksetzen und die Karte des
        # Ausgeschiedenen dauerhaft weiterbelasten könnte.
        # D1 (AND-38 / AND-75): stripe_customer_id wird genullt, stripe_subscription_id bleibt.
        self.sdb.mitglieder = [42, 43]
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "selbst"})
        self.assertEqual(FakeSubscription.deleted, [])        # NICHT sofort beendet
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [7])
        self.assertTrue(any("abo_gekuendigt = true" in sql for sql, _ in self.sdb.executes))
        self.assertTrue(any("stripe_customer_id = NULL" in sql for sql, _ in self.sdb.executes))
        self.assertFalse(any("stripe_subscription_id" in sql for sql, _ in self.sdb.executes))
        self.assertIsNone(self.sdb.cust_id)
        self.assertEqual(self.sdb.sub_id, "sub_test123")

    async def test_fall_b_stripe_customer_id_genullt_subscription_unveraendert(self):
        # D1 (AND-38 / AND-75): Fall B (Eigentümer geht, Haushalt bleibt).
        # Nach Fall B ist stripe_customer_id leer (None), stripe_subscription_id unverändert.
        self.sdb.mitglieder = [42, 43]
        self.assertEqual(self.sdb.cust_id, "cus_test123")
        self.assertEqual(self.sdb.sub_id, "sub_test123")
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "selbst"})
        self.assertIsNone(self.sdb.cust_id, "stripe_customer_id muss nach Fall B leer sein")
        self.assertEqual(self.sdb.sub_id, "sub_test123", "stripe_subscription_id muss unverändert bleiben")
        update_sqls = [sql for sql, _ in self.sdb.executes if "UPDATE account" in sql]
        self.assertTrue(any("stripe_customer_id = NULL" in s for s in update_sqls))
        self.assertFalse(any("stripe_subscription_id" in s for s in update_sqls))

    async def test_stripe_kuendigung_fehlgeschlagen_loeschung_trotzdem(self):
        self.sdb.mitglieder = [42, 43]
        stripe_pay_stub.kuendige_ergebnis = {"ok": True, "stripe": False}
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "selbst"})

    async def test_mitglied_geht_haushalt_bleibt_stripe_unberuehrt(self):
        # Nicht-Eigentümer geht: Der Zahler bleibt im Haushalt → Abo läuft unverändert.
        self.sdb.rolle = "mitglied"
        self.sdb.mitglieder = [41, 42]                        # 41 bleibt (wird Eigentümer)
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "selbst"})
        self.assertEqual(FakeSubscription.deleted, [])
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [])

    async def test_ohne_stripe_abo_passiert_nichts(self):
        self.sdb.sub_id = None                                # z. B. Gratis-/Beta-Konto
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"geloescht": True, "modus": "haushalt"})
        self.assertEqual(FakeSubscription.deleted, [])
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [])

    async def test_haushalt_modus_ohne_eigentuemer_fasst_stripe_nicht_an(self):
        # modus='haushalt' wird ohne Eigentümer abgelehnt – der Stripe-Vorab-Check
        # spiegelt den Guard und darf das Abo dann nicht anfassen.
        self.sdb.rolle = "mitglied"
        self.sdb.mitglieder = [41, 42]
        res = await services_echt.loesche_eigenes_konto("haushalt")
        self.assertIn("error", res)
        self.assertEqual(FakeSubscription.deleted, [])
        self.assertEqual(stripe_pay_stub.kuendige_aufrufe, [])

    async def test_nicht_angemeldet_wird_abgewiesen(self):
        userauth.current_user.set(None)
        res = await services_echt.loesche_eigenes_konto("selbst")
        self.assertEqual(res, {"error": "nicht angemeldet"})
        self.assertEqual(FakeSubscription.deleted, [])


class ZweckbindungResetTests(_Basis):
    async def test_passwort_reset_lehnt_loesch_token_ab(self):
        # Echtes userauth: Lösch-Präfix wird vor jedem DB-Zugriff abgewiesen.
        res = await userauth.passwort_reset_ausfuehren(
            userauth.LOESCH_TOKEN_PREFIX + "abc", "neuespasswort1")
        self.assertEqual(res, {"error": "Ungültiger Link."})

    async def test_passwort_reset_ohne_token_abgewiesen(self):
        res = await userauth.passwort_reset_ausfuehren("", "neuespasswort1")
        self.assertEqual(res, {"error": "Ungültiger Link."})


class D3AboVerfallshinweisTests(_Basis):
    """D3 (Sicherheitsprüfung AND-38 / AND-75): Hinweis auf sofortiges Abo-Ende
    und Verfall bezahlter Restlaufzeit."""

    def test_loesch_mail_enthaelt_abo_verfallshinweis(self):
        mail_src = (REPO / "app" / "mailer.py").read_text(encoding="utf-8")
        self.assertIn("Ein laufendes Abo endet sofort; die bereits bezahlte Restlaufzeit verfällt.", mail_src)

    def test_konto_loeschen_komponente_enthaelt_abo_verfallshinweis(self):
        jsx_src = (REPO / "koch-web" / "src" / "components" / "KontoLoeschen.jsx").read_text(encoding="utf-8")
        self.assertIn("Ein laufendes Abo endet sofort; die bereits bezahlte Restlaufzeit verfällt.", jsx_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
