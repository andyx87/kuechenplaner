"""MCP-Server (FastMCP, Streamable HTTP) fuer die KI-Anbindung.

Exponiert dieselben Operationen wie die REST-API als MCP-Tools.
Wird in main.py unter /mcp gemountet.
"""
from __future__ import annotations

from fastmcp import FastMCP

from . import services

INSTRUKTIONEN = """\
Küchen-Assistent: verwaltet Rezepte, Küchengeräte, Vorrat, Tagesauswahl und Wochenplanung.

WICHTIG beim Anlegen/Ändern von Rezepten (rezept_anlegen / rezept_aktualisieren):
- Gliedere die Zubereitung im Feld `zubereitung` in Komponenten (z.B. "Reis", "Hähnchen", "Sauce", "Anrichten").
- Rufe zuerst `geraete_liste` auf, um ALLE vorhandenen Küchengeräte zu kennen.
- Hinterlege für jede Komponente, die sich auf mehreren Geräten zubereiten lässt, je eine eigene Variante
  PRO geeignetem vorhandenem Gerät – jeweils mit vollständigem, eigenständigem Zubereitungstext
  (Mengen, Zeiten, Temperaturen/Stufen passend zum jeweiligen Gerät). Beispiel "Reis": je eine Variante für
  Reiskocher, Herd (Topf) und Thermomix, sofern diese Geräte vorhanden sind.
- Nutze als `geraet` ausschließlich Namen aus `geraete_liste`; erfinde keine Geräte. Geräte, auf denen die
  Komponente nicht sinnvoll zubereitbar ist, lässt du weg.
- Komponenten ohne Gerätebezug (z.B. "Anrichten") bekommen eine Variante mit geraet=null.
- `zubereitung` ersetzt bei Updates die bisherige Struktur vollständig – gib daher stets alle Komponenten und
  Varianten komplett mit, nicht nur die Änderung.

WOCHENPLANUNG (plan_*-Tools):
- `einkaufstage_holen` zeigt, wann in der Woche eingekauft wird – relevant für Vorschläge und Einkaufsliste.
- `wochenplan_holen` gibt alle geplanten Mahlzeiten (Frühstück/Mittag/Abendessen/Snack/Unterwegs) für eine Woche.
- `einkaufsliste_holen` berechnet die Einkaufsliste, aufgeteilt nach Einkaufstagen und Pantry-Abgleich.
- `plan_eintrag_anlegen` plant eine Mahlzeit; person_ids aus `personen_liste`; datum als YYYY-MM-DD.
- Beim Erstellen eines Wochenplans: zuerst einkaufstage_holen + wochenplan_holen + personen_liste + vorrat_holen,
  dann passende Rezepte (rezepte_vorschlagen oder rezepte_suchen) auswählen und einplanen.

Tageslogik (Alltags-/situative Geräte, Tagesauswahl) gilt in der Zeitzone Europe/Berlin.
"""

mcp = FastMCP("Koch-Assistent", instructions=INSTRUKTIONEN)


@mcp.tool
async def geraete_liste() -> list:
    """Listet alle vorhandenen Kuechengeraete (id, name, typ)."""
    return await services.list_geraete()


@mcp.tool
async def geraete_heute_holen() -> list:
    """Gibt die heute zur Nutzung ausgewaehlten Geraete zurueck."""
    return await services.get_geraete_heute()


@mcp.tool
async def geraete_heute_setzen(geraet_ids: list[int]) -> list:
    """Setzt die heute genutzten Geraete (ueberschreibt die bestehende Auswahl)."""
    return await services.set_geraete_heute(geraet_ids)


@mcp.tool
async def geraet_aktualisieren(geraet_id: int, name: str | None = None, typ: str | None = None,
                               standard: bool | None = None) -> dict | None:
    """Aendert ein Geraet. standard=true (Alltag) vs. false (situativ, z.B. Grill)."""
    return await services.update_geraet(geraet_id, name, typ, None, standard)


@mcp.tool
async def geraet_loeschen(geraet_id: int) -> dict:
    """Loescht ein Geraet (inkl. Verknuepfungen zu Rezepten und Tagesauswahl)."""
    return await services.delete_geraet(geraet_id)


