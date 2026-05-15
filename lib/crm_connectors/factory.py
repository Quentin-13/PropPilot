"""
Factory CRM push — sélectionne le connecteur selon la config client.

Usage principal :
    push_lead_to_crm(client_id, lead_data)   # dans extract_and_update_lead()

Usage secondaire :
    get_connector(client_id)                  # pour le bouton "Tester" dans le dashboard
    get_push_stats_7d(client_id)              # pour l'affichage du statut dans le dashboard
    retry_failed_pushes()                     # appelé par le batch APScheduler
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from lib.crm_connectors.base import CRMConnector

logger = logging.getLogger(__name__)

_MAX_RETRY_ATTEMPTS = 3


# ─── API publique ─────────────────────────────────────────────────────────────

def push_lead_to_crm(client_id: str, lead_data: dict) -> None:
    """
    Pousse un lead vers le CRM configuré pour ce client.
    Non-bloquant : les erreurs sont loguées mais ne propagent pas.
    Sur échec : enqueue dans crm_push_queue pour retry.
    """
    try:
        connector, crm_type = _get_connector_and_type(client_id)
        if connector is None:
            return

        success = connector.push_lead(lead_data)
        lead_id = lead_data.get("id", "")
        _log_sync(client_id, lead_id, crm_type, success=success)

        if success:
            _update_crm_last_sync(client_id)
            _cancel_pending_queue(lead_id)   # évite double-envoi si retry en attente
        else:
            _update_crm_last_error(client_id, "push_lead() a retourné False")
            _enqueue_failed_push(client_id, lead_id, "push_lead() a retourné False")
    except Exception as e:
        logger.error("[CRM Factory] push_lead_to_crm client_id=%s: %s", client_id, e)
        try:
            _update_crm_last_error(client_id, str(e))
            _enqueue_failed_push(client_id, lead_data.get("id", ""), str(e))
        except Exception:
            pass


def get_connector(client_id: str) -> Optional[CRMConnector]:
    """Retourne le connecteur actif, ou None si crm_type='none'."""
    connector, _ = _get_connector_and_type(client_id)
    return connector


def get_push_stats_7d(client_id: str) -> dict:
    """
    Statistiques de push sur 7 jours pour l'affichage dashboard.
    Retourne {"total": int, "success": int, "error": int, "last_error": str, "last_sync": datetime}
    """
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM crm_sync_log
                   WHERE client_id = ?
                     AND sent_at >= NOW() - INTERVAL '7 days'
                   GROUP BY status""",
                (client_id,),
            ).fetchall()

        success = sum(r["cnt"] for r in rows if r["status"] == "success")
        error = sum(r["cnt"] for r in rows if r["status"] == "error")

        with get_connection() as conn:
            row = conn.execute(
                "SELECT crm_last_sync_at, crm_last_error FROM users WHERE id = ?",
                (client_id,),
            ).fetchone()
        last_sync = row["crm_last_sync_at"] if row else None
        last_error = row["crm_last_error"] if row else None

        return {
            "total": success + error,
            "success": success,
            "error": error,
            "last_sync": last_sync,
            "last_error": last_error,
        }
    except Exception as e:
        logger.warning("[CRM Factory] get_push_stats_7d: %s", e)
        return {"total": 0, "success": 0, "error": 0, "last_sync": None, "last_error": None}


def save_crm_push_config(client_id: str, crm_type: str, config: dict) -> None:
    """Enregistre la config CRM push sur la table users."""
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET crm_type = ?, crm_config = ?::jsonb WHERE id = ?",
                (crm_type, json.dumps(config, ensure_ascii=False), client_id),
            )
    except Exception as e:
        logger.error("[CRM Factory] save_crm_push_config: %s", e)
        raise


