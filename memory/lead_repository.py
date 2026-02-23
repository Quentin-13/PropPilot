"""
CRUD leads + historique conversations.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from memory.database import get_connection
from memory.models import Canal, Conversation, Lead, LeadStatus, NurturingSequence, ProjetType


def _row_to_lead(row: dict) -> Lead:
    """Convertit une ligne SQLite en Lead dataclass."""
    return Lead(
        id=row["id"],
        client_id=row["client_id"],
        prenom=row.get("prenom", ""),
        nom=row.get("nom", ""),
        telephone=row.get("telephone", ""),
        email=row.get("email", ""),
        source=Canal(row.get("source", "sms")),
        projet=ProjetType(row.get("projet", "inconnu")),
        localisation=row.get("localisation", ""),
        budget=row.get("budget", ""),
        timeline=row.get("timeline", ""),
        financement=row.get("financement", ""),
        motivation=row.get("motivation", ""),
        score=row.get("score", 0),
        score_urgence=row.get("score_urgence", 0),
        score_budget=row.get("score_budget", 0),
        score_motivation=row.get("score_motivation", 0),
        statut=LeadStatus(row.get("statut", "entrant")),
        nurturing_sequence=NurturingSequence(row["nurturing_sequence"]) if row.get("nurturing_sequence") else None,
        nurturing_step=row.get("nurturing_step", 0),
        prochain_followup=datetime.fromisoformat(row["prochain_followup"]) if row.get("prochain_followup") else None,
        rdv_date=datetime.fromisoformat(row["rdv_date"]) if row.get("rdv_date") else None,
        mandat_date=datetime.fromisoformat(row["mandat_date"]) if row.get("mandat_date") else None,
        resume=row.get("resume", ""),
        notes_agent=row.get("notes_agent", ""),
        created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(),
        updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else datetime.now(),
    )


def create_lead(lead: Lead) -> Lead:
    """Insère un nouveau lead en base."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO leads
               (id, client_id, prenom, nom, telephone, email, source, projet,
                localisation, budget, timeline, financement, motivation,
                score, score_urgence, score_budget, score_motivation,
                statut, nurturing_sequence, nurturing_step,
                prochain_followup, rdv_date, mandat_date, resume, notes_agent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                lead.id, lead.client_id, lead.prenom, lead.nom,
                lead.telephone, lead.email, lead.source.value, lead.projet.value,
                lead.localisation, lead.budget, lead.timeline, lead.financement,
                lead.motivation, lead.score, lead.score_urgence, lead.score_budget,
                lead.score_motivation, lead.statut.value,
                lead.nurturing_sequence.value if lead.nurturing_sequence else None,
                lead.nurturing_step,
                lead.prochain_followup.isoformat() if lead.prochain_followup else None,
                lead.rdv_date.isoformat() if lead.rdv_date else None,
                lead.mandat_date.isoformat() if lead.mandat_date else None,
                lead.resume, lead.notes_agent,
            ),
        )
    return lead


def get_lead(lead_id: str) -> Optional[Lead]:
    """Récupère un lead par son ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(dict(row)) if row else None


def get_leads_by_client(
    client_id: str,
    statut: Optional[str] = None,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Lead]:
    """Récupère les leads d'un client avec filtres optionnels."""
    query = "SELECT * FROM leads WHERE client_id = ?"
    params: list = [client_id]

    if statut:
        query += " AND statut = ?"
        params.append(statut)
    if score_min is not None:
        query += " AND score >= ?"
        params.append(score_min)
    if score_max is not None:
        query += " AND score <= ?"
        params.append(score_max)

    query += " ORDER BY score DESC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_lead(dict(row)) for row in rows]


def update_lead(lead: Lead) -> Lead:
    """Met à jour un lead existant."""
    lead.updated_at = datetime.now()
    with get_connection() as conn:
        conn.execute(
            """UPDATE leads SET
               prenom=?, nom=?, telephone=?, email=?, source=?, projet=?,
               localisation=?, budget=?, timeline=?, financement=?, motivation=?,
               score=?, score_urgence=?, score_budget=?, score_motivation=?,
               statut=?, nurturing_sequence=?, nurturing_step=?,
               prochain_followup=?, rdv_date=?, mandat_date=?,
               resume=?, notes_agent=?, updated_at=?
               WHERE id=?""",
            (
                lead.prenom, lead.nom, lead.telephone, lead.email,
                lead.source.value, lead.projet.value, lead.localisation,
                lead.budget, lead.timeline, lead.financement, lead.motivation,
                lead.score, lead.score_urgence, lead.score_budget, lead.score_motivation,
                lead.statut.value,
                lead.nurturing_sequence.value if lead.nurturing_sequence else None,
                lead.nurturing_step,
                lead.prochain_followup.isoformat() if lead.prochain_followup else None,
                lead.rdv_date.isoformat() if lead.rdv_date else None,
                lead.mandat_date.isoformat() if lead.mandat_date else None,
                lead.resume, lead.notes_agent,
                lead.updated_at.isoformat(),
                lead.id,
            ),
        )
    return lead


