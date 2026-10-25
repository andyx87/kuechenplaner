"""Audit-Log für sicherheitsrelevante Admin-Aktionen (B-5).

Keine neue Tabelle/DDL: jede Admin-Mutation erzeugt genau EIN strukturiertes
JSON-Log-Event über den bestehenden Log-Stream (stdout -> Cloud Logging).
Eine persistente Anzeige/Historie in der App selbst würde eine neue Tabelle
brauchen und ist bewusst nicht vorgesehen – die Auswertung läuft über Cloud Logging (Filter: jsonPayload.aktion
bzw. logName mit "audit").
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("audit")


def log_admin_action(ctx: dict, aktion: str, target: str, alt=None, neu=None) -> None:
    """Schreibt ein strukturiertes JSON-Event für eine Admin-Mutation.
    ctx ist der Auth-Kontext (user_id/account_id) des ausführenden Admins.
    Niemals Secrets/Tokens/Passwörter in alt/neu übergeben."""
    event = {
        "zeit": datetime.now(timezone.utc).isoformat(),
        "actor_user_id": (ctx or {}).get("user_id"),
        "actor_account_id": (ctx or {}).get("account_id"),
        "aktion": aktion,
        "target": target,
        "alt": alt,
        "neu": neu,
    }
    log.info(json.dumps(event, ensure_ascii=False, default=str))
