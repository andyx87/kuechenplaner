"""Spracheingabe über eine OpenAI-kompatible Transkriptions-API
(POST {base}/audio/transcriptions, multipart; z. B. whisper-1)."""
from __future__ import annotations

import httpx

from .. import config
from .einstellungen import KiNichtKonfiguriert, verfuegbar

_ENDUNG = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3",
           "audio/wav": "wav", "audio/x-wav": "wav", "audio/m4a": "m4a", "audio/x-m4a": "m4a"}


async def transkribiere(audio: bytes, mime: str | None = None) -> str:
    if not verfuegbar("spracheingabe"):
        raise KiNichtKonfiguriert("spracheingabe")
    mt = (mime or "audio/webm").split(";")[0].strip().lower()
    dateiname = "aufnahme." + _ENDUNG.get(mt, "webm")
    headers = {}
    if config.KI_TRANSCRIBE_API_KEY:
        headers["Authorization"] = "Bearer " + config.KI_TRANSCRIBE_API_KEY
    async with httpx.AsyncClient(timeout=config.KI_TIMEOUT_S) as cx:
        r = await cx.post(
            f"{config.KI_TRANSCRIBE_BASE_URL}/audio/transcriptions",
            headers=headers,
            data={"model": config.KI_TRANSCRIBE_MODEL, "language": "de", "response_format": "json"},
            files={"file": (dateiname, audio, mt)},
        )
        r.raise_for_status()
    try:
        return str((r.json() or {}).get("text") or "").strip()
    except ValueError:
        return r.text.strip()
