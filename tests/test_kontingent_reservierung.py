"""Unit-Tests für S-7: Kontingent und Bild-Credits atomar reservieren (AND-22 / AND-35).

Läuft ohne Postgres, ohne asyncpg, ohne FastAPI und ohne google-auth: `app.db`,
`app.userauth`, `app.gauth` und `asyncpg` werden vor dem Import durch Stubs ersetzt.
Getestet wird die echte Logik aus `app/billing.py` (gate_v4/freigeben_v4/complete/
record_usage/record_bild_gemini) und `app/bilder.py` (generiere_rezeptbild).

Die Fake-DB erzwingt die drei Mechanismen produktionsgleich, auf denen der Fix beruht:
  • FORCE ROW LEVEL SECURITY (Konto-Kontext `app.account_id`, fail-closed ohne Kontext,
    WITH CHECK gegen fremde account_id),
  • `SELECT … FOR UPDATE` als Konto-Row-Lock, der die Gates eines Kontos serialisiert,
  • Transaktionen inkl. Rollback.
Dazu kommt die Tabelle `ki_reservierung` (migration_ki_reservierung.sql) mit `ablauf`.

Kernnachweis (Auftrag AND-35, Ziel 3): 10 parallele Anfragen gegen ein Konto mit
1 Credit bzw. 1 freiem Kontingentplatz → GENAU EINE kommt durch, der Modellaufruf läuft
einmal (Mock), die übrigen 9 erhalten LimitErreicht. Ohne die Vorab-Reservierung
(Stand vor S-7) bestanden alle 10 dieselbe Prüfung.

Ausführung vom Repo-Root:
    python3 -m pytest tests/test_kontingent_reservierung.py -q
    python3 tests/test_kontingent_reservierung.py
"""
from __future__ import annotations

import asyncio
import copy
import sys
import types
import unittest
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ACC = 7          # Test-Konto
UID = 42         # Test-Nutzer


# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------

# Testisolation (wie in test_stripe_webhook_guthaben.py): bereits geladene app-Module
# und asyncpg beiseitelegen, unten mit den Stubs dieser Datei frisch importieren und
# den fremden Zustand danach wiederherstellen, damit nachfolgende Tests in derselben
# pytest-Sitzung ungestört bleiben.
_fremde_app_module = {
    m: sys.modules.pop(m) for m in list(sys.modules) if m == "app" or m.startswith("app.")
}
_fremdes_asyncpg = sys.modules.pop("asyncpg", None)


class PostgresError(Exception):
    pass


class UndefinedTableError(PostgresError):
    """asyncpg: relation … does not exist (SQLSTATE 42P01)."""
    sqlstate = "42P01"


asyncpg_stub = types.ModuleType("asyncpg")
asyncpg_stub.PostgresError = PostgresError
asyncpg_stub.UndefinedTableError = UndefinedTableError
sys.modules["asyncpg"] = asyncpg_stub

current_account: "ContextVar[int | None]" = ContextVar("current_account", default=None)
current_user: "ContextVar[int | None]" = ContextVar("current_user", default=None)


async def _darf_ki(user_id, account_id) -> bool:
    return True


userauth_stub = types.ModuleType("app.userauth")
userauth_stub.current_account = current_account
userauth_stub.current_user = current_user
userauth_stub.darf_ki = _darf_ki
sys.modules["app.userauth"] = userauth_stub

gauth_stub = types.ModuleType("app.gauth")
gauth_stub.get_token = lambda: "stub-token"
sys.modules["app.gauth"] = gauth_stub


# ---------- Fake-DB ----------

class RlsVerletzung(Exception):
    """Die FORCE-RLS-Policy (WITH CHECK) hat den Schreibzugriff abgelehnt."""


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _monatsanfang() -> datetime:
    j = _jetzt()
    return j.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _tarif(code: str, ki_limit, bild_limit, ist_payg=False) -> dict:
    return {"code": code, "name": code.capitalize(), "ist_payg": ist_payg,
            "preis_cents": 0, "markup_prozent": 0, "tages_limit_cents": None,
            "wochen_limit_cents": None, "monats_ki_limit": ki_limit,
            "monats_bild_limit": bild_limit, "sortierung": 0, "aktiv": True}


