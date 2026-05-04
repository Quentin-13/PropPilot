"""
Serveur FastAPI — PropPilot.
Expose les webhooks Twilio (SMS, WhatsApp), SeLoger, LeBonCoin, portails et Apimo.

Démarrage :
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Production :
    uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Optional

from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import get_settings
from memory.database import init_database
from tools.security import (
    validate_twilio_signature,
    sanitize_sms_input,
    sanitize_phone_number,
    rate_limit,
)
from webhooks.twilio_voice import router as voice_router
from api.calls import router as calls_router
from api.waitlist import router as waitlist_router

logger = logging.getLogger(__name__)

# Lock par numéro de téléphone entrant — empêche le traitement concurrent de deux SMS
# du même expéditeur (retry Twilio ou double envoi rapide)
_sms_process_locks: dict[str, threading.Lock] = {}
_sms_locks_registry = threading.Lock()


def _get_sms_lock(key: str) -> threading.Lock:
    with _sms_locks_registry:
        if key not in _sms_process_locks:
            _sms_process_locks[key] = threading.Lock()
        return _sms_process_locks[key]
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
        logger.info("PropPilot démarré — capture leads, reminders nurturing, no auto-SMS")
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class SecurityAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        ip = request.client.host if request.client else "unknown"
        sensitive = ["/webhooks", "/admin", "/health", "/api"]
        if any(path.startswith(s) for s in sensitive):
            logger.info(f"[Audit] {request.method} {path} — IP: {ip}")
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning(f"[Audit] {response.status_code} sur {path} — IP: {ip}")
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SecurityAuditMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Sprint A — capture d'appels ───────────────────────────────────────────────
app.include_router(voice_router)
app.include_router(calls_router)

# ── Landing waitlist ──────────────────────────────────────────────────────────
app.include_router(waitlist_router)


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
    """Sert la landing page index.html (migration Netlify → Railway)."""
    return FileResponse("index.html")


@app.get("/legal/mentions-legales", tags=["legal"])
async def mentions_legales():
    path = os.path.join(os.path.dirname(__file__), "static/legal/mentions-legales.html")
    return FileResponse(path, media_type="text/html")


@app.get("/legal/cgu", tags=["legal"])
async def cgu():
    path = os.path.join(os.path.dirname(__file__), "static/legal/cgu.html")
    return FileResponse(path, media_type="text/html")


@app.get("/legal/confidentialite", tags=["legal"])
async def confidentialite():
    path = os.path.join(os.path.dirname(__file__), "static/legal/confidentialite.html")
    return FileResponse(path, media_type="text/html")


@app.get("/health", tags=["health"])
async def health(request: Request):
    """Health check — détails disponibles uniquement avec X-Health-Key."""
    settings = get_settings()
    if settings.health_secret:
        provided = request.headers.get("X-Health-Key", "")
        if not hmac.compare_digest(provided, settings.health_secret):
            return {"status": "ok"}
    return {
        "status": "ok",
        "anthropic": settings.anthropic_available,
        "twilio": settings.twilio_available,
        "twilio_sms": settings.twilio_sms_available,
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
            "email": body.email,
        })
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─── Webhooks WhatsApp (Twilio) ────────────────────────────────────────────────

@app.post("/webhooks/whatsapp", tags=["webhooks"], response_class=Response)
async def whatsapp_webhook(request: Request):
    """
    Webhook WhatsApp Business entrant via Twilio.
    Configurez dans Twilio Console > Messaging > WhatsApp Sandbox.
    Retourne du TwiML pour répondre automatiquement.
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

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
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

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

    # Nouveau contact Apimo → créer le lead en DB (qualification via dashboard agent)
    if parsed.get("event_type") == "new_contact":
        data = parsed.get("data", {})
        telephone = data.get("telephone", "")
        if telephone:
            try:
                from memory.lead_repository import create_lead, get_lead_by_phone
                from memory.models import Lead, Canal, LeadStatus
                settings = get_settings()
                existing = get_lead_by_phone(telephone, settings.agency_client_id)
                if not existing:
                    lead = Lead(
                        client_id=settings.agency_client_id,
                        prenom=data.get("prenom", ""),
                        nom=data.get("nom", ""),
                        telephone=telephone,
                        email=data.get("email", ""),
                        source=Canal.WEB,
                        statut=LeadStatus.ENTRANT,
                    )
                    create_lead(lead)
                    logger.info("[Apimo] Nouveau lead créé : %s", telephone)
            except Exception as e:
                logger.warning("[Apimo] Erreur création lead : %s", e)

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
            create_lead(final_lead)
            logger.info("[CRM Webhook] Lead %s créé depuis %s", final_lead.telephone, crm_name)
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


