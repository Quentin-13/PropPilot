"""
SmsmodeTool — SMS bidirectionnel via smsmode API (Time2Chat).
Mock automatique si SMSMODE_API_KEY absent.
Docs API : https://www.smsmode.com/api-sms/
"""
from __future__ import annotations
import logging
import uuid
import requests
from typing import Optional
from config.settings import get_settings

logger = logging.getLogger(__name__)

SMSMODE_SEND_URL = "https://api.smsmode.com/http/1.6/sendSMS.do"


class SmsmodeTool:
    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.smsmode_available
        if self.mock_mode:
            logger.info("[smsmode] Mode mock activé — SMSMODE_API_KEY absent")

    def send_sms(self, to: str, body: str,
                 sender: Optional[str] = None) -> dict:
        """
        Envoie un SMS via smsmode Time2Chat.
        Args:
            to: Numéro destinataire format E.164 (+33...)
            body: Corps du SMS
            sender: Expéditeur (numéro virtuel 09xx ou texte ≤11 chars)
        Returns:
            {"success": bool, "message_id": str, "mock": bool}
        """
        from_sender = (
            sender
            or self.settings.smsmode_phone_number
            or "PropPilot"
        )
        # smsmode attend le format 33XXXXXXXXX (sans +)
        to_clean = to.replace("+", "").replace(" ", "").replace("-", "")

        if self.mock_mode:
            logger.info(
                f"[MOCK smsmode] To: {to} | "
                f"Sender: {from_sender} | Body: {body[:60]}..."
            )
            return {
                "success": True,
                "message_id": f"mock_smsmode_{uuid.uuid4().hex[:8]}",
                "mock": True,
                "to": to,
            }

        try:
            params = {
                "accessToken": self.settings.smsmode_api_key,
                "message": body,
                "numero": to_clean,
                "emetteur": from_sender,
                "nbr_msg": 1,
            }
            resp = requests.get(
                SMSMODE_SEND_URL,
                params=params,
                timeout=10,
            )
            text = resp.text.strip()
            # smsmode retourne "0 | message_id" si succès
            if text.startswith("0"):
                parts = text.split("|")
                msg_id = parts[1].strip() if len(parts) > 1 else "ok"
                logger.info(f"[smsmode] SMS envoyé : {msg_id} → {to}")
                return {
                    "success": True,
                    "message_id": msg_id,
                    "mock": False,
                    "to": to,
                }
            else:
                logger.error(f"[smsmode] Erreur : {text}")
                return {"success": False, "error": text, "mock": False}
        except Exception as e:
            logger.error(f"[smsmode] Exception : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def format_french_number(self, phone: str) -> str:
        """Convertit un numéro français en format E.164."""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("0") and len(phone) == 10:
            return f"+33{phone[1:]}"
        if phone.startswith("33") and not phone.startswith("+"):
            return f"+{phone}"
        return phone
