"""Einfaches In-Memory-Rate-Limiting (F6).

Sliding-Window-Zähler pro Schlüssel (z. B. IP oder E-Mail). Bewusst ohne externe
Abhängigkeit (kein Redis): der Zustand ist PRO PROZESS. Auf Cloud Run mit mehreren
Instanzen wirkt das Limit also je Instanz, nicht global – als Defense-in-Depth gegen
Brute-Force / Enumeration / Reset-Mail-Flooding trotzdem wertvoll. Für harte, global
konsistente Limits wäre ein gemeinsamer Store (Redis) nötig.

Speicherschutz (S4, AND-24/AND-33): Schlüssel aus Benutzereingaben (E-Mail) werden
gehasht und gekappt (email_schluessel), Buckets altern ohne Zugriff nach dem
längsten Fenster und die Gesamtzahl der Buckets ist gedeckelt – ein Angreifer kann
den Prozessspeicher nicht mit Einmalschlüsseln unbegrenzt wachsen lassen.
"""
from __future__ import annotations

import hashlib
import ipaddress
import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request

from . import config

_buckets: dict[str, deque] = {}
_letzter_zugriff: dict[str, float] = {}   # monotone-Zeit des letzten Zugriffs je Bucket
_lock = Lock()
_last_cleanup = 0.0

_CLEANUP_INTERVALL_S = 300      # Aufräum-Läufe höchstens alle 5 Minuten
_MAX_ALTER_S = 86_400           # längstes verwendetes Fenster (24 h): ohne Zugriff
                                # länger her sind alle Einträge logisch verfallen
_MAX_BUCKETS = 50_000           # harte Obergrenze gegen Speicherwachstum (S4); bei
                                # Überschreitung fliegen die am längsten ungenutzten raus


def _cleanup(now: float, erzwingen: bool = False) -> None:
    """Buckets entfernen: leere, zu alte (kein Zugriff seit _MAX_ALTER_S) und bei
    Bedarf die am längsten ungenutzten über der Obergrenze _MAX_BUCKETS (S4)."""
    global _last_cleanup
    if not erzwingen and now - _last_cleanup < _CLEANUP_INTERVALL_S:
        return  # höchstens alle 5 Minuten
    _last_cleanup = now
    for k in [k for k, dq in _buckets.items()
              if not dq or now - _letzter_zugriff.get(k, 0.0) > _MAX_ALTER_S]:
        _buckets.pop(k, None)
        _letzter_zugriff.pop(k, None)
    ueber = len(_buckets) - _MAX_BUCKETS
    if ueber > 0:
        for k in sorted(_buckets, key=lambda k: _letzter_zugriff.get(k, 0.0))[:ueber]:
            _buckets.pop(k, None)
            _letzter_zugriff.pop(k, None)


def treffer(key: str, limit: int, fenster_s: int) -> bool:
    """Registriert einen Versuch. True = noch erlaubt, False = Limit überschritten."""
    now = time.monotonic()
    with _lock:
        _cleanup(now)
        dq = _buckets.get(key)
        if dq is None:
            if len(_buckets) >= _MAX_BUCKETS:
                _cleanup(now, erzwingen=True)  # S4: Deckel gilt auch unter Flut
            dq = _buckets.setdefault(key, deque())
        grenze = now - fenster_s
        while dq and dq[0] < grenze:
            dq.popleft()
        _letzter_zugriff[key] = now
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


def pruefe(key: str, limit: int, fenster_s: int,
           meldung: str = "Zu viele Versuche. Bitte versuch es später noch einmal.") -> None:
    """Wie treffer(), wirft aber HTTP 429, wenn das Limit überschritten ist."""
    if not treffer(key, limit, fenster_s):
        raise HTTPException(status_code=429, detail=meldung)


def email_schluessel(email: str) -> str:
    """Rate-Limit-Schlüssel aus einer E-Mail-Adresse (S4, AND-24).

    Normalisieren (strip, lowercase), auf 254 Zeichen kappen (RFC-5321-Maximum)
    und sha256[:32] bilden. Verhindert unbegrenztes Speicherwachstum durch rohe,
    beliebig lange Eingaben als Bucket-Schlüssel und hält Klartext-Adressen aus
    dem Bucket-Store. Deterministisch: dieselbe Adresse liefert immer denselben
    Schlüssel, die Limits wirken unverändert.
    """
    norm = (email or "").strip().lower()[:254]
    # errors="replace": vereinzelte Surrogate aus JSON-Decodern dürfen nie 500 werfen
    return hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest()[:32]


def _ist_ip(wert: str) -> bool:
    try:
        ipaddress.ip_address(wert)
        return True
    except ValueError:
        return False


def client_ip(request: Request | None) -> str:
    """Echte Client-IP hinter Proxies (S-5, AND-22/AND-33).

    Reihenfolge:
    1. ``CF-Connecting-IP`` – von Cloudflare gesetzt und nur vertrauenswürdig,
       wenn die Anfrage erkennbar über Cloudflare lief (``CF-Ray`` vorhanden)
       und der Wert eine gültige IP ist.
    2. Der n-letzte Eintrag aus ``X-Forwarded-For``, n = ``TRUSTED_PROXY_HOPS``
       (Anzahl der Proxies, die verlässlich die Peer-IP anhängen; Produktion:
       Cloudflare + Google-Frontend = 2). Jeder Proxy hängt die IP an, von der
       er die Anfrage bekommen hat – die echten Client-IPs stehen also HINTEN.
       Alle früheren Einträge stammen vom Client und sind frei fälschbar; die
       ERSTE Adresse darf deshalb nie verwendet werden (alter Bug). Gibt es
       weniger Einträge als Hops, kann die Liste nur komplett von unseren
       eigenen Proxies stammen → der letzte Eintrag ist die echte Peer-IP.
       Ist der Kandidat keine gültige IP (Konfigurationsfehler), fällt die
       Antwort auf ``request.client.host`` zurück statt auf einen Angreiferwert.
    3. ``request.client.host`` – direkte Verbindung ohne Proxy-Header.

    Hinweis: Wird die Cloud-Run-Origin-URL direkt (ohne Cloudflare) erreicht,
    zählt ``TRUSTED_PROXY_HOPS`` die falsche Kette – XFF-Auswertung ist dann
    prinzipbedingt fälschbar. Abhilfe ist Infrastruktur-seitig (Origin nur für
    Cloudflare-IPs erreichbar), nicht im Code.
    """
    if request is None:
        return "unbekannt"
    headers = request.headers
    cf_ip = (headers.get("cf-connecting-ip") or "").strip()
    if cf_ip and (headers.get("cf-ray") or "").strip() and _ist_ip(cf_ip):
        return cf_ip
    xff = headers.get("x-forwarded-for")
    if xff:
        eintraege = [e.strip() for e in xff.split(",") if e.strip()]
        if eintraege:
            try:
                hops = max(1, int(getattr(config, "TRUSTED_PROXY_HOPS", 2)))
            except (TypeError, ValueError):
                hops = 2
            kandidat = eintraege[-hops] if len(eintraege) >= hops else eintraege[-1]
            if _ist_ip(kandidat):
                return kandidat
    return (request.client.host if request.client else None) or "unbekannt"
