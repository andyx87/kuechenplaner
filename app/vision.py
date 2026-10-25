"""Erkennt Lebensmittel bzw. Kuechengeraete auf einem Foto ueber den KI-Anbieter.

Gibt eine Vorschlagsliste zurueck. Der Eintrag in den Vorrat erfolgt erst
nach Bestaetigung in der Web-App (Review-Schritt).
"""
from __future__ import annotations

import json

from . import ki



_SYSTEM = (
    "Du erkennst Lebensmittel auf einem Foto fuer eine Vorratsverwaltung. "
    "Antworte AUSSCHLIESSLICH mit validem JSON, ohne Erklaerung, ohne Markdown. "
    'Schema: {"items":[{"name":string,"menge":number|null,"einheit":string|null,'
    '"kategorie":string|null}]}. '
    "Schaetze Menge und Einheit grob (z.B. Stueck, g, ml). Verwende deutsche Namen."
)


async def foto_zu_items(image_b64: str, media_type: str) -> list[dict]:
    resp = await ki.complete(
        "foto-erkennung", max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Welche Lebensmittel sind hier? Antworte nur mit JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                ],
            },
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data.get("items", []) if isinstance(data, dict) else []


_SYSTEM_GERAETE = (
    "Du erkennst Kuechengeraete auf einem Foto fuer eine Geraeteverwaltung. "
    "Antworte AUSSCHLIESSLICH mit validem JSON, ohne Erklaerung, ohne Markdown. "
    'Schema: {"geraete":[{"name":string,"typ":string|null}]}. '
    "name = gebraeuchlicher deutscher Geraetename (z.B. 'Backofen', 'Mikrowelle', 'Thermomix', "
    "'Heissluftfritteuse', 'Induktionskochfeld', 'Standmixer', 'Toaster'). typ = grobe Kategorie "
    "('Ofen','Herd','Kleingeraet') oder null. Nur tatsaechlich erkennbare Kuechengeraete - "
    "kein Geschirr, keine Deko, keine Lebensmittel."
)


async def foto_zu_geraeten(image_b64: str, media_type: str) -> list[dict]:
    resp = await ki.complete(
        "foto-erkennung", max_tokens=512,
        messages=[
            {"role": "system", "content": _SYSTEM_GERAETE},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Welche Kuechengeraete sind hier? Antworte nur mit JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                ],
            },
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data.get("geraete", []) if isinstance(data, dict) else []
