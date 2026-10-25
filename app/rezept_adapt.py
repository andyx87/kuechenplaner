"""Rezepte an die aktuellen Kuechengeraete anpassen (Hintergrund-Job).

Fuer jedes Rezept mit strukturierter Zubereitung wird per KI sichergestellt, dass
jede Komponente eine Variante fuer jedes vorhandene Geraet hat. Vorhandene
Varianten bleiben unveraendert; fehlende werden ergaenzt. Laeuft als asyncio-Task
mit Fortschritt (wie der Prospekt-Import).
"""
from __future__ import annotations

import asyncio
import json
import uuid

from . import ki, services
from .db import acquire
from .userauth import current_account

JOBS: dict[str, dict] = {}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _geraet_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a in b or b in a


def _abgedeckt(zubereitung: list, geraete: list[str]) -> bool:
    """True, wenn jede geraeteabhaengige Komponente bereits jedes Geraet abdeckt."""
    for komp in zubereitung or []:
        varianten = komp.get("varianten") or []
        # geraetelose Komponente (nur 'ohne Geraet') = geraeteunabhaengig -> ok
        hat_geraet = any((v.get("geraet") or "").strip() for v in varianten)
        if not hat_geraet:
            continue
        for g in geraete:
            if not any(_geraet_match(v.get("geraet") or "", g) for v in varianten):
                return False
    return True


_SYS = (
    "Du passt die Zubereitung eines Rezepts an die vorhandenen Kuechengeraete an. "
    "Antworte AUSSCHLIESSLICH mit validem JSON: {\"zubereitung\":[{\"titel\":str,"
    "\"varianten\":[{\"geraet\":str|null,\"text\":str}]}]}. "
    "Regeln: VORHANDENE Varianten woertlich uebernehmen (Text + Geraet unveraendert). "
    "Fuer jede geraeteabhaengige Komponente fehlende Varianten fuer die genannten Geraete "
    "ERGAENZEN (knapp, 1-3 Saetze, korrekt fuer das jeweilige Geraet). Varianten fuer Geraete, "
    "die NICHT in der Liste stehen, entfernen – aber nie eine Komponente ganz ohne Variante "
    "lassen (dann eine 'ohne Geraet'-Variante mit geraet=null behalten/erstellen). Komponenten, "
    "die nur eine geraetelose Variante haben, unveraendert lassen."
)


