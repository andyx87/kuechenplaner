"""Einmal-/Wartungs-Job: Bilder für öffentliche Rezepte (Pool) erzeugen.

Läuft kontoübergreifend (bypass), erzeugt für veröffentlichte Rezepte OHNE Bild ein
1024px-Bild über den konfigurierten Bild-Anbieter und speichert es. In Chunks
aufrufbar, damit es unter dem Request-Timeout bleibt.
"""
from __future__ import annotations

import asyncio
import logging

from . import bilder
from .db import acquire
from .ki import bild_openai

log = logging.getLogger("koch")


async def _generiere_mit_retry(prompt: str, versuche: int = 4):
    """Erzeugt EIN 1024px-Bild; bei 429 (Rate-Limit) mit Backoff erneut versuchen."""
    for i in range(versuche):
        try:
            # Admin-Wartungsjob ohne Nutzerkontext -> direkt der Anbieter (ohne darf_ki).
            return await bild_openai.bild_erzeugen(prompt)
        except Exception as e:
            is429 = "429" in str(e) or "Too Many Requests" in str(e)
            if is429 and i < versuche - 1:
                await asyncio.sleep(20 * (i + 1))   # 20s, 40s, 60s
                continue
            raise
    return None


async def _zutaten_namen(con, rezept_id: int) -> str:
    rows = await con.fetch(
        "SELECT z.name FROM rezept_zutaten rz JOIN zutaten z ON z.id = rz.zutat_id "
        "WHERE rz.rezept_id = $1 LIMIT 12", rezept_id)
    return ", ".join((r["name"] or "").strip() for r in rows if (r["name"] or "").strip())[:400]


async def offen_anzahl() -> int:
    async with acquire(bypass=True) as con:
        return int(await con.fetchval(
            "SELECT COUNT(*) FROM rezepte WHERE veroeffentlicht AND bild IS NULL") or 0)


async def batch(limit: int = 8) -> dict:
    """Erzeugt für bis zu `limit` öffentliche Rezepte ohne Bild eines (1024px).
    Gibt {erledigt, fehler, verbleibend} zurück."""
    limit = max(1, min(int(limit or 8), 25))
    erledigt = 0
    fehler = 0
    async with acquire(bypass=True) as con:
        rezepte = await con.fetch(
            "SELECT id, name, beschreibung FROM rezepte "
            "WHERE veroeffentlicht AND bild IS NULL ORDER BY id LIMIT $1", limit)
        for idx, r in enumerate(rezepte):
            try:
                zlist = await _zutaten_namen(con, r["id"])
                prompt = bilder.bild_prompt(r["name"], zlist)
                raw = await _generiere_mit_retry(prompt)
                if not raw:
                    fehler += 1
                    continue
                data_url = bilder.quadrat_resize(raw, max_px=1024)
                await con.execute(
                    "UPDATE rezepte SET bild = $2, updated_at = now() WHERE id = $1",
                    r["id"], data_url)
                erledigt += 1
            except Exception as e:
                log.warning("pool-bild fehlgeschlagen (rezept %s): %s", r["id"], e)
                fehler += 1
            # Pacing gegen das Rate-Limit (nicht nach dem letzten Bild warten).
            if idx < len(rezepte) - 1:
                await asyncio.sleep(7)
    verbleibend = await offen_anzahl()
    return {"erledigt": erledigt, "fehler": fehler, "verbleibend": verbleibend}
