"""
Log des coûts API réels par action/client.
Usage INTERNE UNIQUEMENT — jamais exposé au dashboard client.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from memory.database import get_connection

# Coûts approximatifs par provider (en euros, mis à jour manuellement)
COST_PER_UNIT = {
    "anthropic": {
        "claude-sonnet-4-5": {
            "input_per_1k": 0.0028,    # €/1000 tokens input
            "output_per_1k": 0.0140,   # €/1000 tokens output
            "cache_read_per_1k": 0.00028,  # 90% réduction sur cache hit
        }
    },
    "openai": {
        "dall-e-3": {
            "standard_1024": 0.038,    # €/image 1024x1024
            "standard_1792": 0.076,    # €/image 1792x1024
        }
    },
    "twilio": {
        "sms_fr": 0.0085,              # €/SMS sortant France
        "whatsapp_session": 0.025,     # €/session WhatsApp
        "voice_minute": 0.013,         # €/minute appel France
    },
    "elevenlabs": {
        "per_1k_chars": 0.003,         # €/1000 caractères TTS
    },
    "retell": {
        "per_minute": 0.05,            # €/minute appel IA
    },
}


def calculate_anthropic_cost(
    tokens_input: int,
    tokens_output: int,
    model: str = "claude-sonnet-4-5",
    cache_hit: bool = False,
) -> float:
    """Calcule le coût Anthropic en euros."""
    rates = COST_PER_UNIT["anthropic"].get(model, COST_PER_UNIT["anthropic"]["claude-sonnet-4-5"])
    if cache_hit:
        input_cost = (tokens_input / 1000) * rates["cache_read_per_1k"]
    else:
        input_cost = (tokens_input / 1000) * rates["input_per_1k"]
    output_cost = (tokens_output / 1000) * rates["output_per_1k"]
    return round(input_cost + output_cost, 6)


def log_api_action(
    client_id: str,
    action_type: str,
    provider: str,
    model: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    cost_euros: Optional[float] = None,
    success: bool = True,
    mock_used: bool = False,
    metadata: Optional[dict] = None,
) -> None:
    """
    Enregistre une action API avec son coût réel.
    Cette table n'est visible que depuis le back-office admin.
    """
    # Calcul automatique du coût si non fourni
    if cost_euros is None and provider == "anthropic":
        cost_euros = calculate_anthropic_cost(tokens_input, tokens_output, model)
    elif cost_euros is None:
        cost_euros = 0.0

    metadata_json = json.dumps(metadata or {})

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO api_actions
               (client_id, action_type, provider, model, tokens_input, tokens_output,
                cost_euros, success, mock_used, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                client_id, action_type, provider, model,
                tokens_input, tokens_output, cost_euros,
                1 if success else 0,
                1 if mock_used else 0,
                metadata_json,
            ),
        )

        # Mise à jour du coût agrégé dans usage_tracking
        month = datetime.now().strftime("%Y-%m")
        conn.execute(
            """UPDATE usage_tracking
               SET api_cost_euros = api_cost_euros + ?
               WHERE client_id = ? AND month = ?""",
            (cost_euros, client_id, month),
        )


def get_cost_report_admin(month: Optional[str] = None, client_id: Optional[str] = None) -> dict:
    """
    Rapport complet des coûts pour l'admin.
    NE JAMAIS exposer au client.
    """
    month = month or datetime.now().strftime("%Y-%m")
    params = [month]
    filter_client = ""
    if client_id:
        filter_client = "AND client_id = ?"
        params.append(client_id)

    with get_connection() as conn:
        # Coûts par provider
        by_provider = conn.execute(
            f"""SELECT provider, SUM(cost_euros) as total_cost, COUNT(*) as nb_actions,
                       SUM(CASE WHEN mock_used=1 THEN 1 ELSE 0 END) as mocks
                FROM api_actions
                WHERE TO_CHAR(created_at, 'YYYY-MM') = ? {filter_client}
                GROUP BY provider""",
            params,
        ).fetchall()

        # Coûts par client
        by_client = conn.execute(
            f"""SELECT client_id, SUM(cost_euros) as total_cost, COUNT(*) as nb_actions
                FROM api_actions
                WHERE TO_CHAR(created_at, 'YYYY-MM') = ? {filter_client}
                GROUP BY client_id""",
            params,
        ).fetchall()

        # Revenus estimés (depuis usage_tracking)
        revenue_query = "SELECT client_id, tier FROM usage_tracking WHERE month = ?"
        if client_id:
            revenue_query += " AND client_id = ?"
        clients_revenue = conn.execute(
            revenue_query,
            [month] + ([client_id] if client_id else []),
        ).fetchall()

    from config.tier_limits import TIERS
    total_revenue = sum(
        TIERS.get(r["tier"], TIERS["Starter"]).prix_mensuel
        for r in clients_revenue
    )
    total_cost = sum(r["total_cost"] for r in by_provider)
    margin = total_revenue - total_cost

    return {
        "month": month,
        "total_revenue_eur": total_revenue,
        "total_api_cost_eur": round(total_cost, 2),
        "margin_eur": round(margin, 2),
        "margin_pct": round(margin / total_revenue * 100, 1) if total_revenue > 0 else 0,
        "by_provider": [dict(r) for r in by_provider],
        "by_client": [dict(r) for r in by_client],
    }
