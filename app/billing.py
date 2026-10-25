"""Token-Messung, fiktives Guthaben und monatliche Abo-Pauschale (Beta).

Jeder KI-Aufruf läuft über `complete()`: erfasst die von LiteLLM gemeldeten
Kosten (Header `x-litellm-response-cost`, USD) + Token, schlägt den
plattformweiten Markup auf (Default 25 %), protokolliert in `ai_nutzung` und
zieht das Guthaben des aktiven Kontos ab. Beträge in Hundertstel-€ ("cents") mit
Nachkommastellen (numeric), da echte Modellkosten Bruchteile eines Cents sind.

Das genutzte Modell richtet sich nach der Stufe des Kontos (schnell/standard/pro).
"""
from __future__ import annotations

import contextvars
import logging
from datetime import date, timedelta
from decimal import Decimal

import asyncpg

from . import config
from .db import acquire
from .userauth import current_account, current_user, darf_ki

# Pro Request optionale Kostenerfassung: Endpunkt ruft beginne_kostenerfassung(),
# record_usage/record_bild_gemini addieren den (marked-up) €-Betrag, Endpunkt liest ihn
# aus, um dem Nutzer die realen Kosten der Aktion zu zeigen.
_turn_kosten: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("turn_kosten", default=None)


def beginne_kostenerfassung() -> dict:
    box = {"cents": Decimal(0)}
    _turn_kosten.set(box)
    return box


def _erfasse_kosten(betrag) -> None:
    box = _turn_kosten.get()
    if box is not None:
        try:
            box["cents"] += Decimal(str(betrag))
        except Exception:
            pass


async def guthaben_jetzt() -> float:
    """Aktuelles €-Guthaben (in Cent) des aktiven Kontos – für die Kostenanzeige."""
    acc = current_account.get() or 1
    try:
        async with acquire() as con:
            v = await con.fetchval("SELECT guthaben_cents FROM account WHERE id = $1", acc)
        return float(v or 0)
    except Exception:
        return 0.0


async def buche(con, account_id: int, betrag_cents, typ: str, zweck: str | None = None,
                app: str = "cooking", clamp: bool = False):
    """Eine Guthaben-Buchung: append-only Ledger-Eintrag + atomischer Saldo-Update mit
    Row-Lock (verhindert Lost-Updates/Races). betrag_cents > 0 = Gutschrift, < 0 = Abzug.
    clamp=True (für Abzüge): nie unter 0 – es wird nur das tatsächlich Vorhandene gebucht,
    sodass Cache-Saldo == Summe(Ledger) bleibt. Gibt den neuen Saldo (cents) zurück.
    Muss mit einer offenen Connection aufgerufen werden (eigene Transaktion innen)."""
    betrag = Decimal(str(betrag_cents))
    async with con.transaction():
        bal = await con.fetchval("SELECT guthaben_cents FROM account WHERE id = $1 FOR UPDATE", account_id)
        bal = bal if bal is not None else Decimal(0)
        eff = betrag
        if clamp and betrag < 0:
            eff = -min(-betrag, bal)
        await con.execute(
            "INSERT INTO guthaben_buchung (account_id, app, betrag_cents, typ, zweck) "
            "VALUES ($1, $2, $3, $4, $5)", account_id, app, eff, typ, zweck)
        neu = await con.fetchval(
            "UPDATE account SET guthaben_cents = guthaben_cents + $2 WHERE id = $1 RETURNING guthaben_cents",
            account_id, eff)
    return neu

log = logging.getLogger("koch")

# Fallback-Defaults (DB-Tabelle plattform_einstellung überschreibt sie).
# Pauschale je Haushalt nach Personenzahl: 1 Person vs. mehrere. Einladungen gratis.
ABO_EINZEL_CENTS = 299      # 2,99 € bei einer Person im Haushalt
ABO_MEHRERE_CENTS = 449     # 4,49 € ab zwei Personen
FOTO_PACK_CENTS = 1299      # 12,99 € je Foto-Pack (Fallback; führend ist plattform_einstellung)
MARKUP_DEFAULT = Decimal(25)
OVERAGE_MARKUP_DEFAULT = Decimal(65)   # Aufschlag im Abo-Pay-as-you-go-Überlauf (vergünstigt)
# F3: Vorab-Reservierung je PAYG-Aufruf (in Cent). Wird beim eigentlichen Verbuchen gegen
# die realen Kosten abgerechnet (Über-Reservierung wird erstattet). Der Wert wirkt nur als
# Mindest-Startguthaben und Nebenläufigkeits-Bremse – die Endabrechnung bleibt exakt.
PAYG_RESERVE_CENTS = Decimal("3")

# Modellstufen → Vertex-AI-Modell-ID (alle multimodal, also auch für Foto/Prospekt).
TIER_MODELL = {
    "schnell": "google/gemini-2.5-flash-lite",
    "standard": "google/gemini-2.5-flash",
    "pro": "google/gemini-2.5-pro",
}
DEFAULT_TIER = "standard"

# Anzeigename in der Abrechnung: rohe Modell-ID / Imagen-Stufe -> nutzerseitige
# Stufe. Modellnamen werden bewusst NIE nach außen gegeben (nur Schnell/Standard/
# Pro bzw. Bild · Schnell/Standard) – konsistent zur Einstellungen-UI.
_MODELL_LABEL = {mid: stufe.capitalize() for stufe, mid in TIER_MODELL.items()}


def modell_label(modell: str | None) -> str:
    if not modell:
        return "—"
    m = modell.strip()
    if m in _MODELL_LABEL:
        return _MODELL_LABEL[m]
    ml = m.lower()
    if "imagen" in ml or ml.startswith("bild"):
        if "standard" in ml:
            return "Bild · Standard"
        if "schnell" in ml or "fast" in ml:
            return "Bild · Schnell"
        return "Bild"
    for mid, label in _MODELL_LABEL.items():
        if mid.lower() in ml:
            return label
    return "KI"


# Token-Preis (€/1 Mio. Token in/out) je Modell; Kosten werden daraus berechnet.
# Schlüssel = Teilstring der Modell-ID (längster Treffer zuerst → "flash-lite" vor "flash").
_PREISE: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
_PREIS_DEFAULT = (0.50, 3.00)


def _preis_fuer(modell: str | None) -> tuple[float, float]:
    m = (modell or "").strip().lower()
    # längste passende Bezeichnung zuerst (damit "flash lite" vor "flash" greift)
    for key in sorted(_PREISE, key=len, reverse=True):
        if key in m:
            return _PREISE[key]
    return _PREIS_DEFAULT


def kosten_cents(modell: str | None, prompt_tokens: int, completion_tokens: int) -> Decimal:
    p_in, p_out = _preis_fuer(modell)
    eur = prompt_tokens / 1_000_000 * p_in + completion_tokens / 1_000_000 * p_out
    return Decimal(str(eur * 100)).quantize(Decimal("0.0001"))


# ---------- Modellwahl je Konto ----------

async def get_modell_stufe() -> dict:
    acc = current_account.get() or 1
    async with acquire() as con:
        stufe = await con.fetchval("SELECT einstellungen->>'modell_stufe' FROM account WHERE id = $1", acc)
    s = stufe if stufe in TIER_MODELL else DEFAULT_TIER
    return {"stufe": s, "modell": TIER_MODELL[s], "stufen": list(TIER_MODELL.keys())}


async def set_modell_stufe(stufe: str | None) -> dict:
    s = stufe if stufe in TIER_MODELL else DEFAULT_TIER
    acc = current_account.get() or 1
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{modell_stufe}', to_jsonb($2::text)) WHERE id = $1", acc, s)
    return {"stufe": s, "modell": TIER_MODELL[s]}


# Modellwahl ist NICHT mehr nutzerseitig (keine Konto-Einstellung). Wir routen pro
# Operation (zweck) zentral – günstige Modelle wo möglich, stärkere nur wo nötig.
ZWECK_MODELL: dict[str, str] = {
    "chat": TIER_MODELL["standard"],                 # Tools + Reasoning → Flash
    "foto-erkennung": TIER_MODELL["standard"],       # Vision (Vorrat/Geräte-Foto)
    "guided-cooking": TIER_MODELL["standard"],
    "guided-frage": TIER_MODELL["standard"],
    "rezept-link": TIER_MODELL["standard"],
    "rezept-import-datei": TIER_MODELL["standard"],  # Vision (Screenshots/PDF)
    # Prospekt-Extraktion: EIN Aufruf je Seite, bis 24 Seiten je Import – der teuerste Zweck
    # pro Nutzeraktion. Der Schlüssel hieß bis 2026-07-26 "angebote" und griff damit NIE
    # (der Import ruft mit zweck="angebote-import" auf); es zog still der DEFAULT_TIER.
    # Jetzt korrekt verdrahtet und per ANGEBOTE_STUFE umstellbar.
    "angebote-import": TIER_MODELL[
        config.ANGEBOTE_STUFE if config.ANGEBOTE_STUFE in TIER_MODELL else "schnell"],
    "spracheingabe": TIER_MODELL["schnell"],         # Transkription → günstig
    "kategorisierung": TIER_MODELL["schnell"],       # einfache Klassifizierung → günstig
}


def modell_fuer_zweck(zweck: str | None) -> str:
    """Zentrales Modell-Routing pro Operation (kein Nutzer-Setting mehr)."""
    return ZWECK_MODELL.get(zweck or "", TIER_MODELL[DEFAULT_TIER])


async def modell_fuer_konto() -> str:
    """Kompat-Helfer: liefert das Standard-Modell (Modellwahl erfolgt zentral pro Operation
    in complete()/modell_fuer_zweck, nicht mehr je Konto)."""
    return TIER_MODELL[DEFAULT_TIER]


# ---------- Tarif / Nutzungslimits (Claude-Stil) ----------

class LimitErreicht(Exception):
    """Ein Stunden-/Wochen-/Monats-Limit des Abo-Tarifs ist erreicht. `.info` trägt
    das limit_pruefen()-Ergebnis; rest.py macht daraus eine HTTP-402-Antwort."""

    def __init__(self, info: dict):
        self.info = info
        super().__init__("KI-Limit erreicht")


class AbrechnungspruefungFehlgeschlagen(Exception):
    """Die Vorab-Limit-/Guthabenprüfung konnte nicht ausgewertet werden (DB-Fehler o.ä.).
    Wir brechen fail-closed ab, statt einen kostenpflichtigen Modell-Aufruf ohne gültige
    Prüfung durchzulassen (F9). main.py macht daraus eine HTTP-503-Antwort."""


def _tarif_public(t: dict | None) -> dict:
    t = t or {}
    def _i(k):
        return int(t[k]) if t.get(k) is not None else None
    return {
        "code": t.get("code") or "payg",
        "name": t.get("name") or "Pay-as-you-go",
        "ist_payg": bool(t.get("ist_payg", t.get("code") == "payg")),
        "preis_cents": int(t.get("preis_cents") or 0),
        "markup_prozent": float(t["markup_prozent"]) if t.get("markup_prozent") is not None else 0.0,
        "tages_limit_cents": _i("tages_limit_cents"),
        "wochen_limit_cents": _i("wochen_limit_cents"),
        # Monatskontingente des Kontingent-Modells (NULL = unbegrenzt) – gehören zur
        # Preisliste und sind daher auch im Admin-Editor sichtbar/pflegbar.
        "monats_ki_limit": _i("monats_ki_limit"),
        "monats_bild_limit": _i("monats_bild_limit"),
        "sortierung": int(t.get("sortierung") or 0),
        "aktiv": bool(t.get("aktiv", True)),
    }


