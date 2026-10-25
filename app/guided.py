"""Guided Cooking: KI-strukturierte Schritt-für-Schritt-Anleitung eines Rezepts.

Die Zubereitung liegt als Freitext je Komponente/Geräte-Variante vor. Hier wird sie per
KI in einzelne Schritte zerlegt (Text, Timer-Dauer, Geräte, Zutaten je Schritt) und am
Rezept gecacht – getrennt je gewählter Varianten-Kombination (Signatur). Mengen bleiben
in BASIS-Portionen; das Frontend skaliert auf die Zielportionen.
"""
from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from . import billing, config, gauth, services
from .db import acquire

_client: AsyncOpenAI | None = None


def _c() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=config.VERTEX_BASE_URL, api_key=gauth.get_token())
    else:
        _client.api_key = gauth.get_token()
    return _client


_SYS = (
    "Du wandelst ein Rezept in eine Schritt-für-Schritt-Kochanleitung um. Antworte "
    "AUSSCHLIESSLICH mit validem JSON, ohne Erklärung, ohne Markdown. Schema: "
    '{"schritte":[{"nr":int,"komponente":string|null,"text":string,'
    '"dauer_minuten":int|null,"timer":boolean,"geraete":[string],'
    '"zutaten":[{"name":string,"menge":number|null,"einheit":string|null}]}]}. '
    "Zerlege die Zubereitung in einzelne, klar umsetzbare Schritte (eine Haupthandlung "
    "pro Schritt), in sinnvoller Reihenfolge über alle Komponenten. nr fortlaufend ab 1. "
    "komponente = Titel der zugehörigen Komponente (oder null). "
    "Wenn ein Schritt eine Warte-/Garzeit enthält (z.B. '15 Min köcheln', 'Ofen 25 Min'), "
    "setze dauer_minuten auf die Minuten und timer=true; sonst dauer_minuten=null, timer=false. "
    "geraete = im Schritt genutzte Küchengeräte (aus der Variante/Beschreibung), sonst []. "
    "zutaten = die in DIESEM Schritt verwendeten Zutaten mit Menge+Einheit, übernommen aus "
    "der Zutatenliste des Rezepts (Mengen in den angegebenen Basis-Portionen, nichts erfinden; "
    "wenn unklar, menge=null). Deutsche Sprache. Keine zusätzlichen Felder."
)


def _parse(text: str) -> list[dict]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = None
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            try:
                data = json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        schritte = data.get("schritte")
    elif isinstance(data, list):
        schritte = data
    else:
        schritte = None
    out: list[dict] = []
    for n, s in enumerate(schritte or [], 1):
        if not isinstance(s, dict) or not (s.get("text") or "").strip():
            continue
        zut = []
        for z in (s.get("zutaten") or []):
            if isinstance(z, dict) and (z.get("name") or "").strip():
                zut.append({"name": str(z["name"]).strip(),
                            "menge": z.get("menge"),
                            "einheit": z.get("einheit")})
        dm = s.get("dauer_minuten")
        try:
            dm = int(dm) if dm is not None else None
        except (TypeError, ValueError):
            dm = None
        out.append({
            "nr": n,
            "komponente": (s.get("komponente") or None),
            "text": str(s["text"]).strip(),
            "dauer_minuten": dm,
            "timer": bool(s.get("timer")) and dm is not None,
            "geraete": [str(g) for g in (s.get("geraete") or []) if str(g).strip()],
            "zutaten": zut,
        })
    return out


def _aktive_varianten(rezept: dict, varianten: list[int] | None) -> tuple[str, list[dict]]:
    """Wählt je Komponente die aktive Variante (Index aus `varianten`, sonst 0) und liefert
    (Signatur, [{titel, geraet, text}])."""
    komp = rezept.get("zubereitung") or []
    sig_teile: list[str] = []
    aktiv: list[dict] = []
    for i, k in enumerate(komp):
        vs = k.get("varianten") or []
        idx = 0
        if varianten and i < len(varianten):
            try:
                idx = int(varianten[i])
            except (TypeError, ValueError):
                idx = 0
        if idx < 0 or idx >= len(vs):
            idx = 0
        v = vs[idx] if vs else {}
        sig_teile.append(f"{i}:{idx}")
        aktiv.append({"titel": k.get("titel"), "geraet": v.get("geraet"),
                      "text": (v.get("text") or "").replace("\\n", "\n")})
    sig = "|".join(sig_teile) or "std"
    return sig, aktiv


