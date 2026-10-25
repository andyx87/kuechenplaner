"""Unit-Tests für den Stripe-Webhook-Zweig `art=guthaben` (Sicherheitsfix S-3, AND-22).

Läuft ohne Postgres, ohne FastAPI und ohne echtes Stripe: `app.db`, `argon2`, `asyncpg`
und `stripe` werden vor dem Import der App-Module durch Stubs ersetzt (dasselbe Muster
wie `tests/test_kontoloeschung.py`). Getestet wird die ECHTE Logik von
`app/stripe_pay.py` und `app/billing.py` (`buche`).

Hintergrund S-3 (mittel, Geld): Der Stripe-Webhook läuft ohne Auth-Kontext. Ohne Bypass
setzt `db.acquire()` dann `app.account_id='-1'` (fail-closed, F10) und
`koch.guthaben_buchung` (FORCE ROW LEVEL SECURITY, `WITH CHECK (account_id =
current_setting('app.account_id'))`, migration_ledger_rls.sql) lehnt den INSERT ab –
die Idempotenz-Abfrage sieht außerdem nie eine vorhandene Buchung. Die Fake-DB hier
erzwingt dieselbe Policy, d. h. der alte Code-Pfad (bypass=False, kein Kontext) scheitert
in diesen Tests genau wie in Produktion.

Geprüft wird:
  • Webhook-Zweig `art=guthaben` bucht OHNE Auth-Kontext (via bypass=True),
  • Idempotenz: zweimal dasselbe Event → genau eine Buchung (Claim in `stripe_event`),
  • Idempotenz auch bei Redelivery nach Claim-Freigabe (Zweck `Stripe:<session_id>`),
  • Redirect-Pfad (mit Auth-Kontext) bucht weiter OHNE Bypass,
  • Regression: ohne Bypass und ohne Kontext verhindert die RLS-Policy die Buchung,
  • Kontobindung bleibt: fremde Session (anderes account_id in den Metadaten) wird
    auch mit Bypass abgelehnt; der Bypass wirkt nur im `async with`-Block.

Ausführung vom Repo-Root:
    python3 tests/test_stripe_webhook_guthaben.py
    python3 -m unittest tests.test_stripe_webhook_guthaben -v
"""
from __future__ import annotations

import json
import os
import sys
import types
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------


class RlsPolicyFehler(Exception):
    """Modelliert die WITH CHECK-Verletzung von koch.guthaben_buchung (FORCE RLS)."""


class FakeDb:
    """Mini-asyncpg-Ersatz: dispatcht die festen Queries von stripe_pay.bestaetige(),
    billing.buche() und dem Event-Claim – und erzwingt die RLS-Policy der
    migration_ledger_rls.sql (USING/WITH CHECK: bypass ODER account_id = Kontext)."""

    def __init__(self):
        self.konten = {7: Decimal("0"), 8: Decimal("0")}   # account.id → guthaben_cents
        self.buchungen = []          # guthaben_buchung-Zeilen (dicts)
        self.stripe_events = set()   # Idempotenz-Claim-Tabelle stripe_event
        self.bypass_aufrufe = []     # bypass-Flag je acquire()
        self.bypass = False          # Zustand NUR innerhalb des acquire-Blocks
        self.ctx_account = -1        # app.account_id (ohne Auth-Kontext fail-closed -1, F10)

    def _rls_check(self, account_id):
        """WITH CHECK (migration_ledger_rls.sql): bypass='on' ODER account_id = Kontext."""
        if not self.bypass and int(account_id) != int(self.ctx_account):
            raise RlsPolicyFehler(
                f"new row violates row-level security policy (account_id={account_id}, "
                f"app.account_id={self.ctx_account})")

    def _sichtbar(self, account_id):
        """USING-Klausel: ohne Bypass sind nur Zeilen des eigenen Kontexts sichtbar."""
        return self.bypass or int(account_id) == int(self.ctx_account)

    async def execute(self, sql, *args):
        if "INSERT INTO stripe_event" in sql:
            if args[0] in self.stripe_events:
                return "INSERT 0 0"
            self.stripe_events.add(args[0])
            return "INSERT 0 1"
        if "DELETE FROM stripe_event" in sql:
            self.stripe_events.discard(args[0])
            return "DELETE 1"
        if sql.startswith("SELECT 1 FROM account WHERE id = $1 FOR UPDATE"):
            return "SELECT 1"
        if "INSERT INTO guthaben_buchung" in sql:
            self._rls_check(args[0])
            self.buchungen.append({"account_id": args[0], "app": args[1],
                                   "betrag_cents": args[2], "typ": args[3],
                                   "zweck": args[4]})
            return "INSERT 0 1"
        raise AssertionError(f"unerwartetes execute(): {sql}")

    async def fetchval(self, sql, *args):
        if "FROM guthaben_buchung WHERE account_id = $1 AND zweck = $2" in sql:
            if not self._sichtbar(args[0]):
                return None   # RLS zeigt die Buchung nicht – Kern des S-3-Bugs
            return 1 if any(b["account_id"] == args[0] and b["zweck"] == args[1]
                            for b in self.buchungen) else None
        if "SELECT guthaben_cents FROM account WHERE id = $1 FOR UPDATE" in sql:
            return self.konten.get(args[0])
        if "UPDATE account SET guthaben_cents" in sql:
            if args[0] not in self.konten:
                return None
            self.konten[args[0]] += args[1]
            return self.konten[args[0]]
        if "SELECT guthaben_cents FROM account WHERE id = $1" in sql:
            return self.konten.get(args[0])
        raise AssertionError(f"unerwartetes fetchval(): {sql}")

    @asynccontextmanager
    async def transaction(self):
        yield self