# ─── Webhooks Twilio voix / SMS ───────────────────────────────────────────────

@app.post("/webhooks/twilio/voice", tags=["webhooks"], response_class=Response)
@rate_limit(max_calls=30, window_seconds=60)
async def twilio_voice_inbound(request: Request, background_tasks: BackgroundTasks):
    """
    Appel entrant sur le 07.
    Joue le message vocal de l'agence (personnalisé avec nom + agence).
    L'appel sera enregistré et transcrit dans le sprint Capture Appels.
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature invalide")

    form = await request.form()
    from_number = sanitize_phone_number(form.get("From", ""))
    to_number = form.get("To", "")

    logger.info("[Twilio voice] Appel entrant — %s → %s", from_number, to_number)

    # Lookup client par numéro 06/07
    agent_name = "votre conseiller"
    agency_name = "l'agence"

    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT agency_name, first_name FROM users "
                "WHERE twilio_sms_number = %s AND plan_active = TRUE LIMIT 1",
                (to_number,),
            ).fetchone()
            if row:
                agency_name = row["agency_name"] or agency_name
                agent_name = row["first_name"] or agent_name
            else:
                logger.warning(
                    "[Twilio voice] Numéro 'To' inconnu : %s — appel ignoré",
                    to_number,
                )
    except Exception as e:
        logger.warning("[Twilio voice] DB lookup: %s", e)

    # TwiML — message vocal entrant
    from tools.twilio_tool import TwilioTool
    twiml = TwilioTool().generate_inbound_twiml(
        agent_name=agent_name,
        agency_name=agency_name,
    )
    return Response(content=twiml, media_type="application/xml")


@app.post("/twiml/inbound", tags=["twiml"], response_class=Response)
async def twiml_inbound_redirect(request: Request, background_tasks: BackgroundTasks):
    """Rétro-compatibilité — alias du webhook voix entrant."""
    return await twilio_voice_inbound(request, background_tasks)


@app.post("/twiml/sophie/inbound", tags=["twiml"], response_class=Response)
async def twiml_sophie_inbound_compat(request: Request, background_tasks: BackgroundTasks):
    """Rétro-compatibilité legacy — redirige vers le webhook voix entrant."""
    return await twilio_voice_inbound(request, background_tasks)





@app.post("/webhooks/twilio/sms", tags=["webhooks"], response_class=Response)
async def twilio_sms_incoming(request: Request, background_tasks: BackgroundTasks):
    """
    SMS entrants Twilio 06/07.
    Capture le message et le stocke dans la table conversations.
    Aucune réponse automatique — l'agent répond lui-même depuis le dashboard.
    """
    if not await validate_twilio_signature(request):
        raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    form_data = dict(await request.form())
    from_number = sanitize_phone_number(form_data.get("From", ""))
    body = sanitize_sms_input(form_data.get("Body", ""))
    to_number = form_data.get("To", "")

    if not from_number or not body:
        return Response(
            content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
            media_type="application/xml",
        )

    logger.info("[Twilio SMS entrant] %s → %s: %s", from_number, to_number, body[:80])

    # Lookup client par numéro Twilio
    client_id: str | None = None
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM users "
                "WHERE twilio_sms_number = %s AND plan_active = TRUE LIMIT 1",
                (to_number,),
            ).fetchone()
            if row:
                client_id = row["id"]
            else:
                logger.warning(
                    "[Twilio SMS] Numéro 'To' inconnu : %s — message rejeté",
                    to_number,
                )
    except Exception as e:
        logger.warning("[Twilio SMS] DB lookup: %s", e)

    if not client_id:
        return Response(
            content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
            media_type="application/xml",
        )

    # Stockage en background (non bloquant)
    _cid = client_id

    def _store():
        from lib.sms_storage import store_incoming_sms
        result = store_incoming_sms(
            from_number=from_number,
            to_number=to_number,
            body=body,
            client_id=_cid,
        )
        if not result["stored"]:
            logger.error("[Twilio SMS] Échec stockage pour %s", from_number)

    background_tasks.add_task(_store)

    return Response(
        content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
        media_type="application/xml",
    )



# ─── Envoi SMS sortant ────────────────────────────────────────────────────────

class _SmsSendRequest(BaseModel):
    lead_id: str
    body: str


@app.post("/api/sms/send", tags=["api"])
async def api_sms_send(payload: _SmsSendRequest, request: Request):
    """Envoie un SMS à un lead via Twilio et stocke le message en base."""
    client_id = request.state.user_id

    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Le corps du SMS ne peut pas être vide")
    if len(payload.body) > 1600:
        raise HTTPException(status_code=400, detail="Le SMS dépasse la limite de 1600 caractères")

    from memory.database import get_connection

    # Vérification lead + ownership
    with get_connection() as conn:
        lead_row = conn.execute(
            "SELECT id, telephone FROM leads WHERE id = %s AND client_id = %s LIMIT 1",
            (payload.lead_id, client_id),
        ).fetchone()

    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead introuvable")

    telephone = lead_row["telephone"]
    if not telephone:
        raise HTTPException(status_code=400, detail="Ce lead n'a pas de numéro de téléphone")

    # Récupération du numéro Twilio assigné à l'utilisateur
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT twilio_sms_number FROM users WHERE id = %s LIMIT 1",
            (client_id,),
        ).fetchone()

    if not user_row or not user_row["twilio_sms_number"]:
        raise HTTPException(status_code=400, detail="Aucun numéro SMS Twilio assigné à ce compte")

    from_number = user_row["twilio_sms_number"]

    # Envoi via Twilio
    settings = get_settings()
    from twilio.rest import Client as TwilioClient

    twilio_client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    message = twilio_client.messages.create(
        from_=from_number,
        to=telephone,
        body=payload.body,
    )
    logger.info(
        "[SMS sortant] %s → %s | SID=%s | status=%s",
        from_number, telephone, message.sid, message.status,
    )

    # Stockage en base (non bloquant si erreur — le SMS est déjà parti)
    conversation_id: str | None = None
    try:
        from memory.lead_repository import add_conversation_message
        from memory.models import Canal
        conv = add_conversation_message(
            lead_id=payload.lead_id,
            client_id=client_id,
            role="assistant",
            contenu=payload.body,
            canal=Canal.SMS,
            metadata={
                "twilio_message_sid": message.sid,
                "status": message.status,
                "from_number": from_number,
                "to_number": telephone,
            },
        )
        conversation_id = conv.id
    except Exception as e:
        logger.error("[SMS sortant] Erreur stockage conversation : %s", e)

    return {"ok": True, "twilio_sid": message.sid, "status": message.status, "conversation_id": conversation_id}


# ─── Lecture conversations SMS ────────────────────────────────────────────────

@app.get("/api/sms/conversations", tags=["api"])
async def api_sms_conversations(request: Request, limit: int = 100):
    """Liste tous les threads SMS de l'agence connectée (un thread = un lead)."""
    client_id = request.state.user_id
    if limit > 500:
        limit = 500

    from memory.database import get_connection

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

        unread_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversations "
            "WHERE client_id = %s AND canal = 'sms' AND role = 'user' AND read_at IS NULL",
            (client_id,),
        ).fetchone()

    total_unread = int(unread_row["cnt"]) if unread_row else 0

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

    logger.info("[SMS conversations] client=%s threads=%d unread=%d", client_id, len(threads), total_unread)
    return {"ok": True, "threads": threads, "total_unread": total_unread}