async def tarif_fuer_konto(con, account_id: int) -> dict:
    """EFFEKTIVE Tarif-Zeile des Kontos (Fallback payg). Ein Abo-Tarif gilt nur, solange
    die bezahlte Periode läuft (abo_bezahlt_bis >= heute); danach zählt das Konto für
    Limits/Aufschlag/Abrechnung als PAYG, bis der Sweep verlängert oder es endgültig auf
    payg fällt."""
    arow = await con.fetchrow(
        "SELECT tarif_code, abo_bezahlt_bis FROM account WHERE id = $1", account_id)
    code = (arow["tarif_code"] if arow else None) or "payg"
    bis = arow["abo_bezahlt_bis"] if arow else None
    if code != "payg" and (bis is None or bis < date.today()):
        code = "payg"
    row = await con.fetchrow("SELECT * FROM tarif WHERE code = $1", code)
    if row is None:
        row = await con.fetchrow("SELECT * FROM tarif WHERE code = 'payg'")
    return dict(row) if row else {"code": "payg", "ist_payg": True}


async def _billing_modus(con, account_id: int) -> str:
    """'abo' = Nutzung durch das Wochen-/Tagesvolumen gedeckt (kein Guthaben-Abzug);
    'payg' = aus Guthaben abrechnen. Fällt bei Fehlern auf 'payg' zurück, damit die
    Abrechnung vor der Migration unverändert läuft."""
    try:
        overage = await con.fetchval("SELECT payg_overage FROM account WHERE id = $1", account_id)
        if overage:
            return "payg"
        tarif = await tarif_fuer_konto(con, account_id)
        return "payg" if bool(tarif.get("ist_payg")) else "abo"
    except Exception:
        return "payg"


async def _markup_fuer(con, account_id: int) -> Decimal:
    """Token-/Bild-Aufschlag (%) für das Konto. PAYG-Tarif: dessen markup_prozent (125 %).
    Abo regulär: Stufen-Aufschlag (Basis 100 / Plus 85 / Max 65). Abo im Pay-as-you-go-
    Überlauf (Guthaben nach Volumen): vergünstigter overage_markup_prozent (65 %)."""
    try:
        tarif = await tarif_fuer_konto(con, account_id)
        if bool(tarif.get("ist_payg")):
            return Decimal(str(tarif.get("markup_prozent") if tarif.get("markup_prozent") is not None else MARKUP_DEFAULT))
        overage = await con.fetchval("SELECT payg_overage FROM account WHERE id = $1", account_id)
        if overage:
            ov = await con.fetchval("SELECT overage_markup_prozent FROM plattform_einstellung WHERE id = 1")
            return Decimal(str(ov)) if ov is not None else OVERAGE_MARKUP_DEFAULT
        m = tarif.get("markup_prozent")
        return Decimal(str(m)) if m is not None else MARKUP_DEFAULT
    except Exception:
        return MARKUP_DEFAULT


async def limit_pruefen(con, account_id: int, *, geplant_cents: Decimal = Decimal(0)) -> dict:
    """Prüft die zwei Nutzungsfenster (Tag = letzte 24 h, Woche = letzte 7 Tage, beide
    rollend) gegen das Tages-/Wochenvolumen des Tarifs. Verbrauch in marked-up Cent
    (= das, was vom Volumen abgeht). PAYG/Overage ist nie geblockt (nur Guthaben zählt).

    Der Pay-as-you-go-Überlauf gilt nur, solange ein Limit erreicht ist: sobald das Konto
    durch das rollende Fenster wieder unter dem Limit liegt ("wieder freigeschaltet"),
    wird der Überlauf automatisch deaktiviert und muss beim nächsten Limit erneut
    aktiviert werden."""
    arow = await con.fetchrow("SELECT guthaben_cents, payg_overage FROM account WHERE id = $1", account_id)
    guthaben = float(arow["guthaben_cents"]) if arow else 0.0
    overage = bool(arow["payg_overage"]) if arow else False
    tarif = await tarif_fuer_konto(con, account_id)
    ist_payg_tarif = bool(tarif.get("ist_payg"))

    w = await con.fetchrow("""
        SELECT
          COALESCE(SUM(kosten_cents) FILTER (WHERE erstellt >= now() - interval '1 day'),0) AS tag,
          COALESCE(SUM(kosten_cents) FILTER (WHERE erstellt >= now() - interval '7 days'),0) AS woche
        FROM ai_nutzung
        WHERE erstellt >= now() - interval '7 days'""")
    verbrauch = {"tag": float(w["tag"]), "woche": float(w["woche"])}
    rest = {"tag": None, "woche": None}

    # Rohes Limit aus dem Tarif (ohne Überlauf) bestimmen – auch wenn der Überlauf
    # gerade aktiv ist, damit wir die Freischaltung erkennen.
    limit_erreicht = None
    if not ist_payg_tarif:
        tl = tarif.get("tages_limit_cents")
        wl = tarif.get("wochen_limit_cents")
        if tl is not None:
            rest["tag"] = max(0.0, float(tl) - verbrauch["tag"])
        if wl is not None:
            rest["woche"] = max(0.0, float(wl) - verbrauch["woche"])
        # Reihenfolge: zuerst das engste Fenster (Tag) melden.
        if tl is not None and verbrauch["tag"] >= float(tl):
            limit_erreicht = "tag"
        elif wl is not None and verbrauch["woche"] >= float(wl):
            limit_erreicht = "woche"

    # Überlauf automatisch beenden, sobald kein Limit mehr erreicht ist (rollendes
    # Fenster hat Volumen freigegeben → muss beim nächsten Limit neu aktiviert werden).
    if overage and not ist_payg_tarif and limit_erreicht is None:
        try:
            await con.execute(
                "UPDATE account SET payg_overage = false, payg_overage_seit = NULL WHERE id = $1",
                account_id)
            overage = False
        except Exception as e:
            log.warning("payg_overage Auto-Reset fehlgeschlagen: %s", e)

    ist_payg = ist_payg_tarif or overage

    # PAYG bzw. abgelaufenes Abo OHNE Guthaben: KI gesperrt → Nutzer muss ein Abo
    # abschließen oder Guthaben aufladen. Abo im Inklusivvolumen ist nie 'kein_guthaben'.
    kein_guthaben = ist_payg and guthaben <= 0
    blockiert_limit = (limit_erreicht is not None) and not ist_payg
    blockiert = blockiert_limit or kein_guthaben
    grund = "limit" if blockiert_limit else ("kein_guthaben" if kein_guthaben else None)

    return {
        "modus": "payg" if ist_payg else "abo",
        "tarif": _tarif_public(tarif),
        "verbrauch": verbrauch,
        "limit_erreicht": limit_erreicht,
        "rest": rest,
        "guthaben_cents": guthaben,
        "payg_overage": overage,
        "ist_payg_tarif": ist_payg_tarif,
        "blockiert": blockiert,
        "grund": grund,
        "darf_payg_weiter": guthaben > 0,
    }


def limit_payload(info: dict) -> dict:
    """Formt ein limit_pruefen()-Ergebnis in den HTTP-402-Body fürs Frontend.
    grund='limit'        → Abo-Volumen erschöpft (PAYG weiter / Upgrade).
    grund='kein_guthaben'→ kein aktives Abo & kein Guthaben (Abo abschließen / aufladen)."""
    if info.get("v4"):
        return limit_payload_v4(info)
    tarif = info.get("tarif") or {}
    grund = info.get("grund") or "limit"
    hat_abo = not bool(info.get("ist_payg_tarif", True))
    return {
        "fehler": "limit",
        "grund": grund,
        "limit": info.get("limit_erreicht"),
        "tarif": tarif,
        "verbrauch": info.get("verbrauch"),
        "rest": info.get("rest"),
        "guthaben_cents": info.get("guthaben_cents"),
        "modus": info.get("modus"),
        "hat_abo": hat_abo,
        "optionen": {
            "payg_moeglich": bool(info.get("darf_payg_weiter")) and grund == "limit",
            "upgrade_moeglich": hat_abo and tarif.get("code") != "max",
            "abo_moeglich": grund == "kein_guthaben",
            "aufladen_moeglich": True,
        },
    }


# ==================== ABO-MODELL v4 (Kontingent statt €-Guthaben) ====================
# Nur aktiv bei config.ABO_MODELL_V4. Ersetzt PAYG/Guthaben durch:
#   Gratis  : monatl. KI-Text-Kontingent (tarif.monats_ki_limit) + Bild-Kontingent
#   Abo     : KI-Text unbegrenzt (monats_ki_limit NULL) + Bild-Kontingent
#   Trial   : voller Abo-Zugang bis account.trial_bis
#   Bilder über dem Monatslimit ziehen einen Bild-Credit (account.bild_credits).
#
# S-7: Kontingent und Bild-Credits werden IM GATE atomar reserviert (analog zur F3-
# Reservierung im PAYG-Pfad) – `gate_v4()` zählt unter dem Konto-Row-Lock, zieht einen
# Bild-Credit sofort und legt eine Zeile in `ki_reservierung` an, die schon während des
# langlaufenden Modell-/Bildaufrufs gegen das Monatskontingent zählt. Ohne das zogen N
# parallele Anfragen alle dieselbe Prüfung und überzogen Kontingent/Credits.

# KI-Text-Zwecke, die gegen das Gratis-Monatskontingent zählen (user-initiierte Text-KI).
# 'rezept-bild' zählt separat als Bild; Hintergrund/Admin-Zwecke (angebote*) zählen NICHT.
_KI_TEXT_ZWECKE_V4 = [
    "chat", "rezept-generieren", "guided-cooking", "guided-frage",
    "rezept-adapt", "rezept-link", "rezept-import-datei", "foto-erkennung",
    "geraete-anpassung",
    # 'ki-suche' entfällt: die Rezeptsuche läuft seit 2026-07-26 lexikalisch ohne
    # Modellaufruf (rezept_suche.py) und zählt nicht mehr ins Kontingent.
]

# S-7: Vorab-Reservierung je v4-Aufruf (Tabelle `ki_reservierung`,
# migration_ki_reservierung.sql). Art-Werte: 'ki' = KI-Text gegen das Monatskontingent,
# 'bild' = Bild innerhalb des Monats-Bildkontingents, 'bild_credit' = Bild über dem
# Monatskontingent, bezahlt mit einem sofort gezogenen Bild-Credit.
RES_KI = "ki"
RES_BILD = "bild"
RES_BILD_CREDIT = "bild_credit"
# Crash-Schutz: eine Reservierung gilt höchstens so lange. Danach zählt sie nicht mehr und
# wird beim nächsten Gate gelöscht (ein gezogener Bild-Credit kommt dabei zurück). Deutlich
# länger als die Modell-/Bild-Timeouts (120 s), kurz genug, dass ein Absturz das
# Monatskontingent nicht dauerhaft belegt.
RESERVIERUNG_MINUTEN = 10

# None = Verfügbarkeit der Tabelle noch nicht geprüft, True/False = geprüft.
_reservierung_verfuegbar: "bool | None" = None


async def _tarif_v4(con, account_id: int) -> dict:
    """Effektiver v4-Tarif: 'abo' (inkl. laufendem Trial) oder 'gratis'. Trial
    (trial_bis >= heute) => voller Abo-Zugang. 'abo' nur mit gültiger Periode
    (abo_bezahlt_bis >= heute); sonst Rückfall auf 'gratis'."""
    a = await con.fetchrow(
        "SELECT tarif_code, abo_bezahlt_bis, trial_bis FROM account WHERE id = $1", account_id)
    heute = date.today()
    ist_abo = False
    if a:
        if a["trial_bis"] and a["trial_bis"] >= heute:
            ist_abo = True
        elif a["tarif_code"] == "abo" and a["abo_bezahlt_bis"] and a["abo_bezahlt_bis"] >= heute:
            ist_abo = True
    code = "abo" if ist_abo else "gratis"
    row = await con.fetchrow("SELECT * FROM tarif WHERE code = $1", code)
    if row is None:
        row = await con.fetchrow("SELECT * FROM tarif WHERE code = 'gratis'")
    return dict(row) if row else {"code": code, "monats_ki_limit": 10, "monats_bild_limit": 3}