@mcp.tool
async def personen_liste() -> list:
    """Listet alle Haushalts-Personen (Esser) mit Rolle, kcal-Ziel, Makro-Profil (Eiweiss/Fett/KH %)
    und Portionsfaktor. Basis fuer Mengen-/Budgetplanung."""
    return await services.list_personen()


@mcp.tool
async def person_anlegen(name: str, rolle: str = "erwachsener", kcal_ziel: int | None = None,
                         eiweiss_pct: int = 30, fett_pct: int = 30, kh_pct: int = 40,
                         portionsfaktor: float = 1.0,
                         ernaehrung: str = "", allergien: str = "",
                         mag_nicht: str = "", mag_gern: str = "") -> dict:
    """Legt eine Person an. rolle: 'erwachsener' oder 'kind'. Makros in % (Summe ~100).
    portionsfaktor: relativer Portionsanteil (Kinder z.B. 0.5). kcal_ziel: Standard-Tagesbudget.
    Praeferenzen (Freitext, kommagetrennt): ernaehrung (z.B. 'vegetarisch'),
    allergien (hart ausgeschlossen), mag_nicht (Abneigungen), mag_gern (Vorlieben)."""
    return await services.add_person(name, rolle, kcal_ziel, eiweiss_pct, fett_pct, kh_pct,
                                     portionsfaktor, True, ernaehrung, allergien, mag_nicht, mag_gern)


@mcp.tool
async def person_aktualisieren(person_id: int, name: str, rolle: str = "erwachsener",
                               kcal_ziel: int | None = None, eiweiss_pct: int = 30,
                               fett_pct: int = 30, kh_pct: int = 40,
                               portionsfaktor: float = 1.0, aktiv: bool = True,
                               ernaehrung: str | None = None, allergien: str | None = None,
                               mag_nicht: str | None = None, mag_gern: str | None = None) -> dict | None:
    """Aktualisiert eine Person (ersetzt ALLE Standardfelder – immer den kompletten Satz mitgeben).
    Praeferenzfelder (ernaehrung/allergien/mag_nicht/mag_gern) nur mitgeben, wenn sie geaendert
    werden sollen; None laesst den bestehenden Wert unveraendert. Werte sind Freitext, kommagetrennt."""
    return await services.update_person(person_id, name, rolle, kcal_ziel, eiweiss_pct,
                                        fett_pct, kh_pct, portionsfaktor, aktiv,
                                        ernaehrung, allergien, mag_nicht, mag_gern)


@mcp.tool
async def person_loeschen(person_id: int) -> dict:
    """Loescht eine Person."""
    return await services.delete_person(person_id)


@mcp.tool
async def lagerorte_liste() -> list:
    """Listet alle Lagerorte (Kuehlschrank, Tiefkuehler, Vorratsschrank, ...)."""
    return await services.list_lagerorte()


@mcp.tool
async def zutaten_liste() -> list:
    """Listet alle bekannten Zutaten (mit Flag 'grundzutat': immer-vorhanden,
    nie auf der Einkaufsliste). Nuetzlich um zutat_id und Grundzutat-Status zu finden."""
    return await services.list_zutaten()


@mcp.tool
async def zutat_grundzutat_setzen(zutat_id: int, grundzutat: bool = True) -> dict:
    """Markiert eine Zutat als Grundzutat (immer vorhanden) oder hebt das auf.
    Grundzutaten (z.B. Wasser, Salz, Gewuerze, Oel) kommen nie auf die Einkaufsliste
    und gelten im Rezept-Vorrat-Check nicht als fehlend. zutat_id aus zutaten_liste."""
    return await services.set_grundzutat(zutat_id, grundzutat)


