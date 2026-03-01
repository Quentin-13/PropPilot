"""
Serveur FastAPI — PropPilot.
Expose les webhooks Twilio (SMS, WhatsApp), SeLoger, LeBonCoin, Retell et Apimo.

Démarrage :
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Production :
    uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import get_settings
from memory.database import init_database

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisation au démarrage du serveur."""
    init_database()
    settings = get_settings()
    logger.info(f"PropPilot — {settings.agency_name} | Tier {settings.agency_tier}")
    logger.info(f"Claude: {'✅' if settings.anthropic_available else '⚠️ mock'} | "
                f"Twilio: {'✅' if settings.twilio_available else '⚠️ mock'}")
    yield


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PropPilot — API",
    description="Webhooks entrants pour leads, SMS, WhatsApp, appels voix",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def jwt_middleware(request: Request, call_next):
    """Vérifie le JWT Bearer token sur toutes les routes /api/*."""
    if request.url.path.startswith("/api/"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Token d'authentification manquant"},
                status_code=401,
            )
        token = auth_header[7:]
        from memory.auth import verify_token
        payload = verify_token(token)
        if not payload:
            return JSONResponse(
                {"detail": "Token invalide ou expiré"},
                status_code=401,
            )
        request.state.user_id = payload["user_id"]
        request.state.tier = payload["plan"]
    return await call_next(request)


# ─── Modèles auth ─────────────────────────────────────────────────────────────

class _SignupRequest(BaseModel):
    email: str
    password: str
    agency_name: str = ""


class _LoginRequest(BaseModel):
    email: str
    password: str


def _get_client_settings() -> tuple[str, str]:
    """Retourne (client_id, tier) depuis la config."""
    settings = get_settings()
    return settings.agency_client_id, settings.agency_tier


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
async def root():
    """Endpoint racine — health check rapide."""
    settings = get_settings()
    return {
        "service": "PropPilot",
        "agency": settings.agency_name,
        "tier": settings.agency_tier,
        "status": "ok",
    }


@app.get("/health", tags=["health"])
async def health():
    """Health check détaillé."""
    settings = get_settings()
    return {
        "status": "ok",
        "anthropic": settings.anthropic_available,
        "twilio": settings.twilio_available,
        "openai": settings.openai_available,
        "elevenlabs": settings.elevenlabs_available,
    }


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/signup", tags=["auth"], status_code=201)
async def auth_signup(body: _SignupRequest):
    """Crée un nouveau compte. Retourne les informations du compte créé."""
    from memory.auth import signup
    try:
        user = signup(body.email, body.password, body.agency_name)
        return JSONResponse(user, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login", tags=["auth"])
async def auth_login(body: _LoginRequest):
    """Authentifie un utilisateur et retourne un JWT Bearer token + infos compte."""
    from memory.auth import login
    from memory.database import get_connection
    try:
        token = login(body.email, body.password)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, agency_name, plan FROM users WHERE email = ?",
                (body.email,),
            ).fetchone()
        return JSONResponse({
            "access_token": token,
            "token_type": "bearer",
            "user_id": row["id"] if row else "",
            "agency_name": row["agency_name"] if row else "",
            "plan": row["plan"] if row else "Starter",
        })
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─── Webhooks SMS (Twilio) ─────────────────────────────────────────────────────

@app.post("/webhooks/sms", tags=["webhooks"], response_class=Response)
async def sms_webhook(request: Request):
    """
    Webhook SMS entrant Twilio.
    Configurez dans Twilio Console > Phone Numbers > Messaging Webhook.
    Retourne du TwiML pour répondre automatiquement.
    """
    form_data = dict(await request.form())
    client_id, tier = _get_client_settings()

    from integrations.sms_webhook import handle_sms_webhook
    result = handle_sms_webhook(form_data, client_id=client_id, tier=tier)

    return Response(
        content=result.get("twiml", "<?xml version='1.0'?><Response></Response>"),
        media_type="text/xml",
    )


@app.post("/webhooks/sms/status", tags=["webhooks"])
async def sms_status_callback(request: Request):
    """
    Callback statut SMS Twilio (delivered, failed, etc.).
    Configurez dans Twilio Console > Phone Numbers > Status Callback.
    """
    form_data = dict(await request.form())
    from integrations.sms_webhook import handle_sms_status_callback
    result = handle_sms_status_callback(form_data)
    return JSONResponse(result)


