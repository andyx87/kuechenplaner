"""Backoffice-Kennzahlen (Admin-Dashboard).

Aggregiert kontoübergreifend (bypass=True, da RLS sonst nur das eigene Konto zeigt):
Nutzer, Haushalte, Aktivität, Rezepte, offene Bugreports. Bewusst lesend und
fehlertolerant – das Dashboard darf nie einen 500 werfen.
"""
from __future__ import annotations

import logging

from .db import acquire

log = logging.getLogger("koch")


async def _zahl(con, sql: str) -> int:
    try:
        return int(await con.fetchval(sql) or 0)
    except Exception as e:  # z. B. fehlende Spalte in einer alten Datenbank
        log.warning("Kennzahl übersprungen (%s): %s", sql[:60], e)
        return 0


async def kennzahlen() -> dict:
    """Liefert die KPI-Übersicht fürs Admin-Dashboard."""
    async with acquire(bypass=True) as con:
        return {
            "nutzer_gesamt": await _zahl(con, "SELECT COUNT(*) FROM app_user"),
            "nutzer_aktiv": await _zahl(con, "SELECT COUNT(*) FROM app_user WHERE aktiv"),
            "neu_7d": await _zahl(
                con, "SELECT COUNT(*) FROM app_user WHERE created_at >= now() - interval '7 days'"),
            "neu_30d": await _zahl(
                con, "SELECT COUNT(*) FROM app_user WHERE created_at >= now() - interval '30 days'"),
            "haushalte": await _zahl(con, "SELECT COUNT(*) FROM account"),
            # Aktive Haushalte = Login/Nutzung im Zeitfenster (account.zuletzt_aktiv).
            "aktiv_7d": await _zahl(
                con, "SELECT COUNT(*) FROM account WHERE zuletzt_aktiv >= now() - interval '7 days'"),
            "aktiv_30d": await _zahl(
                con, "SELECT COUNT(*) FROM account WHERE zuletzt_aktiv >= now() - interval '30 days'"),
            "rezepte": await _zahl(con, "SELECT COUNT(*) FROM rezepte"),
            "rezepte_oeffentlich": await _zahl(con, "SELECT COUNT(*) FROM rezepte WHERE veroeffentlicht"),
            "bugreports_offen": await _zahl(con, "SELECT COUNT(*) FROM bugreport WHERE status = 'offen'"),
        }