async def _adaptiere(detail: dict, geraete: list[str]) -> list | None:
    user = (
        f"Rezept: {detail.get('name')}\n"
        f"Vorhandene Geraete: {', '.join(geraete) or '(keine)'}\n"
        f"Aktuelle Zubereitung (JSON):\n{json.dumps(detail.get('zubereitung') or [], ensure_ascii=False)}\n\n"
        "Gib die angepasste Zubereitung als JSON zurueck."
    )
    resp = await ki.complete(
        "geraete-anpassung", max_tokens=8192, temperature=0.3,
        messages=[{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i == -1 or j <= i:
            return None
        try:
            data = json.loads(text[i:j + 1])
        except json.JSONDecodeError:
            return None
    zub = data.get("zubereitung") if isinstance(data, dict) else None
    return zub if isinstance(zub, list) and zub else None


async def _run(job_id: str, account_id: int | None):
    job = JOBS[job_id]
    try:
        if account_id is None:
            job.update(status="fehler", error="Kein Konto-Kontext.")
            return
        geraete_rows = await services.list_geraete()
        geraete = [g["name"] for g in geraete_rows]
        cur_sig = services._geraete_sig_von(geraete)
        if not geraete:
            job.update(status="fehler", error="Keine Geraete angelegt.")
            return
        # NUR Rezepte des eingeloggten Kontos – sonst zu viele Token.
        async with acquire() as con:
            rezepte = await con.fetch(
                "SELECT id, name FROM rezepte WHERE account_id = $1 ORDER BY name", account_id)
        job["total"] = len(rezepte)
        job["phase"] = "anpassen"
        angepasst = 0
        uebersprungen = 0
        for i, r in enumerate(rezepte, 1):
            job["index"] = i
            job["name"] = r["name"]
            detail = await services.get_rezept(r["id"])
            zub = detail.get("zubereitung") or []
            if not zub:
                continue
            if _abgedeckt(zub, geraete):
                # schon auf die Geraete abgestimmt -> kein KI-Aufruf, aber Signatur setzen
                await _set_geraete_sig(r["id"], cur_sig)
                uebersprungen += 1
                job["uebersprungen"] = uebersprungen
                continue
            try:
                neu = await _adaptiere(detail, geraete)
            except Exception:
                neu = None
            if not neu:
                continue
            await services.update_rezept(
                r["id"],
                name=detail["name"],
                beschreibung=detail.get("beschreibung"),
                anleitung=detail.get("anleitung"),
                portionen=int(detail.get("portionen") or 2),
                dauer_minuten=detail.get("dauer_minuten"),
                quelle=detail.get("quelle"),
                zutaten=[{"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit"),
                          "optional": z.get("optional")} for z in (detail.get("zutaten") or [])],
                geraete=[{"geraet_id": g["geraet_id"], "pflicht": g.get("pflicht")}
                         for g in (detail.get("geraete") or [])],
                zubereitung=neu,
                gang=detail.get("gang"),
                kueche=detail.get("kueche"),
            )
            await _set_geraete_sig(r["id"], cur_sig)
            angepasst += 1
            job["angepasst"] = angepasst
        job.update(status="fertig", angepasst=angepasst, uebersprungen=uebersprungen)
    except Exception as e:
        job.update(status="fehler", error=f"{type(e).__name__}: {e}")


async def adaptiere_eines(rezept_id: int) -> dict:
    """Passt EIN Rezept (z.B. ein frisch importiertes) an die Geräte des aktiven Kontos
    an – KI-Aufruf (Token). Überspringt, wenn keine Geräte/Zubereitung oder bereits
    abgedeckt. LimitErreicht/PermissionError werden durchgereicht (HTTP 402/403)."""
    detail = await services.get_rezept(rezept_id)
    if not detail:
        return {"error": "Rezept nicht gefunden"}
    geraete = [g["name"] for g in await services.list_geraete()]
    cur_sig = services._geraete_sig_von(geraete)
    zub = detail.get("zubereitung") or []
    if not zub or not geraete or _abgedeckt(zub, geraete):
        # Nichts anzupassen → trotzdem als „auf diese Küche abgestimmt" markieren.
        await _set_geraete_sig(rezept_id, cur_sig)
        return {"angepasst": False}
    neu = await _adaptiere(detail, geraete)
    if not neu:
        return {"angepasst": False}
    await services.update_rezept(
        rezept_id,
        name=detail["name"], beschreibung=detail.get("beschreibung"),
        anleitung=detail.get("anleitung"), portionen=int(detail.get("portionen") or 2),
        dauer_minuten=detail.get("dauer_minuten"), quelle=detail.get("quelle"),
        zutaten=[{"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit"),
                  "optional": z.get("optional")} for z in (detail.get("zutaten") or [])],
        geraete=[{"geraet_id": g["geraet_id"], "pflicht": g.get("pflicht")}
                 for g in (detail.get("geraete") or [])],
        zubereitung=neu, gang=detail.get("gang"), kueche=detail.get("kueche"),
    )
    await _set_geraete_sig(rezept_id, cur_sig)
    return {"angepasst": True}


async def _set_geraete_sig(rezept_id: int, sig: str) -> None:
    """Markiert ein Rezept als auf die aktuelle Gerätekombination abgestimmt (account-scoped)."""
    try:
        async with acquire() as con:
            await con.execute("UPDATE rezepte SET geraete_sig = $2 WHERE id = $1", int(rezept_id), sig)
    except Exception:
        pass


async def starte() -> str:
    job_id = uuid.uuid4().hex[:12]
    acc = current_account.get()
    JOBS[job_id] = {"status": "laeuft", "phase": "start", "index": 0, "total": 0,
                    "angepasst": 0, "uebersprungen": 0, "name": "", "error": None,
                    "account_id": acc}   # F15: Job an das anlegende Konto binden
    asyncio.create_task(_run(job_id, acc))
    return job_id


def status(job_id: str) -> dict | None:
    s = JOBS.get(job_id)
    if s is None:
        return None
    # F15: nur das anlegende Konto darf den Job-Status sehen.
    if s.get("account_id") is not None and s["account_id"] != current_account.get():
        return None
    return {k: v for k, v in s.items() if k != "account_id"}
