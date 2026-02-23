"""
Tracking usage temps réel par client/tier.
check_and_consume() DOIT être appelé avant chaque action coûteuse.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from config.tier_limits import ACTION_TO_FIELD, get_limit_for_action, get_upgrade_message
from memory.database import get_connection

# Mapping action → colonne SQLite dans usage_tracking
ACTION_TO_DB_COLUMN: dict[str, str] = {
    "lead": "leads_count",
    "voice_minute": "voice_minutes",
    "image": "images_count",
    "token": "tokens_used",
    "followup": "followups_count",
    "listing": "listings_count",
    "estimation": "estimations_count",
}


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _get_or_create_usage(conn, client_id: str, month: str, tier: str) -> dict:
    """Retourne l'enregistrement usage existant ou en crée un nouveau."""
    row = conn.execute(
        "SELECT * FROM usage_tracking WHERE client_id = ? AND month = ?",
        (client_id, month),
    ).fetchone()

    if row:
        return dict(row)

    conn.execute(
        """INSERT INTO usage_tracking (client_id, month, tier)
           VALUES (?, ?, ?)
           ON CONFLICT(client_id, month) DO NOTHING""",
        (client_id, month, tier),
    )
    row = conn.execute(
        "SELECT * FROM usage_tracking WHERE client_id = ? AND month = ?",
        (client_id, month),
    ).fetchone()
    return dict(row)


def check_and_consume(
    client_id: str,
    action: str,
    amount: float = 1.0,
    tier: str = "Starter",
) -> dict:
    """
    Vérifie la limite d'usage et consomme si autorisé.

    Args:
        client_id: Identifiant du client
        action: Type d'action (lead, voice_minute, image, token, followup, listing, estimation)
        amount: Quantité à consommer (défaut 1)
        tier: Tier du client

    Returns:
        {
            "allowed": bool,
            "message": str,
            "remaining": Optional[int],
            "current_usage": float,
            "limit": Optional[float],
            "upgrade_url": str
        }
    """
    month = _current_month()
    field = ACTION_TO_FIELD.get(action)
    limit = get_limit_for_action(tier, action)

    with get_connection() as conn:
        usage = _get_or_create_usage(conn, client_id, month, tier)

        if not field:
            return {
                "allowed": True,
                "message": "Action inconnue — pas de limite appliquée.",
                "remaining": None,
                "current_usage": 0,
                "limit": None,
                "upgrade_url": "",
            }

        db_col = ACTION_TO_DB_COLUMN.get(action, field)
        current = usage.get(db_col, 0) or 0

        # Illimité si limit is None (Elite sur certaines features)
        if limit is None:
            _increment_usage(conn, client_id, month, db_col, amount, tier)
            return {
                "allowed": True,
                "message": "Utilisation illimitée sur votre forfait.",
                "remaining": None,
                "current_usage": current + amount,
                "limit": None,
                "upgrade_url": "",
            }

        # Vérification limite
        if current + amount > limit:
            upgrade_msg = get_upgrade_message(tier, action)
            return {
                "allowed": False,
                "message": upgrade_msg,
                "remaining": max(0, int(limit - current)),
                "current_usage": current,
                "limit": limit,
                "upgrade_url": "https://proppilot.fr/upgrade",
            }

        # Consommation
        _increment_usage(conn, client_id, month, db_col, amount, tier)
        remaining = int(limit - (current + amount))

        # Messages d'alerte progressifs
        pct = (current + amount) / limit * 100
        if pct >= 95:
            msg = f"⚠️ Vous arriverez bientôt à votre limite — il vous reste {remaining} utilisation(s) ce mois."
        elif pct >= 80:
            msg = f"Vous approchez de votre limite — il vous reste {remaining} utilisation(s) ce mois."
        else:
            msg = f"OK — {remaining} utilisation(s) restante(s) ce mois."

        return {
            "allowed": True,
            "message": msg,
            "remaining": remaining,
            "current_usage": current + amount,
            "limit": limit,
            "upgrade_url": "https://proppilot.fr/upgrade",
        }


def _increment_usage(conn, client_id: str, month: str, field: str, amount: float, tier: str) -> None:
    """Incrémente un champ d'usage dans la base."""
    conn.execute(
        f"""UPDATE usage_tracking
            SET {field} = {field} + ?,
                updated_at = CURRENT_TIMESTAMP,
                tier = ?
            WHERE client_id = ? AND month = ?""",
        (amount, tier, client_id, month),
    )


def get_usage_summary(client_id: str, tier: str, month: Optional[str] = None) -> dict:
    """
    Retourne le résumé d'usage pour le dashboard client.
    JAMAIS de coûts API — uniquement métriques métier.
    """
    month = month or _current_month()

    with get_connection() as conn:
        usage = _get_or_create_usage(conn, client_id, month, tier)

    from config.tier_limits import TIERS, get_tier_limits
    limits = get_tier_limits(tier)

    def pct(current: float, limit: Optional[int]) -> float:
        if limit is None:
            return 0.0
        return min(100.0, current / limit * 100) if limit > 0 else 0.0

    return {
        "month": month,
        "tier": tier,
        "leads": {
            "used": usage.get("leads_count", 0),
            "limit": limits.leads_par_mois,
            "pct": pct(usage.get("leads_count", 0), limits.leads_par_mois),
            "label": "Leads qualifiés",
        },
        "voice": {
            "used": round(usage.get("voice_minutes", 0.0), 1),
            "limit": limits.minutes_voix_par_mois,
            "pct": pct(usage.get("voice_minutes", 0.0), limits.minutes_voix_par_mois),
            "label": "Minutes voix",
        },
        "images": {
            "used": usage.get("images_count", 0),
            "limit": limits.images_par_mois,
            "pct": pct(usage.get("images_count", 0), limits.images_par_mois),
            "label": "Images staging",
        },
        "followups": {
            "used": usage.get("followups_count", 0),
            "limit": limits.followups_sms_par_mois,
            "pct": pct(usage.get("followups_count", 0), limits.followups_sms_par_mois),
            "label": "Follow-ups SMS",
        },
        "listings": {
            "used": usage.get("listings_count", 0),
            "limit": limits.annonces_par_mois,
            "pct": pct(usage.get("listings_count", 0), limits.annonces_par_mois),
            "label": "Annonces générées",
        },
        "estimations": {
            "used": usage.get("estimations_count", 0),
            "limit": limits.estimations_par_mois,
            "pct": pct(usage.get("estimations_count", 0), limits.estimations_par_mois),
            "label": "Estimations",
        },
    }


def get_all_usage_admin(month: Optional[str] = None) -> list[dict]:
    """
    Retourne tous les usages avec coûts API pour le back-office admin.
    NE JAMAIS exposer cette fonction dans le dashboard client.
    """
    month = month or _current_month()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM usage_tracking WHERE month = ? ORDER BY api_cost_euros DESC",
            (month,),
        ).fetchall()
    return [dict(row) for row in rows]
