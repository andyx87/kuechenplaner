"""MCP-Server (FastMCP, Streamable HTTP unter /mcp) – Connector für Claude & Co.

Das Modell im Client (z. B. Claude) übernimmt Wahrnehmung und Sprache: Prospekte, Fotos
und Rezepttexte lesen, Rezepte schreiben, Schritte strukturieren. Der Server speichert
strukturierte Ergebnisse und rechnet (Zutaten-Abgleich, Einkaufsliste, Vorschläge).

Zugriff nur mit Token (OAuth 2.1 oder persönliches Zugriffstoken, s. app/oauth.py). Jeder
Aufruf läuft im Haushalt des Token-Inhabers unter Postgres-RLS (app/mcp_auth.py). Lesende
Werkzeuge brauchen Scope `read`, schreibende zusätzlich `write`.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from fastmcp.tools.base import ToolResult
from mcp_types import ImageContent, TextContent
from pydantic import Field

from . import bilder, ki, mcp_dienste as dienste, services
from .mcp_auth import HaushaltsKontext
from .schemas import (AngeboteImport, AngebotPosten, Datum, EinkaufPosten, GeraetIn, Gang, Kochschritt,
                      Kueche, PlanEintrag, RezeptIn, RezeptUpdate, VorratPosten)
from .userauth import current_account

INSTRUKTIONEN = """\
Topfplan: Küchen-Assistent für einen Haushalt – Rezepte, Vorrat, Küchengeräte, Wochenplan,
Einkaufsliste, Supermarkt-Angebote und Kochmodus. (Kitchen assistant for one household.)

Arbeitsteilung: DU liest Fotos, PDFs, Prospekte und Webseiten selbst und schickst nur
strukturierte Daten. Dateien kann man diesen Werkzeugen nicht übergeben. Der Server gleicht
Zutaten ab, rechnet Mengen, Einkaufsliste und Vorschläge.

Ablauf-Regeln:
- Zu Beginn haushalt_uebersicht aufrufen (Personen, Geräte, Lagerorte, Märkte).
- Massen-Schreibwerkzeuge (vorrat_buchen, angebote_importieren, rezepte_aktualisieren) zuerst mit
  vorschau=true aufrufen, das Ergebnis dem Nutzer zeigen, dann mit vorschau=false speichern.
- Bei Wiederholungsgefahr (Abbruch, Timeout) idempotenz_schluessel setzen: gleicher Schlüssel =
  kein doppelter Import.
- Zutatennamen generisch und ohne Marke ('Naturjoghurt', 'Hähnchenbrust').
- Rezept-Zubereitung in Komponenten mit je einer Variante pro geeignetem vorhandenen Gerät
  (exakte Gerätenamen aus haushalt_uebersicht, sonst geraet=null).
