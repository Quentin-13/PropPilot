"""
API calls — click-to-call sortant et consultation des appels.

Routes (sous préfixe /api) :
    POST /api/calls/outbound            — Initie un appel sortant
    GET  /api/calls/{call_id}           — Détails d'un appel
    GET  /api/calls/{call_id}/extraction — Extraction structurée d'un appel
    GET  /api/calls                     — Liste des appels (paginée)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calls", tags=["calls"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class OutboundCallRequest(BaseModel):
    lead_id: str
    agent_id: str
    lead_phone: Optional[str] = None
    caller_id: Optional[str] = Field(
        default=None,
        description="Numéro affiché chez le lead (numéro Twilio de l'agence par défaut)",
    )


class OutboundCallResponse(BaseModel):
    call_id: str
    call_sid: str
    status: str
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/outbound", response_model=OutboundCallResponse)
async def initiate_outbound_call(body: OutboundCallRequest, request: Request):
    """
    Initie un appel sortant en deux étapes :
    1. Twilio appelle le portable de l'agent
    2. Quand l'agent décroche, mention courte puis connexion au lead

    Nécessite un JWT valide (middleware /api/*).
    """
    from config.settings import get_settings
    from memory.call_repository import create_call
    from memory.lead_repository import get_lead

    settings = get_settings()
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # Récupérer le numéro du lead — vérifie l'appartenance au client
    lead_phone = body.lead_phone
    if not lead_phone and body.lead_id:
        try:
            lead = get_lead(body.lead_id, client_id=user_id)
            if lead:
                lead_phone = lead.telephone
        except Exception as exc:
            logger.warning("[Outbound] get_lead failed: %s", exc)

    if not lead_phone:
        raise HTTPException(status_code=400, detail="Numéro de téléphone du lead requis")

    # Récupérer le numéro de l'agent
    agent_phone = None
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT phone, twilio_sms_number FROM users WHERE id = %s",
                (body.agent_id,),
            ).fetchone()
            if row:
                agent_phone = row.get("phone")
    except Exception as exc:
        logger.warning("[Outbound] agent phone lookup failed: %s", exc)

    if not agent_phone:
        raise HTTPException(status_code=400, detail="Numéro de téléphone de l'agent introuvable")

    # Caller ID : numéro Twilio de l'agence par défaut
    caller_id = body.caller_id or settings.twilio_sms_number or agent_phone

    # Utilise les headers X-Forwarded pour obtenir l'URL publique (Railway / reverse proxy)
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    forwarded_host = request.headers.get("X-Forwarded-Host", request.url.netloc)
    base_url = f"{forwarded_proto}://{forwarded_host}"

    if not settings.twilio_available:
        # Mock mode
        mock_call_id = f"mock-{body.lead_id[:8]}"
        mock_sid = f"CAxxxxxxx_{body.lead_id[:8]}"
        logger.info(
            "[MOCK] Outbound call agent=%s lead=%s lead_phone=%s",
            body.agent_id, body.lead_id, lead_phone,
        )
        call_id = create_call(
            call_sid=mock_sid,
            direction="outbound",
            mode="outbound",
            from_number=caller_id or "",
            to_number=lead_phone,
            twilio_number=caller_id or "",
            lead_id=body.lead_id,
            agent_id=body.agent_id,
            client_id=user_id,
            started_at=datetime.utcnow(),
        )
        return OutboundCallResponse(
            call_id=call_id or mock_call_id,
            call_sid=mock_sid,
            status="initiated",
            message="[MOCK] Appel sortant simulé",
        )

    # Appel réel via Twilio
    try:
        from urllib.parse import quote
        from twilio.rest import Client as TwilioClient

        twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)

        # TwiML public servi à l'agent quand il décroche — hors /api/ (pas de JWT requis)
        twiml_url = (
            f"{base_url}/webhooks/twilio/voice/outbound"
            f"?lead_phone={quote(lead_phone, safe='')}"
            f"&lead_id={quote(body.lead_id, safe='')}"
        )

        call = twilio_client.calls.create(
            to=agent_phone,
            from_=caller_id,
            url=twiml_url,
            status_callback=f"{base_url}/webhooks/twilio/voice/status",
            status_callback_method="POST",
        )

        call_id = create_call(
            call_sid=call.sid,
            direction="outbound",
            mode="outbound",
            from_number=caller_id,
            to_number=lead_phone,
            twilio_number=caller_id,
            lead_id=body.lead_id,
            agent_id=body.agent_id,
            client_id=user_id,
            started_at=datetime.utcnow(),
        )

        logger.info(
            "[Outbound] Call created call_sid=%s agent=%s lead_phone=%s",
            call.sid, body.agent_id, lead_phone,
        )
        return OutboundCallResponse(
            call_id=call_id or call.sid,
            call_sid=call.sid,
            status="initiated",
            message="Appel en cours d'initiation",
        )

    except Exception as exc:
        logger.error("[Outbound] Twilio call creation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Erreur Twilio : {exc}")


@router.get("/{call_id}")
async def get_call(call_id: str, request: Request):
    """Détails d'un appel (transcription incluse)."""
    _require_auth(request)
    from memory.call_repository import get_call_by_id

    call = get_call_by_id(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    _check_call_ownership(call, request.state.user_id)
    return call


@router.get("/{call_id}/extraction")
async def get_call_extraction(call_id: str, request: Request):
    """Extraction structurée d'un appel."""
    _require_auth(request)
    from memory.call_repository import get_call_by_id, get_extraction_by_call

    call = get_call_by_id(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    _check_call_ownership(call, request.state.user_id)

    extraction = get_extraction_by_call(call_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction introuvable pour cet appel")
    return extraction


@router.get("")
async def list_calls(request: Request, limit: int = 20, offset: int = 0):
    """Liste des appels de l'agence (paginated)."""
    _require_auth(request)
    user_id = request.state.user_id

    from memory.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.call_sid, c.direction, c.mode, c.from_number, c.to_number,
                   c.started_at, c.ended_at, c.duration_seconds,
                   c.status, ce.score_qualification
            FROM calls c
            LEFT JOIN conversation_extractions ce ON ce.call_id = c.id AND ce.source = 'call'
            WHERE c.client_id = %s
            ORDER BY c.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def _require_auth(request: Request) -> None:
    if not getattr(request.state, "user_id", None):
        raise HTTPException(status_code=401, detail="Authentification requise")


def _check_call_ownership(call: dict, user_id: str) -> None:
    """Lève 403 si l'appel n'appartient pas à l'agence authentifiée."""
    call_owner = call.get("client_id") or call.get("agency_id")
    if call_owner and call_owner != user_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