class FakeCon(FakeDb):
    pass


_db_holder = {"db": None}


@asynccontextmanager
async def _fake_acquire(bypass: bool = False):
    """Spiegelt app.db.acquire(): Kontext aus der ContextVar (ohne Auth fail-closed -1),
    Bypass-Flag nur für die Dauer des Blocks, danach zurückgesetzt."""
    # Bewusst die auf Modulebene importierte ContextVar (unten) statt eines späten
    # Imports: nach der Wiederherstellung fremder app-Module (AND-84) zeigt
    # sys.modules["app.userauth"] sonst auf ein anderes userauth-Modul.
    db = _db_holder["db"]
    db.bypass_aufrufe.append(bypass)
    db.bypass = bypass
    acc = current_account.get()
    db.ctx_account = acc if acc is not None else -1
    try:
        yield db
    finally:
        db.bypass = False


# Testisolation (Rebase auf main nach PR #44, AND-84): tests/test_kontoloeschung.py
# registriert eigene Stubs für app.stripe_pay, app.db und app.services in sys.modules
# und räumt sie nicht weg. Läuft diese Datei danach in derselben pytest-Sitzung, käme
# `from app import stripe_pay` sonst beim Stub statt beim echten Modul an
# (AttributeError: kein handle_webhook). Deshalb alle bereits geladenen app-Module
# beiseitelegen, unten mit den Stubs dieser Datei frisch importieren und den fremden
# Zustand danach wiederherstellen (späte Importe wie `from . import services` in
# kontoloeschung.py müssen ihre Stubs weiter finden). stripe_pay/billing importieren
# nur auf Modulebene und behalten die hier geladenen Objekte.
_fremde_app_module = {
    m: sys.modules.pop(m) for m in list(sys.modules) if m == "app" or m.startswith("app.")
}

db_stub = types.ModuleType("app.db")
db_stub.acquire = _fake_acquire
db_stub.pool = lambda: None
sys.modules["app.db"] = db_stub

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

# asyncpg-Stub (billing.py importiert das Modul; Exceptions nur als Typen benötigt).
asyncpg_stub = types.ModuleType("asyncpg")


class _PostgresError(Exception):
    pass


asyncpg_exc = types.ModuleType("asyncpg.exceptions")


class UndefinedColumnError(_PostgresError):
    pass


class InvalidColumnReferenceError(_PostgresError):
    pass


asyncpg_exc.UndefinedColumnError = UndefinedColumnError
asyncpg_exc.InvalidColumnReferenceError = InvalidColumnReferenceError
asyncpg_stub.PostgresError = _PostgresError
asyncpg_stub.exceptions = asyncpg_exc
sys.modules["asyncpg"] = asyncpg_stub
sys.modules["asyncpg.exceptions"] = asyncpg_exc

