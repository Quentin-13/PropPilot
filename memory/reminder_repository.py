"""
CRUD reminders — tâches planifiées créées par l'agent Marc.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from memory.database import get_connection

logger = logging.getLogger(__name__)


def get_reminders_by_client(
    client_id: str,
    include_done: bool = False,
) -> list[dict]:
    """
    Retourne les reminders d'un client avec le nom du lead associé.
    Par défaut n'inclut pas les reminders 'done' ni 'sent'.
    """
    conditions = ["r.client_id = %s"]
    params: list = [client_id]

    if not include_done:
        conditions.append("r.status IN ('pending', 'snoozed')")

    where = " AND ".join(conditions)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT r.id, r.lead_id, r.client_id, r.type, r.canal,
                   r.message, r.sujet, r.scheduled_at, r.sent_at,
                   r.status, r.metadata, r.created_at,
                   l.prenom, l.nom, l.telephone
            FROM reminders r
            LEFT JOIN leads l ON l.id = r.lead_id
            WHERE {where}
            ORDER BY r.scheduled_at ASC
            """,
            params,
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        val = d.get("metadata")
        if isinstance(val, str):
            try:
                d["metadata"] = json.loads(val)
            except Exception:
                d["metadata"] = {}
        elif val is None:
            d["metadata"] = {}
        result.append(d)
    return result


def mark_reminder_done(reminder_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE reminders SET status = 'done', sent_at = NOW() WHERE id = %s",
            (reminder_id,),
        )
    logger.info("[ReminderRepo] Marked done: %s", reminder_id)


def snooze_reminder(reminder_id: str, new_scheduled_at: datetime) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE reminders SET scheduled_at = %s, status = 'pending' WHERE id = %s",
            (new_scheduled_at, reminder_id),
        )
    logger.info("[ReminderRepo] Snoozed %s → %s", reminder_id, new_scheduled_at)
