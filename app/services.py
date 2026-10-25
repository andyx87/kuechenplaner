"""Gemeinsame Datenbank-Operationen.

Diese Schicht ist die Single Source of Truth: sowohl die REST-API (Web-App)
als auch der MCP-Server (KI) rufen ausschliesslich diese Funktionen auf.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .db import acquire, pool

log = logging.getLogger("koch")

try:
    from asyncpg import UniqueViolationError
except Exception:  # pragma: no cover
    class UniqueViolationError(Exception):
        pass

_BERLIN = ZoneInfo("Europe/Berlin")


class NichtGefunden(Exception):
    """Eine Lösch-/Zugriffs-Operation traf keine (eigene) Ressource. Wird an der
    HTTP-Grenze (main.py) zu einem sauberen 404 gemappt – statt fälschlich 200 zu
    melden, wenn RLS eine fremde/nicht existierende Zeile schützt. Chat/MCP fangen
    die Exception ab und zeigen sie als lesbaren Fehler."""


def _affected(res: str | None) -> int:
    """Betroffene Zeilen aus einem asyncpg-Command-Tag ('DELETE 1' → 1)."""
    try:
        return int(str(res).split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


def _today() -> date:
    """Heutiges Datum in lokaler Zeit (fuer den Tageswechsel der Geraeteauswahl)."""
    return datetime.now(_BERLIN).date()


# ---------- Hilfsfunktionen ----------

def _d(r) -> dict | None:
    return dict(r) if r is not None else None


def _l(rs) -> list[dict]:
    return [dict(r) for r in rs]


def _num(v) -> Decimal | None:
    # asyncpg erwartet fuer NUMERIC ein Decimal; MCP/JSON liefern oft str/float.
    return None if v is None or v == "" else Decimal(str(v))


def _date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _jsonable(obj: Any) -> Any:
    """Decimal/date in JSON-freundliche Typen wandeln (fuer MCP-Rueckgaben)."""
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _woerter(text: str) -> list[str]:
    out, cur = [], ""
    for ch in (text or "").lower():
        if ch.isalpha():
            cur += ch
        elif cur:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return out


def _name_match(master: str, text: str) -> bool:
    """True, wenn die (meist kurze) Master-Bezeichnung als Wort/Wortstamm im Text
    vorkommt. Wortbasiert mit gemeinsamem Prefix (>=4 Zeichen), damit 'Tomate' ~
    'Tomaten' trifft, aber 'Lauch' NICHT in 'Knoblauch'."""
    m = (master or "").lower().strip()
    if len(m) < 3:
        return False
    for w in _woerter(text):
        if len(w) < 3:
            continue
        if w == m:
            return True
        if len(m) >= 4 and len(w) >= 4 and (w.startswith(m) or m.startswith(w)):
            return True
    return False


async def _finde_zutat(con, name: str) -> tuple[int, str, str] | None:
    """Sucht eine passende Zutat OHNE anzulegen -> (id, name, treffer) oder None.
    treffer: 'exakt' (gleicher Name), 'normalisiert' (Umlaut/Klammern), 'aehnlich'
    (Plural/Kopfwort) – dieselbe Logik wie beim Anlegen (_ensure_zutat)."""
    nm = (name or "").strip()
    if not nm:
        return None
    # 1) Exakter Name – globale Master-Zutaten zuerst (so matchen generierte Rezepte
    #    direkt auf die geteilte Master-DB), sonst eigene.
    row = await con.fetchrow(
        "SELECT id, name FROM zutaten WHERE lower(name) = lower($1) ORDER BY account_id NULLS FIRST LIMIT 1", nm)
    if row:
        return row["id"], row["name"], "exakt"
    # 2) Kein exakter Treffer -> unter den GLOBALEN Master-Zutaten suchen.
    #    a) Umlaut-/klammer-normalisierter Exakt-Treffer ('Olivenoel' == 'Olivenöl').
    #    b) sonst semantisch (Plural/Suffix, z.B. 'Tomate'->'Tomaten'); konservativer
    #       Kopfnomen-Abgleich, bevorzugt den namentlich nächstliegenden Master.
    norm = _normalize_zutat(nm)
    gmaster = await con.fetch(
        "SELECT id, name FROM zutaten WHERE account_id IS NULL AND kanonische_zutat_id IS NULL")
    exakt = [r for r in gmaster if _normalize_zutat(r["name"]) == norm]
    if exakt:
        return exakt[0]["id"], exakt[0]["name"], "normalisiert"
    treffer = [r for r in gmaster if _zutat_namensmatch(nm, r["name"] or "")]
    if treffer:
        treffer.sort(key=lambda r: (abs(len(r["name"]) - len(nm)), len(r["name"])))
        return treffer[0]["id"], treffer[0]["name"], "aehnlich"
    return None


async def _ensure_zutat(con, name: str, einheit: str | None = None,
                        kategorie: str | None = None) -> int:
    nm = name.strip()
    gefunden = await _finde_zutat(con, nm)
    if gefunden:
        return gefunden[0]
    # 3) Nicht vorhanden -> neu anlegen (eigenes Konto, als Master; account_id via Default).
    row = await con.fetchrow(
        "INSERT INTO zutaten (name, standard_einheit, kategorie) VALUES ($1, $2, $3) RETURNING id",
        nm, einheit, kategorie)
    return row["id"]


# ---------- Zutaten ----------

async def list_zutaten() -> list[dict]:
    async with acquire() as con:
        return _jsonable(_l(await con.fetch("SELECT * FROM zutaten ORDER BY name")))


async def ensure_zutat(name: str, einheit: str | None = None,
                       kategorie: str | None = None) -> int:
    async with acquire() as con:
        return await _ensure_zutat(con, name, einheit, kategorie)


async def create_zutat(name: str, standard_einheit: str | None = None,
                       kategorie: str | None = None, grundzutat: bool = False,
                       gebinde_menge=None, gebinde_einheit: str | None = None,
                       kanonische_zutat_id: int | None = None,
                       kanonisch_fixiert: bool = True) -> dict:
    """Legt eine neue Zutat an. Ohne kanonische_zutat_id ist es eine Master-Zutat
    (kanonische_zutat_id NULL). Mit kanonische_zutat_id wird sie direkt diesem Master
    untergeordnet (mit Validierung). Existiert der Name (case-insensitive) bereits,
    wird die bestehende Zutat unveraendert zurueckgegeben (kein Duplikat)."""
    nm = (name or "").strip()
    if not nm:
        return {"error": "Name fehlt"}
    gm = _num(gebinde_menge) if gebinde_menge not in (None, "") else None
    ge = (gebinde_einheit or "").strip() or None
    if gm is None:
        ge = None
    async with acquire() as con:
        existing = await con.fetchrow(
            "SELECT * FROM zutaten WHERE lower(name) = lower($1)", nm
        )
        if existing is not None:
            return {**_d(existing),
                    "_hinweis": "Zutat existierte bereits, unveraendert zurueckgegeben"}
        row = await con.fetchrow(
            """INSERT INTO zutaten
               (name, standard_einheit, kategorie, grundzutat, gebinde_menge, gebinde_einheit)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING *""",
            nm, (standard_einheit or None), kategorie, bool(grundzutat), gm, ge,
        )
    if kanonische_zutat_id is not None:
        return await set_kanonische_zutat(int(row["id"]), int(kanonische_zutat_id),
                                          fixiert=bool(kanonisch_fixiert))
    return _d(row)


async def _zutat_edit_bypass(zutat_id: int) -> tuple[bool, dict | None]:
    """Entscheidet, ob das Bearbeiten einer Zutat einen RLS-Bypass braucht.
    Globale Zutaten (account_id NULL) sind geteilte Katalog-Daten: Die RLS-WITH-CHECK
    laesst Updates an ihnen fuer normale App-Verbindungen (koch_app) NICHT zu. Sie
    duerfen daher nur vom Super-Admin (bzw. im MCP/LAN-Kontext ohne Nutzer) geaendert
    werden – dann mit bypass=True. Eigene Account-Zutaten werden normal geschrieben.
    Rueckgabe: (bypass, error|None)."""
    from .userauth import current_user, ist_super_admin
    async with acquire() as con:
        row = await con.fetchrow("SELECT account_id FROM zutaten WHERE id = $1", int(zutat_id))
    if row is None:
        return (False, {"error": "Zutat nicht gefunden"})
    if row["account_id"] is not None:
        return (False, None)  # eigene Account-Zutat -> normaler RLS-Write
    uid = current_user.get()
    if uid is not None and not await ist_super_admin(uid):
        return (False, {"error": "Globale Zutat – kann nur vom Administrator bearbeitet werden."})
    return (True, None)  # globale Zutat + Super-Admin/MCP -> bypass


async def set_grundzutat(zutat_id: int, grundzutat: bool) -> dict:
    """Markiert eine Zutat als Grundzutat (immer vorhanden) oder hebt das auf.
    Grundzutaten kommen nie auf die Einkaufsliste und gelten nicht als fehlend."""
    bypass, err = await _zutat_edit_bypass(zutat_id)
    if err:
        return err
    async with acquire(bypass=bypass) as con:
        row = await con.fetchrow(
            "UPDATE zutaten SET grundzutat = $2 WHERE id = $1 RETURNING *",
            int(zutat_id), bool(grundzutat),
        )
    return _d(row) if row else {"error": "Zutat nicht gefunden"}


async def set_gebinde(zutat_id: int, gebinde_menge=None, gebinde_einheit: str | None = None) -> dict:
    """Setzt die Gebinde-Groesse einer Zutat: 1 standard_einheit = gebinde_menge
    gebinde_einheit (z.B. 1 Packung = 250 g). Damit kann Vorrat in Packungen/Dosen
    auf die Rezept-Basiseinheit (g/ml) umgerechnet werden. Beide leer = loeschen."""
    gm = _num(gebinde_menge) if gebinde_menge not in (None, "") else None
    ge = (gebinde_einheit or "").strip() or None
    if gm is None:
        ge = None
    bypass, err = await _zutat_edit_bypass(zutat_id)
    if err:
        return err
    async with acquire(bypass=bypass) as con:
        row = await con.fetchrow(
            "UPDATE zutaten SET gebinde_menge = $2, gebinde_einheit = $3 WHERE id = $1 RETURNING *",
            int(zutat_id), gm, ge,
        )
    return _d(row) if row else {"error": "Zutat nicht gefunden"}


async def rename_zutat(zutat_id: int, name: str) -> dict:
    """Benennt eine Zutat (z.B. eine Master-Zutat) um."""
    neu = (name or "").strip()
    if not neu:
        return {"error": "Name darf nicht leer sein"}
    bypass, err = await _zutat_edit_bypass(zutat_id)
    if err:
        return err
    async with acquire(bypass=bypass) as con:
        try:
            row = await con.fetchrow(
                "UPDATE zutaten SET name = $2 WHERE id = $1 RETURNING *", int(zutat_id), neu
            )
        except UniqueViolationError:
            return {"error": f"Eine Zutat mit dem Namen '{neu}' existiert bereits"}
    return _d(row) if row else {"error": "Zutat nicht gefunden"}


async def delete_zutat(zutat_id: int) -> dict:
    """Loescht eine Zutat. Verweigert, wenn sie in einem Rezept verwendet wird oder
    noch im Vorrat liegt. Zutaten, die sie als Master haben, werden eigenstaendig."""
    zid = int(zutat_id)
    bypass, err = await _zutat_edit_bypass(zutat_id)
    if err:
        return err
    async with acquire(bypass=bypass) as con:
        if await con.fetchval("SELECT EXISTS(SELECT 1 FROM rezept_zutaten WHERE zutat_id = $1)", zid):
            return {"error": "Wird in mindestens einem Rezept verwendet - kann nicht geloescht werden."}
        if await con.fetchval("SELECT EXISTS(SELECT 1 FROM vorrat WHERE zutat_id = $1)", zid):
            return {"error": "Liegt noch im Vorrat - dort erst entfernen."}
        await con.execute(
            "UPDATE zutaten SET kanonische_zutat_id = NULL WHERE kanonische_zutat_id = $1", zid
        )
        res = await con.execute("DELETE FROM zutaten WHERE id = $1", zid)
    if not _affected(res):
        raise NichtGefunden("Zutat nicht gefunden oder kein Zugriff.")
    return {"deleted": True, "id": zid}


async def _load_canon_map(con) -> dict:
    """{zutat_id: master_zutat_id} fuer alle zugeordneten Zutaten."""
    rows = await con.fetch(
        "SELECT id, kanonische_zutat_id FROM zutaten WHERE kanonische_zutat_id IS NOT NULL"
    )
    return {int(r["id"]): int(r["kanonische_zutat_id"]) for r in rows}


async def set_kanonische_zutat(zutat_id: int, master_zutat_id: int | None,
                               fixiert: bool = False) -> dict:
    """Ordnet eine Zutat einer Master-Zutat zu (kanonische_zutat_id) oder hebt die
    Zuordnung auf (master_zutat_id=None -> eigenstaendiger Master). Verhindert
    Selbstbezug und Ketten (Ziel muss selbst Master sein). fixiert=True schuetzt
    die Zuordnung vor der automatischen KI-Zuordnung."""
    zid = int(zutat_id)
    bypass, err = await _zutat_edit_bypass(zutat_id)
    if err:
        return err
    async with acquire(bypass=bypass) as con:
        if master_zutat_id is None:
            row = await con.fetchrow(
                "UPDATE zutaten SET kanonische_zutat_id = NULL, kanonisch_fixiert = $2 WHERE id = $1 RETURNING *",
                zid, bool(fixiert),
            )
            return _d(row) if row else {"error": "Zutat nicht gefunden"}
        mid = int(master_zutat_id)
        if mid == zid:
            return {"error": "Zutat kann nicht ihr eigener Master sein"}
        master = await con.fetchrow(
            "SELECT id, kanonische_zutat_id FROM zutaten WHERE id = $1", mid
        )
        if master is None:
            return {"error": "Master-Zutat nicht gefunden"}
        if master["kanonische_zutat_id"] is not None:
            return {"error": "Ziel ist selbst kein Master (zeigt auf eine andere Zutat)"}
        row = await con.fetchrow(
            "UPDATE zutaten SET kanonische_zutat_id = $2, kanonisch_fixiert = $3 WHERE id = $1 RETURNING *",
            zid, mid, bool(fixiert),
        )
    return _d(row) if row else {"error": "Zutat nicht gefunden"}


async def list_master_zutaten() -> list[dict]:
    """Alle Master-Zutaten (kanonische_zutat_id IS NULL) mit Flag rezept_zutat
    (wird in mindestens einem Rezept verwendet). Ziel-Kandidaten fuer Zuordnungen
    und fuer das manuelle Such-/Auswahlfeld."""
    async with acquire() as con:
        rows = await con.fetch(
            """
            SELECT z.id, z.name, z.standard_einheit, z.grundzutat,
                   z.gebinde_menge, z.gebinde_einheit,
                   EXISTS(SELECT 1 FROM rezept_zutaten rz WHERE rz.zutat_id = z.id) AS rezept_zutat
            FROM zutaten z
            WHERE z.kanonische_zutat_id IS NULL
            ORDER BY z.name
            """
        )
    return _jsonable(_l(rows))


async def list_unmapped_zutaten() -> list[dict]:
    """Zutaten, die (noch) keinem Master zugeordnet sind, nicht in Rezepten
    verwendet werden, aber im Vorrat liegen - die Kandidaten fuer die automatische
    KI-Zuordnung (fixierte werden ausgelassen)."""
    async with acquire() as con:
        rows = await con.fetch(
            """
            SELECT DISTINCT z.id, z.name, z.standard_einheit
            FROM zutaten z
            JOIN vorrat v ON v.zutat_id = z.id
            WHERE z.kanonische_zutat_id IS NULL
              AND NOT z.kanonisch_fixiert
              AND NOT EXISTS(SELECT 1 FROM rezept_zutaten rz WHERE rz.zutat_id = z.id)
            ORDER BY z.name
            """
        )
    return _jsonable(_l(rows))


async def list_unbestaetigte_zuordnungen() -> list[dict]:
    """Alle Kanonik-Zuordnungen, die noch NICHT bestaetigt sind
    (kanonische_zutat_id gesetzt, aber kanonisch_fixiert=false) - also Vorschlaege
    der automatischen KI-Zuordnung, die auf User-Review warten. Pro Eintrag:
    zutat_id/name + master_id/master_name. Bestaetigen = zutat_kanonisch_zuordnen
    mit fixiert=true; ablehnen = zutat_kanonisch_zuordnen mit master_zutat_id=None."""
    async with acquire() as con:
        rows = await con.fetch(
            """
            SELECT z.id, z.name, z.standard_einheit,
                   z.kanonische_zutat_id AS master_id,
                   m.name AS master_name
            FROM zutaten z
            JOIN zutaten m ON m.id = z.kanonische_zutat_id
            WHERE z.kanonische_zutat_id IS NOT NULL
              AND NOT z.kanonisch_fixiert
            ORDER BY m.name, z.name
            """
        )
    return _jsonable(_l(rows))


# ---------- Geraete ----------

async def list_geraete() -> list[dict]:
    async with acquire() as con:
        return _jsonable(_l(await con.fetch("SELECT * FROM geraete ORDER BY name")))


async def add_geraet(name: str, typ: str | None = None,
                     notizen: str | None = None, standard: bool = True) -> dict:
    async with acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                """
                INSERT INTO geraete (name, typ, notizen, standard) VALUES ($1, $2, $3, $4)
                ON CONFLICT (account_id, name) DO UPDATE
                  SET typ = EXCLUDED.typ, notizen = EXCLUDED.notizen, standard = EXCLUDED.standard
                RETURNING *
                """,
                name.strip(), typ, notizen, bool(standard),
            )
            # Neues Alltagsgeraet sofort fuer heute aktiv schalten.
            if row["standard"]:
                await con.execute(
                    "INSERT INTO geraete_heute (geraet_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    row["id"],
                )
    return _jsonable(_d(row))


async def update_geraet(geraet_id: int, name: str | None = None, typ: str | None = None,
                        notizen: str | None = None, standard: bool | None = None) -> dict | None:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            UPDATE geraete SET
              name     = COALESCE($2, name),
              typ      = COALESCE($3, typ),
              notizen  = COALESCE($4, notizen),
              standard = COALESCE($5, standard)
            WHERE id = $1
            RETURNING *
            """,
            int(geraet_id), name, typ, notizen, standard,
        )))


async def delete_geraet(geraet_id: int) -> dict:
    # rezept_geraete und geraete_heute haengen per ON DELETE CASCADE dran.
    async with acquire() as con:
        res = await con.execute("DELETE FROM geraete WHERE id = $1", int(geraet_id))
    if not _affected(res):
        raise NichtGefunden("Gerät nicht gefunden oder kein Zugriff.")
    return {"deleted": int(geraet_id)}


# ---------- Personen / Haushalt ----------

# Mahlzeit-Rang für Abwesenheitsberechnung (muss mit Frontend übereinstimmen)
_MAHLZEIT_RANG = {'Frühstück': 0, 'Mittag': 1, 'Abendessen': 2, 'Snack': 3, 'Unterwegs': 4}


async def list_personen() -> list[dict]:
    """Listet alle aktiven Personen inkl. ihrer Abwesenheitsregeln."""
    async with acquire() as con:
        personen = _l(await con.fetch(
            "SELECT * FROM person WHERE aktiv ORDER BY CASE rolle WHEN 'erwachsener' THEN 0 ELSE 1 END, name"
        ))
        regeln = _l(await con.fetch(
            "SELECT * FROM person_abwesenheit_regel ORDER BY person_id, id"
        ))
    regel_map: dict[int, list] = {}
    for r in regeln:
        regel_map.setdefault(r["person_id"], []).append(r)
    for p in personen:
        p["abwesenheit_regeln"] = regel_map.get(p["id"], [])
    return _jsonable(personen)


