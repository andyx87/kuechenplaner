"""Bildgenerierung über eine OpenAI-Images-kompatible API (POST {base}/images/generations).

Funktioniert z. B. mit OpenAI (gpt-image-1, dall-e-3), LiteLLM oder anderen kompatiblen
Proxys. Antwort als b64_json oder als URL (wird dann nachgeladen).
"""
from __future__ import annotations

import base64
import logging

import httpx

from .. import config
from .einstellungen import KiNichtKonfiguriert, verfuegbar

log = logging.getLogger("koch")
_MAX_BILD_BYTES = 20 * 1024 * 1024


async def bild_erzeugen(prompt: str) -> bytes | None:
    if not verfuegbar("bild"):
        raise KiNichtKonfiguriert("bild")
    headers = {"Content-Type": "application/json"}
    if config.KI_IMAGE_API_KEY:
        headers["Authorization"] = "Bearer " + config.KI_IMAGE_API_KEY
    body = {"model": config.KI_IMAGE_MODEL, "prompt": prompt, "n": 1, "size": config.KI_IMAGE_SIZE}
    async with httpx.AsyncClient(timeout=max(config.KI_TIMEOUT_S, 180.0)) as cx:
        r = await cx.post(f"{config.KI_IMAGE_BASE_URL}/images/generations", json=body, headers=headers)
        r.raise_for_status()
        daten = (r.json() or {}).get("data") or []
        if not daten:
            return None
        eintrag = daten[0] or {}
        if eintrag.get("b64_json"):
            return base64.b64decode(eintrag["b64_json"])
        url = eintrag.get("url")
        # Nur https-URLs nachladen, die der (vom Betreiber konfigurierte) Anbieter liefert.
        if url and url.startswith("https://"):
            r2 = await cx.get(url)
            r2.raise_for_status()
            if len(r2.content) > _MAX_BILD_BYTES:
                log.warning("Bildgenerierung: Antwort zu groß (%d Bytes)", len(r2.content))
                return None
            return r2.content
    return None
