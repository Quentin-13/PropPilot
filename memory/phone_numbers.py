"""
Gestion du pool de numéros PropPilot.

- assign_available_phone_number : attribution atomique depuis pool phone_numbers
- get_assigned_number           : numéro actuel du client
- should_show_welcome           : premier login (welcome_seen_at IS NULL)
- mark_welcome_seen             : marque l'onboarding vu
- get_client_welcome_context    : contexte complet pour la page bienvenue
"""
from __future__ import annotations

import logging
from typing import Optional

from memory.database import get_connection

_log = logging.getLogger(__name__)

_CRM_LABELS: dict[str, str] = {
    "hektor":      "Hektor (La Boîte Immo)",
    "apimo":       "Apimo",
    "prospeneo":   "Prospeneo",
    "whise":       "Whise",
    "adaptimmo":   "Adaptimmo",
    "email":       "Email",
    "csv":         "Import CSV",
    "none":        "",
}


# ── Attribution de numéro ─────────────────────────────────────────────────────

def assign_available_phone_number(client_id: str) -> Optional[str]:
    """
    Attribue un numéro PropPilot disponible au client.

    - Idempotent : si le client a déjà un numéro, le retourne sans rien modifier.
    - Atomique   : CTE UPDATE…RETURNING protège contre les races.
    - Synchronise users.twilio_sms_number pour que les webhooks Twilio fonctionnent.

    Retourne le numéro ou None si le pool est épuisé.
    """
    if not client_id:
        return None

    try:
        with get_connection() as conn:
            # Idempotent — numéro déjà assigné via phone_numbers
            existing = conn.execute(
                "SELECT phone_number FROM phone_numbers WHERE client_id = %s LIMIT 1",
                (client_id,),
            ).fetchone()
            if existing:
                return existing["phone_number"]

            # Idempotent — numéro déjà assigné directement sur users
            user_row = conn.execute(
                "SELECT twilio_sms_number FROM users WHERE id = %s LIMIT 1",
                (client_id,),
            ).fetchone()
            if user_row and user_row["twilio_sms_number"]:
                return user_row["twilio_sms_number"]

            # Attribution atomique du premier numéro disponible
            result = conn.execute(
                """
                WITH chosen AS (
                    SELECT id, phone_number
                    FROM phone_numbers
                    WHERE status = 'available'
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE phone_numbers
                    SET status      = 'assigned',
                        client_id   = %s,
                        assigned_at = NOW(),
                        updated_at  = NOW()
                FROM chosen
                WHERE phone_numbers.id = chosen.id
                RETURNING phone_numbers.phone_number
                """,
                (client_id,),
            ).fetchone()

            if not result:
                _log.warning("[PhonePool] Pool épuisé — aucun numéro disponible pour client %s", client_id)
                return None

            number = result["phone_number"]

            # Synchronise users.twilio_sms_number (routing webhooks Twilio)
            conn.execute(
                "UPDATE users SET twilio_sms_number = %s WHERE id = %s AND twilio_sms_number IS NULL",
                (number, client_id),
            )
            return number

    except Exception as exc:
        _log.error("[PhonePool] assign_available_phone_number erreur pour %s: %s", client_id, exc)
        return None


def get_assigned_number(client_id: str) -> Optional[str]:
    """Retourne le numéro PropPilot du client, ou None si aucun assigné."""
    if not client_id:
        return None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT twilio_sms_number FROM users WHERE id = %s LIMIT 1",
                (client_id,),
            ).fetchone()
        return (row["twilio_sms_number"] or None) if row else None
    except Exception as exc:
        _log.error("[PhonePool] get_assigned_number erreur: %s", exc)
        return None


# ── Onboarding / premier login ────────────────────────────────────────────────

def should_show_welcome(client_id: str) -> bool:
    """True si le client n'a pas encore vu la page bienvenue."""
    if not client_id:
        return False
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT welcome_seen_at FROM users WHERE id = %s LIMIT 1",
                (client_id,),
            ).fetchone()
        if not row:
            return False
        return row["welcome_seen_at"] is None
    except Exception as exc:
        _log.error("[Welcome] should_show_welcome erreur: %s", exc)
        return False


def mark_welcome_seen(client_id: str) -> None:
    """Marque la page bienvenue comme vue pour ce client."""
    if not client_id:
        return
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET welcome_seen_at = NOW() WHERE id = %s",
                (client_id,),
            )
    except Exception as exc:
        _log.error("[Welcome] mark_welcome_seen erreur: %s", exc)


# ── Contexte page bienvenue ───────────────────────────────────────────────────

def get_client_welcome_context(client_id: str) -> dict:
    """
    Retourne le contexte nécessaire à la page bienvenue :
    phone_number, crm_type, crm_label, crm_status, crm_last_sync_at.
    """
    ctx = {
        "phone_number": None,
        "crm_type": "none",
        "crm_label": "",
        "crm_status": "none",   # "none" | "configured" | "active" | "error"
        "crm_last_sync_at": None,
    }
    if not client_id:
        return ctx

    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT twilio_sms_number, crm_type, crm_last_sync_at, crm_last_error
                FROM users WHERE id = %s LIMIT 1
                """,
                (client_id,),
            ).fetchone()
    except Exception as exc:
        _log.error("[Welcome] get_client_welcome_context erreur: %s", exc)
        return ctx

    if not row:
        return ctx

    ctx["phone_number"] = row["twilio_sms_number"] or None
    crm_type = row["crm_type"] or "none"
    ctx["crm_type"] = crm_type
    ctx["crm_label"] = _CRM_LABELS.get(crm_type, crm_type)
    ctx["crm_last_sync_at"] = row.get("crm_last_sync_at")

    if crm_type == "none":
        ctx["crm_status"] = "none"
    elif row.get("crm_last_error"):
        ctx["crm_status"] = "error"
    elif row.get("crm_last_sync_at"):
        ctx["crm_status"] = "active"
    else:
        ctx["crm_status"] = "configured"

    return ctx
