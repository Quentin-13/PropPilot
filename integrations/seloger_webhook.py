"""
Webhook SeLoger / LeBonCoin — Réception leads depuis portails immobiliers.
SeLoger et LeBonCoin Immo envoient des leads via webhook HTTP POST.

Format SeLoger : https://www.seloger.com/pro/integration/leads-webhook
Format LeBonCoin : format propriétaire similaire

Usage dans un serveur Flask/FastAPI :
    from integrations.seloger_webhook import handle_seloger_lead, handle_leboncoin_lead
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from config.settings import get_settings
from memory.models import Canal
from orchestrator import process_incoming_message

logger = logging.getLogger(__name__)


# ─── SeLoger ──────────────────────────────────────────────────────────────────

def verify_seloger_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Vérifie la signature HMAC-SHA256 du webhook SeLoger.
    Clé secrète configurée dans SELOGER_WEBHOOK_SECRET.
    """
    settings = get_settings()
    secret = getattr(settings, "seloger_webhook_secret", "")
    if not secret:
        logger.warning("SELOGER_WEBHOOK_SECRET non configuré — signature non vérifiée.")
        return True  # Accept in dev/mock mode

    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.replace("sha256=", ""))


def parse_seloger_lead(payload: dict) -> dict:
    """
    Parse le format SeLoger vers les champs Lead standard.

    SeLoger payload example:
    {
        "lead_id": "SL-12345",
        "contact": {"firstname": "Marie", "lastname": "Dupont", "phone": "0611223344", "email": "marie@email.fr"},
        "property": {"reference": "APT-001", "type": "appartement", "price": 320000, "area": 65},
        "message": "Je suis intéressée par ce bien, est-il toujours disponible ?",
        "source": "seloger",
        "created_at": "2026-02-23T14:30:00Z"
    }
    """
    contact = payload.get("contact", {})
    prop = payload.get("property", {})
    message = payload.get("message", "Je suis intéressé(e) par votre annonce.")

    prenom = contact.get("firstname", "")
    nom = contact.get("lastname", "")
    telephone = _normalize_phone(contact.get("phone", ""))
    email = contact.get("email", "")
    prix_bien = prop.get("price", 0)
    type_bien = prop.get("type", "bien")
    surface = prop.get("area", 0)
    reference = prop.get("reference", payload.get("lead_id", ""))

    # Construction message enrichi pour qualification
    message_enrichi = (
        f"{message}\n"
        f"[Lead SeLoger — Réf: {reference} — {type_bien}"
        f"{', ' + str(surface) + 'm²' if surface else ''}"
        f"{', ' + str(int(prix_bien)) + '€' if prix_bien else ''}]"
    )

    return {
        "prenom": prenom,
        "nom": nom,
        "telephone": telephone,
        "email": email,
        "message": message_enrichi,
        "canal": Canal.EMAIL.value,
        "source": "seloger",
        "source_data": {
            "seloger_lead_id": payload.get("lead_id", ""),
            "property_ref": reference,
            "type_bien": type_bien,
            "prix_bien": prix_bien,
            "surface": surface,
        },
    }


def handle_seloger_lead(
    payload: dict,
    client_id: str,
    tier: str = "Starter",
    raw_bytes: Optional[bytes] = None,
    signature: Optional[str] = None,
) -> dict:
    """
    Point d'entrée principal pour un lead SeLoger.
    Vérifie la signature, parse le lead, lance le flux de qualification.

    Returns:
        {"success": bool, "lead_id": str, "message_sortant": str}
    """
    # Vérification signature (optionnel)
    if raw_bytes and signature:
        if not verify_seloger_signature(raw_bytes, signature):
            logger.warning("SeLoger webhook : signature invalide")
            return {"success": False, "error": "invalid_signature"}

    try:
        lead_data = parse_seloger_lead(payload)
    except Exception as e:
        logger.error(f"Erreur parsing SeLoger payload : {e}")
        return {"success": False, "error": str(e)}

    if not lead_data.get("telephone"):
        logger.warning("SeLoger lead sans numéro de téléphone — qualification impossible par SMS")
        # Qualifier quand même avec email si disponible
        if not lead_data.get("email"):
            return {"success": False, "error": "no_contact_info"}

    logger.info(
        f"Lead SeLoger reçu : {lead_data['prenom']} {lead_data['nom']} — "
        f"{lead_data['telephone'] or lead_data['email']}"
    )

    # Lancement qualification via orchestrateur
    final_state = process_incoming_message(
        telephone=lead_data["telephone"],
        message=lead_data["message"],
        client_id=client_id,
        tier=tier,
        canal=lead_data["canal"],
        prenom=lead_data["prenom"],
        nom=lead_data["nom"],
        email=lead_data["email"],
        lead_id=None,
    )

    return {
        "success": True,
        "lead_id": final_state.get("lead_id", ""),
        "score": final_state.get("score", 0),
        "status": final_state.get("status", ""),
        "message_sortant": final_state.get("message_sortant", ""),
        "source": "seloger",
    }