def get_lead_by_phone(telephone: str, client_id: str) -> Optional[Lead]:
    """Récupère un lead par numéro de téléphone (le plus récent)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE client_id = ? AND telephone = ? ORDER BY created_at DESC LIMIT 1",
            (client_id, telephone),
        ).fetchone()
    return _row_to_lead(dict(row)) if row else None


def get_leads_for_followup(client_id: str) -> list[Lead]:
    """Leads dont le prochain follow-up est dû (maintenant ou passé)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM leads
               WHERE client_id = ?
               AND prochain_followup <= ?
               AND statut IN ('nurturing', 'qualifie')
               ORDER BY prochain_followup ASC""",
            (client_id, datetime.now().isoformat()),
        ).fetchall()
    return [_row_to_lead(dict(row)) for row in rows]


def add_conversation_message(
    lead_id: str,
    client_id: str,
    role: str,
    contenu: str,
    canal: Canal = Canal.SMS,
    metadata: Optional[dict] = None,
) -> Conversation:
    """Ajoute un message dans l'historique de conversation."""
    from uuid import uuid4
    msg = Conversation(
        id=str(uuid4()),
        lead_id=lead_id,
        client_id=client_id,
        canal=canal,
        role=role,
        contenu=contenu,
        metadata=metadata or {},
    )
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO conversations (id, lead_id, client_id, canal, role, contenu, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id, msg.lead_id, msg.client_id, msg.canal.value,
                msg.role, msg.contenu, json.dumps(msg.metadata),
            ),
        )
    return msg


def get_conversation_history(lead_id: str, limit: int = 50) -> list[Conversation]:
    """Récupère l'historique de conversation d'un lead (tri chronologique)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE lead_id = ? ORDER BY created_at ASC LIMIT ?",
            (lead_id, limit),
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        result.append(
            Conversation(
                id=d["id"],
                lead_id=d["lead_id"],
                client_id=d["client_id"],
                canal=Canal(d.get("canal", "sms")),
                role=d["role"],
                contenu=d["contenu"],
                metadata=json.loads(d.get("metadata", "{}")),
                created_at=datetime.fromisoformat(d["created_at"]),
            )
        )
    return result


def format_history_for_llm(lead_id: str, limit: int = 20) -> list[dict]:
    """Formate l'historique en messages pour l'API Anthropic/OpenAI."""
    history = get_conversation_history(lead_id, limit)
    return [{"role": msg.role, "content": msg.contenu} for msg in history]


def get_pipeline_stats(client_id: str, month: Optional[str] = None) -> dict:
    """Statistiques pipeline pour le dashboard ROI."""
    month = month or datetime.now().strftime("%Y-%m")
    with get_connection() as conn:
        stats = {}
        for statut in LeadStatus:
            count = conn.execute(
                """SELECT COUNT(*) FROM leads
                   WHERE client_id = ? AND statut = ?
                   AND strftime('%Y-%m', created_at) = ?""",
                (client_id, statut.value, month),
            ).fetchone()[0]
            stats[statut.value] = count

        # RDV bookés ce mois
        rdv_count = conn.execute(
            """SELECT COUNT(*) FROM leads
               WHERE client_id = ? AND rdv_date IS NOT NULL
               AND strftime('%Y-%m', rdv_date) = ?""",
            (client_id, month),
        ).fetchone()[0]

        # Mandats ce mois
        mandat_count = conn.execute(
            """SELECT COUNT(*) FROM leads
               WHERE client_id = ? AND statut IN ('mandat', 'vendu')
               AND strftime('%Y-%m', created_at) = ?""",
            (client_id, month),
        ).fetchone()[0]

    stats["rdv_count"] = rdv_count
    stats["mandat_count"] = mandat_count
    stats["total"] = sum(stats.get(s.value, 0) for s in LeadStatus)
    return stats
