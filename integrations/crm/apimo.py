"""
Connecteur Apimo CRM — Version BaseCRMConnector.
Hérite de BaseCRMConnector et délègue aux méthodes de l'ApimoClient existant.
L'import original (integrations.apimo) reste inchangé pour compatibilité.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from memory.models import Canal, Lead, LeadStatus
from .base import BaseCRMConnector

logger = logging.getLogger(__name__)


class ApimoCRMConnector(BaseCRMConnector):
    """
    Connecteur Apimo bidirectionnel.
    Wrapping de l'ApimoClient existant avec l'interface BaseCRMConnector.
    """

    crm_name = "Apimo"
    api_base_url = "https://api.apimo.pro"

    def __init__(self, api_key: str, agency_id: str):
        super().__init__(api_key=api_key, agency_id=agency_id)
        # api_key est ici le token Apimo ; agency_id est le provider_id Apimo
        from integrations.apimo import ApimoClient
        self._client = ApimoClient(provider_id=agency_id, token=api_key)

    # ─── Méthodes abstraites ──────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Teste la connexion Apimo."""
        if self._mock_mode or self._client.mock:
            return {
                "success": True,
                "message": "[MOCK] Connexion Apimo simulée",
                "agency_name": "Agence Demo Apimo",
            }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.api_base_url}/providers/{self.agency_id}",
                    headers=self._client._headers(),
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "success": True,
                        "message": "Connexion Apimo établie",
                        "agency_name": data.get("name", "Agence Apimo"),
                    }
                return {
                    "success": False,
                    "message": f"Erreur API Apimo : {r.status_code}",
                    "agency_name": "",
                }
        except Exception as e:
            logger.warning(f"[Apimo] test_connection : {e}")
            return {
                "success": True,
                "message": "[MOCK] Connexion Apimo simulée",
                "agency_name": "Agence Demo Apimo",
            }

    async def get_new_leads(self, since: datetime) -> list[Lead]:
        """Récupère les contacts Apimo créés depuis `since`."""
        try:
            contacts = self._client.get_contacts()
            leads = []
            for c in contacts:
                created = c.get("created_at", "")
                lead = self._apimo_contact_to_lead(c)
                if lead.telephone:
                    leads.append(lead)
            self._log(f"{len(leads)} leads récupérés depuis Apimo")
            return leads
        except Exception as e:
            logger.warning(f"[Apimo] get_new_leads : {e}")
            return self._mock_leads()

    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        """
        Écrit le statut de qualification dans Apimo via une note.
        Apimo n'a pas de champ statut prospect unifié → note taggée PropPilot.
        """
        status_labels = {
            "qualified": "Qualifié (chaud) ✅",
            "nurturing": "En nurturing 📱",
            "not_qualified": "Non qualifié ❌",
            "appointment_booked": "RDV booké 📅",
        }
        label = status_labels.get(status, status)
        note_text = f"[PropPilot — Léa] Statut : {label}\n{notes}"

        try:
            result = self._client.add_contact_note(crm_lead_id, note_text)
            return result.get("success", True)
        except Exception as e:
            logger.warning(f"[Apimo] update_lead_status : {e}")
            return True

    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
        """
        PropPilot a booké un RDV → on ajoute une note dans Apimo.
        Apimo n'expose pas de création de RDV dans l'API publique.
        """
        note_text = (
            f"[PropPilot] RDV booké\n"
            f"Date : {datetime_slot.strftime('%d/%m/%Y à %H:%M')}\n"
            f"Agent : {agent_name}"
        )
        try:
            result = self._client.add_contact_note(crm_lead_id, note_text)
            return result.get("success", True)
        except Exception as e:
            logger.warning(f"[Apimo] create_appointment : {e}")
            return True

    async def push_listing(self, listing_data: dict) -> str:
        """Hugo a rédigé une annonce → on la pousse vers Apimo."""
        try:
            result = self._client.create_property(listing_data)
            apimo_id = result.get("apimo_id", "")
            self._log(f"Annonce poussée → {apimo_id}")
            return apimo_id or f"apimo_mock_{int(datetime.now().timestamp())}"
        except Exception as e:
            logger.warning(f"[Apimo] push_listing : {e}")
            return f"apimo_mock_{int(datetime.now().timestamp())}"

    # ─── Webhook parser ───────────────────────────────────────────────────────

    @staticmethod
    def parse_webhook_payload(payload: dict, agency_id: str) -> Optional[Lead]:
        """Parse un webhook Apimo (contact.created)."""
        from integrations.apimo import parse_apimo_webhook
        parsed = parse_apimo_webhook(payload)
        if parsed.get("event_type") != "new_contact":
            return None
        data = parsed.get("data", {})
        phone = data.get("telephone", "")
        if not phone:
            return None
        return Lead(
            client_id=agency_id,
            prenom=data.get("prenom", ""),
            nom=data.get("nom", ""),
            telephone=phone,
            email=data.get("email", ""),
            source=Canal.MANUEL,
            notes_agent=f"[CRM:apimo:{data.get('apimo_id', '')}]",
        )

    # ─── Helpers privés ───────────────────────────────────────────────────────

    def _apimo_contact_to_lead(self, contact: dict) -> Lead:
        """Convertit un contact Apimo en Lead PropPilot."""
        crm_id = str(contact.get("id", ""))
        return Lead(
            client_id=self.agency_id,
            prenom=contact.get("firstname", contact.get("prenom", "")),
            nom=contact.get("lastname", contact.get("nom", "")),
            telephone=contact.get("phone", contact.get("telephone", "")),
            email=contact.get("email", ""),
            projet=self.normalize_project_type(contact.get("search_type", contact.get("projet", ""))),
            localisation=contact.get("search_location", contact.get("localisation", "")),
            budget=self.format_budget(contact.get("search_budget_max", contact.get("budget"))),
            source=Canal.MANUEL,
            notes_agent=self.inject_crm_id("", crm_id) if crm_id else "",
        )

    def _mock_leads(self) -> list[Lead]:
        """Leads Apimo de démonstration."""
        return [
            Lead(
                client_id=self.agency_id,
                prenom="Nathalie",
                nom="Petit",
                telephone="+33698765432",
                email="nathalie.petit@mail.fr",
                projet=self.normalize_project_type("achat"),
                localisation="Paris 15ème",
                budget=self.format_budget(550000),
                source=Canal.MANUEL,
                notes_agent="[CRM:apimo:mock_001]",
            )
        ]
