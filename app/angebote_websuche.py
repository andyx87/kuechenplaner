"""Angebote im Internet suchen (Voll-Automatik) via Gemini + Google-Search-Grounding.

Der Chatbot kann auf Wunsch ("such die aktuellen Angebote von Supermarkt Beispiel") online nach den
aktuellen Prospekt-/Wochenangeboten eines Marktes suchen. Dafuer rufen wir den nativen
Vertex generateContent-Endpunkt mit dem `google_search`-Tool auf (das OpenAI-kompatible
Layer kann kein Grounding) und lassen das Modell die gefundenen Angebote als JSON liefern.
Abgerechnet wird tokenbasiert wie bei den uebrigen KI-Aufrufen (billing.record_usage).

WICHTIG: Online gefundene Preise koennen veraltet/ungenau sein. Das Ergebnis enthaelt
daher immer die Quelle; der Chat zeigt es dem Nutzer und erfasst erst nach Bestaetigung
(ueber das bestehende angebote_erfassen-Tool).
"""
from __future__ import annotations

import json
import logging
import re
import types

from . import billing, config, gauth, services
from .db import acquire
from .userauth import current_account, current_user, darf_ki

log = logging.getLogger("koch")

# Grounding laeuft ueber ein normales Text-Gemini (kein -lite, damit die Suche/Extraktion
# zuverlaessig ist). Bewusst fix, unabhaengig von der Modellstufe des Kontos.
_SUCH_MODELL = "gemini-2.5-flash"
_MAX_ANGEBOTE = 60


def _prompt(markt: str, ort: str | None, heute: str) -> str:
    ortzeile = f" am/um {ort}" if ort else ""
    return (
        f"Heutiges Datum: {heute}. Suche im Internet die AKTUELL gueltigen Wochen-/"
        f"Prospekt-Angebote des Lebensmittel-Marktes \"{markt}\"{ortzeile} (Deutschland). "
        "Nutze die Google-Suche und bevorzuge die offizielle Prospektseite des Marktes "
        "bzw. serioese Prospekt-Portale. Nimm NUR Angebote, die laut Quelle aktuell gueltig "
        "sind (Zeitraum, der das heutige Datum einschliesst). Erfinde KEINE Preise oder "
        "Artikel; lass Felder lieber weg, als zu raten.\n\n"
        "Gib AUSSCHLIESSLICH ein JSON-Objekt aus (kein Fliesstext, keine Erklaerung) in genau "
        "dieser Form:\n"
        "{\n"
        '  "markt": "<Markt-Name>",\n'
        '  "gueltig_von": "YYYY-MM-DD",\n'
        '  "gueltig_bis": "YYYY-MM-DD",\n'
        '  "quelle": "<URL der wichtigsten Quelle>",\n'
        '  "angebote": [\n'
        "    {\n"
        '      "name": "<Artikelname>",\n'
        '      "preis_angebot": <Zahl in EUR, z.B. 2.99>,\n'
        '      "preis_normal": <Zahl in EUR oder weglassen>,\n'
        '      "einheit": "<z.B. Stück, kg, Packung, 500 g>",\n'
        '      "kategorie": "<z.B. Fleisch, Obst, Molkerei, Tiefkühl>",\n'
        '      "art": "<zutat | fertiggericht | non_food>",\n'
        '      "master_zutat": "<nur bei art=zutat: generische Zutat, z.B. Hähnchenbrust>",\n'
        '      "beschreibung": "<optional: Sorte/Grundpreis>"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "art: 'zutat' = Grund-/Kochzutat (Fleisch, Obst, Gemuese, Mehl, Naturjoghurt ...); "
        "'fertiggericht' = verarbeitet/fertig (TK-Pizza, Frucht-Joghurt, Snacks, Suesswaren, "
        "Getraenke ...); 'non_food' = kein Lebensmittel (Haushalt, Drogerie, Tierbedarf ...). "
        "Bei art='zutat' immer 'master_zutat' setzen (generische Zutat hinter dem Markenprodukt). "
        f"Maximal {_MAX_ANGEBOTE} Angebote. Findest du keine aktuellen Angebote, gib "
        '{"angebote": []} zurueck.'
    )