@mcp.tool
async def zutat_anlegen(name: str, standard_einheit: str | None = None,
                        kategorie: str | None = None, grundzutat: bool = False,
                        gebinde_menge: float | None = None,
                        gebinde_einheit: str | None = None,
                        kanonische_zutat_id: int | None = None) -> dict:
    """Legt eine neue Zutat an. OHNE kanonische_zutat_id entsteht eine generische
    MASTER-Zutat (z.B. 'Lachs', 'Champignons', 'Gewuerzgurken') - genau die Ziele,
    denen man anschliessend Marken-/Vorratsartikel via zutat_kanonisch_zuordnen
    unterordnet. MIT kanonische_zutat_id wird die neue Zutat direkt diesem Master
    untergeordnet. Existiert der Name schon (case-insensitive), wird die bestehende
    Zutat unveraendert zurueckgegeben (kein Duplikat). Gibt die Zutat inkl. id zurueck.

    Parameter:
    - standard_einheit: Basiseinheit (g, ml, Stück, Dose, Packung, Glas, EL, ...).
    - grundzutat=True: gilt als immer vorhanden (nie fehlend, nie auf Einkaufsliste);
      fuer Salz/Pfeffer/Oel/Gewuerze.
    - gebinde_menge/-einheit: 1 standard_einheit = gebinde_menge gebinde_einheit
      (z.B. 1 Dose = 195 g), damit Dosen/Packungen gegen g/ml-Rezepte zaehlen.

    VORGEHEN: zuerst zutaten_master_liste pruefen, ob ein passender Master bereits
    existiert; nur wenn nicht, hier neu anlegen (vermeidet Dubletten)."""
    return await services.create_zutat(
        name, standard_einheit, kategorie, grundzutat,
        gebinde_menge, gebinde_einheit, kanonische_zutat_id,
    )


@mcp.tool
async def zutaten_master_liste() -> list:
    """Alle Master-Zutaten (kanonische_zutat_id IS NULL) mit Flag 'rezept_zutat'.
    Das sind die Ziel-Kandidaten, denen Vorratsartikel zugeordnet werden koennen."""
    return await services.list_master_zutaten()


@mcp.tool
async def zutaten_unmapped_liste() -> list:
    """Vorratsartikel, die noch keinem Master zugeordnet sind und in keinem Rezept
    vorkommen (fixierte ausgenommen) - die Kandidaten fuer die KI-Zuordnung.
    Vorgehen: diese Liste + zutaten_master_liste holen, passende Paare bilden,
    dann je zutat_kanonisch_zuordnen aufrufen. Nur zuordnen, wenn es klar passt
    (z.B. 'Bertolli Olivenoel' -> Master 'Olivenoel'); im Zweifel offen lassen."""
    return await services.list_unmapped_zutaten()


@mcp.tool
async def zutaten_unbestaetigt_liste() -> list:
    """Kanonik-Zuordnungen, die noch auf User-Bestaetigung warten (Vorschlaege der
    automatischen KI-Zuordnung: kanonische_zutat_id gesetzt, aber nicht fixiert).
    Pro Eintrag: zutat_id/name + master_id/master_name. Dem User vorlegen; dann
    bestaetigen via zutat_kanonisch_zuordnen(fixiert=true) oder ablehnen via
    zutat_kanonisch_zuordnen(master_zutat_id=None)."""
    return await services.list_unbestaetigte_zuordnungen()


@mcp.tool
async def zutat_kanonisch_zuordnen(zutat_id: int, master_zutat_id: int | None = None,
                                   fixiert: bool = False) -> dict:
    """Ordnet eine Zutat einer Master-Zutat zu (Markenartikel -> generische Zutat).
    master_zutat_id=None hebt die Zuordnung auf (Zutat wird eigenstaendiger Master).
    Das Ziel muss selbst Master sein. fixiert=True schuetzt manuelle Zuordnungen
    vor der automatischen KI-Zuordnung. IDs aus zutaten_unmapped_liste/zutaten_master_liste."""
    return await services.set_kanonische_zutat(zutat_id, master_zutat_id, fixiert)


@mcp.tool
async def zutat_gebinde_setzen(zutat_id: int, gebinde_menge: float | None = None,
                               gebinde_einheit: str | None = None) -> dict:
    """Setzt die Gebinde-Groesse einer Zutat: 1 standard_einheit = gebinde_menge
    gebinde_einheit (z.B. 1 Packung = 250 g, 1 Dose = 400 ml). Damit rechnet das
    Matching Vorrat in Packungen/Dosen auf die Rezept-Basiseinheit (g/ml) um.
    Beide Werte leer lassen loescht die Gebinde-Groesse. zutat_id aus zutaten_liste."""
    return await services.set_gebinde(zutat_id, gebinde_menge, gebinde_einheit)