@app.get("/api/leads/{lead_id}/conversations", tags=["api"])
async def api_lead_conversations(lead_id: str, request: Request):
    """Détail du thread SMS pour un lead spécifique."""
    client_id = request.state.user_id

    import json as _json
    from memory.database import get_connection

    with get_connection() as conn:
        lead_row = conn.execute(
            "SELECT id, prenom, nom, telephone, score, statut "
            "FROM leads WHERE id = %s AND client_id = %s LIMIT 1",
            (lead_id, client_id),
        ).fetchone()

    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead introuvable")

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
            "metadata": _json.loads(d.get("metadata") or "{}"),
        })

    logger.info("[SMS thread] client=%s lead=%s messages=%d", client_id, lead_id, len(messages))
    return {
        "ok": True,
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


@app.post("/api/sms/conversations/{lead_id}/mark_as_read", tags=["api"])
async def api_sms_mark_as_read(lead_id: str, request: Request):
    """Marque tous les SMS entrants non lus du lead comme lus."""
    client_id = request.state.user_id

    from memory.database import get_connection

    with get_connection() as conn:
        lead_row = conn.execute(
            "SELECT id FROM leads WHERE id = %s AND client_id = %s LIMIT 1",
            (lead_id, client_id),
        ).fetchone()

    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead introuvable")

    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE conversations SET read_at = NOW() "
            "WHERE lead_id = %s AND client_id = %s AND canal = 'sms' "
            "AND role = 'user' AND read_at IS NULL",
            (lead_id, client_id),
        )
        marked = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0

    logger.info("[SMS mark_as_read] client=%s lead=%s marked=%d", client_id, lead_id, marked)
    return {"ok": True, "marked_as_read": marked}