# stripe-Stub: Webhook-Signaturprüfung + Session.retrieve gegen feste Testdaten.
stripe_stub = types.ModuleType("stripe")
stripe_stub.api_key = ""


class _FakeSession:
    """checkout.Session – Testdaten liegen in FakeDb-Instanz (pro Test frisch)."""

    @staticmethod
    def retrieve(session_id):
        sessions = _db_holder["db"].stripe_sessions
        if session_id not in sessions:
            raise KeyError(f"keine solche Session: {session_id}")
        return dict(sessions[session_id])


class _FakeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        if not secret:
            raise ValueError("kein Webhook-Secret")
        return json.loads(payload)


stripe_stub.checkout = types.SimpleNamespace(Session=_FakeSession)
stripe_stub.Webhook = _FakeWebhook
sys.modules["stripe"] = stripe_stub

# Jetzt die echten Module unter Test importieren.
import app  # noqa: E402,F401  (leeres Paket-__init__)
from app import stripe_pay  # noqa: E402
from app.userauth import current_account  # noqa: E402

# sys.modules für den app-Namensraum exakt auf den Zustand vor dieser Datei zurücksetzen
# (eigene Stubs und frisch geladene Module raus, fremde wieder rein), siehe oben. Diese
# Datei hält ihre Modulobjekte (stripe_pay, current_account) als Referenz.
for _name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
    del sys.modules[_name]
sys.modules.update(_fremde_app_module)

ACC = 7           # Testkonto
BETRAG = 1000     # 10,00 € Aufladung
SESSION_ID = "cs_test_1"
EVENT_ID = "evt_test_1"


def _guthaben_event(event_id=EVENT_ID, session_id=SESSION_ID, acc=ACC):
    """checkout.session.completed-Event, wie Stripe es zustellt (art=guthaben)."""
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "metadata": {"account_id": str(acc), "art": "guthaben"},
        }},
    }