@mcp.tool
async def zutat_umbenennen(zutat_id: int, name: str) -> dict:
    """Benennt eine Zutat um (z.B. eine Master-Zutat)."""
    return await services.rename_zutat(zutat_id, name)


@mcp.tool
async def zutat_loeschen(zutat_id: int) -> dict:
    """Loescht eine Zutat. Verweigert, wenn sie in einem Rezept verwendet wird oder
    noch im Vorrat liegt. Zutaten, die sie als Master hatten, werden eigenstaendig."""
    return await services.delete_zutat(zutat_id)


@mcp.tool
async def lagerort_anlegen(name: str, sortierung: int = 0) -> dict:
    """Legt einen Lagerort an (oder passt die Sortierung bei gleichem Namen an)."""
    return await services.add_lagerort(name, sortierung)


@mcp.tool
async def lagerort_aktualisieren(lagerort_id: int, name: str, sortierung: int = 0) -> dict | None:
    """Aktualisiert einen Lagerort (Name/Sortierung)."""
    return await services.update_lagerort(lagerort_id, name, sortierung)


@mcp.tool
async def lagerort_loeschen(lagerort_id: int) -> dict:
    """Loescht einen Lagerort; betroffene Vorratseintraege verlieren nur die Ortszuordnung."""
    return await services.delete_lagerort(lagerort_id)


@mcp.tool
async def vorrat_holen() -> list:
    """Aktueller Vorrat, aggregiert pro Zutat (mit Gesamtmenge und naechstem Ablaufdatum)."""
    return await services.vorrat_aggregiert()


@mcp.tool
async def vorrat_hinzufuegen(name: str, menge: float, einheit: str,
                             ablaufdatum: str | None = None, ort: str | None = None) -> dict:
    """Fuegt eine Position zum Vorrat hinzu. ablaufdatum als YYYY-MM-DD.
    ort = Lagerort-Name (z.B. 'Kuehlschrank'); wird angelegt, falls noch nicht vorhanden."""
    res = await services.add_vorrat([{
        "name": name, "menge": menge, "einheit": einheit,
        "ablaufdatum": ablaufdatum, "ort": ort,
    }])
    return res[0]


@mcp.tool
async def vorrat_reduzieren(zutat_id: int, menge: float, einheit: str) -> dict:
    """Reduziert eine Zutat im Vorrat (FIFO nach Ablaufdatum). Gibt nicht gedeckte Restmenge zurueck."""
    return await services.reduce_vorrat(zutat_id, menge, einheit)


@mcp.tool
async def rezepte_suchen(query: str | None = None) -> list:
    """Sucht Rezepte nach Name/Beschreibung. Ohne query: alle Rezepte."""
    return await services.search_rezepte(query)


@mcp.tool
async def rezept_holen(rezept_id: int) -> dict | None:
    """Holt ein Rezept inkl. Zutaten (mit Mengen) und benoetigter Geraete."""
    return await services.get_rezept(rezept_id)


@mcp.tool
async def rezept_anlegen(name: str, beschreibung: str | None = None, anleitung: str | None = None,
                         portionen: int = 2, dauer_minuten: int | None = None,
                         quelle: str | None = None,
                         zutaten: list[dict] | None = None,
                         geraete: list[dict] | None = None,
                         zubereitung: list | None = None) -> dict:
    """Legt ein Rezept an.
    zutaten: [{name, menge, einheit, optional}]; geraete: [{name|geraet_id, pflicht}];
    zubereitung: geordnete Komponenten mit Geraete-Varianten, z.B.
    [{titel:"Reis", varianten:[{geraet:"Reiskocher", text:"..."}, {geraet:"Herd", text:"..."}]},
     {titel:"Anrichten", varianten:[{geraet:null, text:"..."}]}].
    geraet ist der Geraetename (aus geraete_liste) oder null (= ohne Geraet, gilt immer).
    WICHTIG: Vorher geraete_liste aufrufen und fuer jede Komponente eine Variante pro geeignetem
    vorhandenem Geraet anlegen, damit alle Zubereitungswege abgedeckt sind."""
    return await services.add_rezept(
        name, beschreibung, anleitung, portionen, dauer_minuten, quelle, zutaten, geraete, zubereitung
    )