# ─── LeBonCoin ────────────────────────────────────────────────────────────────

def parse_leboncoin_lead(payload: dict) -> dict:
    """
    Parse le format LeBonCoin Immo vers les champs Lead standard.

    LeBonCoin payload example:
    {
        "id": "LBC-67890",
        "sender": {"first_name": "Paul", "last_name": "Martin", "phone": "0622334455", "email": "paul@email.fr"},
        "ad": {"title": "Appartement 3P Lyon 6ème", "price": 285000, "surface": 72},
        "body": "Bonjour, je voudrais visiter cet appartement.",
        "created_at": "2026-02-23T16:00:00Z"
    }
    """
    sender = payload.get("sender", {})
    ad = payload.get("ad", {})
    body = payload.get("body", "Je suis intéressé(e) par votre annonce sur LeBonCoin.")

    prenom = sender.get("first_name", "")
    nom = sender.get("last_name", "")
    telephone = _normalize_phone(sender.get("phone", ""))
    email = sender.get("email", "")
    titre_annonce = ad.get("title", "")
    prix_annonce = ad.get("price", 0)
    surface = ad.get("surface", 0)
    ad_id = payload.get("id", "")

    message_enrichi = (
        f"{body}\n"
        f"[Lead LeBonCoin — {titre_annonce}"
        f"{', ' + str(surface) + 'm²' if surface else ''}"
        f"{', ' + str(int(prix_annonce)) + '€' if prix_annonce else ''}]"
    )

    return {
        "prenom": prenom,
        "nom": nom,
        "telephone": telephone,
        "email": email,
        "message": message_enrichi,
        "canal": Canal.EMAIL.value,
        "source": "leboncoin",
        "source_data": {
            "lbc_lead_id": ad_id,
            "titre_annonce": titre_annonce,
            "prix_annonce": prix_annonce,
            "surface": surface,
        },
    }


def handle_leboncoin_lead(
    payload: dict,
    client_id: str,
    tier: str = "Starter",
) -> dict:
    """
    Point d'entrée pour un lead LeBonCoin Immo.
    """
    try:
        lead_data = parse_leboncoin_lead(payload)
    except Exception as e:
        logger.error(f"Erreur parsing LeBonCoin payload : {e}")
        return {"success": False, "error": str(e)}

    if not lead_data.get("telephone") and not lead_data.get("email"):
        return {"success": False, "error": "no_contact_info"}

    logger.info(
        f"Lead LeBonCoin reçu : {lead_data['prenom']} {lead_data['nom']} — "
        f"{lead_data.get('telephone', lead_data.get('email', ''))}"
    )

    final_state = process_incoming_message(
        telephone=lead_data["telephone"],
        message=lead_data["message"],
        client_id=client_id,
        tier=tier,
        canal=lead_data["canal"],
        prenom=lead_data["prenom"],
        nom=lead_data["nom"],
        email=lead_data["email"],
    )

    return {
        "success": True,
        "lead_id": final_state.get("lead_id", ""),
        "score": final_state.get("score", 0),
        "status": final_state.get("status", ""),
        "message_sortant": final_state.get("message_sortant", ""),
        "source": "leboncoin",
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Normalise un numéro de téléphone français vers le format E.164."""
    if not phone:
        return ""
    # Supprimer espaces, tirets, points
    cleaned = "".join(c for c in phone if c.isdigit() or c == "+")
    # Convertir format 06xxxxxxxx → +336xxxxxxxx
    if cleaned.startswith("0") and len(cleaned) == 10:
        cleaned = "+33" + cleaned[1:]
    elif cleaned.startswith("33") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned
