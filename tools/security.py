"""
Sécurité PropPilot — validation des webhooks et protection contre les abus.
"""
import base64
import hmac
import hashlib
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
        logger.warning("[Security] Requête Twilio sans signature")
        return False

    url = str(request.url)
    try:
        form_data = await request.form()
        params = dict(form_data)
    except Exception:
        params = {}

    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    signature_str = url + sorted_params
    expected = hmac.new(
        auth_token.encode("utf-8"),
        signature_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    expected_b64 = base64.b64encode(expected).decode()

    valid = hmac.compare_digest(twilio_signature, expected_b64)
    if not valid:
        logger.warning("[Security] Signature Twilio invalide")
    return valid


# ── SMS PARTNER VALIDATION ────────────────────────────────────────────────────

async def validate_smspartner_request(request: Request) -> bool:
    settings = get_settings()
    secret = getattr(settings, "smspartner_webhook_secret", None)

    if not secret:
        client_ip = request.client.host if request.client else "unknown"
        logger.info(f"[Security] SMS Partner sans secret configuré — IP: {client_ip}")
        return True

    provided_secret = request.headers.get("X-SMSPartner-Secret", "")
    valid = hmac.compare_digest(provided_secret, secret)
    if not valid:
        logger.warning("[Security] Secret SMS Partner invalide")
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