@mcp.tool
async def rezept_aktualisieren(rezept_id: int, name: str, beschreibung: str | None = None,
                               anleitung: str | None = None, portionen: int = 2,
                               dauer_minuten: int | None = None, quelle: str | None = None,
                               zutaten: list[dict] | None = None,
                               geraete: list[dict] | None = None,
                               zubereitung: list | None = None) -> dict | None:
    """Aktualisiert ein Rezept (ersetzt Zutaten, Geraete und Zubereitung vollstaendig).
    zutaten: [{name, menge, einheit, optional}]; geraete: [{name|geraet_id, pflicht}];
    zubereitung: [{titel, varianten:[{geraet, text}]}] (geraet=Name aus geraete_liste oder null).
    WICHTIG: Vorher geraete_liste aufrufen und fuer jede Komponente eine Variante pro geeignetem
    vorhandenem Geraet hinterlegen. Da zubereitung vollstaendig ersetzt wird, immer ALLE Komponenten
    und Varianten mitgeben (auch unveraenderte)."""
    return await services.update_rezept(
        rezept_id, name, beschreibung, anleitung, portionen, dauer_minuten, quelle,
        zutaten, geraete, zubereitung
    )


@mcp.tool
async def rezept_loeschen(rezept_id: int) -> dict:
    """Loescht ein Rezept (inkl. seiner Zutaten- und Geraete-Verknuepfungen)."""
    return await services.delete_rezept(rezept_id)


@mcp.tool
async def rezepte_vorschlagen(limit: int = 10) -> list:
    """Schlaegt Rezepte vor: passend zu den heute gewaehlten Geraeten,
    sortiert nach Vorratsdeckung (wenigste fehlende Zutaten zuerst)."""
    return await services.rezepte_vorschlagen(limit)


@mcp.tool
async def kochen_vorschau(rezept_id: int) -> dict | None:
    """Zeigt, welche Zutaten beim Kochen aus dem Vorrat abgezogen wuerden (ohne sie abzuziehen)."""
    return await services.kochen_vorschau(rezept_id)


@mcp.tool
async def kochen_bestaetigen(rezept_id: int, faktor: float = 1.0) -> dict | None:
    """Zieht die Rezeptzutaten aus dem Vorrat ab. faktor skaliert die Portionen (z.B. 2.0 = doppelt)."""
    return await services.kochen_bestaetigen(rezept_id, faktor)


# ---------- Wochenplaner ----------

@mcp.tool
async def einkaufstage_holen(datum: str) -> list:
    """Gibt die Einkaufstage der Woche zurueck, die das angegebene Datum enthaelt.
    datum: beliebiges Datum der Woche als YYYY-MM-DD.
    Einkaufstage markieren, wann eingekauft wird – relevant fuer Planung und Einkaufsliste."""
    from datetime import date
    return await services.list_einkaufstage(date.fromisoformat(datum))


@mcp.tool
async def wochenplan_holen(datum: str) -> list:
    """Gibt alle geplanten Mahlzeiten der Woche zurueck (Frühstück/Mittag/Abendessen/Snack/Unterwegs).
    datum: beliebiges Datum der gewuenschten Woche als YYYY-MM-DD.
    Jeder Eintrag enthaelt: datum, mahlzeit, rezept_id, rezept_name, notiz, person_ids, portionen."""
    from datetime import date
    return await services.list_wochenplan(date.fromisoformat(datum))


@mcp.tool
async def einkaufsliste_holen(datum: str) -> dict:
    """Berechnet die Einkaufsliste ab heute. Vergangene Tage/Einkaufstage fallen raus.
    Mit Einkaufstagen je Periode bis zum naechsten Einkaufstag bzw. Sonntag; ohne
    Einkaufstage ab heute bis Sonntag der Folgewoche. Jede Periode: von, bis,
    ist_einkaufstag, positionen [{zutat, einheit, benoetigt, vorhanden, kaufen}].
    Zusaetzlich 'manuell': manuell hinzugefuegte Artikel. datum: YYYY-MM-DD."""
    from datetime import date
    return await services.get_einkaufsliste(date.fromisoformat(datum))