async def get_verfuegbar(datum: date, mahlzeit: str) -> list[int]:
    """Gibt IDs der Personen zurück, die an datum/mahlzeit anwesend sind."""
    personen = await list_personen()
    return [p["id"] for p in personen if _ist_anwesend(p, datum, mahlzeit)]


def _ist_anwesend(person: dict, datum: date, mahlzeit: str) -> bool:
    """Berechnet Anwesenheit einer Person anhand ihrer Abwesenheitsregeln."""
    regeln = person.get("abwesenheit_regeln") or []
    if not regeln:
        return True
    # ISO-Woche und Wochentag (1=Mo…7=So)
    iso = datum.isocalendar()
    kw, wochentag = iso[1], iso[2]
    m_rang = _MAHLZEIT_RANG.get(mahlzeit, 2)

    for r in regeln:
        wt = r["woche_typ"]
        if wt == "gerade" and kw % 2 != 0:
            continue
        if wt == "ungerade" and kw % 2 == 0:
            continue
        # Montag der aktuellen Woche
        montag = datum - timedelta(days=wochentag - 1)
        dep = montag + timedelta(days=r["von_wochentag"] - 1)
        ret = montag + timedelta(days=r["bis_wochentag"] - 1)
        if r["folgewoche"]:
            ret += timedelta(weeks=1)
        dep_rang = _MAHLZEIT_RANG.get(r["von_mahlzeit"], 2)
        ret_rang = _MAHLZEIT_RANG.get(r["bis_mahlzeit"], 2)

        if dep < datum < ret:
            return False
        if datum == dep and m_rang >= dep_rang:
            return False
        if datum == ret and m_rang < ret_rang:
            return False
    return True


async def add_abwesenheit_regel(person_id: int, woche_typ: str, von_wochentag: int,
                                 von_mahlzeit: str, bis_wochentag: int, bis_mahlzeit: str,
                                 folgewoche: bool = False, notiz: str | None = None) -> dict:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """INSERT INTO person_abwesenheit_regel
               (person_id, woche_typ, von_wochentag, von_mahlzeit, bis_wochentag, bis_mahlzeit,
                folgewoche, notiz)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
            int(person_id), woche_typ, int(von_wochentag), von_mahlzeit,
            int(bis_wochentag), bis_mahlzeit, bool(folgewoche), notiz,
        )))


async def delete_abwesenheit_regel(regel_id: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM person_abwesenheit_regel WHERE id=$1", int(regel_id))
    if not _affected(res):
        raise NichtGefunden("Abwesenheits-Regel nicht gefunden oder kein Zugriff.")
    return {"deleted": int(regel_id)}


async def add_person(name: str, rolle: str = "erwachsener", kcal_ziel: int | None = None,
                     eiweiss_pct: int = 30, fett_pct: int = 30, kh_pct: int = 40,
                     portionsfaktor: float = 1.0, aktiv: bool = True,
                     ernaehrung: str = "", allergien: str = "",
                     mag_nicht: str = "", mag_gern: str = "") -> dict:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            INSERT INTO person (name, rolle, kcal_ziel, eiweiss_pct, fett_pct, kh_pct, portionsfaktor, aktiv,
                                ernaehrung, allergien, mag_nicht, mag_gern)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            name.strip(), rolle, kcal_ziel, int(eiweiss_pct), int(fett_pct), int(kh_pct),
            float(portionsfaktor), bool(aktiv),
            (ernaehrung or "").strip(), (allergien or "").strip(),
            (mag_nicht or "").strip(), (mag_gern or "").strip(),
        )))


async def update_person(person_id: int, name: str, rolle: str = "erwachsener",
                        kcal_ziel: int | None = None, eiweiss_pct: int = 30, fett_pct: int = 30,
                        kh_pct: int = 40, portionsfaktor: float = 1.0, aktiv: bool = True,
                        ernaehrung: str | None = None, allergien: str | None = None,
                        mag_nicht: str | None = None, mag_gern: str | None = None) -> dict | None:
    """Vollstaendiger Ersatz aller Felder (Editor sendet immer das komplette Objekt).
    Praeferenzfelder (ernaehrung/allergien/mag_nicht/mag_gern) werden nur ueberschrieben,
    wenn sie != None sind – so loescht ein Speichern aus dem alten Editor sie nicht."""
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            UPDATE person SET
              name = $2, rolle = $3, kcal_ziel = $4, eiweiss_pct = $5, fett_pct = $6,
              kh_pct = $7, portionsfaktor = $8, aktiv = $9,
              ernaehrung = COALESCE($10, ernaehrung),
              allergien  = COALESCE($11, allergien),
              mag_nicht  = COALESCE($12, mag_nicht),
              mag_gern   = COALESCE($13, mag_gern)
            WHERE id = $1
            RETURNING *
            """,
            int(person_id), name.strip(), rolle, kcal_ziel, int(eiweiss_pct), int(fett_pct),
            int(kh_pct), float(portionsfaktor), bool(aktiv),
            None if ernaehrung is None else ernaehrung.strip(),
            None if allergien is None else allergien.strip(),
            None if mag_nicht is None else mag_nicht.strip(),
            None if mag_gern is None else mag_gern.strip(),
        )))


async def delete_person(person_id: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM person WHERE id = $1", int(person_id))
    if not _affected(res):
        raise NichtGefunden("Person nicht gefunden oder kein Zugriff.")
    return {"deleted": int(person_id)}


# ---------- Personen-Vorlieben & -Memory (Chat + UI) ----------

def _append_csv(vorhanden: str | None, neu: str | None) -> str:
    items = [x.strip() for x in (vorhanden or "").split(",") if x.strip()]
    low = [i.lower() for i in items]
    for n in [x.strip() for x in (neu or "").replace(";", ",").split(",") if x.strip()]:
        if n.lower() not in low:
            items.append(n)
            low.append(n.lower())
    return ", ".join(items)


async def _person_resolve(con, ref):
    """ref = Person-Name (str) oder id -> (id, name) | (None, None)."""
    if isinstance(ref, int) or (isinstance(ref, str) and str(ref).strip().isdigit()):
        r = await con.fetchrow("SELECT id, name FROM person WHERE id = $1", int(ref))
    else:
        r = await con.fetchrow(
            "SELECT id, name FROM person WHERE lower(name) = lower($1) ORDER BY id LIMIT 1", str(ref).strip())
    return (r["id"], r["name"]) if r else (None, None)


async def person_vorlieben_aktualisieren(person_ref, mag_gern=None, mag_nicht=None,
                                         allergien=None, ernaehrung=None) -> dict:
    """Hängt strukturierte Vorlieben an die richtige Person an (mag_gern/mag_nicht/allergien
    werden ergänzt, ernaehrung wird gesetzt). Für den Chat."""
    async with acquire() as con:
        pid, pname = await _person_resolve(con, person_ref)
        if pid is None:
            return {"error": f"Person '{person_ref}' nicht gefunden"}
        row = await con.fetchrow(
            "SELECT mag_gern, mag_nicht, allergien, ernaehrung FROM person WHERE id = $1", pid)
        g = _append_csv(row["mag_gern"], mag_gern) if mag_gern else row["mag_gern"]
        n = _append_csv(row["mag_nicht"], mag_nicht) if mag_nicht else row["mag_nicht"]
        a = _append_csv(row["allergien"], allergien) if allergien else row["allergien"]
        e = ernaehrung.strip() if (ernaehrung or "").strip() else row["ernaehrung"]
        await con.execute(
            "UPDATE person SET mag_gern=$2, mag_nicht=$3, allergien=$4, ernaehrung=$5 WHERE id=$1",
            pid, g, n, a, e)
    return {"ok": True, "person": pname, "mag_gern": g, "mag_nicht": n, "allergien": a, "ernaehrung": e}


async def list_person_notizen(person_id: int) -> list[dict]:
    async with acquire() as con:
        rows = await con.fetch(
            "SELECT id, person_id, text, quelle, erstellt FROM person_notiz "
            "WHERE person_id = $1 ORDER BY erstellt DESC", int(person_id))
    return _jsonable([dict(r) for r in rows])


async def add_person_notiz(person_id: int, text: str, quelle: str = "manuell") -> dict:
    text = (text or "").strip()
    if not text:
        return {"error": "Leere Notiz"}
    async with acquire() as con:
        row = await con.fetchrow(
            "INSERT INTO person_notiz (person_id, text, quelle) VALUES ($1,$2,$3) "
            "RETURNING id, person_id, text, quelle, erstellt",
            int(person_id), text, (quelle if quelle in ("manuell", "chat") else "manuell"))
    return _jsonable(dict(row))


async def update_person_notiz(notiz_id: int, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {"error": "Leere Notiz"}
    async with acquire() as con:
        row = await con.fetchrow(
            "UPDATE person_notiz SET text=$2 WHERE id=$1 RETURNING id, person_id, text, quelle, erstellt",
            int(notiz_id), text)
    return _jsonable(dict(row)) if row else {"error": "nicht gefunden"}


async def delete_person_notiz(notiz_id: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM person_notiz WHERE id = $1", int(notiz_id))
    if not _affected(res):
        raise NichtGefunden("Notiz nicht gefunden oder kein Zugriff.")
    return {"ok": True}


async def person_notiz_speichern(person_ref, text, quelle: str = "chat") -> dict:
    """Speichert eine personenbezogene Memory-Notiz (Chat)."""
    text = (text or "").strip()
    if not text:
        return {"error": "Leere Notiz"}
    async with acquire() as con:
        pid, pname = await _person_resolve(con, person_ref)
        if pid is None:
            return {"error": f"Person '{person_ref}' nicht gefunden"}
        await con.execute(
            "INSERT INTO person_notiz (person_id, text, quelle) VALUES ($1,$2,$3)",
            pid, text, (quelle if quelle in ("manuell", "chat") else "chat"))
    return {"ok": True, "person": pname}


async def get_chat_memory_aktiv() -> bool:
    from .userauth import current_account
    acc = current_account.get() or 1
    async with acquire() as con:
        v = await con.fetchval("SELECT einstellungen->>'chat_memory' FROM account WHERE id = $1", acc)
    return v != "aus"  # Default: an


async def set_chat_memory_aktiv(aktiv: bool) -> dict:
    from .userauth import current_account
    acc = current_account.get() or 1
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{chat_memory}', to_jsonb($2::text)) WHERE id = $1", acc, "an" if aktiv else "aus")
    return {"chat_memory_aktiv": bool(aktiv)}


async def get_auto_bild() -> bool:
    """Ob beim Speichern eines KI-Rezepts automatisch ein Bild erzeugt wird (Default: AUS –
    Bildgenerierung verbraucht spürbar Nutzungsvolumen, daher bewusst opt-in)."""
    from .userauth import current_account
    acc = current_account.get() or 1
    async with acquire() as con:
        v = await con.fetchval("SELECT einstellungen->>'auto_bild' FROM account WHERE id = $1", acc)
    return v == "an"  # Default: aus


async def set_auto_bild(aktiv: bool) -> dict:
    from .userauth import current_account
    acc = current_account.get() or 1
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{auto_bild}', to_jsonb($2::text)) WHERE id = $1", acc, "an" if aktiv else "aus")
    return {"auto_bild_aktiv": bool(aktiv)}


async def list_personen_heute() -> list[dict]:
    """Gibt alle Personen zurueck, die heute mitessen.
    Auto-Init: wenn Tabelle leer, alle aktiven Personen eintragen."""
    async with acquire() as con:
        async with con.transaction():
            count = await con.fetchval("SELECT COUNT(*) FROM personen_heute")
            if count == 0:
                await con.execute(
                    "INSERT INTO personen_heute (person_id) SELECT id FROM person WHERE aktiv = true "
                    "ON CONFLICT DO NOTHING"
                )
            rows = await con.fetch(
                """
                SELECT p.* FROM personen_heute ph
                JOIN person p ON p.id = ph.person_id
                ORDER BY CASE p.rolle WHEN 'erwachsener' THEN 0 ELSE 1 END, p.name
                """
            )
    return _jsonable(_l(rows))


async def set_personen_heute(person_ids: list[int]) -> list[dict]:
    async with acquire() as con:
        async with con.transaction():
            await con.execute("DELETE FROM personen_heute")
            for pid in person_ids:
                await con.execute(
                    "INSERT INTO personen_heute (person_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    int(pid),
                )
    return await list_personen_heute()


async def _ensure_heute_aktuell(con) -> None:
    """Setzt die Tagesauswahl bei Tageswechsel auf die Alltagsgeraete zurueck.
    EINE Zeile pro Konto (geraete_heute_stand ist über account_id eindeutig); die
    Abfrage ist durch RLS bereits auf das aktive Konto beschränkt."""
    today = _today()
    row = await con.fetchrow("SELECT stand_datum FROM geraete_heute_stand LIMIT 1")
    if row is not None and row["stand_datum"] == today:
        return
    await con.execute("DELETE FROM geraete_heute")
    await con.execute("INSERT INTO geraete_heute (geraet_id) SELECT id FROM geraete WHERE standard")
    await con.execute(
        """
        INSERT INTO geraete_heute_stand (stand_datum) VALUES ($1)
        ON CONFLICT (account_id) DO UPDATE SET stand_datum = EXCLUDED.stand_datum
        """,
        today,
    )


async def get_geraete_heute() -> list[dict]:
    async with acquire() as con:
        async with con.transaction():
            await _ensure_heute_aktuell(con)
            rows = await con.fetch(
                "SELECT g.* FROM geraete_heute h JOIN geraete g ON g.id = h.geraet_id ORDER BY g.name"
            )
    return _jsonable(_l(rows))


async def set_geraete_heute(geraet_ids: list[int]) -> list[dict]:
    async with acquire() as con:
        async with con.transaction():
            await con.execute("DELETE FROM geraete_heute")
            if geraet_ids:
                await con.executemany(
                    "INSERT INTO geraete_heute (geraet_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    [(int(i),) for i in geraet_ids],
                )
            # Stand auf heute stempeln, damit die Auswahl nicht sofort wieder
            # auf die Alltagsgeraete zurueckgesetzt wird.
            await con.execute(
                """
                INSERT INTO geraete_heute_stand (stand_datum) VALUES ($1)
                ON CONFLICT (account_id) DO UPDATE SET stand_datum = EXCLUDED.stand_datum
                """,
                _today(),
            )
    return await get_geraete_heute()


# ---------- Lagerorte ----------

async def list_lagerorte() -> list[dict]:
    async with acquire() as con:
        return _jsonable(_l(await con.fetch(
            "SELECT * FROM lagerort ORDER BY sortierung, name"
        )))


async def _ensure_lagerort(con, name: str) -> int:
    row = await con.fetchrow(
        """
        INSERT INTO lagerort (name) VALUES ($1)
        ON CONFLICT (account_id, name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        name.strip(),
    )
    return row["id"]


async def add_lagerort(name: str, sortierung: int = 0) -> dict:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            INSERT INTO lagerort (name, sortierung) VALUES ($1, $2)
            ON CONFLICT (account_id, name) DO UPDATE SET sortierung = EXCLUDED.sortierung
            RETURNING *
            """,
            name.strip(), int(sortierung),
        )))


async def update_lagerort(lagerort_id: int, name: str, sortierung: int = 0) -> dict | None:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            "UPDATE lagerort SET name = $2, sortierung = $3 WHERE id = $1 RETURNING *",
            int(lagerort_id), name.strip(), int(sortierung),
        )))


async def delete_lagerort(lagerort_id: int) -> dict:
    # vorrat.lagerort_id haengt per ON DELETE SET NULL dran.
    async with acquire() as con:
        res = await con.execute("DELETE FROM lagerort WHERE id = $1", int(lagerort_id))
    if not _affected(res):
        raise NichtGefunden("Lagerort nicht gefunden oder kein Zugriff.")
    return {"deleted": int(lagerort_id)}


async def delete_vorrat_by_lagerort(lagerort_id: int) -> dict:
    """Loescht ALLE Vorrats-Artikel eines Lagerorts (fuer 'Bereich neu erfassen').
    Der Lagerort selbst bleibt bestehen."""
    async with acquire() as con:
        res = await con.execute("DELETE FROM vorrat WHERE lagerort_id = $1", int(lagerort_id))
    try:
        n = int(str(res).split()[-1])
    except (ValueError, IndexError):
        n = 0
    return {"deleted": n, "lagerort_id": int(lagerort_id)}


# ---------- Vorrat ----------

async def list_vorrat() -> list[dict]:
    async with acquire() as con:
        return _jsonable(_l(await con.fetch(
            """
            SELECT v.*, z.name AS zutat, lo.name AS lagerort
            FROM vorrat v
            JOIN zutaten z ON z.id = v.zutat_id
            LEFT JOIN lagerort lo ON lo.id = v.lagerort_id
            ORDER BY v.ablaufdatum NULLS LAST, z.name
            """
        )))


async def vorrat_aggregiert() -> list[dict]:
    async with acquire() as con:
        return _jsonable(_l(await con.fetch(
            "SELECT * FROM v_vorrat_aggregiert ORDER BY zutat"
        )))


async def add_vorrat(items: list[dict]) -> list[dict]:
    """items: [{name, menge, einheit, ablaufdatum?, lagerort_id? | ort?, kategorie?}].
    ort (Name) wird zu einem Lagerort aufgeloest/angelegt, falls lagerort_id fehlt."""
    out: list[dict] = []
    async with acquire() as con:
        async with con.transaction():
            for it in items:
                zid = await _ensure_zutat(con, it["name"], it.get("einheit"), it.get("kategorie"))
                lid = it.get("lagerort_id")
                if lid is None and it.get("ort"):
                    lid = await _ensure_lagerort(con, it["ort"])
                row = await con.fetchrow(
                    """
                    INSERT INTO vorrat (zutat_id, menge, einheit, ablaufdatum, lagerort_id)
                    VALUES ($1, $2, $3, $4, $5) RETURNING *
                    """,
                    zid, _num(it["menge"]), it["einheit"], _date(it.get("ablaufdatum")),
                    int(lid) if lid is not None else None,
                )
                out.append(dict(row))
    return _jsonable(out)


