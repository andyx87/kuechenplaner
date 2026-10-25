"""IT-Recht Kanzlei – Legal Text Interface (LTI).

Empfängt die per HTTP-POST (text/xml) gepushten Rechtstexte (Impressum, AGB,
Datenschutz, Widerruf), speichert sie in der Tabelle `rechtstext` und liefert die
von IT-Recht erwartete XML-Antwort zurück. Auth über ein gemeinsames Token
(ITRK_TOKEN), das im Mandantenportal hinterlegt wird.

Spezifikation: github.com/it-recht-kanzlei/itrk-plugin-sdk (LTI_XML_Specification).

Das gepushte HTML wird vor dem Speichern auf eine Tag-/Attribut-Whitelist reduziert
(`bereinige_html`, nh3) – Befund S-4 des Sicherheitsaudits 2026-09-11 (AND-22).
"""
import hmac
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from xml.parsers import expat

import nh3

from . import config, db

log = logging.getLogger("koch")

GUELTIGE_TYPEN = {"impressum", "agb", "datenschutz", "widerruf"}
SHOPVERSION = "1.0"
MODULVERSION = "1.0.0"

# S-6 (AND-22/AND-33): LTI-Pushes sind klein (Rechtstexte < 100 KB); harte
# Obergrenze gegen DoS über riesige Bodies / XML-Parsing.
MAX_BODY_BYTES = 256 * 1024


def content_length_ok(wert: str | None) -> bool:
    """Content-Length VOR dem Lesen des Bodys gegen MAX_BODY_BYTES prüfen (S-6).

    True = unauffällig (auch bei fehlendem/ungültigem Header – dann greift die
    Begrenzung beim Streaming-Lesen in body_lesen)."""
    if not wert:
        return True
    try:
        return int(wert) <= MAX_BODY_BYTES
    except ValueError:
        return True


async def body_lesen(stream) -> bytes | None:
    """Request-Stream mit harter Größengrenze lesen (S-6). None = Grenze
    überschritten (→ 413). Schützt auch bei fehlender oder falscher
    Content-Length (chunked encoding)."""
    teile = []
    gesamt = 0
    async for chunk in stream:
        gesamt += len(chunk)
        if gesamt > MAX_BODY_BYTES:
            return None
        teile.append(chunk)
    return b"".join(teile)


def token_ok(kandidat: str | None) -> bool:
    """Konstantzeit-Vergleich gegen ITRK_TOKEN (F11). Nicht-ASCII zählt als
    ungültig (S-6): hmac.compare_digest wirft bei Nicht-ASCII-Strings sonst
    TypeError → HTTP 500."""
    erwartet = config.ITRK_TOKEN or ""
    if not erwartet or not kandidat or not kandidat.isascii():
        return False
    return hmac.compare_digest(kandidat, erwartet)


class _DtdGefunden(Exception):
    """Abbruch-Marker für den DTD-Scan (nie nach außen sichtbar)."""


def dtd_gefunden(body: bytes) -> bool:
    """True, wenn der Body eine DTD/Entity-Deklaration enthält (S-6).

    Scan auf expat-Ebene statt als Byte-Suche: erkennt DOCTYPE/ENTITY in JEDEM
    von expat unterstützten Encoding (auch UTF-16/UTF-32, wo ein Byte-Muster
    versagt) und bricht beim ersten Fund ab, BEVOR irgendeine Entity expandiert
    wird („Billion Laughs" läuft also gar nicht erst an). Kaputtes XML zählt
    als unauffällig – ET.fromstring lehnt es anschließend ohnehin ab.
    """
    parser = expat.ParserCreate()

    def fund(*args):
        raise _DtdGefunden()

    parser.StartDoctypeDeclHandler = fund
    parser.EntityDeclHandler = fund
    parser.UnparsedEntityDeclHandler = fund
    parser.ExternalEntityRefHandler = fund
    try:
        parser.Parse(body, True)
    except _DtdGefunden:
        return True
    except expat.ExpatError:
        return False
    return False
# --- S-4 (Sicherheitsaudit 2026-09-11, AND-22): Rechtstext-HTML bereinigen -------------
# Die Rechtstexte kommen von außen (Push der IT-Recht Kanzlei auf /api/itrk) und werden im
# Frontend gerendert (`Rechtliches.jsx`, auch auf den öffentlichen Seiten /datenschutz,
# /impressum, /agb). Wer das ITRK_TOKEN erlangt oder das Kanzlei-Konto kompromittiert,
# könnte sonst beliebiges HTML/JavaScript auf der App-Domain ausliefern – und weil der
# Session-Token im localStorage liegt, führt ein einziger XSS-Pfad zur Kontoübernahme.
# Deshalb wird das HTML VOR dem Speichern auf eine Whitelist reduziert. Das Frontend
# bereinigt zusätzlich mit DOMPurify (Verteidigung in der Tiefe; deckt auch Texte ab, die
# vor diesem Fix gespeichert wurden).

# Erlaubte Tags = reiner Textaufbau eines Rechtstexts. Nicht erlaubte Tags werden entfernt,
# ihr Textinhalt bleibt erhalten; <script>/<style> verschwinden samt Inhalt.
ERLAUBTE_TAGS = {
    "p", "br",
    "h1", "h2", "h3", "h4",
    "ul", "ol", "li",
    "strong", "b", "em", "i",
    "a",
    "table", "caption", "colgroup", "col", "thead", "tbody", "tfoot", "tr", "td", "th",
}

