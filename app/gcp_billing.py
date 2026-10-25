"""Echte Google-Cloud-Projektkosten fürs Admin-Board.

Liest den Cloud-Billing-Export aus BigQuery (Dataset `billing_export`, Standard-
Export `gcp_billing_export_v1_*`) und aggregiert die Netto-Kosten (cost + credits)
des Projekts nach Monat / 30 Tagen / Service / Tag.

Bewusst komplett fehlertolerant: fehlt die Library, die Tabelle, die Berechtigung
oder ist der Export noch nicht aktiviert, liefert die Funktion `{"verfuegbar": False,
"hinweis": ...}` statt eines 500. So kann das Board schon existieren, bevor der
Export Daten liefert (Aktivierung in der Billing-Console, danach ~Stunden Verzug).
"""
from __future__ import annotations

import asyncio
import logging

from . import config

log = logging.getLogger("koch")

_PROJECT = getattr(config, "GCP_PROJECT", None) or None  # leer: Default-Projekt der ADC
_DATASET = getattr(config, "BQ_BILLING_DATASET", None) or "billing_export"
_TABLE_HINT = getattr(config, "BQ_BILLING_TABLE", None) or ""  # optional feste Tabelle
_LOCATION = getattr(config, "BQ_BILLING_LOCATION", None) or "EU"  # Dataset-Region (Query-Job)


def _abfrage() -> dict:
    """Synchron (läuft im Thread): BigQuery abfragen und Kosten aggregieren."""
    try:
        from google.cloud import bigquery  # type: ignore
    except Exception:  # noqa: BLE001
        return {"verfuegbar": False, "hinweis": "BigQuery-Client nicht installiert."}

    try:
        client = bigquery.Client(project=_PROJECT)
    except Exception as e:  # noqa: BLE001
        log.warning("gcp_billing: BQ-Client init fehlgeschlagen: %s", e)
        return {"verfuegbar": False, "hinweis": "BigQuery nicht erreichbar."}

    # Export-Tabelle finden (Standard-Export: gcp_billing_export_v1_<Konto>).
    table = _TABLE_HINT
    if not table:
        try:
            tabs = [t.table_id for t in client.list_tables(f"{_PROJECT}.{_DATASET}")]
        except Exception as e:  # noqa: BLE001
            log.info("gcp_billing: Dataset/Export noch nicht da: %s", e)
            return {"verfuegbar": False, "hinweis": "Billing-Export nach BigQuery ist noch nicht aktiviert (Dataset/Tabelle fehlt)."}
        cand = [t for t in tabs if t.startswith("gcp_billing_export_v1_")] \
            or [t for t in tabs if t.startswith("gcp_billing_export_")]
        if not cand:
            return {"verfuegbar": False, "hinweis": "Billing-Export ist eingerichtet, aber es sind noch keine Kostendaten eingelaufen (kann einige Stunden dauern)."}
        table = cand[0]

    full = f"`{_PROJECT}.{_DATASET}.{table}`"
    # Netto = cost + Summe der (negativen) credits. Nur dieses Projekt.
    netto = "cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)"
    where = "project.id = @proj AND usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 35 DAY)"
    params = [bigquery.ScalarQueryParameter("proj", "STRING", _PROJECT)]
    cfg = bigquery.QueryJobConfig(query_parameters=params)

    def q(sql: str):
        return list(client.query(sql, job_config=cfg, location=_LOCATION).result())

    try:
        # Summen: aktueller Kalendermonat + rollierende 30 Tage + Währung + Stand.
        gesamt = q(f"""
            SELECT
              SUM(IF(invoice.month = FORMAT_TIMESTAMP('%Y%m', CURRENT_TIMESTAMP()), {netto}, 0)) AS monat,
              SUM(IF(usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY), {netto}, 0)) AS d30,
              SUM(IF(usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY), {netto}, 0)) AS d7,
              ANY_VALUE(currency) AS currency,
              MAX(export_time) AS stand
            FROM {full}
            WHERE {where}""")
        nach_service = q(f"""
            SELECT service.description AS service, SUM({netto}) AS kosten
            FROM {full}
            WHERE {where} AND usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
            GROUP BY service HAVING kosten <> 0 ORDER BY kosten DESC LIMIT 20""")
        nach_tag = q(f"""
            SELECT FORMAT_TIMESTAMP('%Y-%m-%d', usage_start_time) AS tag, SUM({netto}) AS kosten
            FROM {full}
            WHERE {where} AND usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
            GROUP BY tag ORDER BY tag""")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Permission" in msg or "denied" in msg or "Access Denied" in msg:
            return {"verfuegbar": False, "hinweis": "Dem Dienst-Konto fehlen BigQuery-Leserechte (bigquery.dataViewer/jobUser)."}
        log.warning("gcp_billing: Abfrage fehlgeschlagen: %s", e)
        return {"verfuegbar": False, "hinweis": "Abfrage der Kostendaten fehlgeschlagen."}

    g = gesamt[0] if gesamt else None
    eur = lambda v: round(float(v or 0), 2)  # noqa: E731
    stand = None
    try:
        stand = g["stand"].isoformat() if g and g["stand"] else None
    except Exception:  # noqa: BLE001
        stand = None
    return {
        "verfuegbar": True,
        "waehrung": (g["currency"] if g and g["currency"] else "EUR"),
        "monat_eur": eur(g["monat"]) if g else 0.0,
        "dreissig_tage_eur": eur(g["d30"]) if g else 0.0,
        "sieben_tage_eur": eur(g["d7"]) if g else 0.0,
        "stand": stand,
        "nach_service": [{"service": r["service"] or "?", "eur": eur(r["kosten"])} for r in nach_service],
        "nach_tag": [{"tag": r["tag"], "eur": eur(r["kosten"])} for r in nach_tag],
    }


async def cloud_kosten() -> dict:
    """Async-Wrapper: BigQuery-Abfrage im Thread, damit der Event-Loop frei bleibt."""
    try:
        return await asyncio.to_thread(_abfrage)
    except Exception as e:  # noqa: BLE001
        log.warning("gcp_billing: unerwartet: %s", e)
        return {"verfuegbar": False, "hinweis": "Kostenmodul nicht verfügbar."}