async def update_vorrat(vid: int, menge, einheit: str,
                        ablaufdatum=None, lagerort_id: int | None = None) -> dict | None:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            UPDATE vorrat SET menge = $2, einheit = $3, ablaufdatum = $4,
                              lagerort_id = $5, ort = NULL
            WHERE id = $1 RETURNING *
            """,
            int(vid), _num(menge), einheit, _date(ablaufdatum),
            int(lagerort_id) if lagerort_id is not None else None,
        )))


async def delete_vorrat(vid: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM vorrat WHERE id = $1", int(vid))
    if not _affected(res):
        raise NichtGefunden("Vorratsartikel nicht gefunden oder kein Zugriff.")
    return {"deleted": int(vid)}


async def _reduce_vorrat_con(con, zutat_id: int, menge, einheit: str) -> dict:
    """Kernlogik des FIFO-Abzugs auf einer BEREITS offenen Verbindung/Transaktion.
    Ermöglicht atomare Mehrfach-Abzüge (z. B. ein ganzes Rezept, F16)."""
    rest = _num(menge) or Decimal(0)
    geleert: list[int] = []
    rows = await con.fetch(
        """
        SELECT id, menge FROM vorrat
        WHERE zutat_id = $1 AND einheit = $2 AND menge > 0
        ORDER BY ablaufdatum NULLS LAST, id
        FOR UPDATE
        """,
        int(zutat_id), einheit,
    )
    for r in rows:
        if rest <= 0:
            break
        if r["menge"] <= rest:
            rest -= r["menge"]
            await con.execute("DELETE FROM vorrat WHERE id = $1", r["id"])
            geleert.append(r["id"])
        else:
            await con.execute(
                "UPDATE vorrat SET menge = menge - $2 WHERE id = $1", r["id"], rest
            )
            rest = Decimal(0)
    return {
        "zutat_id": int(zutat_id),
        "einheit": einheit,
        "geleerte_positionen": geleert,
        "nicht_gedeckt": float(rest),
    }


async def reduce_vorrat(zutat_id: int, menge, einheit: str) -> dict:
    """Reduziert eine Zutat FIFO nach Ablaufdatum. Gibt nicht gedeckte Restmenge zurueck."""
    async with acquire() as con:
        async with con.transaction():
            return await _reduce_vorrat_con(con, zutat_id, menge, einheit)


async def reduce_vorrat_by_name(name: str, menge, einheit: str | None = None) -> dict:
    """Zieht eine vorhandene Vorrats-Zutat per Name ab. Legt NICHTS an und kann
    nie ins Minus gehen: Ist die Zutat nicht im Vorrat (oder reicht die Menge
    nicht), wird nur das Vorhandene reduziert und der Rest als nicht_gedeckt
    gemeldet. Ohne passende Einheit wird die im Vorrat hinterlegte Einheit
    genommen (haeufigster Bestand zuerst)."""
    angefordert = float(_num(menge) or 0)
    if angefordert <= 0:
        return {"name": name, "error": "Menge muss groesser 0 sein", "abgezogen": 0.0, "nicht_gedeckt": 0.0}
    async with acquire() as con:
        z = await con.fetchrow(
            "SELECT id FROM zutaten WHERE lower(name) = lower($1)", (name or "").strip()
        )
        if z is None:
            return {"name": name, "error": "nicht im Vorrat (Zutat unbekannt)",
                    "abgezogen": 0.0, "nicht_gedeckt": angefordert}
        zid = int(z["id"])
        # Einheit bestimmen: gewuenschte, sonst die mit dem groessten Bestand.
        eff_einheit = einheit
        if not eff_einheit:
            best = await con.fetchrow(
                """SELECT einheit FROM vorrat WHERE zutat_id = $1 AND menge > 0
                   GROUP BY einheit ORDER BY SUM(menge) DESC LIMIT 1""",
                zid,
            )
            if best is None:
                return {"name": name, "error": "nicht im Vorrat",
                        "abgezogen": 0.0, "nicht_gedeckt": angefordert}
            eff_einheit = best["einheit"]
    res = await reduce_vorrat(zid, menge, eff_einheit)
    res["name"] = name
    res["abgezogen"] = round(angefordert - float(res.get("nicht_gedeckt", 0.0)), 4)
    return res


# ---------- Rezepte ----------

def _normalize_zutat(s: str) -> str:
    """Normalisiert einen Zutatnamen fuer den Abgleich: Klammer-Qualifizierer raus,
    klein, Umlaute/ß gefaltet (ä->ae, ö->oe, ü->ue, ß->ss). So matchen ASCII-Schreibweisen
    aus KI-Rezepten ('Olivenoel', 'Haehnchenbrust') auf die Master mit Umlauten."""
    s = re.sub(r"\([^)]*\)", " ", (s or "")).lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return " ".join(s.split())


def _zutat_namensmatch(a: str, b: str) -> bool:
    """Strenger Namensabgleich Vorrat<->Rezept (Fallback, wenn keine Master-Zuordnung).
    Vermeidet falsche Treffer wie 'Mais' <-> 'Mais-Waffeln': deutsche Komposita haben den
    KOPF (Bedeutung) im LETZTEN Wort. Match nur bei Gleichheit oder Praefix/Suffix des
    Kopfwortes ('Öl' passt auf 'Olivenöl', 'Tomate' auf 'Tomaten'; 'Mais' NICHT auf das
    Kopfwort von 'Mais-Waffeln mit Meersalz'). Umlaut-/Klammer-normalisiert."""
    a = _normalize_zutat(a)
    b = _normalize_zutat(b)
    if not a or not b:
        return False
    if a == b:
        return True

    def kopf(s):
        toks = s.replace("-", " ").split()
        return toks[-1] if toks else s

    ka, kb = kopf(a), kopf(b)
    if ka == kb:
        return True
    kurz, lang = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    # Suffix = der kurze Name ist der KOPF des langen (z.B. 'öl' von 'olivenöl') -> Treffer.
    if lang.endswith(kurz):
        return len(kurz) >= 2
    # Praefix nur bei kurzer Endung (Plural: tomate->tomaten); NICHT 'mais'->'maismehl'.
    if lang.startswith(kurz):
        return len(kurz) >= 3 and (len(lang) - len(kurz)) <= 2
    return False


async def _build_vorrat_basis(con) -> tuple[dict, dict]:
    """(vorrat_basis, canon_map). vorrat_basis: kanonische zutat_id → {klasse: basismenge}.
    Identische Aggregation wie in check_vorrat_fuer_rezept (Gebinde-normalisiert,
    Markenartikel unter ihrem Master zusammengefasst) – damit Listen-/Vorschlags-Checks
    mengengenau zur Detail-Ansicht passen."""
    canon = await _load_canon_map(con)
    vrows = await con.fetch(
        """
        SELECT v.zutat_id, v.einheit, SUM(v.menge) AS menge,
               z.gebinde_menge, z.gebinde_einheit
        FROM vorrat v JOIN zutaten z ON z.id = v.zutat_id
        GROUP BY v.zutat_id, v.einheit, z.gebinde_menge, z.gebinde_einheit
        """
    )
    vorrat_basis: dict[int, dict[str, float]] = {}
    for v in vrows:
        cz = canon.get(int(v["zutat_id"]), int(v["zutat_id"]))
        d = vorrat_basis.setdefault(cz, {})
        menge = float(v["menge"] or 0)
        rohklasse, rohfkt = _einheit_basis(v["einheit"])
        d[rohklasse] = d.get(rohklasse, 0.0) + menge * rohfkt
        klasse, basis = _basis_mit_gebinde(
            v["menge"], v["einheit"], v["gebinde_menge"], v["gebinde_einheit"]
        )
        if klasse != rohklasse:
            d[klasse] = d.get(klasse, 0.0) + basis
    return vorrat_basis, canon


def _zutat_ausreichend(vorrat_basis: dict, canon: dict, zutat_id, menge, einheit) -> bool:
    """True, wenn die (kanonisch gematchte) Pflicht-Zutat im Vorrat ist und – bei
    vergleichbarer Einheit – die Menge fuer die Rezept-Basis-Portionen reicht.
    Konsistent zu _match in check_vorrat_fuer_rezept: 'knapp' (gleiche Einheit, zu wenig)
    gilt als NICHT ausreichend; 'vorhanden' (nur andere Einheit) gilt als ausreichend.
    KEIN unscharfer Namens-Match (wie die Detail-Ansicht)."""
    zid = canon.get(int(zutat_id), int(zutat_id))
    vb = vorrat_basis.get(zid)
    if not vb:
        return False
    klasse_b, benoetigt_basis = _basis_mit_gebinde(float(menge or 0), einheit)
    if klasse_b in vb and vb[klasse_b] > 0:
        return vb[klasse_b] >= benoetigt_basis
    return True


async def _fehlende_zutaten_map(con) -> dict:
    """{rezept_id: {fehlend, pflicht}} – Anzahl fehlender Pflicht-Zutaten je Rezept.
    Pflicht = nicht optional und keine Grundzutat. Mengengenau und nur ueber die
    kanonische Master-Zutat (kein Fuzzy-Namensmatch) – damit das 'alles im Vorrat'-
    Badge exakt zur Rezept-Detail-Ansicht (check_vorrat_fuer_rezept) passt."""
    rz_rows = await con.fetch(
        "SELECT rz.rezept_id, rz.zutat_id, rz.menge, rz.einheit, rz.optional FROM rezept_zutaten rz"
    )
    vorrat_basis, canon = await _build_vorrat_basis(con)
    grund_rows = await con.fetch("SELECT id FROM zutaten WHERE grundzutat = true")
    grund_ids = {int(r["id"]) for r in grund_rows}

    by_rez: dict[int, list] = {}
    for rz in rz_rows:
        by_rez.setdefault(int(rz["rezept_id"]), []).append(rz)
    out: dict[int, dict] = {}
    for rid, zs in by_rez.items():
        pflicht = [z for z in zs if not z["optional"] and int(z["zutat_id"]) not in grund_ids]
        fehlend = sum(
            1 for z in pflicht
            if not _zutat_ausreichend(vorrat_basis, canon, z["zutat_id"], z["menge"], z["einheit"])
        )
        out[rid] = {"fehlend": fehlend, "pflicht": len(pflicht)}
    return out


async def _markt_abdeckung_ctx(con, haendler: str, datum: date, vorrat_aktiv: bool) -> dict:
    """Kontext für die Markt-Abdeckung: Angebote des Markts (am Datum gültig) + Vorrat."""
    canon = await _load_canon_map(con)
    grund_ids = {int(r["id"]) for r in await con.fetch("SELECT id FROM zutaten WHERE grundzutat = true")}
    maerkte = [h.strip() for h in str(haendler).split(",") if h.strip()] if haendler else []
    ang_rows = await con.fetch(
        "SELECT a.master_zutat_id, z.name AS master_name FROM angebote a "
        "JOIN zutaten z ON z.id = a.master_zutat_id "
        "WHERE a.haendler = ANY($1) AND a.gueltig_von <= $2 AND a.gueltig_bis >= $2", maerkte, datum)
    angebot_master = {int(a["master_zutat_id"]) for a in ang_rows if a["master_zutat_id"] is not None}
    angebot_namen = [(a["master_name"] or "").lower() for a in ang_rows if a["master_name"]]
    vorrat_ids, vorrat_namen = set(), set()
    if vorrat_aktiv:
        vrows = await con.fetch("SELECT DISTINCT v.zutat_id, z.name FROM vorrat v JOIN zutaten z ON z.id = v.zutat_id")
        vorrat_ids = {canon.get(int(r["zutat_id"]), int(r["zutat_id"])) for r in vrows}
        vorrat_namen = {(r["name"] or "").lower() for r in vrows}
    return {"canon": canon, "grund_ids": grund_ids, "angebot_master": angebot_master,
            "angebot_namen": angebot_namen, "vorrat_ids": vorrat_ids, "vorrat_namen": vorrat_namen}


def _markt_treffer(zs: list, ctx: dict) -> tuple[int, int]:
    """(Anzahl durch Angebote gedeckte Zutaten, Anzahl durch Vorrat gedeckte) – ohne Grundzutaten/optionale."""
    angebot, vorrat = set(), set()
    for z in zs:
        if z["optional"] or int(z["zutat_id"]) in ctx["grund_ids"]:
            continue
        zid = int(z["zutat_id"])
        mid = ctx["canon"].get(zid, zid)
        zn = (z["zutat"] or "").lower()
        if mid in ctx["angebot_master"] or any(_zutat_namensmatch(zn, mn) for mn in ctx["angebot_namen"]):
            angebot.add(mid)
        if mid in ctx["vorrat_ids"] or any(_zutat_namensmatch(zn, vn) for vn in ctx["vorrat_namen"]):
            vorrat.add(mid)
    return len(angebot), len(vorrat)


def _geraete_sig_von(namen) -> str:
    """Signatur einer Gerätekombination (sortiert, kleingeschrieben) für den
    „auf die Küche abgestimmt"-Vergleich."""
    return "|".join(sorted((n or "").strip().lower() for n in (namen or []) if (n or "").strip()))


async def search_rezepte(query: str | None = None, gang: str | None = None, kueche: str | None = None,
                         zutaten: list | None = None, markt: str | None = None,
                         vorrat_aktiv: bool = True, datum: date | None = None) -> list[dict]:
    from .userauth import current_account
    _acc_list = current_account.get()
    gang = _norm_kat(gang, GANG_LISTE)
    kueche = _norm_kat(kueche, KUECHE_LISTE)
    zutaten = [z.strip() for z in (zutaten or []) if z and z.strip()]
    async with acquire() as con:
        conds, params, i = [], [], 1
        if query:
            conds.append(f"(r.name ILIKE ${i} OR r.beschreibung ILIKE ${i})"); params.append(f"%{query}%"); i += 1
        if gang:
            conds.append(f"r.gang = ${i}"); params.append(gang); i += 1
        if kueche:
            conds.append(f"r.kueche = ${i}"); params.append(kueche); i += 1
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        rows = await con.fetch(
            f"SELECT r.*, b.sterne FROM rezepte r LEFT JOIN bewertung b ON b.rezept_id = r.id{where} ORDER BY r.name",
            *params)
        fmap = await _fehlende_zutaten_map(con)
        rez_zutaten: dict[int, list] = {}
        if zutaten or markt:
            for rz in await con.fetch(
                    "SELECT rz.rezept_id, rz.zutat_id, z.name AS zutat, rz.optional "
                    "FROM rezept_zutaten rz JOIN zutaten z ON z.id = rz.zutat_id"):
                rez_zutaten.setdefault(int(rz["rezept_id"]), []).append(dict(rz))
        markt_ctx = await _markt_abdeckung_ctx(con, markt, datum or _today(), vorrat_aktiv) if markt else None
        cur_sig = _geraete_sig_von([x["name"] for x in await con.fetch("SELECT name FROM geraete")])
    schnitt = await _bewertung_schnitt_map()
    out = []
    for r in rows:
        rid = int(r["id"])
        zs = rez_zutaten.get(rid, [])
        # Zutaten-UND-Filter: jede gesuchte Zutat muss im Rezept vorkommen.
        if zutaten and not all(any(_zutat_namensmatch(term, (z["zutat"] or "")) for z in zs) for term in zutaten):
            continue
        d = dict(r)
        info = fmap.get(rid, {})
        d["fehlend"] = info.get("fehlend")
        d["pflicht_zutaten"] = info.get("pflicht")
        bw = schnitt.get(rid)
        d["bewertung_schnitt"] = bw["schnitt"] if bw else None
        d["bewertung_anzahl"] = bw["anzahl"] if bw else 0
        d["sterne"] = round(bw["schnitt"]) if bw else None
        # Vollbild nicht in die Liste (Performance) – nur ein Flag. Sichtbar: eigene Bilder
        # sowie die VERÖFFENTLICHTER fremder Rezepte – dieselbe Regel wie im Detail
        # (get_rezept) und am Thumbnail-Endpoint (get_rezept_bild). Vorher galten fremde
        # Rezepte in der Liste pauschal als bildlos („Bilder sind privat") – ein Rest des
        # alten Token-Anreiz-Modells: Detail zeigte das Bild, die Liste den Platzhalter.
        eigen = _acc_list is None or d.get("account_id") is None or d.get("account_id") == _acc_list
        d["hat_bild"] = bool(d.get("bild")) and (eigen or bool(d.get("veroeffentlicht")))
        d.pop("bild", None)
        # „Auf die Küche abgestimmt": eigenes Rezept + Signatur == aktuelle Geräte.
        d["geraete_abgestimmt"] = bool(eigen and d.get("geraete_sig") and d.get("geraete_sig") == cur_sig)
        d.pop("geraete_sig", None)
        if markt_ctx is not None:
            at, vt = _markt_treffer(zs, markt_ctx)
            d["angebot_treffer"], d["vorrat_treffer"] = at, vt
            if at < 1:
                continue  # nur Rezepte zeigen, die mind. einen Angebotsartikel nutzen
        out.append(d)
    if markt_ctx is not None:
        out.sort(key=lambda x: (-(x.get("angebot_treffer", 0) + x.get("vorrat_treffer", 0)),
                                -(x.get("sterne") or 0), x.get("name", "")))
    return _jsonable(out)


async def rezept_angebote(rezept_id: int, markt: str | None, datum: date | None = None) -> dict:
    """Welche (nicht-optionalen) Zutaten eines Rezepts sind aktuell im Angebot der
    gewaehlten Maerkte? -> {zutat_id: {haendler, name, preis_angebot, einheit}}.
    Match ueber Master-/Kanonik-Zutat (Fallback: Namensaehnlichkeit zum Master-Namen)."""
    r = await get_rezept(rezept_id)
    if not r:
        return {}
    # Markt optional: ohne Markt → ALLE aktuell gültigen Angebote (marktübergreifend).
    maerkte = [h.strip() for h in str(markt).split(",") if h.strip()] if markt else []
    datum = datum or _today()
    async with acquire() as con:
        canon = await _load_canon_map(con)
        if maerkte:
            ang_rows = await con.fetch(
                "SELECT a.master_zutat_id, a.name, a.haendler, a.preis_angebot, a.einheit, "
                "z.name AS master_name FROM angebote a JOIN zutaten z ON z.id = a.master_zutat_id "
                "WHERE a.haendler = ANY($1) AND a.gueltig_von <= $2 AND a.gueltig_bis >= $2 "
                "AND a.master_zutat_id IS NOT NULL", maerkte, datum)
        else:
            ang_rows = await con.fetch(
                "SELECT a.master_zutat_id, a.name, a.haendler, a.preis_angebot, a.einheit, "
                "z.name AS master_name FROM angebote a JOIN zutaten z ON z.id = a.master_zutat_id "
                "WHERE a.gueltig_von <= $1 AND a.gueltig_bis >= $1 "
                "AND a.master_zutat_id IS NOT NULL", datum)
    by_master: dict = {}
    name_index: list = []
    for a in ang_rows:
        mid = int(a["master_zutat_id"])
        pa = a["preis_angebot"]
        cur = by_master.get(mid)
        if cur is None or (pa is not None and (cur["preis_angebot"] is None or pa < cur["preis_angebot"])):
            by_master[mid] = a
        if a["master_name"]:
            name_index.append(((a["master_name"] or "").lower(), a))
    treffer: dict = {}
    for z in r["zutaten"]:
        if z.get("optional"):
            continue
        zid = int(z["zutat_id"])
        mid = canon.get(zid, zid)
        zn = (z["zutat"] or "").lower()
        ang = by_master.get(mid) or next((a for (mn, a) in name_index if _zutat_namensmatch(zn, mn)), None)
        if ang is not None:
            treffer[zid] = {"haendler": ang["haendler"], "name": ang["name"],
                            "preis_angebot": ang["preis_angebot"], "einheit": ang["einheit"]}
    return _jsonable(treffer)


def _flatten_zubereitung(zub):
    """Geräteneutrale Fassung: pro Komponente genau EINE Variante (bevorzugt die ohne
    Gerät, sonst die erste), Geräte-Bezug entfernt. Für veröffentlichte Rezepte beim
    Lesen durch Fremd-Konten + beim Import (global freigegebene Rezepte sind nicht
    gerätespezifisch)."""
    if not isinstance(zub, list):
        return zub
    out = []
    for k in zub:
        if not isinstance(k, dict):
            continue
        vs = k.get("varianten") or []
        v = next((x for x in vs if not (x.get("geraet") or "").strip()), None) or (vs[0] if vs else {})
        out.append({"titel": k.get("titel"), "varianten": [{"geraet": None, "text": v.get("text", "")}]})
    return out


