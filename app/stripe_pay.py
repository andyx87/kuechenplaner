"""Stripe-Guthaben-Aufladung (Pay-as-you-go, echtes €-Guthaben).

Ablauf ohne Webhook (sofort nutzbar): Checkout-Session anlegen → Stripe-Bezahlseite →
Redirect zurück mit ?aufladung=SESSION_ID → Server prüft die Session per API (bezahlt?)
und schreibt das Guthaben über das Ledger (billing.buche, idempotent per Session-ID) gut.

Keys kommen aus den Umgebungsvariablen (STRIPE_SECRET_KEY); nie im Code/Repo.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from . import billing, config
from .db import acquire

log = logging.getLogger("koch")

MIN_CENTS = 200       # Mindestaufladung 2 € (deckt Stripe-Gebühr)
MAX_CENTS = 20000     # Obergrenze 200 € pro Aufladung


def _feld(obj, key, default=None):
    """Liest ein Feld aus einem Stripe-Objekt ODER einem dict.
    Ab stripe>=v8 ist StripeObject kein dict mehr (kein .get); Index-Zugriff
    funktioniert aber für beide Fälle."""
    try:
        val = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if val is None else val


def _stripe():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or ""
    return stripe


def verfuegbar() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


async def checkout(account_id: int, betrag_cents: int, origin: str) -> dict:
    """Erzeugt eine Stripe-Checkout-Session und gibt die Bezahl-URL zurück."""
    if not verfuegbar():
        return {"error": "Aufladung ist derzeit nicht konfiguriert."}
    betrag = max(MIN_CENTS, min(int(betrag_cents or 0), MAX_CENTS))
    stripe = _stripe()
    origin = (origin or "").rstrip("/") or config.APP_BASE_URL

    def _create():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": "eur",
                    "unit_amount": betrag,
                    "product_data": {"name": "Guthaben Küchenassistent"},
                },
            }],
            metadata={"account_id": str(account_id), "art": "guthaben"},
            success_url=f"{origin}/?aufladung={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/?aufladung=abbruch",
        )
    try:
        sess = await asyncio.to_thread(_create)
        return {"url": sess.url}
    except Exception as e:
        log.warning("stripe checkout fehlgeschlagen: %s", e)
        return {"error": f"Aufladung konnte nicht gestartet werden: {type(e).__name__}"}


async def checkout_abo(account_id: int, origin: str) -> dict:
    """Startet das wiederkehrende Topfplan-Abo (Stripe Subscription-Checkout). account_id
    liegt in der Session- UND der Subscription-Metadaten, damit spätere invoice.paid-/
    subscription-Events das Konto sicher auflösen können."""
    if not verfuegbar() or not config.STRIPE_PRICE_ABO:
        return {"error": "Abo ist derzeit nicht konfiguriert."}
    stripe = _stripe()
    origin = (origin or "").rstrip("/") or config.APP_BASE_URL
    async with acquire() as con:
        cust = await con.fetchval("SELECT stripe_customer_id FROM account WHERE id = $1", account_id)

    def _create():
        kw = dict(
            mode="subscription",
            line_items=[{"price": config.STRIPE_PRICE_ABO, "quantity": 1}],
            metadata={"account_id": str(account_id), "art": "abo"},
            subscription_data={"metadata": {"account_id": str(account_id), "art": "abo"}},
            client_reference_id=str(account_id),
            success_url=f"{origin}/?abo={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/?abo=abbruch",
        )
        if cust:
            kw["customer"] = cust
        return stripe.checkout.Session.create(**kw)
    try:
        sess = await asyncio.to_thread(_create)
        return {"url": sess.url}
    except Exception as e:
        log.warning("stripe abo-checkout fehlgeschlagen: %s", e)
        return {"error": f"Abo konnte nicht gestartet werden: {type(e).__name__}"}


async def checkout_credits(account_id: int, origin: str) -> dict:
    """Startet den einmaligen Kauf eines Foto-Credit-Packs (mode=payment)."""
    if not verfuegbar() or not config.STRIPE_PRICE_CREDITS:
        return {"error": "Foto-Credits sind derzeit nicht konfiguriert."}
    stripe = _stripe()
    origin = (origin or "").rstrip("/") or config.APP_BASE_URL
    # Credit-Anzahl aus der Preisliste (DB), NICHT aus dem Code: sonst zeigt das Frontend
    # eine andere Zahl an, als der Kauf gutschreibt. Der Wert wandert in die Session-Metadaten
    # und gilt damit unverändert für diesen Kauf, auch wenn das Pack später geändert wird.
    pack = await billing.foto_pack()

    def _create():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": config.STRIPE_PRICE_CREDITS, "quantity": 1}],
            metadata={"account_id": str(account_id), "art": "credits",
                      "credits": str(pack["credits"])},
            client_reference_id=str(account_id),
            success_url=f"{origin}/?credits={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/?credits=abbruch",
        )
    try:
        sess = await asyncio.to_thread(_create)
        return {"url": sess.url}
    except Exception as e:
        log.warning("stripe credits-checkout fehlgeschlagen: %s", e)
        return {"error": f"Kauf konnte nicht gestartet werden: {type(e).__name__}"}


async def kuendige_abo(account_id: int) -> dict:
    """Kündigt das Stripe-Abo des Kontos zum Ende der bezahlten Periode.

    Bewusst `cancel_at_period_end` statt sofortiger Löschung: Der Nutzer hat den laufenden
    Monat bezahlt und behält ihn. Zusätzlich wird `abo_gekuendigt` gesetzt, damit der
    Monats-Sweep die Periode nicht verlängert. Rückgabe enthält `bis` = Vertragsende.

    Ohne Stripe-Abo (z.B. Beta-Konto oder Gratis) wird nur der Kontostatus gesetzt – die
    Erklärung des Nutzers gilt trotzdem als angenommen."""
    async with acquire(bypass=True) as con:
        a = await con.fetchrow(
            "SELECT stripe_subscription_id, abo_bezahlt_bis, tarif_code FROM account WHERE id = $1",
            int(account_id))
    if a is None:
        return {"error": "Konto nicht gefunden"}
    sub_id = a["stripe_subscription_id"]
    bis = a["abo_bezahlt_bis"]
    gekuendigt_bei_stripe = False
    if sub_id and verfuegbar():
        stripe = _stripe()
        try:
            sub = await asyncio.to_thread(
                stripe.Subscription.modify, sub_id, cancel_at_period_end=True)
            gekuendigt_bei_stripe = True
            ende = _ts_to_date(getattr(sub, "current_period_end", None))
            if ende:
                bis = ende
        except Exception as e:  # noqa: BLE001 – die Kündigung darf nie am Anbieter scheitern
            log.warning("stripe Kündigung fehlgeschlagen (Konto %s): %s", account_id, e)
    async with acquire(bypass=True) as con:
        await con.execute(
            "UPDATE account SET abo_gekuendigt = true, abo_naechster_tarif = NULL WHERE id = $1",
            int(account_id))
    return {"ok": True, "stripe": gekuendigt_bei_stripe,
            "bis": bis.isoformat() if bis else None,
            "hatte_abo": bool(sub_id) or (a["tarif_code"] or "") == "abo"}


async def bestaetige(session_id: str, account_id: int, bypass: bool = False) -> dict:
    """Prüft eine Checkout-Session und schreibt – wenn bezahlt und noch nicht verbucht –
    das Guthaben gut (idempotent über die Session-ID im Ledger-Zweck).

    bypass=True ist NUR für den Stripe-Webhook gedacht (S-3, Audit AND-22): Dort fehlt der
    Auth-Kontext, `db.acquire()` setzt dann `app.account_id='-1'` (fail-closed, F10) und der
    INSERT in `guthaben_buchung` (FORCE ROW LEVEL SECURITY, WITH CHECK account_id) würde die
    Policy verletzen – die Gutschrift bliebe aus und Stripe stellte das Event endlos erneut
    zu. Der Bypass gilt nur innerhalb des `async with`-Blocks (Reset durch `db.acquire` im
    finally); die Kontobindung bleibt explizit über die Metadaten-Prüfung unten
    (`ziel_acc != account_id`) und den account_id-Filter jeder Query. Der Redirect-Pfad
    (`POST /guthaben/checkout-bestaetigen`, mit Session) läuft weiter OHNE Bypass über den
    Auth-Kontext."""
    session_id = (session_id or "").strip()
    if not session_id or not verfuegbar():
        return {"gutgeschrieben": False}
    stripe = _stripe()
    try:
        sess = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
    except Exception as e:
        log.warning("stripe session retrieve fehlgeschlagen: %s", e)
        return {"gutgeschrieben": False, "error": "Zahlung konnte nicht geprüft werden."}

    if _feld(sess, "payment_status") != "paid":
        return {"gutgeschrieben": False}
    meta = _feld(sess, "metadata") or {}
    ziel_acc = int(_feld(meta, "account_id") or 0)
    if ziel_acc != int(account_id):
        return {"gutgeschrieben": False}   # Session gehört nicht zu diesem Konto
    betrag = int(_feld(sess, "amount_total") or 0)
    zweck = f"Stripe:{session_id}"

    async with acquire(bypass=bypass) as con:
        async with con.transaction():
            # Konto-Zeile sperren → Prüfung + Buchung atomar serialisieren (Idempotenz OHNE
            # Unique-Index): zwei parallele Bestätigungen derselben Session (Doppelklick/zwei
            # Tabs) können sich nicht überholen – die zweite sieht die Buchung der ersten.
            await con.execute("SELECT 1 FROM account WHERE id = $1 FOR UPDATE", account_id)
            schon = await con.fetchval(
                "SELECT 1 FROM guthaben_buchung WHERE account_id = $1 AND zweck = $2", account_id, zweck)
            if not schon:
                saldo = await billing.buche(con, account_id, betrag, "aufladung", zweck)
                return {"gutgeschrieben": True, "betrag_cents": betrag,
                        "guthaben_cents": float(saldo or 0)}
            saldo = await con.fetchval("SELECT guthaben_cents FROM account WHERE id = $1", account_id)
    return {"gutgeschrieben": False, "bereits_verbucht": True,
            "guthaben_cents": float(saldo or 0)}


def webhook_konfiguriert() -> bool:
    return bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))


async def _event_neu(event_id: str) -> bool:
    """Idempotenz-CLAIM: markiert das Event als in Arbeit und liefert True, wenn es NEU war
    (INSERT-first verhindert Doppelverbuchung bei parallelen Stripe-Zustellungen).
    WICHTIG: Scheitert die Verarbeitung danach, muss der Claim per _event_freigeben()
    zurückgenommen werden – sonst gilt ein fehlgeschlagenes Event für immer als verarbeitet,
    der Stripe-Retry läuft ins 'duplikat' und der Kunde hat gezahlt, ohne etwas zu bekommen.
    Bypass (kein Auth-Kontext)."""
    if not event_id:
        return True
    async with acquire(bypass=True) as con:
        r = await con.execute(
            "INSERT INTO stripe_event (event_id) VALUES ($1) ON CONFLICT (event_id) DO NOTHING",
            event_id)
    return r.strip().endswith("1")   # 'INSERT 0 1' = neu; 'INSERT 0 0' = Duplikat


async def _event_freigeben(event_id: str) -> None:
    """Nimmt den Idempotenz-Claim eines GESCHEITERTEN Events zurück, damit die
    Stripe-Wiederzustellung (Endpoint antwortet 500) erneut verarbeiten kann. Tolerant –
    schlägt auch das fehl, bleibt der Claim stehen und der Fall ist im Log sichtbar."""
    if not event_id:
        return
    try:
        async with acquire(bypass=True) as con:
            await con.execute("DELETE FROM stripe_event WHERE event_id = $1", event_id)
    except Exception as e:  # noqa: BLE001
        log.error("stripe webhook: Claim-Freigabe für %s fehlgeschlagen: %s – Event bleibt "
                  "als verarbeitet markiert, manuell prüfen!", event_id, e)


async def _gutschreibe_credits(acc: int, credits: int) -> dict:
    async with acquire(bypass=True) as con:
        stand = await con.fetchval(
            "UPDATE account SET bild_credits = bild_credits + $2 WHERE id = $1 RETURNING bild_credits",
            acc, int(credits))
    log.info("stripe webhook: Konto %s +%s Foto-Credits (Stand %s)", acc, credits, stand)
    return {"ok": True, "credits_gutgeschrieben": int(credits), "credits_stand": int(stand or 0)}


def _ts_to_date(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date() if ts else None
    except Exception:
        return None


async def _aktiviere_abo(sess, acc: int) -> dict:
    """checkout.session.completed (art=abo): Konto auf 'abo', Stripe-Kunde/Subscription
    + Periodenende übernehmen."""
    stripe = _stripe()
    sub_id = _feld(sess, "subscription")
    cust_id = _feld(sess, "customer")
    bis = None
    if sub_id:
        try:
            sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
            bis = _ts_to_date(_feld(sub, "current_period_end"))
        except Exception as e:
            log.warning("stripe Subscription.retrieve fehlgeschlagen: %s", e)
    async with acquire(bypass=True) as con:
        await con.execute(
            "UPDATE account SET tarif_code = 'abo', stripe_subscription_id = $2, "
            "stripe_customer_id = COALESCE($3, stripe_customer_id), "
            "abo_bezahlt_bis = COALESCE($4, abo_bezahlt_bis), abo_gekuendigt = false, "
            "trial_bis = NULL WHERE id = $1",
            acc, sub_id, cust_id, bis)
    log.info("stripe webhook: Abo aktiviert Konto %s (sub %s, bis %s)", acc, sub_id, bis)
    return {"ok": True, "abo_aktiv": True, "konto": acc, "bis": str(bis)}


async def _verlaengere_abo(sub_id: str) -> dict:
    """invoice.paid: verlängert die Abo-Periode. Konto robust über Subscription-Metadaten
    (account_id) bzw. gespeicherte sub-id auflösen (Reihenfolge der Events nicht garantiert)."""
    stripe = _stripe()
    acc, bis = 0, None
    try:
        sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
        acc = int(_feld(_feld(sub, "metadata") or {}, "account_id") or 0)
        bis = _ts_to_date(_feld(sub, "current_period_end"))
    except Exception as e:
        log.warning("stripe Subscription.retrieve (invoice.paid) fehlgeschlagen: %s", e)
    if not acc:
        async with acquire(bypass=True) as con:
            acc = int(await con.fetchval(
                "SELECT id FROM account WHERE stripe_subscription_id = $1", sub_id) or 0)
    if not acc:
        return {"ok": True, "ignoriert": "kein Konto zur Subscription"}
    async with acquire(bypass=True) as con:
        await con.execute(
            "UPDATE account SET tarif_code = 'abo', stripe_subscription_id = $2, "
            "abo_bezahlt_bis = COALESCE($3, abo_bezahlt_bis), abo_gekuendigt = false, "
            "trial_bis = NULL WHERE id = $1",
            acc, sub_id, bis)
    log.info("stripe webhook: Abo verlängert Konto %s (sub %s, bis %s)", acc, sub_id, bis)
    return {"ok": True, "verlaengert_bis": str(bis), "konto": acc}


async def _beende_abo(sub_id: str) -> dict:
    """customer.subscription.deleted: Konto zurück auf 'gratis'."""
    async with acquire(bypass=True) as con:
        r = await con.execute(
            "UPDATE account SET tarif_code = 'gratis', abo_gekuendigt = true, "
            "stripe_subscription_id = NULL WHERE stripe_subscription_id = $1", sub_id)
    log.info("stripe webhook: Abo beendet (sub %s) -> gratis [%s]", sub_id, r)
    return {"ok": True, "abo_beendet": True}


async def handle_webhook(payload: bytes, sig_header: str | None) -> dict:
    """Verifiziert die Stripe-Signatur und verarbeitet Zahlungen server-seitig & idempotent
    (unabhängig vom Redirect). Behandelt:
      - checkout.session.completed / async_payment_succeeded: art = abo | credits | guthaben(alt)
      - invoice.paid: Abo-Verlängerung (neue Periode)
      - customer.subscription.deleted: Abo-Ende -> gratis
    Wirft ValueError bei ungültiger Signatur (Endpoint -> 400)."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET nicht gesetzt")
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header or "", secret)
    except Exception as e:
        raise ValueError(f"ungültige Stripe-Signatur: {type(e).__name__}") from e

    event_id = _feld(event, "id") or ""
    typ = _feld(event, "type")
    if not await _event_neu(event_id):
        return {"ok": True, "duplikat": event_id}
    try:
        return await _verarbeite_event(typ, event)
    except Exception:
        # Verarbeitung gescheitert: Claim zurücknehmen, damit der Stripe-Retry (Endpoint
        # antwortet 500) das Event erneut verarbeiten kann statt ins 'duplikat' zu laufen.
        await _event_freigeben(event_id)
        raise


