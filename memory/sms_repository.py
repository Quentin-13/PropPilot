"""
Helpers SMS — accès direct à la base de données (utilisés par le dashboard Streamlit).
"""
from __future__ import annotations

import json
from typing import Optional

from memory.database import get_connection


def get_sms_threads(client_id: str, limit: int = 100) -> list[dict]:
    """Retourne les threads SMS d'un client, triés par dernier message desc.

    Même query que GET /api/sms/conversations (server.py).
    """
    if limit > 500:
        limit = 500

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                l.id               AS lead_id,
                l.prenom,
                l.nom,
                l.telephone,
                l.score,
                l.statut,
                l.projet,
                l.localisation,
                l.budget,
                last_c.contenu     AS dernier_message,
                last_c.role        AS dernier_message_role,
                last_c.created_at  AS dernier_message_at,
                counts.nb_messages_total,
                counts.nb_non_lus,
                calls_agg.dernier_appel_at
            FROM leads l
            INNER JOIN (
                SELECT
                    lead_id,
                    COUNT(*) AS nb_messages_total,
                    SUM(CASE WHEN role = 'user' AND read_at IS NULL THEN 1 ELSE 0 END) AS nb_non_lus
                FROM conversations
                WHERE client_id = %s AND canal = 'sms'
                GROUP BY lead_id
            ) counts ON counts.lead_id = l.id
            INNER JOIN LATERAL (
                SELECT contenu, role, created_at
                FROM conversations
                WHERE lead_id = l.id AND client_id = %s AND canal = 'sms'
                ORDER BY created_at DESC
                LIMIT 1
            ) last_c ON TRUE
            LEFT JOIN (
                SELECT lead_id, MAX(created_at) AS dernier_appel_at
                FROM calls
                WHERE client_id = %s
                GROUP BY lead_id
            ) calls_agg ON calls_agg.lead_id = l.id
            WHERE l.client_id = %s
            ORDER BY last_c.created_at DESC
            LIMIT %s
            """,
            (client_id, client_id, client_id, client_id, limit),
        ).fetchall()

    threads = []
    for row in rows:
        d = dict(row)
        projet = d.get("projet") or ""
        localisation = d.get("localisation") or ""
        budget_texte = d.get("budget") or ""
        if projet or localisation or budget_texte:
            extraction_resume = {
                "budget": budget_texte if budget_texte else None,
                "budget_min": None,
                "budget_max": None,
                "type_bien": projet if projet else None,
                "zone": localisation if localisation else None,
            }
        else:
            extraction_resume = None

        dernier = d.get("dernier_message") or ""
        threads.append({
            "lead_id": d["lead_id"],
            "prenom": d.get("prenom") or "",
            "nom": d.get("nom") or "",
            "telephone": d.get("telephone") or "",
            "score": d.get("score"),
            "statut": d.get("statut"),
            "dernier_message": dernier[:100],
            "dernier_message_role": d.get("dernier_message_role"),
            "dernier_message_at": d["dernier_message_at"].isoformat() if d.get("dernier_message_at") else None,
            "nb_messages_total": int(d.get("nb_messages_total") or 0),
            "nb_non_lus": int(d.get("nb_non_lus") or 0),
            "dernier_appel_at": d["dernier_appel_at"].isoformat() if d.get("dernier_appel_at") else None,
            "extraction_resume": extraction_resume,
        })

    return threads


def get_thread_messages(client_id: str, lead_id: str) -> dict:
    """Retourne le lead + liste des messages d'un thread SMS.

    Retourne {} si le lead n'existe pas ou n'appartient pas au client.
    Même structure que GET /api/leads/{lead_id}/conversations.
    """
    with get_connection() as conn:
        lead_row = conn.execute(
            "SELECT id, prenom, nom, telephone, score, statut "
            "FROM leads WHERE id = %s AND client_id = %s LIMIT 1",
            (lead_id, client_id),
        ).fetchone()

    if not lead_row:
        return {}

    with get_connection() as conn:
        msg_rows = conn.execute(
            "SELECT id, role, contenu, created_at, read_at, metadata "
            "FROM conversations "
            "WHERE lead_id = %s AND client_id = %s AND canal = 'sms' "
            "ORDER BY created_at ASC",
            (lead_id, client_id),
        ).fetchall()

    lead = dict(lead_row)
    messages = []
    for row in msg_rows:
        d = dict(row)
        messages.append({
            "id": d["id"],
            "role": d["role"],
            "contenu": d["contenu"],
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
            "read_at": d["read_at"].isoformat() if d.get("read_at") else None,
            "metadata": json.loads(d.get("metadata") or "{}"),
        })

    return {
        "lead": {
            "id": lead["id"],
            "prenom": lead.get("prenom") or "",
            "nom": lead.get("nom") or "",
            "telephone": lead.get("telephone") or "",
            "score": lead.get("score"),
            "statut": lead.get("statut"),
        },
        "messages": messages,
    }


def mark_thread_as_read(client_id: str, lead_id: str) -> int:
    """Marque tous les SMS entrants non lus du lead comme lus. Retourne le nb de messages marqués."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE conversations SET read_at = NOW() "
            "WHERE lead_id = %s AND client_id = %s AND canal = 'sms' "
            "AND role = 'user' AND read_at IS NULL",
            (lead_id, client_id),
        )
        marked = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
    return marked


