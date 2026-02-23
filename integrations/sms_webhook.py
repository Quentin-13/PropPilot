"""
Webhook SMS entrant — Réception SMS via Twilio.
Twilio redirige les SMS entrants vers cet endpoint.

Configuration Twilio :
  - Console > Phone Numbers > Configure > Messaging Webhook
  - URL : https://votre-domaine.com/webhooks/sms
  - Method : HTTP POST

Usage Flask :
    @app.route("/webhooks/sms", methods=["POST"])
    def sms_endpoint():
        result = handle_sms_webhook(request.form.to_dict(), client_id="client_demo")
        return result["twiml"], 200, {"Content-Type": "text/xml"}

Usage FastAPI :
    @app.post("/webhooks/sms")
    async def sms_endpoint(request: Request):
        form = await request.form()
        result = handle_sms_webhook(dict(form), client_id="client_demo")
        return Response(content=result["twiml"], media_type="text/xml")
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from config.settings import get_settings
from memory.lead_repository import get_lead_by_phone
from memory.models import Canal
from orchestrator import process_incoming_message

logger = logging.getLogger(__name__)

# Mots-clés STOP conformément aux obligations légales RGPD
STOP_KEYWORDS = {"stop", "arret", "arrêt", "désinscription", "desinscription", "unsubscribe", "fin"}


def parse_twilio_sms_payload(form_data: dict) -> dict:
    """
    Parse le payload Twilio SMS entrant.

    Twilio envoie :
        From: +33611223344
        To: +33755001122
        Body: Bonjour je cherche un appartement à Lyon
        MessageSid: SMxxx...
        NumMedia: 0
        FromCity: PARIS
        FromState:
        FromZip:
        FromCountry: FR
    """
    telephone = form_data.get("From", "").strip()
    body = form_data.get("Body", "").strip()
    to = form_data.get("To", "").strip()
    message_sid = form_data.get("MessageSid", "")
    from_city = form_data.get("FromCity", "")
    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0", "") if num_media > 0 else ""

    return {
        "telephone": telephone,
        "message": body,
        "to": to,
        "canal": Canal.SMS.value,
        "message_sid": message_sid,
        "from_city": from_city,
        "num_media": num_media,
        "media_url": media_url,
        "raw": form_data,
    }


def is_stop_request(message: str) -> bool:
    """Détecte si le message est une demande de désinscription SMS (conformité RGPD)."""
    message_clean = message.strip().lower()
    # Message court = 1 mot = potentiellement STOP
    if len(message_clean.split()) <= 2:
        return any(kw in message_clean for kw in STOP_KEYWORDS)
    return False


def handle_stop_request(telephone: str, client_id: str) -> str:
    """
    Traite une demande STOP : marque le lead comme ne voulant plus de contact.
    Retourne le message de confirmation légale obligatoire.
    """
    from memory.lead_repository import get_lead_by_phone, update_lead
    from memory.models import LeadStatus

    lead = get_lead_by_phone(telephone, client_id=client_id)
    if lead:
        lead.statut = LeadStatus.PERDU
        lead.notes_agent = (lead.notes_agent or "") + "\n[STOP SMS reçu — ne plus contacter]"
        update_lead(lead)
        logger.info(f"STOP reçu de {telephone} — lead {lead.id} marqué PERDU")
    else:
        logger.info(f"STOP reçu de {telephone} — pas de lead associé")

    # Message de confirmation légal obligatoire
    return "Vous avez été désinscrit(e). Vous ne recevrez plus de SMS de notre part. Contact : contact@agence.fr"


def handle_sms_webhook(
    form_data: dict,
    client_id: str,
    tier: str = "Starter",
) -> dict:
    """
    Traite un SMS entrant.

    Returns:
        {
            "success": bool,
            "lead_id": str,
            "twiml": str,           # TwiML XML à retourner à Twilio
            "message_sortant": str,
            "is_stop": bool,
        }
    """
    try:
        parsed = parse_twilio_sms_payload(form_data)
    except Exception as e:
        logger.error(f"Erreur parsing SMS payload : {e}")
        return {"success": False, "error": str(e), "twiml": _empty_twiml()}

    telephone = parsed.get("telephone", "")
    message = parsed.get("message", "")

    if not telephone:
        logger.warning("SMS webhook : numéro de téléphone manquant")
        return {"success": False, "error": "no_phone", "twiml": _empty_twiml()}

    # Détecter demande STOP (conformité CNIL / RGPD)
    if is_stop_request(message):
        stop_response = handle_stop_request(telephone, client_id)
        logger.info(f"STOP traité pour {telephone}")
        return {
            "success": True,
            "is_stop": True,
            "twiml": _build_twiml_response(stop_response),
            "message_sortant": stop_response,
            "lead_id": "",
        }

    if not message:
        logger.info(f"SMS vide de {telephone} — ignoré")
        return {"success": True, "twiml": _empty_twiml(), "message_sortant": "", "is_stop": False}

    # Vérifier si lead existant
    existing_lead = get_lead_by_phone(telephone, client_id=client_id)
    lead_id = existing_lead.id if existing_lead else None

    logger.info(
        f"SMS de {telephone} — {len(message)} chars — "
        f"Lead connu: {'oui' if lead_id else 'non'}"
        + (f" (ville: {parsed.get('from_city')})" if parsed.get("from_city") else "")
    )

    # Traitement via orchestrateur
    final_state = process_incoming_message(
        telephone=telephone,
        message=message,
        client_id=client_id,
        tier=tier,
        canal=Canal.SMS.value,
        lead_id=lead_id,
    )

    message_sortant = final_state.get("message_sortant", "")
    twiml = _build_twiml_response(message_sortant)

    return {
        "success": True,
        "lead_id": final_state.get("lead_id", ""),
        "score": final_state.get("score", 0),
        "status": final_state.get("status", ""),
        "message_sortant": message_sortant,
        "twiml": twiml,
        "is_stop": False,
    }


# ─── Callback statut SMS ──────────────────────────────────────────────────────

def handle_sms_status_callback(form_data: dict) -> dict:
    """
    Traite les callbacks de statut Twilio SMS.
    (queued, sent, delivered, undelivered, failed)

    Utile pour tracker la délivrabilité et adapter la stratégie nurturing.
    """
    message_sid = form_data.get("MessageSid", "")
    status = form_data.get("MessageStatus", "")
    to = form_data.get("To", "")
    error_code = form_data.get("ErrorCode", "")
    error_message = form_data.get("ErrorMessage", "")

    logger.info(f"SMS status : {message_sid} → {status} (to: {to})")

    if status in ("failed", "undelivered"):
        logger.error(
            f"SMS ÉCHEC : {message_sid} → {to} — Code: {error_code} — {error_message}"
        )
        # Marquer le numéro comme problématique si statut "undelivered" persistant
        _handle_delivery_failure(to, status, error_code)

    return {
        "message_sid": message_sid,
        "status": status,
        "to": to,
        "error_code": error_code,
    }


def _handle_delivery_failure(telephone: str, status: str, error_code: str) -> None:
    """Marque un numéro problématique dans les notes du lead."""
    if not telephone:
        return

    settings = get_settings()

    from memory.lead_repository import get_lead_by_phone, update_lead
    lead = get_lead_by_phone(telephone, client_id=settings.agency_client_id)
    if lead and status == "undelivered":
        note = f"\n[SMS {status} — code {error_code} — vérifier le numéro]"
        if note not in (lead.notes_agent or ""):
            lead.notes_agent = (lead.notes_agent or "") + note
            update_lead(lead)


# ─── TwiML helpers ────────────────────────────────────────────────────────────

def _build_twiml_response(message: str) -> str:
    """Construit le TwiML XML pour répondre au SMS."""
    if not message:
        return _empty_twiml()

    message_escaped = (
        message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{message_escaped}</Message>
</Response>"""


def _empty_twiml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response></Response>"""
