"""
Transcript consolidé cross-canal d'un lead.

Combine SMS (table conversations) et transcriptions d'appels (table calls)
dans un ordre chronologique strict.

Format de sortie :
    [SMS IN  - 2026-05-05 14:32] Bonjour, je cherche une maison à Toulouse...
    [SMS OUT - 2026-05-06 10:45] Bonjour, voici une sélection de biens.
    [CALL    - 2026-05-06 10:15] (transcription complète Whisper)

Garantit l'isolation client_id — ne mélange jamais les données de clients distincts.
"""
from __future__ import annotations

import logging
from datetime import datetime

from memory.database import get_connection

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1)


def _to_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00").rstrip("+00:00"))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(v[:19])
        except ValueError:
            pass
    return _EPOCH


def _format_ts(v) -> str:
    dt = _to_dt(v)
    if dt == _EPOCH:
        return "?"
    return dt.strftime("%Y-%m-%d %H:%M")


def build_lead_conversation_transcript(lead_id: str, client_id: str) -> str:
    """
    Construit un transcript consolidé de tous les échanges d'un lead.

    Args:
        lead_id:   ID du lead
        client_id: ID client — isolation multi-tenant obligatoire

    Returns:
        Chaîne multi-lignes triée chronologiquement, ou "" si aucun échange.
    """
    events: list[tuple[datetime, str]] = []

    # ── 1. SMS depuis conversations ───────────────────────────────────────────
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT role, contenu, created_at
                FROM conversations
                WHERE lead_id = %s AND client_id = %s AND canal = 'sms'
                ORDER BY created_at ASC
                """,
                (lead_id, client_id),
            ).fetchall()

        for row in rows:
            dt = _to_dt(row["created_at"])
            ts = _format_ts(row["created_at"])
            role = row.get("role") or "user"
            direction = "IN " if role == "user" else "OUT"
            contenu = (row.get("contenu") or "").strip()
            events.append((dt, f"[SMS {direction} - {ts}] {contenu}"))

    except Exception as exc:
        logger.warning("[Transcript] SMS lead_id=%s client=%s: %s", lead_id, client_id, exc)

    # ── 2. Appels avec transcription ──────────────────────────────────────────
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT started_at, transcript_text
                FROM calls
                WHERE lead_id = %s AND client_id = %s
                  AND transcript_text IS NOT NULL AND transcript_text <> ''
                ORDER BY started_at ASC
                """,
                (lead_id, client_id),
            ).fetchall()

        for row in rows:
            dt = _to_dt(row["started_at"])
            ts = _format_ts(row["started_at"])
            text = (row.get("transcript_text") or "").strip()
            events.append((dt, f"[CALL    - {ts}] {text}"))

    except Exception as exc:
        logger.warning("[Transcript] Calls lead_id=%s client=%s: %s", lead_id, client_id, exc)

    # ── Tri chronologique ─────────────────────────────────────────────────────
    events.sort(key=lambda x: x[0])
    return "\n".join(line for _, line in events)
