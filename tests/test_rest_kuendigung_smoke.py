"""Smoke-Test für den öffentlichen Kündigungs-Endpunkt in app/rest.py (M-1/M-2, AND-96).

Hintergrund: Beim Zusammenführen der PR-Kette #47/#45 ging `import hashlib` in
`app/rest.py` verloren, während `auth_kuendigung` es weiter benutzte. Kein Test hatte
`app.rest` importiert oder den Endpunkt aufgerufen – die Suite blieb grün, in Produktion
wäre jeder `POST /api/auth/kuendigung` mit gültiger E-Mail ein HTTP 500 gewesen.

Der Test importiert das ECHTE `app.rest` (braucht FastAPI und die übrigen Laufzeit-
abhängigkeiten aus requirements.txt, keine DB, kein Netz) und ruft die Endpunktfunktion
direkt auf. Die fachliche Kündigungslogik (`kuendigung.annehmen`) wird gestubbt; geprüft
wird nur, dass der Routen-Code selbst fehlerfrei bis zum Service läuft und der E-Mail-
Rate-Limit-Key gehasht gebildet wird.

Isolation: Die übrigen Testdateien ersetzen `app.db`, `app.services`, `fastapi` … vor dem
Import durch Stubs und lassen Teile davon in `sys.modules` zurück. Damit `app.rest` trotzdem
gegen die echten Module läuft (und umgekehrt keine Stubs anderer Tests verdrängt), läuft
der eigentliche Aufruf in einem frischen Python-Unterprozess.

Ausführung vom Repo-Root (im venv mit `pip install -r requirements.txt`):
    python3 -m unittest tests.test_rest_kuendigung_smoke -v
"""
from __future__ import annotations

import importlib.machinery
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# PathFinder statt importlib.util.find_spec: Letzteres schaut zuerst in sys.modules und
# stolpert über den fastapi-Stub aus test_ratelimit.py (__spec__ is None).
_FASTAPI = importlib.machinery.PathFinder.find_spec("fastapi") is not None

# Läuft im Unterprozess: echtes app.rest, gestubbte Kündigungslogik, drei Aufrufe.
_KIND = r"""
import asyncio, json, sys, types
sys.path.insert(0, sys.argv[1])
from fastapi import BackgroundTasks
from app import ratelimit, rest

aufrufe = []
async def annehmen_stub(daten, ip=None, background=None):
    aufrufe.append({"daten": daten, "ip": ip})
    return {"ok": True}
rest.kuendigung.annehmen = annehmen_stub

def request(ip="203.0.113.7"):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=ip), headers={})

def post(body):
    ratelimit._buckets.clear()
    res = asyncio.run(rest.auth_kuendigung(body, request(), BackgroundTasks()))
    return {"res": res, "buckets": sorted(ratelimit._buckets)}

out = {
    "routen": len(rest.router.routes),
    "gueltig": post({"email": "Kunde@Example.org"}),
    "erwarteter_key": "kuendigung:email:" + ratelimit.email_schluessel("kunde@example.org"),
    "muell": post({"email": "x" * 300}),
    "aufrufe": aufrufe,
}
print(json.dumps(out))
"""


@unittest.skipUnless(_FASTAPI, "FastAPI fehlt – Smoke-Test braucht das venv mit requirements.txt")
class RestKuendigungSmokeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        p = subprocess.run([sys.executable, "-c", _KIND, str(REPO)], capture_output=True, text=True,
                           cwd=str(REPO), timeout=120)
        if p.returncode != 0:
            raise AssertionError("app.rest-Smoke im Unterprozess fehlgeschlagen:\n" + p.stderr[-4000:])
        cls.out = json.loads(p.stdout.strip().splitlines()[-1])

    def test_gueltige_email_erreicht_service_ohne_fehler(self):
        """M-1: Mit gültiger E-Mail darf kein NameError/500 entstehen (fehlender Import)."""
        self.assertEqual(self.out["gueltig"]["res"], {"ok": True})
        self.assertEqual(self.out["aufrufe"][0]["ip"], "203.0.113.7")
        self.assertGreater(self.out["routen"], 100)

    def test_email_rate_limit_key_wird_gehasht_gebildet(self):
        """K-2: Bucket je E-Mail entsteht gehasht (kein Klartext) über ratelimit.email_schluessel."""
        buckets = self.out["gueltig"]["buckets"]
        self.assertIn(self.out["erwarteter_key"], buckets)
        self.assertFalse(any("example.org" in k for k in buckets))

    def test_unformatige_email_erzeugt_keinen_bucket(self):
        """K-2: Müll-Eingaben ohne @ bekommen keinen E-Mail-Bucket, laufen aber neutral durch."""
        self.assertEqual(self.out["muell"]["res"], {"ok": True})
        self.assertFalse(any(k.startswith("kuendigung:email:") for k in self.out["muell"]["buckets"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
