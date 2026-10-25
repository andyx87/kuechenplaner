"""Backoffice-Kennzahlen (Admin-Dashboard).

Aggregiert kontoübergreifend (bypass=True, da RLS sonst nur das eigene Konto zeigt):
Nutzer, Haushalte, aktive Abos je Tarif, MRR, KI-Nutzung/-Kosten. Bewusst lesend und
fehlertolerant – das Dashboard darf nie einen 500 werfen.
"""
from __future__ import annotations

import logging

from .db import acquire

log = logging.getLogger("koch")


async def kennzahlen() -> dict:
    """Liefert die KPI-Übersicht fürs Admin-Dashboard."""
    async with acquire(bypass=True) as con:
        nutzer_gesamt = await con.fetchval("SELECT COUNT(*) FROM app_user")
        nutzer_aktiv = await con.fetchval("SELECT COUNT(*) FROM app_user WHERE aktiv")
        neu_7d = await con.fetchval(
            "SELECT COUNT(*) FROM app_user WHERE created_at >= now() - interval '7 days'")
        neu_30d = await con.fetchval(
            "SELECT COUNT(*) FROM app_user WHERE created_at >= now() - interval '30 days'")
        haushalte = await con.fetchval("SELECT COUNT(*) FROM account")

        # Aktive KI-Nutzer (haben in dem Zeitfenster KI verwendet).
        aktiv_7d = await con.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM ai_nutzung WHERE erstellt >= now() - interval '7 days'")
        aktiv_30d = await con.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM ai_nutzung WHERE erstellt >= now() - interval '30 days'")

        # Aktive Abos je Tarif + MRR (nur laufende Abo-Perioden, kein PAYG).
        abo_rows = await con.fetch(
            """SELECT a.tarif_code AS code, t.name, t.preis_cents,
                      COUNT(*) AS anzahl
                 FROM account a
                 JOIN tarif t ON t.code = a.tarif_code
                WHERE a.tarif_code <> 'payg'
                  AND a.abo_bezahlt_bis IS NOT NULL
                  AND a.abo_bezahlt_bis >= CURRENT_DATE
             GROUP BY a.tarif_code, t.name, t.preis_cents, t.sortierung
             ORDER BY t.sortierung""")
        abos = [{"code": r["code"], "name": r["name"],
                 "anzahl": int(r["anzahl"]),
                 "preis_cents": int(r["preis_cents"] or 0),
                 "mrr_cents": int(r["anzahl"]) * int(r["preis_cents"] or 0)} for r in abo_rows]
        mrr_cents = sum(a["mrr_cents"] for a in abos)
        abos_gesamt = sum(a["anzahl"] for a in abos)

        # KI-Nutzungswert (marked-up cents = das, was den Nutzern abgeht/zählt).
        ki_30d = await con.fetchval(
            "SELECT COALESCE(SUM(kosten_cents),0) FROM ai_nutzung WHERE erstellt >= now() - interval '30 days'")
        ki_7d = await con.fetchval(
            "SELECT COALESCE(SUM(kosten_cents),0) FROM ai_nutzung WHERE erstellt >= now() - interval '7 days'")
        guthaben_summe = await con.fetchval("SELECT COALESCE(SUM(guthaben_cents),0) FROM account")

        # Top-Verbraucher (30 Tage) – für den Blick auf Ausreißer.
        top_rows = await con.fetch(
            """SELECT n.user_id, u.email::text AS email,
                      COALESCE(SUM(n.kosten_cents),0) AS kosten
                 FROM ai_nutzung n
                 LEFT JOIN app_user u ON u.id = n.user_id
                WHERE n.erstellt >= now() - interval '30 days'
             GROUP BY n.user_id, u.email
             ORDER BY kosten DESC
                LIMIT 5""")
        top_verbraucher = [{"user_id": r["user_id"], "email": r["email"],
                            "kosten_cents": float(r["kosten"])} for r in top_rows]

        # Nutzung je Funktion (zweck) – 30 Tage. kosten_cents = abgerechneter Wert (inkl.
        # Aufschlag = unser „Umsatz"/das vom Nutzer Bezahlte).
        funk_rows = await con.fetch(
            """SELECT zweck, COUNT(*) AS anzahl, COALESCE(SUM(kosten_cents),0) AS kosten
                 FROM ai_nutzung
                WHERE erstellt >= now() - interval '30 days'
             GROUP BY zweck
             ORDER BY kosten DESC""")
        nach_funktion = [{"zweck": r["zweck"] or "?", "anzahl": int(r["anzahl"]),
                          "kosten_cents": float(r["kosten"])} for r in funk_rows]

    return {
        "nach_funktion": nach_funktion,
        "nutzer_gesamt": int(nutzer_gesamt or 0),
        "nutzer_aktiv": int(nutzer_aktiv or 0),
        "neu_7d": int(neu_7d or 0),
        "neu_30d": int(neu_30d or 0),
        "haushalte": int(haushalte or 0),
        "aktiv_ki_7d": int(aktiv_7d or 0),
        "aktiv_ki_30d": int(aktiv_30d or 0),
        "abos": abos,
        "abos_gesamt": abos_gesamt,
        "mrr_cents": mrr_cents,
        "ki_nutzung_7d_cents": float(ki_7d or 0),
        "ki_nutzung_30d_cents": float(ki_30d or 0),
        "guthaben_summe_cents": float(guthaben_summe or 0),
        "top_verbraucher": top_verbraucher,
    }
