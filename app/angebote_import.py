"""Prospekt-Import im Hintergrund: Datei (PDF/Bild) -> Vision -> Angebote.

Die KI erkennt Markt (haendler) und Gueltigkeitszeitraum selbst aus dem Prospekt.
Nur wenn beides weder vom Nutzer angegeben noch erkennbar ist, geht der Job in den
Status 'rueckfrage' und wartet auf die fehlenden Angaben (ohne erneute Verarbeitung).

Die Verarbeitung (inkl. Klassifizierung art/master_zutat) laeuft als asyncio-Task,
damit der HTTP-Request sofort zurueckkommt. Fortschritt per Status-Endpunkt pollbar.
Die hochgeladene Datei liegt waehrend der Verarbeitung in einem temporaeren Ordner
und wird danach geloescht.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date as _d, timedelta as _td

from . import ki, pdf, services
from .userauth import current_account

# job_id -> {status, phase, seite, seiten, gefunden, importiert, error, erkannt, ...}
JOBS: dict[str, dict] = {}
TMP_DIR = os.environ.get("ANGEBOTE_TMP_DIR", "/tmp/koch_angebote")
MAX_SEITEN = 24
TEXT_MIN = 200  # ab so vielen Zeichen Seitentext: Text-Pfad statt Vision-Backup



_SYS = (
    "Du erfasst eine Seite eines Supermarkt-Prospekts. Antworte AUSSCHLIESSLICH mit "
    "validem JSON, ohne Erklaerung, ohne Markdown. Schema: "
    '{"markt":string|null,"gueltig_von":"YYYY-MM-DD"|null,"gueltig_bis":"YYYY-MM-DD"|null,'
    '"angebote":[{"name":string,"preis_angebot":number|null,"preis_normal":number|null,'
    '"einheit":string|null,"kategorie":string|null,"art":"zutat"|"fertiggericht"|"non_food",'
    '"master_zutat":string|null,"beschreibung":string|null,'
    '"gueltig_von":"YYYY-MM-DD"|null,"gueltig_bis":"YYYY-MM-DD"|null,'
    '"nur_wochenende":boolean,"wochenende_tage":string|null,"box":[number,number,number,number]|null}]}. '
    "markt = Name des Marktes/Haendlers (z.B. 'Supermarkt Beispiel', 'Discounter Muster'), wenn auf der "
    "Seite erkennbar, sonst null. Auf oberster Ebene gueltig_von/bis = HAUPT-Aktionszeitraum als "
    "ISO-Datum, wenn erkennbar (fehlt das Jahr, aus dem mitgegebenen heutigen Datum ableiten), sonst null. "
    "WICHTIG je Angebot: Gehoert ein Angebot zu einer Aktion mit ABWEICHENDEM, meist kuerzerem Zeitraum "
    "(z.B. 'Wochenend-Knaller/-Knueller', 'nur Fr.+Sa.', 'Do Fr Sa', 'nur am Wochenende', 'Donnerstag-Kracher'), "
    "setze nur_wochenende=true und schreibe die genannten Aktionstage woertlich in wochenende_tage (z.B. "
    "'Do Fr Sa', 'Fr+Sa'). Stehen explizite Datumsangaben dabei, gib zusaetzlich gueltig_von/bis (ISO) an. "
    "Sonst nur_wochenende=false, wochenende_tage=null, gueltig_von/bis=null. "
    "art: 'zutat' = Grund-/Kochzutat (Fleisch, Obst, Gemuese, Mehl, Naturjoghurt); "
    "'fertiggericht' = verarbeitet/fertig (TK-Pizza, Frucht-Joghurt, Snacks, Suesswaren, "
    "Getraenke); 'non_food' = kein Lebensmittel (Haushalt, Drogerie, Tierbedarf, Pflanzen). "
    "master_zutat NUR bei art='zutat': die generische Zutat hinter dem Produkt (z.B. "
    "'Haehnchenbrust' fuer 'Marke X Haehnchenbrustfilet', 'Tomate' fuer 'Snacktomaten'). "
    "einheit = Preisbezug (z.B. '100 g', 'Stueck', '500-g-Packung'). "
    "box = Bounding-Box NUR des Produktfotos dieses Artikels auf der Seite als "
    "[ymin,xmin,ymax,xmax], normiert 0-1000 (0=oben/links, 1000=unten/rechts). Umfasse "
    "moeglichst eng nur das Produktbild (ohne Preis-Stoerer/Nachbarartikel). Ist im Bild "
    "kein eindeutiges Produktfoto erkennbar (oder reine Textauswertung), box=null. "
    "Nur echte Angebote mit "
    "Produktname; keine reinen Werbe-/Deko-Texte, keine Dubletten. Deutsche Namen. "
    "Erfasse ALLE einzelnen Angebots-Artikel der Seite VOLLSTAENDIG – die erkannten Artikel "
    "ERGAENZEN die bestehende Angebotsliste des Marktes (nichts wird ersetzt), also lieber "
    "einen Artikel zu viel als einen vergessen."
)


def _parse(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(t)
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        pass
    # Bergung 1: JSON-Objekt aus umgebendem Fließtext herausschneiden (erste { … letzte }).
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        try:
            d = json.loads(t[i:j + 1])
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            pass
    # Bergung 2: bei abgeschnittener Ausgabe wenigstens die vollständigen
    # angebote-Objekte aus dem (truncierten) Text retten, statt die ganze Seite zu verlieren.
    objs = re.findall(r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*\}', t)
    angebote = []
    for o in objs:
        try:
            angebote.append(json.loads(o))
        except json.JSONDecodeError:
            continue
    if angebote:
        return {"angebote": angebote}
    return {}


def _bilder_zuordnen(meta: dict, page, aktiv: bool = True) -> None:
    """Schneidet je Angebot mit gueltiger 'box' den Produktausschnitt aus dem Seitenbild
    (PIL-Bild) und legt ihn als 'bild' ab. 'box' wird IMMER entfernt (nie importiert); ohne
    aktiv/Seite wird nur aufgeraeumt, nicht geschnitten."""
    for it in (meta.get("angebote") or []):
        box = it.pop("box", None)
        if not aktiv or page is None or not box:
            continue
        try:
            bild = pdf.ausschnitt(page, box)
        except Exception:
            bild = None
        if bild:
            it["bild"] = bild


# Ausgabe-Deckel je Seite. Die Ausgabe-Token dominieren die Kosten (bei Flash-Lite 0,40 €
# je 1 Mio., bei Flash 2,50 € – also das Vier- bis Achtfache der Eingabe), und ein Import
# macht bis zu 24 Aufrufe. Mit den alten 8192 kostete ein prospektreiches PDF im
# Extremfall ein Mehrfaches des Monats-Deckungsbeitrags eines Abos. 4096 lässt auch für
# dichte Seiten reichlich Luft (ein Angebot ≈ 30 Token JSON, das sind über 100 Angebote
# je Seite) und halbiert die Obergrenze. Wird eine Seite doch abgeschnitten, liefert
# _parse() nichts für diese Seite – dann hier erhöhen, nicht den Deckel entfernen.
_MAX_OUT = 4096


async def _seite_extrakt(url: str, heute: str) -> dict:
    """Vision-Backup: Seite als Bild an das Modell."""
    resp = await ki.complete(
        "angebote-import", max_tokens=_MAX_OUT,
        messages=[
            {"role": "system", "content": _SYS},
            {"role": "user", "content": [
                {"type": "text", "text": f"Heute ist {heute}. Erkenne Markt und Gueltigkeitszeitraum (falls sichtbar) und erfasse alle Angebote dieser Seite. Antworte nur mit JSON."},
                {"type": "image_url", "image_url": {"url": url}},
            ]},
        ],
    )
    return _parse(resp.choices[0].message.content or "")


async def _seite_text(text: str, heute: str) -> dict:
    """Text-Pfad: vorhandene PDF-Textebene direkt auswerten (ohne Bild)."""
    resp = await ki.complete(
        "angebote-import", max_tokens=_MAX_OUT,
        messages=[
            {"role": "system", "content": _SYS},
            {"role": "user", "content": f"Heute ist {heute}. Erkenne Markt und Gueltigkeitszeitraum (falls genannt) und erfasse alle Angebote aus diesem Prospekt-Seitentext. Antworte nur mit JSON.\n\nSEITENTEXT:\n{text[:14000]}"},
        ],
    )
    return _parse(resp.choices[0].message.content or "")


def _wochenende_zeitraum(gb: str, tage: str | None):
    """Leitet aus dem Haupt-Ende (meist Samstag) + den genannten Aktionstagen den
    Kurz-Zeitraum ab: 'Do…'->Do-Sa (2 Tage zurueck), 'Mi…'->3, sonst Fr+Sa (1)."""
    try:
        ende = _d.fromisoformat(gb)
    except (ValueError, TypeError):
        return None, None
    toks = set(re.findall(r"[a-zäöü]+", (tage or "").lower()))
    if {"do", "donnerstag"} & toks:
        back = 2
    elif {"mi", "mittwoch"} & toks:
        back = 3
    else:
        back = 1  # Fr+Sa
    return (ende - _td(days=back)).isoformat(), ende.isoformat()


def _stamp(offers: list[dict], haendler: str, gv: str, gb: str):
    """Stempelt Markt + Zeitraum. Eigener (z.B. Wochenend-) Zeitraum je Angebot hat
    Vorrang vor dem Hauptzeitraum."""
    for it in offers:
        it["haendler"] = haendler
        iv = (it.get("gueltig_von") or "").strip() or None
        ib = (it.get("gueltig_bis") or "").strip() or None
        if iv and ib:
            it["gueltig_von"], it["gueltig_bis"] = iv, ib
        elif it.get("nur_wochenende") and gb:
            wv, wb = _wochenende_zeitraum(gb, it.get("wochenende_tage"))
            it["gueltig_von"], it["gueltig_bis"] = (wv or gv), (wb or gb)
        else:
            it["gueltig_von"], it["gueltig_bis"] = gv, gb
        it.pop("nur_wochenende", None)
        it.pop("wochenende_tage", None)


async def _import(offers: list[dict], haendler: str, gv: str, gb: str) -> int:
    _stamp(offers, haendler, gv, gb)
    res = await services.import_angebote(offers)
    return int(res.get("importiert", 0))


async def _run(job_id: str, path: str, haendler: str | None, gv: str | None, gb: str | None,
               mit_bildern: bool = True):
    job = JOBS[job_id]
    try:
        heute = services._today().isoformat()
        offers: list[dict] = []
        det_markt = det_von = det_bis = None
        modi: set[str] = set()

        def _verarbeite(meta: dict):
            nonlocal det_markt, det_von, det_bis
            det_markt = det_markt or ((meta.get("markt") or "").strip() or None)
            det_von = det_von or (meta.get("gueltig_von") or None)
            det_bis = det_bis or (meta.get("gueltig_bis") or None)
            for it in (meta.get("angebote") or []):
                if (it.get("name") or "").strip():
                    offers.append(it)
            job["gefunden"] = len(offers)

        ext = os.path.splitext(path)[1].lower()
        job["phase"] = "erkennen"

        if ext == ".json":
            # JSON: die KI schaut drueber (klassifiziert art/Master-Zutat, erkennt
            # Wochenend-Aktionen, normalisiert Felder). Faellt auf rohes JSON zurueck,
            # falls die KI nichts liefert.
            job["seiten"] = 1
            job["seite"] = 1
            try:
                with open(path, "r", encoding="utf-8") as f:
                    roh = f.read()
            except Exception as e:
                job.update(status="fehler", error=f"Datei nicht lesbar: {e}")
                return
            meta: dict = {}
            try:
                meta = await _seite_text(roh[:9000], heute)
                modi.add("json+ki")
            except Exception:
                meta = {}
            if not (meta.get("angebote")):
                try:
                    data = json.loads(roh)
                    if isinstance(data, list):
                        meta = {"angebote": data}
                    elif isinstance(data, dict) and isinstance(data.get("angebote"), list):
                        meta = data
                    elif isinstance(data, dict) and (data.get("name") or "").strip():
                        meta = {"angebote": [data]}
                    elif isinstance(data, dict):
                        meta = data
                    modi.discard("json+ki")
                    modi.add("json")
                except Exception:
                    pass
            if not (meta.get("angebote")):
                job.update(status="fehler", error="JSON enthaelt keine erkennbaren Angebote.")
                return
            _verarbeite(meta)
        elif ext == ".pdf":
            try:
                job["seiten"] = min(pdf.seitenzahl(path), MAX_SEITEN)
                seiten = pdf.pdf_seiten(path, MAX_SEITEN)
            except Exception:
                job.update(status="fehler", error="PDF konnte nicht geoeffnet werden.")
                return
            for i, seite in enumerate(seiten, 1):
                job["seite"] = i
                meta = {}
                try:
                    txt = seite.text
                    if mit_bildern or len(txt) < TEXT_MIN:
                        # Bilder gewuenscht (liefert Angebote UND Produktbild-Boxen) oder
                        # keine brauchbare Textebene -> Vision pro Seite.
                        meta = await _seite_extrakt(pdf.data_url(seite.bild), heute)
                        modi.add("vision")
                        if not (meta.get("angebote")) and len(txt) >= TEXT_MIN:
                            meta = await _seite_text(txt, heute)
                            modi.add("text")
                    else:
                        # Ohne Bilder: schneller Text-Pfad.
                        meta = await _seite_text(txt, heute)
                        modi.add("text")
                except (PermissionError, ki.KiNichtKonfiguriert):
                    raise  # Sperre/fehlende Konfiguration klar melden, nicht als "0 Angebote" verschlucken
                except Exception:
                    meta = {}
                _bilder_zuordnen(meta, seite.bild, mit_bildern)
                _verarbeite(meta)
        else:
            # Einzelbild -> immer Vision; Ausschnitte aus demselben Bild.
            job["seiten"] = 1
            job["seite"] = 1
            try:
                seite = pdf.bild_oeffnen(path)
            except Exception:
                job.update(status="fehler", error="Datei konnte nicht gelesen werden (PDF oder Bild erwartet).")
                return
            try:
                meta = await _seite_extrakt(pdf.data_url(seite.bild, "JPEG", 85), heute)
                modi.add("vision")
            except (PermissionError, ki.KiNichtKonfiguriert):
                raise  # Sperre/fehlende Konfiguration klar melden, nicht als "0 Angebote" verschlucken
            except Exception:
                meta = {}
            _bilder_zuordnen(meta, seite.bild, mit_bildern)
            _verarbeite(meta)

        job["modus"] = "/".join(sorted(modi)) or "?"

        # Nutzerangabe hat Vorrang, sonst das von der KI Erkannte.
        eff_h = (haendler or "").strip() or det_markt
        eff_v = (gv or "").strip() or det_von
        eff_b = (gb or "").strip() or det_bis
        job["erkannt"] = {"markt": det_markt, "gueltig_von": det_von, "gueltig_bis": det_bis}

        if not (eff_h and eff_v and eff_b):
            # Markt/Zeitraum unbekannt -> nachfragen, Angebote zwischenspeichern.
            job["offers"] = offers
            job.update(
                status="rueckfrage", phase="rueckfrage",
                fehlt=[k for k, v in (("markt", eff_h), ("gueltig_von", eff_v), ("gueltig_bis", eff_b)) if not v],
                vorschlag={"markt": eff_h, "gueltig_von": eff_v, "gueltig_bis": eff_b},
            )
            return

        job["phase"] = "import"
        job["importiert"] = await _import(offers, eff_h, eff_v, eff_b)
        job["markt"] = eff_h
        job.update(status="fertig")
    except PermissionError as e:
        job.update(status="fehler", error=str(e))
    except Exception as e:
        job.update(status="fehler", error=f"{type(e).__name__}: {e}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def starte_import(datei_bytes: bytes, dateiname: str,
                        haendler: str | None, gv: str | None, gb: str | None,
                        mit_bildern: bool = True) -> str:
    os.makedirs(TMP_DIR, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    ext = os.path.splitext(dateiname or "")[1].lower() or ".bin"
    path = os.path.join(TMP_DIR, job_id + ext)
    with open(path, "wb") as f:
        f.write(datei_bytes)
    JOBS[job_id] = {
        "status": "verarbeitung", "phase": "warten", "seite": 0, "seiten": 0,
        "gefunden": 0, "importiert": 0, "error": None,
        "account_id": current_account.get(),   # F15: Job an das anlegende Konto binden
    }
    asyncio.create_task(_run(job_id, path, haendler, gv, gb, mit_bildern))
    return job_id


async def fortsetzen(job_id: str, haendler: str | None, gv: str | None, gb: str | None) -> dict | None:
    """Nach einer Rueckfrage: fehlende Angaben ergaenzen und die zwischengespeicherten
    Angebote importieren (ohne erneute Verarbeitung)."""
    job = JOBS.get(job_id)
    if job is None or job.get("status") != "rueckfrage":
        return None
    # F15: nur das Konto, das den Job angelegt hat, darf ihn fortsetzen.
    if job.get("account_id") is not None and job["account_id"] != current_account.get():
        return None
    erk = job.get("erkannt") or {}
    eff_h = (haendler or "").strip() or erk.get("markt")
    eff_v = (gv or "").strip() or erk.get("gueltig_von")
    eff_b = (gb or "").strip() or erk.get("gueltig_bis")
    if not (eff_h and eff_v and eff_b):
        return job  # immer noch unvollstaendig
    job.update(status="verarbeitung", phase="import")
    try:
        job["importiert"] = await _import(job.get("offers") or [], eff_h, eff_v, eff_b)
        job["markt"] = eff_h
        job.update(status="fertig")
    except Exception as e:
        job.update(status="fehler", error=f"{type(e).__name__}: {e}")
    return job


def status(job_id: str) -> dict | None:
    s = JOBS.get(job_id)
    if s is None:
        return None
    # F15: nur das anlegende Konto darf den Job-Status sehen.
    if s.get("account_id") is not None and s["account_id"] != current_account.get():
        return None
    # 'offers'/'account_id' nicht mit ausliefern (gross bzw. intern).
    return {k: v for k, v in s.items() if k not in ("offers", "account_id")}