class FakeDatenbank:
    """Geteilter Zustand aller „Verbindungen": Tabellen, Row-Locks, Sequenzen."""

    def __init__(self):
        self.accounts = {ACC: {"id": ACC, "name": "Test", "bild_credits": 0,
                               "guthaben_cents": 0, "tarif_code": "gratis",
                               "payg_overage": False, "abo_bezahlt_bis": None,
                               "trial_bis": None, "abo_status": "aktiv",
                               "einstellungen": {}}}
        self.tarife = {"gratis": _tarif("gratis", 10, 3),
                       "abo": _tarif("abo", None, 50),
                       "payg": _tarif("payg", None, None, ist_payg=True)}
        self.ai_nutzung: list[dict] = []        # abgeschlossene Aufrufe
        self.reservierungen: list[dict] = []    # ki_reservierung: laufende Aufrufe
        self.reservierung_tabelle = True        # False = Migration fehlt
        self.naechste_id = 1000
        self.row_locks: "dict[int, asyncio.Lock]" = {}
        self.modell_aufrufe = 0
        self.bild_aufrufe = 0

    # -- Transaktions-Sicherung (Rollback) --
    def snapshot(self) -> dict:
        return {"accounts": copy.deepcopy(self.accounts),
                "ai_nutzung": list(self.ai_nutzung),
                "reservierungen": list(self.reservierungen),
                "naechste_id": self.naechste_id}

    def zurueck(self, snap: dict) -> None:
        self.accounts = snap["accounts"]
        self.ai_nutzung = snap["ai_nutzung"]
        self.reservierungen = snap["reservierungen"]
        self.naechste_id = snap["naechste_id"]

    # -- Testhelfer --
    def konto(self) -> dict:
        return self.accounts[ACC]

    def aktive_reservierungen(self) -> list[dict]:
        jetzt = _jetzt()
        return [z for z in self.reservierungen
                if z["account_id"] == ACC and z["ablauf"] > jetzt]

    def reservierung_anlegen(self, art: str, *, minuten: int = -1, zweck: str = "rezept-bild"):
        """Reservierungszeile direkt einfügen (für Crash-/Ablauf-Szenarien)."""
        self.naechste_id += 1
        zeile = {"id": self.naechste_id, "account_id": ACC, "user_id": UID, "zweck": zweck,
                 "art": art, "erstellt": _jetzt(),
                 "ablauf": _jetzt() + timedelta(minutes=minuten)}
        self.reservierungen.append(zeile)
        return zeile["id"]


