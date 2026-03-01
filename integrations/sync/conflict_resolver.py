"""
Résolution de conflits et dédoublonnage de leads.
Détecte les doublons (même téléphone ou email) et les fusionne ou ignore.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from memory.database import get_connection
from memory.lead_repository import get_lead_by_phone, update_lead
from memory.models import Lead

logger = logging.getLogger(__name__)


def find_duplicate(lead: Lead) -> Optional[Lead]:
    """
    Cherche un lead existant avec le même téléphone ou email.
    Retourne le lead existant ou None.
    """
    # Priorité : téléphone (identifiant fort)
    if lead.telephone:
        existing = get_lead_by_phone(lead.telephone, lead.client_id)
        if existing:
            return existing

    # Fallback : email
    if lead.email:
        existing = _find_by_email(lead.email, lead.client_id)
        if existing:
            return existing

    return None


def merge_leads(existing: Lead, incoming: Lead) -> Lead:
    """
    Fusionne un lead entrant dans un lead existant.
    Règle : enrichir sans écraser (les champs vides sont complétés).
    """
    # Enrichir les champs vides de l'existant avec les données entrantes
    if not existing.prenom and incoming.prenom:
        existing.prenom = incoming.prenom
    if not existing.nom and incoming.nom:
        existing.nom = incoming.nom
    if not existing.email and incoming.email:
        existing.email = incoming.email
    if not existing.localisation and incoming.localisation:
        existing.localisation = incoming.localisation
    if not existing.budget and incoming.budget:
        existing.budget = incoming.budget

    # Ajouter les notes CRM entrantes
    if incoming.notes_agent and incoming.notes_agent not in (existing.notes_agent or ""):
        existing.notes_agent = (
            f"{existing.notes_agent}\n{incoming.notes_agent}"
            if existing.notes_agent
            else incoming.notes_agent
        )

    existing.updated_at = datetime.now()
    update_lead(existing)
    logger.info(f"[ConflictResolver] Lead {existing.id} enrichi depuis {incoming.notes_agent or 'import'}")
    return existing


def resolve(lead: Lead) -> tuple[Lead, bool]:
    """
    Point d'entrée principal.
    Retourne (lead_final, is_duplicate).
    Si doublon détecté : fusionne et retourne l'existant enrichi.
    Sinon : retourne le lead entrant tel quel.
    """
    existing = find_duplicate(lead)
    if existing:
        merged = merge_leads(existing, lead)
        return merged, True
    return lead, False


def get_duplicate_stats(client_id: str) -> dict:
    """Statistiques de doublons pour le dashboard admin."""
    with get_connection() as conn:
        # Leads avec le même téléphone
        phone_dupes = conn.execute(
            """SELECT telephone, COUNT(*) as cnt
               FROM leads
               WHERE client_id = ? AND telephone != ''
               GROUP BY telephone HAVING COUNT(*) > 1""",
            (client_id,),
        ).fetchall()

        email_dupes = conn.execute(
            """SELECT email, COUNT(*) as cnt
               FROM leads
               WHERE client_id = ? AND email != ''
               GROUP BY email HAVING COUNT(*) > 1""",
            (client_id,),
        ).fetchall()

    return {
        "phone_duplicates": len(phone_dupes),
        "email_duplicates": len(email_dupes),
        "total_duplicate_groups": len(phone_dupes) + len(email_dupes),
    }


def _find_by_email(email: str, client_id: str) -> Optional[Lead]:
    """Cherche un lead par email dans la DB."""
    from memory.lead_repository import _row_to_lead  # type: ignore
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE client_id = ? AND email = ? ORDER BY created_at DESC LIMIT 1",
            (client_id, email),
        ).fetchone()
    if not row:
        return None
    try:
        return _row_to_lead(row)
    except Exception:
        return None
