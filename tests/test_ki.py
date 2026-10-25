"""Tests für die KI-Anbieter-Abstraktion (app/ki) – ohne Netz und ohne Datenbank."""
from __future__ import annotations

import base64
import sys
import unittest
from unittest import mock

import httpx
import openai

_vorher = set(sys.modules)
from app import config, ki  # noqa: E402
from app.ki import bild_openai, text_openai, transkription_openai  # noqa: E402

# Andere Testmodule ersetzen app.db/app.mailer usw. vor dem Import durch Stubs. Damit sie
# frische Module bekommen, die hier geladenen app.*-Module wieder aus sys.modules nehmen
# (die Referenzen oben bleiben gültig).
for _name in set(sys.modules) - _vorher:
    if _name == "app" or _name.startswith("app."):
        del sys.modules[_name]

_AsyncClient = httpx.AsyncClient

_LEER = dict(KI_BASE_URL="", KI_API_KEY="", KI_MODEL_DEFAULT="", KI_MODEL_VISION="",
             KI_MODEL_FLYER="", KI_IMAGE_BASE_URL="", KI_IMAGE_API_KEY="", KI_IMAGE_MODEL="",
             KI_TRANSCRIBE_BASE_URL="", KI_TRANSCRIBE_API_KEY="", KI_TRANSCRIBE_MODEL="",
             KI_WEBSUCHE_GEMINI_API_KEY="")


def _konfig(**werte):
    return mock.patch.multiple(config, **{**_LEER, **werte})


class StatusTests(unittest.TestCase):
    def test_ohne_konfiguration_alles_aus(self):
        with _konfig():
            self.assertEqual(ki.status(), {f: False for f in ki.FAEHIGKEITEN})
            with self.assertRaises(ki.KiNichtKonfiguriert):
                ki.modell_fuer_zweck("chat")

    def test_text_konfiguriert_vision_faellt_auf_default(self):
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m-default"):
            st = ki.status()
            self.assertTrue(st["text"])
            self.assertTrue(st["vision"])
            self.assertFalse(st["bild"])
            self.assertEqual(ki.modell_fuer_zweck("foto-erkennung"), "m-default")
            self.assertEqual(ki.modell_fuer_zweck("angebote-import"), "m-default")

    def test_modell_slots_je_zweck(self):
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m-default",
                     KI_MODEL_VISION="m-vision", KI_MODEL_FLYER="m-flyer"):
            self.assertEqual(ki.modell_fuer_zweck("chat"), "m-default")
            self.assertEqual(ki.modell_fuer_zweck("rezept-import-datei"), "m-vision")
            self.assertEqual(ki.modell_fuer_zweck("angebote-import"), "m-flyer")
            msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}]
            self.assertEqual(ki.modell_fuer_zweck("chat", msgs), "m-vision")

    def test_vision_aus(self):
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m", KI_MODEL_VISION="aus"):
            self.assertFalse(ki.verfuegbar("vision"))
            with self.assertRaises(ki.KiNichtKonfiguriert) as cm:
                ki.modell_fuer_zweck("foto-erkennung")
            self.assertEqual(cm.exception.faehigkeit, "vision")

    def test_status_enthaelt_keine_geheimnisse(self):
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_API_KEY="sk-geheim", KI_MODEL_DEFAULT="m"):
            self.assertNotIn("sk-geheim", repr(ki.status()))


class _FakeCompletions:
    def __init__(self, fehler_bei_response_format=False):
        self.aufrufe = []
        self.fehler = fehler_bei_response_format

    async def create(self, **kwargs):
        self.aufrufe.append(kwargs)
        if self.fehler and "response_format" in kwargs:
            req = httpx.Request("POST", "http://ki.example/v1/chat/completions")
            raise openai.BadRequestError("response_format nicht unterstützt",
                                         response=httpx.Response(400, request=req), body=None)
        return {"ok": True, "model": kwargs["model"]}


class TextTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, comp):
        return mock.patch.object(text_openai, "_c", lambda: mock.Mock(chat=mock.Mock(completions=comp)))

    async def test_modell_wird_gesetzt(self):
        comp = _FakeCompletions()
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m-default"), self._client(comp):
            res = await text_openai.complete("chat", model="ignoriert", messages=[])
        self.assertEqual(res["model"], "m-default")

    async def test_retry_ohne_response_format(self):
        comp = _FakeCompletions(fehler_bei_response_format=True)
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m"), self._client(comp):
            res = await text_openai.complete("rezept-link", messages=[], response_format={"type": "json_object"})
        self.assertTrue(res["ok"])
        self.assertEqual(len(comp.aufrufe), 2)
        self.assertNotIn("response_format", comp.aufrufe[1])

    async def test_ohne_freigabe_kein_aufruf(self):
        comp = _FakeCompletions()
        with _konfig(KI_BASE_URL="http://ki.example/v1", KI_MODEL_DEFAULT="m"), self._client(comp), \
                mock.patch.object(ki, "darf_ki", mock.AsyncMock(return_value=False)):
            with self.assertRaises(PermissionError):
                await ki.complete("chat", messages=[])
        self.assertEqual(comp.aufrufe, [])


class _FakeAsyncClient:
    """Ersetzt httpx.AsyncClient durch einen MockTransport-Client."""

    def __init__(self, handler):
        self.handler = handler

    def __call__(self, *a, **kw):
        return _AsyncClient(transport=httpx.MockTransport(self.handler))


class BildUndSpracheTests(unittest.IsolatedAsyncioTestCase):
    async def test_bild_ohne_konfiguration(self):
        with _konfig():
            with self.assertRaises(ki.KiNichtKonfiguriert):
                await bild_openai.bild_erzeugen("Suppe")

    async def test_bild_b64(self):
        gesehen = {}

        def handler(request):
            gesehen["url"] = str(request.url)
            gesehen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"PNG").decode()}]})

        with _konfig(KI_IMAGE_BASE_URL="http://bild.example/v1", KI_IMAGE_API_KEY="k", KI_IMAGE_MODEL="img"), \
                mock.patch.object(bild_openai.httpx, "AsyncClient", _FakeAsyncClient(handler)):
            self.assertEqual(await bild_openai.bild_erzeugen("Suppe"), b"PNG")
        self.assertEqual(gesehen["url"], "http://bild.example/v1/images/generations")
        self.assertEqual(gesehen["auth"], "Bearer k")

    async def test_transkription(self):
        def handler(request):
            self.assertIn(b"whisper-x", request.content)
            return httpx.Response(200, json={"text": " Hallo Welt "})

        with _konfig(KI_TRANSCRIBE_BASE_URL="http://stt.example/v1", KI_TRANSCRIBE_MODEL="whisper-x"), \
                mock.patch.object(transkription_openai.httpx, "AsyncClient", _FakeAsyncClient(handler)):
            self.assertEqual(await transkription_openai.transkribiere(b"abc", "audio/webm;codecs=opus"),
                             "Hallo Welt")


if __name__ == "__main__":
    unittest.main()
