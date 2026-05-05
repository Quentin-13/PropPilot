"""
CRUD pour les tables calls et conversation_extractions.
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

_SCORE_MAP = {"froid": 2, "tiede": 5, "chaud": 8}
_VALID_PROJET = {"achat", "vente", "location", "inconnu"}


def _apply_extraction_to_lead(lead_id: str, data, conn) -> None:
    """Met à jour leads.* depuis une CallExtractionData. Règles :
    - Ne jamais écraser par None/vide.
    - Ne jamais rétrograder le score.
    - Motivation : uniquement si leads.motivation est vide.
    Doit être appelée dans la même transaction que l'INSERT extraction.
    """
    if not lead_id:
        return
    row = conn.execute(
        "SELECT score, motivation FROM leads WHERE id = %s", (lead_id,)
    ).fetchone()
    if not row:
        return

    current_score = row["score"] or 0
    current_motivation = row["motivation"] or ""
    fields: dict = {}

    if data.score_qualification:
        new_score = _SCORE_MAP.get(data.score_qualification.lower(), 0)
        if new_score > current_score:
            fields["score"] = new_score

    if data.type_projet:
        proj = data.type_projet.lower()
        fields["projet"] = proj if proj in _VALID_PROJET else "inconnu"

    if data.zone_geographique:
        fields["localisation"] = data.zone_geographique

    if data.budget_max is not None:
        fields["budget"] = str(data.budget_max)

    if data.type_bien:
        fields["type_bien"] = data.type_bien

    if data.resume_appel:
        fields["resume"] = data.resume_appel

    if data.motivation and not current_motivation.strip():
        fields["motivation"] = data.motivation

    fields["last_extraction_at"] = datetime.utcnow()
    fields["updated_at"] = datetime.utcnow()

    cols = ", ".join(f"{k} = %s" for k in fields)
    conn.execute(f"UPDATE leads SET {cols} WHERE id = %s", [*fields.values(), lead_id])
    logger.info("[CallRepo] leads.* updated for lead_id=%s fields=%s", lead_id, list(fields))


def apply_extraction_to_lead(lead_id: str, extraction: dict) -> None:
    """Applique un dict d'extraction (issu de get_latest_extraction_for_lead)
    sur leads.*. Ouvre sa propre connexion — utilisé par le backfill.
    """
    from lib.call_extraction_pipeline import CallExtractionData

    data = CallExtractionData(
        score_qualification=extraction.get("score_qualification") or "froid",
        type_projet=extraction.get("type_projet"),
        zone_geographique=extraction.get("zone_geographique"),
        budget_max=extraction.get("budget_max"),
        type_bien=extraction.get("type_bien"),
        resume_appel=extraction.get("resume_appel"),
        motivation=extraction.get("motivation"),
    )
    with get_connection() as conn:
        _apply_extraction_to_lead(lead_id, data, conn)


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


# ── conversation_extractions ──────────────────────────────────────────────────

def save_call_extraction(call_id: str, data) -> int:
    """
    Sauvegarde une CallExtractionData en DB (source='call').
    data est un CallExtractionData depuis lib/call_extraction_pipeline.

    Retourne l'id SERIAL de l'extraction créée.
    """
    from lib.call_extraction_pipeline import CallExtractionData

    assert isinstance(data, CallExtractionData)

    # Résoudre lead_id depuis la table calls
    with get_connection() as conn:
        call_row = conn.execute(
            "SELECT lead_id FROM calls WHERE id = %s LIMIT 1", (call_id,)
        ).fetchone()
    lead_id = call_row["lead_id"] if call_row else None

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO conversation_extractions (
                source, call_id, lead_id,
                type_projet, budget_min, budget_max, zone_geographique,
                type_bien, surface_min, surface_max,
                criteres, timing, financement,
                motivation, score_qualification,
                prochaine_action_suggeree, resume_appel, points_attention,
                extraction_model, extraction_prompt_version,
                extracted_at
            ) VALUES (
                'call', %s, %s,
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
                call_id, lead_id,
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
        _apply_extraction_to_lead(lead_id, data, conn)
        logger.info("[CallRepo] Extraction saved id=%d call_id=%s", extraction_id, call_id)
        return extraction_id


def get_extraction_by_call(call_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM conversation_extractions "
            "WHERE call_id = %s AND source = 'call' ORDER BY extracted_at DESC LIMIT 1",
            (call_id,),
        ).fetchone()
        return dict(row) if row else None


# ── agency_phone_numbers ──────────────────────────────────────────────────────

def get_calls_by_client(
    client_id: str,
    since: Optional[datetime] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """
    Retourne les appels d'un client avec extraction et infos lead,
    triés par date décroissante.
    """
    conditions = ["c.agency_id = %s"]
    params: list = [client_id]

    if since:
        conditions.append("c.created_at >= %s")
        params.append(since)

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.id, c.call_sid, c.direction, c.mode,
                c.from_number, c.to_number, c.twilio_number,
                c.lead_id, c.status, c.statut,
                c.started_at, c.ended_at, c.duration_seconds,
                c.recording_url, c.transcript_text,
                c.transcript_segments, c.created_at,
                ce.score_qualification, ce.resume_appel,
                ce.points_attention, ce.type_projet,
                ce.budget_min, ce.budget_max, ce.zone_geographique,
                ce.type_bien, ce.surface_min, ce.surface_max,
                ce.prochaine_action_suggeree, ce.motivation,
                ce.criteres, ce.timing, ce.financement,
                l.prenom, l.nom, l.telephone AS lead_telephone
            FROM calls c
            LEFT JOIN conversation_extractions ce ON ce.call_id = c.id AND ce.source = 'call'
            LEFT JOIN leads l ON l.id = c.lead_id
            WHERE {where}
            ORDER BY c.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        for field in ("transcript_segments", "points_attention"):
            val = d.get(field)
            if isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except Exception:
                    d[field] = []
            elif val is None:
                d[field] = []
        for field in ("criteres", "timing", "financement"):
            val = d.get(field)
            if isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except Exception:
                    d[field] = {}
            elif val is None:
                d[field] = {}
        result.append(d)
    return result


def count_calls_by_client(client_id: str, since: Optional[datetime] = None) -> int:
    """Compte le nombre d'appels d'un client."""
    conditions = ["agency_id = %s"]
    params: list = [client_id]
    if since:
        conditions.append("created_at >= %s")
        params.append(since)
    where = " AND ".join(conditions)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM calls WHERE {where}",
            params,
        ).fetchone()
    return int(row["cnt"]) if row else 0


def get_calls_by_lead(lead_id: str) -> list[dict]:
    """Retourne les appels d'un lead avec extraction, triés par date décroissante."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.direction, c.mode, c.status, c.statut,
                   c.started_at, c.ended_at, c.duration_seconds,
                   c.recording_url, c.transcript_text, c.created_at,
                   ce.score_qualification, ce.resume_appel, ce.points_attention,
                   ce.type_projet, ce.budget_min, ce.budget_max,
                   ce.zone_geographique, ce.motivation, ce.prochaine_action_suggeree
            FROM calls c
            LEFT JOIN conversation_extractions ce ON ce.call_id = c.id AND ce.source = 'call'
            WHERE c.lead_id = %s
            ORDER BY c.created_at DESC
            """,
            (lead_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_extractions_by_lead(lead_id: str) -> list[dict]:
    """Retourne toutes les extractions d'appels pour un lead (source='call')."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversation_extractions
            WHERE lead_id = %s AND source = 'call'
            ORDER BY extracted_at DESC
            """,
            (lead_id,),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("criteres", "timing", "financement", "points_attention"):
            val = d.get(field)
            if isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except Exception:
                    d[field] = {} if field != "points_attention" else []
        result.append(d)
    return result


def get_latest_extraction_for_lead(lead_id: str) -> Optional[dict]:
    """Retourne la dernière extraction pour un lead, tous canaux confondus (call + sms)."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM conversation_extractions
            WHERE lead_id = %s
            ORDER BY extracted_at DESC
            LIMIT 1
            """,
            (lead_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for field in ("criteres", "timing", "financement", "points_attention"):
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except Exception:
                d[field] = {} if field != "points_attention" else []
    return d


def save_sms_extraction(lead_id: str, client_id: str, data) -> int:
    """
    Sauvegarde une extraction SMS en DB (source='sms').
    data est un CallExtractionData depuis lib/sms_extraction_pipeline.

    Retourne l'id SERIAL de l'extraction créée.
    """
    from lib.call_extraction_pipeline import CallExtractionData

    assert isinstance(data, CallExtractionData)

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO conversation_extractions (
                source, lead_id,
                type_projet, budget_min, budget_max, zone_geographique,
                type_bien, surface_min, surface_max,
                criteres, timing, financement,
                motivation, score_qualification,
                prochaine_action_suggeree, resume_appel, points_attention,
                extraction_model, extraction_prompt_version,
                extracted_at
            ) VALUES (
                'sms', %s,
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
                lead_id,
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
        _apply_extraction_to_lead(lead_id, data, conn)
        logger.info(
            "[CallRepo] SMS extraction saved id=%d lead_id=%s client=%s",
            extraction_id, lead_id, client_id,
        )
        return extraction_id


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