class _Basis(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"          # Test-Dummies, keine
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_dummy"   # echten Schlüssel
        db = FakeCon()
        db.stripe_sessions = {
            SESSION_ID: {"payment_status": "paid", "amount_total": BETRAG,
                         "metadata": {"account_id": str(ACC), "art": "guthaben"}},
            # Gehört Konto 8 – darf Konto 7 nie gutgeschrieben werden (Metadaten-Prüfung).
            "cs_fremd": {"payment_status": "paid", "amount_total": 2500,
                         "metadata": {"account_id": "8", "art": "guthaben"}},
        }
        _db_holder["db"] = self.db = db

    async def webhook(self, event=None):
        ev = event if event is not None else _guthaben_event()
        return await stripe_pay.handle_webhook(json.dumps(ev).encode(), "t=0,v1=dummy")


class WebhookGuthabenTests(_Basis):
    async def test_webhook_bucht_ohne_auth_kontext_mit_bypass(self):
        # KEIN current_account gesetzt – exakt die Webhook-Situation (S-3).
        res = await self.webhook()
        self.assertTrue(res["ok"])
        self.assertTrue(res["verbucht"])
        self.assertEqual(len(self.db.buchungen), 1)
        b = self.db.buchungen[0]
        self.assertEqual(b["account_id"], ACC)
        self.assertEqual(b["betrag_cents"], Decimal(BETRAG))
        self.assertEqual(b["typ"], "aufladung")
        self.assertEqual(b["zweck"], f"Stripe:{SESSION_ID}")
        self.assertEqual(self.db.konten[ACC], Decimal(BETRAG))
        # Claim + Buchung laufen im Webhook durchweg mit Bypass; danach zurückgesetzt.
        self.assertEqual(self.db.bypass_aufrufe, [True, True])
        self.assertFalse(self.db.bypass)

    async def test_dasselbe_event_zweimal_genau_eine_buchung(self):
        # Idempotenz-Nachweis (Auftragspunkt 3): Event-Claim in stripe_event.
        r1 = await self.webhook()
        r2 = await self.webhook()
        self.assertTrue(r1["verbucht"])
        self.assertEqual(r2, {"ok": True, "duplikat": EVENT_ID})
        self.assertEqual(len(self.db.buchungen), 1)
        self.assertEqual(self.db.konten[ACC], Decimal(BETRAG))

    async def test_redelivery_nach_claim_freigabe_bleibt_idempotent(self):
        # Stripe stellt ein bereits verbuchtes Event erneut zu, obwohl der Claim
        # freigegeben wurde (z. B. Absturz nach der Buchung): die Zweck-Idempotenz
        # in bestaetige() muss die Doppelbuchung verhindern. Vor dem Fix sah die
        # Idempotenz-Abfrage ohne Bypass nie die vorhandene Buchung (RLS/USING).
        await self.webhook()
        self.db.stripe_events.clear()          # simulierte Claim-Freigabe
        r2 = await self.webhook()
        self.assertTrue(r2["ok"])
        self.assertFalse(r2["verbucht"])
        self.assertEqual(len(self.db.buchungen), 1)
        self.assertEqual(self.db.konten[ACC], Decimal(BETRAG))

    async def test_db_fehler_gibt_idempotenz_claim_wieder_frei(self):
        # DB-Ausfall während der Verarbeitung → Exception (Endpoint 500) UND der
        # Idempotenz-Claim wird zurückgenommen, damit der Stripe-Retry neu kann.
        orig_execute = self.db.execute

        async def kaputt(sql, *args):
            if "INSERT INTO guthaben_buchung" in sql:
                raise RuntimeError("db weg")
            return await orig_execute(sql, *args)

        self.db.execute = kaputt
        with self.assertRaises(RuntimeError):
            await self.webhook()
        self.assertEqual(self.db.stripe_events, set())   # Claim freigegeben
        self.assertEqual(self.db.buchungen, [])

    async def test_fehler_ohne_bypass_wuerde_an_rls_scheitern(self):
        # Regression/Kern von S-3: alter Pfad (bypass=False) ohne Auth-Kontext – die
        # RLS-Policy (hier wie in Produktion erzwungen) verhindert die Buchung.
        with self.assertRaises(RlsPolicyFehler):
            await stripe_pay.bestaetige(SESSION_ID, ACC)          # Default: kein Bypass
        self.assertEqual(self.db.buchungen, [])
        self.assertEqual(self.db.konten[ACC], Decimal("0"))

    async def test_fremde_session_wird_auch_mit_bypass_abgelehnt(self):
        # Kontobindung bleibt explizit: Session-Metadaten (Konto 8) ≠ Ziel-Konto (7).
        res = await stripe_pay.bestaetige("cs_fremd", ACC, bypass=True)
        self.assertFalse(res["gutgeschrieben"])
        self.assertEqual(self.db.buchungen, [])
        self.assertEqual(self.db.konten[ACC], Decimal("0"))
        self.assertEqual(self.db.konten[8], Decimal("0"))


class RedirectPfadTests(_Basis):
    async def test_mit_auth_kontext_ohne_bypass(self):
        # Redirect-Pfad (POST /guthaben/checkout-bestaetigen): auth() setzt die
        # ContextVar → acquire() nutzt das echte Konto, Bypass bleibt aus.
        token = current_account.set(ACC)
        try:
            res = await stripe_pay.bestaetige(SESSION_ID, ACC)    # bypass=False (Default)
        finally:
            current_account.reset(token)
        self.assertTrue(res["gutgeschrieben"])
        self.assertEqual(res["betrag_cents"], BETRAG)
        self.assertEqual(self.db.bypass_aufrufe, [False])
        self.assertEqual(len(self.db.buchungen), 1)
        self.assertEqual(self.db.konten[ACC], Decimal(BETRAG))

    async def test_redirect_und_webhook_zusammen_buchen_genau_einmal(self):
        # Kunde kommt über den Redirect zurück UND Stripe liefert das Event: beide
        # Wege teilen dieselbe Zweck-Idempotenz → genau eine Buchung.
        token = current_account.set(ACC)
        try:
            r1 = await stripe_pay.bestaetige(SESSION_ID, ACC)     # Redirect (ohne Bypass)
        finally:
            current_account.reset(token)
        r2 = await self.webhook()                                 # Webhook (mit Bypass)
        self.assertTrue(r1["gutgeschrieben"])
        self.assertTrue(r2["ok"])
        self.assertFalse(r2["verbucht"])                          # bereits verbucht
        self.assertEqual(len(self.db.buchungen), 1)
        self.assertEqual(self.db.konten[ACC], Decimal(BETRAG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
