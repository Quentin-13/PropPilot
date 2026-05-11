"""
Factory CRM push — sélectionne le connecteur selon la config client.

Usage principal :
    push_lead_to_crm(client_id, lead_data)   # dans les pipelines d'extraction

Usage secondaire :
    get_connector(client_id)                  # pour le bouton "Tester" dans le dashboard
    get_push_stats_7d(client_id)              # pour l'affichage du statut dans le dashboard
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from lib.crm_connectors.base import CRMConnector

logger = logging.getLogger(__name__)


# ─── API publique ─────────────────────────────────────────────────────────────

def push_lead_to_crm(client_id: str, lead_data: dict) -> None:
    """
    Pousse un lead vers le CRM configuré pour ce client.
    Non-bloquant : les erreurs sont loguées mais ne propagent pas.
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
        else:
            _update_crm_last_error(client_id, "push_lead() a retourné False")
    except Exception as e:
        logger.error("[CRM Factory] push_lead_to_crm client_id=%s: %s", client_id, e)
        try:
            _update_crm_last_error(client_id, str(e))
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

        # Dernière erreur + dernière sync depuis users
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
    Construit le dict lead_data complet depuis la DB (lead + dernière extraction).
    Utilisé par le bouton "Tester" dans le dashboard.
    """
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            lead_row = conn.execute(
                """SELECT l.id, l.client_id, l.prenom, l.nom, l.telephone, l.email,
                          l.projet, l.localisation, l.motivation, l.score, l.resume,
                          l.next_action_label, l.next_action_reason
                   FROM leads l WHERE l.id = ?""",
                (lead_id,),
            ).fetchone()
        if not lead_row:
            return None

        score = lead_row["score"] or 0
        score_label = "chaud" if score >= 18 else "tiede" if score >= 11 else "froid"

        data = {
            "id": lead_row["id"],
            "client_id": lead_row["client_id"],
            "prenom": lead_row["prenom"] or "",
            "nom": lead_row["nom"] or "",
            "telephone": lead_row["telephone"] or "",
            "email": lead_row["email"] or "",
            "type_projet": lead_row["projet"] or "inconnu",
            "zone": lead_row["localisation"] or "",
            "motivation": lead_row["motivation"] or "",
            "score_label": score_label,
            "resume": lead_row["resume"] or "",
            "next_action_label": lead_row["next_action_label"],
            "next_action_reason": lead_row["next_action_reason"],
            "budget_min": None,
            "budget_max": None,
            "type_bien": None,
            "surface_min": None,
            "surface_max": None,
        }

        # Complète avec la dernière extraction si disponible
        try:
            from memory.call_repository import get_latest_extraction_for_lead
            ext = get_latest_extraction_for_lead(lead_id)
            if ext:
                data["budget_min"] = ext.get("budget_min")
                data["budget_max"] = ext.get("budget_max")
                data["type_bien"] = ext.get("type_bien")
                data["surface_min"] = ext.get("surface_min")
                data["surface_max"] = ext.get("surface_max")
                if ext.get("zone_geographique"):
                    data["zone"] = ext["zone_geographique"]
                if ext.get("motivation"):
                    data["motivation"] = ext["motivation"]
                if ext.get("resume_appel"):
                    data["resume"] = ext["resume_appel"]
        except Exception:
            pass

        return data
    except Exception as e:
        logger.error("[CRM Factory] build_lead_data_from_db lead_id=%s: %s", lead_id, e)
        return None


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
            from lib.crm_connectors.email_parsing import EmailParsingConnector
            return EmailParsingConnector(
                target_email=config.get("target_email", ""),
                reply_to_email=client_email,
                crm_label=config.get("crm_label", "CRM"),
            ), "email"

        logger.warning("[CRM Factory] crm_type inconnu : %s", crm_type)
        return None, crm_type

    except Exception as e:
        logger.error("[CRM Factory] _get_connector_and_type client_id=%s: %s", client_id, e)
        return None, "none"


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