async def get_rezept(rezept_id: int) -> dict | None:
    async with acquire() as con:
        r = await con.fetchrow("SELECT * FROM rezepte WHERE id = $1", int(rezept_id))
        if r is None:
            return None
        zut = await con.fetch(
            """
            SELECT rz.zutat_id, z.name AS zutat, rz.menge, rz.einheit, rz.optional,
                   COALESCE(z.kanonische_zutat_id, z.id) AS master_zutat_id,
                   COALESCE(m.name, z.name)              AS master_name
            FROM rezept_zutaten rz
            JOIN zutaten z ON z.id = rz.zutat_id
            LEFT JOIN zutaten m ON m.id = z.kanonische_zutat_id
            WHERE rz.rezept_id = $1 ORDER BY z.name
            """,
            int(rezept_id),
        )
        ger = await con.fetch(
            """
            SELECT rg.geraet_id, g.name AS geraet, rg.pflicht
            FROM rezept_geraete rg JOIN geraete g ON g.id = rg.geraet_id
            WHERE rg.rezept_id = $1 ORDER BY g.name
            """,
            int(rezept_id),
        )
        bew = await con.fetchrow("SELECT * FROM bewertung WHERE rezept_id = $1", int(rezept_id))
        cur_sig = _geraete_sig_von([x["name"] for x in await con.fetch("SELECT name FROM geraete")])
    d = dict(r)
    d["zutaten"] = _l(zut)
    d["geraete"] = _l(ger)
    d["bewertung"] = dict(bew) if bew else None
    schnitt = await _bewertung_schnitt_map()
    bw = schnitt.get(int(rezept_id))
    d["bewertung_schnitt"] = bw["schnitt"] if bw else None
    d["bewertung_anzahl"] = bw["anzahl"] if bw else 0
    from .userauth import current_account
    acc = current_account.get()
    own = acc is not None and d.get("account_id") == acc
    # „Auf die Küche abgestimmt": eigenes Rezept + Signatur == aktuelle Geräte.
    d["geraete_abgestimmt"] = bool(own and d.get("geraete_sig") and d.get("geraete_sig") == cur_sig)
    d.pop("geraete_sig", None)
    # Fremde (veröffentlichte/globale) Rezepte: geräteneutral darstellen.
    if not own:
        d["zubereitung"] = _flatten_zubereitung(d.get("zubereitung"))
    # Bild: für ANDERE nur bei veröffentlichten Rezepten sichtbar (Ersteller-Bild im Pool);
    # beim Import wird es mitkopiert (siehe importiere_rezept).
    if d.get("bild") and not own and not d.get("veroeffentlicht"):
        d["bild"] = None
    d["hat_bild"] = bool(d.get("bild"))
    return _jsonable(d)


async def get_rezept_bild(rezept_id: int) -> dict:
    """Liefert nur das Rezeptbild (Data-URL) – fuer Listen-Thumbnails (lazy).
    Sichtbar fuer das eigene Konto ODER bei veroeffentlichten Rezepten (Ersteller-Bild
    im oeffentlichen Pool)."""
    from .userauth import current_account
    acc = current_account.get()
    async with acquire() as con:
        row = await con.fetchrow(
            "SELECT bild, account_id, veroeffentlicht FROM rezepte WHERE id = $1", int(rezept_id))
    if row is None:
        return {"bild": None}
    bild = row["bild"]
    own = acc is not None and row["account_id"] == acc
    if bild and not own and not row["veroeffentlicht"]:
        bild = None
    return {"bild": bild}


GANG_LISTE = ["Frühstück", "Vorspeise", "Suppe", "Salat", "Hauptgericht", "Beilage",
              "Snack", "Nachspeise", "Kuchen & Torten", "Brot & Backwaren",
              "Getränk", "Soße & Dip"]
KUECHE_LISTE = ["Deutsch", "Italienisch", "Mediterran", "Asiatisch", "Mexikanisch",
                "Indisch", "Orientalisch", "Amerikanisch", "International"]


def _norm_kat(v, liste):
    """Kategorie nur akzeptieren, wenn sie in der festen Liste steht (sonst None)."""
    v = (v or "").strip()
    return v if v in liste else None


async def rezept_kategorien() -> dict:
    """Feste Gang-/Küche-Listen (für Formulare) + die im Konto tatsächlich genutzten
    Werte mit Anzahl (für die Filter-Vorauswahl, häufigste zuerst)."""
    async with acquire() as con:
        kg = await con.fetch(
            "SELECT kueche AS wert, count(*) AS anzahl FROM rezepte "
            "WHERE kueche IS NOT NULL AND kueche <> '' GROUP BY kueche ORDER BY count(*) DESC, kueche")
        gg = await con.fetch(
            "SELECT gang AS wert, count(*) AS anzahl FROM rezepte "
            "WHERE gang IS NOT NULL AND gang <> '' GROUP BY gang ORDER BY count(*) DESC, gang")
    return {"gaenge": GANG_LISTE, "kuechen": KUECHE_LISTE,
            "kuechen_genutzt": [dict(r) for r in kg], "gaenge_genutzt": [dict(r) for r in gg]}


async def add_rezept(name: str, beschreibung: str | None = None, anleitung: str | None = None,
                     portionen: int = 2, dauer_minuten: int | None = None, quelle: str | None = None,
                     zutaten: list[dict] | None = None, geraete: list[dict] | None = None,
                     zubereitung: list | None = None, gang: str | None = None,
                     kueche: str | None = None) -> dict:
    """zutaten: [{name, menge, einheit, optional?}]; geraete: [{name|geraet_id, pflicht?}];
    zubereitung: [{titel, varianten:[{geraet, text}]}] (geraet=Name oder null)."""
    async with acquire() as con:
        async with con.transaction():
            r = await con.fetchrow(
                """
                INSERT INTO rezepte (name, beschreibung, anleitung, portionen, dauer_minuten, quelle, zubereitung, gang, kueche)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id
                """,
                name, beschreibung, anleitung, int(portionen),
                int(dauer_minuten) if dauer_minuten is not None else None, quelle, zubereitung,
                _norm_kat(gang, GANG_LISTE), _norm_kat(kueche, KUECHE_LISTE),
            )
            rid = r["id"]
            for z in (zutaten or []):
                zid = await _ensure_zutat(con, z["name"], z.get("einheit"))
                await con.execute(
                    """
                    INSERT INTO rezept_zutaten (rezept_id, zutat_id, menge, einheit, optional)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (rezept_id, zutat_id) DO UPDATE
                      SET menge = EXCLUDED.menge, einheit = EXCLUDED.einheit, optional = EXCLUDED.optional
                    """,
                    rid, zid, _num(z.get("menge")), z.get("einheit"), bool(z.get("optional", False)),
                )
            for g in (geraete or []):
                gid = g.get("geraet_id")
                if gid is None and g.get("name"):
                    gr = await con.fetchrow(
                        """
                        INSERT INTO geraete (name) VALUES ($1)
                        ON CONFLICT (account_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id
                        """,
                        g["name"],
                    )
                    gid = gr["id"]
                if gid is not None:
                    await con.execute(
                        """
                        INSERT INTO rezept_geraete (rezept_id, geraet_id, pflicht)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (rezept_id, geraet_id) DO UPDATE SET pflicht = EXCLUDED.pflicht
                        """,
                        rid, int(gid), bool(g.get("pflicht", True)),
                    )
    return await get_rezept(rid)


async def update_rezept(rezept_id: int, name: str, beschreibung: str | None = None,
                        anleitung: str | None = None, portionen: int = 2,
                        dauer_minuten: int | None = None, quelle: str | None = None,
                        zutaten: list[dict] | None = None, geraete: list[dict] | None = None,
                        zubereitung: list | None = None, gang: str | None = None,
                        kueche: str | None = None) -> dict | None:
    """Aktualisiert ein Rezept und ersetzt dessen Zutaten und Geraete vollstaendig."""
    async with acquire() as con:
        async with con.transaction():
            r = await con.fetchrow(
                """
                UPDATE rezepte SET
                  name = $2, beschreibung = $3, anleitung = $4,
                  portionen = $5, dauer_minuten = $6, quelle = $7,
                  zubereitung = $8, gang = $9, kueche = $10, updated_at = now()
                WHERE id = $1 RETURNING id
                """,
                int(rezept_id), name, beschreibung, anleitung, int(portionen),
                int(dauer_minuten) if dauer_minuten is not None else None, quelle, zubereitung,
                _norm_kat(gang, GANG_LISTE), _norm_kat(kueche, KUECHE_LISTE),
            )
            if r is None:
                return None
            rid = r["id"]
            # Strukturierte Kochmodus-Schritte gehören zur alten Zubereitung → verwerfen.
            await con.execute("UPDATE rezepte SET zubereitung_guided = NULL WHERE id = $1", rid)
            try:
                async with con.transaction():
                    await con.execute("DELETE FROM kochmodus_schritte WHERE rezept_id = $1", rid)
            except Exception:  # Tabelle fehlt (Migration noch nicht gelaufen)
                pass
            # Zutaten komplett ersetzen
            await con.execute("DELETE FROM rezept_zutaten WHERE rezept_id = $1", rid)
            for z in (zutaten or []):
                zid = await _ensure_zutat(con, z["name"], z.get("einheit"))
                await con.execute(
                    """
                    INSERT INTO rezept_zutaten (rezept_id, zutat_id, menge, einheit, optional)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (rezept_id, zutat_id) DO UPDATE
                      SET menge = EXCLUDED.menge, einheit = EXCLUDED.einheit, optional = EXCLUDED.optional
                    """,
                    rid, zid, _num(z.get("menge")), z.get("einheit"), bool(z.get("optional", False)),
                )
            # Geraete komplett ersetzen
            await con.execute("DELETE FROM rezept_geraete WHERE rezept_id = $1", rid)
            for g in (geraete or []):
                gid = g.get("geraet_id")
                if gid is None and g.get("name"):
                    gr = await con.fetchrow(
                        """
                        INSERT INTO geraete (name) VALUES ($1)
                        ON CONFLICT (account_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id
                        """,
                        g["name"],
                    )
                    gid = gr["id"]
                if gid is not None:
                    await con.execute(
                        """
                        INSERT INTO rezept_geraete (rezept_id, geraet_id, pflicht)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (rezept_id, geraet_id) DO UPDATE SET pflicht = EXCLUDED.pflicht
                        """,
                        rid, int(gid), bool(g.get("pflicht", True)),
                    )
    return await get_rezept(rid)


async def delete_rezept(rezept_id: int) -> dict:
    # rezept_zutaten und rezept_geraete haengen per ON DELETE CASCADE dran.
    # RLS (rezepte_mod) loescht nur EIGENE Rezepte; fremde/globale bleiben unberuehrt.
    async with acquire() as con:
        res = await con.execute("DELETE FROM rezepte WHERE id = $1", int(rezept_id))
    if not _affected(res):
        raise NichtGefunden("Rezept nicht gefunden oder kein Zugriff.")
    return {"deleted": int(rezept_id), "ok": True}


async def rezepte_vorschlagen(limit: int = 10) -> list[dict]:
    """Rezepte vorschlagen mit:
    - Geraete-Check: falls zubereitung vorhanden, braucht jede Komponente mind. eine passende
      Variante fuer ein heute-Geraet (oder eine ohne-Geraet-Variante). Fallback: alte
      Pflicht-Geraete-Logik fuer Rezepte ohne strukturierte Zubereitung.
    - Zutaten-Abdeckung: bidirektionale Namenssuche ('Oel' matched 'Olivenoel' und umgekehrt).
    - Sortierung: wenigste fehlende Zutaten zuerst."""
    async with acquire() as con:
        await _ensure_heute_aktuell(con)

        heute_rows = await con.fetch(
            "SELECT g.id, g.name FROM geraete_heute h JOIN geraete g ON g.id = h.geraet_id"
        )
        heute_ids: set[int] = {r["id"] for r in heute_rows}
        heute_namen: set[str] = {r["name"].lower() for r in heute_rows}

        rez_rows = await con.fetch(
            "SELECT id, name, account_id, zubereitung, portionen, (bild IS NOT NULL) AS hat_bild FROM rezepte ORDER BY name")

        rz_rows = await con.fetch(
            """
            SELECT rz.rezept_id, rz.zutat_id, z.name AS zutat, rz.menge, rz.einheit, rz.optional
            FROM rezept_zutaten rz JOIN zutaten z ON z.id = rz.zutat_id
            """
        )
        rz_map: dict[int, list] = {}
        for rz in rz_rows:
            rz_map.setdefault(int(rz["rezept_id"]), []).append(dict(rz))

        rg_rows = await con.fetch("SELECT rezept_id, geraet_id, pflicht FROM rezept_geraete")
        rg_map: dict[int, list] = {}
        for rg in rg_rows:
            rg_map.setdefault(int(rg["rezept_id"]), []).append(dict(rg))

        bew_rows = await con.fetch("SELECT rezept_id, sterne FROM bewertung")
        bew_map: dict[int, int] = {int(r["rezept_id"]): int(r["sterne"]) for r in bew_rows}

        # Mengengenauer Vorrat-Abgleich – nur kanonischer Master-Match, Mengen zaehlen
        # (konsistent zu check_vorrat_fuer_rezept und _fehlende_zutaten_map).
        vorrat_basis, canon = await _build_vorrat_basis(con)
        grund_rows = await con.fetch("SELECT id FROM zutaten WHERE grundzutat = true")
        grund_ids: set[int] = {int(r["id"]) for r in grund_rows}

    def geraet_passt(geraet_name: str | None) -> bool:
        if not geraet_name:
            return True  # ohne Geraet = immer machbar
        gn = geraet_name.lower()
        return any(gn in hn or hn in gn for hn in heute_namen)

    def geraete_machbar(rid: int, zubereitung: list | None) -> bool:
        if not heute_ids:
            return True  # keine Auswahl = alle Rezepte zeigen
        if zubereitung:
            # Smart: jede Komponente braucht mind. eine machbare Variante
            for komp in zubereitung:
                varianten = komp.get("varianten", [])
                if varianten and not any(geraet_passt(v.get("geraet")) for v in varianten):
                    return False
            return True
        # Fallback: alle Pflicht-Geraete muessen heute ausgewaehlt sein
        rg = rg_map.get(rid, [])
        return not any(g["pflicht"] and g["geraet_id"] not in heute_ids for g in rg)

    # Eigene Bibliothek hat Vorrang: öffentliche Rezepte überspringen, wenn der Nutzer
    # ein gleichnamiges eigenes Rezept besitzt (keine Doppel-Anzeige Eigen + Öffentlich).
    from .userauth import current_account
    _acc = current_account.get()
    eigene_namen = {(r["name"] or "").strip().lower() for r in rez_rows
                    if _acc is not None and r["account_id"] == _acc}

    result = []
    for rez in rez_rows:
        rid = int(rez["id"])
        if (_acc is not None and rez["account_id"] != _acc
                and (rez["name"] or "").strip().lower() in eigene_namen):
            continue
        zub = rez["zubereitung"] or []

        if not geraete_machbar(rid, zub):
            continue

        zutaten = rz_map.get(rid, [])
        pflicht = [z for z in zutaten
                   if not z["optional"] and int(z["zutat_id"]) not in grund_ids]
        n_vorhanden = sum(
            1 for z in pflicht
            if _zutat_ausreichend(vorrat_basis, canon, z["zutat_id"], z["menge"], z["einheit"])
        )
        n_pflicht = len(pflicht)

        result.append({
            "rezept_id": rid,
            "rezept": rez["name"],
            "portionen": int(rez["portionen"] or 2),
            "pflicht_zutaten": n_pflicht,
            "davon_vorhanden": n_vorhanden,
            "fehlend": n_pflicht - n_vorhanden,
            "sterne": bew_map.get(rid),
            "hat_bild": bool(rez["hat_bild"]),
        })

    # Sortierung: wenigste fehlende Zutaten → höhere Bewertung → mehr vorhanden
    result.sort(key=lambda x: (x["fehlend"], -(x["sterne"] or 0), -x["davon_vorhanden"]))
    return _jsonable(result[:int(limit)])


async def rezepte_aus_angeboten(haendler: str, datum: date, limit: int = 8) -> list[dict]:
    """Koch-Ideen aus den Angeboten: Rezepte, die moeglichst viele Zutaten aus den
    am Datum gueltigen Angeboten des Markts verwenden. Match ueber die Master-Zutat
    (angebot.master_zutat_id ↔ kanonisierte Rezept-Zutat). Sortiert nach Anzahl
    Angebots-Treffer, dann Bewertung."""
    if not haendler:
        return []
    async with acquire() as con:
        ang_rows = await con.fetch(
            """SELECT a.master_zutat_id, z.name AS master_name, a.name, a.preis_angebot
               FROM angebote a JOIN zutaten z ON z.id = a.master_zutat_id
               WHERE a.haendler = $1
                 AND a.gueltig_von <= $2 AND a.gueltig_bis >= $2""",
            haendler, datum,
        )
        rz_rows = await con.fetch(
            "SELECT rz.rezept_id, rz.zutat_id, z.name AS zutat, rz.optional "
            "FROM rezept_zutaten rz JOIN zutaten z ON z.id = rz.zutat_id"
        )
        rez_rows = await con.fetch("SELECT id, name FROM rezepte")
        grund_rows = await con.fetch("SELECT id FROM zutaten WHERE grundzutat = true")
        bew_rows = await con.fetch("SELECT rezept_id, sterne FROM bewertung")
        canon = await _load_canon_map(con)

    grund_ids = {int(r["id"]) for r in grund_rows}
    bew_map = {int(r["rezept_id"]): int(r["sterne"]) for r in bew_rows}
    namen = {int(r["id"]): r["name"] for r in rez_rows}
    # Angebote je Master (id ODER Name): guenstigstes behalten.
    angebot_master: dict[int, dict] = {}
    angebot_namen: list[tuple] = []   # (master_name_lower, {name, preis})
    for a in ang_rows:
        rec = {"name": a["name"], "preis_angebot": a["preis_angebot"]}
        mid = a["master_zutat_id"]
        if mid is not None:
            prev = angebot_master.get(int(mid))
            if prev is None or (a["preis_angebot"] or 1e9) < (prev["preis_angebot"] or 1e9):
                angebot_master[int(mid)] = rec
        mn = (a["master_name"] or "").lower()
        if mn:
            angebot_namen.append((mn, rec))
    if not angebot_master and not angebot_namen:
        return []

    by_rez: dict[int, list] = {}
    for rz in rz_rows:
        by_rez.setdefault(int(rz["rezept_id"]), []).append(rz)

    result = []
    for rid, zs in by_rez.items():
        treffer = []
        gesehen = set()
        for z in zs:
            if z["optional"] or int(z["zutat_id"]) in grund_ids:
                continue
            mid = canon.get(int(z["zutat_id"]), int(z["zutat_id"]))
            zn = (z["zutat"] or "").lower()
            # Treffer ueber Master-id ODER Namens-Substring.
            a = angebot_master.get(mid)
            if a is None and zn:
                for mn, rec in angebot_namen:
                    if _name_match(mn, z["zutat"]):
                        a = rec
                        break
            schluessel = a["name"] if a else None
            if a and schluessel not in gesehen:
                gesehen.add(schluessel)
                treffer.append({
                    "zutat": z["zutat"], "angebot": a["name"],
                    "preis_angebot": float(a["preis_angebot"]) if a["preis_angebot"] is not None else None,
                })
        if treffer:
            result.append({
                "rezept_id": rid,
                "rezept": namen.get(rid, ""),
                "treffer": len(treffer),
                "angebote": treffer,
                "sterne": bew_map.get(rid),
            })
    result.sort(key=lambda x: (-x["treffer"], -(x["sterne"] or 0), x["rezept"].lower()))
    return _jsonable(result[:int(limit)])


