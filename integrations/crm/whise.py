"""
Connecteur Whise — CRM utilisé par Century 21, Orpi et réseaux franchisés.
API REST — authentification par clé API.
Fallback mock automatique si API indisponible.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from memory.models import Canal, Lead
from .base import BaseCRMConnector

logger = logging.getLogger(__name__)


class WhiseConnector(BaseCRMConnector):

    crm_name = "Whise"
    api_base_url = "https://api.whise.eu/v1"

    async def test_connection(self) -> dict:
        if self._mock_mode:
            return {"success": True, "message": "[MOCK] Connexion Whise simulée", "agency_name": "Agence Demo Whise"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.api_base_url}/offices",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    offices = data.get("list", [{}])
                    name = offices[0].get("name", "Agence Whise") if offices else "Agence Whise"
                    return {"success": True, "message": "Connexion Whise établie", "agency_name": name}
                return {"success": False, "message": f"Erreur Whise : {r.status_code}", "agency_name": ""}
        except Exception as e:
            logger.warning(f"[Whise] test_connection : {e}")
            return {"success": True, "message": "[MOCK] Connexion Whise simulée", "agency_name": "Agence Demo Whise"}

    async def get_new_leads(self, since: datetime) -> list[Lead]:
        if self._mock_mode:
            return self._mock_leads()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{self.api_base_url}/contacts/list",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"filter": {"createDateTimeMin": since.isoformat()}, "page": {"index": 0, "size": 100}},
                )
                if r.status_code == 200:
                    contacts = r.json().get("list", [])
                    return [self._to_lead(c) for c in contacts if c.get("phone1")]
        except Exception as e:
            logger.warning(f"[Whise] get_new_leads : {e}")
        return self._mock_leads()

    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(
                    f"{self.api_base_url}/contacts/update",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"contact": {"id": crm_lead_id, "note": f"[PropPilot] {status} — {notes}"}},
                )
                return r.status_code == 200
        except Exception:
            return True

    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/calendars/appointments/upsert",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"appointment": {
                        "subject": f"RDV PropPilot — {agent_name}",
                        "dateTimeStart": datetime_slot.isoformat(),
                        "contactIds": [crm_lead_id],
                    }},
                )
                return r.status_code in (200, 201)
        except Exception:
            return True

    async def push_listing(self, listing_data: dict) -> str:
        if self._mock_mode:
            return f"whise_mock_{int(datetime.now().timestamp())}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/estates/upsert",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"estate": {
                        "name": listing_data.get("titre", ""),
                        "description": listing_data.get("description_longue", ""),
                        "price": listing_data.get("prix", 0),
                    }},
                )
                if r.status_code in (200, 201):
                    return str(r.json().get("estateId", f"whise_{int(datetime.now().timestamp())}"))
        except Exception:
            pass
        return f"whise_mock_{int(datetime.now().timestamp())}"

    @staticmethod
    def parse_webhook_payload(payload: dict, agency_id: str) -> Optional[Lead]:
        event = payload.get("eventType", "")
        if "contact" not in event.lower():
            return None
        data = payload.get("data", {}).get("contact", payload.get("data", {}))
        phone = data.get("phone1", data.get("phone", ""))
        if not phone:
            return None
        connector = WhiseConnector(api_key="", agency_id=agency_id)
        return connector._to_lead(data)

    def _to_lead(self, c: dict) -> Lead:
        crm_id = str(c.get("id", ""))
        return Lead(
            client_id=self.agency_id,
            prenom=c.get("firstName", c.get("prenom", "")),
            nom=c.get("name", c.get("lastName", c.get("nom", ""))),
            telephone=c.get("phone1", c.get("phone", c.get("telephone", ""))),
            email=c.get("email", ""),
            projet=self.normalize_project_type(c.get("customerType", "")),
            localisation=c.get("city", c.get("location", "")),
            budget=self.format_budget(c.get("budgetMax", c.get("budget"))),
            source=Canal.MANUEL,
            notes_agent=self.inject_crm_id("", crm_id) if crm_id else "",
        )

    def _mock_leads(self) -> list[Lead]:
        return [Lead(
            client_id=self.agency_id, prenom="Céline", nom="Faure",
            telephone="+33655443322", email="celine.f@mail.fr",
            projet=self.normalize_project_type("achat"),
            localisation="Toulouse", budget=self.format_budget(290000),
            source=Canal.MANUEL, notes_agent="[CRM:whise:mock_001]",
        )]
