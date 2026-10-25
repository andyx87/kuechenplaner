"""Unit-Tests für app/ratelimit.py – S-5 (client_ip hinter Proxies, AND-22/AND-33)
und S4 (Bucket-Store: Alterung + Deckel, gehashte E-Mail-Schlüssel, AND-24/AND-33).

Läuft ohne installiertes FastAPI: Das Modul wird vor dem Import durch einen Stub
ersetzt (dasselbe Vorgehen wie in tests/test_kontoloeschung.py).

Ausführung vom Repo-Root:
    python3 -m pytest tests/test_ratelimit.py -q
    python3 -m unittest tests.test_ratelimit -v
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import types
import unittest
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------- Stubs (VOR dem Import der app-Module registrieren) ----------

if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class HTTPException(Exception):  # Minimal-Ersatz für die Tests
        def __init__(self, status_code: int, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi_stub.HTTPException = HTTPException
    fastapi_stub.Request = object
    sys.modules["fastapi"] = fastapi_stub

from app import config, ratelimit  # noqa: E402


class FakeClient:
    def __init__(self, host: str):
        self.host = host


class FakeRequest:
    """Minimaler Request-Ersatz: Header-Dict (kleingeschriebene Schlüssel, wie
    Starlette case-insensitive zugreifbar) + optionaler Socket-Peer."""

    def __init__(self, headers: dict | None = None, client_host: str | None = None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = FakeClient(client_host) if client_host else None


class _Basis(unittest.TestCase):
    """Setzt Bucket-Store und TRUSTED_PROXY_HOPS je Test deterministisch zurück."""

    def setUp(self):
        self._buckets_save = dict(ratelimit._buckets)
        self._zugriff_save = dict(ratelimit._letzter_zugriff)
        self._cleanup_save = ratelimit._last_cleanup
        self._hops_save = config.TRUSTED_PROXY_HOPS
        ratelimit._buckets.clear()
        ratelimit._letzter_zugriff.clear()
        ratelimit._last_cleanup = 0.0

    def tearDown(self):
        ratelimit._buckets.clear()
        ratelimit._letzter_zugriff.clear()
        ratelimit._buckets.update(self._buckets_save)
        ratelimit._letzter_zugriff.update(self._zugriff_save)
        ratelimit._last_cleanup = self._cleanup_save
        config.TRUSTED_PROXY_HOPS = self._hops_save


class TestClientIpXffReihenfolge(_Basis):
    """S-5: die ERSTE X-Forwarded-For-Adresse ist Angreifer-Eingabe und tabu."""

    def test_request_none_ist_unbekannt(self):
        self.assertEqual(ratelimit.client_ip(None), "unbekannt")

    def test_ohne_header_zaehlt_der_socket_peer(self):
        req = FakeRequest(client_host="203.0.113.9")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.9")

    def test_xff_default_2_hops_nimmt_zweitletzte_adresse(self):
        # Kette Produktion: Client → Cloudflare (hängt echte IP an) → Google-
        # Frontend (hängt Cloudflare-IP an). Vorne steht Angreifer-Eingabe.
        config.TRUSTED_PROXY_HOPS = 2
        req = FakeRequest(
            {"X-Forwarded-For": "10.0.0.1, 198.51.100.7, 172.16.0.3"},
            client_host="127.0.0.1")
        ip = ratelimit.client_ip(req)
        self.assertEqual(ip, "198.51.100.7")
        self.assertNotEqual(ip, "10.0.0.1")  # erste (fälschbare) Adresse nie

    def test_xff_ein_hop_nimmt_letzte_adresse(self):
        config.TRUSTED_PROXY_HOPS = 1
        req = FakeRequest({"X-Forwarded-For": "10.0.0.1, 198.51.100.7, 203.0.113.3"},
                          client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.3")

    def test_xff_drei_hops(self):
        config.TRUSTED_PROXY_HOPS = 3
        req = FakeRequest(
            {"X-Forwarded-For": "10.9.9.9, 198.51.100.7, 172.16.0.3, 172.16.0.4"},
            client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.7")

    def test_weniger_eintraege_als_hops_nimmt_letzten(self):
        # Ein einzelner Eintrag kann nur vom eigenen Edge-Proxy angehängt worden
        # sein (Client-Eingaben würden die Liste verlängern) → vertrauenswürdig.
        config.TRUSTED_PROXY_HOPS = 2
        req = FakeRequest({"X-Forwarded-For": "203.0.113.5"}, client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.5")

    def test_ungueltiger_kandidat_faellt_auf_socket_peer_zurueck(self):
        config.TRUSTED_PROXY_HOPS = 2
        req = FakeRequest({"X-Forwarded-For": "10.0.0.1, böser-text, 172.16.0.3"},
                          client_host="203.0.113.2")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.2")

    def test_leerer_xff_faellt_auf_socket_peer_zurueck(self):
        req = FakeRequest({"X-Forwarded-For": " , "}, client_host="203.0.113.2")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.2")

    def test_ohne_alles_unbekannt(self):
        self.assertEqual(ratelimit.client_ip(FakeRequest()), "unbekannt")


class TestClientIpCloudflare(_Basis):

    def test_cf_connecting_ip_hat_vorrang(self):
        req = FakeRequest({
            "CF-Connecting-IP": "198.51.100.44",
            "CF-RAY": "8f12ab34c56de789-FRA",
            "X-Forwarded-For": "10.0.0.1, 198.51.100.44, 172.16.0.3",
        }, client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.44")

    def test_cf_header_ohne_ray_wird_ignoriert(self):
        # Ohne CF-Ray gilt die Anfrage nicht als „über Cloudflare" – der Header
        # könnte bei direktem Origin-Zugriff vom Angreifer gesetzt sein.
        config.TRUSTED_PROXY_HOPS = 2
        req = FakeRequest({
            "CF-Connecting-IP": "10.6.6.6",
            "X-Forwarded-For": "1.1.1.1, 198.51.100.7, 172.16.0.3",
        }, client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.7")

    def test_cf_ip_ungueltig_wird_ignoriert(self):
        config.TRUSTED_PROXY_HOPS = 2
        req = FakeRequest({
            "CF-Connecting-IP": "keine-ip",
            "CF-RAY": "8f12ab34c56de789-FRA",
            "X-Forwarded-For": "10.0.0.1, 203.0.113.9, 172.16.0.3",
        }, client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.9")

    def test_ipv6_wird_erkannt(self):
        req = FakeRequest({"CF-Connecting-IP": "2001:db8::1", "CF-RAY": "x-FRA"})
        self.assertEqual(ratelimit.client_ip(req), "2001:db8::1")


class TestClientIpEnvWert(_Basis):
    """TRUSTED_PROXY_HOPS kommt aus der Env (app/config.py)."""

    def _reload_config_mit_env(self, wert: str | None):
        alte = dict(os.environ)
        try:
            if wert is None:
                os.environ.pop("TRUSTED_PROXY_HOPS", None)
            else:
                os.environ["TRUSTED_PROXY_HOPS"] = wert
            importlib.reload(config)
            return config.TRUSTED_PROXY_HOPS
        finally:
            os.environ.clear()
            os.environ.update(alte)
            importlib.reload(config)

    def test_env_wert_3_wird_uebernommen(self):
        self.assertEqual(self._reload_config_mit_env("3"), 3)
        config.TRUSTED_PROXY_HOPS = 3
        req = FakeRequest({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3, 4.4.4.4"},
                          client_host="127.0.0.1")
        self.assertEqual(ratelimit.client_ip(req), "2.2.2.2")

    def test_default_ist_2_cloud_run_hinter_cloudflare(self):
        self.assertEqual(self._reload_config_mit_env(None), 2)

    def test_ungueltiger_env_wert_faellt_auf_default(self):
        self.assertEqual(self._reload_config_mit_env("abc"), 2)

    def test_env_wert_wird_auf_mindestens_1_geklemmt(self):
        self.assertEqual(self._reload_config_mit_env("0"), 1)
        self.assertEqual(self._reload_config_mit_env("-4"), 1)


class TestEmailSchluessel(_Basis):
    """S4: Schlüssel aus gekappter, kleingeschriebener, gehashter E-Mail."""

    def test_deterministisch_und_normalisiert(self):
        a = ratelimit.email_schluessel(" Kunde@Example.DE ")
        b = ratelimit.email_schluessel("kunde@example.de")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in a))

    def test_verschiedene_adressen_verschiedene_schluessel(self):
        self.assertNotEqual(ratelimit.email_schluessel("a@x.de"),
                            ratelimit.email_schluessel("b@x.de"))

    def test_ueberlange_eingabe_wird_auf_254_zeichen_gekappt(self):
        lang = "x" * 5000 + "@spam.example"
        self.assertEqual(ratelimit.email_schluessel(lang),
                         ratelimit.email_schluessel(lang[:254]))
        # Unterschiedliche Enden hinter Zeichen 254 ändern den Schlüssel nicht:
        self.assertEqual(ratelimit.email_schluessel("y" * 300 + "A"),
                         ratelimit.email_schluessel("y" * 300 + "B"))

    def test_rohe_adresse_taucht_nicht_im_schluessel_auf(self):
        s = ratelimit.email_schluessel("kunde@example.de")
        self.assertNotIn("kunde", s)
        self.assertNotIn("example", s)

    def test_leer_und_sonderzeichen_werfen_nicht(self):
        self.assertEqual(len(ratelimit.email_schluessel("")), 32)
        self.assertEqual(len(ratelimit.email_schluessel("\ud800@x.de")), 32)


class TestBucketStore(_Basis):
    """S4: Alterung nach letztem Zugriff + harter Deckel auf die Bucket-Zahl."""

    def test_limit_wird_durchgesetzt(self):
        for _ in range(3):
            self.assertTrue(ratelimit.treffer("login:ip:1.2.3.4", limit=3, fenster_s=60))
        self.assertFalse(ratelimit.treffer("login:ip:1.2.3.4", limit=3, fenster_s=60))

    def test_pruefe_wirft_429(self):
        for _ in range(2):
            ratelimit.pruefe("k", limit=2, fenster_s=60)
        with self.assertRaises(Exception) as ctx:
            ratelimit.pruefe("k", limit=2, fenster_s=60)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 429)

    def test_bucket_ohne_zugriff_altert_raus_obwohl_nicht_leer(self):
        # Kern des S4-Bugs: volles Deque, aber seit Ewigkeiten kein Zugriff –
        # früher unkonditional im Speicher geblieben.
        now = time.monotonic()
        ratelimit._buckets["alt"] = deque([now - 10.0, now - 5.0])
        ratelimit._letzter_zugriff["alt"] = now - ratelimit._MAX_ALTER_S - 1
        ratelimit._buckets["neu"] = deque([now - 1.0])
        ratelimit._letzter_zugriff["neu"] = now - 1.0
        ratelimit._cleanup(now, erzwingen=True)
        self.assertNotIn("alt", ratelimit._buckets)
        self.assertNotIn("alt", ratelimit._letzter_zugriff)
        self.assertIn("neu", ratelimit._buckets)

    def test_leerer_bucket_wird_entfernt(self):
        now = time.monotonic()
        ratelimit._buckets["leer"] = deque()
        ratelimit._letzter_zugriff["leer"] = now
        ratelimit._cleanup(now, erzwingen=True)
        self.assertNotIn("leer", ratelimit._buckets)

    def test_gesamtzahl_der_buckets_ist_gedeckelt(self):
        deckel_save = ratelimit._MAX_BUCKETS
        ratelimit._MAX_BUCKETS = 100
        self.addCleanup(setattr, ratelimit, "_MAX_BUCKETS", deckel_save)
        for i in range(1000):
            ratelimit.treffer(f"reset:email:{i:064x}", limit=3, fenster_s=3600)
        self.assertLessEqual(len(ratelimit._buckets), ratelimit._MAX_BUCKETS + 1)
        self.assertLessEqual(len(ratelimit._letzter_zugriff), ratelimit._MAX_BUCKETS + 1)
        # Der jüngste Schlüssel ist noch da und zählt korrekt weiter:
        self.assertTrue(ratelimit.treffer("reset:email:" + f"{999:064x}",
                                          limit=3, fenster_s=3600))
        self.assertTrue(ratelimit.treffer("reset:email:" + f"{999:064x}",
                                          limit=3, fenster_s=3600))
        self.assertFalse(ratelimit.treffer("reset:email:" + f"{999:064x}",
                                           limit=3, fenster_s=3600))


if __name__ == "__main__":
    unittest.main()