# ─── Webhooks WhatsApp (Twilio) ────────────────────────────────────────────────

@app.post("/webhooks/whatsapp", tags=["webhooks"], response_class=Response)
async def whatsapp_webhook(request: Request):
    """
    Webhook WhatsApp Business entrant via Twilio.
    Configurez dans Twilio Console > Messaging > WhatsApp Sandbox.
    Retourne du TwiML pour répondre automatiquement.
    """
    form_data = dict(await request.form())
    client_id, tier = _get_client_settings()

    from integrations.whatsapp_webhook import handle_whatsapp_webhook
    result = handle_whatsapp_webhook(form_data, client_id=client_id, tier=tier)

    return Response(
        content=result.get("twiml", "<?xml version='1.0'?><Response></Response>"),
        media_type="text/xml",
    )


@app.post("/webhooks/whatsapp/status", tags=["webhooks"])
async def whatsapp_status_callback(request: Request):
    """Callback statut WhatsApp Twilio."""
    form_data = dict(await request.form())
    from integrations.whatsapp_webhook import handle_whatsapp_status_callback
    result = handle_whatsapp_status_callback(form_data)
    return JSONResponse(result)


# ─── Webhooks portails immobiliers ────────────────────────────────────────────

@app.post("/webhooks/seloger", tags=["webhooks"])
async def seloger_webhook(
    request: Request,
    x_seloger_signature: Optional[str] = Header(None, alias="X-SeLoger-Signature"),
):
    """
    Webhook leads SeLoger.
    SeLoger envoie un POST JSON à chaque nouveau lead sur vos annonces.
    Docs : https://www.seloger.com/pro/integration/leads-webhook
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    client_id, tier = _get_client_settings()
    raw_bytes = await request.body()

    from integrations.seloger_webhook import handle_seloger_lead
    result = handle_seloger_lead(
        payload=payload,
        client_id=client_id,
        tier=tier,
        raw_bytes=raw_bytes,
        signature=x_seloger_signature,
    )

    if not result.get("success"):
        if result.get("error") == "invalid_signature":
            raise HTTPException(status_code=401, detail="Invalid signature")
        raise HTTPException(status_code=400, detail=result.get("error", "Error"))

    return JSONResponse(result)


@app.post("/webhooks/leboncoin", tags=["webhooks"])
async def leboncoin_webhook(request: Request):
    """
    Webhook leads LeBonCoin Immo.
    LeBonCoin envoie un POST JSON à chaque nouveau message sur vos annonces.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    client_id, tier = _get_client_settings()

    from integrations.seloger_webhook import handle_leboncoin_lead
    result = handle_leboncoin_lead(payload=payload, client_id=client_id, tier=tier)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error"))

    return JSONResponse(result)


# ─── Webhook Retell AI (post-appel) ───────────────────────────────────────────

