"""
Sécurité PropPilot — validation des webhooks et protection contre les abus.
"""
import logging
import time
import re
from collections import defaultdict
from functools import wraps

from fastapi import HTTPException, Request

from config.settings import get_settings

logger = logging.getLogger(__name__)


# ── TWILIO SIGNATURE VALIDATION ───────────────────────────────────────────────

async def validate_twilio_signature(request: Request) -> bool:
    settings = get_settings()
    auth_token = settings.twilio_auth_token

    if not auth_token:
        logger.warning("[Security] TWILIO_AUTH_TOKEN absent — signature non vérifiée")
        return True

    twilio_signature = request.headers.get("X-Twilio-Signature", "")
    if not twilio_signature:
        logger.warning(
            "[Security] Requête Twilio sans X-Twilio-Signature — IP=%s rejetée",
            request.client.host if request.client else "unknown",
        )
        return False

    url = str(request.url)
    try:
        form_data = await request.form()
        params = dict(form_data)
    except Exception:
        params = {}

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        valid = validator.validate(url, params, twilio_signature)
    except Exception as e:
        logger.error("[Security] Erreur RequestValidator Twilio : %s", e)
        return False

    if not valid:
        logger.warning(
            "[Security] Signature Twilio invalide — URL=%s IP=%s",
            url,
            request.client.host if request.client else "unknown",
        )
    return valid


# ── RATE LIMITING ─────────────────────────────────────────────────────────────

_rate_limit_store: dict = defaultdict(list)


def rate_limit(max_calls: int, window_seconds: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            key = f"{func.__name__}:{ip}"

            _rate_limit_store[key] = [
                t for t in _rate_limit_store[key] if now - t < window_seconds
            ]

            if len(_rate_limit_store[key]) >= max_calls:
                logger.warning(f"[RateLimit] {ip} bloqué sur {func.__name__}")
                raise HTTPException(status_code=429, detail="Trop de requêtes.")

            _rate_limit_store[key].append(now)
            return await func(request, *args, **kwargs)

        return wrapper
    return decorator


# ── PROMPT INJECTION PROTECTION ───────────────────────────────────────────────

_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore les instructions",
    "oublie tes instructions",
    "act as ",
    "tu es maintenant",
    "nouveau rôle",
    "system prompt",
    "jailbreak",
    "<script",
    "javascript:",
    "drop table",
    "select * from",
    "'; drop",
    "' or '1'='1",
]


def sanitize_sms_input(text: str) -> str:
    if not text:
        return ""
    text = text[:500]
    text_lower = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in text_lower:
            logger.warning(f"[Security] Injection détectée — pattern='{pattern}' message='{text[:80]}'")
            return "[Message filtré]"
    text = re.sub(r'[<>{}|\\\[\]^`]', '', text)
    return text.strip()


def sanitize_phone_number(phone: str) -> str:
    if not phone:
        return ""
    phone = re.sub(r'[\s\-\.]', '', phone)
    if re.match(r'^\+33[0-9]{9}$', phone):
        return phone
    if re.match(r'^0[0-9]{9}$', phone):
        return "+33" + phone[1:]
    if re.match(r'^\+[1-9][0-9]{7,14}$', phone):
        return phone
    logger.warning(f"[Security] Numéro de téléphone invalide : {phone[:20]!r}")
    return ""