@app.get("/api/sms/unread_count", tags=["api"])
async def api_sms_unread_count(request: Request):
    """Compteur global SMS non lus pour le badge de notification dashboard."""
    client_id = request.state.user_id

    from memory.database import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversations "
            "WHERE client_id = %s AND canal = 'sms' AND role = 'user' AND read_at IS NULL",
            (client_id,),
        ).fetchone()

    unread_count = int(row["cnt"]) if row else 0
    logger.info("[SMS unread_count] client=%s count=%d", client_id, unread_count)
    return {"ok": True, "unread_count": unread_count}


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
    Simule un lead entrant (désactivé — qualification automatique supprimée).
    Crée uniquement le lead en DB pour les tests.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    from memory.lead_repository import create_lead
    from memory.models import Lead, Canal, LeadStatus

    telephone = body.get("telephone", "+33699000099")
    prenom = body.get("prenom", "")
    canal_str = body.get("canal", "sms")
    client_id = request.state.user_id

    try:
        canal = Canal(canal_str)
    except ValueError:
        canal = Canal.SMS

    lead = Lead(
        client_id=client_id,
        prenom=prenom,
        telephone=telephone,
        source=canal,
        statut=LeadStatus.ENTRANT,
    )
    saved = create_lead(lead)
    return JSONResponse({"lead_id": saved.id, "status": "entrant", "note": "qualification_manuelle_required"})


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
    Appels sortants automatiques désactivés — architecture full SMS.
    Les prospects appellent le 07, l'agent répond et déclenche la qualification SMS.
    Endpoint conservé pour compatibilité — retourne toujours disabled.
    """
    return JSONResponse({
        "disabled": True,
        "message": "Appels sortants désactivés — flux commercial 100% SMS entrant.",
        "total_leads": 0,
        "calls_initiated": 0,
        "results": [],
    })


# ─── Stripe ───────────────────────────────────────────────────────────────────

class _CheckoutRequest(BaseModel):
    plan: str
    success_url: str = ""
    cancel_url: str = ""
    engagement: bool = True


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
        engagement=body.engagement,
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


# ─── Webhooks leads entrants (sans JWT) ───────────────────────────────────────

class _WebhookLeadPayload(BaseModel):
    nom: str = ""
    prenom: str = ""
    telephone: str = ""
    email: str = ""
    source: str = "webhook"
    bien_ref: Optional[str] = None
    projet: Optional[str] = None


@app.post("/webhooks/{user_id}/leads", tags=["webhooks"])
async def webhook_leads(
    user_id: str,
    body: _WebhookLeadPayload,
    background_tasks: BackgroundTasks,
):
    """
    Webhook externe pour recevoir des leads (sans JWT).
    URL unique par compte — à configurer dans les outils externes (SeLoger, portails...).
    """
    from memory.database import get_connection as _get_conn

    # Vérification que l'user_id existe
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, plan, plan_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Compte non trouvé")

    tier = row["plan"] or "Starter"

    # Création du lead + déclenchement orchestrateur en background
    from memory.lead_repository import create_lead
    from memory.models import Lead, LeadStatus, ProjetType, Canal
    from memory.journey_repository import log_action

    projet = ProjetType.INCONNU
    if body.projet:
        try:
            projet = ProjetType(body.projet.lower())
        except ValueError:
            pass

    lead = Lead(
        client_id=user_id,
        prenom=body.prenom,
        nom=body.nom,
        telephone=body.telephone,
        email=body.email,
        source=Canal.WEB,
        statut=LeadStatus.ENTRANT,
        projet=projet,
    )
    saved_lead = create_lead(lead)

    log_action(
        lead_id=saved_lead.id,
        client_id=user_id,
        stage="reception",
        action_done="webhook_lead_received",
        action_result=f"source={body.source}",
        next_action="agent_review",
        agent_name="system",
        metadata={"source": body.source, "bien_ref": body.bien_ref or ""},
    )

    return JSONResponse({"status": "ok", "lead_id": saved_lead.id})


# ─── Import CSV leads (avec JWT) ──────────────────────────────────────────────

@app.post("/api/leads/import", tags=["api"])
async def api_leads_import(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Importe des leads depuis un fichier CSV multipart.
    Colonnes attendues : nom, prénom, téléphone, email
    Paramètre form optionnel : source (défaut: csv)
    """
    import csv as _csv
    import io as _io

    client_id = request.state.user_id
    tier = request.state.tier

    form = await request.form()
    source = form.get("source", "csv")
    uploaded = form.get("file")

    if not uploaded:
        raise HTTPException(status_code=400, detail="Champ 'file' manquant")

    raw_bytes = await uploaded.read()
    try:
        text = raw_bytes.decode("utf-8-sig")  # utf-8-sig gère le BOM Excel
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")

    reader = _csv.DictReader(_io.StringIO(text))

    # Normalisation des noms de colonnes (minuscules, sans accents)
    def _norm(s: str) -> str:
        return s.lower().strip().replace("é", "e").replace("è", "e").replace("ê", "e").replace("ô", "o").replace("â", "a")

    imported = 0
    errors = []

    from memory.lead_repository import create_lead
    from memory.models import Lead, LeadStatus, Canal
    from memory.journey_repository import log_action

    for i, row in enumerate(reader):
        normed = {_norm(k): v.strip() for k, v in row.items() if k}

        telephone = normed.get("telephone", normed.get("tel", normed.get("phone", "")))
        if not telephone:
            errors.append(f"Ligne {i + 2} : téléphone manquant")
            continue

        lead = Lead(
            client_id=client_id,
            prenom=normed.get("prenom", normed.get("prénom", normed.get("firstname", ""))),
            nom=normed.get("nom", normed.get("lastname", normed.get("name", ""))),
            telephone=telephone,
            email=normed.get("email", normed.get("mail", "")),
            source=Canal.MANUEL,
            statut=LeadStatus.ENTRANT,
        )

        try:
            saved = create_lead(lead)
            imported += 1

            log_action(
                lead_id=saved.id,
                client_id=client_id,
                stage="reception",
                action_done="csv_import",
                action_result=f"source={source}",
                next_action="agent_review",
                agent_name="system",
                metadata={"source": source, "row": i + 2},
            )

        except Exception as e:
            errors.append(f"Ligne {i + 2} : {str(e)[:60]}")

    return JSONResponse({"imported": imported, "errors": errors})


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