@app.post("/webhooks/retell", tags=["webhooks"])
async def retell_webhook(request: Request):
    """
    Webhook Retell AI — events call_started, call_ended, call_analyzed.
    Configurez dans Retell Dashboard > Webhooks.
    Déclenche le traitement post-appel (transcription, scoring, booking RDV).
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "")
    call_data = payload.get("call", {})
    call_id = call_data.get("call_id", "")

    logger.info(f"Retell webhook : event={event} call_id={call_id[:12] if call_id else 'N/A'}")

    # Seul l'event call_analyzed nous intéresse (contient transcription + analyse)
    if event not in ("call_ended", "call_analyzed"):
        return JSONResponse({"status": "ignored", "event": event})

    # Récupérer le lead_id depuis les métadonnées de l'appel
    metadata = call_data.get("metadata", {})
    lead_id = metadata.get("lead_id", "")
    client_id = metadata.get("client_id", get_settings().agency_client_id)

    if not lead_id or not call_id:
        logger.warning(f"Retell webhook sans lead_id ou call_id — ignoré")
        return JSONResponse({"status": "ignored", "reason": "missing_lead_id"})

    # Traitement post-appel via VoiceCallAgent
    from agents.voice_call import VoiceCallAgent
    settings = get_settings()
    agent = VoiceCallAgent(client_id=client_id, tier=settings.agency_tier)

    try:
        result = agent.process_call_ended(call_id=call_id, lead_id=lead_id)
        return JSONResponse({
            "status": "processed",
            "lead_updated": result.get("lead_updated"),
            "rdv_booked": result.get("rdv_booked"),
            "post_score": result.get("post_score"),
        })
    except Exception as e:
        logger.error(f"Erreur traitement post-appel {call_id} : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Webhook Apimo CRM ────────────────────────────────────────────────────────

@app.post("/webhooks/apimo", tags=["webhooks"])
async def apimo_webhook(request: Request):
    """
    Webhook Apimo CRM entrant.
    Events : contact.created, property.mandate.signed
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    from integrations.apimo import parse_apimo_webhook
    parsed = parse_apimo_webhook(payload)

    logger.info(f"Apimo webhook : event={parsed.get('event_type')}")

    # Si nouveau contact créé dans Apimo, le qualifier via l'orchestrateur
    if parsed.get("event_type") == "new_contact":
        data = parsed.get("data", {})
        telephone = data.get("telephone", "")
        if telephone:
            from orchestrator import process_incoming_message
            settings = get_settings()
            process_incoming_message(
                telephone=telephone,
                message=f"Nouveau contact Apimo : {data.get('prenom', '')} {data.get('nom', '')}",
                client_id=settings.agency_client_id,
                tier=settings.agency_tier,
                canal="email",
                prenom=data.get("prenom", ""),
                nom=data.get("nom", ""),
                email=data.get("email", ""),
            )

    return JSONResponse({"status": "ok", "event": parsed.get("event_type")})


# ─── Webhooks CRM universels ──────────────────────────────────────────────────