class FakeCon:
    """Eine Verbindung: RLS-Kontext (`app.account_id`), Row-Locks, Transaktionen."""

    def __init__(self, db: FakeDatenbank, konto, bypass: bool = False):
        self.db = db
        self.konto = konto
        self.bypass = bypass
        self._gehalten: "dict[int, int]" = {}   # account_id -> Haltecount (reentrant)
        self.sql_log: list[str] = []

    # -- RLS --
    def _sichtbar(self, account_id) -> bool:
        """FORCE ROW LEVEL SECURITY: fremde/fehlende Mandanten sehen nichts."""
        if self.bypass:
            return True
        return self.konto is not None and account_id is not None and int(account_id) == int(self.konto)

    def _konto_zeile(self, account_id):
        if not self._sichtbar(account_id):
            return None
        return self.db.accounts.get(int(account_id))

    def _schreiben_erlaubt(self, account_id) -> None:
        if not self._sichtbar(account_id):
            raise RlsVerletzung(
                f"new row for relation \"ki_reservierung\" violates row-level security policy "
                f"(account_id={account_id}, app.account_id={self.konto})")

    # -- Row-Lock (SELECT … FOR UPDATE) --
    async def _row_lock(self, account_id) -> None:
        if not self._sichtbar(account_id) or int(account_id) not in self.db.accounts:
            return                      # RLS: keine Zeile → kein Lock
        aid = int(account_id)
        if self._gehalten.get(aid):       # dieselbe Transaktion hält ihn schon
            self._gehalten[aid] += 1
            return
        lock = self.db.row_locks.setdefault(aid, asyncio.Lock())
        await lock.acquire()
        self._gehalten[aid] = 1

    async def _locks_freigeben(self) -> None:
        for aid, n in list(self._gehalten.items()):
            lock = self.db.row_locks.get(aid)
            if lock is not None and lock.locked():
                lock.release()
            del self._gehalten[aid]

    @asynccontextmanager
    async def transaction(self):
        snap = self.db.snapshot()
        try:
            yield self
        except BaseException:
            self.db.zurueck(snap)         # Rollback wie in Postgres
            raise
        finally:
            await self._locks_freigeben()  # COMMIT/ROLLBACK gibt den Row-Lock frei

    # -- Query-Dispatch (wie asyncpg) --
    @staticmethod
    def _norm(sql: str) -> str:
        return " ".join(sql.split())

    def _tabelle(self) -> None:
        if not self.db.reservierung_tabelle:
            raise UndefinedTableError('relation "ki_reservierung" does not exist')

    async def fetchval(self, sql, *args):
        s = self._norm(sql)
        self.sql_log.append(s)
        if "FROM ki_reservierung LIMIT 1" in s:
            self._tabelle()
            return 1
        if "FROM account WHERE id = $1 FOR UPDATE" in s:
            await self._row_lock(args[0])
            zeile = self._konto_zeile(args[0])
            return 1 if zeile else None
        if "UPDATE account SET bild_credits = bild_credits - 1" in s:
            acc = self._konto_zeile(args[0])
            self._schreiben_erlaubt(args[0])
            if acc is None or int(acc["bild_credits"]) <= 0:
                return None               # WHERE bild_credits > 0 greift nicht
            acc["bild_credits"] = int(acc["bild_credits"]) - 1
            return acc["bild_credits"]
        if "UPDATE account SET bild_credits = bild_credits + $2" in s:
            acc = self._konto_zeile(args[0])
            self._schreiben_erlaubt(args[0])
            if acc is not None:
                acc["bild_credits"] = int(acc["bild_credits"]) + int(args[1])
            return "UPDATE 1"
        if "UPDATE account SET bild_credits = bild_credits + 1" in s:
            acc = self._konto_zeile(args[0])
            self._schreiben_erlaubt(args[0])
            if acc is not None:
                acc["bild_credits"] = int(acc["bild_credits"]) + 1
            return "UPDATE 1"
        if "DELETE FROM ki_reservierung WHERE id = $1 RETURNING" in s:
            self._tabelle()
            passende = [
                z for z in self.db.reservierungen
                if z["id"] == args[0] and self._sichtbar(z["account_id"])
            ]
            if not passende:
                return None
            self.db.reservierungen = [
                z for z in self.db.reservierungen
                if not (z["id"] == args[0] and self._sichtbar(z["account_id"]))
            ]
            if "RETURNING art" in s:
                return passende[0]["art"]
            return passende[0]["id"]
        if "INSERT INTO ki_reservierung" in s:
            self._tabelle()
            self._schreiben_erlaubt(args[0])
            self.db.naechste_id += 1
            zeile = {"id": self.db.naechste_id, "account_id": args[0], "user_id": args[1],
                     "zweck": args[2], "art": args[3], "erstellt": _jetzt(),
                     "ablauf": _jetzt() + timedelta(minutes=int(args[4]))}
            self.db.reservierungen.append(zeile)
            return zeile["id"]
        if "SELECT bild_credits FROM account" in s:
            acc = self._konto_zeile(args[0])
            return acc["bild_credits"] if acc else None
        if "SELECT guthaben_cents FROM account" in s:
            acc = self._konto_zeile(args[0])
            return acc["guthaben_cents"] if acc else None
        if "SELECT payg_overage FROM account" in s:
            acc = self._konto_zeile(args[0])
            return acc["payg_overage"] if acc else None
        return None

    async def fetchrow(self, sql, *args):
        s = self._norm(sql)
        self.sql_log.append(s)
        if "FROM tarif WHERE code = $1" in s:
            t = self.db.tarife.get(args[0])
            return dict(t) if t else None
        if "FROM account WHERE id = $1" in s:
            acc = self._konto_zeile(args[0])
            return dict(acc) if acc else None
        if "FROM ai_nutzung" in s:
            anfang = _monatsanfang()
            eigene = [z for z in self.db.ai_nutzung if self._sichtbar(z["account_id"])]
            ki = sum(1 for z in eigene
                     if z["zweck"] in billing._KI_TEXT_ZWECKE_V4 and z["erstellt"] >= anfang)
            bilder = sum(1 for z in eigene
                         if z["zweck"] == "rezept-bild" and z["erstellt"] >= anfang)
            return {"ki": ki, "bilder": bilder}
        if "FROM ki_reservierung WHERE ablauf > now()" in s:
            self._tabelle()
            jetzt = _jetzt()
            eigene = [z for z in self.db.reservierungen
                      if self._sichtbar(z["account_id"]) and z["ablauf"] > jetzt]
            return {"ki": sum(1 for z in eigene if z["art"] == "ki"),
                    "bilder": sum(1 for z in eigene if z["art"] != "ki")}
        return None

    async def fetch(self, sql, *args):
        s = self._norm(sql)
        self.sql_log.append(s)
        if "DELETE FROM ki_reservierung WHERE ablauf <= now()" in s:
            self._tabelle()
            jetzt = _jetzt()
            behalten, geraeumt = [], []
            for z in self.db.reservierungen:
                if z["ablauf"] <= jetzt and self._sichtbar(z["account_id"]):
                    geraeumt.append(z)
                else:
                    behalten.append(z)
            self.db.reservierungen = behalten
            return [{"art": z["art"]} for z in geraeumt]
        return []

    async def execute(self, sql, *args):
        s = self._norm(sql)
        self.sql_log.append(s)
        if "INSERT INTO ai_nutzung" in s:
            # account_id kommt aus dem RLS-Kontext (Spalten-Default), nicht aus dem Code.
            if self.konto is None or int(self.konto) < 0:
                raise RlsVerletzung("ai_nutzung: kein Mandanten-Kontext (fail-closed, F10)")
            if "'rezept-bild'" in s:
                # record_bild_gemini: der Zweck steht literal im SQL, $2..$6 verschieben sich.
                zweck, rest = "rezept-bild", args
            else:
                zweck, rest = args[1], (args[0],) + args[2:]
            self.db.naechste_id += 1
            self.db.ai_nutzung.append({
                "id": self.db.naechste_id, "account_id": self.konto, "user_id": rest[0],
                "zweck": zweck, "modell": rest[1], "prompt_tokens": rest[2],
                "completion_tokens": rest[3], "total_tokens": rest[4],
                "kosten_cents": rest[5], "erstellt": _jetzt()})
            return "INSERT 0 1"
        if "DELETE FROM ki_reservierung WHERE id = $1" in s:
            self._tabelle()
            self.db.reservierungen = [
                z for z in self.db.reservierungen
                if not (z["id"] == args[0] and self._sichtbar(z["account_id"]))]
            return "DELETE 1"
        if "UPDATE account SET bild_credits" in s:
            return await self.fetchval(sql, *args)
        return "OK"


