"""
Intégration Apimo CRM — Synchronisation leads, mandats, biens.
Apimo est le CRM leader des agences immobilières françaises.
Documentation API : https://www.apimo.com/api/
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import requests

from config.settings import get_settings
from memory.database import get_connection
from memory.lead_repository import get_lead, update_lead
from memory.models import Lead, LeadStatus

logger = logging.getLogger(__name__)

APIMO_API_BASE = "https://api.apimo.pro"
APIMO_TIMEOUT = 15  # secondes


class ApimoClient:
    """
    Client Apimo CRM.
    Mode mock automatique si APIMO_PROVIDER_ID ou APIMO_TOKEN absents.
    """

    def __init__(self, provider_id: Optional[str] = None, token: Optional[str] = None):
        self.settings = get_settings()
        self.provider_id = provider_id or getattr(self.settings, "apimo_provider_id", "")
        self.token = token or getattr(self.settings, "apimo_token", "")
        self.mock = not (self.provider_id and self.token)

        if self.mock:
            logger.info("[MOCK] ApimoClient — pas de clés Apimo, mode démo activé.")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _base_url(self) -> str:
        return f"{APIMO_API_BASE}/providers/{self.provider_id}"

    # ─── Contacts / Leads ─────────────────────────────────────────────────────

    def create_contact(self, lead: Lead) -> dict:
        """
        Crée ou met à jour un contact dans Apimo depuis un lead local.

        Returns:
            {"success": bool, "apimo_id": str, "mock": bool}
        """
        if self.mock:
            mock_id = f"APM-{lead.id[:8].upper()}"
            logger.info(f"[MOCK] Apimo create_contact → {mock_id} pour {lead.nom_complet}")
            return {"success": True, "apimo_id": mock_id, "mock": True}

        payload = {
            "first_name": lead.prenom or "",
            "last_name": lead.nom or "",
            "phone": lead.telephone or "",
            "email": lead.email or "",
            "comment": f"Lead IA — Score {lead.score}/10 — {lead.projet.value} — {lead.localisation}",
            "origin": "web",
        }

        try:
            r = requests.post(
                f"{self._base_url()}/contacts",
                headers=self._headers(),
                json=payload,
                timeout=APIMO_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            apimo_id = str(data.get("id", ""))
            logger.info(f"Apimo contact créé : {apimo_id}")
            return {"success": True, "apimo_id": apimo_id, "mock": False}
        except Exception as e:
            logger.error(f"Apimo create_contact error : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def sync_lead_to_apimo(self, lead_id: str) -> dict:
        """
        Synchronise un lead local vers Apimo CRM.
        Crée le contact + ajoute une note avec le résumé IA.
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"success": False, "error": "Lead introuvable"}

        result = self.create_contact(lead)
        if not result.get("success"):
            return result

        apimo_id = result["apimo_id"]

        # Ajouter note de qualification IA
        note_result = self.add_contact_note(
            apimo_contact_id=apimo_id,
            note=(
                f"[IA Qualification]\n"
                f"Score : {lead.score}/10\n"
                f"Projet : {lead.projet.value}\n"
                f"Budget : {lead.budget or 'non précisé'}\n"
                f"Timeline : {lead.timeline or 'non précisé'}\n"
                f"Financement : {lead.financement or 'non précisé'}\n"
                f"Motivation : {lead.motivation or 'non précisé'}\n"
                f"Statut : {lead.statut.value}\n"
                f"Résumé : {lead.resume or 'non disponible'}"
            ),
        )

        # Stocker l'ID Apimo dans les notes_agent du lead
        lead.notes_agent = (lead.notes_agent or "") + f"\n[Apimo ID: {apimo_id}]"
        update_lead(lead)

        return {
            "success": True,
            "apimo_id": apimo_id,
            "note_added": note_result.get("success", False),
            "mock": result.get("mock", False),
        }

    def add_contact_note(self, apimo_contact_id: str, note: str) -> dict:
        """Ajoute une note à un contact Apimo."""
        if self.mock:
            logger.info(f"[MOCK] Apimo add_note → contact {apimo_contact_id}")
            return {"success": True, "mock": True}

        try:
            r = requests.post(
                f"{self._base_url()}/contacts/{apimo_contact_id}/notes",
                headers=self._headers(),
                json={"content": note},
                timeout=APIMO_TIMEOUT,
            )
            r.raise_for_status()
            return {"success": True, "mock": False}
        except Exception as e:
            logger.error(f"Apimo add_note error : {e}")
            return {"success": False, "error": str(e)}

    # ─── Biens / Mandats ──────────────────────────────────────────────────────

    def create_property(self, listing_data: dict) -> dict:
        """
        Crée un bien immobilier dans Apimo depuis les données d'annonce générées.

        Args:
            listing_data: dict issu de ListingGeneratorAgent.generate()

        Returns:
            {"success": bool, "apimo_property_id": str, "mock": bool}
        """
        if self.mock:
            mock_id = f"APM-PROP-{listing_data.get('listing_id', 'XXX')[:6].upper()}"
            logger.info(f"[MOCK] Apimo create_property → {mock_id}")
            return {"success": True, "apimo_property_id": mock_id, "mock": True}

        # Mapping vers le format Apimo
        payload = {
            "category": self._map_type_bien(listing_data.get("type_bien", "Appartement")),
            "name": listing_data.get("titre", ""),
            "description": listing_data.get("description_longue", ""),
            "area": listing_data.get("surface", 0),
            "rooms": listing_data.get("nb_pieces", 0),
            "bedrooms": listing_data.get("nb_chambres", 0),
            "price": listing_data.get("prix", 0),
            "city": listing_data.get("adresse", ""),
            "published": True,
        }

        try:
            r = requests.post(
                f"{self._base_url()}/properties",
                headers=self._headers(),
                json=payload,
                timeout=APIMO_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            apimo_id = str(data.get("id", ""))
            logger.info(f"Apimo propriété créée : {apimo_id}")
            return {"success": True, "apimo_property_id": apimo_id, "mock": False}
        except Exception as e:
            logger.error(f"Apimo create_property error : {e}")
            return {"success": False, "error": str(e)}

    def get_contacts(self, limit: int = 50) -> list[dict]:
        """Récupère les contacts Apimo pour synchronisation inverse."""
        if self.mock:
            return [
                {"id": "APM-001", "first_name": "Marie", "last_name": "Dupont", "phone": "+33611223344", "email": "marie.dupont@email.fr"},
                {"id": "APM-002", "first_name": "Jean", "last_name": "Martin", "phone": "+33622334455", "email": "jean.martin@email.fr"},
            ]

        try:
            r = requests.get(
                f"{self._base_url()}/contacts",
                headers=self._headers(),
                params={"limit": limit},
                timeout=APIMO_TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("contacts", [])
        except Exception as e:
            logger.error(f"Apimo get_contacts error : {e}")
            return []

    def sync_all_qualified_leads(self, client_id: str) -> dict:
        """
        Synchronise tous les leads qualifiés (score ≥ 7) vers Apimo.
        Utile pour synchronisation batch quotidienne.
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM leads WHERE client_id = ? AND score >= 7 ORDER BY created_at DESC",
                (client_id,),
            ).fetchall()

        synced = 0
        errors = 0
        for row in rows:
            result = self.sync_lead_to_apimo(row["id"])
            if result.get("success"):
                synced += 1
            else:
                errors += 1

        logger.info(f"Sync Apimo batch : {synced} synced, {errors} errors")
        return {
            "total": len(rows),
            "synced": synced,
            "errors": errors,
            "mock": self.mock,
        }

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _map_type_bien(type_bien: str) -> int:
        """Mappe le type de bien vers les catégories Apimo."""
        mapping = {
            "Appartement": 1,
            "Maison": 2,
            "Studio": 1,
            "Loft": 1,
            "Duplex": 1,
            "Villa": 2,
            "Terrain": 6,
            "Local commercial": 7,
            "Bureau": 8,
        }
        return mapping.get(type_bien, 1)


# ─── Webhook Apimo entrant ─────────────────────────────────────────────────────

def parse_apimo_webhook(payload: dict) -> dict:
    """
    Parse un webhook entrant depuis Apimo (nouveau mandat, mise à jour contact).

    Returns:
        {"event_type": str, "data": dict}
    """
    event_type = payload.get("event", "unknown")

    if event_type == "contact.created":
        contact = payload.get("contact", {})
        return {
            "event_type": "new_contact",
            "data": {
                "apimo_id": str(contact.get("id", "")),
                "prenom": contact.get("first_name", ""),
                "nom": contact.get("last_name", ""),
                "telephone": contact.get("phone", ""),
                "email": contact.get("email", ""),
                "source": "apimo",
            },
        }

    elif event_type == "property.mandate.signed":
        prop = payload.get("property", {})
        return {
            "event_type": "mandate_signed",
            "data": {
                "apimo_property_id": str(prop.get("id", "")),
                "adresse": prop.get("address", ""),
                "prix": prop.get("price", 0),
            },
        }

    return {"event_type": event_type, "data": payload}