async def set_bewertung(rezept_id: int, sterne: int, kommentar: str | None = None) -> dict:
    # Eine Bewertung je Konto und Rezept (UNIQUE(account_id, rezept_id)); bei
    # veröffentlichten Rezepten bilden alle Konten zusammen den Durchschnitt.
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            INSERT INTO bewertung (rezept_id, sterne, kommentar)
            VALUES ($1, $2, $3)
            ON CONFLICT (account_id, rezept_id) DO UPDATE
              SET sterne = EXCLUDED.sterne, kommentar = EXCLUDED.kommentar,
                  bewertet_am = now()
            RETURNING *
            """,
            int(rezept_id), int(sterne), kommentar,
        )))


async def set_rezept_bild(rezept_id: int, data_url: str | None) -> dict:
    """Speichert/löscht das Rezeptbild (Data-URL). Nur eigene Rezepte (RLS)."""
    async with acquire() as con:
        row = await con.fetchrow(
            "UPDATE rezepte SET bild = $2, updated_at = now() WHERE id = $1 RETURNING id",
            int(rezept_id), data_url)
    if row is None:
        return {"error": "Rezept nicht gefunden oder nicht eigenes"}
    return {"id": int(rezept_id), "hat_bild": bool(data_url)}


async def _bewertung_schnitt_map() -> dict:
    """rezept_id -> {schnitt, anzahl} über ALLE Konten (für veröffentlichte Rezepte
    = Ø aller Nutzer). bypass, da kontoübergreifend aggregiert wird."""
    async with acquire(bypass=True) as con:
        rows = await con.fetch(
            "SELECT rezept_id, AVG(sterne)::float AS schnitt, COUNT(*) AS anzahl "
            "FROM bewertung GROUP BY rezept_id")
    return {int(r["rezept_id"]): {"schnitt": float(r["schnitt"]), "anzahl": int(r["anzahl"])} for r in rows}


async def _nicht_globale_zutaten(con, rezept_id: int) -> list:
    """Zutaten eines Rezepts, die NICHT global sind (account-eigen)."""
    return await con.fetch(
        "SELECT DISTINCT z.id, z.name, z.kanonische_zutat_id "
        "FROM rezept_zutaten rz JOIN zutaten z ON z.id = rz.zutat_id "
        "WHERE rz.rezept_id = $1 AND z.account_id IS NOT NULL ORDER BY z.name",
        int(rezept_id))


async def _repoint_rezept_zutat(con, rid: int, alt: int, neu: int) -> None:
    """Haengt eine Rezeptzutat-Referenz von alt auf neu um (Dublette vermeiden)."""
    if alt == neu:
        return
    hat = await con.fetchval(
        "SELECT 1 FROM rezept_zutaten WHERE rezept_id=$1 AND zutat_id=$2", rid, neu)
    if hat:
        await con.execute("DELETE FROM rezept_zutaten WHERE rezept_id=$1 AND zutat_id=$2", rid, alt)
    else:
        await con.execute(
            "UPDATE rezept_zutaten SET zutat_id=$2 WHERE rezept_id=$1 AND zutat_id=$3", rid, neu, alt)


async def globalisiere_rezept_zutaten(rezept_id: int) -> list:
    """Stellt sicher, dass alle Zutaten eines Rezepts auf GLOBALE Master zeigen:
    zeigt eine account-eigene Zutat auf einen globalen Master -> Rezept dorthin
    umhaengen; gibt es einen gleichnamigen globalen Master -> damit verknuepfen;
    sonst die Zutat global machen (account_id NULL). Bypass. Gibt Aktionsliste."""
    rid = int(rezept_id)
    aktionen = []
    async with acquire(bypass=True) as con:
        async with con.transaction():
            for r in await _nicht_globale_zutaten(con, rid):
                zid = r["id"]
                nm = (r["name"] or "").strip()
                # a) zeigt bereits auf einen globalen Master?
                if r["kanonische_zutat_id"] is not None:
                    m = await con.fetchrow(
                        "SELECT id, account_id FROM zutaten WHERE id=$1", r["kanonische_zutat_id"])
                    if m and m["account_id"] is None:
                        await _repoint_rezept_zutat(con, rid, zid, m["id"])
                        aktionen.append({"zutat": nm, "aktion": "auf globalen Master umgehängt"})
                        continue
                # b) gleichnamiger globaler Master vorhanden?
                g = await con.fetchrow(
                    "SELECT id FROM zutaten WHERE account_id IS NULL AND kanonische_zutat_id IS NULL "
                    "AND lower(name)=lower($1) LIMIT 1", nm)
                if g:
                    await _repoint_rezept_zutat(con, rid, zid, g["id"])
                    aktionen.append({"zutat": nm, "aktion": "mit globaler Zutat verknüpft"})
                    continue
                # c) keinen globalen Treffer -> Zutat global machen
                await con.execute("UPDATE zutaten SET account_id = NULL WHERE id=$1", zid)
                aktionen.append({"zutat": nm, "aktion": "global angelegt"})
    return aktionen


async def set_veroeffentlicht(rezept_id: int, veroeffentlicht: bool,
                              globalisieren: bool = False, als_admin: bool = False) -> dict:
    """Gibt ein Rezept frei (veröffentlicht → für alle Konten sichtbar) oder nimmt es
    zurück. Eigentümer wirken via RLS nur auf EIGENE Rezepte; ein Admin (als_admin=True)
    darf per Bypass JEDES Rezept zurückziehen/freigeben. Vor der Freigabe MÜSSEN alle
    Zutaten global sein; nicht-globale werden mit globalisieren=True zuvor global gemacht."""
    rid = int(rezept_id)
    if veroeffentlicht:
        # Regeln: importierte Kopien nie veröffentlichbar; jedes Rezept nur EINMAL.
        async with acquire(bypass=als_admin) as con:
            meta = await con.fetchrow(
                "SELECT importiert, je_veroeffentlicht FROM rezepte WHERE id = $1", rid)
        if meta is None:
            return {"error": "Rezept nicht gefunden oder nicht eigenes"}
        if meta["importiert"]:
            return {"error": "Importierte Rezepte können nicht veröffentlicht werden – "
                             "bitte teile nur selbst erstellte Rezepte (Urheberrecht der Quelle)."}
        if meta["je_veroeffentlicht"]:
            return {"error": "Dieses Rezept wurde bereits veröffentlicht – das geht nur einmal."}
        async with acquire(bypass=True) as con:
            offen = await _nicht_globale_zutaten(con, rid)
        if offen:
            if not globalisieren:
                return {"benoetigt_globalisierung": True,
                        "nicht_global": [r["name"] for r in offen],
                        "rezept_id": rid}
            await globalisiere_rezept_zutaten(rid)
    async with acquire(bypass=als_admin) as con:
        row = await con.fetchrow(
            "UPDATE rezepte SET veroeffentlicht = $2, "
            "je_veroeffentlicht = je_veroeffentlicht OR $2, updated_at = now() "
            "WHERE id = $1 RETURNING id, veroeffentlicht",
            rid, bool(veroeffentlicht))
    if row is None:
        return {"error": "Rezept nicht gefunden oder nicht eigenes"}
    return {"id": int(row["id"]), "veroeffentlicht": bool(row["veroeffentlicht"])}


async def importiere_rezept(rezept_id: int) -> dict:
    """Kopiert ein (öffentliches) Rezept als EIGENE Kopie ins aktuelle Konto – inklusive
    des vorhandenen Bildes (ein erneutes Generieren würde nur unnötige KI-Aufrufe kosten)."""
    r = await get_rezept(rezept_id)
    if r is None:
        return {"error": "Rezept nicht gefunden"}
    # Dedupe: dasselbe öffentliche Rezept nicht doppelt ins Konto kopieren (Doppel-Tap auf
    # „In meine Bibliothek" bzw. erneuter Import Tage später). Erkennung über Name +
    # importiert-Flag im EIGENEN Konto – eine Quell-ID-Spalte gibt es (noch) nicht, und die
    # RLS-Leseregel zeigt auch fremde veröffentlichte Zeilen, daher explizit account_id.
    # Tolerant: schlägt der Check fehl, wird normal importiert (schlimmstenfalls Duplikat).
    from .userauth import current_account
    acc = current_account.get()
    if acc is not None and r.get("name"):
        try:
            async with acquire() as con:
                vorhanden = await con.fetchval(
                    "SELECT id FROM rezepte WHERE account_id = $1 AND importiert "
                    "AND lower(name) = lower($2) ORDER BY id LIMIT 1", acc, r["name"])
            if vorhanden:
                return {"id": int(vorhanden), "name": r["name"], "bereits_vorhanden": True}
        except Exception:
            pass
    zutaten = [{"name": (z.get("zutat") or z.get("name")), "menge": z.get("menge"),
                "einheit": z.get("einheit"), "optional": bool(z.get("optional"))}
               for z in (r.get("zutaten") or []) if (z.get("zutat") or z.get("name"))]
    # Geräteneutral importieren: keine Geräte-Bindung übernehmen (zubereitung kommt via
    # get_rezept bereits geflattet). Der Nutzer passt selbst an seine Geräte an.
    neu = await add_rezept(
        name=r.get("name"), beschreibung=r.get("beschreibung"), anleitung=r.get("anleitung"),
        portionen=r.get("portionen") or 2, dauer_minuten=r.get("dauer_minuten"),
        quelle="Öffentliches Rezept", zutaten=zutaten, geraete=[],
        zubereitung=r.get("zubereitung"))
    # Vorhandenes Bild der Vorlage mitkopieren (kein KI-Aufruf).
    # Kopie als 'importiert' markieren: importierte Rezepte können NICHT (erneut)
    # veröffentlicht werden (kein Pool-Duplikat).
    if isinstance(neu, dict) and neu.get("id"):
        bild = r.get("bild") if isinstance(r.get("bild"), str) else None
        try:
            async with acquire() as con:
                await con.execute(
                    "UPDATE rezepte SET importiert = true, "
                    "bild = COALESCE($2, bild) WHERE id = $1",
                    int(neu["id"]), bild)
        except Exception:
            bild = None   # Kopie bleibt bestehen, nur ohne Bild
        neu["bild_uebernommen"] = bool(bild)
        neu["hat_bild"] = bool(bild)
    return neu


async def delete_bewertung(rezept_id: int) -> dict:
    async with acquire() as con:
        await con.execute("DELETE FROM bewertung WHERE rezept_id = $1", int(rezept_id))
    return {"deleted": int(rezept_id)}


async def check_vorrat_fuer_rezept(rezept_id: int) -> dict | None:
    """Prueft pro Pflicht-Zutat, ob und wie viel im Vorrat vorhanden ist (Basis: Faktor 1).
    Das Frontend skaliert die Mengen client-seitig gemaess gewuenschter Portionszahl.
    Status: 'ok' (gleiche Einheit, genug), 'knapp' (gleiche Einheit, zu wenig),
            'vorhanden' (andere Einheit, Menge unklar), 'aehnlich' (Namens-Match),
            'fehlt' (nicht im Vorrat)."""
    r = await get_rezept(rezept_id)
    if r is None:
        return None

    async with acquire() as con:
        canon_map = await _load_canon_map(con)
        vrows = await con.fetch(
            """
            SELECT v.zutat_id, v.einheit, SUM(v.menge) AS menge,
                   z.gebinde_menge, z.gebinde_einheit
            FROM vorrat v JOIN zutaten z ON z.id = v.zutat_id
            GROUP BY v.zutat_id, v.einheit, z.gebinde_menge, z.gebinde_einheit
            """
        )
        # vorrat_basis: Master-zutat_id → {klasse: basismenge} (Gebinde-normalisiert,
        # zugeordnete Markenartikel unter ihrem Master zusammengefasst).
        # Es werden ZWEI Klassen je Artikel gefuehrt: die rohe Einheit (z.B. "dose",
        # fuer Rezepte die in Dosen rechnen) UND – falls ein Gebinde hinterlegt ist –
        # zusaetzlich die Masse/Volumen-Klasse (z.B. Dose→g, fuer Rezepte in g/ml).
        vorrat_basis: dict[int, dict[str, float]] = {}
        for v in vrows:
            cz = canon_map.get(int(v["zutat_id"]), int(v["zutat_id"]))
            d = vorrat_basis.setdefault(cz, {})
            menge = float(v["menge"] or 0)
            rohklasse, rohfkt = _einheit_basis(v["einheit"])
            d[rohklasse] = d.get(rohklasse, 0.0) + menge * rohfkt
            klasse, basis = _basis_mit_gebinde(
                v["menge"], v["einheit"], v["gebinde_menge"], v["gebinde_einheit"]
            )
            if klasse != rohklasse:
                d[klasse] = d.get(klasse, 0.0) + basis

        vname_rows = await con.fetch(
            "SELECT DISTINCT v.zutat_id, z.name FROM vorrat v JOIN zutaten z ON z.id = v.zutat_id"
        )
        vorrat_namen: dict[int, str] = {}
        for r2 in vname_rows:
            cz = canon_map.get(int(r2["zutat_id"]), int(r2["zutat_id"]))
            vorrat_namen.setdefault(cz, r2["name"].lower())

        grund_rows = await con.fetch("SELECT id FROM zutaten WHERE grundzutat")
        grund_ids = {int(r2["id"]) for r2 in grund_rows}

    def _match(zid, klasse_b, benoetigt_basis, fkt, einheit, aehnlich=False):
        """(vorhanden_menge, vorhanden_einheit, status) fuer Master-id zid.
        fkt = Basis pro 1 Anzeige-Einheit. Gleiche Klasse → ok/knapp (bzw. aehnlich);
        nur andere Klasse vorhanden → 'vorhanden': die Zutat ist im Vorrat, aber in einer
        nicht direkt vergleichbaren Einheit (z.B. Rezept '1 EL', Vorrat in ml/g). Das gilt
        NICHT als fehlend; es wird die vorhandene Menge in der Vorrat-Klasse zurueckgegeben."""
        vb = vorrat_basis.get(zid)
        if not vb:
            return (None, None, None)
        if klasse_b in vb and vb[klasse_b] > 0:
            total = vb[klasse_b]
            menge = round(total / fkt, 2) if fkt else total
            st = "aehnlich" if aehnlich else ("ok" if total >= benoetigt_basis else "knapp")
            return (menge, einheit, st)
        klasse_v = next(iter(vb))
        einheit_v = {"masse": "g", "volumen": "ml"}.get(klasse_v, klasse_v)
        return (round(vb[klasse_v], 2), einheit_v, "aehnlich" if aehnlich else "vorhanden")

    items = []
    for zutat in r["zutaten"]:
        if zutat.get("optional"):
            continue
        zid_orig = int(zutat["zutat_id"])
        if zid_orig in grund_ids:
            continue
        zid = canon_map.get(zid_orig, zid_orig)
        zname = zutat["zutat"]
        benoetigt = float(zutat.get("menge") or 0)
        einheit = zutat.get("einheit", "")
        klasse_b, benoetigt_basis = _basis_mit_gebinde(benoetigt, einheit)
        fkt = (benoetigt_basis / benoetigt) if benoetigt else 1.0

        vorhanden_menge = None
        vorhanden_einheit = None
        matched_name = None
        status = "fehlt"

        # Nur ueber die Master-/Kanonik-Zutat matchen – keine unscharfe
        # Namensaehnlichkeit mehr (sonst tauchen artfremde "≈"-Treffer auf).
        if zid in vorrat_basis:
            vorhanden_menge, vorhanden_einheit, status = _match(
                zid, klasse_b, benoetigt_basis, fkt, einheit
            )

        items.append({
            "zutat_id": zid_orig,
            "zutat": zname,
            "benoetigt": benoetigt,
            "einheit": einheit,
            "vorhanden_menge": vorhanden_menge,
            "vorhanden_einheit": vorhanden_einheit,
            "matched_name": matched_name,
            "status": status,
        })

    return _jsonable({
        "rezept_id": int(r["id"]),
        "rezept": r["name"],
        "portionen_basis": int(r.get("portionen") or 1),
        "zutaten": items,
    })


# ---------- Koch-Flow (Vorratsabzug) ----------

async def kochen_vorschau(rezept_id: int) -> dict | None:
    r = await get_rezept(rezept_id)
    if r is None:
        return None
    abzug = [
        {"zutat_id": z["zutat_id"], "zutat": z["zutat"], "menge": z["menge"], "einheit": z["einheit"]}
        for z in r["zutaten"]
        if not z["optional"] and z["menge"] is not None
    ]
    return {"rezept_id": r["id"], "rezept": r["name"], "abzug": abzug}


async def kochen_bestaetigen(rezept_id: int, faktor: float = 1.0) -> dict | None:
    vor = await kochen_vorschau(rezept_id)
    if vor is None:
        return None
    f = Decimal(str(faktor))
    ergebnis = []
    # F16: Alle Zutaten-Abzüge in EINER Transaktion → kein halb abgezogener Vorrat bei Fehler.
    async with acquire() as con:
        async with con.transaction():
            for a in vor["abzug"]:
                res = await _reduce_vorrat_con(con, a["zutat_id"], Decimal(str(a["menge"])) * f, a["einheit"])
                ergebnis.append({**a, **res})
    return {"rezept_id": int(rezept_id), "faktor": float(faktor), "reduziert": _jsonable(ergebnis)}


# ---------- Wochenplaner ----------

MAHLZEITEN_REIHENFOLGE = ["Frühstück", "Mittag", "Abendessen", "Snack", "Unterwegs"]

def _montag(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def list_wochenplan(datum: date) -> list[dict]:
    montag = _montag(datum)
    sonntag = montag + timedelta(days=6)
    async with acquire() as con:
        rows = await con.fetch(
            """
            SELECT e.*, r.name AS rezept_name
            FROM essensplan e
            LEFT JOIN rezepte r ON r.id = e.rezept_id
            WHERE e.datum BETWEEN $1 AND $2
            ORDER BY e.datum,
                CASE e.mahlzeit
                  WHEN 'Frühstück' THEN 1 WHEN 'Mittag' THEN 2
                  WHEN 'Abendessen' THEN 3 WHEN 'Snack' THEN 4
                  WHEN 'Unterwegs' THEN 5 ELSE 6 END,
                e.erstellt_am
            """,
            montag, sonntag,
        )
        cart = await con.fetch("SELECT DISTINCT rezept_id FROM einkauf_extra WHERE rezept_id IS NOT NULL")
    cart_ids = {int(c["rezept_id"]) for c in cart}
    out = _l(rows)
    for e in out:
        e["im_warenkorb"] = (e.get("rezept_id") is not None and int(e["rezept_id"]) in cart_ids)
    return _jsonable(out)


# ---------- Speiseplan als iCalendar (ICS) fuer Google-Kalender-Abo ----------

# Uhrzeit + Dauer (Minuten) je Mahlzeit fuer die Kalender-Termine.
_MAHLZEIT_ZEIT = {
    "Frühstück": (8, 0, 30),
    "Mittag": (12, 0, 60),
    "Abendessen": (18, 0, 60),
    "Snack": (15, 0, 15),
    "Unterwegs": (12, 0, 45),
}
_MAHLZEIT_ICON = {
    "Frühstück": "🥐", "Mittag": "🍽️", "Abendessen": "🌙",
    "Snack": "🍎", "Unterwegs": "🚗",
}


def _ics_escape(text) -> str:
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    """RFC-5545-Zeilenfaltung (konservativ auf ~73 Zeichen, mit fuehrendem Space)."""
    if len(line) <= 73:
        return line
    chunks = [line[:73]]
    rest = line[73:]
    while rest:
        chunks.append(" " + rest[:72])
        rest = rest[72:]
    return "\r\n".join(chunks)


async def list_plan_range(von: date, bis: date) -> list[dict]:
    async with acquire() as con:
        rows = await con.fetch(
            """
            SELECT e.*, r.name AS rezept_name
            FROM essensplan e
            LEFT JOIN rezepte r ON r.id = e.rezept_id
            WHERE e.datum BETWEEN $1 AND $2
            ORDER BY e.datum,
                CASE e.mahlzeit
                  WHEN 'Frühstück' THEN 1 WHEN 'Mittag' THEN 2
                  WHEN 'Abendessen' THEN 3 WHEN 'Snack' THEN 4
                  WHEN 'Unterwegs' THEN 5 ELSE 6 END
            """,
            von, bis,
        )
    return _l(rows)


async def build_speiseplan_ics(tage_zurueck: int = 7, tage_voraus: int = 28) -> str:
    """Baut den Speiseplan als iCalendar-Text. Jede geplante Mahlzeit wird ein Termin
    (floating local time) mit Rezeptname, Mahlzeit-Icon und – falls WEB_BASE_URL gesetzt –
    einem Hyperlink auf das Rezept (URL-Property + in der Beschreibung)."""
    from . import config
    heute = _today()
    von = heute - timedelta(days=int(tage_zurueck))
    bis = heute + timedelta(days=int(tage_voraus))
    rows = await list_plan_range(von, bis)
    base = config.WEB_BASE_URL
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    out = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Kochassistent//Speiseplan//DE",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Speiseplan", "X-WR-TIMEZONE:Europe/Berlin",
    ]
    for e in rows:
        titel = e.get("rezept_name") or e.get("notiz")
        if not titel:
            continue  # leerer Slot ohne Rezept/Notiz -> kein Termin
        d = e["datum"]
        mahlzeit = e.get("mahlzeit") or ""
        h, m, dur = _MAHLZEIT_ZEIT.get(mahlzeit, (12, 0, 60))
        start = datetime(d.year, d.month, d.day, h, m)
        ende = start + timedelta(minutes=dur)
        icon = _MAHLZEIT_ICON.get(mahlzeit, "🍴")
        summary = f"{icon} {titel}"

        rezept_id = e.get("rezept_id")
        link = f"{base}/?rezept={rezept_id}" if (base and rezept_id) else None
        desc_parts = []
        if mahlzeit:
            desc_parts.append(mahlzeit)
        gaeste = int(e.get("gaeste") or 0)
        if gaeste:
            desc_parts.append(f"+{gaeste} Gäste")
        if e.get("notiz") and e.get("rezept_name"):
            desc_parts.append(str(e["notiz"]))
        if link:
            desc_parts.append(f"Rezept öffnen: {link}")
        desc = _ics_escape("\n".join(desc_parts))

        out += [
            "BEGIN:VEVENT",
            f"UID:speiseplan-{e['id']}@koch",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}",
            f"DTEND:{ende:%Y%m%dT%H%M%S}",
            _ics_fold(f"SUMMARY:{_ics_escape(summary)}"),
        ]
        if desc:
            out.append(_ics_fold(f"DESCRIPTION:{desc}"))
        if link:
            out.append(_ics_fold(f"URL:{link}"))
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


async def add_plan_eintrag(datum: date, mahlzeit: str, rezept_id: int | None = None,
                           notiz: str | None = None, person_ids: list[int] | None = None,
                           portionen: float | None = None, gaeste: int = 0) -> dict:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            INSERT INTO essensplan (datum, mahlzeit, rezept_id, notiz, person_ids, portionen, gaeste)
            VALUES ($1, $2, $3, $4, $5::int[], $6, $7) RETURNING *
            """,
            datum, mahlzeit, rezept_id, notiz, person_ids or [],
            Decimal(str(portionen)) if portionen is not None else None,
            int(gaeste or 0),
        )))