def _json_aus_text(text: str) -> dict:
    """Extrahiert das JSON-Objekt aus der Modellantwort (toleriert ```-Fences/Fliesstext)."""
    if not text:
        return {}
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # Fallback: groesste {...}-Klammer herausschneiden.
    i, j = t.find("{"), t.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(t[i:j + 1])
        except Exception:
            return {}
    return {}


async def suche_angebote(markt: str, ort: str | None = None) -> dict:
    """Sucht online die aktuellen Angebote von `markt`. Gibt
    {markt, gueltig_von, gueltig_bis, quelle, angebote:[...], gefunden} zurueck.
    Wirft PermissionError / billing.LimitErreicht analog zu billing.complete."""
    markt = (markt or "").strip()
    if not markt:
        return {"gefunden": 0, "angebote": [], "fehler": "Kein Markt angegeben."}

    # Gleiche Vor-Pruefung wie billing.complete: KI-Freigabe + Tarif-Limit.
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")
    acc = current_account.get() or 1
    try:
        async with acquire() as con:
            info = await billing.limit_pruefen(con, acc)
    except Exception as e:
        log.warning("limit_pruefen (websuche) fehlgeschlagen: %s", e)
        info = None
    if info and info.get("blockiert"):
        raise billing.LimitErreicht(info)

    import httpx
    heute = services._today().isoformat()
    url = f"{config.VERTEX_PREDICT_BASE}/publishers/google/models/{_SUCH_MODELL}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": _prompt(markt, ort, heute)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1},
    }
    headers = {"Authorization": "Bearer " + gauth.get_token(), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as cx:
        r = await cx.post(url, json=body, headers=headers)
    r.raise_for_status()
    d = r.json() or {}

    # Tokenverbrauch abrechnen (Shim, damit record_usage Markup/PAYG-Abzug wiederverwendet).
    um = d.get("usageMetadata") or {}
    pt = int(um.get("promptTokenCount") or 0)
    tt = int(um.get("totalTokenCount") or 0)
    ct = int(um.get("candidatesTokenCount") or 0) or max(0, tt - pt)
    shim = types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt or (pt + ct)),
        model=_SUCH_MODELL)
    await billing.record_usage(shim, "angebote-websuche", modell=_SUCH_MODELL)

    # Antworttext zusammensetzen und JSON parsen.
    text = ""
    for cand in (d.get("candidates") or []):
        for p in (cand.get("content") or {}).get("parts") or []:
            if isinstance(p.get("text"), str):
                text += p["text"]
    daten = _json_aus_text(text)

    eintraege = daten.get("angebote") if isinstance(daten, dict) else None
    if not isinstance(eintraege, list):
        eintraege = []
    gv = (daten.get("gueltig_von") if isinstance(daten, dict) else None) or None
    gb = (daten.get("gueltig_bis") if isinstance(daten, dict) else None) or None
    quelle = (daten.get("quelle") if isinstance(daten, dict) else None) or None

    angebote: list[dict] = []
    for e in eintraege[:_MAX_ANGEBOTE]:
        if not isinstance(e, dict) or not (e.get("name") or "").strip():
            continue
        angebote.append({
            "name": str(e.get("name")).strip(),
            "preis_angebot": e.get("preis_angebot"),
            "preis_normal": e.get("preis_normal"),
            "einheit": e.get("einheit"),
            "kategorie": e.get("kategorie"),
            "art": e.get("art"),
            "master_zutat": e.get("master_zutat"),
            "beschreibung": e.get("beschreibung"),
            "gueltig_von": e.get("gueltig_von") or gv,
            "gueltig_bis": e.get("gueltig_bis") or gb,
            "haendler": markt,
        })

    return {
        "markt": markt,
        "gueltig_von": gv,
        "gueltig_bis": gb,
        "quelle": quelle,
        "gefunden": len(angebote),
        "angebote": angebote,
        "hinweis": ("Online-Suche ist SEHR UNGENAU (Preise/Sortiment/Gültigkeit oft veraltet "
                    "oder regional abweichend). Dem Nutzer klar sagen, dass das nur eine grobe "
                    "Orientierung ist und der Prospekt-Upload die mit Abstand beste, exakte "
                    "Variante ist: am besten die Prospekt-PDF hochladen oder Fotos/Screenshots "
                    "vom Prospekt machen – direkt hier im Assistenten (📎) oder in der Rubrik "
                    "'Angebote'. Quelle nennen, Funde nur nach Bestätigung erfassen."),
    }
