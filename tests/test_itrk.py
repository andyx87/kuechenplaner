"""Unit-Tests für app/itrk.py – Härtung von /api/itrk (S-6, AND-22/AND-33).

Geprüft werden: Größenlimit (Content-Length vorab + Streaming-Grenze),
Token-Prüfung (ASCII-sicher, kein TypeError/HTTP 500 bei Nicht-ASCII) und die
Ablehnung von DTD/Entities vor dem XML-Parsen (Entity-Expansion-DoS).

Läuft ohne asyncpg/FastAPI: app.db wird vor dem Import durch einen Stub ersetzt
(dasselbe Vorgehen wie in tests/test_kontoloeschung.py).

Ausführung vom Repo-Root:
    python3 -m pytest tests/test_itrk.py -q
    python3 -m unittest tests.test_itrk -v
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------

if "app.db" not in sys.modules:
    db_stub = types.ModuleType("app.db")
    db_stub.pool = lambda: None
    sys.modules["app.db"] = db_stub

from app import config, itrk  # noqa: E402


class FakeStream:
    """Async-Iterator-Ersatz für request.stream() mit Zähler."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.gelesen = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.gelesen >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.gelesen]
        self.gelesen += 1
        return chunk


def _xml(action: str = "getversion", token: str = "", pw: str = "") -> bytes:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><request>"
            f"<action>{action}</action>"
            f"<user_auth_token>{token}</user_auth_token>"
            f"<user_password>{pw}</user_password>"
            "</request>").encode("utf-8")


class TestContentLength(unittest.TestCase):
    """S-6: Content-Length wird VOR dem Lesen gegen 256 KB geprüft."""

    def test_klein_und_grenzwert_ok(self):
        self.assertTrue(itrk.content_length_ok("0"))
        self.assertTrue(itrk.content_length_ok("1024"))
        self.assertTrue(itrk.content_length_ok(str(itrk.MAX_BODY_BYTES)))

    def test_ueber_grenze_abgelehnt(self):
        self.assertFalse(itrk.content_length_ok(str(itrk.MAX_BODY_BYTES + 1)))
        self.assertFalse(itrk.content_length_ok("999999999"))

    def test_fehlender_oder_unlesbarer_header_ist_ok(self):
        # Dann greift die harte Grenze beim Streaming-Lesen (body_lesen).
        self.assertTrue(itrk.content_length_ok(None))
        self.assertTrue(itrk.content_length_ok(""))
        self.assertTrue(itrk.content_length_ok("abc"))

    def test_grenze_ist_256_kb(self):
        self.assertEqual(itrk.MAX_BODY_BYTES, 256 * 1024)


class TestBodyLesen(unittest.IsolatedAsyncioTestCase):
    """S-6: harte Lesegrenze auch ohne/gegen falsche Content-Length (chunked)."""

    async def test_body_unter_grenze_wird_vollstaendig_gelesen(self):
        st = FakeStream([b"<request>", b"<action>getversion</action>", b"</request>"])
        body = await itrk.body_lesen(st)
        self.assertEqual(body, b"<request><action>getversion</action></request>")
        self.assertEqual(st.gelesen, 3)

    async def test_body_ueber_grenze_liefert_none(self):
        st = FakeStream([b"x" * (64 * 1024)] * 5)  # 320 KB > 256 KB
        self.assertIsNone(await itrk.body_lesen(st))

    async def test_lesen_stoppt_sofort_an_der_grenze(self):
        # Nicht erst den ganzen (Riesen-)Body puffern: nach Überschreiten der
        # Grenze darf kein weiterer Chunk mehr gelesen werden.
        st = FakeStream([b"x" * (64 * 1024)] * 100)  # 6,4 MB
        self.assertIsNone(await itrk.body_lesen(st))
        self.assertEqual(st.gelesen, 5)  # 4×64 KB ok, 5. Chunk → Grenze → Stopp

    async def test_exakt_an_der_grenze_ist_erlaubt(self):
        st = FakeStream([b"x" * (128 * 1024), b"y" * (128 * 1024)])
        body = await itrk.body_lesen(st)
        self.assertIsNotNone(body)
        self.assertEqual(len(body), itrk.MAX_BODY_BYTES)