async def _verarbeite_event(typ: str | None, event) -> dict:
    """Eigentliche Event-Verarbeitung – getrennt vom Idempotenz-Claim in handle_webhook()."""
    obj = _feld(_feld(event, "data") or {}, "object") or {}
    if typ in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        meta = _feld(obj, "metadata") or {}
        art = _feld(meta, "art")
        acc = int(_feld(meta, "account_id") or 0)
        session_id = _feld(obj, "id") or ""
        if art == "credits" and acc:
            # Metadaten sind führend (Stand zum Kaufzeitpunkt); fehlen sie, gilt die Preisliste.
            credits = _feld(meta, "credits")
            if not credits:
                credits = (await billing.foto_pack())["credits"]
            return await _gutschreibe_credits(acc, int(credits))
        if art == "abo" and acc:
            return await _aktiviere_abo(obj, acc)
        if art == "guthaben" and acc:   # Alt-Flow (Prepaid-Guthaben), Kompatibilität
            # S-3: Der Webhook hat keinen Auth-Kontext – ohne Bypass würde die FORCE-RLS-
            # Policy von guthaben_buchung (WITH CHECK account_id, fail-closed '-1' aus F10)
            # die Gutschrift ablehnen, der Endpoint mit 500 antworten und Stripe das Event
            # endlos erneut zustellen. Kontobindung: Metadaten-Prüfung + account_id-Filter.
            res = await bestaetige(session_id, acc, bypass=True)
            return {"ok": True, "verbucht": bool(res.get("gutgeschrieben")), "session": session_id}
        return {"ok": True, "ignoriert": f"art={art}"}
    if typ == "invoice.paid":
        sub_id = _feld(obj, "subscription")
        return await _verlaengere_abo(sub_id) if sub_id else {"ok": True, "ignoriert": "invoice ohne subscription"}
    if typ == "customer.subscription.deleted":
        sub_id = _feld(obj, "id")
        if sub_id:
            return await _beende_abo(sub_id)
    return {"ok": True, "ignoriert": typ}