@mcp.tool
async def plan_eintrag_anlegen(datum: str, mahlzeit: str = "Abendessen",
                                rezept_id: int | None = None, notiz: str | None = None,
                                person_ids: list[int] | None = None,
                                portionen: float | None = None, gaeste: int = 0) -> dict:
    """Plant eine Mahlzeit fuer einen bestimmten Tag.
    datum: YYYY-MM-DD. mahlzeit: Frühstück|Mittag|Abendessen|Snack|Unterwegs.
    rezept_id aus rezepte_suchen oder rezepte_vorschlagen. person_ids aus personen_liste.
    portionen: optional, wird sonst aus person_ids berechnet (Summe der Portionsfaktoren).
    gaeste: zusaetzliche Gast-Portionen, werden zu den mitessenden Personen addiert.
    notiz: freier Text falls kein Rezept (z.B. 'Schulkantine', 'Reste')."""
    from datetime import date
    return await services.add_plan_eintrag(
        date.fromisoformat(datum), mahlzeit, rezept_id, notiz, person_ids, portionen, gaeste
    )


@mcp.tool
async def plan_eintrag_loeschen(eintrag_id: int) -> dict:
    """Loescht einen Planungseintrag."""
    return await services.delete_plan_eintrag(eintrag_id)


@mcp.tool
async def einkaufstag_setzen(datum: str) -> dict:
    """Setzt oder entfernt einen Einkaufstag (Toggle).
    datum: YYYY-MM-DD. Gibt {action: 'added'|'removed', datum} zurueck."""
    from datetime import date
    return await services.toggle_einkaufstag(date.fromisoformat(datum))


@mcp.tool
async def einkaufsliste_artikel_hinzufuegen(artikel: list[dict]) -> list:
    """Fuegt manuell aufgeschriebene Artikel zur Einkaufsliste hinzu – mehrere auf einmal.
    artikel: Liste von {name, menge?, einheit?}; name ist Pflicht, menge/einheit optional.
    Beispiel: [{"name": "Klopapier"}, {"name": "Milch", "menge": 2, "einheit": "l"}].
    Diese Artikel erscheinen in der Einkaufsliste unter 'manuell', unabhaengig vom Plan."""
    return await services.add_einkauf_extra(artikel)


@mcp.tool
async def einkaufsliste_extra_holen() -> list:
    """Listet die manuell hinzugefuegten Einkaufslisten-Artikel (mit id zum Loeschen)."""
    return await services.list_einkauf_extra()


@mcp.tool
async def einkaufsliste_extra_loeschen(extra_id: int) -> dict:
    """Entfernt einen manuell hinzugefuegten Einkaufslisten-Artikel.
    extra_id aus einkaufsliste_extra_holen."""
    return await services.delete_einkauf_extra(extra_id)


@mcp.tool
async def rezept_vorrat_check(rezept_id: int) -> dict:
    """Zeigt je Pflicht-Zutat eines Rezepts, ob sie im Vorrat ist.
    Status: ok (genug) / knapp (zu wenig) / vorhanden (andere Einheit) /
    aehnlich (Namens-Match) / fehlt. Basis: 1 Rezept-Portion (Faktor 1)."""
    return await services.check_vorrat_fuer_rezept(rezept_id)


@mcp.tool
async def personen_verfuegbarkeit(datum: str, mahlzeit: str = "Abendessen") -> dict:
    """Gibt an, welche Personen an einem bestimmten Tag und Mahlzeit anwesend sind.
    Beruecksichtigt automatisch Abwesenheitsregeln (z.B. Wechselmodell-Kinder).
    datum: YYYY-MM-DD. mahlzeit: Frühstück|Mittag|Abendessen|Snack|Unterwegs.
    Beim Erstellen von Planeintraegen immer zuerst aufrufen um korrekte person_ids zu erhalten."""
    from datetime import date
    ids = await services.get_verfuegbar(date.fromisoformat(datum), mahlzeit)
    return {"datum": datum, "mahlzeit": mahlzeit, "person_ids": ids}


@mcp.tool
async def angebote_holen(datum: str | None = None) -> list:
    """Gibt aktuelle Supermarkt-Angebote zurueck (alle hinterlegten Maerkte).
    Nutze diese IMMER vor der Wochenplanung um reduzierte Zutaten zu bevorzugen.
    Wenn ein Rezept eine Angebots-Zutat verwendet, darauf hinweisen.
    datum: YYYY-MM-DD (optional, default heute)."""
    from datetime import date
    d = date.fromisoformat(datum) if datum else None
    return await services.get_angebote(d)


