"""
Stockage des SMS entrants dans la table conversations.
Isolé du webhook Twilio pour faciliter les tests et la réutilisation.

Comportement :
  1. Cherche un lead existant par (telephone, client_id)
  2. Si absent, crée un nouveau lead (statut "entrant")
  3. Stocke le message dans conversations (role="user")
  4. Retourne le lead_id et un flag is_new_lead

Aucune réponse automatique, aucune qualification IA.
Le dashboard agent lit les conversations récentes pour afficher les SMS reçus.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def store_incoming_message(
    from_number: str,
    body: str,
    client_id: str,
    canal: str = "sms",
    to_number: str = "",
    prenom: str = "",
    nom: str = "",
    email: str = "",
    source_metadata: Optional[dict] = None,
) -> dict:
    """
    Stocke un message entrant (SMS, WhatsApp, portail) en base.
    Version générique de store_incoming_sms().

    Returns:
        {"lead_id": str, "is_new_lead": bool, "stored": bool}
    """
    if not from_number:
        logger.warning("[MessageStorage] Message ignoré — numéro manquant")
        return {"lead_id": None, "is_new_lead": False, "stored": False}

    try:
        from memory.lead_repository import (
            get_lead_by_phone,
            create_lead,
            add_conversation_message,
        )
        from memory.models import Canal as CanalEnum, Lead, LeadStatus

        try:
            canal_enum = CanalEnum(canal)
        except ValueError:
            canal_enum = CanalEnum.SMS

        lead = get_lead_by_phone(from_number, client_id)
        is_new = False

        if not lead:
            lead = Lead(
                client_id=client_id,
                prenom=prenom,
                nom=nom,
                telephone=from_number,
                email=email,
                source=canal_enum,
                statut=LeadStatus.ENTRANT,
            )
            lead = create_lead(lead)
            is_new = True
            logger.info("[MessageStorage] Nouveau lead créé : %s (tel=%s)", lead.id, from_number)
        else:
            logger.info("[MessageStorage] Lead existant : %s (tel=%s)", lead.id, from_number)

        meta = {"from": from_number, "to": to_number, "source": canal, **(source_metadata or {})}
        add_conversation_message(
            lead_id=lead.id,
            client_id=client_id,
            role="user",
            contenu=body or "[Message sans texte]",
            canal=canal_enum,
            metadata=meta,
        )

        return {"lead_id": lead.id, "is_new_lead": is_new, "stored": True}

    except Exception as e:
        logger.error("[MessageStorage] Erreur stockage : %s", e)
        return {"lead_id": None, "is_new_lead": False, "stored": False}


def store_incoming_sms(
    from_number: str,
    to_number: str,
    body: str,
    client_id: str,
) -> dict:
    """
    Stocke un SMS entrant en base de données.

    Args:
        from_number : Numéro de l'expéditeur (format E.164, ex: +33600000001)
        to_number   : Numéro Twilio du client (ex: +33700000001)
        body        : Corps du SMS
        client_id   : ID de l'agence cliente

    Returns:
        {
            "lead_id": str,
            "is_new_lead": bool,
            "stored": bool,
        }
    """
    if not from_number or not body:
        logger.warning("[SMSStorage] SMS ignoré — numéro ou corps manquant")
        return {"lead_id": None, "is_new_lead": False, "stored": False}

    try:
        from memory.lead_repository import (
            get_lead_by_phone,
            create_lead,
            add_conversation_message,
        )
        from memory.models import Canal, Lead, LeadStatus

        # 1. Trouver ou créer le lead
        lead = get_lead_by_phone(from_number, client_id)
        is_new = False

        if not lead:
            lead = Lead(
                client_id=client_id,
                telephone=from_number,
                source=Canal.SMS,
                statut=LeadStatus.ENTRANT,
            )
            lead = create_lead(lead)
            is_new = True
            logger.info(
                "[SMSStorage] Nouveau lead créé : %s (tel=%s)", lead.id, from_number
            )
        else:
            logger.info(
                "[SMSStorage] Lead existant trouvé : %s (tel=%s)", lead.id, from_number
            )

        # 2. Stocker le message entrant
        add_conversation_message(
            lead_id=lead.id,
            client_id=client_id,
            role="user",
            contenu=body,
            canal=Canal.SMS,
            metadata={"from": from_number, "to": to_number, "source": "twilio_webhook"},
        )

        return {"lead_id": lead.id, "is_new_lead": is_new, "stored": True}

    except Exception as e:
        logger.error("[SMSStorage] Erreur stockage SMS : %s", e)
        return {"lead_id": None, "is_new_lead": False, "stored": False}
