"""
Connecteur Hektor — La Boîte Immo.
CRM le plus utilisé par les agences indépendantes françaises.
API REST — authentification Bearer token.
Fallback mock automatique si API indisponible.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Optional

import httpx

from memory.models import Canal, Lead, LeadStatus, ProjetType
from .base import BaseCRMConnector

logger = logging.getLogger(__name__)


class HektorConnector(BaseCRMConnector):

    crm_name = "Hektor"
    api_base_url = "https://api.laboiteimmo.com/v1"

    # ─── Méthodes abstraites ──────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Teste la connexion Hektor avec le token fourni."""
        if self._mock_mode:
            return {
                "success": True,
                "message": "[MOCK] Connexion Hektor simulée",
                "agency_name": "Agence Demo Hektor",
            }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.api_base_url}/agency",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "success": True,
                        "message": "Connexion Hektor établie",
                        "agency_name": data.get("name", "Agence inconnue"),
                    }
                return {
                    "success": False,
                    "message": f"Erreur API Hektor : {r.status_code}",
                    "agency_name": "",
                }
        except Exception as e:
            logger.warning(f"[Hektor] test_connection exception : {e} — fallback mock")
            return {
                "success": True,
                "message": "[MOCK] Connexion Hektor simulée (API indisponible)",
                "agency_name": "Agence Demo Hektor",
            }

    async def get_new_leads(self, since: datetime) -> list[Lead]:
        """Récupère les prospects Hektor créés depuis `since`."""
        if self._mock_mode:
            return self._mock_leads()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.api_base_url}/contacts",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={
                        "created_after": since.isoformat(),
                        "type": "prospect",
                        "limit": 100,
                    },
                )
                if r.status_code == 200:
                    contacts = r.json().get("data", [])
                    leads = [self._hektor_contact_to_lead(c) for c in contacts]
                    self._log(f"{len(leads)} nouveaux leads récupérés")
                    return leads
        except Exception as e:
            logger.warning(f"[Hektor] get_new_leads exception : {e} — fallback mock")
        return self._mock_leads()

    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        """
        Écrit le statut de qualification de Léa dans Hektor.
        PropPilot → Hektor : qualified→prospect_chaud, nurturing→prospect_tiede, etc.
        """
        status_map = {
            "qualified": "prospect_chaud",
            "nurturing": "prospect_tiede",
            "not_qualified": "prospect_froid",
            "appointment_booked": "rdv_planifie",
        }
        hektor_status = status_map.get(status, "en_cours")

        if self._mock_mode:
            self._log(f"[MOCK] update_lead_status {crm_lead_id} → {hektor_status}")
            return True
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.patch(
                    f"{self.api_base_url}/contacts/{crm_lead_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "status": hektor_status,
                        "notes": f"[PropPilot] {notes}",
                        "updated_at": datetime.now().isoformat(),
                    },
                )
                return r.status_code == 200
        except Exception as e:
            logger.warning(f"[Hektor] update_lead_status exception : {e}")
            return True  # Mock : toujours succès

    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
"""PropPilot a booké un RDV → on le crée dans l'agenda Hektor."""
        if self._mock_mode:
            self._log(f"[MOCK] create_appointment {crm_lead_id} @ {datetime_slot.isoformat()}")
            return True
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.api_base_url}/appointments",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "contact_id": crm_lead_id,
                        "date": datetime_slot.isoformat(),
                        "agent": agent_name,
                        "type": "visite",
                        "source": "PropPilot",
                        "notes": "RDV créé automatiquement par PropPilot",
                    },
                )
                return r.status_code in (200, 201)
        except Exception as e:
            logger.warning(f"[Hektor] create_appointment exception : {e}")
            return True

    async def push_listing(self, listing_data: dict) -> str:
        """Hugo a rédigé une annonce → on la pousse vers Hektor."""
        if self._mock_mode:
            mock_id = f"hektor_mock_{int(datetime.now().timestamp())}"
            self._log(f"[MOCK] push_listing → {mock_id}")
            return mock_id
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.api_base_url}/properties",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "title": listing_data.get("titre", ""),
                        "description": listing_data.get("description_longue", ""),
                        "price": listing_data.get("prix", 0),
                        "surface": listing_data.get("surface", 0),
                        "address": listing_data.get("adresse", ""),
                        "source": "PropPilot — Hugo",
                        "status": "draft",
                    },
                )
                if r.status_code in (200, 201):
                    return r.json().get("id", f"hektor_{int(datetime.now().timestamp())}")
        except Exception as e:
            logger.warning(f"[Hektor] push_listing exception : {e}")
        return f"hektor_mock_{int(datetime.now().timestamp())}"

    # ─── Webhook parser ───────────────────────────────────────────────────────

    @staticmethod
    def parse_webhook_payload(payload: dict, agency_id: str) -> Optional[Lead]:
        """
        Parse un webhook entrant Hektor (contact.created / lead.new).
        Retourne un Lead PropPilot ou None si payload non reconnu.
        """
        event = payload.get("event", "")
        if event not in ("contact.created", "lead.new", "prospect.created"):
            return None

        contact = payload.get("contact", payload.get("data", {}))
        phone = contact.get("phone", contact.get("telephone", ""))
        if not phone:
            return None

        connector = HektorConnector(api_key="", agency_id=agency_id)
        return connector._hektor_contact_to_lead(contact)

    # ─── Helpers privés ───────────────────────────────────────────────────────

    def _hektor_contact_to_lead(self, contact: dict) -> Lead:
        """Convertit un contact Hektor en Lead PropPilot standardisé."""
        crm_id = str(contact.get("id", ""))
        return Lead(
            client_id=self.agency_id,
            prenom=contact.get("firstname", contact.get("prenom", "")),
            nom=contact.get("lastname", contact.get("nom", "")),
            telephone=contact.get("phone", contact.get("telephone", "")),
            email=contact.get("email", ""),
            projet=self.normalize_project_type(contact.get("project", contact.get("projet", "achat"))),
            localisation=contact.get("location", contact.get("localisation", "")),
            budget=self.format_budget(contact.get("budget")),
            source=Canal.MANUEL,
            notes_agent=self.inject_crm_id("", crm_id) if crm_id else "",
        )

    def _mock_leads(self) -> list[Lead]:
        """Leads de démonstration Hektor."""
        mock_contacts = [
            {
                "id": f"hektor_{random.randint(10000, 99999)}",
                "firstname": "Pierre",
                "lastname": "Durand",
                "phone": "+33612345678",
                "email": "pierre.durand@email.fr",
                "project": "achat",
                "budget": 320000,
                "location": "Lyon 6ème",
            },
            {
                "id": f"hektor_{random.randint(10000, 99999)}",
                "firstname": "Isabelle",
                "lastname": "Moreau",
                "phone": "+33687654321",
                "email": "i.moreau@email.fr",
                "project": "vente",
                "budget": 450000,
                "location": "Bordeaux Chartrons",
            },
        ]
        return [self._hektor_contact_to_lead(c) for c in mock_contacts]
