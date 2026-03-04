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

from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import get_settings
from memory.database import init_database

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

def _send_weekly_reports_job() -> None:
    """Job APScheduler — envoie le rapport hebdo à tous les utilisateurs actifs."""
    from datetime import datetime, timedelta
    from memory.database import get_connection
    from memory.lead_repository import get_weekly_stats
    from tools.email_tool import EmailTool

    week_start = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
    logger.info(f"[CRON] Rapport hebdomadaire — semaine du {week_start}")

    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, email, agency_name, plan FROM users WHERE plan_active = TRUE"
            ).fetchall()
    except Exception as e:
        logger.error(f"[CRON] Impossible de lire les utilisateurs : {e}")
        return

    email_tool = EmailTool()
    for row in rows:
        try:
            stats = get_weekly_stats(row["id"])
            email_tool.send_weekly_report(
                to_email=row["email"],
                agency_name=row["agency_name"] or row["email"],
                week_start=week_start,
                stats=stats,
            )
        except Exception as e:
            logger.error(f"[CRON] Rapport hebdo non envoyé à {row['email']} : {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisation au démarrage du serveur."""
    settings = get_settings()
    try:
        init_database()
        logger.info(f"PropPilot — {settings.agency_name} | Tier {settings.agency_tier}")
        logger.info(f"Claude: {'✅' if settings.anthropic_available else '⚠️ mock'} | "
                    f"Twilio: {'✅' if settings.twilio_available else '⚠️ mock'} | "
                    f"Stripe: {'✅' if settings.stripe_available else '⚠️ mock'}")
    except Exception as e:
        if settings.testing:
            logger.warning(f"DB non disponible (mode test) : {e}")
        else:
            raise

    # APScheduler — rapport hebdomadaire le lundi à 8h (pas en mode test)
    scheduler = None
    if not settings.testing:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            scheduler = BackgroundScheduler(timezone="Europe/Paris")
            scheduler.add_job(
                _send_weekly_reports_job,
                CronTrigger(day_of_week="mon", hour=8, minute=0),
                id="weekly_report",
                replace_existing=True,
            )
            scheduler.start()
            logger.info("APScheduler démarré — rapport hebdo lundi 8h (Europe/Paris)")
        except Exception as e:
            logger.warning(f"APScheduler non démarré : {e}")

    yield

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler arrêté.")


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
    """Vérifie le JWT Bearer token et plan_active sur toutes les routes /api/*."""
    # /api/calendar/callback est une redirection Google — pas de JWT
    _exempt = {"/api/calendar/callback"}
    if request.url.path.startswith("/api/") and request.url.path not in _exempt:
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

        # Vérification plan actif en temps réel (résiliation, impayé)
        try:
            from memory.stripe_billing import is_plan_active
            if not is_plan_active(payload["user_id"]):
                return JSONResponse(
                    {"detail": "Abonnement inactif. Souscrivez à un forfait PropPilot pour continuer."},
                    status_code=402,
                )
        except Exception:
            pass  # DB indisponible → on laisse passer (tests sans PostgreSQL)

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
        # Email de bienvenue (avant paiement)
        try:
            from tools.email_tool import EmailTool
            EmailTool().send_welcome_signup(
                to_email=body.email,
                agency_name=body.agency_name or body.email,
            )
        except Exception as _e:
            logger.warning(f"Email bienvenue non envoyé : {_e}")
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
                "SELECT id, agency_name, plan, plan_active, is_admin FROM users WHERE email = ?",
                (body.email,),
            ).fetchone()
        return JSONResponse({
            "access_token": token,
            "token_type": "bearer",
            "user_id": row["id"] if row else "",
            "agency_name": row["agency_name"] if row else "",
            "plan": row["plan"] if row else "Starter",
            "plan_active": bool(row["plan_active"]) if row else False,
            "is_admin": bool(row["is_admin"]) if row else False,
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


# ─── Stripe ───────────────────────────────────────────────────────────────────

class _CheckoutRequest(BaseModel):
    plan: str
    success_url: str = ""
    cancel_url: str = ""


def _extract_user_id(request: Request) -> Optional[str]:
    """Extrait l'user_id depuis le Bearer token JWT de la requête."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    from memory.auth import verify_token
    payload = verify_token(token)
    return payload["user_id"] if payload else None


@app.get("/stripe/plans", tags=["stripe"])
async def stripe_plans():
    """Retourne la liste des 4 forfaits avec prix, features et price_id Stripe."""
    from memory.stripe_billing import PLAN_FEATURES, STRIPE_PRICE_IDS
    from config.tier_limits import TIERS

    plans = []
    for plan_name in ("Indépendant", "Starter", "Pro", "Elite"):
        tier = TIERS[plan_name]
        features = PLAN_FEATURES.get(plan_name, {})
        plans.append({
            "name": plan_name,
            "price_id": STRIPE_PRICE_IDS[plan_name],
            "prix_mensuel": tier.prix_mensuel,
            "prix_affiche": features.get("prix", f"{tier.prix_mensuel}€/mois"),
            "features": features.get("features", []),
            "utilisateurs": tier.utilisateurs,
            "voix": features.get("voix", ""),
            "sms": features.get("sms", ""),
        })
    return JSONResponse({"plans": plans})


@app.post("/stripe/create-checkout-session", tags=["stripe"])
async def stripe_create_checkout(request: Request, body: _CheckoutRequest):
    """
    Crée une session Stripe Checkout pour le forfait choisi.
    Requiert un JWT Bearer token.
    """
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    from memory.stripe_billing import create_checkout_session, get_user_subscription_info
    settings = get_settings()

    user_info = get_user_subscription_info(user_id)
    customer_email = user_info["email"] if user_info else ""

    _dashboard = "https://proppilot-dashboard-production.up.railway.app"
    success_url = body.success_url or f"{_dashboard}/10_success"
    cancel_url = body.cancel_url or f"{_dashboard}/"
    # Encoder les caractères non-ASCII éventuels (ex : accents dans les URLs custom)
    success_url = quote(success_url, safe=":/?=&#%+@!$,;")
    cancel_url = quote(cancel_url, safe=":/?=&#%+@!$,;")

    result = create_checkout_session(
        user_id=user_id,
        plan_name=body.plan,
        customer_email=customer_email,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.get("/stripe/portal", tags=["stripe"])
async def stripe_portal(request: Request):
    """
    Crée et retourne l'URL du portail client Stripe pour gérer l'abonnement.
    Requiert un JWT Bearer token.
    """
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    from memory.stripe_billing import create_portal_session
    settings = get_settings()
    return_url = f"{settings.api_url}/"

    result = create_portal_session(user_id=user_id, return_url=return_url)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return JSONResponse(result)


@app.post("/stripe/webhook", tags=["stripe"])
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
):
    """
    Webhook Stripe — reçoit les événements d'abonnement.
    Configurez dans Stripe Dashboard > Webhooks > Endpoint URL.
    Événements : checkout.session.completed, customer.subscription.deleted, invoice.payment_failed
    """
    import json as _json

    raw_body = await request.body()
    settings = get_settings()

    # Vérification signature Stripe (désactivée en mode test)
    if settings.stripe_available and settings.stripe_webhook_secret and stripe_signature:
        import stripe as _stripe
        _stripe.api_key = settings.stripe_secret_key
        try:
            event = _stripe.Webhook.construct_event(
                raw_body, stripe_signature, settings.stripe_webhook_secret
            )
        except Exception as e:
            logger.warning(f"[STRIPE] Signature webhook invalide : {e}")
            raise HTTPException(status_code=400, detail=f"Signature invalide : {e}")
    else:
        try:
            event = _json.loads(raw_body)
        except Exception:
            raise HTTPException(status_code=400, detail="Payload JSON invalide")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})
    logger.info(f"[STRIPE] Webhook : {event_type}")

    if event_type == "checkout.session.completed":
        user_id = (
            data_obj.get("client_reference_id")
            or data_obj.get("metadata", {}).get("user_id", "")
        )
        plan_name = data_obj.get("metadata", {}).get("plan", "Starter")
        stripe_customer_id = data_obj.get("customer", "")
        stripe_subscription_id = data_obj.get("subscription", "")

        if user_id:
            from memory.stripe_billing import activate_subscription, get_user_subscription_info
            activate_subscription(user_id, plan_name, stripe_customer_id, stripe_subscription_id)

            # Email confirmation paiement
            user_info = get_user_subscription_info(user_id)
            if user_info and user_info.get("email"):
                from tools.email_tool import EmailTool
                EmailTool().send_payment_confirmed(
                    to_email=user_info["email"],
                    agency_name=user_info.get("agency_name", ""),
                    plan=plan_name,
                )

    elif event_type == "customer.subscription.deleted":
        stripe_subscription_id = data_obj.get("id", "")
        if stripe_subscription_id:
            from memory.stripe_billing import deactivate_subscription, get_user_subscription_info
            cancelled_user_id = deactivate_subscription(stripe_subscription_id)
            if cancelled_user_id:
                user_info = get_user_subscription_info(cancelled_user_id)
                if user_info and user_info.get("email"):
                    from tools.email_tool import EmailTool
                    EmailTool().send_subscription_cancelled(
                        to_email=user_info["email"],
                        agency_name=user_info.get("agency_name", ""),
                    )

    elif event_type == "invoice.payment_failed":
        stripe_customer_id = data_obj.get("customer", "")
        customer_email = data_obj.get("customer_email", "")

        if stripe_customer_id:
            from memory.stripe_billing import set_past_due
            user_info = set_past_due(stripe_customer_id)

            if user_info and customer_email:
                from tools.email_tool import EmailTool
                EmailTool().send_payment_failed(
                    to_email=customer_email,
                    agency_name=user_info.get("agency_name", ""),
                    portal_url="https://billing.stripe.com/",
                )

    return JSONResponse({"status": "ok", "event": event_type})


# ─── Modèles Google Calendar ───────────────────────────────────────────────────

class _CalendarBookRequest(BaseModel):
    slot_start: str          # ISO datetime
    lead_email: Optional[str] = None
    lead_name: str = ""
    lead_projet: str = "projet immobilier"
    lead_budget: str = ""
    lead_localisation: str = ""
    duration_min: int = 30


# ─── Google Calendar OAuth ─────────────────────────────────────────────────────

_DASHBOARD = "https://proppilot-dashboard-production.up.railway.app"


@app.get("/api/calendar/auth", tags=["calendar"])
async def calendar_auth(request: Request):
    """
    Génère l'URL d'autorisation Google OAuth 2.0.
    Le paramètre state = user_id (pour identifier l'utilisateur au retour).
    """
    settings = get_settings()
    user_id = request.state.user_id

    if not settings.google_oauth_available:
        # Mode mock : retourne une URL de callback local simulée
        mock_url = (
            f"{settings.api_url.rstrip('/')}/api/calendar/callback"
            f"?code=mock_code&state={user_id}"
        )
        return {"auth_url": mock_url, "mock": True}

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=settings.google_scopes,
        )
        flow.redirect_uri = settings.google_redirect_uri
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=user_id,
            prompt="consent",
        )
        return {"auth_url": auth_url, "mock": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur OAuth Google : {e}")


@app.get("/api/calendar/callback", tags=["calendar"])
async def calendar_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Reçoit le code OAuth Google, échange contre un token et le stocke en DB.
    Redirige vers le dashboard après.
    """
    from fastapi.responses import RedirectResponse
    import json as _json

    if error:
        return RedirectResponse(f"{_DASHBOARD}/08_calendar?calendar_error={error}")
    if not code or not state:
        return RedirectResponse(f"{_DASHBOARD}/08_calendar?calendar_error=missing_params")

    user_id = state
    settings = get_settings()

    # Mode mock (TESTING=true ou pas de clés OAuth)
    if not settings.google_oauth_available:
        token_data = {"access_token": "mock_token", "token_type": "Bearer", "mock": True}
        try:
            from memory.database import get_connection
            with get_connection() as conn:
                conn.execute(
                    "UPDATE users SET google_calendar_token = ? WHERE id = ?",
                    (_json.dumps(token_data), user_id),
                )
        except Exception:
            pass  # DB indisponible en tests
        return RedirectResponse(f"{_DASHBOARD}/08_calendar?calendar_connected=true")

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=settings.google_scopes,
        )
        flow.redirect_uri = settings.google_redirect_uri
        flow.fetch_token(code=code)
        creds = flow.credentials

        token_data = {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else settings.google_scopes,
            "mock": False,
        }
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET google_calendar_token = ? WHERE id = ?",
                (_json.dumps(token_data), user_id),
            )
        return RedirectResponse(f"{_DASHBOARD}/08_calendar?calendar_connected=true")
    except Exception as e:
        return RedirectResponse(f"{_DASHBOARD}/08_calendar?calendar_error={quote(str(e), safe='')}")


@app.get("/api/calendar/slots", tags=["calendar"])
async def calendar_slots(request: Request, days_ahead: int = 7):
    """
    Retourne les créneaux disponibles des N prochains jours.
    Jours ouvrés uniquement, 9h–19h, créneaux de 30 min.
    """
    user_id = request.state.user_id
    from tools.calendar_tool import CalendarTool

    cal = CalendarTool()
    slots = cal.get_available_slots(
        days_ahead=days_ahead,
        start_hour=9,
        end_hour=19,
        user_id=user_id,
    )
    return {
        "slots": [
            {
                "start": s["start"].isoformat(),
                "end": s["end"].isoformat(),
                "label": s["label"],
                "label_short": s["label_short"],
            }
            for s in slots
        ],
        "count": len(slots),
    }


@app.get("/api/calendar/status", tags=["calendar"])
async def calendar_status(request: Request):
    """Retourne si l'utilisateur a connecté Google Calendar."""
    import json as _json
    user_id = request.state.user_id
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT google_calendar_token FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row and row["google_calendar_token"]:
            token_data = _json.loads(row["google_calendar_token"])
            return {"connected": True, "mock": token_data.get("mock", False)}
        return {"connected": False, "mock": False}
    except Exception:
        return {"connected": False, "mock": False}


@app.post("/api/calendar/book", tags=["calendar"])
async def calendar_book(request: Request, body: _CalendarBookRequest):
    """
    Crée un événement Google Calendar + envoie email de confirmation au lead.
    """
    import json as _json
    from datetime import datetime as _dt
    user_id = request.state.user_id

    try:
        start_dt = _dt.fromisoformat(body.slot_start)
    except ValueError:
        raise HTTPException(status_code=422, detail="slot_start doit être un ISO datetime valide")

    from tools.calendar_tool import CalendarTool, SLOT_DURATION_MIN

    slot = {
        "start": start_dt,
        "end": start_dt + __import__("datetime").timedelta(minutes=body.duration_min),
        "label": start_dt.strftime("%A %d/%m à %H:%M"),
        "label_short": start_dt.strftime("%Hh%M"),
    }

    # Objet lead minimal pour CalendarTool
    class _MiniLead:
        prenom = body.lead_name
        nom_complet = body.lead_name
        email = body.lead_email
        budget = body.lead_budget
        localisation = body.lead_localisation

        class projet:
            value = body.lead_projet

    cal = CalendarTool()
    result = cal.book_appointment(
        lead=_MiniLead(),
        slot=slot,
        user_id=user_id,
        send_email=bool(body.lead_email),
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Erreur booking"))

    return result