- Listen sind paginiert: naechster_cursor an das nächste Aufruf-Argument cursor übergeben.
- Daten (Datum) immer als YYYY-MM-DD; Zeitzone Europe/Berlin.
"""

mcp = FastMCP("Topfplan", instructions=INSTRUKTIONEN, middleware=[HaushaltsKontext()])

LESEN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
SCHREIBEN = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
SCHREIBEN_IDEMPOTENT = {**SCHREIBEN, "idempotentHint": True}
LOESCHEN = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}
WRITE = require_scopes("write")

Limit = Annotated[int, Field(ge=1, le=100, description="Einträge pro Seite (page size), max. 100")]
Cursor = Annotated[str | None, Field(description="naechster_cursor aus der vorigen Antwort (pagination cursor)")]
Vorschau = Annotated[bool, Field(description=(
    "true = nur prüfen und Abgleich zeigen, nichts speichern; false = speichern (true = dry run)"))]
Idem = Annotated[str | None, Field(max_length=120, description=(
    "Optionaler Idempotenz-Schlüssel: gleicher Schlüssel → Ergebnis des ersten Aufrufs, keine Doppelbuchung"))]


async def _ausfuehren(coro):
    try:
        return await coro
    except dienste.Fehler as e:
        raise ToolError(str(e)) from e
    except services.NichtGefunden as e:
        raise ToolError(str(e) or "Nicht gefunden oder kein Zugriff.") from e
    except ki.KiNichtKonfiguriert as e:
        raise ToolError("Diese Funktion braucht einen Bild-/KI-Anbieter, der auf diesem Server nicht "
                        "eingerichtet ist (KI_IMAGE_MODEL usw.). / Not configured on this server.") from e


# ---------------------------------------------------------------- Kontext

@mcp.tool(annotations=LESEN)
async def haushalt_uebersicht() -> dict:
    """Einstieg: Personen (Portionsfaktor, Allergien, Vorlieben), Küchengeräte (heute verfügbar?),
    Lagerorte, Einkaufstage dieser Woche, Märkte mit aktuellen Angeboten. Keine Eingabe.
    / Household overview; call first."""
    return await _ausfuehren(dienste.haushalt_uebersicht())


# ---------------------------------------------------------------- Angebote

@mcp.tool(annotations=LESEN)
async def angebote_schema() -> dict:
    """Erwartetes Format für angebote_importieren: JSON-Schema, Beispiel, Regeln, aktuelle Kategorien
    und bekannte Märkte. Vor dem ersten Prospekt-Import aufrufen. / Schema + categories for offer import."""
    return await _ausfuehren(dienste.angebote_schema())


@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def angebote_importieren(
    markt: Annotated[str, Field(min_length=1, max_length=80, description="Markt/Händler (store name)")],
    gueltig_von: Datum,
    gueltig_bis: Datum,
    angebote: Annotated[list[AngebotPosten], Field(min_length=1, max_length=500)],
    vorschau: Vorschau = True,
    idempotenz_schluessel: Idem = None,
) -> dict:
    """Angebote EINES Prospekts speichern, die du selbst aus Link/PDF/Foto gelesen hast: Markt,
    Gültigkeit und je Artikel name, preis (+ marke, menge, einheit, preis_normal, grundpreis,
    kategorie, art, master_zutat). Exakte Dubletten werden übersprungen. Erst vorschau=true.
    / Store offers you extracted from a flyer; dry-run first."""
    try:
        imp = AngeboteImport(markt=markt, gueltig_von=gueltig_von, gueltig_bis=gueltig_bis, angebote=angebote)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if vorschau:
        return await _ausfuehren(dienste.angebote_importieren(imp, True))
    return await _ausfuehren(dienste.idempotent(
        "angebote_importieren", idempotenz_schluessel, lambda: dienste.angebote_importieren(imp, False)))


@mcp.tool(annotations=LESEN)
async def angebote_holen(
    markt: Annotated[str | None, Field(description="Nur dieser Markt (store filter)")] = None,
    datum: Annotated[Datum | None, Field(description="Gültig an diesem Tag, Standard heute")] = None,
    art: Annotated[Literal["zutat", "fertiggericht", "non_food"] | None, Field()] = None,
    suche: Annotated[str | None, Field(max_length=80, description="Textsuche im Artikelnamen")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> dict:
    """Aktuelle Angebote (eigene und für alle freigegebene), filterbar nach Markt, Datum, Art,
    Text; paginiert. / Current offers, paginated."""
    return await _ausfuehren(dienste.angebote_holen(markt, datum, art, suche, limit, cursor))


@mcp.tool(annotations=LOESCHEN, auth=WRITE)
async def angebote_blatt_loeschen(
    markt: Annotated[str, Field(min_length=1, max_length=80)],
    gueltig_von: Datum,
    gueltig_bis: Datum,
) -> dict:
    """Löscht alle EIGENEN Angebote eines Markts für genau diesen Zeitraum (z. B. falscher Import).
    / Delete an imported flyer of this household."""
    return await _ausfuehren(dienste.angebote_blatt_loeschen(markt, gueltig_von, gueltig_bis))


# ---------------------------------------------------------------- Vorrat & Geräte

@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def vorrat_buchen(
    posten: Annotated[list[VorratPosten], Field(min_length=1, max_length=200)],
    vorschau: Vorschau = True,
    idempotenz_schluessel: Idem = None,
) -> dict:
    """Vorrat hinzufügen, z. B. was du auf einem Küchen-/Kühlschrankfoto erkannt hast: je Posten
    name (generisch), menge, einheit, optional lagerort und mhd. Der Server ordnet bekannten
    Zutaten zu (exakt/Umlaut/Plural) und meldet neue. Erst vorschau=true.
    / Add pantry items (e.g. recognised in a photo); dry-run shows ingredient matching."""
    if vorschau:
        return await _ausfuehren(dienste.vorrat_buchen(posten, True))
    return await _ausfuehren(dienste.idempotent(
        "vorrat_buchen", idempotenz_schluessel, lambda: dienste.vorrat_buchen(posten, False)))


@mcp.tool(annotations=LESEN)
async def vorrat_holen(
    lagerort: Annotated[str | None, Field(description="Nur dieser Lagerort")] = None,
    ablauf_in_tagen: Annotated[int | None, Field(ge=0, le=365, description=(
        "Nur Posten mit MHD innerhalb dieser Tage (inkl. abgelaufene)"))] = None,
    suche: Annotated[str | None, Field(max_length=80)] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> dict:
    """Vorratsposten mit vorrat_id, Menge, Einheit, MHD, Lagerort; filterbar, paginiert.
    / Pantry items, paginated."""
    return await _ausfuehren(dienste.vorrat_holen(lagerort, ablauf_in_tagen, suche, limit, cursor))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def vorrat_aendern(
    vorrat_id: Annotated[int, Field(ge=1, description="ID aus vorrat_holen")],
    menge: Annotated[float | None, Field(gt=0, le=100000)] = None,
    einheit: Annotated[str | None, Field(max_length=20)] = None,
    mhd: Annotated[Datum | None, Field()] = None,
    lagerort: Annotated[str | None, Field(max_length=60, description="Neuer Lagerort (wird ggf. angelegt)")] = None,
    mhd_entfernen: bool = False,
) -> dict:
    """Einen Vorratsposten ändern; nur übergebene Felder ändern sich. / Update one pantry item."""
    return await _ausfuehren(dienste.vorrat_aendern(vorrat_id, menge, einheit, mhd, lagerort, mhd_entfernen))


@mcp.tool(annotations=LOESCHEN, auth=WRITE)
async def vorrat_loeschen(
    vorrat_ids: Annotated[list[int], Field(min_length=1, max_length=200, description="IDs aus vorrat_holen")],
) -> dict:
    """Vorratsposten entfernen (aufgebraucht/weggeworfen). / Delete pantry items."""
    return await _ausfuehren(dienste.vorrat_loeschen(vorrat_ids))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def geraete_anlegen(
    geraete: Annotated[list[GeraetIn], Field(min_length=1, max_length=50)],
) -> dict:
    """Küchengeräte anlegen, z. B. aus einem Küchenfoto: je Gerät name (+ typ, standard). Vorhandene
    Namen werden nicht doppelt angelegt. / Create kitchen appliances (idempotent by name)."""
    return await _ausfuehren(dienste.geraete_anlegen(geraete))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def geraete_heute_setzen(
    geraet_ids: Annotated[list[int], Field(max_length=50, description="IDs aus haushalt_uebersicht.geraete")],
) -> dict:
    """Welche Geräte heute verfügbar sind (ersetzt die Tagesauswahl). / Set today's appliances."""
    rows = await _ausfuehren(services.set_geraete_heute(geraet_ids))
    return {"heute": [{"id": g["id"], "name": g["name"]} for g in rows]}


