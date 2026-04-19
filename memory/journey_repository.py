"""
JourneyRepository — Traçabilité des étapes du lead dans le pipeline.
Chaque action agent est loguée dans lead_journey pour audit et monitoring.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from memory.database import get_connection

logger = logging.getLogger(__name__)


def log_action(
    lead_id: str,
    client_id: str,
    stage: str,
    action_done: str,
    action_result: str = "",
    next_action: str = "",
    next_action_at: Optional[datetime] = None,
    agent_name: str = "",
    metadata: Optional[dict] = None,
) -> None:
    """
    Insère une ligne dans lead_journey pour tracer une action agent.

    Args:
        lead_id: ID du lead concerné
        client_id: ID de l'agence
        stage: Étape du pipeline (qualification, routing, nurturing, rdv_proposal, voice_call)
        action_done: Action effectuée (new_lead_created, message_sent, lead_scored, ...)
        action_result: Résultat de l'action (succès, message envoyé, score, ...)
        next_action: Prochaine action prévue
        next_action_at: Date/heure de la prochaine action
        agent_name: Nom de l'agent responsable (lea, marc, hugo, thomas, julie, orchestrateur)
        metadata: Données supplémentaires (JSON)
    """
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO lead_journey
                   (lead_id, client_id, stage, action_done, action_result,
                    next_action, next_action_at, agent_name, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lead_id,
                    client_id,
                    stage,
                    action_done,
                    action_result,
                    next_action,
                    next_action_at,
                    agent_name,
                    meta_json,
                ),
            )
    except Exception as e:
        logger.warning(f"[JourneyRepository] Impossible de logger l'action : {e}")


def get_journey(lead_id: str) -> list[dict]:
    """
    Retourne toutes les étapes du pipeline pour un lead donné,
    triées par date croissante.

    Args:
        lead_id: ID du lead

    Returns:
        Liste de dicts avec toutes les colonnes de lead_journey
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, lead_id, client_id, stage, action_done, action_result,
                          next_action, next_action_at, agent_name, metadata, created_at
                   FROM lead_journey
                   WHERE lead_id = ?
                   ORDER BY created_at ASC""",
                (lead_id,),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except Exception:
                d["metadata"] = {}
            result.append(d)
        return result
    except Exception as e:
        logger.warning(f"[JourneyRepository] get_journey({lead_id}) : {e}")
        return []


def get_pending_actions(client_id: str) -> list[dict]:
    """
    Retourne les actions planifiées dont next_action_at <= maintenant.
    Utilisé par le scheduler pour déclencher les actions différées.

    Args:
        client_id: ID de l'agence

    Returns:
        Liste de dicts prêts à être traités
    """
    now = datetime.now()
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, lead_id, client_id, stage, action_done, action_result,
                          next_action, next_action_at, agent_name, metadata, created_at
                   FROM lead_journey
                   WHERE client_id = ?
                     AND next_action_at IS NOT NULL
                     AND next_action_at <= ?
                     AND next_action != ''
                   ORDER BY next_action_at ASC""",
                (client_id, now),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except Exception:
                d["metadata"] = {}
            result.append(d)
        return result
    except Exception as e:
        logger.warning(f"[JourneyRepository] get_pending_actions({client_id}) : {e}")
        return []
