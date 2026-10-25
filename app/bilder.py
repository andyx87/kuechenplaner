"""Rezeptbilder: 1:1-Zuschnitt/Resize + KI-Generierung.

Eigene Uploads werden serverseitig auf quadratisch + max 1024 px gerechnet und als
JPEG-Data-URL gespeichert (Spalte rezepte.bild).
"""
from __future__ import annotations

import base64
import io
import logging

from . import config, ki
from .userauth import current_account, current_user, darf_ki

log = logging.getLogger("koch")
MAX_PX = 1024


def bild_prompt(name: str, zutaten_namen: str | None = None) -> str:
    """EIN beschreibender Satz (kein \n, keine Anweisungen) -> verhindert gerenderten Text."""
    gericht = (name or "Gericht") + (f", with {zutaten_namen}" if zutaten_namen else "")
    return f"{gericht}. {config.KI_IMAGE_STYLE}."


def quadrat_resize(raw: bytes, max_px: int = 768) -> str:
    """Mittiger 1:1-Zuschnitt + Resize auf max_px; gibt eine JPEG-Data-URL zurück."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    elif im.mode == "L":
        im = im.convert("RGB")
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    im = im.crop((left, top, left + s, top + s))
    if s > max_px:
        im = im.resize((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def generiere_rezeptbild(name: str, beschreibung: str | None = None,
                               zutaten: list[dict] | None = None) -> str | None:
    """Erzeugt ein quadratisches Food-Foto über den Bild-Anbieter. Ambiente richtet sich nach der
    Küche (Stil-Prompt); Gericht + Zutaten gehen für ein korrektes Ergebnis mit in den
    Prompt. Gibt eine Data-URL zurück (oder None)."""
    # Harte Barriere: ohne KI-Freigabe kein Bild generieren.
    if not await darf_ki(current_user.get(), current_account.get()):
        return None
    zlist = ", ".join(
        (z.get("zutat") or z.get("name") or "").strip()
        for z in (zutaten or []) if (z.get("zutat") or z.get("name"))
    )[:400]
    prompt = bild_prompt(name, zlist)
    try:
        raw = await ki.bild_erzeugen(prompt)
    except ki.KiNichtKonfiguriert:
        raise
    except Exception as e:
        log.warning("Bildgenerierung fehlgeschlagen: %s", e)
        return None
    if not raw:
        return None
    try:
        return quadrat_resize(raw, max_px=1024)
    except Exception as e:
        log.warning("Bild konnte nicht verarbeitet werden: %s", e)
        return None
