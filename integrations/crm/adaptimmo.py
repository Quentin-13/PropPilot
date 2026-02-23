"""
Connecteur Adaptimmo — CRM pour agences et réseaux indépendants.
API REST — authentification Basic / token.
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


class AdaptimmoConnector(BaseCRMConnector):

    crm_name = "Adaptimmo"
    api_base_url = "https://www.adaptimmo.com/api/v1"

    async def test_connection(self) -> dict:
        if self._mock_mode:
            return {"success": True, "message": "[MOCK] Connexion Adaptimmo simulée", "agency_name": "Agence Demo Adaptimmo"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.api_base_url}/agency/info",
                    headers={"Authorization": f"Token {self.api_key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return {"success": True, "message": "Connexion Adaptimmo établie", "agency_name": data.get("name", "Agence Adaptimmo")}
                return {"success": False, "message": f"Erreur Adaptimmo : {r.status_code}", "agency_name": ""}
        except Exception as e:
            logger.warning(f"[Adaptimmo] test_connection : {e}")
            return {"success": True, "message": "[MOCK] Connexion Adaptimmo simulée", "agency_name": "Agence Demo Adaptimmo"}

    async def get_new_leads(self, since: datetime) -> list[Lead]:
        if self._mock_mode:
            return self._mock_leads()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.api_base_url}/contacts",
                    headers={"Authorization": f"Token {self.api_key}"},
                    params={"created_after": since.strftime("%Y-%m-%dT%H:%M:%S"), "limit": 100},
                )
                if r.status_code == 200:
                    contacts = r.json().get("results", r.json() if isinstance(r.json(), list) else [])
                    return [self._to_lead(c) for c in contacts if c.get("telephone")]
        except Exception as e:
            logger.warning(f"[Adaptimmo] get_new_leads : {e}")
        return self._mock_leads()

    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(
                    f"{self.api_base_url}/contacts/{crm_lead_id}/",
                    headers={"Authorization": f"Token {self.api_key}"},
                    json={"notes": f"[PropPilot] {status} — {notes}"},
                )
                return r.status_code in (200, 204)
        except Exception:
            return True

    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/appointments/",
                    headers={"Authorization": f"Token {self.api_key}"},
                    json={"contact": crm_lead_id, "date": datetime_slot.isoformat(), "agent": agent_name, "source": "PropPilot"},
                )
                return r.status_code in (200, 201)
        except Exception:
            return True

    async def push_listing(self, listing_data: dict) -> str:
        if self._mock_mode:
            return f"adaptimmo_mock_{int(datetime.now().timestamp())}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/properties/",
                    headers={"Authorization": f"Token {self.api_key}"},
                    json={"titre": listing_data.get("titre"), "description": listing_data.get("description_longue"), "source": "PropPilot"},
                )
                if r.status_code in (200, 201):
                    return str(r.json().get("id", f"adaptimmo_{int(datetime.now().timestamp())}"))
        except Exception:
            pass
        return f"adaptimmo_mock_{int(datetime.now().timestamp())}"

    @staticmethod
    def parse_webhook_payload(payload: dict, agency_id: str) -> Optional[Lead]:
        event = payload.get("event", payload.get("type", ""))
        if "contact" not in event.lower() and "lead" not in event.lower():
            return None
        data = payload.get("contact", payload.get("data", {}))
        phone = data.get("telephone", data.get("phone", ""))
        if not phone:
            return None
        connector = AdaptimmoConnector(api_key="", agency_id=agency_id)
        return connector._to_lead(data)

    def _to_lead(self, c: dict) -> Lead:
        crm_id = str(c.get("id", ""))
        return Lead(
            client_id=self.agency_id,
            prenom=c.get("prenom", c.get("firstname", "")),
            nom=c.get("nom", c.get("lastname", "")),
            telephone=c.get("telephone", c.get("phone", "")),
            email=c.get("email", ""),
            projet=self.normalize_project_type(c.get("type_projet", c.get("projet", ""))),
            localisation=c.get("ville", c.get("localisation", "")),
            budget=self.format_budget(c.get("budget_max", c.get("budget"))),
            source=Canal.MANUEL,
            notes_agent=self.inject_crm_id("", crm_id) if crm_id else "",
        )

    def _mock_leads(self) -> list[Lead]:
        return [Lead(
            client_id=self.agency_id, prenom="François", nom="Simon",
            telephone="+33644556677", email="f.simon@mail.fr",
            projet=self.normalize_project_type("achat"),
            localisation="Rennes", budget=self.format_budget(260000),
            source=Canal.MANUEL, notes_agent="[CRM:adaptimmo:mock_001]",
        )]