# ---------------------------------------------------------------- Rezepte

@mcp.tool(annotations=LESEN)
async def rezepte_suchen(
    query: Annotated[str | None, Field(max_length=120, description="Text in Name/Beschreibung")] = None,
    gang: Gang | None = None,
    kueche: Kueche | None = None,
    zutaten: Annotated[list[str] | None, Field(max_length=10, description="Alle diese Zutaten müssen vorkommen")] = None,
    markt: Annotated[str | None, Field(description="Nur Rezepte mit Angebotszutaten dieses Markts")] = None,
    nur_eigene: bool = False,
    limit: Limit = 20,
    cursor: Cursor = None,
) -> dict:
    """Rezepte suchen (eigene und veröffentlichte) mit fehlenden Zutaten laut Vorrat, Bewertung,
    'geraete_abgestimmt'. Paginiert. / Search recipes, paginated."""
    return await _ausfuehren(dienste.rezepte_suchen(query, gang, kueche, zutaten, markt, nur_eigene, limit, cursor))


@mcp.tool(annotations=LESEN)
async def rezept_holen(rezept_id: Annotated[int, Field(ge=1)]) -> dict:
    """Ein Rezept vollständig: Zutaten, Zubereitung (Komponenten/Varianten), Geräte, Bewertung.
    Ohne Bilddaten. / Full recipe."""
    r = await _ausfuehren(services.get_rezept(rezept_id))
    if r is None:
        raise ToolError(f"Rezept {rezept_id} nicht gefunden.")
    r.pop("bild", None)
    r.pop("zubereitung_guided", None)
    r["eigenes"] = r.get("account_id") == current_account.get()
    return r


