"""Rezeptbilder: 1:1-Zuschnitt/Resize + KI-Generierung via gemini-3.1-flash-image.

Eigene Uploads werden serverseitig auf quadratisch + max 1024 px gerechnet und als
JPEG-Data-URL gespeichert (Spalte rezepte.bild). Die Generierung läuft über den Vertex
generateContent-Endpoint (Imagen 4 wird am 17.08.2026 abgeschaltet); zwei Auflösungen
(Stufe schnell=512, standard=1024) und TOKENBASIERTE Abrechnung (siehe
billing.record_bild_gemini). Im v4-Kontingent-Modell reserviert billing.gate_v4() das
Monats-Bildkontingent bzw. den Bild-Credit VOR dem Aufruf (S-7); jeder Fehl-Ausgang gibt
die Reservierung zurück (_reservierung_zurueck).
"""
from __future__ import annotations

import base64
import io
import logging

from . import billing, config, gauth
from .db import acquire
from .userauth import current_account, current_user, darf_ki

log = logging.getLogger("koch")
MAX_PX = 1024


async def _gemini_bild_generate(prompt: str, image_size: str) -> "tuple[bytes | None, dict]":
    """Erzeugt EIN quadratisches Bild über Vertex gemini-3.1-flash-image (generateContent).
    image_size: '512' oder '1K'. Gibt (Bildbytes|None, usage) zurück; usage = Tokenzahlen
    {prompt, image, thought} aus usageMetadata (für die tokenbasierte Abrechnung)."""
    import httpx
    url = f"{config.VERTEX_PREDICT_BASE}/publishers/google/models/{config.IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"imageSize": image_size, "aspectRatio": "1:1"},
        },
    }
    headers = {"Authorization": "Bearer " + gauth.get_token(),
               "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as cx:
        r = await cx.post(url, json=body, headers=headers)
    r.raise_for_status()
    d = r.json() or {}
    um = d.get("usageMetadata") or {}
    img_tok = next((x.get("tokenCount", 0) for x in (um.get("candidatesTokensDetails") or [])
                    if x.get("modality") == "IMAGE"), 0)
    usage = {"prompt": int(um.get("promptTokenCount") or 0),
             "image": int(img_tok or 0),
             "thought": int(um.get("thoughtsTokenCount") or 0)}
    for cand in (d.get("candidates") or []):
        for p in (cand.get("content") or {}).get("parts") or []:
            inline = p.get("inlineData") or p.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), usage
    return None, usage


def quadrat_resize(raw: bytes, max_px: int = 768) -> str:
    """Mittiger 1:1-Zuschnitt + Resize auf max_px; gibt eine JPEG-Data-URL zurück."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    elif im.mode == "L":
        im = im.convert("RGB")
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    im = im.crop((left, top, left + s, top + s))
    if s > max_px:
        im = im.resize((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def _reservierung_zurueck(v4: bool, acc: int, info: "dict | None", reserviert) -> None:
    """F3/S-7: Bei JEDEM Fehl-Ausgang die Vorab-Reservierung zurückgeben.
    v4: Reservierungszeile löschen + ggf. den im Gate gezogenen Bild-Credit erstatten.
    PAYG: reservierte Cent aufs Guthaben zurückbuchen."""
    if v4:
        await billing.freigeben_v4(acc, info, "rezept-bild")
    else:
        await billing._erstatte(acc, reserviert, "rezept-bild")


async def generiere_rezeptbild(name: str, beschreibung: str | None = None,
                               zutaten: list[dict] | None = None) -> str | None:
    """Erzeugt ein quadratisches Food-Foto via Imagen. Ambiente richtet sich nach der
    Küche (Stil-Prompt); Gericht + Zutaten gehen für ein korrektes Ergebnis mit in den
    Prompt. Gibt eine Data-URL zurück (oder None); bucht bei Erfolg die Pauschale."""
    # Harte Barriere: ohne KI-Freigabe kein Bild generieren.
    if not await darf_ki(current_user.get(), current_account.get()):
        return None
    # Tarif-Limit vor der (kostenpflichtigen) Generierung prüfen – und im v4-Modell das
    # Kontingent bzw. den Bild-Credit SOFORT unter dem Konto-Row-Lock reservieren (S-7).
    # Ohne das überzogen N parallele Anfragen dasselbe Monatskontingent/denselben Credit.
    acc = current_account.get() or 1
    v4 = config.ABO_MODELL_V4
    _limit = None
    try:
        if v4:
            _limit = await billing.gate_v4(acc, ist_bild=True, zweck="rezept-bild")
        else:
            async with acquire() as con:
                _limit = await billing.limit_pruefen(con, acc)
    except Exception as e:
        # F9: Fail-closed – ohne gültige Prüfung kein kostenpflichtiges Bild.
        log.warning("limit_pruefen (Bild) fehlgeschlagen: %s", e)
        raise billing.AbrechnungspruefungFehlgeschlagen() from e
    if _limit and _limit.get("blockiert"):
        raise billing.LimitErreicht(_limit)
    if v4:
        # v4: kein €-Guthaben. Kontingent/Credit sind über die Reservierungszeile gedeckt;
        # bei Erfolg löst record_bild_gemini() sie ab, bei jedem Fehl-Ausgang wird sie
        # unten zurückgegeben (inkl. Erstattung eines gezogenen Bild-Credits).
        reserviert = 0
    else:
        # F3: Vorab-Reservierung wie im Chat-Pfad (verhindert Nebenläufigkeits-Abuse). Bei
        # jedem Fehl-Ausgang wird sie erstattet; bei Erfolg gegen die realen Kosten verrechnet.
        reserviert = await billing._reserviere_payg(acc, "rezept-bild")
    zlist = ", ".join(
        (z.get("zutat") or z.get("name") or "").strip()
        for z in (zutaten or []) if (z.get("zutat") or z.get("name"))
    )[:400]
    # EIN beschreibender Satz (kein \n, keine Anweisungen) -> verhindert gerenderten Text.
    gericht = name + (f", with {zlist}" if zlist else "")
    prompt = f"{gericht}. {config.IMAGE_STYLE}."
    model, image_size, stufe = await billing.bild_modell_und_preis()
    try:
        raw, usage = await _gemini_bild_generate(prompt, image_size)
    except Exception as e:
        log.warning("Bildgenerierung (Gemini) fehlgeschlagen: %s", e)
        await _reservierung_zurueck(v4, acc, _limit, reserviert)
        return None
    if not raw:
        await _reservierung_zurueck(v4, acc, _limit, reserviert)
        return None
    try:
        max_px = 1024 if stufe == "standard" else 512
        data_url = quadrat_resize(raw, max_px=max_px)
    except Exception as e:
        log.warning("Bild konnte nicht verarbeitet werden: %s", e)
        await _reservierung_zurueck(v4, acc, _limit, reserviert)
        return None
    await billing.record_bild_gemini(usage.get("prompt", 0), usage.get("image", 0),
                                     usage.get("thought", 0), stufe, reserviert=reserviert,
                                     reservierung_id=(_limit or {}).get("reservierung_id"),
                                     credit_gezogen=bool((_limit or {}).get("credit_gezogen")),
                                     credit_bild=bool((_limit or {}).get("credit_bild")))
    return data_url