@mcp.tool
async def angebot_loeschen(angebot_id: int) -> dict:
    """Loescht ein Angebot anhand seiner id (aus angebote_holen). Vom Home-Assistenten
    aus duerfen auch globale Admin-Angebote geloescht werden. Gibt {geloescht: n} zurueck."""
    return await services.delete_angebot(int(angebot_id), admin=True)


@mcp.tool
async def angebote_importieren(eintraege: list[dict]) -> dict:
    """Importiert/ERGAENZT Angebote (z.B. aus dem Wochenprospekt): bestehende Angebote des
    Marktes bleiben erhalten, neue Artikel kommen hinzu, exakte Dubletten werden
    uebersprungen. Gibt {importiert: n, uebersprungen: m} zurueck.

    Jeder Eintrag ist ein Objekt:
    {haendler, gueltig_von, gueltig_bis, name, beschreibung?, preis_normal?, preis_angebot?,
     einheit?, kategorie?, art?, master_zutat?, master_zutat_id?, nur_wochenende?, wochenende_tage?}
    - haendler (WICHTIG): Markt/Haendler des Angebots, z.B. 'Supermarkt Beispiel', 'Discounter Muster'.
      Trennt Maerkte sauber; bei mehreren Maerkten je Angebot setzen.
    - gueltig_von/gueltig_bis: YYYY-MM-DD (Pflicht).
    - name: Angebotsname wie im Prospekt (z.B. 'Gut & Guenstig Thunfischfilet 195g').
    - preis_normal/preis_angebot: Zahl in Euro (z.B. 1.29). einheit/kategorie: Freitext.
    - art: 'zutat' | 'fertiggericht' | 'non_food' (optional, sonst Heuristik).
    - master_zutat (optional, Freitext): generische Zutat hinter dem Produkt (z.B. 'Thunfisch');
      wird automatisch verknuepft/angelegt. Alternativ master_zutat_id (s.u.).
    - nur_wochenende/wochenende_tage: bei Wochenend-Aktionen (z.B. 'Fr Sa') statt eines eigenen
      gueltig_von/bis -> der Zeitraum wird automatisch auf das Aktions-Wochenende verkuerzt.
    - master_zutat_id (optional): ID der generischen Master-Zutat, auf die sich
      das Angebot bezieht. Dadurch wird das Angebot mit Rezepten, Vorrat und Einkaufsliste
      verknuepft (sonst ist es nur Freitext). VORGEHEN: vorher einmal zutaten_master_liste
      holen und je Angebot, wenn es eindeutig passt (z.B. 'Gut & Guenstig Thunfischfilet'
      -> Master 'Thunfisch in eigenem Saft'), die passende master_zutat_id setzen. Im
      Zweifel weglassen (kann spaeter manuell nachgepflegt werden)."""
    return await services.import_angebote(eintraege)


@mcp.tool
async def angebote_master_zuordnen(zuordnungen: list[dict]) -> dict:
    """Ordnet BESTEHENDEN Angeboten nachtraeglich eine Master-Zutat zu, ohne sie neu zu
    importieren. zuordnungen: [{angebot_id, master_zutat_id}]. master_zutat_id=null hebt
    die Zuordnung wieder auf. Gibt {aktualisiert: n} zurueck.

    VORGEHEN: zuerst angebote_holen (gewuenschte Woche) und zutaten_master_liste holen,
    dann je Angebot pruefen, ob es klar zu einer generischen Master-Zutat passt (z.B.
    'Koelln Haferflocken' -> Master 'Haferflocken', 'Bonduelle Goldmais' -> 'Mais',
    'Olympus Feta' -> 'Feta'). Wurst, Snacks, Getraenke, Suesswaren etc. meist OHNE Master
    lassen (kein Rezept-Bezug). Nur klare Treffer setzen, im Zweifel weglassen. Alle
    Zuordnungen in EINEM Aufruf als Liste uebergeben."""
    return await services.set_angebote_master(zuordnungen)
