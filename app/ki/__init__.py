"""Zentrale Stelle für alle Text-KI-Aufrufe (ohne Abrechnung/Kontingente).

`complete(zweck, **kwargs)` prüft die KI-Freigabe des Nutzers, wählt das Modell je
Zweck und führt die Chat-Completion aus.
"""
from __future__ import annotations

from openai import AsyncOpenAI

from .. import config, gauth
from ..userauth import current_account, current_user, darf_ki

_MODELL = {
    "schnell": "google/gemini-2.5-flash-lite",
    "standard": "google/gemini-2.5-flash",
}
_ZWECK_STUFE = {
    "angebote-import": config.ANGEBOTE_STUFE if config.ANGEBOTE_STUFE in _MODELL else "schnell",
    "spracheingabe": "schnell",
    "kategorisierung": "schnell",
}

_client: AsyncOpenAI | None = None


def _c() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=config.VERTEX_BASE_URL, api_key=gauth.get_token())
    else:
        _client.api_key = gauth.get_token()
    return _client


def modell_fuer_zweck(zweck: str | None) -> str:
    return _MODELL[_ZWECK_STUFE.get(zweck or "", "standard")]


async def complete(zweck: str, **kwargs):
    """Führt eine Chat-Completion für `zweck` aus und gibt das Completion-Objekt zurück."""
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")
    kwargs["model"] = modell_fuer_zweck(zweck)
    return await _c().chat.completions.create(**kwargs)
