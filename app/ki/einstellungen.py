"""Auflösung der KI-Konfiguration (Instanz-Ebene, per Env) und Fähigkeiten-Status."""
from __future__ import annotations

from .. import config

FAEHIGKEITEN = ("text", "vision", "bild", "spracheingabe", "websuche")

# Zwecke mit Bildeingabe bzw. Prospekt-Import (eigene Modell-Slots).
_VISION_ZWECKE = {"foto-erkennung", "rezept-import-datei"}
_FLYER_ZWECKE = {"angebote-import"}


class KiNichtKonfiguriert(RuntimeError):
    """Die angefragte KI-Fähigkeit ist auf dieser Instanz nicht eingerichtet (HTTP 503)."""

    def __init__(self, faehigkeit: str = "text"):
        self.faehigkeit = faehigkeit
        super().__init__(f"KI-Funktion '{faehigkeit}' ist auf diesem Server nicht eingerichtet.")


def _aus(wert: str) -> bool:
    return wert.strip().lower() in ("aus", "off", "0", "false", "none", "-")


def text_konfiguriert() -> bool:
    return bool(config.KI_BASE_URL and config.KI_MODEL_DEFAULT)


def vision_modell() -> str | None:
    if not text_konfiguriert() or _aus(config.KI_MODEL_VISION or ""):
        return None
    return config.KI_MODEL_VISION or config.KI_MODEL_DEFAULT


def flyer_modell() -> str | None:
    if not text_konfiguriert():
        return None
    if config.KI_MODEL_FLYER and not _aus(config.KI_MODEL_FLYER):
        return config.KI_MODEL_FLYER
    return vision_modell()


def verfuegbar(faehigkeit: str = "text") -> bool:
    if faehigkeit == "text":
        return text_konfiguriert()
    if faehigkeit == "vision":
        return vision_modell() is not None
    if faehigkeit == "bild":
        return bool(config.KI_IMAGE_BASE_URL and config.KI_IMAGE_MODEL)
    if faehigkeit == "spracheingabe":
        return bool(config.KI_TRANSCRIBE_BASE_URL and config.KI_TRANSCRIBE_MODEL)
    if faehigkeit == "websuche":
        return bool(config.KI_WEBSUCHE_GEMINI_API_KEY)
    return False


def status() -> dict:
    """Welche KI-Fähigkeiten diese Instanz anbietet (für das Ein-/Ausblenden im Frontend).
    Enthält bewusst keine URLs, Modellnamen oder Schlüssel."""
    return {f: verfuegbar(f) for f in FAEHIGKEITEN}


def _hat_bild(messages) -> bool:
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c):
            return True
    return False


def modell_fuer_zweck(zweck: str | None, messages=None) -> str:
    """Modell je Zweck: Prospekt-Import -> KI_MODEL_FLYER, Bildeingaben -> KI_MODEL_VISION,
    sonst KI_MODEL_DEFAULT. Wirft KiNichtKonfiguriert, wenn der nötige Slot fehlt."""
    if not text_konfiguriert():
        raise KiNichtKonfiguriert("text")
    if zweck in _FLYER_ZWECKE:
        m = flyer_modell()
        if not m:
            raise KiNichtKonfiguriert("vision")
        return m
    if zweck in _VISION_ZWECKE or _hat_bild(messages):
        m = vision_modell()
        if not m:
            raise KiNichtKonfiguriert("vision")
        return m
    return config.KI_MODEL_DEFAULT
