"""
SMS Partner Tool — Envoi et réception de SMS
via l'API SMS Partner (smspartner.fr).
Remplace smsmode pour les SMS bidirectionnels.
"""
from __future__ import annotations

import logging

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

SMS_PARTNER_BASE_URL = "https://api.smspartner.fr/v1"


class SmsPartnerTool:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key = self.settings.smspartner_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def format_french_number(self, phone: str) -> str:
        """Normalise un numéro français au format international +33XXXXXXXXX."""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("0") and len(phone) == 10:
            return "+33" + phone[1:]
        if phone.startswith("+33"):
            return phone
        if phone.startswith("33") and len(phone) == 11:
            return "+" + phone
        return phone

    async def send_sms(
        self,
        to: str,
        body: str,
        sender: str = "PropPilot",
    ) -> dict:
        """
        Envoie un SMS via SMS Partner.
        Retourne {"success": True/False, "message_id": str}
        """
        if not self.is_available():
            logger.info(f"[SMSPartner MOCK] → {to} : {body}")
            return {"success": True, "mock": True}

        payload = {
            "apiKey": self.api_key,
            "to": to,
            "message": body,
            "sender": sender[:11],
            "isStopSms": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{SMS_PARTNER_BASE_URL}/send",
                    json=payload,
                )
                data = response.json()

                if response.status_code == 200 and data.get("success"):
                    logger.info(f"[SMSPartner] SMS envoyé à {to}")
                    return {"success": True, "message_id": data.get("message_id", "")}
                else:
                    logger.error(f"[SMSPartner] Erreur : {data}")
                    return {"success": False, "error": str(data)}

        except Exception as e:
            logger.error(f"[SMSPartner] Exception : {e}")
            return {"success": False, "error": str(e)}

    async def send_sms_from_virtual_number(
        self,
        to: str,
        body: str,
        virtual_number: str,
    ) -> dict:
        """
        Envoie un SMS depuis un numéro virtuel dédié
        (numéro du client mandataire).
        """
        if not self.is_available():
            logger.info(f"[SMSPartner MOCK] {virtual_number} → {to} : {body}")
            return {"success": True, "mock": True}

        payload = {
            "apiKey": self.api_key,
            "to": to,
            "message": body,
            "sender": virtual_number,
            "isStopSms": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{SMS_PARTNER_BASE_URL}/send",
                    json=payload,
                )
                data = response.json()
                success = response.status_code == 200 and data.get("success")
                if success:
                    logger.info(f"[SMSPartner] SMS {virtual_number} → {to}")
                return {"success": success, "data": data}

        except Exception as e:
            logger.error(f"[SMSPartner] Exception : {e}")
            return {"success": False, "error": str(e)}