@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def rezept_anlegen(rezept: RezeptIn, idempotenz_schluessel: Idem = None) -> dict:
    """Neues Rezept speichern: name, portionen, zutaten[] (generisch, mit menge/einheit) und
    zubereitung[] als Komponenten mit Geräte-Varianten. Deckt die Zubereitung alle Geräte ab,
    gilt das Rezept als 'auf die Küche abgestimmt'. / Create a structured recipe."""
    return await _ausfuehren(dienste.idempotent(
        "rezept_anlegen", idempotenz_schluessel, lambda: dienste.rezept_anlegen(rezept)))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def rezept_aendern(rezept: RezeptUpdate) -> dict:
    """Ein EIGENES Rezept ändern: rezept_id + nur die zu ändernden Felder. zutaten bzw. zubereitung
    ersetzen die jeweilige Liste komplett. / Partially update one own recipe."""
    res = await _ausfuehren(dienste.rezepte_aktualisieren([rezept], vorschau=False))
    e = res["ergebnisse"][0]
    if e.get("ok") is False:
        raise ToolError(e["fehler"])
    return e


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def rezepte_aktualisieren(
    rezepte: Annotated[list[RezeptUpdate], Field(min_length=1, max_length=25)],
    vorschau: Vorschau = True,
) -> dict:
    """Mehrere eigene Rezepte auf einmal aktualisieren ('alle Rezepte aktualisieren'): je Rezept
    rezept_id + geänderte Felder, typischerweise die vollständige neue zubereitung. Die Liste der
    anzupassenden Rezepte liefert rezepte_anpassungsbedarf. Erst vorschau=true.
    / Batch-update own recipes; dry-run first."""
    return await _ausfuehren(dienste.rezepte_aktualisieren(rezepte, vorschau))


@mcp.tool(annotations=LESEN)
async def rezepte_anpassungsbedarf(limit: Annotated[int, Field(ge=1, le=20)] = 10, cursor: Cursor = None) -> dict:
    """Eigene Rezepte, deren Zubereitung noch nicht zu den aktuellen Geräten passt, mit Zutaten und
    Zubereitung zum Überarbeiten (max. 20 je Seite). Danach rezepte_aktualisieren.
    / Own recipes needing adaptation to current appliances."""
    return await _ausfuehren(dienste.rezepte_anpassungsbedarf(limit, cursor))


@mcp.tool(annotations=LOESCHEN, auth=WRITE)
async def rezept_loeschen(rezept_id: Annotated[int, Field(ge=1)]) -> dict:
    """Ein EIGENES Rezept löschen. / Delete one own recipe."""
    return await _ausfuehren(services.delete_rezept(rezept_id))


