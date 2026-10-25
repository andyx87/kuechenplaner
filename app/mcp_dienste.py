"""Fachlogik der MCP-Werkzeuge (Batch, Vorschau, Idempotenz, Paginierung).

Alles läuft über `db.acquire()` und damit unter RLS im Haushalt des Aufrufers. Kein
bypass, keine Admin-Pfade. Die eigentlichen Berechnungen (Matching, Einkaufsliste,
Vorschläge) kommen unverändert aus `services`.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from . import guided, rezept_adapt, services
from .db import acquire
from .schemas import (AngeboteImport, EinkaufPosten, GeraetIn, Kochschritt, PlanEintrag, RezeptIn,
                      RezeptUpdate, VorratPosten)
from .services import _date, _jsonable, _today
from .userauth import current_account

MAX_LIMIT = 100

KATEGORIEN_STANDARD = [
    "Obst & Gemüse", "Fleisch & Wurst", "Fisch", "Molkerei & Käse", "Eier", "Brot & Backwaren",
    "Nudeln, Reis & Getreide", "Konserven", "Gewürze & Saucen", "Öl & Essig", "Backzutaten",
    "Tiefkühl", "Süßwaren", "Snacks", "Getränke", "Kaffee & Tee", "Drogerie", "Haushalt", "Non-Food",
]


class Fehler(Exception):
    """Fachlicher Fehler mit lesbarer Meldung (wird zum ToolError)."""


def seite(cursor: str | None, limit: int) -> tuple[int, int]:
    try:
        offset = max(0, int(cursor or 0))
    except ValueError as e:
        raise Fehler("Ungültiger cursor – bitte den Wert aus 'naechster_cursor' verwenden.") from e
    return offset, max(1, min(int(limit or 20), MAX_LIMIT))


def paginiert(eintraege: list, offset: int, limit: int, **extra) -> dict:
    teil = eintraege[offset:offset + limit]
    weiter = offset + limit < len(eintraege)
    return {"eintraege": teil, "gesamt": len(eintraege),
            "naechster_cursor": str(offset + limit) if weiter else None, **extra}


# ---------- Idempotenz ----------

async def idempotent(werkzeug: str, schluessel: str | None,
                     ausfuehren: Callable[[], Awaitable[dict]]) -> dict:
    """Führt `ausfuehren` höchstens einmal je (Haushalt, Werkzeug, Schlüssel) aus. Eine
    Wiederholung mit gleichem Schlüssel liefert das gespeicherte Ergebnis (wiederholt=True)."""
    if not schluessel:
        return await ausfuehren()
    async with acquire() as con:
        alt = await con.fetchval(
            "SELECT ergebnis FROM mcp_idempotenz WHERE werkzeug = $1 AND schluessel = $2",
            werkzeug, schluessel)
    if alt is not None:
        res = alt if isinstance(alt, dict) else json.loads(alt)
        return {**res, "wiederholt": True}
    res = await ausfuehren()
    async with acquire() as con:
        await con.execute(
            "INSERT INTO mcp_idempotenz (werkzeug, schluessel, ergebnis) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING", werkzeug, schluessel, _jsonable(res))
    return res


# ---------- Kontext ----------

async def haushalt_uebersicht() -> dict:
    heute = _today()
    personen = await services.list_personen()
    geraete = await services.list_geraete()
    heute_ids = {g["id"] for g in await services.get_geraete_heute()}
    lagerorte = await services.list_lagerorte()
    einkaufstage = await services.list_einkaufstage(heute)
    async with acquire() as con:
        maerkte = await con.fetch(
            "SELECT haendler, min(gueltig_von) AS von, max(gueltig_bis) AS bis, count(*) AS anzahl "
            "FROM angebote WHERE gueltig_bis >= $1 AND haendler IS NOT NULL GROUP BY haendler ORDER BY haendler",
            heute)
        n_rezepte = await con.fetchval("SELECT count(*) FROM rezepte WHERE account_id = $1", current_account.get())
        n_vorrat = await con.fetchval("SELECT count(*) FROM vorrat")
        haushalt = await con.fetchval("SELECT name FROM account WHERE id = $1", current_account.get())
    return _jsonable({
        "haushalt": haushalt,
        "heute": heute.isoformat(),
        "personen": [{k: p.get(k) for k in ("id", "name", "rolle", "portionsfaktor", "kcal_ziel", "ernaehrung",
                                             "allergien", "mag_nicht", "mag_gern", "aktiv")} for p in personen],
        "geraete": [{"id": g["id"], "name": g["name"], "typ": g.get("typ"), "standard": g.get("standard"),
                     "heute": g["id"] in heute_ids} for g in geraete],
        "lagerorte": [{"id": lo["id"], "name": lo["name"]} for lo in lagerorte],
        "einkaufstage_diese_woche": [{"datum": e["datum"], "maerkte": e.get("haendler_liste") or []}
                                     for e in einkaufstage],
        "maerkte_mit_angeboten": [dict(m) for m in maerkte],
        "anzahl_eigene_rezepte": n_rezepte,
        "anzahl_vorratsposten": n_vorrat,
    })


# ---------- Vorrat ----------

async def _lagerort_finden(con, name: str | None) -> tuple[int | None, bool]:
    if not (name or "").strip():
        return None, False
    lid = await con.fetchval("SELECT id FROM lagerort WHERE lower(name) = lower($1)", name.strip())
    return lid, lid is None


async def vorrat_buchen(posten: list[VorratPosten], vorschau: bool) -> dict:
    ergebnisse: list[dict] = []
    async with acquire() as con:
        tx = con.transaction()
        await tx.start()
        try:
            for i, p in enumerate(posten):
                gefunden = await services._finde_zutat(con, p.name)
                lid, lager_neu = await _lagerort_finden(con, p.lagerort)
                eintrag: dict[str, Any] = {
                    "index": i, "eingabe": p.name, "menge": p.menge, "einheit": p.einheit,
                    "lagerort": p.lagerort, "mhd": p.mhd, "sicherheit": p.sicherheit,
                    "zutat_id": gefunden[0] if gefunden else None,
                    "zutat": gefunden[1] if gefunden else p.name,
                    "treffer": gefunden[2] if gefunden else "neu",
                    "lagerort_neu": lager_neu,
                }
                if gefunden:
                    vorhanden = await con.fetch(
                        "SELECT menge, einheit FROM vorrat WHERE zutat_id = $1", gefunden[0])
                    eintrag["schon_im_vorrat"] = [f"{float(v['menge']):g} {v['einheit']}" for v in vorhanden]
                if not vorschau:
                    zid = gefunden[0] if gefunden else await services._ensure_zutat(con, p.name, p.einheit, p.kategorie)
                    if p.lagerort and lid is None:
                        lid = await services._ensure_lagerort(con, p.lagerort)
                    row = await con.fetchrow(
                        "INSERT INTO vorrat (zutat_id, menge, einheit, ablaufdatum, lagerort_id) "
                        "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                        zid, services._num(p.menge), p.einheit, _date(p.mhd), lid)
                    eintrag["vorrat_id"] = row["id"]
                    eintrag["zutat_id"] = zid
                    eintrag["ok"] = True
                ergebnisse.append(eintrag)
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise
    neu = sum(1 for e in ergebnisse if e["treffer"] == "neu")
    return _jsonable({
        "vorschau": vorschau,
        "gebucht": 0 if vorschau else len(ergebnisse),
        "neue_zutaten": neu,
        "posten": ergebnisse,
        "hinweis": ("Vorschau – nichts gespeichert. Dem Nutzer zeigen und mit vorschau=false erneut aufrufen."
                    if vorschau else "Gebucht."),
    })


async def vorrat_holen(lagerort: str | None, ablauf_in_tagen: int | None, suche: str | None,
                       limit: int, cursor: str | None) -> dict:
    offset, limit = seite(cursor, limit)
    rows = await services.list_vorrat()
    heute = _today()
    out = []
    for v in rows:
        if lagerort and (v.get("lagerort") or "").lower() != lagerort.lower():
            continue
        if suche and suche.lower() not in (v.get("zutat") or "").lower():
            continue
        if ablauf_in_tagen is not None:
            if not v.get("ablaufdatum"):
                continue
            if date.fromisoformat(v["ablaufdatum"]) > heute + timedelta(days=ablauf_in_tagen):
                continue
        out.append({"vorrat_id": v["id"], "zutat_id": v["zutat_id"], "zutat": v.get("zutat"),
                    "menge": v["menge"], "einheit": v["einheit"], "mhd": v.get("ablaufdatum"),
                    "lagerort": v.get("lagerort")})
    return paginiert(out, offset, limit)


async def vorrat_aendern(vorrat_id: int, menge: float | None, einheit: str | None, mhd: str | None,
                         lagerort: str | None, mhd_entfernen: bool) -> dict:
    async with acquire() as con:
        async with con.transaction():
            alt = await con.fetchrow("SELECT * FROM vorrat WHERE id = $1", int(vorrat_id))
            if alt is None:
                raise Fehler(f"Vorratsposten {vorrat_id} nicht gefunden.")
            lid = alt["lagerort_id"]
            if lagerort:
                lid = await services._ensure_lagerort(con, lagerort)
            ablauf = None if mhd_entfernen else (_date(mhd) if mhd else alt["ablaufdatum"])
            row = await con.fetchrow(
                "UPDATE vorrat SET menge = $2, einheit = $3, ablaufdatum = $4, lagerort_id = $5 "
                "WHERE id = $1 RETURNING *",
                int(vorrat_id), services._num(menge) if menge is not None else alt["menge"],
                einheit or alt["einheit"], ablauf, lid)
    return _jsonable(dict(row))


async def vorrat_loeschen(vorrat_ids: list[int]) -> dict:
    async with acquire() as con:
        res = await con.fetch("DELETE FROM vorrat WHERE id = ANY($1::int[]) RETURNING id", list(vorrat_ids))
    geloescht = sorted(r["id"] for r in res)
    return {"geloescht": geloescht, "nicht_gefunden": sorted(set(vorrat_ids) - set(geloescht))}


# ---------- Geräte ----------

async def geraete_anlegen(geraete: list[GeraetIn]) -> dict:
    out = []
    for g in geraete:
        async with acquire() as con:
            vorher = await con.fetchval("SELECT id FROM geraete WHERE lower(name) = lower($1)", g.name)
        if vorher:
            out.append({"name": g.name, "geraet_id": vorher, "neu": False})
            continue
        row = await services.add_geraet(g.name, g.typ, None, g.standard)
        out.append({"name": row["name"], "geraet_id": row["id"], "neu": True})
    return {"geraete": out, "angelegt": sum(1 for x in out if x["neu"])}


# ---------- Angebote ----------

async def angebote_schema() -> dict:
    async with acquire() as con:
        kats = await con.fetch(
            "SELECT kategorie, count(*) AS n FROM angebote WHERE kategorie IS NOT NULL AND kategorie <> '' "
            "GROUP BY kategorie ORDER BY count(*) DESC LIMIT 60")
        maerkte = await con.fetch(
            "SELECT DISTINCT haendler FROM angebote WHERE haendler IS NOT NULL ORDER BY haendler")
    genutzt = [r["kategorie"] for r in kats]
    return {
        "kategorien": genutzt + [k for k in KATEGORIEN_STANDARD if k not in genutzt],
        "bekannte_maerkte": [r["haendler"] for r in maerkte],
        "art": {"zutat": "Kochzutat (Gemüse, Fleisch, Milch, Grundnahrung …)",
                "fertiggericht": "Fertigprodukt, Snack, Süßes, Getränk",
                "non_food": "Drogerie, Haushalt, Tierbedarf, Sonstiges"},
        "regeln": [
            "Ein Aufruf je Prospekt/Markt und Gültigkeitszeitraum (gueltig_von/gueltig_bis aus dem Prospekt).",
            "preis = Angebotspreis in Euro als Zahl; preis_normal nur, wenn ein Streichpreis gedruckt ist.",
            "menge + einheit = Packungsgröße (500 + 'g'); grundpreis als gedruckter Text.",
            "master_zutat nur bei art=zutat: der generische Name, unter dem das Produkt in Rezepten vorkommt.",
            "Erst mit vorschau=true prüfen, dann mit vorschau=false speichern. Dubletten werden übersprungen.",
        ],
        "beispiel": {
            "markt": "Supermarkt Musterstadt", "gueltig_von": "2026-11-02", "gueltig_bis": "2026-11-07",
            "vorschau": True,
            "angebote": [
                {"name": "Hähnchen-Brustfilet", "marke": "Hofgut", "menge": 600, "einheit": "g", "preis": 5.99,
                 "preis_normal": 7.49, "grundpreis": "1 kg = 9.98", "kategorie": "Fleisch & Wurst",
                 "art": "zutat", "master_zutat": "Hähnchenbrust"},
                {"name": "Spülmittel", "menge": 500, "einheit": "ml", "preis": 0.95, "kategorie": "Haushalt",
                 "art": "non_food"},
            ],
        },
        "eingabe_schema": AngeboteImport.model_json_schema(),
    }


def _angebot_zeile(imp: AngeboteImport, a) -> dict:
    einheit = f"{a.menge:g} {a.einheit}".strip() if a.menge is not None and a.einheit else (a.einheit or None)
    teile = [t for t in (f"Marke: {a.marke}" if a.marke else None,
                         f"Grundpreis: {a.grundpreis}" if a.grundpreis else None) if t]
    return {
        "haendler": imp.markt, "gueltig_von": imp.gueltig_von, "gueltig_bis": imp.gueltig_bis,
        "name": a.name, "beschreibung": " · ".join(teile) or None, "einheit": einheit,
        "preis_angebot": a.preis, "preis_normal": a.preis_normal, "kategorie": a.kategorie,
        "art": a.art, "master_zutat": a.master_zutat if a.art == "zutat" else None,
        "nur_wochenende": a.nur_wochenende,
    }


async def angebote_importieren(imp: AngeboteImport, vorschau: bool) -> dict:
    zeilen = [_angebot_zeile(imp, a) for a in imp.angebote]
    if not vorschau:
        res = await services.import_angebote(zeilen, nur_konto=True)
        if res.get("error"):
            raise Fehler(res["error"])
        return {"vorschau": False, "markt": imp.markt, **res}
    posten = []
    async with acquire() as con:
        for i, z in enumerate(zeilen):
            dublette = bool(await con.fetchval(
                "SELECT 1 FROM angebote WHERE account_id = $5 AND haendler IS NOT DISTINCT FROM $1 "
                "AND lower(name) = lower($2) AND gueltig_von = $3 AND gueltig_bis = $4",
                z["haendler"], z["name"], _date(z["gueltig_von"]), _date(z["gueltig_bis"]), current_account.get()))
            m = await services._finde_zutat(con, z["master_zutat"]) if z["master_zutat"] else None
            posten.append({"index": i, "name": z["name"], "preis": z["preis_angebot"], "art": z["art"],
                           "dublette": dublette,
                           "master_zutat": (m[1] if m else z["master_zutat"]),
                           "master_treffer": (m[2] if m else ("neu" if z["master_zutat"] else None))})
    return {"vorschau": True, "markt": imp.markt, "gueltig_von": imp.gueltig_von, "gueltig_bis": imp.gueltig_bis,
            "neu": sum(1 for p in posten if not p["dublette"]), "dubletten": sum(1 for p in posten if p["dublette"]),
            "posten": posten,
            "hinweis": "Vorschau – nichts gespeichert. Mit vorschau=false speichern."}


async def angebote_holen(markt: str | None, datum: str | None, art: str | None, suche: str | None,
                         limit: int, cursor: str | None) -> dict:
    offset, limit = seite(cursor, limit)
    rows = await services.get_angebote(_date(datum) if datum else None)
    out = []
    for a in rows:
        if markt and (a.get("haendler") or "").lower() != markt.lower():
            continue
        rubrik = services._angebot_rubrik(a.get("art"), a.get("kategorie"), a.get("master_zutat_id") is not None)
        if art and rubrik != art:
            continue
        if suche and suche.lower() not in (a.get("name") or "").lower():
            continue
        out.append({"angebot_id": a["id"], "markt": a.get("haendler"), "name": a["name"],
                    "preis": a.get("preis_angebot"), "preis_normal": a.get("preis_normal"),
                    "einheit": a.get("einheit"), "kategorie": a.get("kategorie"), "art": rubrik,
                    "master_zutat": a.get("master_zutat_name"), "gueltig_von": a.get("gueltig_von"),
                    "gueltig_bis": a.get("gueltig_bis"), "eigenes": a.get("account_id") is not None})
    return paginiert(out, offset, limit)


async def angebote_blatt_loeschen(markt: str, gueltig_von: str, gueltig_bis: str) -> dict:
    # Ohne admin → RLS: nur Angebote des eigenen Haushalts.
    return await services.delete_angebote_blatt(markt, gueltig_von, gueltig_bis, admin=False)


# ---------- Rezepte ----------

def _rezept_kurz(r: dict) -> dict:
    return {"rezept_id": r["id"], "name": r["name"], "gang": r.get("gang"), "kueche": r.get("kueche"),
            "portionen": r.get("portionen"), "dauer_minuten": r.get("dauer_minuten"),
            "fehlende_zutaten": r.get("fehlend"), "pflicht_zutaten": r.get("pflicht_zutaten"),
            "sterne": r.get("sterne"), "hat_bild": r.get("hat_bild"),
            "eigenes": r.get("account_id") == current_account.get(),
            "geraete_abgestimmt": r.get("geraete_abgestimmt")}


async def rezepte_suchen(query, gang, kueche, zutaten, markt, nur_eigene, limit, cursor) -> dict:
    offset, limit = seite(cursor, limit)
    rows = await services.search_rezepte(query, gang, kueche, zutaten, markt)
    out = [_rezept_kurz(r) for r in rows]
    if nur_eigene:
        out = [r for r in out if r["eigenes"]]
    return paginiert(out, offset, limit)


async def _geraete_namen() -> list[str]:
    return [g["name"] for g in await services.list_geraete()]


async def _sig_wenn_abgedeckt(rezept_id: int, zubereitung: list[dict], geraete: list[str]) -> bool:
    if zubereitung and geraete and rezept_adapt._abgedeckt(zubereitung, geraete):
        await rezept_adapt._set_geraete_sig(rezept_id, services._geraete_sig_von(geraete))
        return True
    return False


def _pruefe_geraete(zubereitung: list[dict], geraete: list[str]) -> list[str]:
    bekannt = {g.lower() for g in geraete}
    unbekannt = []
    for k in zubereitung:
        for v in k.get("varianten") or []:
            g = (v.get("geraet") or "").strip()
            if g and g.lower() not in bekannt and g not in unbekannt:
                unbekannt.append(g)
    return unbekannt


async def rezept_anlegen(rezept: RezeptIn) -> dict:
    d = rezept.model_dump()
    geraete = await _geraete_namen()
    unbekannt = _pruefe_geraete(d["zubereitung"], geraete)
    if unbekannt:
        raise Fehler(f"Unbekannte Geräte in der Zubereitung: {', '.join(unbekannt)}. Nur Namen aus "
                     f"haushalt_uebersicht verwenden (vorhanden: {', '.join(geraete) or 'keine'}) "
                     "oder geraet=null; neue Geräte vorher mit geraete_anlegen anlegen.")
    neu = await services.add_rezept(
        name=d["name"], beschreibung=d["beschreibung"], anleitung=None, portionen=d["portionen"],
        dauer_minuten=d["dauer_minuten"], quelle=d["quelle"], zutaten=d["zutaten"], geraete=None,
        zubereitung=d["zubereitung"], gang=d["gang"], kueche=d["kueche"])
    abgestimmt = await _sig_wenn_abgedeckt(neu["id"], d["zubereitung"], geraete)
    return {"rezept_id": neu["id"], "name": neu["name"], "geraete_abgestimmt": abgestimmt,
            "zutaten": [{"zutat_id": z["zutat_id"], "zutat": z["zutat"]} for z in neu.get("zutaten") or []]}


async def _rezept_update_anwenden(u: RezeptUpdate, alt: dict) -> dict:
    felder = u.model_dump(exclude_unset=True)
    zutaten = felder.get("zutaten") or [
        {"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit"), "optional": z.get("optional")}
        for z in (alt.get("zutaten") or [])]
    return await services.update_rezept(
        u.rezept_id,
        name=felder.get("name", alt["name"]),
        beschreibung=felder.get("beschreibung", alt.get("beschreibung")),
        anleitung=alt.get("anleitung"),
        portionen=int(felder.get("portionen", alt.get("portionen") or 2)),
        dauer_minuten=felder.get("dauer_minuten", alt.get("dauer_minuten")),
        quelle=felder.get("quelle", alt.get("quelle")),
        zutaten=zutaten,
        geraete=[{"geraet_id": g["geraet_id"], "pflicht": g.get("pflicht")} for g in (alt.get("geraete") or [])],
        zubereitung=felder.get("zubereitung", alt.get("zubereitung")),
        gang=felder.get("gang", alt.get("gang")),
        kueche=felder.get("kueche", alt.get("kueche")),
    )


async def rezepte_aktualisieren(rezepte: list[RezeptUpdate], vorschau: bool) -> dict:
    geraete = await _geraete_namen()
    acc = current_account.get()
    ergebnisse = []
    for u in rezepte:
        alt = await services.get_rezept(u.rezept_id)
        if alt is None or alt.get("account_id") != acc:
            ergebnisse.append({"rezept_id": u.rezept_id, "ok": False,
                               "fehler": "Nicht gefunden oder kein eigenes Rezept (fremde Rezepte sind schreibgeschützt)."})
            continue
        felder = u.model_dump(exclude_unset=True)
        zub = felder.get("zubereitung")
        unbekannt = _pruefe_geraete(zub, geraete) if zub else []
        if unbekannt:
            ergebnisse.append({"rezept_id": u.rezept_id, "ok": False,
                               "fehler": f"Unbekannte Geräte: {', '.join(unbekannt)}"})
            continue
        geaendert = sorted(k for k in felder if k != "rezept_id")
        zub_neu = zub if zub is not None else (alt.get("zubereitung") or [])
        abdeckung = bool(zub_neu) and bool(geraete) and rezept_adapt._abgedeckt(zub_neu, geraete)
        e = {"rezept_id": u.rezept_id, "name": felder.get("name", alt["name"]), "felder": geaendert,
             "deckt_alle_geraete_ab": abdeckung}
        if not vorschau:
            await _rezept_update_anwenden(u, alt)
            if abdeckung:
                await rezept_adapt._set_geraete_sig(u.rezept_id, services._geraete_sig_von(geraete))
            e["ok"] = True
        ergebnisse.append(e)
    return {"vorschau": vorschau, "ergebnisse": ergebnisse,
            "aktualisiert": 0 if vorschau else sum(1 for e in ergebnisse if e.get("ok")),
            "fehler": sum(1 for e in ergebnisse if e.get("ok") is False)}


async def rezepte_anpassungsbedarf(limit: int, cursor: str | None) -> dict:
    """Eigene Rezepte, deren Zubereitung noch nicht auf die aktuellen Geräte abgestimmt ist."""
    offset, limit = seite(cursor, min(limit, 20))
    geraete = await _geraete_namen()
    sig = services._geraete_sig_von(geraete)
    async with acquire() as con:
        rows = await con.fetch(
            "SELECT id FROM rezepte WHERE account_id = $1 AND zubereitung IS NOT NULL "
            "AND (geraete_sig IS DISTINCT FROM $2) ORDER BY name", current_account.get(), sig)
    ids = [r["id"] for r in rows]
    teil = ids[offset:offset + limit]
    rezepte = []
    for rid in teil:
        r = await services.get_rezept(rid)
        if not r:
            continue
        if rezept_adapt._abgedeckt(r.get("zubereitung") or [], geraete):
            await rezept_adapt._set_geraete_sig(rid, sig)   # schon passend → nur markieren
            continue
        rezepte.append({"rezept_id": rid, "name": r["name"], "portionen": r.get("portionen"),
                        "zutaten": [{"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit")}
                                    for z in r.get("zutaten") or []],
                        "zubereitung": r.get("zubereitung")})
    weiter = offset + limit < len(ids)
    return _jsonable({
        "geraete": geraete, "offen_gesamt": len(ids), "rezepte": rezepte,
        "naechster_cursor": str(offset + limit) if weiter else None,
        "anleitung": ("Für jedes Rezept die Zubereitung so ergänzen, dass jede geräteabhängige Komponente "
                      "je eine Variante pro Gerät in 'geraete' hat (vorhandene Texte übernehmen), dann "
                      "rezepte_aktualisieren mit allen Komponenten aufrufen. Danach diese Liste erneut "
                      "abrufen – erledigte Rezepte fallen heraus."),
    })


async def rezepte_aus_angeboten(markt: str | None, datum: str | None, limit: int) -> dict:
    d = _date(datum) or _today()
    maerkte = [markt] if markt else [m["haendler"] for m in (await haushalt_uebersicht())["maerkte_mit_angeboten"]]
    out = []
    for m in maerkte:
        for r in await services.rezepte_aus_angeboten(m, d, limit):
            out.append({**r, "markt": m})
    out.sort(key=lambda r: -(r.get("treffer") or r.get("angebot_treffer") or 0))
    return _jsonable({"datum": d.isoformat(), "maerkte": maerkte, "rezepte": out[:limit]})


# ---------- Plan & Einkauf ----------

async def wochenplan_setzen(eintraege: list[PlanEintrag], ersetzen: bool) -> dict:
    out = []
    tage = sorted({e.datum for e in eintraege})
    async with acquire() as con:
        if ersetzen and tage:
            paare = sorted({(e.datum, e.mahlzeit) for e in eintraege})
            for datum, mahlzeit in paare:
                await con.execute("DELETE FROM essensplan WHERE datum = $1 AND mahlzeit = $2",
                                  _date(datum), mahlzeit)
        for e in eintraege:
            if e.rezept_id is not None:
                if not await con.fetchval("SELECT 1 FROM rezepte WHERE id = $1", e.rezept_id):
                    out.append({"datum": e.datum, "mahlzeit": e.mahlzeit, "ok": False,
                                "fehler": f"Rezept {e.rezept_id} nicht gefunden"})
                    continue
            dub = await con.fetchval(
                "SELECT id FROM essensplan WHERE datum = $1 AND mahlzeit = $2 "
                "AND rezept_id IS NOT DISTINCT FROM $3 AND notiz IS NOT DISTINCT FROM $4",
                _date(e.datum), e.mahlzeit, e.rezept_id, e.notiz)
            if dub:
                out.append({"datum": e.datum, "mahlzeit": e.mahlzeit, "eintrag_id": dub, "ok": True, "neu": False})
                continue
            row = await services.add_plan_eintrag(_date(e.datum), e.mahlzeit, e.rezept_id, e.notiz,
                                                  e.person_ids, None, e.gaeste)
            out.append({"datum": e.datum, "mahlzeit": e.mahlzeit, "eintrag_id": row["id"], "ok": True, "neu": True})
    return {"eintraege": out, "neu": sum(1 for x in out if x.get("neu")),
            "fehler": sum(1 for x in out if x.get("ok") is False)}


async def plan_eintraege_loeschen(ids: list[int]) -> dict:
    async with acquire() as con:
        res = await con.fetch("DELETE FROM essensplan WHERE id = ANY($1::int[]) RETURNING id", list(ids))
    geloescht = sorted(r["id"] for r in res)
    return {"geloescht": geloescht, "nicht_gefunden": sorted(set(ids) - set(geloescht))}


async def einkauf_abhaken(posten: list[EinkaufPosten], extra_ids: list[int], in_vorrat: bool) -> dict:
    gebucht = None
    if posten and in_vorrat:
        vp = [VorratPosten(name=p.name, menge=p.menge, einheit=p.einheit, lagerort=p.lagerort, mhd=p.mhd,
                           sicherheit="sicher") for p in posten]
        gebucht = await vorrat_buchen(vp, vorschau=False)
    entfernt = []
    if extra_ids:
        async with acquire() as con:
            res = await con.fetch("DELETE FROM einkauf_extra WHERE id = ANY($1::int[]) RETURNING id", list(extra_ids))
        entfernt = sorted(r["id"] for r in res)
    return {"in_vorrat_gebucht": (gebucht or {}).get("gebucht", 0),
            "vorrat": (gebucht or {}).get("posten", []),
            "extras_entfernt": entfernt}


# ---------- Kochmodus ----------

async def kochmodus_holen(rezept_id: int, varianten: list[int] | None) -> dict:
    r = await services.get_rezept(rezept_id)
    if r is None:
        raise Fehler(f"Rezept {rezept_id} nicht gefunden.")
    sig, aktiv = guided._aktive_varianten(r, varianten)
    schritte = await guided.schritte_laden(r, varianten)
    basis = {"rezept_id": rezept_id, "name": r["name"], "portionen": r.get("portionen"), "signatur": sig,
             "varianten": varianten or [0] * len(r.get("zubereitung") or [])}
    if schritte:
        return _jsonable({**basis, "vorhanden": True, "schritte": schritte})
    return _jsonable({
        **basis, "vorhanden": False,
        "zubereitung_aktiv": aktiv,
        "anleitung": r.get("anleitung") if not aktiv else None,
        "zutaten": [{"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit")}
                    for z in r.get("zutaten") or []],
        "verfuegbare_varianten": [{"komponente": k.get("titel"),
                                   "varianten": [v.get("geraet") or "ohne Gerät" for v in k.get("varianten") or []]}
                                  for k in r.get("zubereitung") or []],
        "hinweis": ("Noch keine Schritte gespeichert: Zubereitung in einzelne Schritte zerlegen "
                    "(eine Handlung pro Schritt, Wartezeiten als dauer_minuten + timer=true, Zutaten mit "
                    "Mengen der Basis-Portionen) und mit kochmodus_speichern ablegen."),
    })


async def kochmodus_speichern(rezept_id: int, varianten: list[int] | None, schritte: list[Kochschritt]) -> dict:
    r = await services.get_rezept(rezept_id)
    if r is None:
        raise Fehler(f"Rezept {rezept_id} nicht gefunden.")
    daten = []
    for i, s in enumerate(sorted(schritte, key=lambda s: s.nr), 1):
        d = s.model_dump()
        d["nr"] = i
        d["timer"] = bool(d["timer"]) and d["dauer_minuten"] is not None
        daten.append(d)
    sig = await guided.schritte_speichern(r, varianten, daten, quelle="mcp")
    return {"rezept_id": rezept_id, "signatur": sig, "schritte": len(daten), "gespeichert": True}