_db_holder = {"db": None}


@asynccontextmanager
async def _fake_acquire(bypass: bool = False):
    db = _db_holder["db"]
    acc = current_account.get()
    # F10: ohne Auth-Kontext ein unmögliches Konto → RLS liefert nichts (fail-closed).
    con = FakeCon(db, acc if acc is not None else -1, bypass=bypass)
    try:
        yield con
    finally:
        await con._locks_freigeben()


db_stub = types.ModuleType("app.db")
db_stub.acquire = _fake_acquire
db_stub.pool = lambda: None
db_stub.set_no_context_account = lambda account_id: None
sys.modules["app.db"] = db_stub

# Jetzt die echten Module unter Test importieren.
import app  # noqa: E402  (leeres Paket-__init__)
from app import billing, bilder, config  # noqa: E402

# sys.modules für den app-Namensraum und asyncpg exakt auf den Zustand vor dieser Datei
# zurücksetzen (eigene Stubs raus, fremde wieder rein). Diese Datei hält ihre Modulobjekte
# (billing, bilder, config) als direkte Referenz.
for _name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
    del sys.modules[_name]
sys.modules.update(_fremde_app_module)
if _fremdes_asyncpg is not None:
    sys.modules["asyncpg"] = _fremdes_asyncpg
else:
    sys.modules.pop("asyncpg", None)


# ---------- Mocks für die Modellaufrufe ----------

class FakeCompletions:
    """OpenAI-kompatibler Stub für client.chat.completions.create()."""

    def __init__(self, db: FakeDatenbank):
        self.db = db
        self.fehler: "BaseException | None" = None
        self.leer = False            # True = leere Antwort (kein Inhalt, keine Tool-Calls)
        self.keine_choices = False   # True = choices=[]
        self.usage: "SimpleNamespace | None | object" = ...  # Default 120 Tokens, None = keine Usage
        self.verzoegerung = 0.01     # Rennfenster für die Nebenläufigkeitstests
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.db.modell_aufrufe += 1
        if self.verzoegerung:
            await asyncio.sleep(self.verzoegerung)
        if self.fehler:
            raise self.fehler
        inhalt = "" if self.leer else "Bitte sehr."
        choices = [] if self.keine_choices else [
            SimpleNamespace(message=SimpleNamespace(content=inhalt, tool_calls=None))
        ]
        if self.usage is ...:
            u = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        else:
            u = self.usage
        return SimpleNamespace(
            model=kwargs.get("model"),
            choices=choices,
            usage=u)


async def _warte_bis(bedingung, timeout=2.0):
    """Pollt, bis die Bedingung True ist (sonst Timeout-Fehler des Tests)."""
    async def _poll():
        while not bedingung():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(_poll(), timeout=timeout)