async def _monats_zaehler_v4(con) -> dict:
    """Nutzung im laufenden Kalendermonat (RLS-gescoped aufs aktive Konto):
    gezählte KI-Text-Aktionen und Bilder. Abgeschlossene Aufrufe stehen in `ai_nutzung`,
    LAUFENDE als Reservierung in `ki_reservierung` (S-7) – beide zählen, sonst würden
    parallele Anfragen dasselbe freie Kontingent mehrfach ausgeben."""
    r = await con.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE zweck = ANY($1::text[])
                              AND erstellt >= date_trunc('month', now())) AS ki,
             COUNT(*) FILTER (WHERE zweck = 'rezept-bild'
                              AND erstellt >= date_trunc('month', now())) AS bilder
           FROM ai_nutzung
           WHERE erstellt >= date_trunc('month', now())""",
        _KI_TEXT_ZWECKE_V4)
    res = await _reservierungen_zaehlen(con)
    return {"ki": int(r["ki"] or 0) + res["ki"],
            "bilder": int(r["bilder"] or 0) + res["bilder"]}


def _tabelle_fehlt(e: Exception) -> bool:
    """True, wenn die Exception „Relation existiert nicht" (SQLSTATE 42P01) bedeutet –
    also `ki_reservierung` noch nicht migriert ist."""
    cls = getattr(asyncpg, "UndefinedTableError", None)
    if cls is not None and isinstance(e, cls):
        return True
    return getattr(e, "sqlstate", None) == "42P01"


async def _reservierung_bereit() -> bool:
    """Ist `ki_reservierung` vorhanden (migration_ki_reservierung.sql eingespielt)?
    Einmalige Prüfung je Prozess. Fehlt die Tabelle, läuft das v4-Gate ohne Reservierung
    weiter (Verfügbarkeit vor Härtung: eine verpasste Migration darf nicht die gesamte KI
    lahmlegen) – der Zustand wird als ERROR protokolliert. Andere DB-Fehler werden
    durchgereicht, das Gate bleibt dann fail-closed (F9)."""
    global _reservierung_verfuegbar
    if _reservierung_verfuegbar is not None:
        return bool(_reservierung_verfuegbar)
    try:
        async with acquire() as con:
            await con.fetchval("SELECT 1 FROM ki_reservierung LIMIT 1")
        _reservierung_verfuegbar = True
    except Exception as e:
        if not _tabelle_fehlt(e):
            raise
        _reservierung_verfuegbar = False
        log.error("ki_reservierung fehlt – migration_ki_reservierung.sql einspielen. "
                  "Die S-7-Reservierung von Kontingent/Bild-Credits ist bis dahin inaktiv.")
    return bool(_reservierung_verfuegbar)


async def _reservierungen_zaehlen(con) -> dict:
    """Aktive (nicht verfallene) Reservierungen des Kontos: {'ki': n, 'bilder': n}.
    'bild' und 'bild_credit' zählen beide aufs Bild-Kontingent – ein Bild über dem Limit
    belegt einen Platz, bezahlt ihn aber mit einem Credit."""
    global _reservierung_verfuegbar
    if _reservierung_verfuegbar is False:
        return {"ki": 0, "bilder": 0}
    try:
        r = await con.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE art = 'ki') AS ki,
                      COUNT(*) FILTER (WHERE art <> 'ki') AS bilder
               FROM ki_reservierung WHERE ablauf > now()""")
    except Exception as e:
        if not _tabelle_fehlt(e):
            raise
        _reservierung_verfuegbar = False
        log.error("ki_reservierung fehlt – migration_ki_reservierung.sql einspielen. "
                  "Die S-7-Reservierung von Kontingent/Bild-Credits ist bis dahin inaktiv.")
        return {"ki": 0, "bilder": 0}
    return {"ki": int(r["ki"] or 0), "bilder": int(r["bilder"] or 0)}


async def _verfallene_reservierungen_raeumen(con, account_id: int) -> None:
    """Crash-Schutz: verfallene Reservierungen des Kontos löschen und für jede dabei
    freigegebene Bild-Credit-Reservierung den Credit zurückbuchen (der Aufruf kam nie
    zustande, also darf er nichts kosten). Läuft unter dem Konto-Row-Lock des Gates."""
    geraeumt = await con.fetch(
        "DELETE FROM ki_reservierung WHERE ablauf <= now() RETURNING art")
    credits = sum(1 for z in geraeumt if z["art"] == RES_BILD_CREDIT)
    if credits:
        await con.execute(
            "UPDATE account SET bild_credits = bild_credits + $2 WHERE id = $1",
            account_id, credits)


async def _reservierung_anlegen(con, account_id: int, zweck: str, *, ist_bild: bool,
                                credit: bool) -> "int | None":
    """Reservierungszeile für einen laufenden Aufruf anlegen; gibt deren ID zurück."""
    art = (RES_BILD_CREDIT if credit else RES_BILD) if ist_bild else RES_KI
    return await con.fetchval(
        "INSERT INTO ki_reservierung (account_id, user_id, zweck, art, ablauf) "
        "VALUES ($1, $2, $3, $4, now() + make_interval(mins => $5)) RETURNING id",
        account_id, current_user.get(), zweck, art, RESERVIERUNG_MINUTEN)


async def _reservierung_verbrauchen(con, reservierung_id: "int | None") -> bool:
    """Erfolg: die Reservierungszeile wird durch die echte `ai_nutzung`-Zeile ersetzt –
    derselbe Aufruf, dieselbe Transaktion, also kein Fenster ohne Zählung.

    Gibt True zurück, wenn die Reservierungszeile gelöscht wurde, False wenn sie
    bereits verfallen und geräumt war (oder keine ID übergeben wurde)."""
    if not reservierung_id:
        return False
    art = await con.fetchval(
        "DELETE FROM ki_reservierung WHERE id = $1 RETURNING art", reservierung_id)
    return art is not None


async def gate_v4(account_id: int, *, ist_bild: bool, zweck: str) -> dict:
    """S-7: v4-Gate mit atomarer Vorab-Reservierung (eigene Verbindung, eigene Transaktion).

    Serialisiert über den Konto-Row-Lock (`SELECT … FOR UPDATE` auf `account`): verfallene
    Reservierungen räumen, Monatszähler + aktive Reservierungen zählen, bei einem Bild über
    dem Monatskontingent den Bild-Credit SOFORT ziehen, Reservierungszeile anlegen. Damit
    kommen N parallele Anfragen nicht mehr alle durch dieselbe Prüfung. Der Lock wird NICHT
    über den (langlaufenden) Modell-/Bildaufruf gehalten.

    Gibt das `limit_pruefen_v4()`-Ergebnis zurück, bei Erfolg ergänzt um `reservierung_id`
    und (falls gezogen) `credit_gezogen=True`. `blockiert=True` → `LimitErreicht` werfen;
    es wurde dann nichts gezogen und nichts reserviert.
    Danach: Erfolg → `record_usage()`/`record_bild_gemini()` (ersetzt die Reservierung),
    Fehlschlag/leere Antwort → `freigeben_v4()` (Erstattung)."""
    if await _reservierung_bereit():
        async with acquire() as con:
            async with con.transaction():
                await con.fetchval(
                    "SELECT 1 FROM account WHERE id = $1 FOR UPDATE", account_id)
                await _verfallene_reservierungen_raeumen(con, account_id)
                info = await limit_pruefen_v4(con, account_id, ist_bild=ist_bild)
                if info.get("blockiert"):
                    return info
                if info.get("credit_bild"):
                    # Über dem Monats-Bildkontingent: Credit schon hier ziehen (vorher erst
                    # nach der Generierung) – nur wenn wirklich noch einer da ist.
                    if await _verbrauche_bild_credit_v4(con, account_id):
                        info["credit_gezogen"] = True
                    else:
                        # Zwischen Zählung und Lock auf 0 gefallen → lieber blocken als
                        # ein Bild ohne Deckung erzeugen.
                        info.update(blockiert=True, grund="bild_kontingent", credit_bild=False)
                        return info
                info["reservierung_id"] = await _reservierung_anlegen(
                    con, account_id, zweck, ist_bild=ist_bild,
                    credit=bool(info.get("credit_gezogen")))
                return info
    # Übergangs-Fallback, solange die Migration fehlt: Prüfung ohne Lock/Reservierung
    # (Verhalten wie vor S-7). Siehe _reservierung_bereit() – wird als ERROR geloggt.
    async with acquire() as con:
        return await limit_pruefen_v4(con, account_id, ist_bild=ist_bild)


async def freigeben_v4(account_id: int, info: "dict | None", zweck: str) -> None:
    """S-7: Reservierung zurückgeben, weil der Modell-/Bildaufruf nichts geliefert hat
    (Timeout, Exception, leere Antwort ohne abgerechnete Usage). Löscht die Reservierungszeile
    und erstattet einen im Gate gezogenen Bild-Credit – eine Transaktion unter dem Konto-Row-Lock.

    S7P-2: Idempotent – der Bild-Credit wird nur erstattet, wenn tatsächlich eine Zeile mit
    art='bild_credit' gelöscht wurde (nicht allein anhand info["credit_gezogen"]). Wurde die
    Reservierung bereits geräumt oder freigegeben, wird kein zweiter Credit erstattet.

    Fehlertolerant: ein Fehler hier darf die ursprüngliche Exception nicht überdecken.
    Bleibt die Reservierung stehen, verfällt sie spätestens nach RESERVIERUNG_MINUTEN und
    der Credit kommt beim Räumen zurück (dann kostet der Nutzer nichts)."""
    info = info or {}
    reservierung_id = info.get("reservierung_id")
    credit = bool(info.get("credit_gezogen"))
    if not reservierung_id and not credit:
        return
    try:
        async with acquire() as con:
            async with con.transaction():
                await con.fetchval(
                    "SELECT 1 FROM account WHERE id = $1 FOR UPDATE", account_id)
                art = None
                if reservierung_id:
                    art = await con.fetchval(
                        "DELETE FROM ki_reservierung WHERE id = $1 RETURNING art",
                        reservierung_id)
                if art == RES_BILD_CREDIT:
                    await con.execute(
                        "UPDATE account SET bild_credits = bild_credits + 1 WHERE id = $1",
                        account_id)
    except Exception as e:
        log.warning("Reservierung freigeben fehlgeschlagen (%s): %s", zweck, e)


def antwort_leer(resp) -> bool:
    """True, wenn ein Modellaufruf nichts Verwertbares geliefert hat UND keine abrechenbaren
    Tokens angefallen sind (keine Choices, keine Nachricht, weder Inhalt noch Tool-Calls
    ohne berechnete Tokens).

    S7P-1: Hat Vertex Tokens abgerechnet (total_tokens > 0 oder prompt_tokens > 0), gilt
    die Antwort als geliefert und verbraucht Kontingent – auch wenn der Inhalt leer ist
    (Content-Filter, leere Generierung nach Prompt-Verarbeitung). Andernfalls könnten
    angemeldete Nutzer unbegrenzt kostenpflichtige Modellaufrufe ohne Kontingentabzug auslösen.
    Erstattung bleibt nur für Exception/Timeout und Antworten ohne jede abgerechnete Usage."""
    usage = getattr(resp, "usage", None)
    if usage:
        tt = int(getattr(usage, "total_tokens", 0) or 0)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        if tt > 0 or pt > 0:
            return False
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return True
    msg = getattr(choices[0], "message", None)
    if msg is None:
        return True
    if getattr(msg, "tool_calls", None):
        return False
    return not (getattr(msg, "content", None) or "").strip()