async def update_plan_eintrag(entry_id: int, datum: date, mahlzeit: str,
                               rezept_id: int | None = None, notiz: str | None = None,
                               person_ids: list[int] | None = None,
                               portionen: float | None = None, gaeste: int = 0) -> dict | None:
    async with acquire() as con:
        return _jsonable(_d(await con.fetchrow(
            """
            UPDATE essensplan SET datum=$2, mahlzeit=$3, rezept_id=$4, notiz=$5,
                                  person_ids=$6::int[], portionen=$7, gaeste=$8
            WHERE id=$1 RETURNING *
            """,
            int(entry_id), datum, mahlzeit, rezept_id, notiz, person_ids or [],
            Decimal(str(portionen)) if portionen is not None else None,
            int(gaeste or 0),
        )))


async def delete_plan_eintrag(entry_id: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM essensplan WHERE id=$1", int(entry_id))
    if not _affected(res):
        raise NichtGefunden("Plan-Eintrag nicht gefunden oder kein Zugriff.")
    return {"deleted": int(entry_id)}


async def list_einkaufstage(datum: date) -> list[dict]:
    montag = _montag(datum)
    sonntag = montag + timedelta(days=6)
    async with acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM einkaufstag WHERE datum BETWEEN $1 AND $2 ORDER BY datum",
            montag, sonntag,
        )
        hrows = await con.fetch(
            "SELECT datum, haendler FROM einkaufstag_haendler WHERE datum BETWEEN $1 AND $2 ORDER BY haendler",
            montag, sonntag,
        )
    hmap: dict = {}
    for r in hrows:
        hmap.setdefault(r["datum"], []).append(r["haendler"])
    out = _l(rows)
    for d in out:
        d["haendler_liste"] = hmap.get(d["datum"], ([d["haendler"]] if d.get("haendler") else []))
    return _jsonable(out)


async def set_einkaufstag_haendler(datum: date, haendler_liste: list | None) -> dict:
    """Setzt die Händler-Liste eines Einkaufstags (Mehrfachauswahl). Legt den Tag an.
    Leere Liste = Einkaufstag ohne Markt (keine Angebots-Logik)."""
    hs = []
    for h in (haendler_liste or []):
        h = (str(h) or "").strip()
        if h and h not in hs:
            hs.append(h)
    async with acquire() as con:
        async with con.transaction():
            await con.execute(
                "INSERT INTO einkaufstag (datum, haendler) VALUES ($1, $2) "
                "ON CONFLICT (account_id, datum) DO UPDATE SET haendler = EXCLUDED.haendler",
                datum, (hs[0] if hs else None))
            await con.execute("DELETE FROM einkaufstag_haendler WHERE datum = $1", datum)
            for h in hs:
                await con.execute(
                    "INSERT INTO einkaufstag_haendler (datum, haendler) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING", datum, h)
    return {"datum": datum.isoformat(), "haendler_liste": hs}


async def toggle_einkaufstag(datum: date) -> dict:
    async with acquire() as con:
        existing = await con.fetchrow("SELECT id FROM einkaufstag WHERE datum=$1", datum)
        if existing:
            await con.execute("DELETE FROM einkaufstag WHERE datum=$1", datum)
            return {"action": "removed", "datum": datum.isoformat()}
        else:
            await con.execute(
                "INSERT INTO einkaufstag (datum) VALUES ($1) ON CONFLICT DO NOTHING", datum
            )
            return {"action": "added", "datum": datum.isoformat()}


async def maerkte_fuer_datum(datum: date) -> list[dict]:
    """Maerkte (haendler) mit am Datum gueltigen Angeboten – die Auswahl fuer
    'wo einkaufen?'. Nur Maerkte, die an dem Tag ueberhaupt Angebote haben."""
    async with acquire() as con:
        rows = await con.fetch(
            """SELECT haendler, COUNT(*) AS anzahl
               FROM angebote
               WHERE haendler IS NOT NULL AND haendler <> ''
                 AND gueltig_von <= $1 AND gueltig_bis >= $1
               GROUP BY haendler ORDER BY anzahl DESC, haendler""",
            datum,
        )
    return _jsonable([{"haendler": r["haendler"], "anzahl": int(r["anzahl"])} for r in rows])


async def set_einkaufstag_markt(datum: date, haendler: str | None) -> dict:
    """Setzt EINEN Markt eines Einkaufstags (Abwärtskompatibilität). Synchronisiert
    die Mehrfach-Händler-Tabelle (genau dieser eine Händler bzw. leer)."""
    h = (haendler or "").strip()
    res = await set_einkaufstag_haendler(datum, [h] if h else [])
    return {"datum": datum.isoformat(), "haendler": (h or None),
            "haendler_liste": res.get("haendler_liste", [])}


# ---------- Manuelle Einkaufslisten-Artikel ----------

async def add_einkauf_extra(items: list[dict]) -> list[dict]:
    """Mehrere manuell aufgeschriebene Artikel zur Einkaufsliste hinzufuegen.
    items: [{name, menge?, einheit?}] – name ist Pflicht, menge/einheit optional."""
    out = []
    async with acquire() as con:
        for it in items or []:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            row = await con.fetchrow(
                "INSERT INTO einkauf_extra (name, menge, einheit, rezept_id) VALUES ($1, $2, $3, $4) RETURNING *",
                name, _num(it.get("menge")), (it.get("einheit") or None),
                (int(it["rezept_id"]) if it.get("rezept_id") else None),
            )
            out.append(_d(row))
    return _jsonable(out)


async def rezept_zutaten_in_warenkorb(rezept_id: int) -> dict:
    """Legt die Pflicht-Zutaten eines Rezepts in den Warenkorb (verknüpft mit dem Rezept)."""
    r = await get_rezept(rezept_id)
    if r is None:
        return {"error": "Rezept nicht gefunden"}
    items = [{"name": z["zutat"], "menge": z.get("menge"), "einheit": z.get("einheit"), "rezept_id": int(rezept_id)}
             for z in (r.get("zutaten") or []) if not z.get("optional") and (z.get("zutat") or "").strip()]
    res = await add_einkauf_extra(items)
    return {"hinzugefuegt": len(res), "rezept_id": int(rezept_id)}


async def list_einkauf_extra() -> list[dict]:
    async with acquire() as con:
        rows = await con.fetch("SELECT * FROM einkauf_extra ORDER BY created_at, id")
    return _jsonable(_l(rows))


async def delete_einkauf_extra(extra_id: int) -> dict:
    async with acquire() as con:
        res = await con.execute("DELETE FROM einkauf_extra WHERE id = $1", int(extra_id))
    if not _affected(res):
        raise NichtGefunden("Eintrag nicht gefunden oder kein Zugriff.")
    return {"deleted": int(extra_id)}


# Einheiten-Normalisierung fuer den Mengenabgleich mit dem Vorrat.
# Masse -> Basis "g", Volumen -> Basis "ml". Alles andere bildet eine eigene
# Klasse (z.B. "stück", "packung", "dose", "bund") und wird nur bei exakt
# gleicher Einheit verrechnet.
_EINHEIT_BASIS = {
    "g": ("masse", 1.0), "gramm": ("masse", 1.0), "mg": ("masse", 0.001),
    "kg": ("masse", 1000.0),
    "ml": ("volumen", 1.0), "cl": ("volumen", 10.0),
    "l": ("volumen", 1000.0), "liter": ("volumen", 1000.0),
}


def _einheit_basis(einheit: str) -> tuple[str, float]:
    e = (einheit or "").strip().lower()
    if e in _EINHEIT_BASIS:
        return _EINHEIT_BASIS[e]
    return (e or "stk", 1.0)


# "Weiche" Wuerz-/Schaetzmasse, die sich nicht zuverlaessig in g/ml umrechnen lassen
# (1 EL ist mal ml, mal g). Ist eine Zutat in einer solchen Einheit gefragt und
# ueberhaupt im Vorrat (egal in welcher Einheit), gilt sie als gedeckt - sie wird
# nicht eingekauft und nicht als fehlend gewertet.
_WEICHE_MASSE = {"el", "tl", "prise", "msp", "messerspitze", "handvoll",
                 "spritzer", "schuss", "etwas"}


def _basis_mit_gebinde(menge, einheit, gebinde_menge=None, gebinde_einheit=None) -> tuple[str, float]:
    """(klasse, basismenge) fuer eine Menge. Ist die Einheit KEINE Masse/Volumen-
    Einheit (also z.B. Packung/Dose/Stueck) UND ist eine Gebinde-Groesse hinterlegt
    (1 Einheit = gebinde_menge gebinde_einheit), wird in die Gebinde-Klasse
    umgerechnet (z.B. 1 Packung -> 250 g). Sonst bleibt es bei der normalen
    Einheiten-Normalisierung."""
    klasse, fkt = _einheit_basis(einheit)
    m = float(menge or 0)
    if klasse not in ("masse", "volumen") and gebinde_menge:
        gk, gfkt = _einheit_basis(gebinde_einheit or "")
        if gk in ("masse", "volumen"):
            return (gk, m * float(gebinde_menge) * gfkt)
    return (klasse, m * fkt)


async def get_einkaufsliste(datum: date) -> dict:
    """Einkaufsliste ab heute, aufgeteilt nach Einkaufstagen.
    Vergangene Tage (und vergangene Einkaufstage) fallen raus. Jeder kuenftige
    Einkaufstag deckt die Mahlzeiten ab seinem Datum bis zum naechsten
    Einkaufstag (exklusiv) bzw. bis Sonntag dieser Woche. Sind in dieser Woche
    keine (kuenftigen) Einkaufstage gesetzt, wird ab heute bis einschliesslich
    Sonntag der Folgewoche als eine Periode gerechnet.
    Der Vorrat wird gegengerechnet (Match ueber zutat_id + Einheiten-
    Normalisierung, Namens-Fallback) und von Periode zu Periode fortgefuehrt."""
    heute = _today()   # F17: Europe/Berlin statt naivem date.today() (UTC-Mitternachtsfenster)
    montag = _montag(datum)
    sonntag = montag + timedelta(days=6)
    # Vergangene Tage fallen raus: ab heute rechnen (aber nie vor Wochenbeginn,
    # falls eine kuenftige Woche betrachtet wird).
    start = max(heute, montag)

    async with acquire() as con:
        # Einkaufstage dieser Woche, aber nur die noch nicht vergangenen.
        einkauf_rows = await con.fetch(
            "SELECT datum, haendler FROM einkaufstag WHERE datum BETWEEN $1 AND $2 ORDER BY datum",
            montag, sonntag,
        )
        einkauf_dates = sorted([r["datum"] for r in einkauf_rows if r["datum"] >= start])
        # Mehrere Händler je Einkaufstag (Fallback: einzelner haendler aus einkaufstag).
        h_rows = await con.fetch(
            "SELECT datum, haendler FROM einkaufstag_haendler WHERE datum BETWEEN $1 AND $2",
            montag, sonntag,
        )
        markt_map: dict = {}
        for r in h_rows:
            markt_map.setdefault(r["datum"], []).append(r["haendler"])
        for r in einkauf_rows:
            if r["datum"] not in markt_map and r["haendler"]:
                markt_map[r["datum"]] = [r["haendler"]]

        # Angebote (mit Master-Zutat + Markt) fuer die Angebots-Markierung der Liste.
        angebot_rows = await con.fetch(
            """SELECT a.haendler, a.master_zutat_id, z.name AS master_name,
                      a.name, a.preis_angebot, a.preis_normal,
                      a.gueltig_von, a.gueltig_bis
               FROM angebote a JOIN zutaten z ON z.id = a.master_zutat_id
               WHERE a.haendler IS NOT NULL"""
        )

        # Ohne (kuenftige) Einkaufstage bis Sonntag der Folgewoche planen,
        # sonst bis Sonntag dieser Woche.
        horizont_ende = sonntag if einkauf_dates else (montag + timedelta(days=13))

        plan_rows = await con.fetch(
            "SELECT * FROM essensplan WHERE datum BETWEEN $1 AND $2 ORDER BY datum",
            start, horizont_ende,
        )

        person_rows = await con.fetch("SELECT id, portionsfaktor FROM person")
        pf_map = {int(r["id"]): float(r["portionsfaktor"]) for r in person_rows}

        rezept_ids = list({int(r["rezept_id"]) for r in plan_rows if r["rezept_id"]})
        zutaten_map: dict[int, list] = {}
        if rezept_ids:
            rz_rows = await con.fetch(
                """
                SELECT rz.rezept_id, rz.zutat_id, z.name AS zutat, rz.menge, rz.einheit,
                       z.grundzutat, z.gebinde_menge, z.gebinde_einheit, r.portionen AS basis
                FROM rezept_zutaten rz
                JOIN zutaten z ON z.id = rz.zutat_id
                JOIN rezepte r ON r.id = rz.rezept_id
                WHERE rz.rezept_id = ANY($1) AND NOT rz.optional
                """,
                rezept_ids,
            )
            for rz in rz_rows:
                zutaten_map.setdefault(int(rz["rezept_id"]), []).append(dict(rz))

        vrows = await con.fetch(
            """
            SELECT v.zutat_id, z.name, v.einheit, SUM(v.menge) AS menge,
                   z.gebinde_menge, z.gebinde_einheit
            FROM vorrat v JOIN zutaten z ON z.id = v.zutat_id
            GROUP BY v.zutat_id, z.name, v.einheit, z.gebinde_menge, z.gebinde_einheit
            """
        )

        canon_map = await _load_canon_map(con)

    def _canon(z):
        return canon_map.get(int(z), int(z))

    # Vorrat in Basis-Mengen je (Master-zutat_id, klasse); Namen fuer den Fallback.
    # Zugeordnete Markenartikel werden ueber ihren Master zusammengefasst.
    pantry0: dict[tuple, float] = {}
    vorrat_namen: dict[int, str] = {}
    for v in vrows:
        zid = _canon(v["zutat_id"])
        menge = float(v["menge"] or 0)
        # rohe Einheiten-Klasse (z.B. "dose"): direkter Match mit Rezepten in derselben Einheit
        rohklasse, rohfkt = _einheit_basis(v["einheit"])
        rk = (zid, rohklasse)
        pantry0[rk] = pantry0.get(rk, 0.0) + menge * rohfkt
        # zusaetzlich Gebinde-normalisiert (z.B. Dose→g): Match mit Rezepten in g/ml
        klasse, basis = _basis_mit_gebinde(
            v["menge"], v["einheit"], v["gebinde_menge"], v["gebinde_einheit"]
        )
        if klasse != rohklasse:
            key = (zid, klasse)
            pantry0[key] = pantry0.get(key, 0.0) + basis
        vorrat_namen.setdefault(zid, v["name"].lower())

    def portionen_fuer_eintrag(e) -> float:
        gaeste = float(e.get("gaeste") or 0)
        if e["portionen"] is not None:
            return float(e["portionen"]) + gaeste
        ids = list(e["person_ids"] or [])
        total = sum(pf_map.get(int(pid), 1.0) for pid in ids)
        return max(total + gaeste, 1.0)

    def needed_aggregieren(entries) -> dict:
        # key (zutat_id, klasse) -> {zutat, basis, anzeige_einheit, anzeige_fkt}
        res: dict[tuple, dict] = {}
        for e in entries:
            rid = e["rezept_id"]
            if not rid:
                continue
            port = portionen_fuer_eintrag(e)
            for z in zutaten_map.get(int(rid), []):
                if z["menge"] is None:
                    continue
                if z.get("grundzutat"):
                    continue
                zid = _canon(z["zutat_id"])
                basis_port = float(z["basis"] or 1) or 1.0
                faktor = port / basis_port
                klasse, basis_einzel = _basis_mit_gebinde(
                    z["menge"], z["einheit"], z.get("gebinde_menge"), z.get("gebinde_einheit")
                )
                add = basis_einzel * faktor
                menge_roh = float(z["menge"] or 0)
                anzeige_fkt = (basis_einzel / menge_roh) if menge_roh else 1.0
                key = (zid, klasse)
                rec = res.get(key)
                if rec is None:
                    res[key] = {
                        "zutat_id": zid,
                        "zutat": z["zutat"], "basis": add,
                        "anzeige_einheit": z["einheit"], "anzeige_fkt": anzeige_fkt or 1.0,
                    }
                else:
                    rec["basis"] += add
        return res

    def finde_vorrat_key(current_pantry, zid, klasse, zname):
        """Passenden pantry-Key (zutat_id, klasse) finden: erst exakt ueber
        zutat_id, dann Namens-Fallback (bidirektionaler Substring)."""
        if (zid, klasse) in current_pantry:
            return (zid, klasse)
        zn = (zname or "").lower()
        if zn:
            for vid, vname in vorrat_namen.items():
                if vid == zid:
                    continue
                if _zutat_namensmatch(zn, vname) and (vid, klasse) in current_pantry:
                    return (vid, klasse)
        return None

    # Perioden bilden. Einkauf deckt [Einkaufstag .. naechster Einkaufstag - 1]
    # bzw. bis Sonntag. Tage vor dem ersten Einkaufstag sind eine Nicht-Einkauf-
    # Periode (zehren nur den Vorrat, werden nicht eingekauft).
    if not einkauf_dates:
        # Kein kuenftiger Einkaufstag: ein Fenster ab heute bis Sonntag Folgewoche.
        grenzen = [(start, horizont_ende, True)]
    else:
        # Ein Einkaufstag deckt die Mahlzeiten BIS zu sich selbst ab (seit dem
        # vorherigen Einkaufstag bzw. ab Fensterbeginn). So rechnet die Liste z.B.
        # bei Einkaufstag 17.6. nur bis einschliesslich 17.6.
        grenzen = []
        for i, ed in enumerate(einkauf_dates):
            von = start if i == 0 else einkauf_dates[i - 1] + timedelta(days=1)
            grenzen.append((von, ed, True))
        # Tage NACH dem letzten Einkaufstag bis Sonntag: nicht Teil dieser Einkaufsplanung.
        if einkauf_dates[-1] < sonntag:
            grenzen.append((einkauf_dates[-1] + timedelta(days=1), sonntag, False))

    def bestes_angebot(master_id, pos_name, hdl, am):
        """Guenstigstes Angebot fuer die Zutat beim Markt hdl, gueltig am Datum am.
        Match ueber Master-Zutat-id ODER Namens-Substring (Master-Name <-> Positions-
        Name, bidirektional), damit 'Tomate' (Angebot) und 'Tomaten' (Rezept) treffen.
        Wird live ausgewertet – laeuft ein Angebot ab, greift automatisch ein neueres
        (oder keins -> nur die Master-Zutat)."""
        if not hdl:
            return None
        hdl_set = {hdl} if isinstance(hdl, str) else set(hdl)
        pn = (pos_name or "").lower()
        best = None
        for a in angebot_rows:
            if a["haendler"] not in hdl_set:
                continue
            if not (a["gueltig_von"] <= am <= a["gueltig_bis"]):
                continue
            passt = (master_id is not None and a["master_zutat_id"] == master_id) or (
                bool(pn) and _name_match(a["master_name"], pos_name))
            if not passt:
                continue
            if best is None or (a["preis_angebot"] or 1e9) < (best["preis_angebot"] or 1e9):
                best = a
        if best is None:
            return None
        return {
            "name": best["name"],
            "haendler": best["haendler"],
            "preis_angebot": float(best["preis_angebot"]) if best["preis_angebot"] is not None else None,
            "preis_normal": float(best["preis_normal"]) if best["preis_normal"] is not None else None,
        }

    current_pantry = dict(pantry0)
    perioden = []

    for von, bis, is_einkauf in grenzen:
        # Der Einkaufstag liegt am ENDE der Periode (bis) -> Markt/Angebote von dort.
        markt = markt_map.get(bis) if is_einkauf else None
        entries_period = [r for r in plan_rows if von <= r["datum"] <= bis]
        needed = needed_aggregieren(entries_period)

        positionen = []
        for (zid, klasse), rec in sorted(needed.items(), key=lambda kv: kv[1]["zutat"].lower()):
            benoetigt_basis = rec["basis"]
            vkey = finde_vorrat_key(current_pantry, zid, klasse, rec["zutat"])
            vorhanden_basis = current_pantry.get(vkey, 0.0) if vkey else 0.0
            # Weiche Wuerzmasse (EL/TL/Prise...): ist die Zutat in nicht vergleichbarer
            # Einheit ueberhaupt vorhanden, als gedeckt behandeln (nicht einkaufen).
            if vkey is None and klasse in _WEICHE_MASSE:
                zn = (rec["zutat"] or "").lower()
                im_vorrat = any(k[0] == zid for k in current_pantry) or (
                    bool(zn) and any(
                        _zutat_namensmatch(zn, vn) and any(k[0] == vid for k in current_pantry)
                        for vid, vn in vorrat_namen.items() if vid != zid
                    )
                )
                if im_vorrat:
                    continue
            kaufen_basis = max(0.0, benoetigt_basis - vorhanden_basis)

            fkt = rec["anzeige_fkt"] or 1.0
            benoetigt = round(benoetigt_basis / fkt, 2)
            vorhanden = round(vorhanden_basis / fkt, 2)
            kaufen = round(kaufen_basis / fkt, 2)

            if is_einkauf and kaufen > 0:
                positionen.append({
                    "zutat_id": rec.get("zutat_id"),
                    "zutat": rec["zutat"],
                    "einheit": rec["anzeige_einheit"],
                    "benoetigt": benoetigt,
                    "vorhanden": vorhanden,
                    "kaufen": kaufen,
                    "angebot": bestes_angebot(rec.get("zutat_id"), rec["zutat"], markt, bis),
                })

            # Vorrat fortfuehren: Alt-Bestand abzueglich Verbrauch. Der ggf.
            # gekaufte Teil deckt genau den Fehlbedarf dieser Periode und ist
            # danach aufgebraucht (kein Uebertrag, da bedarfsgenau gekauft wird).
            if vkey:
                current_pantry[vkey] = max(0.0, vorhanden_basis - benoetigt_basis)

        perioden.append({
            "von": von.isoformat(),
            "bis": bis.isoformat(),
            "ist_einkaufstag": is_einkauf,
            "markt": (", ".join(markt) if markt else None),  # Anzeige-String (mehrere Märkte)
            "positionen": positionen,
        })

    manuell = await list_einkauf_extra()

    return _jsonable({
        "montag": montag.isoformat(),
        "sonntag": sonntag.isoformat(),
        "einkaufstage": [d.isoformat() for d in einkauf_dates],
        "perioden": perioden,
        "manuell": manuell,
    })


