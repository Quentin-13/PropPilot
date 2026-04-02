"""
Gestion des cookies de session PropPilot.
Permet de rester connecté 30 jours sans ressaisir ses identifiants.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

import streamlit as st

logger = logging.getLogger(__name__)

_PREFIX = "proppilot_"
SESSION_DAYS = 30
_SECRET = "PROPPILOT_SECRET_2026"

_FIELDS = ["user_id", "token", "agency_name", "plan",
           "plan_active", "is_admin", "hmac"]


@st.cache_resource
def _get_manager():
    """Singleton CookieManager — chargé une seule fois par process."""
    try:
        import extra_streamlit_components as stx
        return stx.CookieManager(key="proppilot_cookies")
    except Exception as e:  # pragma: no cover
        logger.warning(f"CookieManager indisponible : {e}")
        return None


def get_cookie_manager():
    """Retourne le manager (peut être None si la lib n'est pas installée)."""
    return _get_manager()


def _hmac(user_id: str) -> str:
    raw = f"{user_id}{_SECRET}"
    return hashlib.sha256(raw.encode()).hexdigest()


def save_session(
    user_id: str,
    token: str,
    agency_name: str,
    plan: str,
    plan_active: bool,
    is_admin: bool,
) -> None:
    """Écrit tous les champs de session dans des cookies valables 30 jours."""
    cm = get_cookie_manager()
    if not cm:
        return
    try:
        expires = datetime.now() + timedelta(days=SESSION_DAYS)
        values = {
            "user_id":      str(user_id),
            "token":        token,
            "agency_name":  agency_name,
            "plan":         plan,
            "plan_active":  str(plan_active),
            "is_admin":     str(is_admin),
            "hmac":         _hmac(str(user_id)),
        }
        for key, val in values.items():
            cm.set(f"{_PREFIX}{key}", val, expires_at=expires)
    except Exception as e:
        logger.error(f"save_session error : {e}")


def load_session() -> dict | None:
    """
    Tente de restaurer la session depuis les cookies.
    Retourne un dict compatible avec _set_session(), ou None.
    """
    cm = get_cookie_manager()
    if not cm:
        return None
    try:
        user_id   = cm.get(f"{_PREFIX}user_id")
        token     = cm.get(f"{_PREFIX}token")
        hmac_val  = cm.get(f"{_PREFIX}hmac")

        if not all([user_id, token, hmac_val]):
            return None

        if hmac_val != _hmac(str(user_id)):
            logger.warning("Cookie HMAC invalide — session rejetée")
            return None

        return {
            "user_id":     user_id,
            "token":       token,
            "agency_name": cm.get(f"{_PREFIX}agency_name") or "Mon Agence",
            "plan":        cm.get(f"{_PREFIX}plan") or "Starter",
            "plan_active": cm.get(f"{_PREFIX}plan_active") == "True",
            "is_admin":    cm.get(f"{_PREFIX}is_admin") == "True",
        }
    except Exception as e:
        logger.error(f"load_session error : {e}")
        return None


def clear_session() -> None:
    """Supprime tous les cookies de session (appelé au logout)."""
    cm = get_cookie_manager()
    if not cm:
        return
    try:
        for key in _FIELDS:
            cm.delete(f"{_PREFIX}{key}")
    except Exception as e:
        logger.error(f"clear_session error : {e}")
