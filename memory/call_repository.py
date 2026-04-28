"""
CRUD pour les tables calls et call_extractions.
Garantit l'idempotence sur call_sid (un même CallSid ne crée pas de doublon).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from memory.database import get_connection

logger = logging.getLogger(__name__)


# ── calls ─────────────────────────────────────────────────────────────────────

def create_call(
    *,
    call_sid: str,
    direction: str,
    mode: str,
    from_number: str,
    to_number: str,
    twilio_number: str,
    lead_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agency_id: Optional[str] = None,
    client_id: str = "",
    started_at: Optional[datetime] = None,
) -> Optional[str]:
    """
    Crée un call en DB.
    Si call_sid existe déjà, retourne l'id existant (idempotent).
    Retourne l'id du call créé ou existant.
    """
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM calls WHERE call_sid = %s",
            (call_sid,),
        ).fetchone()
        if existing:
            logger.info("[CallRepo] call_sid=%s already exists — skipping", call_sid)
            return existing["id"]

        call_id = str(uuid.uuid4())
        now = datetime.utcnow()
        conn.execute(
            """
            INSERT INTO calls (
                id, call_sid, direction, mode,
                from_number, to_number, twilio_number,
                lead_id, agent_id, agency_id, client_id,
                started_at, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, 'initiated', %s, %s
            )
            """,
            (
                call_id, call_sid, direction, mode,
                from_number, to_number, twilio_number,
                lead_id, agent_id, agency_id, client_id,
                started_at or now, now, now,
            ),
        )
        logger.info("[CallRepo] Created call id=%s call_sid=%s", call_id, call_sid)
        return call_id


def update_call_status(call_id: str, status: str, **kwargs) -> None:
    """
    Met à jour le statut d'un call et tout champ optionnel fourni en kwargs.
    kwargs acceptés : answered_at, ended_at, duration_seconds, recording_url,
                      recording_duration, transcript_text, transcript_segments,
                      cost_twilio, cost_whisper, cost_claude
    """
    allowed = {
        "answered_at", "ended_at", "duration_seconds",
        "recording_url", "recording_duration",
        "transcript_text", "transcript_segments",
        "cost_twilio", "cost_whisper", "cost_claude",
    }
    sets = ["status = %s", "updated_at = %s"]
    values = [status, datetime.utcnow()]

    for k, v in kwargs.items():
        if k not in allowed:
            logger.warning("[CallRepo] Unknown column %s — ignored", k)
            continue
        sets.append(f"{k} = %s")
        # JSONB fields need to be serialized to string
        if k == "transcript_segments" and isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)
        values.append(v)

    values.append(call_id)
    sql = f"UPDATE calls SET {', '.join(sets)} WHERE id = %s"

    with get_connection() as conn:
        conn.execute(sql, values)


def get_call_by_sid(call_sid: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM calls WHERE call_sid = %s",
            (call_sid,),
        ).fetchone()
        return dict(row) if row else None


def get_call_by_id(call_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM calls WHERE id = %s",
            (call_id,),
        ).fetchone()
        return dict(row) if row else None


# ── call_extractions ──────────────────────────────────────────────────────────

def save_call_extraction(call_id: str, data) -> int:
    """
    Sauvegarde une CallExtractionData en DB.
    data est un CallExtractionData depuis lib/call_extraction_pipeline.

    Retourne l'id SERIAL de l'extraction créée.
    """
    from lib.call_extraction_pipeline import CallExtractionData

    assert isinstance(data, CallExtractionData)

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO call_extractions (
                call_id, lead_id,
                type_projet, budget_min, budget_max, zone_geographique,
                type_bien, surface_min, surface_max,
                criteres, timing, financement,
                motivation, score_qualification,
                prochaine_action_suggeree, resume_appel, points_attention,
                extraction_model, extraction_prompt_version,
                extracted_at
            ) VALUES (
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                NOW()
            ) RETURNING id
            """,
            (
                call_id, None,
                data.type_projet, data.budget_min, data.budget_max, data.zone_geographique,
                data.type_bien, data.surface_min, data.surface_max,
                json.dumps(data.criteres, ensure_ascii=False),
                json.dumps(data.timing, ensure_ascii=False),
                json.dumps(data.financement, ensure_ascii=False),
                data.motivation, data.score_qualification,
                data.prochaine_action_suggeree, data.resume_appel,
                json.dumps(data.points_attention, ensure_ascii=False),
                data.extraction_model, data.extraction_prompt_version,
            ),
        )
        extraction_id = row.fetchone()["id"]
        logger.info("[CallRepo] Extraction saved id=%d call_id=%s", extraction_id, call_id)
        return extraction_id


def get_extraction_by_call(call_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM call_extractions WHERE call_id = %s ORDER BY extracted_at DESC LIMIT 1",
            (call_id,),
        ).fetchone()
        return dict(row) if row else None


# ── agency_phone_numbers ──────────────────────────────────────────────────────

def get_phone_number_config(twilio_number: str) -> Optional[dict]:
    """Retourne la config agence/agent associée à un numéro Twilio."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agency_phone_numbers WHERE twilio_number = %s AND active = TRUE",
            (twilio_number,),
        ).fetchone()
        return dict(row) if row else None


def upsert_phone_number(
    twilio_number: str,
    agency_id: str,
    agent_id: Optional[str] = None,
    agent_phone: Optional[str] = None,
    label: str = "",
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agency_phone_numbers (twilio_number, agency_id, agent_id, agent_phone, label)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (twilio_number) DO UPDATE SET
                agency_id = EXCLUDED.agency_id,
                agent_id = EXCLUDED.agent_id,
                agent_phone = EXCLUDED.agent_phone,
                label = EXCLUDED.label,
                active = TRUE
            """,
            (twilio_number, agency_id, agent_id, agent_phone, label),
        )