def get_unread_count_total(client_id: str) -> int:
    """Retourne le nombre total de SMS entrants non lus pour un client."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversations "
            "WHERE client_id = %s AND canal = 'sms' AND role = 'user' AND read_at IS NULL",
            (client_id,),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def send_sms(client_id: str, lead_id: str, body: str) -> dict:
    """Envoie un SMS via Twilio et stocke le message en base.

    Lève ValueError si le lead est introuvable ou si aucun numéro Twilio n'est configuré.
    Lève l'exception Twilio telle quelle en cas d'échec d'envoi.
    Retourne {"twilio_sid": str, "status": str, "conversation_id": str | None}.
    """
    from config.settings import get_settings
    from twilio.rest import Client as TwilioClient
    from memory.lead_repository import add_conversation_message
    from memory.models import Canal

    # Vérification lead + ownership
    with get_connection() as conn:
        lead_row = conn.execute(
            "SELECT id, telephone FROM leads WHERE id = %s AND client_id = %s LIMIT 1",
            (lead_id, client_id),
        ).fetchone()

    if not lead_row:
        raise ValueError("Lead introuvable ou accès non autorisé")

    telephone = lead_row["telephone"]
    if not telephone:
        raise ValueError("Ce lead n'a pas de numéro de téléphone")

    # Numéro Twilio assigné à l'utilisateur
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT twilio_sms_number FROM users WHERE id = %s LIMIT 1",
            (client_id,),
        ).fetchone()

    if not user_row or not user_row["twilio_sms_number"]:
        raise ValueError("Aucun numéro SMS Twilio assigné à ce compte")

    from_number = user_row["twilio_sms_number"]

    settings = get_settings()
    twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    message = twilio_client.messages.create(
        from_=from_number,
        to=telephone,
        body=body,
    )

    # Stockage en base (non bloquant — le SMS est déjà parti)
    conversation_id: Optional[str] = None
    try:
        conv = add_conversation_message(
            lead_id=lead_id,
            client_id=client_id,
            role="assistant",
            contenu=body,
            canal=Canal.SMS,
            metadata={
                "twilio_message_sid": message.sid,
                "status": message.status,
                "from_number": from_number,
                "to_number": telephone,
            },
        )
        conversation_id = conv.id
    except Exception:
        pass

    return {
        "twilio_sid": message.sid,
        "status": message.status,
        "conversation_id": conversation_id,
    }
