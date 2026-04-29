"""
Gestion des cookies de session PropPilot.
Permet de rester connecté 30 jours sans ressaisir ses identifiants.

Comportement du double-render extra_streamlit_components
─────────────────────────────────────────────────────────
stx.CookieManager fonctionne via un composant React qui lit les cookies
navigateur et les envoie à Python. Ce composant s'exécute de manière
asynchrone : au render #1 les cookies ne sont PAS encore disponibles
(React n'a pas encore répondu). React déclenche un render #2 avec les
vraies valeurs.

Fix : appeler stx.CookieManager() à chaque NOUVEAU render (et non pas une
seule fois via un singleton) pour que Streamlit retourne la valeur courante
stockée dans son registry interne. Un guard par run_id évite le
DuplicateWidgetID si get_cookie_manager() est appelé plusieurs fois dans
le même render.

Conséquence : get_cookie_manager() en render #1 retourne cookies vides,
en render #2 retourne les vraies valeurs. is_cookie_loading() permet à
require_auth() de distinguer ces deux états.
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
           "plan_active", "is_admin", "email", "hmac"]

_CM_KEY          = "_proppilot_cm"           # objet CookieManager mis en cache
_CM_RUN_KEY      = "_proppilot_cm_run_id"    # run_id du render où le CM a été créé
_CM_INIT_KEY     = "_proppilot_cm_initialized"  # False = render #1, True = render #2+


def _current_run_id() -> str | None:
    """Retourne l'ID unique du run Streamlit en cours (change à chaque rerun)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return ctx.run_id if ctx else None
    except Exception:
        return None


def get_cookie_manager():
    """
    Retourne le CookieManager en le re-rendant à chaque nouveau rerun Streamlit.

    - Premier appel d'un nouveau rerun : appelle stx.CookieManager() pour rendre
      le composant React et obtenir la valeur actualisée depuis le registry Streamlit.
    - Appels suivants dans le même rerun : retourne l'objet mis en cache
      (évite DuplicateWidgetID).

    État _CM_INIT_KEY :
      False = render #1 de la session (cookies pas encore disponibles)
      True  = render #2+ (cookies disponibles dans le registry Streamlit)
    """
    run_id = _current_run_id()

    # Guard : même rerun → retourner l'objet déjà rendu ce tour-ci
    if st.session_state.get(_CM_RUN_KEY) == run_id and _CM_KEY in st.session_state:
        return st.session_state.get(_CM_KEY)

    # Nouveau rerun : noter si c'est le tout premier render de cette session
    first_session_render = _CM_KEY not in st.session_state

    try:
        import extra_streamlit_components as stx
        cm = stx.CookieManager(key="proppilot_cookies")
        st.session_state[_CM_KEY] = cm
    except Exception as e:
        logger.warning("CookieManager indisponible : %s", e)
        st.session_state[_CM_KEY] = None
        cm = None

    st.session_state[_CM_RUN_KEY] = run_id
    # Render #1 → pas encore initialisé. Render #2+ → initialisé (cookies disponibles)
    st.session_state[_CM_INIT_KEY] = not first_session_render

    return cm


def is_cookie_loading() -> bool:
    """
    True si on est au render #1 de la session (cookies pas encore lus par React).
    Doit être appelé APRÈS get_cookie_manager().
    """
    if not st.session_state.get(_CM_KEY):
        return False  # CM indisponible → pas en loading, traiter comme non-connecté
    return not st.session_state.get(_CM_INIT_KEY, True)


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
    email: str = "",
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
            "email":        email,
            "hmac":         _hmac(str(user_id)),
        }
        for key, val in values.items():
            cm.set(f"{_PREFIX}{key}", val, expires_at=expires)
    except Exception as e:
        logger.error("save_session error : %s", e)


def load_session() -> dict | None:
    """
    Tente de restaurer la session depuis les cookies.
    Retourne un dict compatible avec _set_session(), ou None.
    Doit être appelé APRÈS get_cookie_manager() ET is_cookie_loading() == False.
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
            "email":       cm.get(f"{_PREFIX}email") or "",
        }
    except Exception as e:
        logger.error("load_session error : %s", e)
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
        logger.error("clear_session error : %s", e)
