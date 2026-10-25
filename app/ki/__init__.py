"""KI-Anbieter-Abstraktion ("bring your own key").

Alle KI-Aufrufe der App laufen über dieses Paket. Konfiguriert wird ausschließlich per
Umgebungsvariablen (s. app/config.py, Abschnitt "KI"). Ohne Konfiguration ist die KI aus:
`verfuegbar()` liefert False, die Web-App blendet die KI-Knöpfe aus und Aufrufe enden mit
`KiNichtKonfiguriert` (HTTP 503) statt mit einem Fehler beim Anbieter.

Öffentliche Schnittstelle:
  status()                       -> {"text", "vision", "bild", "spracheingabe", "websuche"}
  verfuegbar(faehigkeit)         -> bool
  complete(zweck, **kwargs)      -> Chat-Completion (OpenAI-kompatibel)
  bild_erzeugen(prompt)          -> Bildbytes | None
  transkribiere(audio, mime)     -> Text
"""
from __future__ import annotations

from ..userauth import current_account, current_user, darf_ki
from .bild_openai import bild_erzeugen as _bild_erzeugen
from .einstellungen import (FAEHIGKEITEN, KiNichtKonfiguriert, modell_fuer_zweck, status,
                            verfuegbar)
from .text_openai import complete as _complete
from .transkription_openai import transkribiere as _transkribiere

__all__ = ["FAEHIGKEITEN", "KiNichtKonfiguriert", "bild_erzeugen", "complete",
           "modell_fuer_zweck", "status", "transkribiere", "verfuegbar"]


async def _pruefe_freigabe() -> None:
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")


async def complete(zweck: str, **kwargs):
    """Chat-Completion für `zweck`. Das Modell wählt die Konfiguration (ein evtl.
    übergebenes `model` wird überschrieben)."""
    await _pruefe_freigabe()
    return await _complete(zweck, **kwargs)


async def bild_erzeugen(prompt: str) -> bytes | None:
    await _pruefe_freigabe()
    return await _bild_erzeugen(prompt)


async def transkribiere(audio: bytes, mime: str | None = None) -> str:
    await _pruefe_freigabe()
    return await _transkribiere(audio, mime)