def build_lead_data_from_db(lead_id: str) -> Optional[dict]:
    """
    Assemble le dict lead_data complet depuis la DB (lead + dernière extraction + historique).
    Utilisé par push_lead_to_crm() et le bouton "Tester" dans le dashboard.
    Ne recalcule pas le score — lit les valeurs existantes telles quelles.
    """
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            lead_row = conn.execute(
                """SELECT l.id, l.client_id, l.prenom, l.nom, l.telephone, l.email,
                          l.projet, l.localisation, l.motivation, l.score, l.resume,
                          l.next_action_label, l.next_action_reason,
                          l.updated_at
                   FROM leads l WHERE l.id = ?""",
                (lead_id,),
            ).fetchone()
        if not lead_row:
            return None

        score = lead_row["score"] or 0
        score_label = "chaud" if score >= 18 else "tiede" if score >= 11 else "froid"
        statut_display = {"chaud": "chaud", "tiede": "tiède", "froid": "froid"}[score_label]
        client_id = lead_row["client_id"] or ""

        updated_at = lead_row.get("updated_at")
        if updated_at and hasattr(updated_at, "strftime"):
            updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M")
        else:
            updated_at_str = str(updated_at)[:16] if updated_at else ""

        data = {
            "id": lead_row["id"],
            "client_id": client_id,
            "prenom": lead_row["prenom"] or "",
            "nom": lead_row["nom"] or "",
            "telephone": lead_row["telephone"] or "",
            "email": lead_row["email"] or "",
            "type_projet": lead_row["projet"] or "",
            "zone": lead_row["localisation"] or "",
            "motivation": lead_row["motivation"] or "",
            "score": score,
            "score_label": score_label,
            "statut": statut_display,
            "resume": lead_row["resume"] or "",
            "updated_at": updated_at_str,
            "next_action_label": lead_row["next_action_label"] or "",
            "next_action_reason": lead_row["next_action_reason"] or "",
            # Champs extraction — valeurs par défaut
            "lead_type": "acheteur",
            "budget_min": None,
            "budget_max": None,
            "type_bien": "",
            "surface_min": None,
            "surface_max": None,
            "urgence": "",
            "objections": "",
            "financement_str": "",
        }

        # Complète avec la dernière extraction si disponible
        try:
            from memory.call_repository import get_latest_extraction_for_lead
            ext = get_latest_extraction_for_lead(lead_id)
            if ext:
                data["lead_type"] = ext.get("lead_type") or "acheteur"
                data["budget_min"] = ext.get("budget_min")
                data["budget_max"] = ext.get("budget_max")
                data["type_bien"] = ext.get("type_bien") or ""
                data["surface_min"] = ext.get("surface_min")
                data["surface_max"] = ext.get("surface_max")
                if ext.get("zone_geographique"):
                    data["zone"] = ext["zone_geographique"]
                if ext.get("motivation"):
                    data["motivation"] = ext["motivation"]
                if ext.get("resume_appel"):
                    data["resume"] = ext["resume_appel"]
                # Urgence depuis timing dict
                timing = ext.get("timing") or {}
                data["urgence"] = timing.get("urgence", "") if isinstance(timing, dict) else ""
                # Objections depuis points_attention
                pts = ext.get("points_attention") or []
                data["objections"] = ", ".join(pts) if pts else ""
                # Financement formaté
                data["financement_str"] = _format_financement(ext.get("financement"))
        except Exception:
            pass

        # Historique conversations consolidé (SMS + appels)
        try:
            from lib.consolidated_transcript import build_lead_conversation_transcript
            data["conversation_history"] = build_lead_conversation_transcript(lead_id, client_id)
        except Exception:
            data["conversation_history"] = ""

        return data
    except Exception as e:
        logger.error("[CRM Factory] build_lead_data_from_db lead_id=%s: %s", lead_id, e)
        return None


def retry_failed_pushes() -> None:
    """
    Rejoue les pushs CRM en échec (status='pending', attempts < MAX_RETRY_ATTEMPTS).
    Appelé par le batch APScheduler toutes les 10 minutes.
    Erreurs visibles admin/logs uniquement.
    """
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, client_id, lead_id, attempts
                   FROM crm_push_queue
                   WHERE status = 'pending' AND attempts < ?
                   ORDER BY created_at
                   LIMIT 50""",
                (_MAX_RETRY_ATTEMPTS,),
            ).fetchall()
    except Exception as e:
        logger.error("[CRM Retry] Lecture queue: %s", e)
        return

    if not rows:
        return

    logger.info("[CRM Retry] %d push(es) en attente", len(rows))

    for row in rows:
        queue_id = row["id"]
        client_id = row["client_id"]
        lead_id = row["lead_id"]
        attempts = row["attempts"]

        lead_data = build_lead_data_from_db(lead_id)
        if not lead_data:
            _mark_queue_permanent_error(queue_id, "lead introuvable")
            continue

        try:
            connector, crm_type = _get_connector_and_type(client_id)
            if connector is None:
                _mark_queue_permanent_error(queue_id, "pas de connecteur CRM configuré")
                continue

            success = connector.push_lead(lead_data)
            if success:
                _mark_queue_sent(queue_id)
                _log_sync(client_id, lead_id, crm_type, success=True)
                _update_crm_last_sync(client_id)
                logger.info("[CRM Retry] OK lead_id=%s (tentative %d)", lead_id, attempts + 1)
            else:
                new_attempts = attempts + 1
                error_msg = "push_lead() a retourné False"
                if new_attempts >= _MAX_RETRY_ATTEMPTS:
                    _mark_queue_permanent_error(queue_id, error_msg)
                    logger.warning(
                        "[CRM Retry] PERMANENT_ERROR lead_id=%s après %d tentatives",
                        lead_id, new_attempts,
                    )
                else:
                    _increment_queue_attempts(queue_id, error_msg)
        except Exception as e:
            new_attempts = attempts + 1
            error_msg = str(e)[:500]
            if new_attempts >= _MAX_RETRY_ATTEMPTS:
                _mark_queue_permanent_error(queue_id, error_msg)
            else:
                _increment_queue_attempts(queue_id, error_msg)
            logger.warning("[CRM Retry] Erreur lead_id=%s: %s", lead_id, e)


# ─── Internes ─────────────────────────────────────────────────────────────────

def _get_connector_and_type(client_id: str) -> tuple[Optional[CRMConnector], str]:
    """Lit la config CRM du client et instancie le bon connecteur."""
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT crm_type, crm_config, email FROM users WHERE id = ?",
                (client_id,),
            ).fetchone()
        if not row:
            return None, "none"

        crm_type = row["crm_type"] or "none"
        if crm_type == "none":
            return None, "none"

        raw_config = row["crm_config"]
        if isinstance(raw_config, str):
            config = json.loads(raw_config) if raw_config else {}
        else:
            config = raw_config or {}

        client_email = row["email"] or ""

        if crm_type == "apimo":
            from lib.crm_connectors.apimo import ApimoConnector
            return ApimoConnector(
                provider_id=config.get("provider_id", ""),
                api_token=config.get("api_token", ""),
            ), "apimo"

        if crm_type == "email":
            target_email = config.get("target_email", "")
            if not target_email:
                logger.warning("[CRM Factory] crm_type=email mais target_email vide — skip")
                return None, "email"
            return EmailParsingConnector(
                target_email=target_email,
                reply_to_email=client_email,
                crm_label=config.get("crm_label", "CRM"),
            ), "email"

        logger.warning("[CRM Factory] crm_type inconnu : %s", crm_type)
        return None, crm_type

    except Exception as e:
        logger.error("[CRM Factory] _get_connector_and_type client_id=%s: %s", client_id, e)
        return None, "none"


def _cancel_pending_queue(lead_id: str) -> None:
    """Annule les entrées pending de la queue pour ce lead après un push réussi."""
    if not lead_id:
        return
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """UPDATE crm_push_queue
                   SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE lead_id = ? AND status = 'pending'""",
                (lead_id,),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _cancel_pending_queue lead_id=%s: %s", lead_id, e)


def _log_sync(client_id: str, lead_id: str, connector_type: str, success: bool, error: str = "") -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO crm_sync_log (client_id, lead_id, connector_type, status, error)
                   VALUES (?, ?, ?, ?, ?)""",
                (client_id, lead_id, connector_type, "success" if success else "error", error or None),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _log_sync failed: %s", e)


