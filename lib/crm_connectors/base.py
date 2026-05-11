"""
Interface abstraite pour les connecteurs push PropPilot → CRM.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CRMConnector(ABC):
    """
    Interface minimale push-only.

    lead_data dict attendu :
      id, client_id, prenom, nom, telephone, email,
      type_projet, budget_min, budget_max, zone, type_bien, surface_min, surface_max,
      motivation, score_label (chaud/tiede/froid), resume,
      next_action_label, next_action_reason  (peuvent être None)
    """

    connector_type: str = "unknown"

    @abstractmethod
    def push_lead(self, lead_data: dict) -> bool:
        """
        Pousse un lead vers le CRM.
        Retourne True si succès, False si échec.
        Ne lève jamais d'exception vers l'appelant.
        """

    @abstractmethod
    def test_connection(self) -> dict:
        """
        Teste la connexion CRM.
        Retourne {"success": bool, "message": str}.
        """