# ---------- Supermarkt-Angebote ----------

async def get_angebote(datum: "date | None" = None) -> list[dict]:
    """Gibt aktuelle Supermarkt-Angebote zurueck (gueltig am Datum, default heute).
    master_zutat_id/-name verweisen (falls gesetzt) auf die generische Zutat."""
    from datetime import date as date_t
    d = datum or _today()
    async with acquire() as con:
        rows = await con.fetch(
            """SELECT a.*, z.name AS master_zutat_name
               FROM angebote a
               LEFT JOIN zutaten z ON z.id = a.master_zutat_id
               WHERE a.gueltig_von <= $1 AND a.gueltig_bis >= $1
               ORDER BY a.kategorie, a.name""",
            d,
        )
    return _jsonable(_l(rows))


# Kategorien (Fallback ohne explizite art) -> Rubrik. Verarbeitetes/Genussmittel
# zaehlt als Fertiggericht, klassische Non-Food-Kategorien als non_food, der Rest
# (Fleisch, Obst, Gemuese, Molkerei, Grundnahrung ...) als Koch-Zutat.
_KAT_FERTIG = {
    "tiefkühl", "tiefkuehl", "fertiggericht", "fertiggerichte", "snacks", "snack",
    "süßwaren", "suesswaren", "süsswaren", "getränke", "getraenke", "kaffee",
    "spirituosen", "alkohol",
}
_KAT_NONFOOD = {
    "non-food", "nonfood", "non food", "haushalt", "drogerie", "kosmetik",
    "tierfutter", "tierbedarf", "garten", "blumen", "deko", "elektro", "textil",
}


def _angebot_rubrik(art, kategorie, has_master) -> str:
    """Rubrik fuer die Uebersicht. Explizite art gewinnt; sonst Heuristik aus
    der Kategorie (mit Master-Zutat -> immer Koch-Zutat)."""
    a = (art or "").strip().lower()
    if a in ("zutat", "fertiggericht", "non_food"):
        return a
    if has_master:
        return "zutat"
    k = (kategorie or "").strip().lower()
    if k in _KAT_NONFOOD:
        return "non_food"
    if k in _KAT_FERTIG:
        return "fertiggericht"
    return "zutat"


async def get_angebote_uebersicht() -> list[dict]:
    """Alle noch nicht abgelaufenen Angebote (gueltig_bis >= heute), also aktuelle
    UND kommende. Fuer die Angebots-Uebersicht im Frontend, sortiert nach Start-
    datum, Markt, Kategorie. Jede Zeile bekommt eine 'rubrik' (zutat /
    fertiggericht / non_food); master_zutat_name verweist (falls gesetzt) auf die
    generische Zutat."""
    d = _today()
    async with acquire() as con:
        rows = await con.fetch(
            """SELECT a.*, z.name AS master_zutat_name
               FROM angebote a
               LEFT JOIN zutaten z ON z.id = a.master_zutat_id
               WHERE a.gueltig_bis >= $1
               ORDER BY a.gueltig_von, a.haendler NULLS LAST, a.kategorie, a.name""",
            d,
        )
    out = []
    for r in rows:
        rec = dict(r)
        rec["rubrik"] = _angebot_rubrik(rec.get("art"), rec.get("kategorie"), rec.get("master_zutat_id") is not None)
        out.append(rec)
    return _jsonable(out)


def _wochenende_zeitraum(gb, tage):
    """Leitet aus dem Haupt-Ende + genannten Aktionstagen den Wochenend-Kurzzeitraum ab:
    'Do…'→Do-Sa (2 zurueck), 'Mi…'→3, sonst Fr+Sa (1). (ohne re)"""
    try:
        ende = date.fromisoformat(str(gb)[:10])
    except (ValueError, TypeError):
        return None, None
    toks = set((tage or "").lower().replace(",", " ").replace("+", " ").replace("-", " ").split())
    if {"do", "donnerstag"} & toks:
        back = 2
    elif {"mi", "mittwoch"} & toks:
        back = 3
    else:
        back = 1  # Fr+Sa
    return (ende - timedelta(days=back)).isoformat(), ende.isoformat()