def _update_crm_last_sync(client_id: str) -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET crm_last_sync_at = NOW(), crm_last_error = NULL WHERE id = ?",
                (client_id,),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _update_crm_last_sync: %s", e)


def _update_crm_last_error(client_id: str, error: str) -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET crm_last_error = ? WHERE id = ?",
                (error[:500], client_id),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _update_crm_last_error: %s", e)


def _enqueue_failed_push(client_id: str, lead_id: str, error: str) -> None:
    """Insère un lead en échec dans la queue retry."""
    if not lead_id:
        return
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            # Vérifie s'il existe déjà un pending pour ce lead
            existing = conn.execute(
                "SELECT id FROM crm_push_queue WHERE lead_id = ? AND status = 'pending' LIMIT 1",
                (lead_id,),
            ).fetchone()
            if existing:
                # Met à jour l'entrée existante plutôt qu'en créer une nouvelle
                conn.execute(
                    """UPDATE crm_push_queue
                       SET attempts = attempts + 1, last_error = ?,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (error[:500], existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO crm_push_queue
                       (client_id, lead_id, status, attempts, last_error)
                       VALUES (?, ?, 'pending', 1, ?)""",
                    (client_id, lead_id, error[:500]),
                )
    except Exception as e:
        logger.warning("[CRM Factory] _enqueue_failed_push lead_id=%s: %s", lead_id, e)


def _mark_queue_sent(queue_id: int) -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """UPDATE crm_push_queue
                   SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (queue_id,),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _mark_queue_sent id=%s: %s", queue_id, e)


def _mark_queue_permanent_error(queue_id: int, error: str) -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """UPDATE crm_push_queue
                   SET status = 'permanent_error', last_error = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (error[:500], queue_id),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _mark_queue_permanent_error id=%s: %s", queue_id, e)


def _increment_queue_attempts(queue_id: int, error: str) -> None:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                """UPDATE crm_push_queue
                   SET attempts = attempts + 1, last_error = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (error[:500], queue_id),
            )
    except Exception as e:
        logger.warning("[CRM Factory] _increment_queue_attempts id=%s: %s", queue_id, e)


def _format_financement(fin) -> str:
    if not fin:
        return ""
    if isinstance(fin, str):
        return fin.strip()
    if isinstance(fin, dict):
        parts = []
        if fin.get("type"):
            parts.append(fin["type"])
        if fin.get("apport"):
            parts.append(f"apport {fin['apport']}")
        if fin.get("banque"):
            parts.append(f"banque {fin['banque']}")
        remaining = {k: v for k, v in fin.items() if k not in ("type", "apport", "banque") and v}
        for k, v in remaining.items():
            parts.append(f"{k} {v}")
        return ", ".join(parts) if parts else ""
    return ""