class _Basis(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDatenbank()
        _db_holder["db"] = self.db
        billing._reservierung_verfuegbar = None     # Prozess-Flag je Test zurücksetzen
        config.ABO_MODELL_V4 = True                 # v4-Kontingent-Modell
        self.client = FakeCompletions(self.db)
        self._ctx_acc = current_account.set(ACC)
        self._ctx_uid = current_user.set(UID)
        # Bild-Pfad: Vertex-Aufruf und JPEG-Aufbereitung ersetzen (kein httpx/PIL nötig).
        self._alt_generate = bilder._gemini_bild_generate
        self._alt_resize = bilder.quadrat_resize
        bilder._gemini_bild_generate = self._fake_generate
        bilder.quadrat_resize = lambda raw, max_px=768: "data:image/jpeg;base64,stub"

    def tearDown(self):
        bilder._gemini_bild_generate = self._alt_generate
        bilder.quadrat_resize = self._alt_resize
        current_account.reset(self._ctx_acc)
        current_user.reset(self._ctx_uid)
        config.ABO_MODELL_V4 = False
        billing._reservierung_verfuegbar = None

    async def _fake_generate(self, prompt: str, image_size: str):
        self.db.bild_aufrufe += 1
        await asyncio.sleep(0.01)                   # Rennfenster wie beim echten Aufruf
        if self.bild_fehler:
            raise self.bild_fehler
        if self.bild_leer:
            return None, {"prompt": 10, "image": 0, "thought": 0}
        return b"jpeg-bytes", {"prompt": 10, "image": 258, "thought": 0}

    bild_fehler: "BaseException | None" = None
    bild_leer = False

    # -- Helfer --
    def tarif_setzen(self, *, ki_limit, bild_limit):
        self.db.tarife["gratis"] = _tarif("gratis", ki_limit, bild_limit)

    def credits_setzen(self, n: int):
        self.db.konto()["bild_credits"] = n

    async def parallel(self, coro_factory, n: int = 10):
        """n Coroutines gleichzeitig starten; gibt (erfolge, limit_fehler, andere_fehler)."""
        async def _einzeln():
            try:
                await coro_factory()
                return "ok"
            except billing.LimitErreicht:
                return "limit"
            except Exception as e:                      # noqa: BLE001 – Testauswertung
                return f"fehler:{type(e).__name__}"
        ergebnisse = await asyncio.gather(*[_einzeln() for _ in range(n)])
        return (ergebnisse.count("ok"), ergebnisse.count("limit"),
                [e for e in ergebnisse if e not in ("ok", "limit")])


# ==================== 1) Nebenläufigkeit (Kernnachweis) ====================

class TestNebenlaeufigkeit(_Basis):
    async def test_10_parallele_chats_bei_einem_kontingentplatz(self):
        """Monatskontingent 1: von 10 parallelen Anfragen kommt genau eine durch."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        aufrufe = []

        async def _chat():
            resp = await billing.complete(self.client, "chat", messages=[])
            aufrufe.append(resp)

        ok, limit, andere = await self.parallel(_chat)
        self.assertEqual((ok, limit, andere), (1, 9, []))
        self.assertEqual(self.db.modell_aufrufe, 1)          # genau EIN bezahlter Aufruf
        self.assertEqual(len(aufrufe), 1)
        # Genau eine Nutzungszeile, keine hängende Reservierung.
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.ai_nutzung[0]["zweck"], "chat")
        self.assertEqual(self.db.reservierungen, [])

    async def test_10_parallele_bilder_bei_einem_credit(self):
        """Bild-Kontingent 0 + 1 Credit: von 10 parallelen Bildern kommt genau eines durch,
        der Credit ist danach auf 0 (nicht im Minus, nicht doppelt gezogen)."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        async def _bild():
            data = await bilder.generiere_rezeptbild("Kürbissuppe")
            if not data:
                raise AssertionError("Bild erwartet")

        ok, limit, andere = await self.parallel(_bild)
        self.assertEqual((ok, limit, andere), (1, 9, []))
        self.assertEqual(self.db.bild_aufrufe, 1)            # genau EIN Vertex-Aufruf
        self.assertEqual(self.db.konto()["bild_credits"], 0)  # genau ein Credit gezogen
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.ai_nutzung[0]["zweck"], "rezept-bild")
        self.assertEqual(self.db.reservierungen, [])

    async def test_credit_bild_zweitparalell_nicht_doppelt(self):
        """Zwei Credits, drei parallele Bilder → genau zwei kommen durch."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(2)

        async def _bild():
            await bilder.generiere_rezeptbild("Risotto")

        ok, limit, andere = await self.parallel(_bild, n=3)
        self.assertEqual((ok, limit, andere), (2, 1, []))
        self.assertEqual(self.db.bild_aufrufe, 2)
        self.assertEqual(self.db.konto()["bild_credits"], 0)

    async def test_laufende_reservierung_zaehlt_im_status(self):
        """Während der Modellaufruf läuft, zeigt der Kontingent-Status die Reservierung –
        Prüfung und Anzeige zählen dieselbe Belegung."""
        self.tarif_setzen(ki_limit=10, bild_limit=3)
        self.client.verzoegerung = 0.3
        task = asyncio.create_task(billing.complete(self.client, "chat", messages=[]))
        await _warte_bis(lambda: len(self.db.aktive_reservierungen()) == 1)

        status = await billing.kontingent_status_konto(ACC)
        self.assertEqual(status["monats_ki"], 1)
        self.assertEqual(status["ki_limit"], 10)
        self.assertEqual(len(self.db.ai_nutzung), 0)          # noch nicht abgeschlossen

        await task
        status = await billing.kontingent_status_konto(ACC)
        self.assertEqual(status["monats_ki"], 1)              # jetzt die echte Zeile
        self.assertEqual(self.db.reservierungen, [])


# ==================== 2) Erstattung bei Fehlschlag ====================

class TestErstattung(_Basis):
    async def test_timeout_erstattet_das_kontingent(self):
        """Modell-Timeout → Reservierung weg, kein Kontingent verbraucht, nächster
        Versuch kommt durch (try/finally, Auftrag Ziel 2)."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.client.fehler = asyncio.TimeoutError()
        with self.assertRaises(asyncio.TimeoutError):
            await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

        self.client.fehler = None
        await billing.complete(self.client, "chat", messages=[])   # Kontingent noch frei
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.reservierungen, [])

    async def test_exception_erstattet_das_kontingent(self):
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.client.fehler = RuntimeError("vertex 503")
        with self.assertRaises(RuntimeError):
            await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

    async def test_leere_antwort_ohne_usage_erstattet_kontingent(self):
        """Antwort ohne abrechenbare Tokens (usage=None) → kein Verbrauch (Erstattung)."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.client.leer = True
        self.client.usage = None
        resp = await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(getattr(resp.choices[0].message, "content", ""), "")
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

        self.client.leer = False
        self.client.usage = ...
        await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(len(self.db.ai_nutzung), 1)

    async def test_keine_choices_ohne_usage_erstattet_kontingent(self):
        """Modellantwort ohne Choices und ohne Usage → kein Verbrauch (Erstattung)."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.client.keine_choices = True
        self.client.usage = None
        resp = await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(resp.choices, [])
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

    async def test_b3_leere_antworten_umgehen_das_kontingent(self):
        """S7P-1: 20 Aufrufe mit leerer Antwort und abgerechneter Usage (> 0 Tokens)
        dürfen das Kontingent nicht umgehen. Bei Kontingent 3 sind genau 3 Aufrufe erlaubt;
        ab dem 4. Aufruf wird LimitErreicht geworfen und es entstehen genau 3 ai_nutzung-Zeilen."""
        self.tarif_setzen(ki_limit=3, bild_limit=0)
        self.client.leer = True  # content="", aber usage=120 Tokens

        erfolgreich = 0
        blockiert = 0
        for _ in range(20):
            try:
                await billing.complete(self.client, "chat", messages=[])
                erfolgreich += 1
            except billing.LimitErreicht:
                blockiert += 1

        self.assertEqual(erfolgreich, 3)
        self.assertEqual(blockiert, 17)
        self.assertEqual(len(self.db.ai_nutzung), 3)
        self.assertEqual(self.db.reservierungen, [])

    async def test_tool_calls_zaehlen_als_geliefert(self):
        """Eine Antwort NUR mit Tool-Calls ist verwertbar → sie zählt (kein Fehl-Refund)."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)

        async def _create(**kwargs):
            self.db.modell_aufrufe += 1
            return SimpleNamespace(
                model=kwargs.get("model"),
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content="", tool_calls=[SimpleNamespace(id="c1")]))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))

        alt = self.client.create
        self.client.create = _create
        try:
            await billing.complete(self.client, "chat", messages=[])
        finally:
            self.client.create = alt
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.reservierungen, [])

    async def test_bildfehler_erstattet_den_credit(self):
        """Bildgenerierung schlägt fehl → Credit zurück, keine Nutzungszeile."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)
        self.bild_fehler = RuntimeError("vertex 500")
        self.assertIsNone(await bilder.generiere_rezeptbild("Suppe"))
        self.assertEqual(self.db.konto()["bild_credits"], 1)
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

    async def test_bild_ohne_daten_erstattet_den_credit(self):
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)
        self.bild_leer = True
        self.assertIsNone(await bilder.generiere_rezeptbild("Suppe"))
        self.assertEqual(self.db.konto()["bild_credits"], 1)
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

    async def test_verarbeitungsfehler_erstattet_den_credit(self):
        """Bild kommt an, Resize scheitert → Credit zurück."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        def _kaputt(raw, max_px=768):
            raise ValueError("PIL-Fehler")

        bilder.quadrat_resize = _kaputt
        self.assertIsNone(await bilder.generiere_rezeptbild("Suppe"))
        self.assertEqual(self.db.konto()["bild_credits"], 1)
        self.assertEqual(self.db.reservierungen, [])
        self.assertEqual(self.db.ai_nutzung, [])

    async def test_bild_im_kontingent_zieht_keinen_credit(self):
        """Bild innerhalb des Monatskontingents: kein Credit, Reservierung art='bild'."""
        self.tarif_setzen(ki_limit=10, bild_limit=3)
        self.credits_setzen(5)
        data = await bilder.generiere_rezeptbild("Suppe")
        self.assertTrue(data.startswith("data:image/jpeg"))
        self.assertEqual(self.db.konto()["bild_credits"], 5)
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.reservierungen, [])


# ==================== 3) Crash-Schutz (Ablauf) ====================

class TestAblauf(_Basis):
    async def test_verfallene_credit_reservierung_gibt_den_credit_zurueck(self):
        """Absturz mitten im Aufruf: die verfallene Reservierung wird beim nächsten Gate
        gelöscht und der gezogene Credit zurückgebucht."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(0)
        self.db.reservierung_anlegen(billing.RES_BILD_CREDIT, minuten=-1)

        # Kontingent frei, aber Credit 0 → ohne Aufräumen blockiert.
        data = await bilder.generiere_rezeptbild("Suppe")
        self.assertTrue(data)
        self.assertEqual(self.db.konto()["bild_credits"], 0)   # zurückgebucht und neu gezogen
        self.assertEqual(len(self.db.aktive_reservierungen()), 0)

    async def test_verfallene_reservierung_blockiert_das_kontingent_nicht(self):
        """Eine verfallene KI-Reservierung belegt keinen Kontingentplatz mehr."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.db.reservierung_anlegen(billing.RES_KI, minuten=-5, zweck="chat")
        await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.reservierungen, [])           # verfallene Zeile weggeräumt

    async def test_fremde_reservierung_zaehlt_nicht(self):
        """RLS: Reservierungen eines anderen Kontos sind unsichtbar (kein Cross-Tenant-Effekt)."""
        self.tarif_setzen(ki_limit=1, bild_limit=3)
        self.db.accounts[99] = dict(self.db.konto(), id=99)
        self.db.naechste_id += 1
        self.db.reservierungen.append(
            {"id": self.db.naechste_id, "account_id": 99, "user_id": 1, "zweck": "chat",
             "art": "ki", "erstellt": _jetzt(), "ablauf": _jetzt() + timedelta(minutes=5)})
        await billing.complete(self.client, "chat", messages=[])   # eigenes Kontingent frei
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(len(self.db.reservierungen), 1)           # fremde Zeile unberührt

    async def test_b1_doppelte_credit_erstattung_nach_ablauf(self):
        """S7P-2a: Verfällt eine Bild-Credit-Reservierung vor dem Abschluss und wird
        vom Ablaufräumer geräumt (und dabei bereits erstattet), darf freigeben_v4() den
        Credit nicht ein zweites Mal erstatten. Genau 1 Credit zurück."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        # 1) Gate zieht den Credit und legt Reservierung mit art='bild_credit' an
        info = await billing.gate_v4(ACC, ist_bild=True, zweck="rezept-bild")
        self.assertTrue(info.get("credit_gezogen"))
        self.assertEqual(self.db.konto()["bild_credits"], 0)
        self.assertEqual(len(self.db.reservierungen), 1)

        # 2) Reservierung verfällt (simuliert > 10 min Laufzeit)
        self.db.reservierungen[0]["ablauf"] = _jetzt() - timedelta(minutes=1)

        # 3) Ablaufräumer räumt die verfallene Reservierung ab und erstattet den Credit
        async with billing.acquire() as con:
            await billing._verfallene_reservierungen_raeumen(con, ACC)
        self.assertEqual(self.db.konto()["bild_credits"], 1)  # Erstmalige Erstattung
        self.assertEqual(len(self.db.reservierungen), 0)

        # 4) Modellaufruf bricht ab / schlägt fehl -> freigeben_v4() wird aufgerufen
        await billing.freigeben_v4(ACC, info, "rezept-bild")
        # Idempotenz: Credit darf NICHT noch einmal gutgeschrieben werden!
        self.assertEqual(self.db.konto()["bild_credits"], 1)

        # Nochmaliger Aufruf (z. B. doppeltes finally / Fehlerbehandlung)
        await billing.freigeben_v4(ACC, info, "rezept-bild")
        self.assertEqual(self.db.konto()["bild_credits"], 1)

    async def test_b2_bild_gratis_wenn_reservierung_vorher_verfiel(self):
        """S7P-2b: Verfällt eine Bild-Credit-Reservierung während der Bildgenerierung
        (und wird vom Ablaufräumer geräumt + erstattet), darf das gelieferte Bild nicht
        gratis sein: record_bild_gemini() zieht den erstatteten Credit in derselben
        Transaktion erneut ab. Credit-Stand am Ende: 0."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        alt_generate = bilder._gemini_bild_generate

        async def _langsame_generierung(prompt, image_size):
            # Während die Generierung läuft, verfällt die Reservierung
            for z in self.db.reservierungen:
                z["ablauf"] = _jetzt() - timedelta(minutes=1)
            # Ein anderer Request / Gate räumt die verfallene Reservierung ab
            async with billing.acquire() as con:
                await billing._verfallene_reservierungen_raeumen(con, ACC)
            # Konto hat durch die Räumung den Credit vorübergehend zurückerhalten
            self.assertEqual(self.db.konto()["bild_credits"], 1)
            return b"fake-jpg-data", {"prompt": 10, "image": 100, "thought": 0}

        bilder._gemini_bild_generate = _langsame_generierung
        try:
            data = await bilder.generiere_rezeptbild("Festtagsbraten")
            self.assertIsNotNone(data)
            self.assertTrue(data.startswith("data:image/jpeg"))
        finally:
            bilder._gemini_bild_generate = alt_generate

        # Das Bild wurde geliefert
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.ai_nutzung[0]["zweck"], "rezept-bild")
        # Der Credit wurde bei Fertigstellung nachgezogen -> Credit-Stand 0 (nicht 1!)
        self.assertEqual(self.db.konto()["bild_credits"], 0)
        self.assertEqual(self.db.reservierungen, [])

    async def test_b2_bild_reservierung_verfiel_und_keine_credits_mehr(self):
        """S7P-2b: Wenn die Reservierung verfiel, der erstattete Credit anderweitig
        ausgegeben wurde und das Bild doch noch liefert, darf kein Fehler geworfen werden
        (WARNING im Log), das Bild wird geliefert und ai_nutzung erfasst."""
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        alt_generate = bilder._gemini_bild_generate

        async def _langsame_generierung(prompt, image_size):
            for z in self.db.reservierungen:
                z["ablauf"] = _jetzt() - timedelta(minutes=1)
            async with billing.acquire() as con:
                await billing._verfallene_reservierungen_raeumen(con, ACC)
            # Der erstattete Credit wird vor der Fertigstellung anderweitig verbraucht
            self.credits_setzen(0)
            return b"fake-jpg-data", {"prompt": 10, "image": 100, "thought": 0}

        bilder._gemini_bild_generate = _langsame_generierung
        try:
            with self.assertLogs("koch", level="WARNING") as cm:
                data = await bilder.generiere_rezeptbild("Festtagsbraten")
                self.assertIsNotNone(data)
                self.assertTrue(any("keine Bild-Credits mehr zum Nachbuchen" in m for m in cm.output))
        finally:
            bilder._gemini_bild_generate = alt_generate

        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.konto()["bild_credits"], 0)


# ==================== 4) Verhalten ohne Migration ====================

class TestOhneMigration(_Basis):
    async def test_gate_bleibt_verfuegbar_wenn_die_tabelle_fehlt(self):
        """Übergangs-Fallback: fehlt ki_reservierung (Migration nicht eingespielt), bleibt
        die KI verfügbar – das Gate prüft dann ohne Reservierung (Verhalten vor S-7) und
        meldet den Zustand als ERROR im Log."""
        self.db.reservierung_tabelle = False
        self.tarif_setzen(ki_limit=10, bild_limit=3)
        await billing.complete(self.client, "chat", messages=[])
        self.assertEqual(self.db.modell_aufrufe, 1)
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertIs(billing._reservierung_verfuegbar, False)

        self.credits_setzen(1)
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        data = await bilder.generiere_rezeptbild("Suppe")
        self.assertTrue(data)
        self.assertEqual(self.db.bild_aufrufe, 1)
        self.assertEqual(self.db.konto()["bild_credits"], 0)

    async def test_unbegrenzt_bilder_mit_einem_credit_ohne_migration(self):
        """S7P-9 (Pflicht): Fehlt die Tabelle ki_reservierung (Übergangs-Fallback), muss ein
        Konto mit monats_bild_limit=0 und 1 Credit genau EIN Bild erzeugen können, danach
        greift LimitErreicht und der Credit-Stand ist 0 (kein unbegrenztes Generieren)."""
        self.db.reservierung_tabelle = False
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        # 1. Bild: erfolgreich geliefert, Credit wird in record_bild_gemini atomar abgezogen
        data = await bilder.generiere_rezeptbild("Suppe 1")
        self.assertIsNotNone(data)
        self.assertEqual(self.db.bild_aufrufe, 1)
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.konto()["bild_credits"], 0)

        # 2. Bild: Kontingent 0 und 0 Credits -> LimitErreicht
        with self.assertRaises(billing.LimitErreicht):
            await bilder.generiere_rezeptbild("Suppe 2")

        # Keine weiteren Vertex-Aufrufe, keine neue ai_nutzung, Credit bleibt 0
        self.assertEqual(self.db.bild_aufrufe, 1)
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.konto()["bild_credits"], 0)

    async def test_normalpfad_mit_reservierung_zieht_weiterhin_genau_einen_credit(self):
        """S7P-9 Gegenprobe: Im Normalpfad mit aktiver Reservierungstabelle zieht der
        Bild-Credit weiterhin nur EINMAL (im Gate vorab) und wird in record_bild_gemini
        nicht doppelt abgezogen (elif credit_bild and not credit_gezogen greift nicht)."""
        self.db.reservierung_tabelle = True
        self.tarif_setzen(ki_limit=10, bild_limit=0)
        self.credits_setzen(1)

        data = await bilder.generiere_rezeptbild("Braten")
        self.assertIsNotNone(data)
        self.assertEqual(self.db.bild_aufrufe, 1)
        self.assertEqual(len(self.db.ai_nutzung), 1)
        self.assertEqual(self.db.konto()["bild_credits"], 0)
        self.assertEqual(self.db.reservierungen, [])

    async def test_anderer_db_fehler_bleibt_fail_closed(self):
        """F9: Ein echter DB-Fehler im Gate darf KEINEN Modellaufruf durchlassen."""
        self.tarif_setzen(ki_limit=10, bild_limit=3)

        async def _kaputt(sql, *args):
            raise RuntimeError("connection refused")

        alt = FakeCon.fetchrow
        FakeCon.fetchrow = _kaputt
        try:
            with self.assertRaises(billing.AbrechnungspruefungFehlgeschlagen):
                await billing.complete(self.client, "chat", messages=[])
        finally:
            FakeCon.fetchrow = alt
        self.assertEqual(self.db.modell_aufrufe, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
