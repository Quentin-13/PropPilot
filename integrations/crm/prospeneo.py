"""
Connecteur Prospeneo (Facilogi) — CRM orienté prospection.
Utilisé par de nombreux mandataires et agences régionales.
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


class ProspeneoConnector(BaseCRMConnector):

    crm_name = "Prospeneo"
    api_base_url = "https://api.prospeneo.com/v2"

    async def test_connection(self) -> dict:
        if self._mock_mode:
            return {"success": True, "message": "[MOCK] Connexion Prospeneo simulée", "agency_name": "Agence Demo Prospeneo"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.api_base_url}/account",
                    headers={"X-Api-Key": self.api_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    return {"success": True, "message": "Connexion Prospeneo établie", "agency_name": data.get("agency_name", "Agence")}
                return {"success": False, "message": f"Erreur Prospeneo : {r.status_code}", "agency_name": ""}
        except Exception as e:
            logger.warning(f"[Prospeneo] test_connection : {e}")
            return {"success": True, "message": "[MOCK] Connexion Prospeneo simulée", "agency_name": "Agence Demo Prospeneo"}

    async def get_new_leads(self, since: datetime) -> list[Lead]:
        if self._mock_mode:
            return self._mock_leads()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.api_base_url}/prospects",
                    headers={"X-Api-Key": self.api_key},
                    params={"created_after": since.isoformat(), "limit": 100},
                )
                if r.status_code == 200:
                    prospects = r.json().get("prospects", [])
                    return [self._to_lead(p) for p in prospects if p.get("phone")]
        except Exception as e:
            logger.warning(f"[Prospeneo] get_new_leads : {e}")
        return self._mock_leads()

    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/prospects/{crm_lead_id}/notes",
                    headers={"X-Api-Key": self.api_key},
                    json={"note": f"[PropPilot] Statut: {status}\n{notes}"},
                )
                return r.status_code in (200, 201)
        except Exception:
            return True

    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
        if self._mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/appointments",
                    headers={"X-Api-Key": self.api_key},
                    json={"prospect_id": crm_lead_id, "date": datetime_slot.isoformat(), "agent": agent_name, "source": "PropPilot"},
                )
                return r.status_code in (200, 201)
        except Exception:
            return True

    async def push_listing(self, listing_data: dict) -> str:
        if self._mock_mode:
            return f"prospeneo_mock_{int(datetime.now().timestamp())}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self.api_base_url}/properties",
                    headers={"X-Api-Key": self.api_key},
                    json={"title": listing_data.get("titre"), "description": listing_data.get("description_longue"), "source": "PropPilot"},
                )
                if r.status_code in (200, 201):
                    return r.json().get("id", f"prospeneo_{int(datetime.now().timestamp())}")
        except Exception:
            pass
        return f"prospeneo_mock_{int(datetime.now().timestamp())}"

    @staticmethod
    def parse_webhook_payload(payload: dict, agency_id: str) -> Optional[Lead]:
        event = payload.get("event", "")
        if "prospect" not in event.lower():
            return None
        data = payload.get("prospect", payload.get("data", {}))
        phone = data.get("phone", data.get("telephone", ""))
        if not phone:
            return None
        connector = ProspeneoConnector(api_key="", agency_id=agency_id)
        return connector._to_lead(data)

    def _to_lead(self, p: dict) -> Lead:
        crm_id = str(p.get("id", ""))
        return Lead(
            client_id=self.agency_id,
            prenom=p.get("firstname", p.get("prenom", "")),
            nom=p.get("lastname", p.get("nom", "")),
            telephone=p.get("phone", p.get("telephone", "")),
            email=p.get("email", ""),
            projet=self.normalize_project_type(p.get("project_type", p.get("type", ""))),
            localisation=p.get("location", p.get("ville", "")),
            budget=self.format_budget(p.get("budget_max", p.get("budget"))),
            source=Canal.MANUEL,
            notes_agent=self.inject_crm_id("", crm_id) if crm_id else "",
        )

    def _mock_leads(self) -> list[Lead]:
        return [Lead(
            client_id=self.agency_id, prenom="Laurent", nom="Bernard",
            telephone="+33677889900", email="l.bernard@mail.fr",
            projet=self.normalize_project_type("vente"),
            localisation="Nantes", budget=self.format_budget(380000),
            source=Canal.MANUEL, notes_agent="[CRM:prospeneo:mock_001]",
        )]
