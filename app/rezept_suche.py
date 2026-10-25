"""Rezeptsuche (Freitext → passende Rezepte, gerankt) – OHNE KI-Aufruf.

Bis 2026-07-26 war das eine semantische KI-Suche: jeder Suchvorgang ging als
Modellaufruf über `billing.complete` (zweck 'ki-suche'), zählte ins
KI-Monatskontingent und konnte mit 402 enden. Jetzt wird lexikalisch im Backend
gesucht: Die Suchbegriffe werden gegen Name, Zutaten, Gang, Küche und
Beschreibung gematcht und gewichtet gerankt. „ohne X" schließt Rezepte mit X
aus, „schnell" bevorzugt kurze Zubereitungszeiten. Kostenlos, ohne
Kontingent-Verbrauch, auch für Mitglieder ohne KI-Freigabe nutzbar.
"""
from __future__ import annotations

import logging
import re

from . import services
from .db import acquire
from .userauth import current_account

log = logging.getLogger("koch")

MAX_TREFFER = 20

_WORT = re.compile(r"[a-zäöüß]+")

# Füllwörter, die in Wunsch-Formulierungen stecken („was Schnelles mit Hähnchen").
_STOPP = {
    "und", "oder", "was", "etwas", "ein", "eine", "einen", "einem", "einer",
    "der", "die", "das", "den", "dem", "des", "fuer", "zum", "zur", "aus",
    "ich", "wir", "auf", "lust", "habe", "hab", "haben", "gern", "gerne",
    "bitte", "mal", "heute", "abend", "morgen", "mittag", "gericht", "rezept",
    "rezepte", "irgendwas", "am", "im", "an", "in", "so", "wie", "es", "zu",
}

# „schnell"-Wörter werden nicht lexikalisch gematcht, sondern auf die Dauer gemappt.
_SCHNELL = {"schnell", "schnelle", "schnelles", "schneller", "fix", "fixes", "flott", "flottes"}
_SCHNELL_MINUTEN = 30

# Gewichte je Fundstelle – ein Treffer im Namen wiegt mehr als in der Beschreibung.
_GEWICHT_NAME = 3.0
_GEWICHT_ZUTAT = 2.5
_GEWICHT_KATEGORIE = 2.0   # Gang/Küche
_GEWICHT_BESCHREIBUNG = 1.0


def _norm(s: str | None) -> str:
    """Kleinschreibung + Umlaute vereinheitlichen (ä→ae …), damit „Hähnchen"
    und „Haehnchen" gleich matchen."""
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def _begriffe(query: str) -> tuple[list[str], list[str], bool]:
    """Zerlegt den Freitext in Positiv-/Negativ-Begriffe + „schnell"-Flag.
    Wörter nach „ohne" gelten als Ausschluss, bis wieder „mit"/„und" kommt."""
    pos, neg, schnell = [], [], False
    modus_neg = False
    for tok in _WORT.findall((query or "").lower()):
        if tok == "ohne":
            modus_neg = True
            continue
        if tok in ("mit", "aber", "dazu"):
            modus_neg = False
            continue
        t = _norm(tok)
        if t in _SCHNELL:
            schnell = True
            continue
        if len(t) < 3 or t in _STOPP:
            continue
        (neg if modus_neg else pos).append(t)
    return pos, neg, schnell


def _trifft(term: str, text: str) -> bool:
    """Begriff-Match: ganzes Wort oder – ab 4 Zeichen – Teilwort (fängt deutsche
    Komposita wie „Maishähnchen" oder „Hähnchenbrustfilet")."""
    if not text:
        return False
    if len(term) >= 4:
        return term in text
    return any(w == term for w in _WORT.findall(text))


async def suche(query: str, nur_eigene: bool = False) -> dict:
    q = (query or "").strip()
    if len(q) < 2:
        return {"treffer": [], "meldung": "Bitte gib einen Suchbegriff ein."}

    alle = await services.search_rezepte()  # alle sichtbaren Rezepte in Kartenform
    acc = current_account.get()

    def _eigen(r):
        return acc is not None and r.get("account_id") == acc

    if nur_eigene and acc is not None:
        alle = [r for r in alle if _eigen(r)]
    if not alle:
        return {"treffer": [], "gesamt_durchsucht": 0, "gedeckelt": False}

    # Zutaten je Rezept (RLS begrenzt auf sichtbare Rezepte) – für „mit Hähnchen".
    zutaten_map: dict[int, list[str]] = {}
    try:
        async with acquire() as con:
            for row in await con.fetch(
                    "SELECT rz.rezept_id, z.name FROM rezept_zutaten rz "
                    "JOIN zutaten z ON z.id = rz.zutat_id"):
                zutaten_map.setdefault(int(row["rezept_id"]), []).append(row["name"] or "")
    except Exception:
        log.exception("rezept_suche: Zutaten laden fehlgeschlagen – suche nur in Stammdaten")

    pos, neg, schnell = _begriffe(q)

    gewertet = []
    for r in alle:
        rid = int(r["id"])
        felder = [
            (_norm(r.get("name")), _GEWICHT_NAME),
            (_norm(" ".join(zutaten_map.get(rid, []))), _GEWICHT_ZUTAT),
            (_norm(f"{r.get('gang') or ''} {r.get('kueche') or ''}"), _GEWICHT_KATEGORIE),
            (_norm(r.get("beschreibung")), _GEWICHT_BESCHREIBUNG),
        ]
        # Ausschluss: „ohne Ofen" / „ohne Nüsse" – Negativ-Begriff irgendwo → raus.
        if any(_trifft(t, txt) for t in neg for txt, _ in felder):
            continue
        getroffen, score = 0, 0.0
        for t in pos:
            best = max((g for txt, g in felder if _trifft(t, txt)), default=0.0)
            if best > 0:
                getroffen += 1
                score += best
        dauer = r.get("dauer_minuten")
        if schnell:
            if dauer is not None and int(dauer) <= _SCHNELL_MINUTEN:
                score += 1.5
            elif dauer is not None and int(dauer) > 45:
                score -= 1.0
        # Ohne Positiv-Begriffe (z.B. nur „schnell" oder nur „ohne Ofen") zählt
        # jedes nicht ausgeschlossene Rezept; sonst muss mind. ein Begriff treffen.
        if pos and getroffen == 0:
            continue
        if schnell and not pos and (dauer is None or int(dauer) > _SCHNELL_MINUTEN):
            continue
        gewertet.append((getroffen, score, r))

    gewertet.sort(key=lambda x: (-x[0], -x[1], -(x[2].get("sterne") or 0),
                                 (x[2].get("name") or "").lower()))
    treffer = [r for _, _, r in gewertet[:MAX_TREFFER]]
    return {"treffer": treffer, "gesamt_durchsucht": len(alle),
            "gedeckelt": len(gewertet) > MAX_TREFFER}
