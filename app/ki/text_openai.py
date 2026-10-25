"""Text/Vision über eine OpenAI-kompatible Chat-Completions-API."""
from __future__ import annotations

import logging

import openai
from openai import AsyncOpenAI

from .. import config
from .einstellungen import modell_fuer_zweck

log = logging.getLogger("koch")

_client: AsyncOpenAI | None = None


def _c() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.KI_BASE_URL,
            # Lokale Anbieter (z. B. Ollama) brauchen keinen Schlüssel; der Client verlangt einen.
            api_key=config.KI_API_KEY or "kein-schluessel",
            timeout=config.KI_TIMEOUT_S,
        )
    return _client


async def complete(zweck: str, **kwargs):
    kwargs["model"] = modell_fuer_zweck(zweck, kwargs.get("messages"))
    try:
        return await _c().chat.completions.create(**kwargs)
    except openai.BadRequestError as e:
        # Nicht jeder Anbieter kennt response_format=json_object. Die Prompts verlangen JSON
        # ohnehin ausdrücklich und werden tolerant geparst -> einmal ohne erneut versuchen.
        if "response_format" in kwargs:
            log.info("KI (%s): Anbieter lehnt response_format ab, neuer Versuch ohne: %s", zweck, e)
            kwargs.pop("response_format", None)
            return await _c().chat.completions.create(**kwargs)
        raise
