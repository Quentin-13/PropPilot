"""
VonageTool — SMS bidirectionnel via Vonage API.
Mock automatique si VONAGE_API_KEY absent.
Remplace Twilio pour les SMS uniquement.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class VonageTool:
    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self.mock_mode = not self.settings.vonage_available
        if self.mock_mode:
            logger.info("[Vonage] Mode mock activé")

    def _get_client(self):
        if self._client is None and not self.mock_mode:
            import vonage
            self._client = vonage.Client(
                key=self.settings.vonage_api_key,
                secret=self.settings.vonage_api_secret,
            )
        return self._client

    def send_sms(self, to: str, body: str,
                 from_number: Optional[str] = None) -> dict:
        """
        Envoie un SMS via Vonage.

        Args:
            to: Numéro destinataire format E.164 (+33...)
            body: Corps du SMS
            from_number: Expéditeur (numéro ou texte ≤11 chars)

        Returns:
            {"success": bool, "message_id": str, "mock": bool}
        """
        from_num = (from_number
                    or self.settings.vonage_phone_number
                    or "PropPilot")
        to_clean = to.replace("+", "").replace(" ", "")

        if self.mock_mode:
            logger.info(
                f"[MOCK Vonage SMS] To: {to} | "
                f"From: {from_num} | Body: {body[:50]}..."
            )
            return {
                "success": True,
                "message_id": f"mock_vonage_{_gen_id()}",
                "mock": True,
                "to": to,
            }

        try:
            client = self._get_client()
            import vonage
            sms = vonage.Sms(client)
            response = sms.send_message({
                "from": from_num,
                "to": to_clean,
                "text": body,
                "type": "unicode",
            })
            msgs = response.get("messages", [])
            if msgs and msgs[0].get("status") == "0":
                msg_id = msgs[0].get("message-id", "")
                logger.info(f"SMS Vonage envoyé : {msg_id} → {to}")
                return {
                    "success": True,
                    "message_id": msg_id,
                    "mock": False,
                    "to": to,
                }
            else:
                err = (msgs[0].get("error-text", "Erreur inconnue")
                       if msgs else "Réponse vide")
                logger.error(f"Erreur Vonage SMS : {err}")
                return {"success": False, "error": err, "mock": False}
        except Exception as e:
            logger.error(f"Exception Vonage SMS : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def format_french_number(self, phone: str) -> str:
        """Convertit un numéro français en format E.164."""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("0") and len(phone) == 10:
            return f"+33{phone[1:]}"
        if phone.startswith("33") and len(phone) == 11:
            return f"+{phone}"
        return phone


def _gen_id() -> str:
    return str(uuid.uuid4())[:8]
