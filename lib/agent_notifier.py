"""
Notification SMS agent sur réception d'un SMS prospect.

Envoi une alerte courte au téléphone personnel de l'agent quand un prospect
écrit via le numéro PropPilot de l'agence.

Anti-spam : max 1 notification par lead par COOLDOWN_SECONDS (10 min).
Cache en mémoire (process) — se réinitialise au redémarrage du serveur,
ce qui est acceptable pour un MVP (rare restart, intervalle 10 min).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 600  # 10 minutes entre deux notifications pour le même lead
_last_notif: dict[str, float] = {}  # lead_id → timestamp Unix


def notify_agent_sms(
    client_id: str,
    lead_id: str,
    lead_name: str,
    from_number: str,
    dashboard_url: str,
    next_action: Optional[str] = None,
) -> None:
    """
    Envoie une notification SMS à l'agent si :
      - users.phone est renseigné
      - users.sms_notif_enabled est True (défaut)
      - Twilio est disponible (account_sid + auth_token + from_number)
      - Le cooldown de 10 min n'est pas actif pour ce lead

    Ne lève jamais d'exception — toutes les erreurs sont loggées.
    """
    now = time.time()

    # Anti-spam : cooldown par lead_id
    if _last_notif.get(lead_id, 0) + _COOLDOWN_SECONDS > now:
        logger.info("[AgentNotifier] Cooldown actif lead_id=%s — notification ignorée", lead_id)
        return

    # Récupérer les préférences agent depuis la DB
    agent_phone: Optional[str] = None
    sms_notif_enabled: bool = True
    notif_from: Optional[str] = None

    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT phone, sms_notif_enabled, twilio_sms_number FROM users WHERE id = %s LIMIT 1",
                (client_id,),
            ).fetchone()
            if row:
                agent_phone = row.get("phone")
                raw_enabled = row.get("sms_notif_enabled")
                sms_notif_enabled = raw_enabled if raw_enabled is not None else True
                notif_from = row.get("twilio_sms_number")
    except Exception as exc:
        logger.warning("[AgentNotifier] DB lookup client_id=%s: %s", client_id, exc)
        return

    if not agent_phone:
        logger.info("[AgentNotifier] Agent SMS notification skipped: no agent phone configured")
        return

    if not sms_notif_enabled:
        logger.info(
            "[AgentNotifier] Agent SMS notification skipped: notifications disabled client_id=%s",
            client_id,
        )
        return

    # Vérifier que Twilio est configuré
    from_num: Optional[str] = None
    try:
        from config.settings import get_settings
        s = get_settings()
        if not (s.twilio_account_sid and s.twilio_auth_token):
            logger.info("[AgentNotifier] Agent SMS notification skipped: no Twilio sender configured")
            return
        from_num = notif_from or s.twilio_sms_number
        if not from_num:
            logger.info("[AgentNotifier] Agent SMS notification skipped: no Twilio sender configured")
            return
    except Exception as exc:
        logger.warning("[AgentNotifier] Settings: %s", exc)
        return

    # Composer le message
    display_name = lead_name or from_number
    link = (
        f"{dashboard_url.rstrip('/')}/sms?lead_id={lead_id}"
        if lead_id
        else dashboard_url
    )
    lines = [
        "Nouveau SMS prospect reçu sur PropPilot.",
        f"Lead : {display_name}",
    ]
    if next_action:
        lines.append(f"Action : {next_action}")
    lines.append(f"Répondez depuis PropPilot : {link}")
    body = "\n".join(lines)

    # Envoi via Twilio
    try:
        from tools.twilio_tool import TwilioTool
        result = TwilioTool().send_sms(to=agent_phone, body=body, from_number=from_num)
        if result.get("success"):
            _last_notif[lead_id] = now
            logger.info(
                "[AgentNotifier] Notification envoyée → %s (lead_id=%s)",
                agent_phone,
                lead_id,
            )
        else:
            logger.warning("[AgentNotifier] Échec envoi: %s", result.get("error"))
    except Exception as exc:
        logger.error("[AgentNotifier] Exception envoi lead_id=%s: %s", lead_id, exc)