class TestTokenOk(unittest.TestCase):
    """S-6: ASCII-Prüfung VOR hmac.compare_digest (sonst TypeError → 500)."""

    def setUp(self):
        self._token_save = config.ITRK_TOKEN
        config.ITRK_TOKEN = "geheim123"

    def tearDown(self):
        config.ITRK_TOKEN = self._token_save

    def test_richtiges_token_ok(self):
        self.assertTrue(itrk.token_ok("geheim123"))

    def test_falsches_token_abgelehnt(self):
        self.assertFalse(itrk.token_ok("falsch"))
        self.assertFalse(itrk.token_ok(""))
        self.assertFalse(itrk.token_ok(None))

    def test_nicht_ascii_zaehlt_als_ungueltig_statt_typeerror(self):
        # Vor dem Fix: hmac.compare_digest("geheimé", …) → TypeError → HTTP 500.
        self.assertFalse(itrk.token_ok("geheimé"))
        self.assertFalse(itrk.token_ok("🍕geheim"))

    def test_ohne_konfiguriertes_token_wird_alles_abgelehnt(self):
        config.ITRK_TOKEN = ""
        self.assertFalse(itrk.token_ok("geheim123"))


class TestHandleHärtung(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self._token_save = config.ITRK_TOKEN
        config.ITRK_TOKEN = "geheim123"

    def tearDown(self):
        config.ITRK_TOKEN = self._token_save

    async def test_nicht_ascii_token_im_body_ergibt_fehler3_statt_500(self):
        antwort = await itrk.handle(_xml(token="geheimé"))
        self.assertIn("<status>error</status>", antwort)
        self.assertIn("<error>3</error>", antwort)

    async def test_falsches_token_ergibt_fehler3(self):
        antwort = await itrk.handle(_xml(token="falsch"))
        self.assertIn("<error>3</error>", antwort)

    async def test_richtiges_token_getversion_erfolgreich(self):
        antwort = await itrk.handle(_xml(token="geheim123"))
        self.assertIn("<status>success</status>", antwort)
        self.assertIn("<meta_shopversion>", antwort)

    async def test_passwort_feld_wird_weiter_akzeptiert(self):
        antwort = await itrk.handle(_xml(pw="geheim123"))
        self.assertIn("<status>success</status>", antwort)

    async def test_dtd_und_entities_werden_vor_dem_parsen_abgelehnt(self):
        # „Billion Laughs"-Bombe: darf gar nicht erst in den Parser laufen.
        bombe = ('<?xml version="1.0"?>'
                 '<!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
                 '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                 '<r><action>getversion</action>'
                 '<user_auth_token>geheim123</user_auth_token></r>').encode("utf-8")
        antwort = await itrk.handle(bombe)
        self.assertIn("<status>error</status>", antwort)
        self.assertIn("<error>99</error>", antwort)

    async def test_utf16_bombe_umgeht_den_schutz_nicht(self):
        # Byte-Muster-Suche würde hier versagen (andere Kodierung) – der
        # expat-Scan erkennt die DTD encoding-unabhängig.
        bombe = ('<?xml version="1.0" encoding="UTF-16"?>'
                 '<!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
                 '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                 '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
                 '<r><x>&c;</x></r>').encode("utf-16")
        self.assertTrue(itrk.dtd_gefunden(bombe))
        antwort = await itrk.handle(bombe)
        self.assertIn("<error>99</error>", antwort)

    async def test_harmlose_pushes_werden_nicht_faelschlich_abgelehnt(self):
        harmlos = _xml(token="geheim123")
        self.assertFalse(itrk.dtd_gefunden(harmlos))
        antwort = await itrk.handle(harmlos)
        self.assertIn("<status>success</status>", antwort)

    async def test_kaputtes_xml_ergibt_fehler99(self):
        antwort = await itrk.handle(b"<request><action>")
        self.assertIn("<error>99</error>", antwort)


if __name__ == "__main__":
    unittest.main()