@mcp.tool(annotations=LESEN)
async def rezepte_vorschlagen(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict:
    """Vorschläge aus vorhandenen Rezepten, die mit den HEUTE verfügbaren Geräten gehen, sortiert
    nach wenigsten fehlenden Zutaten im Vorrat. / Suggestions by pantry + today's appliances."""
    return {"vorschlaege": await _ausfuehren(services.rezepte_vorschlagen(limit))}


@mcp.tool(annotations=LESEN)
async def rezepte_aus_angeboten(
    markt: Annotated[str | None, Field(description="Markt; leer = alle Märkte mit aktuellen Angeboten")] = None,
    datum: Annotated[Datum | None, Field()] = None,
    limit: Annotated[int, Field(ge=1, le=30)] = 8,
) -> dict:
    """Rezepte, die möglichst viele aktuelle Angebotsartikel nutzen (Server-Abgleich über
    Master-Zutaten). / Recipes matching current offers."""
    return await _ausfuehren(dienste.rezepte_aus_angeboten(markt, datum, limit))


@mcp.tool(annotations=LESEN)
async def rezept_vorrat_check(rezept_id: Annotated[int, Field(ge=1)]) -> dict:
    """Welche Zutaten eines Rezepts im Vorrat reichen und welche fehlen. / Pantry check for a recipe."""
    r = await _ausfuehren(services.check_vorrat_fuer_rezept(rezept_id))
    if r is None:
        raise ToolError(f"Rezept {rezept_id} nicht gefunden.")
    return r


# ---------------------------------------------------------------- Plan & Einkauf

@mcp.tool(annotations=LESEN)
async def wochenplan_holen(datum: Annotated[Datum, Field(description="Ein Tag der gewünschten Woche")]) -> dict:
    """Alle geplanten Mahlzeiten der Woche (Mo–So), mit eintrag_id und Rezept. / Weekly meal plan."""
    return {"eintraege": await _ausfuehren(services.list_wochenplan(services._date(datum)))}


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def wochenplan_setzen(
    eintraege: Annotated[list[PlanEintrag], Field(min_length=1, max_length=60)],
    ersetzen: Annotated[bool, Field(description=(
        "true = vorhandene Einträge an denselben Tag+Mahlzeit vorher entfernen"))] = False,
) -> dict:
    """Mahlzeiten einplanen: je Eintrag datum, mahlzeit, rezept_id (oder notiz), optional person_ids,
    gaeste. Gleiche Einträge werden nicht doppelt angelegt. / Plan meals (batch, idempotent)."""
    return await _ausfuehren(dienste.wochenplan_setzen(eintraege, ersetzen))


@mcp.tool(annotations=LOESCHEN, auth=WRITE)
async def plan_eintraege_loeschen(eintrag_ids: Annotated[list[int], Field(min_length=1, max_length=60)]) -> dict:
    """Plan-Einträge löschen (IDs aus wochenplan_holen). / Delete plan entries."""
    return await _ausfuehren(dienste.plan_eintraege_loeschen(eintrag_ids))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def einkaufstag_setzen(
    datum: Datum,
    aktiv: bool = True,
    maerkte: Annotated[list[str] | None, Field(max_length=5, description="Märkte für diesen Einkauf")] = None,
) -> dict:
    """Einkaufstag setzen oder entfernen (idempotent, kein Umschalten), optional mit Märkten.
    / Set or clear a shopping day."""
    d = services._date(datum)
    tage = {e["datum"] for e in await _ausfuehren(services.list_einkaufstage(d))}
    if (datum in tage) != aktiv:
        await _ausfuehren(services.toggle_einkaufstag(d))
    if aktiv and maerkte is not None:
        await _ausfuehren(services.set_einkaufstag_haendler(d, maerkte))
    return {"datum": datum, "aktiv": aktiv, "maerkte": maerkte}


@mcp.tool(annotations=LESEN)
async def einkaufsliste_erzeugen(datum: Annotated[Datum, Field(description="Ein Tag der Woche")]) -> dict:
    """Berechnet die Einkaufsliste aus Wochenplan minus Vorrat, aufgeteilt nach Einkaufstagen, mit
    passenden Angeboten; plus manuelle Artikel. / Compute shopping list."""
    return await _ausfuehren(services.get_einkaufsliste(services._date(datum)))


@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def einkauf_extra_hinzufuegen(
    artikel: Annotated[list[EinkaufPosten], Field(min_length=1, max_length=100)],
) -> dict:
    """Manuelle Artikel auf die Einkaufsliste setzen (name, menge, einheit). / Add manual items."""
    rows = await _ausfuehren(services.add_einkauf_extra(
        [{"name": a.name, "menge": a.menge, "einheit": a.einheit} for a in artikel]))
    return {"hinzugefuegt": [{"extra_id": r["id"], "name": r["name"]} for r in rows]}


@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def einkauf_abhaken(
    gekauft: Annotated[list[EinkaufPosten] | None, Field(max_length=200, description=(
        "Gekaufte Positionen mit tatsächlicher Menge – werden in den Vorrat gebucht"))] = None,
    extra_ids: Annotated[list[int] | None, Field(max_length=200, description=(
        "Manuelle Artikel (extra_id aus der Einkaufsliste), die erledigt sind"))] = None,
    in_vorrat: bool = True,
    idempotenz_schluessel: Idem = None,
) -> dict:
    """Einkauf erledigt: gekaufte Positionen in den Vorrat buchen und erledigte manuelle Artikel
    entfernen. Danach rechnet die Einkaufsliste mit dem neuen Vorrat. / Check off shopping."""
    gekauft, extra_ids = gekauft or [], extra_ids or []
    if not gekauft and not extra_ids:
        raise ToolError("Nichts übergeben: gekauft oder extra_ids angeben.")
    return await _ausfuehren(dienste.idempotent(
        "einkauf_abhaken", idempotenz_schluessel, lambda: dienste.einkauf_abhaken(gekauft, extra_ids, in_vorrat)))


# ---------------------------------------------------------------- Kochmodus

Varianten = Annotated[list[int] | None, Field(max_length=20, description=(
    "Gewählter Varianten-Index je Komponente (0-basiert, Reihenfolge wie in rezept_holen.zubereitung); "
    "leer = jeweils erste Variante"))]


@mcp.tool(annotations=LESEN)
async def kochmodus_holen(rezept_id: Annotated[int, Field(ge=1)], varianten: Varianten = None) -> dict:
    """Schritte für den Kochmodus der Web-App (Timer, Vorlesen). Fehlen sie, kommt die aktive
    Zubereitung zurück, damit du Schritte strukturierst und mit kochmodus_speichern ablegst.
    / Cooking-mode steps, or the source text to structure."""
    return await _ausfuehren(dienste.kochmodus_holen(rezept_id, varianten))


@mcp.tool(annotations=SCHREIBEN_IDEMPOTENT, auth=WRITE)
async def kochmodus_speichern(
    rezept_id: Annotated[int, Field(ge=1)],
    schritte: Annotated[list[Kochschritt], Field(min_length=1, max_length=80)],
    varianten: Varianten = None,
) -> dict:
    """Strukturierte Kochschritte für ein Rezept speichern (nur für diesen Haushalt): je Schritt nr,
    text, optional komponente, dauer_minuten+timer, geraete, zutaten. / Save cooking steps."""
    return await _ausfuehren(dienste.kochmodus_speichern(rezept_id, varianten, schritte))


# ---------------------------------------------------------------- Bild

@mcp.tool(annotations=SCHREIBEN, auth=WRITE)
async def rezeptbild_erzeugen(
    rezept_id: Annotated[int, Field(ge=1)],
    ueberschreiben: Annotated[bool, Field(description="Vorhandenes Bild ersetzen")] = False,
) -> ToolResult:
    """Erzeugt ein Foto für ein EIGENES Rezept über den Bild-Anbieter dieses Servers (verursacht dort
    Kosten) und speichert es. Nur verfügbar, wenn der Server einen Bild-Anbieter hat.
    / Generate a recipe photo with the server's image provider."""
    if not ki.verfuegbar("bild"):
        raise ToolError("Auf diesem Server ist kein Bild-Anbieter eingerichtet (KI_IMAGE_MODEL). "
                        "/ No image provider configured on this server.")
    r = await _ausfuehren(services.get_rezept(rezept_id))
    if r is None or r.get("account_id") != current_account.get():
        raise ToolError("Nur für eigene Rezepte möglich (Rezept nicht gefunden oder fremd).")
    if r.get("hat_bild") and not ueberschreiben:
        raise ToolError("Das Rezept hat schon ein Bild. Mit ueberschreiben=true ersetzen.")
    data_url = await _ausfuehren(bilder.generiere_rezeptbild(r["name"], r.get("beschreibung"), r.get("zutaten")))
    if not data_url:
        raise ToolError("Der Bild-Anbieter hat kein Bild geliefert. Bitte später erneut versuchen.")
    await _ausfuehren(services.set_rezept_bild(rezept_id, data_url))
    vorschau = _thumbnail(data_url)
    info = {"rezept_id": rezept_id, "gespeichert": True}
    inhalt = [TextContent(type="text", text=f"Bild für '{r['name']}' gespeichert.")]
    if vorschau:
        inhalt.append(ImageContent(type="image", data=vorschau, mime_type="image/jpeg"))
    return ToolResult(content=inhalt, structured_content=info)


def _thumbnail(data_url: str) -> str | None:
    try:
        import io

        from PIL import Image
        raw = base64.b64decode(data_url.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((384, 384))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=75)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------- Prompts (fertige Abläufe)

@mcp.prompt
def prospekt_importieren(markt: str = "", link: str = "") -> str:
    """Prospekt (Link oder hochgeladenes PDF) in Topfplan übernehmen."""
    return (f"Lies den Prospekt{' ' + link if link else ''}{' von ' + markt if markt else ''} vollständig "
            "(alle Seiten). Rufe angebote_schema auf, extrahiere jedes Angebot mit Name, Marke, Packungsgröße, "
            "Preis, Streichpreis, Grundpreis, Kategorie, Art und generischer master_zutat. Rufe "
            "angebote_importieren mit vorschau=true auf, zeige mir eine kurze Übersicht und speichere nach "
            "meiner Bestätigung mit vorschau=false.")


@mcp.prompt
def vorrat_aus_foto() -> str:
    """Vorrat aus einem Foto von Kühlschrank/Vorratsschrank erfassen."""
    return ("Erkenne auf meinem Foto alle Lebensmittel mit geschätzter Menge und Einheit, generischem Namen "
            "und passendem Lagerort (haushalt_uebersicht). Rufe vorrat_buchen mit vorschau=true auf, zeige "
            "mir die Zuordnung (neu/erkannt) und buche nach meiner Bestätigung mit vorschau=false.")


@mcp.prompt
def wochenplan_erstellen() -> str:
    """Wochenplan mit Einkaufsliste erstellen."""
    return ("Hole haushalt_uebersicht, wochenplan_holen (heute), rezepte_aus_angeboten und rezepte_vorschlagen. "
            "Schlage mir einen Plan für die Woche vor (Allergien und Vorlieben beachten). Nach meiner Bestätigung "
            "wochenplan_setzen und danach einkaufsliste_erzeugen und die Liste kompakt zeigen.")


@mcp.prompt
def rezepte_an_geraete_anpassen() -> str:
    """Alle Rezepte an die vorhandenen Küchengeräte anpassen."""
    return ("Rufe rezepte_anpassungsbedarf auf. Ergänze für jedes Rezept je geräteabhängiger Komponente eine "
            "Variante pro Gerät aus 'geraete' (vorhandene Texte wörtlich übernehmen). Prüfe mit "
            "rezepte_aktualisieren vorschau=true, speichere mit vorschau=false und wiederhole, bis offen_gesamt 0 ist.")


@mcp.prompt
def kochmodus_vorbereiten(rezept_id: str) -> str:
    """Kochmodus-Schritte für ein Rezept vorbereiten."""
    return (f"Rufe kochmodus_holen für Rezept {rezept_id} auf. Wenn keine Schritte vorhanden sind, zerlege die "
            "Zubereitung in einzelne Schritte (eine Handlung je Schritt, Wartezeiten als dauer_minuten mit "
            "timer=true, Zutaten mit Mengen) und speichere sie mit kochmodus_speichern.")
