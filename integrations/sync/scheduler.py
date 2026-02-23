"""
Synchronisation automatique PropPilot ↔ CRM clients.
Lance une sync toutes les 15 minutes pour chaque client avec CRM connecté.

Démarrage standalone :
    python -m integrations.sync.scheduler
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from memory.lead_repository import create_lead, get_lead_by_phone
from integrations.crm.repository import get_all_active_connections, update_last_sync

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 900  # 15 minutes


def get_connector(crm_type: str, api_key: str, agency_id: str):
    """Factory — retourne le bon connecteur selon le type CRM."""
    from integrations.crm.hektor import HektorConnector
    from integrations.crm.apimo import ApimoCRMConnector
    from integrations.crm.prospeneo import ProspeneoConnector
    from integrations.crm.whise import WhiseConnector
    from integrations.crm.adaptimmo import AdaptimmoConnector

    connectors = {
        "hektor": HektorConnector,
        "apimo": ApimoCRMConnector,
        "prospeneo": ProspeneoConnector,
        "whise": WhiseConnector,
        "adaptimmo": AdaptimmoConnector,
    }
    cls = connectors.get(crm_type.lower())
    if not cls:
        raise ValueError(f"CRM non supporté : {crm_type}")
    return cls(api_key=api_key, agency_id=agency_id)


async def sync_client(connection: dict) -> dict:
    """
    Synchronise un client PropPilot avec son CRM configuré.
    Retourne un rapport de sync.
    """
    client_id = connection["client_id"]
    crm_type = connection["crm_type"]
    api_key = connection.get("api_key", "")
    agency_id_crm = connection.get("agency_id_crm", client_id)

    report = {
        "client_id": client_id,
        "crm_type": crm_type,
        "new_leads": 0,
        "skipped": 0,
        "errors": [],
    }

    try:
        connector = get_connector(crm_type, api_key, agency_id_crm)

        # Fenêtre de sync : depuis last_sync ou 24h en arrière
        last_sync_str = connection.get("last_sync")
        if last_sync_str:
            try:
                since = datetime.fromisoformat(str(last_sync_str))
            except (ValueError, TypeError):
                since = datetime.now() - timedelta(hours=24)
        else:
            since = datetime.now() - timedelta(hours=24)

        # Récupérer les nouveaux leads
        new_leads = await connector.get_new_leads(since)
        logger.info(f"[Scheduler] {crm_type}/{client_id} : {len(new_leads)} leads candidats")

        for lead in new_leads:
            try:
                # Dédoublonnage par téléphone
                if lead.telephone:
                    existing = get_lead_by_phone(lead.telephone, client_id)
                    if existing:
                        report["skipped"] += 1
                        continue

                lead.client_id = client_id
                create_lead(lead)
                report["new_leads"] += 1

            except Exception as e:
                report["errors"].append(str(e))

        # Mettre à jour le timestamp de sync
        update_last_sync(client_id, crm_type)
        logger.info(
            f"[Scheduler] {crm_type}/{client_id} : "
            f"{report['new_leads']} importés, {report['skipped']} doublons"
        )

    except Exception as e:
        error_msg = f"Erreur sync {crm_type}/{client_id} : {e}"
        logger.error(f"[Scheduler] {error_msg}")
        report["errors"].append(error_msg)

    return report


async def sync_all_clients() -> list[dict]:
    """
    Pour chaque client PropPilot avec un CRM connecté :
    1. Récupère les leads créés depuis la dernière sync
    2. Dédoublonne et insère en DB
    3. Met à jour le timestamp de sync
    """
    try:
        connections = get_all_active_connections()
    except Exception as e:
        logger.error(f"[Scheduler] Impossible de lire crm_connections : {e}")
        return []

    if not connections:
        logger.info("[Scheduler] Aucune connexion CRM active")
        return []

    reports = []
    for connection in connections:
        report = await sync_client(connection)
        reports.append(report)

    total_new = sum(r["new_leads"] for r in reports)
    logger.info(f"[Scheduler] Cycle terminé : {len(connections)} CRM, {total_new} nouveaux leads")
    return reports


async def run_scheduler() -> None:
    """Lance la sync automatique toutes les 15 minutes."""
    logger.info(f"[Scheduler] Démarrage — cycle toutes les {SYNC_INTERVAL_SECONDS}s")
    while True:
        try:
            await sync_all_clients()
        except Exception as e:
            logger.error(f"[Scheduler] Erreur cycle : {e}")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
    asyncio.run(run_scheduler())
