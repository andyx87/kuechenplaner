"""Google-Cloud-Zugriffstoken fuer Vertex AI (Service-Account / ADC).

Liefert ein gueltiges OAuth-Access-Token fuer die Vertex-API. In der Cloud nutzt
`google.auth.default()` automatisch den Cloud-Run-Service-Account; lokal die
Application Default Credentials (`gcloud auth application-default login`).
Tokens laufen ~1 h; `get_token()` erneuert sie bei Bedarf (thread-safe).
"""
from __future__ import annotations

import threading

import google.auth
from google.auth.transport.requests import Request

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_creds = None
_lock = threading.Lock()


def get_token() -> str:
    global _creds
    with _lock:
        if _creds is None:
            _creds, _ = google.auth.default(scopes=_SCOPES)
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds.token