async def limit_pruefen_v4(con, account_id: int, *, ist_bild: bool) -> dict:
    """v4-Prüfung (read-only): Monatskontingent (Gratis-KI-Texte / Bilder) + Bild-Credits,
    inklusive der aktuell laufenden Reservierungen (S-7).
    `credit_bild=True` => dieser Bild-Aufruf ist über dem Monatslimit und braucht einen
    Credit. Wer VERBINDLICH durchlassen will, nutzt `gate_v4()`: das zieht den Credit und
    legt die Reservierungszeile atomar unter dem Konto-Row-Lock an."""
    tarif = await _tarif_v4(con, account_id)
    ist_abo = (tarif.get("code") == "abo")
    zaehler = await _monats_zaehler_v4(con)
    credits = int(await con.fetchval("SELECT bild_credits FROM account WHERE id = $1", account_id) or 0)

    blockiert = False
    grund = None
    credit_bild = False
    if ist_bild:
        bild_limit = tarif.get("monats_bild_limit")
        if bild_limit is not None and zaehler["bilder"] >= int(bild_limit):
            if credits > 0:
                credit_bild = True
            else:
                blockiert, grund = True, "bild_kontingent"
    else:
        ki_limit = tarif.get("monats_ki_limit")
        if ki_limit is not None and zaehler["ki"] >= int(ki_limit):
            blockiert, grund = True, "ki_kontingent"

    return {
        "v4": True,
        "modus": "abo" if ist_abo else "gratis",
        "tarif": _tarif_public(tarif),
        "monats_ki": zaehler["ki"],
        "monats_bilder": zaehler["bilder"],
        "ki_limit": tarif.get("monats_ki_limit"),
        "bild_limit": tarif.get("monats_bild_limit"),
        "bild_credits": credits,
        "credit_bild": credit_bild,
        "blockiert": blockiert,
        "grund": grund,
    }


async def _verbrauche_bild_credit_v4(con, account_id: int) -> bool:
    """Zieht GENAU einen Bild-Credit – nur, wenn noch einer da ist (nie unter 0). Gibt
    True zurück, wenn der Credit gezogen wurde. Läuft im Gate (gate_v4) unter dem
    Konto-Row-Lock (S-7), damit parallele Anfragen denselben Credit nicht mehrfach
    ausgeben können; bei Fehlschlag des Bildaufrufs bucht freigeben_v4() ihn zurück."""
    neu = await con.fetchval(
        "UPDATE account SET bild_credits = bild_credits - 1 "
        "WHERE id = $1 AND bild_credits > 0 RETURNING bild_credits", account_id)
    return neu is not None


def limit_payload_v4(info: dict) -> dict:
    """HTTP-402-Body fürs Frontend im v4-Modell.
    grund='ki_kontingent'   → Gratis-KI-Monatskontingent erschöpft (Abo abschließen).
    grund='bild_kontingent' → Bild-Kontingent + keine Credits (Abo / Credits kaufen)."""
    ist_abo = info.get("modus") == "abo"
    return {
        "fehler": "limit",
        "grund": info.get("grund") or "kontingent",
        "tarif": info.get("tarif"),
        "modus": info.get("modus"),
        "monats_ki": info.get("monats_ki"),
        "monats_bilder": info.get("monats_bilder"),
        "ki_limit": info.get("ki_limit"),
        "bild_limit": info.get("bild_limit"),
        "bild_credits": info.get("bild_credits"),
        "hat_abo": ist_abo,
        "optionen": {
            "abo_moeglich": not ist_abo,
            "credits_kaufen_moeglich": True,
            "upgrade_moeglich": False,
            "payg_moeglich": False,
            "aufladen_moeglich": False,
        },
    }


async def kontingent_status(con, account_id: int) -> dict:
    """Read-only v4-Status fürs Frontend: Tarif (gratis/abo), Monatsnutzung + Limits,
    Bild-Credits, Trial-/Abo-Ende."""
    tarif = await _tarif_v4(con, account_id)
    zaehler = await _monats_zaehler_v4(con)
    a = await con.fetchrow(
        "SELECT bild_credits, trial_bis, abo_bezahlt_bis FROM account WHERE id = $1", account_id)
    heute = date.today()
    trial = a["trial_bis"] if a else None
    return {
        "modus": "abo" if tarif.get("code") == "abo" else "gratis",
        "tarif": _tarif_public(tarif),
        "monats_ki": zaehler["ki"],
        "ki_limit": tarif.get("monats_ki_limit"),
        "monats_bilder": zaehler["bilder"],
        "bild_limit": tarif.get("monats_bild_limit"),
        "bild_credits": int(a["bild_credits"]) if a and a["bild_credits"] is not None else 0,
        "trial": bool(trial and trial >= heute),
        "trial_bis": str(trial) if trial else None,
        "abo_bezahlt_bis": str(a["abo_bezahlt_bis"]) if a and a["abo_bezahlt_bis"] else None,
    }


async def kontingent_status_konto(account_id: int) -> dict:
    """Wrapper mit eigener (RLS-gescopeter) Verbindung fürs Frontend/Endpoint."""
    async with acquire() as con:
        return await kontingent_status(con, account_id)


# ---------- Aufruf + Erfassung ----------

async def _reserviere_payg(acc: int, zweck: str) -> Decimal:
    """F3: reserviert atomar bis zu PAYG_RESERVE_CENTS vom Guthaben (nur im PAYG-Modus),
    serialisiert über den Konto-Row-Lock. Gibt den reservierten Betrag zurück (0 im Abo).
    Blockt via LimitErreicht, wenn kein Guthaben (mehr) vorhanden ist. Der Lock wird NICHT
    über den anschließenden (langlaufenden) Modell-/Bild-Aufruf gehalten."""
    reserviert = Decimal(0)
    async with acquire() as con:
        if await _billing_modus(con, acc) == "payg":
            async with con.transaction():
                bal = await con.fetchval(
                    "SELECT guthaben_cents FROM account WHERE id = $1 FOR UPDATE", acc)
                bal = Decimal(str(bal)) if bal is not None else Decimal(0)
                if bal <= 0:
                    raise LimitErreicht(await limit_pruefen(con, acc))
                reserviert = min(PAYG_RESERVE_CENTS, bal)
                await buche(con, acc, -reserviert, "reservierung", zweck)
    return reserviert


async def _erstatte(acc: int, betrag: Decimal, zweck: str) -> None:
    """Erstattet eine (Teil-)Reservierung zurück aufs Guthaben. Fehlertolerant."""
    if betrag and betrag > 0:
        try:
            async with acquire() as con:
                await buche(con, acc, betrag, "erstattung", zweck)
        except Exception as e:
            log.warning("Reservierungs-Erstattung fehlgeschlagen (%s): %s", zweck, e)


async def complete(client, zweck: str, **kwargs):
    """Führt eine Chat-Completion aus und erfasst Token + Kosten (token-basiert,
    Preise je Modell aus _PREISE). Gibt das Completion-Objekt zurück."""
    # Harte Barriere: ohne KI-Freigabe gar nicht erst die API aufrufen.
    if not await darf_ki(current_user.get(), current_account.get()):
        raise PermissionError("KI-Funktionen sind für diesen Nutzer deaktiviert.")
    # Tarif-Limit VOR dem Modell-Aufruf prüfen (sonst würde es bezahlt).
    acc = current_account.get() or 1
    # v4: Kontingent-Modell (kein €-Guthaben). S-7: Das Gate reserviert das Kontingent
    # atomar UNTER dem Konto-Row-Lock, bevor der Modellaufruf läuft – parallele Anfragen
    # können dasselbe Kontingent nicht mehrfach ausgeben. Ohne verwertbare Antwort
    # (Timeout/Exception/leere Antwort ohne abgerechnete Usage) gibt das finally
    # die Reservierung zurück; bei Erfolg (oder abgerechneten Tokens, S7P-1) ersetzt
    # record_usage() sie durch die echte ai_nutzung-Zeile.
    if config.ABO_MODELL_V4:
        try:
            info = await gate_v4(acc, ist_bild=False, zweck=zweck)
        except Exception as e:
            log.warning("gate_v4 fehlgeschlagen (%s): %s", zweck, e)
            raise AbrechnungspruefungFehlgeschlagen() from e
        if info.get("blockiert"):
            raise LimitErreicht(info)
        kwargs["model"] = modell_fuer_zweck(zweck)
        geliefert = False
        try:
            resp = await client.chat.completions.create(**kwargs)
            geliefert = not antwort_leer(resp)
        finally:
            if not geliefert:
                await freigeben_v4(acc, info, zweck)
        if not geliefert:
            # Nichts geliefert und keine abrechenbare Usage → kein Kontingent-Verbrauch.
            # Die (leere) Antwort geht wie bisher an den Aufrufer, der daraus seinen
            # Fehlermeldungsweg macht.
            return resp
        await record_usage(resp, zweck, modell=kwargs.get("model"),
                           reservierung_id=info.get("reservierung_id"))
        return resp
    try:
        async with acquire() as con:
            info = await limit_pruefen(con, acc)
    except Exception as e:
        log.warning("limit_pruefen fehlgeschlagen (%s): %s", zweck, e)
        # F9: Fail-closed – ohne gültige Prüfung KEIN kostenpflichtiger Modell-Aufruf.
        raise AbrechnungspruefungFehlgeschlagen() from e
    if info and info.get("blockiert"):
        raise LimitErreicht(info)
    # Zentrales Modell-Routing: das Modell ergibt sich aus der Operation (zweck),
    # nicht aus einer Nutzer-Einstellung. Ein evtl. übergebenes model wird überschrieben.
    kwargs["model"] = modell_fuer_zweck(zweck)

    # F3: Vorab-Reservierung im PAYG-Modus. Sie serialisiert Check+Abbuchung über den
    # Konto-Row-Lock, sodass N gleichzeitige Anfragen mit Mini-Guthaben nicht je einen
    # bezahlten Call auslösen können. record_usage() rechnet danach gegen die realen
    # Kosten ab (zu viel Reserviertes wird erstattet); der Lock wird NICHT über den
    # (langlaufenden) Modell-Aufruf gehalten.
    reserviert = await _reserviere_payg(acc, zweck)
    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception:
        await _erstatte(acc, reserviert, zweck)   # nichts geliefert → Reservierung zurück
        raise
    await record_usage(resp, zweck, modell=kwargs.get("model"), reserviert=reserviert)
    return resp


