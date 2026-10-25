"""Sprach-Transkription per Gemini (Vertex, nativer generateContent-Endpoint).

Der Browser nimmt Audio (meist webm/opus) auf; ffmpeg wandelt es in WAV 16 kHz
mono, das Gemini zuverlaessig versteht. Token werden ueber billing.record_usage
abgerechnet (Zweck 'spracheingabe'), die KI-Freigabe (darf_ki) ist Pflicht.
"""
from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import tempfile
import types

import httpx

from . import billing, config, gauth
from .userauth import current_account, current_user, darf_ki

_PROMPT = (
    "Transkribiere die folgende deutschsprachige Sprachaufnahme woertlich. "
    "Gib AUSSCHLIESSLICH den gesprochenen Text zurueck – ohne Anfuehrungszeichen, "
    "ohne Einleitung, ohne Erklaerung. Hoerst du nichts Verstaendliches, gib leeren Text zurueck."
)


def _zu_wav(audio: bytes) -> bytes:
    """Browser-Audio (webm/ogg/mp4 …) -> WAV 16 kHz mono via ffmpeg."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in")
        dst = os.path.join(d, "out.wav")
        with open(src, "wb") as f:
            f.write(audio)
        subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", dst],
            check=True, capture_output=True, timeout=60)
        with open(dst, "rb") as f:
            return f.read()


async def transkribiere(audio: bytes, mime: str | None = None) -> dict:
    """Wandelt die Audiobytes in Text. Liefert {'text': ...}."""
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")
    try:
        wav = await asyncio.to_thread(_zu_wav, audio)
        audio_mime, b64 = "audio/wav", base64.b64encode(wav).decode()
    except Exception:
        # ffmpeg fehlgeschlagen/fehlt -> Rohdaten weiterreichen (Gemini ist tolerant).
        audio_mime, b64 = (mime or "audio/webm"), base64.b64encode(audio).decode()

    model = await billing.modell_fuer_konto()       # z.B. "google/gemini-2.5-flash"
    short = model.split("/")[-1]
    url = f"{config.VERTEX_PREDICT_BASE}/publishers/google/models/{short}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": audio_mime, "data": b64}},
            {"text": _PROMPT},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    headers = {"Authorization": "Bearer " + gauth.get_token(), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as cx:
        r = await cx.post(url, json=body, headers=headers)
        r.raise_for_status()
    data = r.json() or {}

    text = ""
    cands = data.get("candidates") or []
    if cands:
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()

    um = data.get("usageMetadata") or {}
    pt = int(um.get("promptTokenCount", 0) or 0)
    ct = int(um.get("candidatesTokenCount", 0) or 0)
    tt = int(um.get("totalTokenCount", 0) or (pt + ct))
    shim = types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt),
        model=short)
    await billing.record_usage(shim, "spracheingabe", modell=model)
    return {"text": text}