async def strukturiere(rezept: dict, varianten: list[int] | None) -> list[dict]:
    """Ruft die KI, um die aktive Varianten-Zubereitung in Schritte zu zerlegen."""
    sig, aktiv = _aktive_varianten(rezept, varianten)
    basis = rezept.get("portionen") or 4
    zlist = "\n".join(
        f"- {(z.get('zutat') or '').strip()}: {z.get('menge')} {z.get('einheit') or ''}".rstrip()
        for z in (rezept.get("zutaten") or []) if (z.get("zutat") or "").strip()
    )
    komp_txt = "\n\n".join(
        f"## {k['titel'] or 'Komponente'}" + (f" (Gerät: {k['geraet']})" if k.get("geraet") else "") + f"\n{k['text']}"
        for k in aktiv if (k.get("text") or "").strip()
    )
    # Fallback: Rezepte ohne strukturierte Komponenten haben oft nur die Freitext-Anleitung.
    if not komp_txt.strip():
        komp_txt = (rezept.get("anleitung") or "").replace("\\n", "\n").strip()
    user = (
        f"Rezept: {rezept.get('name')}\nBasis-Portionen: {basis}\n\n"
        f"ZUTATEN:\n{zlist}\n\nZUBEREITUNG:\n{komp_txt}\n\nGib die Schritte als JSON zurück."
    )
    resp = await billing.complete(
        _c(), "guided-cooking",
        model=await billing.modell_fuer_konto(),
        max_tokens=8192,
        messages=[{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
    )
    return _parse(resp.choices[0].message.content or "")


async def get_guided(rezept_id: int, varianten: list[int] | None = None, force: bool = False) -> dict:
    """Liefert die strukturierten Schritte für die gewählte Varianten-Kombination.
    Cache je Signatur am Rezept (global, da rezept-intrinsisch). Erzeugt per KI bei Bedarf."""
    rezept = await services.get_rezept(rezept_id)
    if not rezept:
        return {"error": "Rezept nicht gefunden"}
    sig, _ = _aktive_varianten(rezept, varianten)
    if not force:
        async with acquire(bypass=True) as con:
            cache = await con.fetchval("SELECT zubereitung_guided FROM rezepte WHERE id = $1", int(rezept_id))
        if isinstance(cache, dict) and isinstance(cache.get(sig), list) and cache[sig]:
            return {"rezept_id": int(rezept_id), "signatur": sig, "portionen": rezept.get("portionen") or 4,
                    "schritte": cache[sig], "cached": True}
    schritte = await strukturiere(rezept, varianten)
    if not schritte:
        return {"error": "Konnte die Zubereitung nicht in Schritte zerlegen."}
    try:
        async with acquire(bypass=True) as con:
            await con.execute(
                "UPDATE rezepte SET zubereitung_guided = "
                "coalesce(zubereitung_guided, '{}'::jsonb) || jsonb_build_object($2, $3::jsonb) "
                "WHERE id = $1", int(rezept_id), sig, json.dumps(schritte))
    except Exception:
        pass  # Cache ist optional – Schritte trotzdem liefern
    return {"rezept_id": int(rezept_id), "signatur": sig, "portionen": rezept.get("portionen") or 4,
            "schritte": schritte, "cached": False}


async def frage(rezept_id: int, schritt_text: str | None, frage_text: str) -> dict:
    """KI-Assistent im Kochmodus: kurze, praktische Antwort zur Frage im Kontext des
    Rezepts und (falls gegeben) des aktuellen Schritts."""
    frage_text = (frage_text or "").strip()
    if not frage_text:
        return {"error": "Keine Frage angegeben."}
    rezept = await services.get_rezept(rezept_id)
    if not rezept:
        return {"error": "Rezept nicht gefunden"}
    zlist = ", ".join((z.get("zutat") or "").strip() for z in (rezept.get("zutaten") or []) if (z.get("zutat") or "").strip())
    sys = ("Du bist ein hilfreicher Koch-Assistent während des Kochens. Antworte KURZ, "
           "konkret und praktisch auf Deutsch (1-3 Sätze), passend zum Rezept und zum "
           "aktuellen Schritt. Keine Wiederholung der ganzen Anleitung.")
    ctx = f"Rezept: {rezept.get('name')}. Zutaten: {zlist}."
    if (schritt_text or "").strip():
        ctx += f"\nAktueller Schritt: {schritt_text.strip()}"
    resp = await billing.complete(
        _c(), "guided-frage",
        model=await billing.modell_fuer_konto(),
        max_tokens=512,
        messages=[{"role": "system", "content": sys},
                  {"role": "user", "content": f"{ctx}\n\nFrage: {frage_text}"}],
    )
    return {"antwort": (resp.choices[0].message.content or "").strip()}
