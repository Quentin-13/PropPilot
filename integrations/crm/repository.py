"""
Repository CRM — CRUD pour la table crm_connections.
Utilisé par le dashboard Settings et le scheduler de sync.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from memory.database import get_connection


def save_crm_connection(
    client_id: str,
    crm_type: str,
    api_key: str,
    agency_id_crm: str = "",
    sync_leads: bool = True,
    sync_rdv: bool = True,
    sync_listings: bool = True,
) -> dict:
    """Upsert une connexion CRM pour un client."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO crm_connections
               (client_id, crm_type, api_key, agency_id_crm,
                enabled, sync_leads, sync_rdv, sync_listings, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(client_id, crm_type) DO UPDATE SET
                   api_key = excluded.api_key,
                   agency_id_crm = excluded.agency_id_crm,
                   enabled = 1,
                   sync_leads = excluded.sync_leads,
                   sync_rdv = excluded.sync_rdv,
                   sync_listings = excluded.sync_listings,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                client_id, crm_type, api_key, agency_id_crm,
                int(sync_leads), int(sync_rdv), int(sync_listings),
            ),
        )
    return get_crm_connection(client_id, crm_type) or {}


def get_crm_connection(client_id: str, crm_type: str) -> Optional[dict]:
    """Retourne la config d'une connexion CRM, ou None si inexistante."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM crm_connections WHERE client_id = ? AND crm_type = ? AND enabled = 1",
            (client_id, crm_type),
        ).fetchone()
    return dict(row) if row else None


def get_all_crm_connections(client_id: str) -> list[dict]:
    """Retourne toutes les connexions CRM actives d'un client."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM crm_connections WHERE client_id = ? AND enabled = 1",
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_active_connections() -> list[dict]:
    """Retourne toutes les connexions actives (tous clients — usage scheduler)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM crm_connections WHERE enabled = 1",
        ).fetchall()
    return [dict(r) for r in rows]


def update_last_sync(client_id: str, crm_type: str) -> None:
    """Met à jour le timestamp de dernière synchronisation."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE crm_connections
               SET last_sync = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE client_id = ? AND crm_type = ?""",
            (client_id, crm_type),
        )


def disable_crm_connection(client_id: str, crm_type: str) -> None:
    """Désactive (soft-delete) une connexion CRM."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE crm_connections SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE client_id = ? AND crm_type = ?",
            (client_id, crm_type),
        )
