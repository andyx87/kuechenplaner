"""Pydantic-Modelle für strukturierte Ein- und Ausgaben.

Eine Quelle für die MCP-Werkzeuge (Claude sieht daraus ein präzises JSON-Schema) und die
REST-Routen, die dieselben Daten annehmen. Feldbeschreibungen sind deutsch mit kurzer
englischer Ergänzung, weil sie direkt im Tool-Schema beim Modell landen.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Datum = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Datum YYYY-MM-DD")]
Mahlzeit = Literal["Frühstück", "Mittag", "Abendessen", "Snack", "Unterwegs"]
Gang = Literal["Frühstück", "Vorspeise", "Suppe", "Salat", "Hauptgericht", "Beilage", "Snack",
               "Nachspeise", "Kuchen & Torten", "Brot & Backwaren", "Getränk", "Soße & Dip"]
Kueche = Literal["Deutsch", "Italienisch", "Mediterran", "Asiatisch", "Mexikanisch", "Indisch",
                 "Orientalisch", "Amerikanisch", "International"]
AngebotArt = Literal["zutat", "fertiggericht", "non_food"]

EINHEIT_TEXT = ("Einheit, z. B. g, kg, ml, l, Stück, Packung, Dose, Glas, Bund, EL, TL, Prise "
                "(unit, e.g. g, kg, ml, l, piece)")


class _Streng(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- Vorrat ----------

class VorratPosten(_Streng):
    name: str = Field(min_length=1, max_length=120, description=(
        "Generischer deutscher Lebensmittelname ohne Marke, z. B. 'Naturjoghurt' statt "
        "'Marke X Joghurt' (generic German food name, no brand)"))
    menge: float = Field(gt=0, le=100000, description="Menge (amount), > 0")
    einheit: str = Field(min_length=1, max_length=20, description=EINHEIT_TEXT)
    lagerort: str | None = Field(None, max_length=60, description=(
        "Lagerort-Name, z. B. 'Kühlschrank', 'Tiefkühler', 'Vorratsschrank'. Unbekannte Namen "
        "werden angelegt (storage location; created if new)"))
    mhd: Datum | None = Field(None, description="Mindesthaltbarkeits-/Ablaufdatum YYYY-MM-DD (best before)")
    kategorie: str | None = Field(None, max_length=40, description="Optionale Warengruppe (category)")
    sicherheit: Literal["sicher", "geschaetzt"] = Field("geschaetzt", description=(
        "'geschaetzt' wenn aus einem Foto erkannt/geschätzt, 'sicher' wenn genannt (confidence)"))


# ---------- Geräte ----------

class GeraetIn(_Streng):
    name: str = Field(min_length=1, max_length=80, description=(
        "Gerätename wie im Alltag, z. B. 'Backofen', 'Heißluftfritteuse', 'Thermomix' (appliance name)"))
    typ: str | None = Field(None, max_length=60, description="Optionaler Typ/Hersteller-Modell (type)")
    standard: bool = Field(True, description=(
        "true = Alltagsgerät (täglich verfügbar), false = situativ wie Grill (everyday vs. occasional)"))


# ---------- Rezepte ----------

class RezeptZutat(_Streng):
    name: str = Field(min_length=1, max_length=120, description=(
        "Generische Zutat ohne Marke, Singular oder üblicher Name, z. B. 'Zwiebel', 'Olivenöl' "
        "(generic ingredient)"))
    menge: float | None = Field(None, ge=0, le=100000, description="Menge für die angegebenen Portionen (amount)")
    einheit: str | None = Field(None, max_length=20, description=EINHEIT_TEXT)
    optional: bool = Field(False, description="true für optionale Zutaten (optional ingredient)")


class Variante(_Streng):
    geraet: str | None = Field(None, max_length=80, description=(
        "Exakter Gerätename aus haushalt_uebersicht/geraete oder null für 'ohne Gerät' "
        "(exact appliance name or null)"))
    text: str = Field(min_length=3, max_length=6000, description=(
        "Vollständiger Zubereitungstext dieser Komponente für dieses Gerät, mit Mengen, Zeiten, "
        "Temperaturen/Stufen (full instructions)"))


class Komponente(_Streng):
    titel: str = Field(min_length=1, max_length=80, description="Komponente, z. B. 'Reis', 'Sauce', 'Anrichten'")
    varianten: list[Variante] = Field(min_length=1, max_length=12, description=(
        "Eine Variante je geeignetem vorhandenen Gerät; geräteunabhängige Komponenten genau eine "
        "Variante mit geraet=null (one variant per suitable appliance)"))


class RezeptIn(_Streng):
    name: str = Field(min_length=1, max_length=160, description="Rezeptname (recipe title)")
    beschreibung: str | None = Field(None, max_length=2000, description="Kurzbeschreibung (short description)")
    portionen: int = Field(2, ge=1, le=50, description="Portionen, auf die sich die Mengen beziehen (servings)")
    dauer_minuten: int | None = Field(None, ge=1, le=2880, description="Gesamtzeit in Minuten (total time)")
    gang: Gang | None = Field(None, description="Gang/Kategorie (course)")
    kueche: Kueche | None = Field(None, description="Küche (cuisine)")
    quelle: str | None = Field(None, max_length=500, description="Quelle, z. B. URL oder Buch (source)")
    zutaten: list[RezeptZutat] = Field(min_length=1, max_length=80, description="Zutatenliste (ingredients)")
    zubereitung: list[Komponente] = Field(min_length=1, max_length=20, description=(
        "Zubereitung gegliedert in Komponenten mit Geräte-Varianten (structured method)"))


class RezeptUpdate(_Streng):
    """Teil-Update eines eigenen Rezepts; nicht gesetzte Felder bleiben unverändert."""
    rezept_id: int = Field(ge=1, description="ID eines EIGENEN Rezepts (own recipe id)")
    name: str | None = Field(None, min_length=1, max_length=160)
    beschreibung: str | None = Field(None, max_length=2000)
    portionen: int | None = Field(None, ge=1, le=50)
    dauer_minuten: int | None = Field(None, ge=1, le=2880)
    gang: Gang | None = None
    kueche: Kueche | None = None
    quelle: str | None = Field(None, max_length=500)
    zutaten: list[RezeptZutat] | None = Field(None, min_length=1, max_length=80, description=(
        "Wenn gesetzt: ersetzt die komplette Zutatenliste (replaces all ingredients)"))
    zubereitung: list[Komponente] | None = Field(None, min_length=1, max_length=20, description=(
        "Wenn gesetzt: ersetzt die komplette Zubereitung – immer ALLE Komponenten und Varianten "
        "mitschicken (replaces the whole method)"))


# ---------- Angebote ----------

class AngebotPosten(_Streng):
    name: str = Field(min_length=1, max_length=200, description="Artikelname wie im Prospekt (product name)")
    marke: str | None = Field(None, max_length=80, description="Marke, falls genannt (brand)")
    menge: float | None = Field(None, gt=0, le=100000, description="Packungsgröße als Zahl, z. B. 500 (pack size)")
    einheit: str | None = Field(None, max_length=20, description="Einheit der Packungsgröße, z. B. g, kg, ml, l, Stück")
    preis: float = Field(ge=0, le=10000, description="Angebotspreis in Euro (offer price, EUR)")
    preis_normal: float | None = Field(None, ge=0, le=10000, description="Regulärer/Streichpreis in Euro (regular price)")
    grundpreis: str | None = Field(None, max_length=60, description="Grundpreis wie gedruckt, z. B. '1 kg = 3.98' (unit price text)")
    kategorie: str | None = Field(None, max_length=40, description=(
        "Warengruppe; möglichst einen Wert aus angebote_schema.kategorien verwenden (category)"))
    art: AngebotArt = Field("zutat", description=(
        "'zutat' = Kochzutat, 'fertiggericht' = Fertigprodukt/Snack/Getränk, 'non_food' (type)"))
    master_zutat: str | None = Field(None, max_length=80, description=(
        "Nur bei art=zutat: generische Zutat, z. B. 'Hähnchenbrust' für 'Marke X Hähnchen-Brustfilet' "
        "(generic ingredient it maps to)"))
    nur_wochenende: bool = Field(False, description="true bei Wochenend-/Kurzzeit-Aktion (weekend-only deal)")


class AngeboteImport(_Streng):
    markt: str = Field(min_length=1, max_length=80, description="Markt/Händler, z. B. 'Supermarkt Musterstadt' (store)")
    gueltig_von: Datum
    gueltig_bis: Datum
    angebote: list[AngebotPosten] = Field(min_length=1, max_length=500)

    @field_validator("gueltig_bis")
    @classmethod
    def _bis_nach_von(cls, v, info):
        von = info.data.get("gueltig_von")
        if von and v < von:
            raise ValueError("gueltig_bis liegt vor gueltig_von")
        return v


# ---------- Plan ----------

class PlanEintrag(_Streng):
    datum: Datum
    mahlzeit: Mahlzeit = "Abendessen"
    rezept_id: int | None = Field(None, ge=1, description="Rezept-ID aus rezepte_suchen (recipe id) oder null")
    notiz: str | None = Field(None, max_length=200, description="Freitext ohne Rezept, z. B. 'Reste', 'Kantine'")
    person_ids: list[int] | None = Field(None, description="Personen-IDs; leer = Verfügbarkeit automatisch")
    gaeste: int = Field(0, ge=0, le=50, description="Zusätzliche Gäste (extra guests)")


# ---------- Einkauf ----------

class EinkaufPosten(_Streng):
    name: str = Field(min_length=1, max_length=120, description="Zutat wie in der Einkaufsliste (item name)")
    menge: float = Field(gt=0, le=100000, description="Gekaufte Menge (bought amount)")
    einheit: str = Field(min_length=1, max_length=20, description=EINHEIT_TEXT)
    lagerort: str | None = Field(None, max_length=60, description="Lagerort für den Vorrat (storage location)")
    mhd: Datum | None = None


# ---------- Kochmodus ----------

class KochZutat(_Streng):
    name: str = Field(min_length=1, max_length=120)
    menge: float | None = Field(None, ge=0, le=100000)
    einheit: str | None = Field(None, max_length=20)


class Kochschritt(_Streng):
    nr: int = Field(ge=1, le=200, description="Fortlaufende Nummer ab 1 (step number)")
    komponente: str | None = Field(None, max_length=80, description="Titel der Komponente (component)")
    text: str = Field(min_length=3, max_length=1500, description="Eine Haupthandlung pro Schritt (one action)")
    dauer_minuten: int | None = Field(None, ge=1, le=1440, description="Warte-/Garzeit in Minuten (timer length)")
    timer: bool = Field(False, description="true, wenn die App einen Timer anbieten soll (offer timer)")
    geraete: list[str] = Field(default_factory=list, max_length=10, description="Genutzte Geräte (appliances)")
    zutaten: list[KochZutat] = Field(default_factory=list, max_length=40, description=(
        "In diesem Schritt verwendete Zutaten mit Mengen für die Basis-Portionen des Rezepts"))


# ---------- Persönliche Zugriffstokens (REST) ----------

class PatErstellen(_Streng):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal["read", "write"]] = Field(default_factory=lambda: ["read", "write"])
    gueltig_tage: int | None = Field(None, ge=1, le=3650)


class OAuthEntscheidung(_Streng):
    zustimmen: bool
    scopes: list[Literal["read", "write"]] | None = None