async def import_angebote(eintraege: list[dict], nur_konto: bool = False) -> dict:
    """Importiert Angebote eines Prospekts und ERGÄNZT sie (kein Ersetzen mehr):
    bestehende Angebote eines Markts bleiben erhalten, neue Artikel kommen hinzu.
    Exakte Dubletten (gleicher Markt, Name, Zeitraum im selben Scope) werden
    übersprungen. Super-Admin/MCP laden GLOBALE Admin-Angebote (account_id NULL,
    für alle sichtbar); normale User in ihr eigenes Konto."""
    if not eintraege:
        return {"importiert": 0, "uebersprungen": 0}
    from .userauth import current_account, current_user, ist_super_admin
    uid = current_user.get()
    acc = current_account.get()
    if nur_konto:
        # MCP & Co.: immer in den Haushalt des Aufrufers, nie global.
        if acc is None:
            return {"error": "Kein Haushalt im Kontext."}
        global_admin = False
    else:
        global_admin = uid is None or await ist_super_admin(uid)
        acc = acc or 1
    count = 0
    skip = 0
    async with acquire(bypass=global_admin) as con:
        async with con.transaction():
            for e in eintraege:
                gv = _date(e.get("gueltig_von"))
                gb = _date(e.get("gueltig_bis"))
                # Wochenend-Aktion: Zeitraum auf das Aktions-Wochenende verkuerzen
                # (greift auch über MCP/n8n, nicht nur beim Datei-Upload).
                if e.get("nur_wochenende") and e.get("gueltig_bis"):
                    wv, wb = _wochenende_zeitraum(e.get("gueltig_bis"), e.get("wochenende_tage"))
                    if wv and wb:
                        gv, gb = _date(wv), _date(wb)
                hdl = e.get("haendler")
                nm = str(e.get("name", ""))
                # Dubletten-Check im jeweiligen Scope (global = account_id NULL, sonst eigenes Konto).
                if global_admin:
                    exists = await con.fetchval(
                        "SELECT 1 FROM angebote WHERE account_id IS NULL "
                        "AND haendler IS NOT DISTINCT FROM $1 AND lower(name)=lower($2) "
                        "AND gueltig_von=$3 AND gueltig_bis=$4", hdl, nm, gv, gb)
                else:
                    exists = await con.fetchval(
                        "SELECT 1 FROM angebote WHERE account_id=$5 "
                        "AND haendler IS NOT DISTINCT FROM $1 AND lower(name)=lower($2) "
                        "AND gueltig_von=$3 AND gueltig_bis=$4", hdl, nm, gv, gb, acc)
                if exists:
                    skip += 1
                    continue
                mzid = e.get("master_zutat_id")
                # master_zutat als Name: auf bestehende Master-Zutat aufloesen bzw. anlegen.
                if mzid is None and (e.get("master_zutat") or "").strip():
                    mzid = await _ensure_zutat(con, e["master_zutat"].strip())
                art = (e.get("art") or "").strip().lower() or None
                if art not in (None, "zutat", "fertiggericht", "non_food"):
                    art = None
                bild = e.get("bild")
                if not isinstance(bild, str) or len(bild) > 200000:
                    bild = None  # nur kleine Data-URLs zulassen
                await con.execute(
                    """INSERT INTO angebote
                       (account_id, gueltig_von, gueltig_bis, name, beschreibung, haendler,
                        preis_normal, preis_angebot, einheit, kategorie, master_zutat_id, art, bild)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                    (None if global_admin else acc),
                    gv, gb, nm, e.get("beschreibung"), hdl,
                    _num(e.get("preis_normal")), _num(e.get("preis_angebot")),
                    e.get("einheit"), e.get("kategorie"),
                    int(mzid) if mzid is not None else None, art, bild,
                )
                count += 1
    return {"importiert": count, "uebersprungen": skip}


async def delete_angebot(angebot_id: int, admin: bool = False) -> dict:
    """Löscht ein Angebot. admin=True (Super-Admin/MCP) darf globale Admin-Angebote
    (account_id IS NULL) UND die eigenen des handelnden Kontos löschen – aber NICHT die
    anderer Mandanten (F13). Ohne admin greift RLS → nur EIGENE Angebote des Kontos."""
    if admin:
        from .userauth import current_account
        eigen = current_account.get() or 1
        async with acquire(bypass=True) as con:
            res = await con.execute(
                "DELETE FROM angebote WHERE id = $1 AND (account_id IS NULL OR account_id = $2)",
                int(angebot_id), int(eigen))
    else:
        async with acquire() as con:  # RLS → nur eigene
            res = await con.execute("DELETE FROM angebote WHERE id = $1", int(angebot_id))
    geloescht = int(res.split()[-1]) if res else 0
    return {"geloescht": geloescht}


async def delete_angebote_blatt(haendler, gueltig_von, gueltig_bis, admin: bool = False) -> dict:
    """Löscht ein komplettes Angebotsblatt = alle Angebote eines Markts für einen
    Zeitraum (haendler + gueltig_von + gueltig_bis). admin=True darf auch globale
    Admin-Angebote; sonst greift RLS → nur EIGENE Angebote des Kontos."""
    gv, gb = _date(gueltig_von), _date(gueltig_bis)
    if admin:
        # F13: Admin/Bypass nur auf globale (NULL) + eigene Zeilen begrenzen, nicht auf alle Mandanten.
        from .userauth import current_account
        eigen = current_account.get() or 1
        async with acquire(bypass=True) as con:
            res = await con.execute(
                "DELETE FROM angebote WHERE haendler IS NOT DISTINCT FROM $1 "
                "AND gueltig_von = $2 AND gueltig_bis = $3 "
                "AND (account_id IS NULL OR account_id = $4)",
                (haendler or None), gv, gb, int(eigen))
    else:
        async with acquire() as con:  # RLS → nur eigene
            res = await con.execute(
                "DELETE FROM angebote WHERE haendler IS NOT DISTINCT FROM $1 "
                "AND gueltig_von = $2 AND gueltig_bis = $3",
                (haendler or None), gv, gb)
    geloescht = int(res.split()[-1]) if res else 0
    return {"geloescht": geloescht}


async def set_angebote_master(zuordnungen: list[dict]) -> dict:
    """Setzt nachtraeglich die master_zutat_id bestehender Angebote (ohne Neu-Import).
    zuordnungen: [{angebot_id, master_zutat_id}]. master_zutat_id=None hebt auf.
    Gibt {aktualisiert: n} zurueck."""
    if not zuordnungen:
        return {"aktualisiert": 0}
    n = 0
    async with acquire() as con:
        async with con.transaction():
            for z in zuordnungen:
                aid = z.get("angebot_id")
                if aid is None:
                    continue
                mzid = z.get("master_zutat_id")
                await con.execute(
                    "UPDATE angebote SET master_zutat_id = $2 WHERE id = $1",
                    int(aid),
                    int(mzid) if mzid is not None else None,
                )
                n += 1
    return {"aktualisiert": n}


async def delete_expired_angebote() -> dict:
    """Entfernt alle abgelaufenen Angebote (gueltig_bis < heute) aus der DB.
    Aktive (heute noch gueltige) Angebote bleiben – marktuebergreifend. Wird vom
    Hintergrund-Job taeglich aufgerufen (am Tag nach Ablauf)."""
    async with acquire(bypass=True) as con:  # marktuebergreifend, ohne Konto-Kontext
        res = await con.execute("DELETE FROM angebote WHERE gueltig_bis < CURRENT_DATE")
    try:
        n = int(str(res).split()[-1])
    except (ValueError, IndexError):
        n = 0
    return {"geloescht": n}


# ---------- Konto-/Haushalt-Löschung (Self-Service) ----------

# Reihenfolge: Kind-Tabellen vor Eltern; `zutaten` zuletzt (RESTRICT durch vorrat/
# rezept_zutaten). `person_notiz` cascadet über person.
_ACCOUNT_TABELLEN = [
    "kochmodus_schritte", "mcp_idempotenz",
    "personen_heute", "person_abwesenheit_regel",
    "geraete_heute", "geraete_heute_stand", "rezept_geraete", "rezept_zutaten",
    "bewertung", "essensplan", "einkauf_extra", "einkaufstag_haendler", "einkaufstag",
    "vorrat", "rezepte", "person", "geraete", "zutaten", "lagerort",
    "bugreport",
]


async def _delete_account_data(con, acc: int) -> None:
    """Löscht ALLE Daten eines Kontos + das Konto selbst (bypass-Kontext nötig).
    angebote: nur kontoeigene – globale Admin-Angebote (account_id IS NULL) bleiben."""
    for t in _ACCOUNT_TABELLEN:
        await con.execute(f"DELETE FROM {t} WHERE account_id = $1", acc)
    await con.execute("DELETE FROM angebote WHERE account_id = $1", acc)
    # MCP-Zugänge des Haushalts (Tokens hängen per CASCADE an den Grants).
    await con.execute("DELETE FROM api_token WHERE account_id = $1", acc)
    await con.execute("DELETE FROM oauth_grant WHERE account_id = $1", acc)
    await con.execute("DELETE FROM account_mitglied WHERE account_id = $1", acc)
    await con.execute("DELETE FROM account WHERE id = $1", acc)


# ---------- DSGVO: Datenexport (Art. 15 Auskunft / Art. 20 Portabilität) ----------

# Export-Umfang = Löschumfang (_ACCOUNT_TABELLEN) + eigene Angebote.
_EXPORT_TABELLEN = _ACCOUNT_TABELLEN + ["angebote"]


async def export_konto_daten() -> dict:
    """DSGVO-Auskunft/Portabilität: ALLE Daten des aktiven Kontos als JSON-Struktur.
    Läuft im Bypass, filtert aber strikt auf das eigene Konto (account_id)."""
    from .userauth import current_account, current_user
    uid = current_user.get()
    acc = current_account.get()
    if not uid or not acc:
        return {"error": "nicht angemeldet"}
    async with acquire(bypass=True) as con:
        acct = await con.fetchrow("SELECT * FROM account WHERE id = $1", acc)
        mitglieder = await con.fetch(
            "SELECT u.id, u.email::text AS email, u.name, u.plattform_rolle, "
            "m.rolle AS konto_rolle, m.beigetreten_am "
            "FROM account_mitglied m JOIN app_user u ON u.id = m.user_id "
            "WHERE m.account_id = $1 ORDER BY m.beigetreten_am", acc)
        out: dict[str, Any] = {
            "hinweis": "DSGVO-Datenexport (Art. 15/20) - alle zu diesem Konto gespeicherten Daten.",
            "exportiert_am": datetime.now(_BERLIN).isoformat(),
            "konto_id": acc,
            "konto": _jsonable(_d(acct)),
            "mitglieder": _jsonable(_l(mitglieder)),
        }
        for t in _EXPORT_TABELLEN:
            rows = await con.fetch(f"SELECT * FROM {t} WHERE account_id = $1 ORDER BY 1", acc)
            out[t] = _jsonable(_l(rows))
        return out


async def loesche_eigenes_konto(modus: str = "selbst") -> dict:
    """Self-Service-Löschung des aktiven Kontos durch den eingeloggten User.
      - 'haushalt' (nur Eigentümer): ganzer Haushalt inkl. aller Daten + verwaiste Logins.
      - 'selbst': nur eigene Mitgliedschaft + eigener Login. War man Eigentümer,
        wird das älteste verbleibende Mitglied Eigentümer. Ist man der LETZTE Nutzer, wird der ganze Haushalt entfernt."""
    from .userauth import current_account, current_user
    uid = current_user.get()
    acc = current_account.get()
    if not uid or not acc:
        return {"error": "nicht angemeldet"}
    async with acquire(bypass=True) as con:
        async with con.transaction():
            mine = await con.fetchrow(
                "SELECT rolle FROM account_mitglied WHERE account_id=$1 AND user_id=$2", acc, uid)
            ist_owner = bool(mine and mine["rolle"] == "owner")
            if modus == "haushalt" and not ist_owner:
                return {"error": "Nur der Eigentümer kann den ganzen Haushalt löschen."}
            mitglieder = await con.fetch(
                "SELECT user_id FROM account_mitglied WHERE account_id=$1 ORDER BY beigetreten_am", acc)
            andere = [int(m["user_id"]) for m in mitglieder if int(m["user_id"]) != uid]
            voll = (modus == "haushalt") or (len(andere) == 0)
            if voll:
                alle_uids = [int(m["user_id"]) for m in mitglieder]
                await _delete_account_data(con, acc)
                # Verwaiste Logins (keine Mitgliedschaft mehr) entfernen – außer Super-Admin.
                if alle_uids:
                    await con.execute(
                        "DELETE FROM app_user u WHERE u.id = ANY($1::int[]) "
                        "AND NOT EXISTS (SELECT 1 FROM account_mitglied m WHERE m.user_id = u.id) "
                        "AND u.plattform_rolle IS DISTINCT FROM 'super_admin'", alle_uids)
                return {"geloescht": True, "modus": "haushalt"}
            # Nur sich selbst entfernen.
            await con.execute(
                "DELETE FROM account_mitglied WHERE account_id=$1 AND user_id=$2", acc, uid)
            await con.execute("DELETE FROM api_token WHERE account_id=$1 AND user_id=$2", acc, uid)
            await con.execute("DELETE FROM oauth_grant WHERE account_id=$1 AND user_id=$2", acc, uid)
            if ist_owner:
                await con.execute(
                    "UPDATE account_mitglied SET rolle='owner' WHERE account_id=$1 AND user_id=$2",
                    acc, andere[0])
            await con.execute(
                "DELETE FROM app_user u WHERE u.id = $1 "
                "AND NOT EXISTS (SELECT 1 FROM account_mitglied m WHERE m.user_id = u.id) "
                "AND u.plattform_rolle IS DISTINCT FROM 'super_admin'", uid)
            return {"geloescht": True, "modus": "selbst"}


# ---------- Vorrat-Modus (voll / light) ----------

async def get_vorrat_modus(account_id: int) -> dict:
    """Vorrat-Modus des Kontos: 'voll' (App-Vorrat) oder 'light' (Freitext bei Generierung)."""
    async with acquire() as con:
        m = await con.fetchval("SELECT einstellungen->>'vorrat_modus' FROM account WHERE id = $1", account_id)
    return {"modus": m if m in ("voll", "light") else "voll"}


async def set_vorrat_modus(account_id: int, modus: str) -> dict:
    m = modus if modus in ("voll", "light") else "voll"
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{vorrat_modus}', to_jsonb($2::text)) WHERE id = $1", account_id, m)
    return {"modus": m}


# ---------- Startseite ----------

_MAHLZEIT_RANK = {"Frühstück": 1, "Fruehstueck": 1, "Snack": 2, "Mittag": 3,
                  "Mittagessen": 3, "Unterwegs": 4, "Abendessen": 5, "Abend": 5}


def _slot_min_rank(stunde: int) -> int:
    """Aktueller Mahlzeiten-Slot nach Uhrzeit: Frühstück bis 11, Mittag bis 15, Abend bis 24."""
    if stunde < 11:
        return 1
    if stunde < 15:
        return 3
    return 5


async def naechste_mahlzeit() -> dict | None:
    """Die als Nächstes anstehende, noch nicht gekochte geplante Mahlzeit (zeitbasiert).
    Vergangene Slots des heutigen Tages fallen raus, ab morgen zählt alles."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        jetzt = datetime.now(ZoneInfo("Europe/Berlin"))
    except Exception:
        jetzt = datetime.now()
    heute = jetzt.date()
    min_rank = _slot_min_rank(jetzt.hour)
    async with acquire() as con:
        rows = await con.fetch(
            """SELECT e.id, e.datum, e.mahlzeit, e.rezept_id, r.name AS rezept,
                      e.portionen, e.gaeste, (r.bild IS NOT NULL) AS hat_bild
               FROM essensplan e JOIN rezepte r ON r.id = e.rezept_id
               WHERE NOT e.gekocht AND e.datum >= $1 AND e.datum <= ($1 + 7)
               ORDER BY e.datum,
                 CASE e.mahlzeit WHEN 'Frühstück' THEN 1 WHEN 'Snack' THEN 2
                   WHEN 'Mittag' THEN 3 WHEN 'Unterwegs' THEN 4 ELSE 5 END, e.id""",
            heute)
    # Nächsten Slot (datum+mahlzeit) bestimmen …
    slot = None
    for r in rows:
        rank = _MAHLZEIT_RANK.get(r["mahlzeit"], 5)
        if r["datum"] > heute or (r["datum"] == heute and rank >= min_rank):
            slot = (r["datum"], r["mahlzeit"])
            break
    if slot is None:
        return None
    # … und ALLE Rezepte dieses Slots zurückgeben (z.B. Vorspeise/Hauptgericht/Dessert).
    d, m = slot
    rezepte = [
        {"id": r["id"], "rezept_id": r["rezept_id"], "rezept": r["rezept"],
         "hat_bild": bool(r["hat_bild"]), "portionen": r["portionen"], "gaeste": r["gaeste"]}
        for r in rows if r["datum"] == d and r["mahlzeit"] == m
    ]
    return _jsonable({"datum": d, "mahlzeit": m, "rezepte": rezepte})


async def plan_gekocht_setzen(eintrag_id: int, gekocht: bool = True) -> dict:
    async with acquire() as con:
        await con.execute("UPDATE essensplan SET gekocht=$2 WHERE id=$1", int(eintrag_id), bool(gekocht))
    return {"ok": True, "id": int(eintrag_id), "gekocht": bool(gekocht)}


async def start_uebersicht() -> dict:
    """Startseiten-Daten: aktuelle Angebote passend zu den Vorlieben (mag_gern) der
    Haushaltsmitglieder + sofort kochbare Rezepte (0 fehlende Zutaten) und knapp
    kochbare als Fallback."""
    heute = _today()
    angebote = await get_angebote(heute)  # heute gueltige, inkl. master_zutat_name
    async with acquire() as con:
        prows = await con.fetch(
            "SELECT name, mag_gern FROM person WHERE aktiv = true AND mag_gern <> ''"
        )

    def _kws(s: str) -> list[str]:
        roh = (s or "").replace(";", ",").replace("/", ",").replace(" und ", ",")
        return [k.strip().lower() for k in roh.split(",") if len(k.strip()) >= 3]

    personen = [(r["name"], _kws(r["mag_gern"])) for r in prows]

    treffer = []
    for a in angebote:
        text = " ".join(
            str(x) for x in (a.get("name"), a.get("master_zutat_name"),
                             a.get("kategorie"), a.get("beschreibung")) if x
        ).lower()
        fuer = [name for name, kws in personen if any(kw in text for kw in kws)]
        if fuer:
            treffer.append({
                "id": a.get("id"), "name": a.get("name"), "kategorie": a.get("kategorie"),
                "preis_angebot": a.get("preis_angebot"), "preis_normal": a.get("preis_normal"),
                "einheit": a.get("einheit"), "haendler": a.get("haendler"),
                "master_zutat_name": a.get("master_zutat_name"),
                "gueltig_von": a.get("gueltig_von"), "gueltig_bis": a.get("gueltig_bis"),
                "fuer": sorted(set(fuer)),
            })

    vorschlaege = await rezepte_vorschlagen(40)
    sofort = [v for v in vorschlaege if v.get("fehlend") == 0][:8]
    fast = [v for v in vorschlaege if 0 < (v.get("fehlend") or 0) <= 2][:6]
    naechste = await naechste_mahlzeit()
    return _jsonable({
        "naechste_mahlzeit": naechste,
        "angebote_vorlieben": treffer,
        "sofort_kochbar": sofort,
        "fast_kochbar": fast,
    })


# ---------- Bugreports ----------

async def create_bugreport(text: str, seite: str | None = None, user_agent: str | None = None) -> dict:
    """Speichert eine In-App-Fehlermeldung des aktuellen Nutzers/Kontos."""
    from .userauth import current_user
    t = (text or "").strip()
    if not t:
        return {"error": "Bitte beschreibe kurz, was nicht funktioniert hat."}
    uid = current_user.get()
    async with acquire() as con:
        row = await con.fetchrow(
            "INSERT INTO bugreport (user_id, seite, text, user_agent) "
            "VALUES ($1, $2, $3, $4) RETURNING *",
            uid, ((seite or "").strip()[:200] or None), t[:4000],
            ((user_agent or "").strip()[:400] or None),
        )
    return _d(row)


async def list_bugreports(nur_offen: bool = False) -> list[dict]:
    """Alle Bugreports konto-uebergreifend (nur Admin/Support, bypass)."""
    where = "WHERE b.status = 'offen' " if nur_offen else ""
    async with acquire(bypass=True) as con:
        rows = await con.fetch(
            "SELECT b.*, u.email AS user_email, a.name AS account_name "
            "FROM bugreport b "
            "LEFT JOIN app_user u ON u.id = b.user_id "
            "LEFT JOIN account a ON a.id = b.account_id "
            + where +
            "ORDER BY (b.status = 'offen') DESC, b.erstellt_am DESC LIMIT 500"
        )
    return _jsonable(_l(rows))


async def set_bugreport_status(bugreport_id: int, status: str) -> dict:
    """Setzt den Status eines Bugreports (offen/erledigt) – Admin/Support, bypass."""
    st = status if status in ("offen", "erledigt") else "offen"
    async with acquire(bypass=True) as con:
        row = await con.fetchrow(
            "UPDATE bugreport SET status = $2 WHERE id = $1 RETURNING *",
            int(bugreport_id), st)
    return _d(row) if row else {"error": "Bugreport nicht gefunden"}


# ---------- Zutaten-Kuratierung (Super-Admin): Account-Master -> Global ----------

async def list_kuratier_kandidaten() -> dict:
    """Account-eigene Master-Zutaten (account_id gesetzt, selbst Master) als
    Kandidaten zur Ueberfuehrung in die globale DB – mit Nutzungszahlen und
    (falls vorhanden) passendem globalem Master. Plus Liste aller globalen Master
    fuer die manuelle Ziel-Auswahl. Bypass (kontouebergreifend)."""
    async with acquire(bypass=True) as con:
        rows = await con.fetch(
            """
            SELECT z.id, z.name, z.account_id, a.name AS account_name, z.standard_einheit,
                   (SELECT count(*) FROM rezept_zutaten rz WHERE rz.zutat_id = z.id) AS rezept_count,
                   (SELECT count(*) FROM vorrat v WHERE v.zutat_id = z.id) AS vorrat_count,
                   (SELECT count(*) FROM zutaten k WHERE k.kanonische_zutat_id = z.id) AS kinder_count
            FROM zutaten z LEFT JOIN account a ON a.id = z.account_id
            WHERE z.account_id IS NOT NULL AND z.kanonische_zutat_id IS NULL
            ORDER BY rezept_count DESC, z.name
            """
        )
        globale = await con.fetch(
            "SELECT id, name, standard_einheit FROM zutaten "
            "WHERE account_id IS NULL AND kanonische_zutat_id IS NULL ORDER BY name"
        )
    gl = _l(globale)
    out = []
    for r in _l(rows):
        nm = (r["name"] or "").lower()
        exakt = next((g for g in gl if g["name"].lower() == nm), None)
        aehnlich = None
        if not exakt:
            aehnlich = next((g for g in gl if _zutat_namensmatch(nm, g["name"].lower())), None)
        d = dict(r)
        d["global_exakt"] = {"id": exakt["id"], "name": exakt["name"]} if exakt else None
        d["global_aehnlich"] = {"id": aehnlich["id"], "name": aehnlich["name"]} if aehnlich else None
        out.append(d)
    return _jsonable({"kandidaten": out, "globale_master": gl})


async def zutat_global_machen(zutat_id: int) -> dict:
    """Macht eine Account-Master-Zutat global (account_id -> NULL). Rezepte/Vorrat
    behalten dieselbe id und funktionieren weiter. Bypass."""
    zid = int(zutat_id)
    async with acquire(bypass=True) as con:
        ist = await con.fetchrow("SELECT account_id, kanonische_zutat_id, name FROM zutaten WHERE id=$1", zid)
        if ist is None:
            return {"error": "Zutat nicht gefunden"}
        if ist["account_id"] is None:
            return {"error": "Zutat ist bereits global."}
        if ist["kanonische_zutat_id"] is not None:
            return {"error": "Nur Master-Zutaten koennen global werden (diese ist zugeordnet)."}
        try:
            row = await con.fetchrow(
                "UPDATE zutaten SET account_id = NULL WHERE id=$1 RETURNING id, name", zid
            )
        except UniqueViolationError:
            return {"error": f"Eine globale Zutat „{ist['name']}\" existiert bereits – stattdessen zusammenfuehren."}
    return _d(row)


async def merge_zutat(quelle_id: int, ziel_id: int) -> dict:
    """Fuehrt Quelle-Zutat in Ziel-Master zusammen: Kinder, Rezeptzutaten (Dubletten
    werden verworfen), Vorrat und Angebote werden auf das Ziel umgehaengt, dann wird
    die Quelle geloescht. Ziel muss selbst ein Master sein. Bypass.

    B-2: Kein stiller Merge ueber Account-Grenzen. Erlaubt sind nur: Merge innerhalb
    desselben Accounts (inkl. global<->global) sowie das Hochstufen einer Account-Zutat
    in einen globalen Master (Quelle account-gebunden, Ziel global) – das ist der einzige
    von der Kuratierungs-UI genutzte Pfad (siehe kuratiere_zutat_auf_name). Jede andere
    Kombination (fremder Account, oder global -> fremder Account) wird abgelehnt, da sonst
    Rezeptzutaten/Vorrat/Angebote eines Accounts auf eine Zutat umgehaengt wuerden, die die
    RLS-Policy fuer diesen Account gar nicht sichtbar macht."""
    q, z = int(quelle_id), int(ziel_id)
    if q == z:
        return {"error": "Quelle und Ziel sind identisch."}
    async with acquire(bypass=True) as con:
        ziel = await con.fetchrow("SELECT id, account_id, kanonische_zutat_id FROM zutaten WHERE id=$1", z)
        if ziel is None:
            return {"error": "Ziel-Zutat nicht gefunden."}
        if ziel["kanonische_zutat_id"] is not None:
            return {"error": "Ziel ist selbst kein Master (zeigt auf eine andere Zutat)."}
        quelle = await con.fetchrow("SELECT id, account_id FROM zutaten WHERE id=$1", q)
        if quelle is None:
            return {"error": "Quelle-Zutat nicht gefunden."}
        hochstufung_zu_global = quelle["account_id"] is not None and ziel["account_id"] is None
        if quelle["account_id"] != ziel["account_id"] and not hochstufung_zu_global:
            return {"error": "Quelle und Ziel gehoeren zu unterschiedlichen Accounts – Merge ueber Kontogrenzen ist nicht erlaubt."}
        async with con.transaction():
            await con.execute("UPDATE zutaten SET kanonische_zutat_id=$2 WHERE kanonische_zutat_id=$1", q, z)
            # Rezeptzutaten: nicht-kollidierende umhaengen, kollidierende (Rezept hat Ziel schon) verwerfen
            await con.execute(
                "UPDATE rezept_zutaten SET zutat_id=$2 WHERE zutat_id=$1 "
                "AND rezept_id NOT IN (SELECT rezept_id FROM rezept_zutaten WHERE zutat_id=$2)", q, z)
            await con.execute("DELETE FROM rezept_zutaten WHERE zutat_id=$1", q)
            await con.execute("UPDATE vorrat SET zutat_id=$2 WHERE zutat_id=$1", q, z)
            await con.execute("UPDATE angebote SET master_zutat_id=$2 WHERE master_zutat_id=$1", q, z)
            await con.execute("DELETE FROM zutaten WHERE id=$1", q)
    return {"merged": True, "quelle": q, "ziel": z}


async def kuratiere_zutat_auf_name(zutat_id: int, name: str) -> dict:
    """Kuratierung per Ziel-Name (Freitext): Gibt es einen gleichnamigen GLOBALEN
    Master, wird die Zutat dort hineingeführt (merge); sonst wird sie unter diesem
    Namen global angelegt (umbenennen + account_id NULL). Bypass."""
    zid = int(zutat_id)
    nm = (name or "").strip()
    if not nm:
        return {"error": "Bitte einen Ziel-Namen angeben."}
    async with acquire(bypass=True) as con:
        ziel = await con.fetchrow(
            "SELECT id FROM zutaten WHERE account_id IS NULL AND kanonische_zutat_id IS NULL "
            "AND lower(name) = lower($1) AND id <> $2 LIMIT 1", nm, zid)
    if ziel:
        return await merge_zutat(zid, int(ziel["id"]))
    async with acquire(bypass=True) as con:
        if await con.fetchrow("SELECT 1 FROM zutaten WHERE id=$1", zid) is None:
            return {"error": "Zutat nicht gefunden"}
        try:
            row = await con.fetchrow(
                "UPDATE zutaten SET name = $2, account_id = NULL WHERE id = $1 RETURNING id, name",
                zid, nm)
        except UniqueViolationError:
            return {"error": f"Eine globale Zutat „{nm}“ existiert bereits."}
    return {"global": True, "id": int(row["id"]), "name": row["name"]} if row else {"error": "Zutat nicht gefunden"}
