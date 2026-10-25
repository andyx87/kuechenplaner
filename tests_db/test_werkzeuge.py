"""MCP-Werkzeuge Ende-zu-Ende über HTTP mit echtem Token und RLS."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import admin_sql
from helfer import mcp, mcp_tools, ok, voller_ablauf

HEUTE = date.today()
VON, BIS = HEUTE.isoformat(), (HEUTE + timedelta(days=6)).isoformat()


@pytest.fixture
def haushalt(server, nutzer):
    n = nutzer("Hanna")
    tok = voller_ablauf(server, n["token"])["access_token"]
    return {**n, "mcp": tok, "base": server}


def test_annotationen_und_beschreibungen(haushalt):
    import asyncio

    from fastmcp import Client

    async def lauf():
        async with Client(f"{haushalt['base']}/mcp", auth=haushalt["mcp"]) as c:
            return await c.list_tools()
    tools = {t.name: t for t in asyncio.run(lauf())}
    assert tools["haushalt_uebersicht"].annotations.read_only_hint is True
    assert tools["rezept_loeschen"].annotations.destructive_hint is True
    assert tools["vorrat_buchen"].annotations.read_only_hint is False
    # präzises Schema statt "array of object"
    posten = tools["vorrat_buchen"].input_schema
    assert "posten" in posten["properties"]
    assert "/" in tools["angebote_importieren"].description   # DE / EN
    for t in tools.values():
        assert t.description and len(t.description) > 30


def test_angebote_fluss(haushalt):
    b, t = haushalt["base"], haushalt["mcp"]
    schema = ok(b, t, "angebote_schema")
    assert "Obst & Gemüse" in schema["kategorien"] and schema["eingabe_schema"]["properties"]["angebote"]
    angebote = [
        {"name": "Hähnchen-Brustfilet", "marke": "Hofgut", "menge": 600, "einheit": "g", "preis": 5.99,
         "preis_normal": 7.49, "grundpreis": "1 kg = 9.98", "kategorie": "Fleisch & Wurst", "art": "zutat",
         "master_zutat": "Hähnchenbrust"},
        {"name": "Rispentomaten", "menge": 500, "einheit": "g", "preis": 1.49, "kategorie": "Obst & Gemüse",
         "art": "zutat", "master_zutat": "Tomate"},
        {"name": "Spülmittel", "preis": 0.95, "art": "non_food"},
    ]
    v = ok(b, t, "angebote_importieren", markt="Testmarkt", gueltig_von=VON, gueltig_bis=BIS, angebote=angebote)
    assert v["vorschau"] is True and v["neu"] == 3
    assert {p["master_treffer"] for p in v["posten"] if p["art"] == "zutat"} <= {"exakt", "aehnlich", "normalisiert"}
    assert ok(b, t, "angebote_holen", markt="Testmarkt")["gesamt"] == 0   # Vorschau speichert nichts
    r = ok(b, t, "angebote_importieren", markt="Testmarkt", gueltig_von=VON, gueltig_bis=BIS, angebote=angebote,
           vorschau=False, idempotenz_schluessel="prospekt-1")
    assert r["importiert"] == 3
    again = ok(b, t, "angebote_importieren", markt="Testmarkt", gueltig_von=VON, gueltig_bis=BIS,
               angebote=angebote, vorschau=False, idempotenz_schluessel="prospekt-1")
    assert again["wiederholt"] is True and again["importiert"] == 3
    dub = ok(b, t, "angebote_importieren", markt="Testmarkt", gueltig_von=VON, gueltig_bis=BIS, angebote=angebote,
             vorschau=False)
    assert dub["importiert"] == 0 and dub["uebersprungen"] == 3
    liste = ok(b, t, "angebote_holen", markt="Testmarkt", art="zutat")
    assert liste["gesamt"] == 2
    huhn = next(a for a in liste["eintraege"] if a["name"] == "Hähnchen-Brustfilet")
    assert huhn["einheit"] == "600 g" and huhn["master_zutat"] == "Hähnchenbrust" and huhn["preis"] == 5.99
    # ungültige Eingaben werden vom Schema abgelehnt
    erfolgreich, fehler = mcp(b, t, "angebote_importieren", markt="X", gueltig_von=BIS, gueltig_bis=VON,
                              angebote=angebote[:1], vorschau=True)
    assert erfolgreich is False and "gueltig_bis" in fehler
    assert mcp(b, t, "angebote_importieren", markt="X", gueltig_von="morgen", gueltig_bis=BIS,
               angebote=angebote[:1])[0] is False
    assert ok(b, t, "angebote_blatt_loeschen", markt="Testmarkt", gueltig_von=VON, gueltig_bis=BIS)["geloescht"] == 3


def test_vorrat_aus_foto(haushalt):
    b, t = haushalt["base"], haushalt["mcp"]
    posten = [
        {"name": "Tomate", "menge": 6, "einheit": "Stück", "lagerort": "Kühlschrank"},
        {"name": "naturjoghurt", "menge": 500, "einheit": "g", "lagerort": "Kühlschrank",
         "mhd": (HEUTE + timedelta(days=3)).isoformat()},
        {"name": "Drachenfruchtsirup", "menge": 1, "einheit": "Flasche", "lagerort": "Vorratsschrank"},
    ]
    v = ok(b, t, "vorrat_buchen", posten=posten)
    treffer = {p["eingabe"]: p for p in v["posten"]}
    assert treffer["Tomate"]["zutat"] == "Tomaten" and treffer["Tomate"]["treffer"] == "aehnlich"
    assert treffer["naturjoghurt"]["treffer"] == "exakt"
    assert treffer["Drachenfruchtsirup"]["treffer"] == "neu" and v["neue_zutaten"] == 1
    assert treffer["Tomate"]["lagerort_neu"] is True
    assert ok(b, t, "vorrat_holen")["gesamt"] == 0
    g = ok(b, t, "vorrat_buchen", posten=posten, vorschau=False, idempotenz_schluessel="foto-1")
    assert g["gebucht"] == 3
    assert ok(b, t, "vorrat_buchen", posten=posten, vorschau=False, idempotenz_schluessel="foto-1")["wiederholt"]
    alle = ok(b, t, "vorrat_holen")
    assert alle["gesamt"] == 3
    bald = ok(b, t, "vorrat_holen", ablauf_in_tagen=5)
    assert [e["zutat"] for e in bald["eintraege"]] == ["Naturjoghurt"]
    seite1 = ok(b, t, "vorrat_holen", limit=2)
    assert len(seite1["eintraege"]) == 2 and seite1["naechster_cursor"] == "2"
    seite2 = ok(b, t, "vorrat_holen", limit=2, cursor=seite1["naechster_cursor"])
    assert len(seite2["eintraege"]) == 1 and seite2["naechster_cursor"] is None
    jog = bald["eintraege"][0]["vorrat_id"]
    neu = ok(b, t, "vorrat_aendern", vorrat_id=jog, menge=250, lagerort="Tiefkühler")
    assert neu["menge"] == 250
    assert ok(b, t, "vorrat_holen", lagerort="Tiefkühler")["gesamt"] == 1
    assert ok(b, t, "vorrat_loeschen", vorrat_ids=[jog, 999999]) == {"geloescht": [jog], "nicht_gefunden": [999999]}
    # Schema: Menge muss > 0 sein
    assert mcp(b, t, "vorrat_buchen", posten=[{"name": "Reis", "menge": 0, "einheit": "g"}])[0] is False


def _rezept(name="Tomatenreis", varianten=None):
    return {
        "name": name, "portionen": 2, "dauer_minuten": 30, "gang": "Hauptgericht", "kueche": "Mediterran",
        "zutaten": [{"name": "Reis", "menge": 200, "einheit": "g"}, {"name": "Tomaten", "menge": 400, "einheit": "g"},
                    {"name": "Zwiebel", "menge": 1, "einheit": "Stück"}],
        "zubereitung": [
            {"titel": "Reis", "varianten": varianten or [{"geraet": "Herd", "text": "Reis mit doppelter Menge Wasser 15 Minuten köcheln."}]},
            {"titel": "Sauce", "varianten": [{"geraet": None, "text": "Zwiebel und Tomaten anschwitzen und einkochen."}]},
        ],
    }


def test_rezepte_und_geraete(haushalt):
    b, t = haushalt["base"], haushalt["mcp"]
    g = ok(b, t, "geraete_anlegen", geraete=[{"name": "Herd"}, {"name": "Herd"}, {"name": "Grill", "standard": False}])
    assert g["angelegt"] == 2
    fehler = mcp(b, t, "rezept_anlegen", rezept=_rezept(varianten=[{"geraet": "Dampfgarer", "text": "Reis dämpfen bis gar."}]))
    assert fehler[0] is False and "Dampfgarer" in fehler[1]
    r = ok(b, t, "rezept_anlegen", rezept=_rezept(), idempotenz_schluessel="r1")
    assert r["geraete_abgestimmt"] is False   # Grill fehlt noch in der Reis-Komponente
    assert ok(b, t, "rezept_anlegen", rezept=_rezept(), idempotenz_schluessel="r1")["rezept_id"] == r["rezept_id"]
    such = ok(b, t, "rezepte_suchen", query="Tomatenreis", nur_eigene=True)
    assert such["gesamt"] == 1 and such["eintraege"][0]["eigenes"] is True
    assert ok(b, t, "rezepte_suchen", zutaten=["Reis", "Zwiebel"])["gesamt"] >= 1
    voll = ok(b, t, "rezept_holen", rezept_id=r["rezept_id"])
    assert "bild" not in voll and voll["zubereitung"][0]["titel"] == "Reis"

    # "Alle Rezepte aktualisieren"
    bedarf = ok(b, t, "rezepte_anpassungsbedarf")
    assert bedarf["offen_gesamt"] == 1 and set(bedarf["geraete"]) == {"Herd", "Grill"}
    zub = bedarf["rezepte"][0]["zubereitung"]
    zub[0]["varianten"].append({"geraet": "Grill", "text": "Reis in der Grillpfanne 18 Minuten garen."})
    vor = ok(b, t, "rezepte_aktualisieren", rezepte=[{"rezept_id": r["rezept_id"], "zubereitung": zub}])
    assert vor["vorschau"] and vor["ergebnisse"][0]["deckt_alle_geraete_ab"] is True
    assert ok(b, t, "rezepte_anpassungsbedarf")["offen_gesamt"] == 1
    fertig = ok(b, t, "rezepte_aktualisieren", rezepte=[{"rezept_id": r["rezept_id"], "zubereitung": zub}], vorschau=False)
    assert fertig["aktualisiert"] == 1
    assert ok(b, t, "rezepte_anpassungsbedarf")["offen_gesamt"] == 0
    assert ok(b, t, "rezept_holen", rezept_id=r["rezept_id"])["geraete_abgestimmt"] is True
    teil = ok(b, t, "rezept_aendern", rezept={"rezept_id": r["rezept_id"], "portionen": 4})
    assert teil["felder"] == ["portionen"]
    assert ok(b, t, "rezept_holen", rezept_id=r["rezept_id"])["portionen"] == 4

    # Vorschläge nach Vorrat + Geräten
    ok(b, t, "vorrat_buchen", posten=[{"name": "Reis", "menge": 1, "einheit": "kg"},
                                      {"name": "Tomaten", "menge": 1, "einheit": "kg"}], vorschau=False)
    vs = ok(b, t, "rezepte_vorschlagen")["vorschlaege"]
    eintrag = next(v for v in vs if v["rezept_id"] == r["rezept_id"])
    assert eintrag["fehlend"] == 1   # Zwiebel fehlt
    check = ok(b, t, "rezept_vorrat_check", rezept_id=r["rezept_id"])
    assert check

    # Rezepte aus Angeboten
    ok(b, t, "angebote_importieren", markt="Testmarkt Zwei", gueltig_von=VON, gueltig_bis=BIS, vorschau=False,
       angebote=[{"name": "Gemüsezwiebeln 1 kg", "preis": 0.99, "art": "zutat", "master_zutat": "Zwiebel"}])
    aa = ok(b, t, "rezepte_aus_angeboten", markt="Testmarkt Zwei")
    assert any(x["rezept_id"] == r["rezept_id"] for x in aa["rezepte"])

    # Bild: ohne Anbieter klarer Fehler
    bild = mcp(b, t, "rezeptbild_erzeugen", rezept_id=r["rezept_id"])
    assert bild[0] is False and "Bild-Anbieter" in bild[1]
    assert ok(b, t, "rezept_loeschen", rezept_id=r["rezept_id"])["deleted"] == r["rezept_id"]


def test_plan_und_einkauf(haushalt):
    b, t = haushalt["base"], haushalt["mcp"]
    ok(b, t, "geraete_anlegen", geraete=[{"name": "Herd"}])
    r = ok(b, t, "rezept_anlegen", rezept=_rezept("Planreis"))
    eintraege = [{"datum": VON, "mahlzeit": "Abendessen", "rezept_id": r["rezept_id"]},
                 {"datum": VON, "mahlzeit": "Mittag", "notiz": "Kantine"}]
    s1 = ok(b, t, "wochenplan_setzen", eintraege=eintraege)
    assert s1["neu"] == 2
    assert ok(b, t, "wochenplan_setzen", eintraege=eintraege)["neu"] == 0   # idempotent
    plan = ok(b, t, "wochenplan_holen", datum=VON)["eintraege"]
    assert {p["mahlzeit"] for p in plan} >= {"Abendessen", "Mittag"}
    ok(b, t, "einkaufstag_setzen", datum=VON, aktiv=True, maerkte=["Testmarkt"])
    ok(b, t, "einkaufstag_setzen", datum=VON, aktiv=True)                     # bleibt gesetzt
    liste = ok(b, t, "einkaufsliste_erzeugen", datum=VON)
    pos = [p for per in liste["perioden"] for p in per["positionen"]]
    assert {p["zutat"] for p in pos} >= {"Reis", "Tomaten"}
    extra = ok(b, t, "einkauf_extra_hinzufuegen", artikel=[{"name": "Kaffee", "menge": 1, "einheit": "Packung"}])
    xid = extra["hinzugefuegt"][0]["extra_id"]
    ab = ok(b, t, "einkauf_abhaken", gekauft=[{"name": "Reis", "menge": 500, "einheit": "g", "lagerort": "Vorratsschrank"}],
            extra_ids=[xid])
    assert ab["in_vorrat_gebucht"] == 1 and ab["extras_entfernt"] == [xid]
    assert ok(b, t, "vorrat_holen", suche="Reis")["gesamt"] == 1
    ids = [p["id"] for p in plan]
    assert set(ok(b, t, "plan_eintraege_loeschen", eintrag_ids=ids)["geloescht"]) == set(ids)


def test_kochmodus_pro_haushalt(server, nutzer):
    a, c = nutzer("Anna"), nutzer("Carl")
    ta = voller_ablauf(server, a["token"])["access_token"]
    tc = voller_ablauf(server, c["token"])["access_token"]
    ok(server, ta, "geraete_anlegen", geraete=[{"name": "Herd"}])
    r = ok(server, ta, "rezept_anlegen", rezept=_rezept("Kochmodusreis"))
    leer = ok(server, ta, "kochmodus_holen", rezept_id=r["rezept_id"])
    assert leer["vorhanden"] is False and leer["zubereitung_aktiv"][0]["titel"] == "Reis"
    schritte = [{"nr": 1, "komponente": "Reis", "text": "Reis waschen.", "zutaten": [{"name": "Reis", "menge": 200, "einheit": "g"}]},
                {"nr": 2, "komponente": "Reis", "text": "Reis 15 Minuten köcheln.", "dauer_minuten": 15, "timer": True},
                {"nr": 3, "komponente": "Sauce", "text": "Sauce einkochen.", "timer": True}]
    gesp = ok(server, ta, "kochmodus_speichern", rezept_id=r["rezept_id"], schritte=schritte)
    assert gesp["schritte"] == 3
    voll = ok(server, ta, "kochmodus_holen", rezept_id=r["rezept_id"])
    assert voll["vorhanden"] is True and voll["schritte"][1]["timer"] is True
    assert voll["schritte"][2]["timer"] is False   # Timer ohne Dauer wird verworfen
    # Fremder Haushalt: veröffentlichtes Rezept sichtbar, Schritte von Anna NICHT
    admin_sql("UPDATE rezepte SET veroeffentlicht = true WHERE id = $1", r["rezept_id"])
    fremd = ok(server, tc, "kochmodus_holen", rezept_id=r["rezept_id"])
    assert fremd["vorhanden"] is False
    ok(server, tc, "kochmodus_speichern", rezept_id=r["rezept_id"], schritte=schritte[:1])
    assert len(ok(server, ta, "kochmodus_holen", rezept_id=r["rezept_id"])["schritte"]) == 3
    assert len(ok(server, tc, "kochmodus_holen", rezept_id=r["rezept_id"])["schritte"]) == 1
    # Carl darf Annas veröffentlichtes Rezept nicht ändern
    assert ok(server, tc, "rezepte_aktualisieren", rezepte=[{"rezept_id": r["rezept_id"], "portionen": 9}],
              vorschau=False)["aktualisiert"] == 0
    rows = admin_sql("SELECT account_id FROM kochmodus_schritte WHERE rezept_id = $1", r["rezept_id"])
    assert sorted(x["account_id"] for x in rows) == sorted([a["account_id"], c["account_id"]])
    # Rezeptänderung verwirft eigene Schritte (passen nicht mehr)
    zub = _rezept()["zubereitung"]
    zub[1]["varianten"][0]["text"] = "Neue Sauce mit Kräutern einkochen."
    ok(server, ta, "rezept_aendern", rezept={"rezept_id": r["rezept_id"], "zubereitung": zub})
    assert ok(server, ta, "kochmodus_holen", rezept_id=r["rezept_id"])["vorhanden"] is False
    # Carls gespeicherte Schritte passen nicht mehr zur geänderten Zubereitung
    assert ok(server, tc, "kochmodus_holen", rezept_id=r["rezept_id"])["vorhanden"] is False


def test_werkzeugliste_vollstaendig(haushalt):
    tools = set(mcp_tools(haushalt["base"], haushalt["mcp"]))
    erwartet = {"haushalt_uebersicht", "angebote_schema", "angebote_importieren", "angebote_holen",
                "vorrat_buchen", "vorrat_aendern", "vorrat_loeschen", "geraete_anlegen", "rezepte_suchen",
                "rezept_anlegen", "rezept_aendern", "rezepte_aktualisieren", "rezepte_anpassungsbedarf",
                "rezepte_aus_angeboten", "rezepte_vorschlagen", "wochenplan_holen", "wochenplan_setzen",
                "einkaufsliste_erzeugen", "einkauf_abhaken", "kochmodus_holen", "kochmodus_speichern",
                "rezeptbild_erzeugen"}
    assert erwartet <= tools
