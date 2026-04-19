"""
TwilioTool — SMS sortants + message vocal appels entrants.
1 numéro 06/07 unique gère voix entrante + SMS.
Mock automatique si TWILIO_ACCOUNT_SID absent.
"""
from __future__ import annotations

import logging
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class TwilioTool:
    """
    Wrapper Twilio avec fallback mock automatique.
    send_sms() : SMS sortants (Marc, Léa)
    generate_inbound_twiml() : message vocal appels entrants (VoiceInboundAgent)
    """

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self.mock_mode = not self.settings.twilio_available
        if self.mock_mode:
            logger.info("[Twilio] Mode mock activé — aucune clé API détectée")

    def _get_client(self):
        if self._client is None and not self.mock_mode:
            from twilio.rest import Client
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    def send_sms(self, to: str, body: str, from_number: Optional[str] = None) -> dict:
        """
        Envoie un SMS via le numéro 06/07.

        Args:
            to: Numéro destinataire (format E.164 : +33...)
            body: Corps du SMS (160 chars recommandé)
            from_number: Numéro expéditeur (défaut : TWILIO_SMS_NUMBER)

        Returns:
            {"success": bool, "sid": str, "mock": bool, "error": Optional[str]}
        """
        from_num = from_number or self.settings.twilio_sms_number

        if self.mock_mode or not from_num:
            logger.info(f"[MOCK Twilio SMS] {from_num} → {to}: {body[:60]}")
            return {
                "success": True,
                "sid": f"mock_sms_{_generate_id()}",
                "mock": True,
                "to": to,
                "body_preview": body[:50],
            }

        try:
            client = self._get_client()
            message = client.messages.create(
                body=body,
                from_=from_num,
                to=to,
            )
            logger.info(f"SMS envoyé : {message.sid} → {to}")
            return {
                "success": True,
                "sid": message.sid,
                "mock": False,
                "to": to,
                "status": message.status,
            }
        except Exception as e:
            logger.error(f"Erreur SMS Twilio : {e}")
            return {"success": False, "sid": "", "mock": False, "error": str(e)}

    def send_whatsapp(self, to: str, body: str) -> dict:
        """
        Envoie un message WhatsApp Business.

        Args:
            to: Numéro (format E.164)
            body: Message texte

        Returns:
            {"success": bool, "sid": str, "mock": bool}
        """
        wa_from = f"whatsapp:{self.settings.twilio_whatsapp_number}"
        wa_to = f"whatsapp:{to}"

        if self.mock_mode:
            logger.info(f"[MOCK WhatsApp] To: {to} | Body: {body[:50]}...")
            return {
                "success": True,
                "sid": f"mock_wa_{_generate_id()}",
                "mock": True,
                "to": to,
            }

        try:
            client = self._get_client()
            message = client.messages.create(
                body=body,
                from_=wa_from,
                to=wa_to,
            )
            return {"success": True, "sid": message.sid, "mock": False}
        except Exception as e:
            logger.error(f"Erreur WhatsApp Twilio : {e}")
            return {"success": False, "sid": "", "mock": False, "error": str(e)}

    def generate_inbound_twiml(
        self,
        agent_name: str = "votre conseiller",
        agency_name: str = "l'agence",
    ) -> str:
        """
        Génère le TwiML pour les appels entrants sur le 06/07.
        Sophie joue le message puis raccroche — un SMS de qualification
        est déclenché en background.
        """
        message = (
            f"Bonjour, vous avez bien joint {agency_name}. "
            f"{agent_name} n'est pas disponible en ce moment. "
            f"Ne raccrochez pas, vous allez recevoir un SMS "
            f"dans quelques instants pour la suite de votre demande. "
            f"À très vite !"
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'    <Say language="fr-FR" voice="Polly.Lea">{message}</Say>\n'
            "    <Pause length=\"1\"/>\n"
            "    <Hangup/>\n"
            "</Response>"
        )

    def validate_number(self, phone: str) -> bool:
        """Valide qu'un numéro est au format E.164."""
        import re
        pattern = r"^\+[1-9]\d{6,14}$"
        return bool(re.match(pattern, phone.replace(" ", "").replace("-", "")))

    def format_french_number(self, phone: str) -> str:
        """Convertit un numéro français en format E.164."""
        phone = phone.strip().replace(" ", "").replace("-", "").replace(".", "")
        if phone.startswith("0") and len(phone) == 10:
            return f"+33{phone[1:]}"
        if phone.startswith("33") and len(phone) == 11:
            return f"+{phone}"
        return phone


class EmailTool:
    """Outil email minimal — SendGrid ou SMTP avec mock."""

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.sendgrid_available

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> dict:
        if self.mock_mode:
            logger.info(f"[MOCK EMAIL] To: {to_email} | Subject: {subject}")
            return {"success": True, "mock": True, "to": to_email}

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            body_html = body_html or f"<p>{body_text.replace(chr(10), '<br>')}</p>"
            message = Mail(
                from_email=(self.settings.sendgrid_from_email, self.settings.sendgrid_from_name),
                to_emails=(to_email, to_name),
                subject=subject,
                plain_text_content=body_text,
                html_content=body_html,
            )
            sg = SendGridAPIClient(self.settings.sendgrid_api_key)
            response = sg.send(message)
            return {
                "success": response.status_code in (200, 201, 202),
                "status_code": response.status_code,
                "mock": False,
            }
        except Exception as e:
            logger.error(f"Erreur email : {e}")
            return {"success": False, "error": str(e)}


def _generate_id() -> str:
    """Génère un ID court pour les mocks."""
    import uuid
    return str(uuid.uuid4())[:8]
