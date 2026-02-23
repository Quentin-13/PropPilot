"""
Portail Logic-Immo — webhook pour leads entrants.
Logic-Immo (logic-immo.com) : portail partenaire SeLoger Group.
Format JSON propriétaire.
Fallback mock automatique.
"""
from __future__ import annotations

import logging
from typing import Optional

from memory.lead_repository import create_lead
from memory.models import Canal, Lead, ProjetType

logger = logging.getLogger(__name__)

PORTAL_NAME = "Logic-Immo"


def parse_logic_immo_lead(payload: dict) -> Optional[dict]:
    """
    Parse un webhook Logic-Immo.

    Format attendu :
    {
        "lead": {
            "firstName": "...", "lastName": "...",
            "phone": "...", "email": "...",
            "message": "...",
            "propertyType": "house|apartment",
            "transactionType": "buy|rent",
            "city": "...",
            "budget": ...
        }
    }
    """
    lead_data = payload.get("lead", payload)

    phone = lead_data.get("phone", lead_data.get("telephone", ""))
    if not phone:
        return None

    tel = phone.replace(" ", "").replace("-", "")
    if tel.startswith("0") and len(tel) == 10:
        tel = "+33" + tel[1:]

    transaction = lead_data.get("transactionType", "buy").lower()
    if "buy" in transaction or "achat" in transaction:
        projet = ProjetType.ACHAT
    elif "rent" in transaction or "location" in transaction:
        projet = ProjetType.LOCATION
    else:
        projet = ProjetType.INCONNU

    return {
        "prenom": lead_data.get("firstName", lead_data.get("prenom", "")),
        "nom": lead_data.get("lastName", lead_data.get("nom", "")),
        "telephone": tel,
        "email": lead_data.get("email", ""),
        "message": lead_data.get("message", ""),
        "localisation": lead_data.get("city", lead_data.get("ville", "")),
        "budget": str(lead_data.get("budget", lead_data.get("maxPrice", ""))),
        "projet": projet,
        "property_ref": lead_data.get("propertyRef", lead_data.get("reference", "")),
    }


def handle_logic_immo_lead(payload: dict, client_id: str, tier: str) -> dict:
    """
    Traitement d'un lead entrant Logic-Immo.
    Crée le lead en DB et déclenche la qualification.
    """
    parsed = parse_logic_immo_lead(payload)
    if not parsed:
        logger.warning("[Logic-Immo] Payload non reconnu ou sans téléphone")
        return {"success": False, "error": "payload_invalide"}

    lead = Lead(
        client_id=client_id,
        prenom=parsed["prenom"],
        nom=parsed["nom"],
        telephone=parsed["telephone"],
        email=parsed["email"],
        projet=parsed["projet"],
        localisation=parsed["localisation"],
        source=Canal.WEB,
        notes_agent=f"[Logic-Immo] Réf. #{parsed['property_ref']}" if parsed.get("property_ref") else "[Logic-Immo]",
    )
    saved = create_lead(lead)

    message = parsed.get("message", "") or f"Bonjour, je cherche un bien à {parsed['localisation']}."
    try:
        from orchestrator import process_incoming_message
        result = process_incoming_message(
            telephone=parsed["telephone"],
            message=message,
            client_id=client_id,
            tier=tier,
            canal="web",
            prenom=parsed["prenom"],
            nom=parsed["nom"],
            email=parsed["email"],
        )
        return {
            "success": True,
            "lead_id": saved.id,
            "score": result.get("score", 0),
            "source": "logic_immo",
        }
    except Exception as e:
        logger.error(f"[Logic-Immo] Erreur orchestrateur : {e}")
        return {"success": True, "lead_id": saved.id, "source": "logic_immo"}