@app.post("/webhook/crm/{crm_name}", tags=["webhooks"])
async def crm_webhook(
    crm_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Webhook universel pour tous les CRM supportés.
    Accepte les payloads de Hektor, Apimo, Prospeneo, Whise, Adaptimmo.
    URL à configurer dans chaque CRM : https://votre-domaine.com/webhook/crm/{crm_name}

    Exemples :
      POST /webhook/crm/hektor
      POST /webhook/crm/apimo
      POST /webhook/crm/prospeneo
    """
    crm_name_lower = crm_name.lower()
    supported = {"hektor", "apimo", "prospeneo", "whise", "adaptimmo"}

    if crm_name_lower not in supported:
        raise HTTPException(
            status_code=404,
            detail=f"CRM '{crm_name}' non supporté. CRM supportés : {', '.join(sorted(supported))}",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    client_id, tier = _get_client_settings()

    # Parser le payload selon le CRM
    try:
        from integrations.sync.scheduler import get_connector
        settings = get_settings()
        connector = get_connector(
            crm_type=crm_name_lower,
            api_key="",  # webhook entrant — pas de clé nécessaire pour parser
            agency_id=client_id,
        )
        lead = connector.parse_webhook_payload(payload)
    except Exception as e:
        logger.error(f"[CRM Webhook] Erreur parsing {crm_name} : {e}")
        raise HTTPException(status_code=400, detail=f"Payload non parseable : {e}")

    if lead is None:
        logger.warning(f"[CRM Webhook] {crm_name} : payload sans lead exploitable")
        return JSONResponse({"status": "ignored", "reason": "no_lead_data"})

    # Dédoublonnage et insertion en arrière-plan
    def _process_lead(lead, client_id: str, tier: str):
        from integrations.sync.conflict_resolver import resolve
        from memory.lead_repository import create_lead
        lead.client_id = client_id
        final_lead, is_dup = resolve(lead)
        if not is_dup:
            saved = create_lead(final_lead)
            # Déclencher qualification
            try:
                from orchestrator import process_incoming_message
                process_incoming_message(
                    telephone=final_lead.telephone or "",
                    message=f"Nouveau lead {crm_name} : {final_lead.prenom} {final_lead.nom}",
                    client_id=client_id,
                    tier=tier,
                    canal="web",
                    prenom=final_lead.prenom or "",
                    nom=final_lead.nom or "",
                    email=final_lead.email or "",
                )
            except Exception as e:
                logger.warning(f"[CRM Webhook] Orchestrateur ignoré : {e}")
        return is_dup

    background_tasks.add_task(_process_lead, lead, client_id, tier)

    return JSONResponse({
        "status": "accepted",
        "crm": crm_name_lower,
        "lead_name": f"{lead.prenom} {lead.nom}".strip() or "inconnu",
    })


@app.post("/webhook/portal/{portal_name}", tags=["webhooks"])
async def portal_webhook(portal_name: str, request: Request):
    """
    Webhook universel pour les portails immobiliers.
    Supporte : bienici, logic_immo (seloger et leboncoin ont leurs propres endpoints).
    """
    portal_name_lower = portal_name.lower().replace("-", "_")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    client_id, tier = _get_client_settings()

    if portal_name_lower == "bienici":
        from integrations.portals.bienici import handle_bienici_lead
        result = handle_bienici_lead(payload=payload, client_id=client_id, tier=tier)
    elif portal_name_lower in ("logic_immo", "logicimmo"):
        from integrations.portals.logic_immo import handle_logic_immo_lead
        result = handle_logic_immo_lead(payload=payload, client_id=client_id, tier=tier)
    else:
        raise HTTPException(status_code=404, detail=f"Portail '{portal_name}' non supporté")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Error"))

    return JSONResponse(result)


# ─── API interne (back-office) ─────────────────────────────────────────────────

@app.get("/api/status", tags=["api"])
async def api_status(request: Request):
    """Statut global du système — usage et pipeline."""
    client_id = request.state.user_id
    tier = request.state.tier
    from memory.lead_repository import get_pipeline_stats
    from memory.usage_tracker import get_usage_summary

    stats = get_pipeline_stats(client_id)
    usage = get_usage_summary(client_id, tier)

    return JSONResponse({
        "client_id": client_id,
        "tier": tier,
        "pipeline": stats,
        "usage": usage,
    })


@app.post("/api/simulate-lead", tags=["api"])
async def api_simulate_lead(request: Request):
    """
    Simule un lead entrant.
    Body JSON : {"telephone": str, "message": str, "prenom": str, "canal": str}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    telephone = body.get("telephone", "+33699000099")
    message = body.get("message", "Bonjour, je cherche un appartement")
    prenom = body.get("prenom", "")
    canal = body.get("canal", "sms")

    client_id = request.state.user_id
    tier = request.state.tier
    from orchestrator import process_incoming_message

    result = process_incoming_message(
        telephone=telephone,
        message=message,
        client_id=client_id,
        tier=tier,
        canal=canal,
        prenom=prenom,
    )

    return JSONResponse({
        "lead_id": result.get("lead_id"),
        "score": result.get("score"),
        "status": result.get("status"),
        "message_sortant": result.get("message_sortant"),
        "next_action": result.get("next_action"),
    })


@app.post("/api/nurturing/process", tags=["api"])
async def api_process_nurturing(request: Request):
    """
    Déclenche le traitement de tous les follow-ups nurturing dus.
    À appeler via un cron job (ex. toutes les heures).
    """
    from agents.nurturing import NurturingAgent

    agent = NurturingAgent(client_id=request.state.user_id, tier=request.state.tier)
    results = agent.process_due_followups()

    sent = len([r for r in results if r.get("sent")])
    return JSONResponse({
        "total_processed": len(results),
        "sent": sent,
        "skipped": len(results) - sent,
    })


@app.post("/api/voice/call-hot-leads", tags=["api"])
async def api_call_hot_leads(request: Request):
    """
    Déclenche des appels sortants vers les leads chauds non joignables.
    À appeler via un cron job (ex. toutes les 30 min en heures ouvrables).
    """
    from agents.voice_call import VoiceCallAgent

    agent = VoiceCallAgent(client_id=request.state.user_id, tier=request.state.tier)
    results = agent.call_leads_not_responded(min_score=7, sms_delay_min=30)

    initiated = len([r for r in results if r.get("success")])
    return JSONResponse({
        "total_leads": len(results),
        "calls_initiated": initiated,
        "results": results,
    })
