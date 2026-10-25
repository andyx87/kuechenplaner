"""Rezept-Import aus einem Link – v.a. Instagram (Reels/Posts), generisch auch andere Seiten.

Instagram blockt direktes Scraping von Server-IPs, liefert aber mit Crawler-User-Agent
(Googlebot) die Seite inkl. der vollständigen Caption im eingebetteten JSON. Wir holen die
Caption und lassen die KI daraus ein strukturiertes Rezept extrahieren.

Steht das Rezept NICHT in der Caption (nur im Video gesprochen oder „Rezept im Blog / link
in bio"), meldet die Funktion das (status='kein_rezept'/'keine_caption'), damit das Frontend
sauber auf Screenshot-/Text-Eingabe ausweichen kann (der zuverlässigste Fallback).
"""
from __future__ import annotations

import base64
import html as _html
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urlsplit

from . import billing, chat, config, services
from .db import acquire
from .userauth import current_account, current_user, darf_ki

log = logging.getLogger("koch")

_IG_RE = re.compile(r"instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)
# Crawler-UA: Instagram serviert Bots die Seite samt Caption-JSON (kein Login-Wall).
_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
# Normale Rezept-Webseiten blocken oft Datacenter-Bots → echter Browser-UA.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def ist_instagram(url: str | None) -> bool:
    return bool(_IG_RE.search(url or ""))


# --- SSRF-Schutz für externe Fetches (Rezeptimport aus Link) ---
# Der Import lädt vom Nutzer angegebene URLs. Ohne Schutz könnte damit das Backend
# beliebige interne Ziele (localhost, VPC, Metadaten) abrufen. Wir erlauben nur http(s)
# auf öffentliche Adressen, prüfen JEDEN Redirect-Hop erneut und begrenzen die Antwort
# hart auf _MAX_FETCH_BYTES (Schutz vor OOM/DoS durch endlose Antworten).
_MAX_FETCH_BYTES = 3 * 1024 * 1024   # 3 MB Obergrenze pro Fetch
_MAX_REDIRECTS = 5


def _ist_privates_ziel(host: str) -> bool:
    """True, wenn der Host auf eine private/lokale/reservierte IP auflöst (oder gar nicht
    auflösbar ist). Blockt localhost, private Netze, link-local (169.254.*), Metadaten usw."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # nicht auflösbar → sicherheitshalber blocken
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
    return False


async def _sicher_get_text(url: str, ua: str, max_bytes: int = _MAX_FETCH_BYTES) -> str:
    """Holt eine externe URL mit SSRF-Schutz und Byte-Limit. Redirects werden manuell
    Hop für Hop validiert (DNS-Rebinding-Restrisiko besteht theoretisch, ist aber gering).
    Gibt den dekodierten Text zurück oder '' bei Fehler/Blockade."""
    import httpx
    ziel = (url or "").strip()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False,
                                     headers={"User-Agent": ua}) as cx:
            for _ in range(_MAX_REDIRECTS + 1):
                pu = urlsplit(ziel)
                if pu.scheme not in ("http", "https") or not pu.hostname:
                    return ""
                if _ist_privates_ziel(pu.hostname):
                    log.warning("fetch blockiert (privates/lokales Ziel): %s", pu.hostname)
                    return ""
                async with cx.stream("GET", ziel) as r:
                    if r.is_redirect:
                        loc = r.headers.get("location")
                        if not loc:
                            return ""
                        ziel = str(httpx.URL(ziel).join(loc))
                        continue
                    total, chunks = 0, []
                    async for chunk in r.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            log.warning("fetch abgebrochen: >%d Bytes von %s", max_bytes, pu.hostname)
                            break
                        chunks.append(chunk)
                    return b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
            log.warning("fetch abgebrochen: zu viele Redirects (%s)", url)
            return ""
    except Exception as e:
        log.warning("web fetch fehlgeschlagen: %s", e)
        return ""


async def _hole_instagram_caption(url: str) -> str:
    """Lädt die Instagram-Seite mit Crawler-UA und extrahiert die volle Caption."""
    m = _IG_RE.search(url or "")
    if not m:
        return ""
    sc = m.group(1)
    seite = f"https://www.instagram.com/reel/{sc}/"  # p/reel/tv – IG leitet passend um
    h = await _sicher_get_text(seite, _UA)
    if not h:
        return ""

    # og:description = gekürzte, aber sichere Caption (als Anker für die volle Version).
    mo = re.search(r'<meta property="og:description" content="([^"]*)"', h)
    og = _html.unescape(mo.group(1)) if mo else ""
    # Wrapper „N likes, M comments - user on DATE: \"…\"" entfernen.
    og_cap = re.sub(r"^.*? on [^:]*: ", "", og, flags=re.DOTALL).strip().strip('"').strip()
    anker = og_cap[:40]

    # Volle Caption aus dem eingebetteten JSON: das „text"-Feld, das den Anker enthält
    # (sonst bleibt die – evtl. gekürzte – og-Caption als Fallback).
    best = ""
    for mm in re.finditer(r'"text"\s*:\s*"((?:[^"\\]|\\.){20,})"', h):
        try:
            s = json.loads('"' + mm.group(1) + '"')
        except Exception:
            continue
        if anker and anker in s and len(s) > len(best):
            best = s
    return (best or og_cap).strip()


_PROMPT = (
    "Du bekommst Text aus einer Rezeptquelle (Social-Media-Caption, Webseite oder eingefügter "
    "Text). Extrahiere daraus EIN Kochrezept als JSON. Format:\n"
    '{"name": str, "beschreibung": str|null, "portionen": int (Standard 2), '
    '"dauer_minuten": int|null, "gang": str|null, "kueche": str|null, '
    '"zutaten": [{"name": str, "menge": number|null, "einheit": str|null}], '
    '"schritte": [str, ...]}\n'
    "Regeln: Zutaten als GENERISCHE Zutaten (keine Markennamen). Mengen auf die angegebenen "
    "Portionen beziehen. Emojis/Hashtags/Werbung/'link in bio' weglassen. Schritte als klare, "
    "knappe Anweisungen. Sei GROSSZÜGIG: Sobald Zutaten erkennbar sind, erstelle das Rezept und "
    "leite die Zubereitungsschritte aus allen vorhandenen Angaben ab (auch knappe wie Back-/"
    "Kochtemperatur und -zeit). Fehlen ausformulierte Schritte, formuliere selbst mindestens "
    "einen sinnvollen Zubereitungsschritt aus den Angaben. Gib {\"kein_rezept\": true} NUR "
    "zurück, wenn der Text praktisch keine Zutaten/Kochinformationen enthält (reine Ankündigung/"
    "Werbung oder Rezept ausdrücklich nur im Video/Blog). Antworte AUSSCHLIESSLICH mit JSON. "
    f"'gang' möglichst passend einer von: {', '.join(services.GANG_LISTE)} (sonst null)."
)


_URL_RE = re.compile(r"^https?://", re.I)


def _ist_url(s: str) -> bool:
    return bool(_URL_RE.match((s or "").strip()))


def _strip_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?is)<br\s*/?>", "\n", h)
    h = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = _html.unescape(h)
    h = re.sub(r"[ \t]+", " ", h)
    h = re.sub(r"\n\s*\n\s*\n+", "\n\n", h)
    return h.strip()


def _iter_jsonld(data):
    if isinstance(data, list):
        for x in data:
            yield from _iter_jsonld(x)
    elif isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            for x in data["@graph"]:
                yield from _iter_jsonld(x)
        yield data


def _jsonld_recipe(html_text: str) -> dict | None:
    """Findet ein schema.org/Recipe-Objekt im JSON-LD der Seite (die meisten Rezept-Webseiten)."""
    for mm in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text):
        try:
            data = json.loads(mm.group(1).strip())
        except Exception:
            continue
        for obj in _iter_jsonld(data):
            t = obj.get("@type")
            typen = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and x.lower() == "recipe" for x in typen):
                return obj
    return None


def _recipe_to_text(r: dict) -> str:
    teile = []
    if isinstance(r.get("name"), str):
        teile.append("Titel: " + r["name"].strip())
    yld = r.get("recipeYield")
    if yld:
        teile.append("Portionen: " + (", ".join(map(str, yld)) if isinstance(yld, list) else str(yld)))
    zut = r.get("recipeIngredient") or r.get("ingredients")
    if isinstance(zut, list):
        teile.append("Zutaten:\n" + "\n".join("- " + str(z).strip() for z in zut if z))

    def _step(x):
        if isinstance(x, str):
            return x.strip()
        if isinstance(x, dict):
            return str(x.get("text") or x.get("name") or "").strip() or None
        return None

    schritte = []
    instr = r.get("recipeInstructions")
    if isinstance(instr, list):
        for x in instr:
            if isinstance(x, dict) and x.get("@type") == "HowToSection":
                for st in (x.get("itemListElement") or []):
                    s = _step(st)
                    if s:
                        schritte.append(s)
            else:
                s = _step(x)
                if s:
                    schritte.append(s)
    elif isinstance(instr, str):
        schritte = [s.strip() for s in re.split(r"\n+", instr) if s.strip()]
    if schritte:
        teile.append("Zubereitung:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(schritte, 1)))
    return "\n\n".join(teile).strip()


async def _hole_web_text(url: str) -> str:
    """Lädt eine beliebige (Rezept-)Webseite und liefert sauberen Text: bevorzugt das
    schema.org/Recipe-JSON-LD, sonst og:description + bereinigter Seitentext.
    Fetch läuft SSRF-geschützt und mit Byte-Limit (siehe _sicher_get_text)."""
    h = await _sicher_get_text(url, _BROWSER_UA)
    if not h:
        return ""
    rec = _jsonld_recipe(h)
    if rec:
        t = _recipe_to_text(rec)
        if t and len(t) >= 40:
            return t
    mo = re.search(r'<meta property="og:description" content="([^"]*)"', h)
    og = _html.unescape(mo.group(1)) if mo else ""
    return ((og + "\n\n" + _strip_html(h)).strip())[:8000]


async def _pruefe_ki() -> None:
    """KI-Freigabe + Tarif-Limit wie in billing.complete prüfen (vor dem Modell-Aufruf)."""
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")
    acc = current_account.get() or 1
    try:
        async with acquire() as con:
            # v4: Gratis-Monatskontingent (wie billing.complete) statt PAYG/Guthaben.
            # Dieser Vorab-Check ist ein Text-KI-Zweck → ist_bild=False.
            if config.ABO_MODELL_V4:
                info = await billing.limit_pruefen_v4(con, acc, ist_bild=False)
            else:
                info = await billing.limit_pruefen(con, acc)
        if info and info.get("blockiert"):
            raise billing.LimitErreicht(info)
    except billing.LimitErreicht:
        raise
    except Exception as e:
        # F9: Fail-closed – ohne gültige Prüfung keinen kostenpflichtigen Import durchlassen.
        log.warning("limit_pruefen (rezept-import) fehlgeschlagen: %s", e)
        raise billing.AbrechnungspruefungFehlgeschlagen() from e


def _parse_json(resp) -> dict:
    txt = (resp.choices[0].message.content or "").strip()
    try:
        return json.loads(txt)
    except Exception:
        i, j = txt.find("{"), txt.rfind("}")
        try:
            return json.loads(txt[i:j + 1]) if 0 <= i < j else {}
        except Exception:
            return {}


async def _verarbeite(data: dict, quelle: str, fallback_text: str | None,
                      reflekt_text: bool = False) -> dict:
    """Aus dem KI-JSON ein Rezept anlegen – oder kein_rezept zurückgeben.
    `reflekt_text` nur True, wenn `fallback_text` vom Nutzer SELBST stammt (eingefügter
    Text). Gefetchter Web-/Social-Inhalt wird NIE an den Aufrufer zurückgegeben, sonst
    wäre der Import ein SSRF-Read-Kanal (siehe Sicherheits-Review F1)."""
    if not isinstance(data, dict) or data.get("kein_rezept") or not (data.get("name") or "").strip():
        return {"status": "kein_rezept", "text": ((fallback_text or "")[:4000] if reflekt_text else ""),
                "meldung": "Darin konnte ich kein vollständiges Rezept erkennen. Versuch einen "
                           "klareren Screenshot, ein anderes Foto/PDF oder füge den Rezepttext ein."}
    schritte = [s for s in (data.get("schritte") or []) if isinstance(s, str) and s.strip()]
    zubereitung = [{"titel": f"Schritt {i}", "varianten": [{"geraet": None, "text": s.strip()}]}
                   for i, s in enumerate(schritte, 1)]
    zutaten = [{"name": (z.get("name") or "").strip(),
                "menge": z.get("menge"), "einheit": z.get("einheit")}
               for z in (data.get("zutaten") or [])
               if isinstance(z, dict) and (z.get("name") or "").strip()]
    neu = await services.add_rezept(
        name=data["name"].strip(),
        beschreibung=(data.get("beschreibung") or None),
        anleitung=("\n".join(schritte) or None),
        portionen=int(data.get("portionen") or 2),
        dauer_minuten=(int(data["dauer_minuten"]) if data.get("dauer_minuten") else None),
        quelle=quelle,
        zutaten=zutaten,
        geraete=[],
        zubereitung=zubereitung,
        gang=(data.get("gang") or None),
        kueche=(data.get("kueche") or None),
    )
    # Als 'importiert' markieren: Inhalte aus fremden Quellen (Webseite, Social Media,
    # abfotografiertes Buch, eingefügter Text) dürfen NICHT veröffentlicht werden –
    # die Quelle kann urheberrechtlich geschützt sein. Die Sperre sitzt zentral in
    # services.set_veroeffentlicht; privat in der eigenen Bibliothek bleibt alles nutzbar.
    if isinstance(neu, dict) and neu.get("id"):
        try:
            async with acquire() as con:
                await con.execute("UPDATE rezepte SET importiert = true WHERE id = $1",
                                  int(neu["id"]))
            neu["importiert"] = True
        except Exception:
            log.exception("rezept_link: importiert-Flag setzen fehlgeschlagen")
    return {"status": "ok", "rezept": neu}


def _pdf_seiten_zu_urls(b64_pdf: str, max_seiten: int = 10) -> list[str]:
    """Rendert die ersten PDF-Seiten zu PNG-Data-URLs (auf ≤1600 px herunterskaliert)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    try:
        doc = fitz.open(stream=base64.b64decode(b64_pdf), filetype="pdf")
    except Exception:
        return []
    urls: list[str] = []
    try:
        for page in list(doc)[:max_seiten]:
            r = page.rect
            zoom = min(1600.0 / max(r.width, r.height, 1), 2.0)
            png = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
            urls.append("data:image/png;base64," + base64.b64encode(png).decode())
    except Exception:
        return urls
    finally:
        doc.close()
    return urls


async def importiere_aus_link(url: str) -> dict:
    """Importiert ein Rezept aus einer beliebigen Quelle: Instagram-Link, Rezept-Webseite
    (Link) oder eingefügtem Rezepttext. Gibt {status:'ok', rezept:{...}} oder
    {status:'kein_rezept'|'keine_caption'|'nicht_unterstuetzt', ...} zurück.
    Wirft PermissionError/billing.LimitErreicht wie die übrigen KI-Wege."""
    eingabe = (url or "").strip()
    if not eingabe:
        return {"status": "nicht_unterstuetzt", "meldung": "Bitte einen Link oder Rezepttext eingeben."}
    await _pruefe_ki()

    # Quelltext je nach Eingabe gewinnen.
    ist_link = _ist_url(eingabe)
    quelle = eingabe if ist_link else "Eingefügter Text"
    if ist_link and ist_instagram(eingabe):
        quelltext = await _hole_instagram_caption(eingabe)
    elif ist_link:
        quelltext = await _hole_web_text(eingabe)
    else:
        quelltext = eingabe  # direkt eingefügter Rezepttext

    if not quelltext or len(quelltext) < 40:
        return {"status": "keine_caption",
                "meldung": "Aus dieser Quelle konnte ich kein Rezept lesen. Bei Social-Media-Links "
                           "steht das Rezept evtl. nur im Video – häng dann einen Screenshot/ein PDF "
                           "an. Bei Webseiten kannst du auch den Rezepttext direkt einfügen."}

    resp = await billing.complete(
        chat._c(), "rezept-link",
        model=await billing.modell_fuer_konto(),
        messages=[{"role": "system", "content": _PROMPT},
                  {"role": "user", "content": quelltext[:12000]}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    # Nur direkt eingefügten Text zurückspiegeln – gefetchte URLs nicht (SSRF-Read, F1).
    return await _verarbeite(_parse_json(resp), quelle, quelltext, reflekt_text=not ist_link)


async def importiere_aus_dateien(dateien: list[dict]) -> dict:
    """Importiert ein Rezept aus hochgeladenen Dateien: Screenshots/Fotos und/oder PDFs.
    `dateien`: [{data: base64, media_type, filename}]. Mehrere Seiten/Bilder werden zusammen
    ausgewertet. Gibt {status:'ok'|'kein_rezept'|'keine_caption'|'nicht_unterstuetzt', ...}."""
    if not dateien:
        return {"status": "nicht_unterstuetzt", "meldung": "Keine Datei übergeben."}
    await _pruefe_ki()

    bild_urls: list[str] = []
    for d in dateien:
        data = d.get("data")
        if not data:
            continue
        mt = (d.get("media_type") or "").lower()
        name = (d.get("filename") or "").lower()
        if mt == "application/pdf" or name.endswith(".pdf"):
            bild_urls += _pdf_seiten_zu_urls(data)
        else:
            bild_urls.append(f"data:{mt or 'image/jpeg'};base64,{data}")
    bild_urls = bild_urls[:12]  # Seiten/Bilder deckeln (Token/Größe)
    if not bild_urls:
        return {"status": "keine_caption", "meldung": "Die Datei(en) konnten nicht gelesen werden."}

    content = [{"type": "text", "text": "Lies das Rezept aus diesen Bildern/Seiten. Gib NUR das JSON aus."}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in bild_urls]
    resp = await billing.complete(
        chat._c(), "rezept-import-datei",
        model=await billing.modell_fuer_konto(),
        messages=[{"role": "system", "content": _PROMPT},
                  {"role": "user", "content": content}],
        temperature=0.1,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )
    return await _verarbeite(_parse_json(resp), "Foto-/PDF-Import", None)
