"""
Portail BienIci — webhook pour leads entrants.
BienIci (bienici.com) appartient au groupe Axel Springer / Avendrealouer.
Format JSON similaire à SeLoger.
Fallback mock automatique.
"""
from __future__ import annotations

import logging
from typing import Optional

from memory.lead_repository import create_lead
from memory.models import Canal, Lead, LeadStatus, ProjetType

logger = logging.getLogger(__name__)

PORTAL_NAME = "BienIci"


def parse_bienici_lead(payload: dict) -> Optional[dict]:
    """
    Parse un webhook BienIci.

    Format attendu :
    {
        "contactRequest": {
            "firstName": "...", "lastName": "...",
            "phone": "...", "email": "...",
            "message": "...",
            "adId": "...",
        },
        "ad": {"price": ..., "city": ..., "transactionType": "buy|rent"}
    }
    """
    contact = payload.get("contactRequest", payload.get("contact", {}))
    ad = payload.get("ad", payload.get("property", {}))

    phone = contact.get("phone", contact.get("telephone", ""))
    if not phone:
        return None

    # Normalisation téléphone
    tel = phone.replace(" ", "").replace("-", "")
    if tel.startswith("0") and len(tel) == 10:
        tel = "+33" + tel[1:]

    transaction = ad.get("transactionType", ad.get("transaction", "buy")).lower()
    projet = ProjetType.ACHAT if "buy" in transaction or "sale" in transaction else (
        ProjetType.LOCATION if "rent" in transaction else ProjetType.INCONNU
    )

    return {
        "prenom": contact.get("firstName", contact.get("prenom", "")),
        "nom": contact.get("lastName", contact.get("nom", "")),
        "telephone": tel,
        "email": contact.get("email", ""),
        "message": contact.get("message", ""),
        "localisation": ad.get("city", ad.get("ville", "")),
        "budget": str(ad.get("price", "")),
        "projet": projet,
        "ad_id": contact.get("adId", ad.get("id", "")),
    }


def handle_bienici_lead(payload: dict, client_id: str, tier: str) -> dict:
    """
    Traitement d'un lead entrant BienIci.
    Crée le lead en DB et déclenche la qualification via l'orchestrateur.
    """
    parsed = parse_bienici_lead(payload)
    if not parsed:
        logger.warning("[BienIci] Payload non reconnu ou sans téléphone")
        return {"success": False, "error": "payload_invalide"}

    # Créer le lead
    lead = Lead(
        client_id=client_id,
        prenom=parsed["prenom"],
        nom=parsed["nom"],
        telephone=parsed["telephone"],
        email=parsed["email"],
        projet=parsed["projet"],
        localisation=parsed["localisation"],
        source=Canal.WEB,
        notes_agent=f"[BienIci] Annonce #{parsed['ad_id']}" if parsed.get("ad_id") else "[BienIci]",
    )
    saved = create_lead(lead)

    # Déclencher la qualification
    message = parsed.get("message", "") or f"Bonjour, je suis intéressé(e) par un bien à {parsed['localisation']}."
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
            "source": "bienici",
        }
    except Exception as e:
        logger.error(f"[BienIci] Erreur orchestrateur : {e}")
        return {"success": True, "lead_id": saved.id, "source": "bienici"}
