"""
Classe de base abstraite pour tous les connecteurs CRM PropPilot.
Chaque CRM hérite de cette classe et implémente les 5 méthodes abstraites.

Design :
- Toujours retourner une réponse (jamais lever d'exception vers l'appelant)
- Si l'API est indisponible → fallback mock automatique, silencieux
- Journaliser avec préfixe [CRM_NAME]
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from memory.models import Canal, Lead, ProjetType

logger = logging.getLogger(__name__)


class BaseCRMConnector(ABC):
    """Classe abstraite pour tous les connecteurs CRM."""

    crm_name: str = ""
    api_base_url: str = ""

    def __init__(self, api_key: str, agency_id: str):
        self.api_key = api_key
        self.agency_id = agency_id
        self._mock_mode = not bool(api_key) or api_key.startswith("test_")
        if self._mock_mode:
            logger.info(f"[{self.crm_name}] Mode mock activé (pas de clé API valide)")

    # ─── Méthodes abstraites ──────────────────────────────────────────────────

    @abstractmethod
    async def test_connection(self) -> dict:
        """
        Teste la connexion à l'API du CRM.
        Retourne : {"success": bool, "message": str, "agency_name": str}
        """

    @abstractmethod
    async def get_new_leads(self, since: datetime) -> list[Lead]:
        """
        Récupère les nouveaux leads depuis une date donnée.
        Les convertit en objets Lead PropPilot standardisés.
        """

    @abstractmethod
    async def update_lead_status(self, crm_lead_id: str, status: str, notes: str) -> bool:
        """
        Met à jour le statut d'un lead dans le CRM source.
        PropPilot écrit le résultat de Léa/Marc dans le CRM client.
        status : "qualified" | "nurturing" | "not_qualified" | "appointment_booked"
        """

    @abstractmethod
    async def create_appointment(self, crm_lead_id: str, datetime_slot: datetime, agent_name: str) -> bool:
        """Crée un RDV dans le CRM source quand Sophie book un RDV."""

    @abstractmethod
    async def push_listing(self, listing_data: dict) -> str:
        """
        Pousse une annonce générée par Hugo vers le CRM.
        Retourne l'ID de l'annonce créée dans le CRM.
        """

    # ─── Utilitaires communs ──────────────────────────────────────────────────

    def normalize_project_type(self, raw: str) -> ProjetType:
        """Normalise un type de projet vers l'enum PropPilot."""
        raw_lower = (raw or "").lower().strip()
        mapping = {
            "achat": ProjetType.ACHAT,
            "buy": ProjetType.ACHAT,
            "purchase": ProjetType.ACHAT,
            "acquéreur": ProjetType.ACHAT,
            "vente": ProjetType.VENTE,
            "sell": ProjetType.VENTE,
            "sale": ProjetType.VENTE,
            "vendeur": ProjetType.VENTE,
            "location": ProjetType.LOCATION,
            "rental": ProjetType.LOCATION,
            "rent": ProjetType.LOCATION,
            "locataire": ProjetType.LOCATION,
            "estimation": ProjetType.ESTIMATION,
            "valuation": ProjetType.ESTIMATION,
        }
        return mapping.get(raw_lower, ProjetType.INCONNU)

    def format_budget(self, value) -> str:
        """Formate un budget (int/float/str) en chaîne PropPilot."""
        if value is None:
            return ""
        try:
            amount = float(str(value).replace("€", "").replace(" ", "").replace(",", "."))
            if amount <= 0:
                return ""
            formatted = f"{int(amount):,}".replace(",", " ")
            return f"{formatted}€"
        except (ValueError, TypeError):
            return str(value) if value else ""

    def inject_crm_id(self, existing_notes: str, crm_id: str) -> str:
        """Injecte le tag d'ID CRM dans notes_agent d'un Lead."""
        tag = f"[CRM:{self.crm_name.lower()}:{crm_id}]"
        if existing_notes:
            return f"{existing_notes}\n{tag}"
        return tag

    def extract_crm_id(self, notes: Optional[str]) -> Optional[str]:
        """Extrait l'ID CRM depuis le champ notes_agent d'un Lead."""
        if not notes:
            return None
        prefix = f"[CRM:{self.crm_name.lower()}:"
        if prefix in notes:
            start = notes.index(prefix) + len(prefix)
            end = notes.index("]", start)
            return notes[start:end]
        return None

    def _log(self, msg: str) -> None:
        logger.info(f"[{self.crm_name}] {msg}")
