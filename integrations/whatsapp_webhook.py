"""
Webhook WhatsApp Business — Réception messages WhatsApp via Twilio.
Twilio reçoit les messages WhatsApp et les redirige vers cet endpoint.

Configuration Twilio :
  - Sandbox WhatsApp : https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
  - Production : numéro WhatsApp Business approuvé
  - Webhook URL : https://votre-domaine.com/webhooks/whatsapp

Usage Flask :
    @app.route("/webhooks/whatsapp", methods=["POST"])
    def whatsapp_endpoint():
        result = handle_whatsapp_webhook(request.form.to_dict(), client_id="client_demo")
        return result["twiml"], 200, {"Content-Type": "text/xml"}

Usage FastAPI :
    @app.post("/webhooks/whatsapp")
    async def whatsapp_endpoint(request: Request):
        form = await request.form()
        result = handle_whatsapp_webhook(dict(form), client_id="client_demo")
        return Response(content=result["twiml"], media_type="text/xml")
"""
from __future__ import annotations

import logging
from typing import Optional

from config.settings import get_settings
from memory.lead_repository import get_lead_by_phone
from memory.models import Canal
from orchestrator import process_incoming_message

logger = logging.getLogger(__name__)


def parse_twilio_whatsapp_payload(form_data: dict) -> dict:
    """
    Parse le payload Twilio WhatsApp.

    Twilio envoie :
        From: whatsapp:+33611223344
        To: whatsapp:+14155238886
        Body: Bonjour, je cherche un appartement...
        ProfileName: Marie Dupont
        WaId: 33611223344
        NumMedia: 0
        MessageSid: SMxxx...
        AccountSid: ACxxx...
    """
    raw_from = form_data.get("From", "")
    telephone = raw_from.replace("whatsapp:", "").strip()

    body = form_data.get("Body", "").strip()
    profile_name = form_data.get("ProfileName", "")

    # Décomposer le nom de profil si disponible
    parts = profile_name.strip().split(" ", 1)
    prenom = parts[0] if parts else ""
    nom = parts[1] if len(parts) > 1 else ""

    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0", "") if num_media > 0 else ""

    return {
        "telephone": telephone,
        "message": body,
        "prenom": prenom,
        "nom": nom,
        "canal": Canal.WHATSAPP.value,
        "message_sid": form_data.get("MessageSid", ""),
        "wa_id": form_data.get("WaId", ""),
        "num_media": num_media,
        "media_url": media_url,
        "raw": form_data,
    }


def handle_whatsapp_webhook(
    form_data: dict,
    client_id: str,
    tier: str = "Starter",
) -> dict:
    """
    Traite un message WhatsApp entrant.

    Returns:
        {
            "success": bool,
            "lead_id": str,
            "twiml": str,       # TwiML XML à retourner à Twilio
            "message_sortant": str,
        }
    """
    try:
        parsed = parse_twilio_whatsapp_payload(form_data)
    except Exception as e:
        logger.error(f"Erreur parsing WhatsApp payload : {e}")
        return {
            "success": False,
            "error": str(e),
            "twiml": _empty_twiml(),
        }

    telephone = parsed.get("telephone", "")
    message = parsed.get("message", "")

    if not telephone:
        logger.warning("WhatsApp webhook : numéro de téléphone manquant")
        return {"success": False, "error": "no_phone", "twiml": _empty_twiml()}

    if not message and not parsed.get("media_url"):
        logger.info(f"WhatsApp message vide de {telephone} — ignoré")
        return {"success": True, "twiml": _empty_twiml(), "message_sortant": ""}

    # Récupérer lead_id si connu
    existing_lead = get_lead_by_phone(telephone, client_id=client_id)
    lead_id = existing_lead.id if existing_lead else None

    logger.info(
        f"WhatsApp message de {telephone} — {len(message)} chars — "
        f"Lead connu: {'oui' if lead_id else 'non'}"
    )

    # Traitement via orchestrateur
    final_state = process_incoming_message(
        telephone=telephone,
        message=message or "[Message média reçu]",
        client_id=client_id,
        tier=tier,
        canal=Canal.WHATSAPP.value,
        prenom=parsed.get("prenom", ""),
        nom=parsed.get("nom", ""),
        lead_id=lead_id,
    )

    message_sortant = final_state.get("message_sortant", "")

    # Générer TwiML de réponse
    twiml = _build_twiml_response(message_sortant)

    return {
        "success": True,
        "lead_id": final_state.get("lead_id", ""),
        "score": final_state.get("score", 0),
        "status": final_state.get("status", ""),
        "message_sortant": message_sortant,
        "twiml": twiml,
    }


def _build_twiml_response(message: str) -> str:
    """Construit le TwiML XML pour répondre au message WhatsApp."""
    if not message:
        return _empty_twiml()

    # Échapper les caractères XML
    message_escaped = (
        message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{message_escaped}</Message>
</Response>"""


def _empty_twiml() -> str:
    """TwiML vide — aucune réponse envoyée."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response></Response>"""


# ─── Statut de livraison WhatsApp ─────────────────────────────────────────────

def handle_whatsapp_status_callback(form_data: dict) -> dict:
    """
    Traite les callbacks de statut Twilio WhatsApp.
    (sent, delivered, read, failed)

    Twilio envoie :
        MessageSid: SMxxx
        MessageStatus: delivered
        To: whatsapp:+33611223344
    """
    message_sid = form_data.get("MessageSid", "")
    status = form_data.get("MessageStatus", "")
    to = form_data.get("To", "").replace("whatsapp:", "")
    error_code = form_data.get("ErrorCode", "")

    logger.info(f"WhatsApp status : {message_sid} → {status} (to: {to})")

    if status == "failed":
        logger.error(f"WhatsApp FAILED : {message_sid} → {to} — Code: {error_code}")

    return {"message_sid": message_sid, "status": status, "to": to}