# Erlaubte Attribute je Tag ("*" = alle erlaubten Tags). Bewusst KEINE Event-Handler (on*),
# kein `style` und kein `class`: darüber ließen sich Inhalt überdecken oder Skripte
# nachladen. `href` nur auf <a>, Schemata siehe ERLAUBTE_URL_SCHEMES.
ERLAUBTE_ATTRIBUTE = {
    "*": {"title"},
    "a": {"href"},
    "ol": {"start"},
    "col": {"span"},
    "colgroup": {"span"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
}

# Nur echte Link-Schemata. javascript:, data:, vbscript: & Co. verwirft nh3 (das Attribut
# fällt weg, der Linktext bleibt). `rel="noopener noreferrer"` schützt vor tabnabbing.
ERLAUBTE_URL_SCHEMES = {"http", "https", "mailto"}


def bereinige_html(html: str) -> str:
    """Externes HTML auf die Whitelist reduzieren (S-4). Leere Eingabe → leerer String."""
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=ERLAUBTE_TAGS,
        attributes=ERLAUBTE_ATTRIBUTE,
        url_schemes=ERLAUBTE_URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_META = f'<meta_shopversion>{SHOPVERSION}</meta_shopversion><meta_modulversion>{MODULVERSION}</meta_modulversion>'


def _wrap(inner: str) -> str:
    return f'{_HEAD}<response><status>success</status>{inner}</response>'


def _error(code: int, msg: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<response><status>error</status><error>{int(code)}</error>'
            f'<error_message>{_esc(msg)}</error_message></response>')


async def handle(body: bytes) -> str:
    """Verarbeitet einen LTI-Request und gibt die XML-Antwort (als String) zurück."""
    # S-6: DTD/Entity-Expansion („Billion Laughs") und externe Entities
    # ausschließen, bevor der Tree-Parser läuft – LTI-Pushes enthalten nie
    # eine DTD (s. dtd_gefunden: encoding-fest, Abbruch vor jeder Expansion).
    if dtd_gefunden(body):
        return _error(99, "XML konnte nicht gelesen werden")
    try:
        root = ET.fromstring(body)
    except Exception:
        return _error(99, "XML konnte nicht gelesen werden")

    def g(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    if g("api_version") not in ("", "1.0"):
        return _error(1, "Unbekannte API-Version")

    action = g("action")
    tok = g("user_auth_token")
    usr = g("user_username")
    pw = g("user_password")
    # F11: Kein Debug-Logging von Token-Präfix/Länge mehr (Secret-Hygiene) und
    # konstantzeit-Vergleich (hmac.compare_digest) gegen Timing-Angriffe.
    # S-6: token_ok() prüft zusätzlich ASCII – Nicht-ASCII im Token-Feld führte
    # früher zu TypeError in compare_digest (HTTP 500 statt Auth-Fehler).
    ok = token_ok(tok) or token_ok(pw)
    if not ok:
        log.info("itrk: Authentifizierung fehlgeschlagen (action=%s)", action)
        return _error(3, "Authentifizierung fehlgeschlagen")
    if action == "getversion":
        return _wrap(_META)
    if action == "getaccountlist":
        # Spec: KEIN <accounts>-Wrapper; Felder accountid/accountname (ohne Unterstrich).
        return _wrap("<account><accountid>0</accountid><accountname>Topfplan</accountname></account>")
    if action == "push":
        typ = g("rechtstext_type").lower()
        if typ not in GUELTIGE_TYPEN:
            return _error(4, "Ungültiger rechtstext_type")
        text = g("rechtstext_text")
        if not text:
            return _error(5, "rechtstext_text fehlt")
        html_enc = g("rechtstext_html")
        if not html_enc:
            return _error(6, "rechtstext_html fehlt")
        html_roh = urllib.parse.unquote_plus(html_enc)
        # S-4: bereinigen, BEVOR der Text in die DB und damit ins Frontend geht.
        html = bereinige_html(html_roh)
        if html != html_roh:
            # Keine Inhalte ins Log (nur Umfang) – reicht, um Manipulation zu erkennen.
            log.info("itrk: Rechtstext '%s' bereinigt (%d -> %d Zeichen)",
                     typ, len(html_roh), len(html))
        titel = g("rechtstext_title")
        sprache = g("rechtstext_language") or "de"
        land = g("rechtstext_country") or "DE"
        try:
            async with db.pool().acquire() as con:
                await con.execute(
                    """INSERT INTO rechtstext (typ, titel, html, text, sprache, land, aktualisiert)
                       VALUES ($1,$2,$3,$4,$5,$6, now())
                       ON CONFLICT (typ) DO UPDATE SET
                         titel=EXCLUDED.titel, html=EXCLUDED.html, text=EXCLUDED.text,
                         sprache=EXCLUDED.sprache, land=EXCLUDED.land, aktualisiert=now()""",
                    typ, titel, html, text, sprache, land)
        except Exception as e:  # noqa: BLE001
            log.warning("itrk: Speichern von '%s' fehlgeschlagen: %s", typ, e)
            return _error(50, "Rechtstext konnte nicht gespeichert werden")
        log.info("itrk: Rechtstext '%s' aktualisiert", typ)
        return _wrap(_META + f'<target_url>{_esc(config.APP_BASE_URL)}/</target_url>')

    return _error(99, "Unbekannte action")


async def get_rechtstext(typ: str) -> dict | None:
    async with db.pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT typ, titel, html, aktualisiert FROM rechtstext WHERE typ=$1", (typ or "").lower())
    return dict(r) if r else None


async def liste() -> list:
    async with db.pool().acquire() as con:
        rows = await con.fetch("SELECT typ, titel, aktualisiert FROM rechtstext ORDER BY typ")
    return [dict(r) for r in rows]