async def record_usage(resp, zweck: str, modell: str | None = None, cost_usd: float | None = None,
                       reserviert: Decimal = Decimal(0),
                       reservierung_id: "int | None" = None) -> None:
    """Protokolliert Token + Kosten eines Completion-Resultats. Fehlertolerant:
    stört den KI-Flow nie. Kosten = Token × Modellpreis (_PREISE) + Markup.
    (cost_usd wird nicht mehr genutzt – früher der LiteLLM-Kosten-Header.)

    `reservierung_id` (S-7, v4): die im Gate angelegte Reservierungszeile wird in
    DERSELBEN Transaktion wie die Nutzungszeile gelöscht – der Aufruf zählt also
    lückenlos genau einmal."""
    try:
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        tt = int(getattr(usage, "total_tokens", 0) or (pt + ct)) if usage else 0
        # Gemini meldet completion_tokens teils nur unter completion_tokens_details
        # (Thinking-Token) → aus total ableiten, damit nichts unberechnet bleibt.
        if ct == 0 and tt > pt:
            ct = tt - pt
        mdl = modell or getattr(resp, "model", None)
        uid = current_user.get()
        acc = current_account.get() or 1
        async with acquire() as con:
            markup = await _markup_fuer(con, acc)
            cost = (kosten_cents(mdl, pt, ct) * (Decimal(1) + markup / Decimal(100))).quantize(Decimal("0.0001"))
            _erfasse_kosten(cost)
            async with con.transaction():
                await con.execute(
                    """INSERT INTO ai_nutzung
                       (user_id, zweck, modell, prompt_tokens, completion_tokens, total_tokens, kosten_cents)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    uid, zweck, (str(mdl) if mdl else None), pt, ct, tt, cost,
                )
                # S-7: Reservierung des v4-Gates ablösen (atomar mit der Zeile oben).
                await _reservierung_verbrauchen(con, reservierung_id)
                # Im Abo-Modus ist die Nutzung durch das Monatsbudget gedeckt → kein
                # Guthaben-Abzug. Nur PAYG/Overage bucht vom Prepaid-Guthaben ab.
                # F3: Eine ggf. vorab reservierte Summe wird gegen die realen Kosten verrechnet.
                # v4: kein Guthaben-Abzug – die ai_nutzung-Zeile oben dient dem
                # Monatszähler/Analytics; das Kontingent war bis hierher über die
                # Reservierungszeile gedeckt (S-7).
                if not config.ABO_MODELL_V4:
                    modus = await _billing_modus(con, acc)
                    if modus == "payg":
                        rest = cost - reserviert
                        if rest > 0:
                            await buche(con, acc, -rest, "nutzung", zweck, clamp=True)
                        elif rest < 0:
                            # Mehr reserviert als verbraucht → Differenz erstatten.
                            await buche(con, acc, -rest, "erstattung", zweck)
                    elif reserviert > 0:
                        # Modus wechselte zwischenzeitlich auf Abo → Reservierung voll erstatten.
                        await buche(con, acc, reserviert, "erstattung", zweck)
    except Exception as e:
        log.warning("record_usage fehlgeschlagen (%s): %s", zweck, e)


BILD_SCHNELL_CENTS = 5     # (alt, ungenutzt – Bild jetzt tokenbasiert)
BILD_STANDARD_CENTS = 9    # (alt, ungenutzt)
BILD_TIER_DEFAULT = "schnell"
BILD_STUFEN = ("schnell", "standard")
# Auflösung je Stufe für gemini-3.1-flash-image (imageConfig.imageSize): 512px vs 1024px.
BILD_SIZE = {"schnell": "512", "standard": "1K"}
# Token-Preise (€/1 Mio., Doku-Werte): Bild-Output 60, Prompt 0,5, Thinking/Text-Output 3.
BILD_PREIS_IMAGE_1M = 60.00
BILD_PREIS_PROMPT_1M = 0.50
BILD_PREIS_THOUGHT_1M = 3.00


async def get_bild_stufe() -> dict:
    """Bildgenerierungs-Stufe des aktiven Kontos (schnell|standard; Default schnell)."""
    acc = current_account.get() or 1
    async with acquire() as con:
        s = await con.fetchval("SELECT einstellungen->>'bild_stufe' FROM account WHERE id = $1", acc)
    return {"stufe": s if s in BILD_STUFEN else BILD_TIER_DEFAULT, "stufen": list(BILD_STUFEN)}


async def set_bild_stufe(stufe: str | None) -> dict:
    s = stufe if stufe in BILD_STUFEN else BILD_TIER_DEFAULT
    acc = current_account.get() or 1
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{bild_stufe}', to_jsonb($2::text)) WHERE id = $1", acc, s)
    return {"stufe": s}


async def bild_modell_und_preis() -> tuple[str, str, str]:
    """(Modell, imageSize, Stufe) für die Bildgenerierung. Zentral festgelegt (kein
    Nutzer-Setting mehr): Standard = 512px (günstig). Abgerechnet tokenbasiert."""
    stufe = BILD_TIER_DEFAULT  # "schnell" = 512px
    return config.IMAGE_MODEL, BILD_SIZE.get(stufe, "512"), stufe


async def record_bild_gemini(prompt_tokens: int, image_tokens: int, thought_tokens: int,
                             stufe: str = "schnell", reserviert: Decimal = Decimal(0),
                             reservierung_id: "int | None" = None,
                             credit_gezogen: bool = False,
                             credit_bild: bool = False) -> None:
    """Bucht ein per gemini-3.1-flash-image erzeugtes Bild TOKENBASIERT: Bild-Output-Tokens
    × 60/1M + Prompt × 0,5/1M + Thinking × 3/1M (Doku-Preise) + Stufen-/PAYG-Aufschlag.
    Nur PAYG/Overage zieht Guthaben ab (im Abo durch das Volumen gedeckt).
    F3: `reserviert` (€-Vorab-Reservierung) wird gegen die realen Kosten verrechnet.
    S-7: `reservierung_id` ist die im Gate angelegte Kontingent-Reservierung; sie wird in
    derselben Transaktion wie die Nutzungszeile gelöscht. Der Bild-Credit für ein Bild über
    dem Monatskontingent ist bereits im Gate (gate_v4) abgezogen worden – hier wird NICHT
    noch einmal gezogen, ES SEI DENN (S7P-2b): die Reservierung war zwischenzeitlich
    verfallen und der Credit wurde bereits vom Ablaufräumer erstattet.
    S7P-9: Im Übergangs-Fallback ohne Migration (_reservierung_bereit == False) konnte das
    Gate keinen Credit vorab reservieren/ziehen (credit_gezogen=False, credit_bild=True);
    in diesem Fall wird der Bild-Credit hier atomar beim Verbuchen nachgebucht."""
    try:
        pt = int(prompt_tokens or 0); it = int(image_tokens or 0); th = int(thought_tokens or 0)
        eur = (pt * BILD_PREIS_PROMPT_1M + it * BILD_PREIS_IMAGE_1M + th * BILD_PREIS_THOUGHT_1M) / 1_000_000
        roh = Decimal(str(eur * 100))   # Cent (vor Aufschlag)
        uid = current_user.get()
        acc = current_account.get() or 1
        async with acquire() as con:
            markup = await _markup_fuer(con, acc)
            betrag = (roh * (Decimal(1) + markup / Decimal(100))).quantize(Decimal("0.0001"))
            _erfasse_kosten(betrag)
            async with con.transaction():
                await con.execute(
                    """INSERT INTO ai_nutzung
                       (user_id, zweck, modell, prompt_tokens, completion_tokens, total_tokens, kosten_cents)
                       VALUES ($1, 'rezept-bild', $2, $3, $4, $5, $6)""",
                    uid, f"Bild ({stufe})", pt, it + th, pt + it + th, betrag)
                # S-7: Reservierung des v4-Gates ablösen (atomar mit der Zeile oben).
                geloescht = await _reservierung_verbrauchen(con, reservierung_id)
                if credit_gezogen and reservierung_id and not geloescht:
                    # S7P-2b: War die Reservierung vor dem Abschluss verfallen (> 10 min)
                    # und wurde vom Ablaufräumer geräumt (Credit bereits erstattet), den
                    # Credit in derselben Transaktion erneut ziehen.
                    gezogen = await _verbrauche_bild_credit_v4(con, acc)
                    if not gezogen:
                        log.warning(
                            "Bild geliefert, aber Reservierung war verfallen und Konto %s "
                            "hatte keine Bild-Credits mehr zum Nachbuchen.", acc)
                elif credit_bild and not credit_gezogen:
                    # S7P-9: Fallback ohne Migration (_reservierung_bereit == False).
                    # Der Credit wurde im Gate nicht vorab gezogen, da die
                    # Reservierungstabelle fehlt; hier atomar beim Verbuchen nachbuchen.
                    gezogen = await _verbrauche_bild_credit_v4(con, acc)
                    if not gezogen:
                        log.warning(
                            "Bild geliefert (Fallback ohne Reservierung), aber Konto %s "
                            "hatte keine Bild-Credits mehr zum Abbuchen.", acc)
                if not config.ABO_MODELL_V4:
                    modus = await _billing_modus(con, acc)
                    if modus == "payg":
                        rest = betrag - reserviert
                        if rest > 0:
                            await buche(con, acc, -rest, "nutzung", f"Bild ({stufe})", clamp=True)
                        elif rest < 0:
                            await buche(con, acc, -rest, "erstattung", f"Bild ({stufe})")
                    elif reserviert > 0:
                        await buche(con, acc, reserviert, "erstattung", f"Bild ({stufe})")
    except Exception as e:
        log.warning("record_bild_gemini fehlgeschlagen: %s", e)


async def record_bild(zweck: str = "rezept-bild", cents: int | None = None, stufe: str = "schnell") -> None:
    """Bucht ein generiertes Bild (kein Token-Verbrauch). `cents` = Roh-Bildpreis;
    der Stufen-/PAYG-Aufschlag wird wie bei Token aufgeschlagen (Bilder zählen voll
    ins Nutzungsvolumen)."""
    try:
        roh = Decimal(int(cents if cents is not None else BILD_SCHNELL_CENTS))
        uid = current_user.get()
        acc = current_account.get() or 1
        async with acquire() as con:
            markup = await _markup_fuer(con, acc)
            betrag = (roh * (Decimal(1) + markup / Decimal(100))).quantize(Decimal("0.0001"))
            await con.execute(
                """INSERT INTO ai_nutzung
                   (user_id, zweck, modell, prompt_tokens, completion_tokens, total_tokens, kosten_cents)
                   VALUES ($1, $2, $3, 0, 0, 0, $4)""",
                uid, zweck, f"Imagen ({stufe})", betrag)
            if await _billing_modus(con, acc) == "payg":
                await buche(con, acc, -betrag, "nutzung", zweck, clamp=True)
    except Exception as e:
        log.warning("record_bild fehlgeschlagen: %s", e)


# ---------- Plattform-Einstellungen (Preise) ----------

async def _preise(con) -> dict:
    try:
        row = await con.fetchrow(
            "SELECT abo_einzel_cents, abo_mehrere_cents, api_markup_prozent, overage_markup_prozent, "
            "bild_schnell_cents, bild_standard_cents, foto_pack_cents, foto_pack_credits "
            "FROM plattform_einstellung WHERE id = 1")
    except asyncpg.PostgresError:
        # Gemeint ist der Fall „Foto-Pack-Spalten noch nicht migriert" (migration_beta_quelle_kuendigung.sql
        # bzw. db.ensure_preisliste_schema). Bewusst die Oberklasse: ist es ein anderer
        # DB-Fehler, schlägt die Ersatzabfrage darunter ebenfalls fehl und wirft ihn weiter.
        # Ohne die Spalten kommen die Pack-Werte aus den Code-Defaults – die Anzeige bleibt
        # korrekt und es gibt keinen 500er, egal in welcher Reihenfolge Deploy und Migration laufen.
        row = await con.fetchrow(
            "SELECT abo_einzel_cents, abo_mehrere_cents, api_markup_prozent, overage_markup_prozent, "
            "bild_schnell_cents, bild_standard_cents FROM plattform_einstellung WHERE id = 1")
    if row is None:
        return {"abo_einzel_cents": ABO_EINZEL_CENTS, "abo_mehrere_cents": ABO_MEHRERE_CENTS,
                "api_markup_prozent": MARKUP_DEFAULT, "overage_markup_prozent": OVERAGE_MARKUP_DEFAULT,
                "bild_schnell_cents": BILD_SCHNELL_CENTS, "bild_standard_cents": BILD_STANDARD_CENTS,
                "foto_pack_cents": FOTO_PACK_CENTS, "foto_pack_credits": config.FOTO_PACK_CREDITS}
    return dict(row)


# ---------- Preisliste: EINE Quelle für Preise/Kontingente (Frontend + Stripe) ----------
# Abopreis und Monatskontingente stehen in `tarif`, das Foto-Pack in `plattform_einstellung`.
# Das Frontend rendert daraus seine Texte (GET /api/preise) – kein hartcodierter Preis mehr.

async def foto_pack(con=None) -> dict:
    """Preis + Credit-Anzahl des Foto-Packs aus der DB (Fallback: Code-Default)."""
    if con is not None:
        p = await _preise(con)
    else:
        async with acquire(bypass=True) as c:
            p = await _preise(c)
    return {"preis_cents": int(p.get("foto_pack_cents") or FOTO_PACK_CENTS),
            "credits": int(p.get("foto_pack_credits") or config.FOTO_PACK_CREDITS)}


async def preisliste() -> dict:
    """Öffentliche Preisliste für die Anzeige: Gratis-/Abo-Kontingente, Abopreis, Foto-Pack.
    `ki_limit`/`bild_limit` = NULL bedeutet unbegrenzt – das Frontend formuliert entsprechend,
    sodass eine spätere Deckelung des Abos automatisch im Text erscheint."""
    def _stufe(t: dict | None) -> dict:
        t = t or {}
        return {
            "code": t.get("code"),
            "name": t.get("name"),
            "preis_cents": int(t.get("preis_cents") or 0),
            "ki_limit": int(t["monats_ki_limit"]) if t.get("monats_ki_limit") is not None else None,
            "bild_limit": int(t["monats_bild_limit"]) if t.get("monats_bild_limit") is not None else None,
        }
    async with acquire(bypass=True) as con:
        rows = {r["code"]: dict(r) for r in await con.fetch(
            "SELECT code, name, preis_cents, monats_ki_limit, monats_bild_limit "
            "FROM tarif WHERE code = ANY($1::text[])", ["gratis", "abo"])}
        pack = await foto_pack(con)
    return {"gratis": _stufe(rows.get("gratis")), "abo": _stufe(rows.get("abo")), "foto_pack": pack}


async def guthaben_aufladen(account_id: int, betrag_cents) -> dict:
    """Lädt Guthaben eines Kontos auf (oder zieht ab bei negativem Betrag). Admin/Support;
    kontoübergreifend → bypass. Bucht über das Ledger (revisionssicher)."""
    betrag = Decimal(str(betrag_cents))
    typ = "aufladung" if betrag >= 0 else "korrektur"
    async with acquire(bypass=True) as con:
        exists = await con.fetchval("SELECT 1 FROM account WHERE id = $1", int(account_id))
        if not exists:
            return {"error": "Konto nicht gefunden"}
        neu = await buche(con, int(account_id), betrag, typ, "Admin-Buchung")
    return {"account_id": int(account_id), "guthaben_cents": float(neu or 0)}


# ---------- Guthaben-Einladungen (Admin-Codes mit Freiguthaben, einmalig) ----------

async def create_guthaben_einladung(betrag_cents, erstellt_von: int | None) -> dict:
    """Erzeugt einen einmalig gültigen Einladungscode mit Freiguthaben (Super-Admin).
    Gibt {code, betrag_cents} zurück; das Frontend baut daraus den Einladungslink."""
    import uuid
    try:
        cents = int(betrag_cents)
    except (TypeError, ValueError):
        cents = 0
    if cents <= 0:
        return {"error": "Betrag muss größer als 0 sein."}
    code = uuid.uuid4().hex[:16]
    async with acquire(bypass=True) as con:
        await con.execute(
            "INSERT INTO guthaben_einladung (code, betrag_cents, erstellt_von) VALUES ($1, $2, $3)",
            code, cents, int(erstellt_von) if erstellt_von else None)
    return {"code": code, "betrag_cents": cents}


async def einloese_guthaben_einladung(code: str | None) -> dict:
    """Löst einen Guthaben-Einladungscode für das AKTIVE Konto ein (einmalig, atomar).
    Schreibt das Guthaben gut und sperrt den Code."""
    code = (code or "").strip()
    if not code:
        return {"error": "Kein Code angegeben."}
    acc = current_account.get() or 1
    async with acquire(bypass=True) as con:
        async with con.transaction():
            row = await con.fetchrow(
                "SELECT betrag_cents, eingeloest_am FROM guthaben_einladung WHERE code = $1 FOR UPDATE", code)
            if row is None:
                return {"error": "Ungültiger Einladungscode."}
            if row["eingeloest_am"] is not None:
                return {"error": "Dieser Code wurde bereits eingelöst."}
            await con.execute(
                "UPDATE guthaben_einladung SET eingeloest_am = now(), eingeloest_account = $2 WHERE code = $1",
                code, acc)
            neu = await buche(con, acc, int(row["betrag_cents"]), "aufladung", "Einladungscode")
    return {"betrag_cents": int(row["betrag_cents"]), "guthaben_cents": float(neu) if neu is not None else None}


async def get_preise() -> dict:
    async with acquire() as con:
        p = await _preise(con)
    return {"abo_einzel_cents": int(p["abo_einzel_cents"]),
            "abo_mehrere_cents": int(p["abo_mehrere_cents"]),
            "api_markup_prozent": float(p["api_markup_prozent"]),
            "overage_markup_prozent": float(p.get("overage_markup_prozent", OVERAGE_MARKUP_DEFAULT)),
            "bild_schnell_cents": int(p.get("bild_schnell_cents", BILD_SCHNELL_CENTS)),
            "bild_standard_cents": int(p.get("bild_standard_cents", BILD_STANDARD_CENTS)),
            "foto_pack_cents": int(p.get("foto_pack_cents") or FOTO_PACK_CENTS),
            "foto_pack_credits": int(p.get("foto_pack_credits") or config.FOTO_PACK_CREDITS)}


async def set_preise(abo_einzel_cents: int, abo_mehrere_cents: int, api_markup_prozent: float,
                     bild_schnell_cents: int | None = None, bild_standard_cents: int | None = None,
                     overage_markup_prozent: float | None = None,
                     foto_pack_cents: int | None = None,
                     foto_pack_credits: int | None = None) -> dict:
    async with acquire() as con:
        cur = await _preise(con)
        bs = int(bild_schnell_cents if bild_schnell_cents is not None else cur.get("bild_schnell_cents", BILD_SCHNELL_CENTS))
        bt = int(bild_standard_cents if bild_standard_cents is not None else cur.get("bild_standard_cents", BILD_STANDARD_CENTS))
        ov = Decimal(str(overage_markup_prozent if overage_markup_prozent is not None
                         else cur.get("overage_markup_prozent", OVERAGE_MARKUP_DEFAULT)))
        fp = int(foto_pack_cents if foto_pack_cents is not None else (cur.get("foto_pack_cents") or FOTO_PACK_CENTS))
        fc = int(foto_pack_credits if foto_pack_credits is not None
                 else (cur.get("foto_pack_credits") or config.FOTO_PACK_CREDITS))
        if fp < 0 or fc < 1:
            raise ValueError("Foto-Pack: Preis darf nicht negativ und die Credit-Anzahl muss mindestens 1 sein")
        await con.execute(
            """UPDATE plattform_einstellung
               SET abo_einzel_cents = $1, abo_mehrere_cents = $2, api_markup_prozent = $3,
                   bild_schnell_cents = $4, bild_standard_cents = $5, overage_markup_prozent = $6,
                   foto_pack_cents = $7, foto_pack_credits = $8
               WHERE id = 1""",
            int(abo_einzel_cents), int(abo_mehrere_cents), Decimal(str(api_markup_prozent)), bs, bt, ov, fp, fc,
        )
    return await get_preise()


# ---------- Abo / monatliche Grundpauschale ----------

def _plus_month(d: date) -> date:
    """Ein Monat später, Tag möglichst erhalten (rollende Abo-Periode). 31.→Monatsende."""
    import calendar
    y = d.year + (1 if d.month == 12 else 0)
    m = 1 if d.month == 12 else d.month + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# Empfohlene KI-Stufen je Tarif (Modell + Bild). Wird nach einer Tarifbuchung
# vorgeschlagen; bewusst OHNE Preise/Token nach außen.
TARIF_EMPFEHLUNG = {
    "basis": {"modell_stufe": "schnell",  "bild_stufe": "schnell"},
    "plus":  {"modell_stufe": "standard", "bild_stufe": "schnell"},
    "max":   {"modell_stufe": "pro",      "bild_stufe": "standard"},
    "payg":  {"modell_stufe": "standard", "bild_stufe": "schnell"},
}


def tarif_empfehlung(code: str | None) -> dict:
    """Empfohlene Modell-/Bildstufe für einen Tarif (nur Stufen-Labels, keine Preise)."""
    e = TARIF_EMPFEHLUNG.get(code or "payg", TARIF_EMPFEHLUNG["payg"])
    return {
        "tarif": code or "payg",
        "modell_stufe": e["modell_stufe"],
        "bild_stufe": e["bild_stufe"],
        "modell_label": e["modell_stufe"].capitalize(),
        "bild_label": e["bild_stufe"].capitalize(),
    }


def monatsbetrag_cents(personen: int, einzel_cents: int, mehrere_cents: int,
                       abo_typ: str | None = None) -> int:
    """Pauschale: Multi (mehrere) wenn der Nutzer 'multi' gewählt hat ODER ab 2 Personen;
    sonst Single (einzel). Einladungen kosten nichts."""
    if abo_typ == "multi" or int(personen) >= 2:
        return int(mehrere_cents)
    return int(einzel_cents)


async def get_abo_typ() -> dict:
    """Gewähltes Abo-Modell des Kontos (single|multi; Default single)."""
    acc = current_account.get() or 1
    async with acquire() as con:
        v = await con.fetchval("SELECT einstellungen->>'abo_typ' FROM account WHERE id = $1", acc)
    return {"abo_typ": v if v in ("single", "multi") else "single"}


async def set_abo_typ(abo_typ: str | None) -> dict:
    t = abo_typ if abo_typ in ("single", "multi") else "single"
    acc = current_account.get() or 1
    async with acquire() as con:
        await con.execute(
            "UPDATE account SET einstellungen = jsonb_set(coalesce(einstellungen,'{}'::jsonb), "
            "'{abo_typ}', to_jsonb($2::text)) WHERE id = $1", acc, t)
    return {"abo_typ": t}


async def _abo_buchung(con, account_id: int, periode_start: date, betrag_cents: int,
                       *, idempotenz: str | None = None) -> int:
    """Erfasst EINE Abo-Buchung (volle Monatsgebühr bzw. anteilige Upgrade-Differenz).
    KEIN Guthaben-Abzug: das Abo wird separat berechnet, der Zugang ist unabhängig vom
    Guthaben (Guthaben nur für Extra-Volumen).

    F4: Idempotenz läuft NICHT mehr über (account_id, zeitraum) – sonst kollidierten mehrere
    Buchungen am selben Tag (z. B. Abo abschließen + gleich upgraden) und die zweite wurde
    still verschluckt (Unter-Fakturierung). Nur der automatische Monats-Sweep übergibt einen
    `idempotenz`-Schlüssel (z. B. "monat:ACC:PERIODE"), damit tägliche Catch-up-Läufe nicht
    doppelt buchen. Nutzer-initiierte Buchungen (idempotenz=None) werden immer angehängt.
    Gibt den tatsächlich gebuchten Betrag zurück (0 = nichts gebucht / bereits vorhanden)."""
    if not betrag_cents or int(betrag_cents) <= 0:
        return 0
    personen = await con.fetchval("SELECT count(*) FROM person WHERE account_id = $1", account_id) or 0
    try:
        gebucht = await con.fetchval(
            """INSERT INTO abo_buchung (account_id, zeitraum, personen, betrag_cents, idempotenz)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (idempotenz) WHERE idempotenz IS NOT NULL DO NOTHING
               RETURNING betrag_cents""",
            account_id, periode_start, int(personen), int(betrag_cents), idempotenz,
        )
    except (asyncpg.exceptions.UndefinedColumnError,
            asyncpg.exceptions.InvalidColumnReferenceError):
        # Migration (idempotenz-Spalte/Index) noch nicht eingespielt → Altverhalten
        # (Dedup über UNIQUE(account_id, zeitraum)). Nach der Migration greift der obere Pfad.
        gebucht = await con.fetchval(
            """INSERT INTO abo_buchung (account_id, zeitraum, personen, betrag_cents)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (account_id, zeitraum) DO NOTHING
               RETURNING betrag_cents""",
            account_id, periode_start, int(personen), int(betrag_cents),
        )
    return int(gebucht) if gebucht is not None else 0


async def abo_sweep() -> dict:
    """Täglich: verlängert laufende Abos rollend um einen Monat (neue Buchung, KEIN
    Guthaben-Abzug), wendet geplante Tarifwechsel (Downgrade) bzw. Kündigungen zum
    Periodenende an und lässt gekündigte Abos danach auf PAYG zurückfallen. Setzt
    außerdem die Pay-as-you-go-Überlauf-Einwilligung zu Monatsbeginn zurück."""
    heute = date.today()
    konten: set[int] = set()
    gebucht_cents = 0
    async with acquire(bypass=True) as con:
        # Überlauf-Einwilligung aus Vormonaten löschen (Consent gilt nur den lfd. Monat).
        await con.execute(
            "UPDATE account SET payg_overage = false, payg_overage_seit = NULL "
            "WHERE payg_overage = true AND (payg_overage_seit IS NULL OR payg_overage_seit < $1)",
            heute.replace(day=1))
        accounts = await con.fetch(
            "SELECT id, tarif_code, abo_bezahlt_bis, abo_gekuendigt, abo_naechster_tarif "
            "FROM account WHERE abo_status = 'aktiv' AND tarif_code <> 'payg'")
        for a in accounts:
            aid = int(a["id"])
            bis = a["abo_bezahlt_bis"]
            code = a["tarif_code"]
            gekuendigt = bool(a["abo_gekuendigt"])
            naechster = a["abo_naechster_tarif"]
            if bis is None:
                # Abo-Tarif ohne Periode (Altbestand) → eine Periode ab heute starten.
                row = await con.fetchrow("SELECT preis_cents FROM tarif WHERE code = $1", code)
                await con.execute("UPDATE account SET abo_bezahlt_bis = $2 WHERE id = $1", aid, _plus_month(heute))
                if row:
                    g = await _abo_buchung(con, aid, heute, int(row["preis_cents"]),
                                           idempotenz=f"monat:{aid}:{heute.isoformat()}")
                    if g:
                        konten.add(aid); gebucht_cents += g
                continue
            # Fällige Perioden abarbeiten (i.d.R. genau eine, da täglich).
            while bis is not None and bis <= heute:
                if gekuendigt or naechster == "payg":
                    await con.execute(
                        "UPDATE account SET tarif_code = 'payg', abo_bezahlt_bis = NULL, "
                        "abo_gekuendigt = false, abo_naechster_tarif = NULL, "
                        "payg_overage = false, payg_overage_seit = NULL WHERE id = $1", aid)
                    bis = None
                    break
                ziel = naechster or code
                # Preis OHNE aktiv-Filter lesen (Bestandsschutz): Wird ein Tarif nur aus
                # dem Verkauf genommen (aktiv=false), zahlen Bestandskunden weiter ihren
                # regulären Preis. Existiert der Tarif gar nicht mehr (gelöscht), lässt sich
                # kein Preis mehr ableiten → sauber auf PAYG zurückfallen statt gratis
                # (0 €) zu verlängern.
                row = await con.fetchrow("SELECT preis_cents FROM tarif WHERE code = $1", ziel)
                if row is None:
                    await con.execute(
                        "UPDATE account SET tarif_code = 'payg', abo_bezahlt_bis = NULL, "
                        "abo_gekuendigt = false, abo_naechster_tarif = NULL, "
                        "payg_overage = false, payg_overage_seit = NULL WHERE id = $1", aid)
                    bis = None
                    break
                preis = int(row["preis_cents"])
                neu = _plus_month(bis)
                await con.execute(
                    "UPDATE account SET tarif_code = $2, abo_bezahlt_bis = $3, abo_naechster_tarif = NULL "
                    "WHERE id = $1", aid, ziel, neu)
                g = await _abo_buchung(con, aid, bis, preis,
                                       idempotenz=f"monat:{aid}:{bis.isoformat()}")
                if g:
                    konten.add(aid); gebucht_cents += g
                code, naechster, bis = ziel, None, neu
    return {"konten": len(konten), "gebucht_cents": gebucht_cents}


# ---------- Tarifwahl je Konto + Verwaltung ----------

async def _abo_status(con, account_id: int) -> dict:
    """Abo-Periodeninfo des Kontos fürs Frontend (kein Geld, nur Status/Daten)."""
    a = await con.fetchrow(
        "SELECT tarif_code, abo_bezahlt_bis, abo_gekuendigt, abo_naechster_tarif FROM account WHERE id = $1",
        account_id)
    if a is None:
        return {"tarif_code": "payg", "bezahlt_bis": None, "gekuendigt": False,
                "naechster_tarif": None, "aktiv": False}
    bis = a["abo_bezahlt_bis"]
    aktiv = a["tarif_code"] != "payg" and bis is not None and bis >= date.today()
    return {
        "tarif_code": a["tarif_code"],
        "bezahlt_bis": bis.isoformat() if bis else None,
        "gekuendigt": bool(a["abo_gekuendigt"]),
        "naechster_tarif": a["abo_naechster_tarif"],
        "aktiv": aktiv,
    }


async def _tarif_antwort(con, account_id: int, empfehlung_fuer: str | None = None) -> dict:
    """Standard-Antwort der Tarif-Endpunkte: Limitstatus + Abo-Periode + KI-Empfehlung."""
    info = await limit_pruefen(con, account_id)
    info["abo"] = await _abo_status(con, account_id)
    info["empfehlung"] = tarif_empfehlung(empfehlung_fuer or info["abo"]["tarif_code"])
    return info


async def get_tarif() -> dict:
    """Aktueller Tarif + Live-Limitstatus + Abo-Periode + Empfehlung des aktiven Kontos."""
    acc = current_account.get() or 1
    async with acquire() as con:
        return await _tarif_antwort(con, acc)


async def set_tarif(code: str | None) -> dict:
    """Tarif des aktiven Kontos ändern – NUR kündigen bzw. auf einen kostenlosen Tarif wechseln.

    SICHERHEIT: Ein KOSTENPFLICHTIGER Tarif wird hier nie mehr vergeben. Die Berechtigung
    entsteht ausschließlich aus einer bestätigten Zahlung (Stripe-Webhook, künftig Store-Kauf).
    Vorher setzte diese Funktion `tarif_code` und `abo_bezahlt_bis` direkt und buchte die
    Gebühr nur als Ledger-Eintrag OHNE Guthaben-Abzug – jeder eingeloggte Nutzer konnte sich
    damit per `PUT /api/konto/tarif` ein Abo selbst freischalten (Fund 2026-07-25).

    Weiter möglich:
      • 'payg' bzw. jeder Tarif mit preis_cents = 0: kündigen → Abo läuft bis Periodenende,
        danach der kostenlose Tarif (sofort, falls kein aktives Abo).
    Nicht mehr möglich (→ Fehler, Hinweis auf die Kasse):
      • Abo abschließen, Upgrade, Downgrade zwischen bezahlten Tarifen."""
    acc = current_account.get() or 1
    heute = date.today()
    async with acquire() as con:
        ziel = await con.fetchrow(
            "SELECT code, ist_payg, preis_cents, sortierung FROM tarif WHERE code = $1 AND aktiv", code)
        if ziel is None:
            return {"error": "Unbekannter Tarif"}
        # Im Kontingent-Modell v4 kommt die Abo-Berechtigung ausschließlich aus der Zahlung.
        if config.ABO_MODELL_V4:
            return {"error": "Tarifwechsel läuft über die Kasse (Abo buchen bzw. kündigen)."}
        if not (ziel["ist_payg"] or int(ziel["preis_cents"] or 0) == 0):
            return {"error": "Kostenpflichtige Tarife werden nur über die Kasse gebucht."}
        a = await con.fetchrow("SELECT tarif_code, abo_bezahlt_bis FROM account WHERE id = $1", acc)
        akt_code = (a["tarif_code"] if a else None) or "payg"
        bis = a["abo_bezahlt_bis"] if a else None
        abo_aktiv = akt_code != "payg" and bis is not None and bis >= heute

        if ziel["ist_payg"] or ziel["code"] == "payg":
            # Kündigen: aktives Abo bis Periodenende behalten, danach PAYG; sonst sofort PAYG.
            if abo_aktiv:
                await con.execute(
                    "UPDATE account SET abo_gekuendigt = true, abo_naechster_tarif = 'payg' WHERE id = $1", acc)
            else:
                await con.execute(
                    "UPDATE account SET tarif_code = 'payg', abo_bezahlt_bis = NULL, abo_gekuendigt = false, "
                    "abo_naechster_tarif = NULL, payg_overage = false, payg_overage_seit = NULL WHERE id = $1", acc)
        elif not abo_aktiv:
            # Neues Abo: volle Gebühr buchen, Freischaltung +1 Monat ab heute.
            await con.execute(
                "UPDATE account SET tarif_code = $2, abo_bezahlt_bis = $3, abo_gekuendigt = false, "
                "abo_naechster_tarif = NULL, payg_overage = false, payg_overage_seit = NULL WHERE id = $1",
                acc, ziel["code"], _plus_month(heute))
            await _abo_buchung(con, acc, heute, int(ziel["preis_cents"]))
        elif ziel["code"] == akt_code:
            # gleicher Tarif: nur eine vorgemerkte Kündigung/Downgrade aufheben (reaktivieren).
            await con.execute(
                "UPDATE account SET abo_gekuendigt = false, abo_naechster_tarif = NULL WHERE id = $1", acc)
        else:
            akt = await con.fetchrow("SELECT preis_cents, sortierung FROM tarif WHERE code = $1", akt_code)
            akt_sort = int(akt["sortierung"]) if akt else 0
            akt_preis = int(akt["preis_cents"]) if akt else 0
            if int(ziel["sortierung"]) > akt_sort:
                # Upgrade: anteilige Differenz für die Restlaufzeit, bezahlt_bis unverändert.
                rest_tage = max(0, (bis - heute).days)
                diff = max(0, int(ziel["preis_cents"]) - akt_preis)
                anteil = int(round(diff * rest_tage / 30.0))
                await con.execute(
                    "UPDATE account SET tarif_code = $2, abo_gekuendigt = false, abo_naechster_tarif = NULL "
                    "WHERE id = $1", acc, ziel["code"])
                if anteil > 0:
                    await _abo_buchung(con, acc, heute, anteil)
            else:
                # Downgrade: zum Periodenende vormerken (aktueller Tarif bleibt bis dahin).
                await con.execute(
                    "UPDATE account SET abo_gekuendigt = false, abo_naechster_tarif = $2 WHERE id = $1",
                    acc, ziel["code"])

        # Empfehlung bezieht sich auf den vom Nutzer gewählten Zieltarif.
        return await _tarif_antwort(con, acc, empfehlung_fuer=ziel["code"])


async def set_payg_overage(an: bool) -> dict:
    """Schaltet den Pay-as-you-go-Überlauf des aktiven Kontos (weiter aus Guthaben,
    wenn ein Limit erreicht ist). Gilt nur bis zur nächsten Freischaltung: sobald das
    Konto wieder unter dem Limit liegt, deaktiviert limit_pruefen() den Überlauf
    automatisch – er muss dann beim nächsten Limit erneut aktiviert werden."""
    acc = current_account.get() or 1
    async with acquire() as con:
        if an:
            await con.execute(
                "UPDATE account SET payg_overage = true, payg_overage_seit = $2 WHERE id = $1",
                acc, date.today())
        else:
            await con.execute(
                "UPDATE account SET payg_overage = false, payg_overage_seit = NULL WHERE id = $1", acc)
        return await limit_pruefen(con, acc)


async def list_tarife() -> list[dict]:
    """Aktive Tarife für die Tarif-Auswahl (jeder Nutzer)."""
    async with acquire() as con:
        rows = await con.fetch("SELECT * FROM tarif WHERE aktiv ORDER BY sortierung, preis_cents")
    return [_tarif_public(dict(r)) for r in rows]


async def admin_list_tarife() -> list[dict]:
    """Alle Tarife (auch inaktive) für den Admin-Editor."""
    async with acquire(bypass=True) as con:
        rows = await con.fetch("SELECT * FROM tarif ORDER BY sortierung, preis_cents")
    return [_tarif_public(dict(r)) for r in rows]


async def admin_set_tarife(tarife: list[dict]) -> list[dict]:
    """Super-Admin aktualisiert die Tarif-Definitionen (Preis/Aufschlag/Tages-+Wochenvolumen)."""
    def _opt(v):
        return int(v) if v not in (None, "") else None
    # Server-seitige Validierung (die REST-API ist direkt aufrufbar, daher darf sich der
    # Schutz nicht allein auf das Frontend verlassen): negative/ungültige Beträge ablehnen,
    # statt sie still als 0 € oder gelöschtes Limit zu speichern.
    for t in tarife or []:
        if not t.get("code"):
            continue
        try:
            preis = int(t.get("preis_cents") or 0)
            markup = Decimal(str(t.get("markup_prozent") or 0))
            tag, woche = _opt(t.get("tages_limit_cents")), _opt(t.get("wochen_limit_cents"))
            ki, bild = _opt(t.get("monats_ki_limit")), _opt(t.get("monats_bild_limit"))
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError(f"Ungültige Zahlenwerte für Tarif {t.get('code')}")
        if preis < 0 or markup < 0 or (tag is not None and tag < 0) or (woche is not None and woche < 0):
            raise ValueError(f"Negative Werte sind nicht zulässig (Tarif {t.get('code')})")
        if (ki is not None and ki < 0) or (bild is not None and bild < 0):
            raise ValueError(f"Monatskontingente dürfen nicht negativ sein (Tarif {t.get('code')})")
    async with acquire(bypass=True) as con:
        for t in tarife or []:
            if not t.get("code"):
                continue
            await con.execute(
                """UPDATE tarif SET name = $2, preis_cents = $3, markup_prozent = $4,
                       tages_limit_cents = $5, wochen_limit_cents = $6, aktiv = $7, sortierung = $8,
                       monats_ki_limit = $9, monats_bild_limit = $10
                   WHERE code = $1""",
                t["code"], str(t.get("name") or ""), int(t.get("preis_cents") or 0),
                Decimal(str(t.get("markup_prozent") or 0)), _opt(t.get("tages_limit_cents")),
                _opt(t.get("wochen_limit_cents")), bool(t.get("aktiv", True)),
                int(t.get("sortierung") or 0),
                _opt(t.get("monats_ki_limit")), _opt(t.get("monats_bild_limit")))
    return await admin_list_tarife()


# ---------- Abrechnungs-Übersicht ----------

def _as_date(s):
    """'YYYY-MM-DD'-String → date-Objekt (asyncpg braucht echtes date für ::date)."""
    if s is None or isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _nutzung_filter(von, bis, zwecke, person_id, start_idx=1, prefix=""):
    """WHERE-Bedingung + Parameter für ai_nutzung-Auswertungen.
    prefix = Tabellen-Alias (z.B. 'n') bei JOINs."""
    px = (prefix + ".") if prefix else ""
    von, bis = _as_date(von), _as_date(bis)
    conds, params, i = [], [], start_idx
    if von:
        conds.append(f"{px}erstellt >= ${i}::date"); params.append(von); i += 1
    if bis:
        conds.append(f"{px}erstellt < (${i}::date + 1)"); params.append(bis); i += 1
    if zwecke:
        conds.append(f"{px}zweck = ANY(${i}::text[])"); params.append(list(zwecke)); i += 1
    if person_id:
        conds.append(f"{px}user_id = ${i}"); params.append(int(person_id)); i += 1
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return where, params, i


def _label_modelle(rows) -> list[dict]:
    """nach_modell-Rohzeilen auf Stufen-Labels (Schnell/Standard/Pro/Bild) mappen + summieren."""
    agg: dict[str, dict] = {}
    for r in rows:
        label = modell_label(r["modell"])
        a = agg.setdefault(label, {"modell": label, "anzahl": 0, "total_tokens": 0, "kosten_cents": Decimal(0)})
        a["anzahl"] += int(r["anzahl"])
        a["total_tokens"] += int(r["total_tokens"] or 0)
        a["kosten_cents"] += Decimal(str(r["kosten_cents"] or 0))
    out = sorted(agg.values(), key=lambda x: x["kosten_cents"], reverse=True)
    for a in out:
        a["kosten_cents"] = float(a["kosten_cents"])
    return out


async def abrechnung(von=None, bis=None, zwecke=None, person_id=None) -> dict:
    """Guthaben + Abo + gefilterter KI-Verbrauch des aktiven Kontos.
    Filter: von/bis (YYYY-MM-DD; Default letzte 30 Tage), zwecke (Liste), person_id."""
    acc = current_account.get() or 1
    if not von and not bis:
        heute = date.today()
        von = (heute - timedelta(days=29)).isoformat()
        bis = heute.isoformat()
    where, params, _ = _nutzung_filter(von, bis, zwecke, person_id)
    wp, pp, _ = _nutzung_filter(von, bis, zwecke, person_id, prefix="n")

    def _g(row):
        d = dict(row)
        if d.get("kosten_cents") is not None:
            d["kosten_cents"] = float(d["kosten_cents"])
        return d

    async with acquire() as con:
        konto = await con.fetchrow(
            "SELECT guthaben_cents, abo_status, einstellungen->>'abo_typ' AS abo_typ, "
            "einstellungen->>'modell_stufe' AS modell_stufe, einstellungen->>'bild_stufe' AS bild_stufe "
            "FROM account WHERE id = $1", acc)
        guthaben = konto["guthaben_cents"] if konto else 0
        try:
            limit = await limit_pruefen(con, acc)
        except Exception as e:  # Tarif-Migration noch nicht eingespielt → PAYG-Fallback
            log.warning("limit_pruefen (abrechnung) fehlgeschlagen: %s", e)
            limit = {"modus": "payg", "tarif": _tarif_public(None), "verbrauch": {},
                     "rest": {}, "limit_erreicht": None, "payg_overage": False}
        personen = int(await con.fetchval("SELECT count(*) FROM person WHERE account_id = $1", acc) or 0)
        nutzer = int(await con.fetchval("SELECT count(*) FROM account_mitglied WHERE account_id = $1", acc) or 1)
        abo_buchungen = await con.fetch(
            "SELECT zeitraum, personen, betrag_cents, gebucht FROM abo_buchung ORDER BY zeitraum DESC LIMIT 12")
        abo_periode = await _abo_status(con, acc)
        bereich = await con.fetchrow(f"""
            SELECT COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                   COALESCE(SUM(total_tokens),0) AS total_tokens,
                   COALESCE(SUM(kosten_cents),0) AS kosten_cents, COUNT(*) AS anzahl,
                   COALESCE(SUM(kosten_cents) FILTER (WHERE zweck = 'rezept-bild'),0) AS bild_cents,
                   COALESCE(SUM(kosten_cents) FILTER (WHERE zweck <> 'rezept-bild'),0) AS token_cents
            FROM ai_nutzung{where}""", *params)
        nach_zweck = await con.fetch(f"""
            SELECT zweck, COUNT(*) AS anzahl, COALESCE(SUM(total_tokens),0) AS total_tokens,
                   COALESCE(SUM(kosten_cents),0) AS kosten_cents
            FROM ai_nutzung{where} GROUP BY zweck ORDER BY SUM(kosten_cents) DESC""", *params)
        nach_modell = await con.fetch(f"""
            SELECT COALESCE(NULLIF(modell,''),'?') AS modell, COUNT(*) AS anzahl,
                   COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(kosten_cents),0) AS kosten_cents
            FROM ai_nutzung{where} GROUP BY 1""", *params)
        nach_person = await con.fetch(f"""
            SELECT n.user_id, COALESCE(u.name, u.email, 'Unbekannt') AS person, COUNT(*) AS anzahl,
                   COALESCE(SUM(n.total_tokens),0) AS total_tokens, COALESCE(SUM(n.kosten_cents),0) AS kosten_cents
            FROM ai_nutzung n LEFT JOIN app_user u ON u.id = n.user_id{wp}
            GROUP BY n.user_id, u.name, u.email ORDER BY SUM(n.kosten_cents) DESC""", *pp)
        nutzer_liste = await con.fetch(
            "SELECT u.id, COALESCE(u.name, u.email) AS name FROM account_mitglied m "
            "JOIN app_user u ON u.id = m.user_id WHERE m.account_id = $1 ORDER BY 2", acc)
        tage = await con.fetch(f"""
            SELECT (erstellt AT TIME ZONE 'Europe/Berlin')::date AS tag,
                   COUNT(*) AS anzahl, COALESCE(SUM(total_tokens),0) AS total_tokens,
                   COALESCE(SUM(kosten_cents),0) AS kosten_cents
            FROM ai_nutzung{where} GROUP BY tag ORDER BY tag""", *params)
        avg7 = await con.fetchval(
            "SELECT COALESCE(SUM(kosten_cents),0)/7.0 FROM ai_nutzung WHERE erstellt >= now() - interval '7 days'")

    avg7 = float(avg7 or 0)
    reichweite = int(float(guthaben or 0) / avg7) if avg7 > 0 else None

    return {
        "guthaben_cents": float(guthaben or 0),
        "filter": {"von": von, "bis": bis, "zwecke": list(zwecke) if zwecke else None, "person_id": person_id},
        "modelle": {
            "ki": (konto["modell_stufe"] if konto and konto["modell_stufe"] in TIER_MODELL else DEFAULT_TIER),
            "bild": (konto["bild_stufe"] if konto and konto["bild_stufe"] in BILD_STUFEN else BILD_TIER_DEFAULT),
        },
        "bereich": _g(bereich) if bereich else {},
        "nach_zweck": [_g(r) for r in nach_zweck],
        "nach_modell": _label_modelle(nach_modell),
        "nach_person": [_g(r) for r in nach_person],
        "tage": [_g(r) for r in tage],
        "reichweite_tage": reichweite,
        "mehrnutzer": nutzer > 1,
        "nutzer_liste": [dict(r) for r in nutzer_liste],
        "tarif": {
            "status": (konto["abo_status"] if konto else "aktiv"),
            "personen": personen,
            "modus": limit["modus"],
            "payg_overage": limit["payg_overage"],
            "verbrauch": limit["verbrauch"],
            "rest": limit["rest"],
            "limit_erreicht": limit["limit_erreicht"],
            **limit["tarif"],   # code, name, preis_cents, markup_prozent, tages_/wochen_limit_cents …
            "abo": abo_periode,   # bezahlt_bis, gekuendigt, naechster_tarif, aktiv
            "buchungen": [dict(r) for r in abo_buchungen],
        },
    }


async def nutzung_protokoll(von=None, bis=None, zwecke=None, person_id=None, limit=50, offset=0) -> dict:
    """Paginiertes Aktivitätsprotokoll: einzelne KI-Aufrufe mit Token/Kosten."""
    where, params, i = _nutzung_filter(von, bis, zwecke, person_id, prefix="n")
    async with acquire() as con:
        total = await con.fetchval(f"SELECT COUNT(*) FROM ai_nutzung n{where}", *params)
        rows = await con.fetch(f"""
            SELECT n.id, n.erstellt, n.zweck, n.modell, n.prompt_tokens, n.completion_tokens,
                   n.total_tokens, n.kosten_cents, COALESCE(u.name, u.email) AS person
            FROM ai_nutzung n LEFT JOIN app_user u ON u.id = n.user_id{where}
            ORDER BY n.erstellt DESC LIMIT ${i} OFFSET ${i + 1}""", *params, int(limit), int(offset))
    return {
        "total": int(total or 0), "limit": int(limit), "offset": int(offset),
        "rows": [{
            "id": r["id"], "erstellt": r["erstellt"].isoformat(), "zweck": r["zweck"],
            "modell": modell_label(r["modell"]),
            "prompt_tokens": int(r["prompt_tokens"] or 0), "completion_tokens": int(r["completion_tokens"] or 0),
            "total_tokens": int(r["total_tokens"] or 0), "kosten_cents": float(r["kosten_cents"] or 0),
            "person": r["person"],
        } for r in rows],
    }
