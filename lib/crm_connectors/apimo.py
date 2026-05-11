"""
Connecteur push PropPilot → Apimo CRM.

- Authentification Bearer token (provider_id + token stockés dans crm_config)
- Endpoint contact : POST /providers/{provider_id}/contacts
- Endpoint note    : POST /providers/{provider_id}/contacts/{id}/notes
- Retry 3x avec backoff exponentiel sur erreurs réseau
- 401 → pas de retry, remonte immédiatement l'erreur
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from lib.crm_connectors.base import CRMConnector

logger = logging.getLogger(__name__)

APIMO_API_BASE = "https://api.apimo.pro"
_RETRY_DELAYS = (1, 3, 9)


class ApimoConnector(CRMConnector):
    """Push-only connector PropPilot → Apimo."""

    connector_type = "apimo"

    def __init__(self, provider_id: str, api_token: str):
        self._provider_id = provider_id
        self._api_token = api_token
        self._mock = not (provider_id and api_token) or api_token.startswith("test_")
        if self._mock:
            logger.info("[Apimo] Mode mock activé (clé absente ou préfixe test_)")

    # ─── Interface publique ────────────────────────────────────────────────────

    def push_lead(self, lead_data: dict) -> bool:
        from lib.crm_connectors.apimo_mapping import build_contact_payload, build_note_text

        if self._mock:
            mock_id = f"APM-{(lead_data.get('id') or 'MOCK')[:8].upper()}"
            logger.info(
                "[MOCK][Apimo] push_lead → %s (%s %s)",
                mock_id, lead_data.get("prenom"), lead_data.get("nom"),
            )
            return True

        try:
            contact_payload = build_contact_payload(lead_data)
            apimo_id = self._create_contact(contact_payload)
            if apimo_id:
                note_text = build_note_text(lead_data)
                self._add_note(apimo_id, note_text)
            logger.info("[Apimo] Lead pushé OK → contact %s", apimo_id)
            return True
        except _AuthError as e:
            logger.error("[Apimo] Auth échouée : %s", e)
            return False
        except Exception as e:
            logger.error("[Apimo] push_lead échoué : %s", e)
            return False

    def test_connection(self) -> dict:
        if self._mock:
            return {"success": True, "message": "[MOCK] Connexion Apimo simulée"}
        try:
            import httpx
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    f"{APIMO_API_BASE}/providers/{self._provider_id}",
                    headers=self._headers(),
                )
            if r.status_code == 200:
                name = r.json().get("name", "Agence Apimo")
                return {"success": True, "message": f"Connexion OK — {name}"}
            if r.status_code == 401:
                return {"success": False, "message": "Clé API invalide (401 Unauthorized)"}
            return {"success": False, "message": f"Erreur HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "message": f"Erreur réseau : {e}"}

    # ─── Appels API internes ───────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _create_contact(self, payload: dict) -> Optional[str]:
        import httpx
        url = f"{APIMO_API_BASE}/providers/{self._provider_id}/contacts"
        last_exc: Exception = Exception("Toutes les tentatives ont échoué")

        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                with httpx.Client(timeout=15) as client:
                    r = client.post(url, headers=self._headers(), json=payload)
                if r.status_code == 401:
                    raise _AuthError(f"401 Unauthorized — provider_id={self._provider_id}")
                if r.status_code in (200, 201):
                    return str(r.json().get("id", ""))
                logger.warning(
                    "[Apimo] create_contact HTTP %s — tentative %d/%d",
                    r.status_code, attempt + 1, len(_RETRY_DELAYS),
                )
                last_exc = Exception(f"HTTP {r.status_code}")
            except _AuthError:
                raise
            except Exception as e:
                logger.warning("[Apimo] create_contact erreur réseau tentative %d: %s", attempt + 1, e)
                last_exc = e
            if attempt < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)

        raise last_exc

    def _add_note(self, contact_id: str, note: str) -> None:
        import httpx
        url = f"{APIMO_API_BASE}/providers/{self._provider_id}/contacts/{contact_id}/notes"

        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                with httpx.Client(timeout=15) as client:
                    r = client.post(url, headers=self._headers(), json={"content": note})
                if r.status_code == 401:
                    raise _AuthError("401 — note non autorisée")
                if r.status_code in (200, 201, 204):
                    return
                logger.warning(
                    "[Apimo] add_note HTTP %s — tentative %d/%d",
                    r.status_code, attempt + 1, len(_RETRY_DELAYS),
                )
            except _AuthError:
                raise
            except Exception as e:
                logger.warning("[Apimo] add_note erreur réseau tentative %d: %s", attempt + 1, e)
            if attempt < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)


class _AuthError(Exception):
    pass
