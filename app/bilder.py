"""Rezeptbilder: 1:1-Zuschnitt/Resize + KI-Generierung.

Eigene Uploads werden serverseitig auf quadratisch + max 1024 px gerechnet und als
JPEG-Data-URL gespeichert (Spalte rezepte.bild).
"""
from __future__ import annotations

import base64
import io
import logging

from . import config, gauth
from .userauth import current_account, current_user, darf_ki

log = logging.getLogger("koch")
MAX_PX = 1024


async def _gemini_bild_generate(prompt: str, image_size: str) -> "tuple[bytes | None, dict]":
    """Erzeugt EIN quadratisches Bild über Vertex gemini-3.1-flash-image (generateContent).
    image_size: '512' oder '1K'. Gibt (Bildbytes|None, usage) zurück; usage = Tokenzahlen
    {prompt, image, thought} aus usageMetadata (für die tokenbasierte Abrechnung)."""
    import httpx
    url = f"{config.VERTEX_PREDICT_BASE}/publishers/google/models/{config.IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"imageSize": image_size, "aspectRatio": "1:1"},
        },
    }
    headers = {"Authorization": "Bearer " + gauth.get_token(),
               "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as cx:
        r = await cx.post(url, json=body, headers=headers)
    r.raise_for_status()
    d = r.json() or {}
    um = d.get("usageMetadata") or {}
    img_tok = next((x.get("tokenCount", 0) for x in (um.get("candidatesTokensDetails") or [])
                    if x.get("modality") == "IMAGE"), 0)
    usage = {"prompt": int(um.get("promptTokenCount") or 0),
             "image": int(img_tok or 0),
             "thought": int(um.get("thoughtsTokenCount") or 0)}
    for cand in (d.get("candidates") or []):
        for p in (cand.get("content") or {}).get("parts") or []:
            inline = p.get("inlineData") or p.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), usage
    return None, usage


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
    """Erzeugt ein quadratisches Food-Foto via Imagen. Ambiente richtet sich nach der
    Küche (Stil-Prompt); Gericht + Zutaten gehen für ein korrektes Ergebnis mit in den
    Prompt. Gibt eine Data-URL zurück (oder None)."""
    # Harte Barriere: ohne KI-Freigabe kein Bild generieren.
    if not await darf_ki(current_user.get(), current_account.get()):
        return None
    zlist = ", ".join(
        (z.get("zutat") or z.get("name") or "").strip()
        for z in (zutaten or []) if (z.get("zutat") or z.get("name"))
    )[:400]
    # EIN beschreibender Satz (kein \n, keine Anweisungen) -> verhindert gerenderten Text.
    gericht = name + (f", with {zlist}" if zlist else "")
    prompt = f"{gericht}. {config.IMAGE_STYLE}."
    try:
        raw, _usage = await _gemini_bild_generate(prompt, "1K")
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
