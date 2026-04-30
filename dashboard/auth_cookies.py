"""
Gestion des cookies de session PropPilot.
Utilise streamlit-cookies-controller.

Double-render
─────────────
CookieController s'appuie sur un composant React. Au render #1 (premier render
d'une nouvelle session Streamlit), le composant React n'a pas encore communiqué
ses valeurs : getAll() retourne {} (pas None). On détecte render #1 via
l'absence de 'proppilot_cc' dans st.session_state (clé interne de la lib,
absente avant le premier CookieController()).

Race condition iFrame
─────────────────────
cc.set() ajoute une iFrame React dont le JS charge de manière asynchrone.
Si st.rerun() est appelé juste après, la nouvelle page remplace l'iFrame avant
que ws.set() ait eu le temps d'écrire dans document.cookie.
Fix : ne jamais appeler save_session() dans le même render que st.rerun().
Voir require_auth(write_pending_cookie=True) dans auth_ui.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

import streamlit as st

logger = logging.getLogger(__name__)

_SESSION_COOKIE = "proppilot_session"
SESSION_DAYS    = 30
_SECRET         = "PROPPILOT_SECRET_2026"

_CC_KEY      = "_proppilot_cc"       # objet CookieController mis en cache
_CC_RUN_KEY  = "_proppilot_cc_run"   # run_id du render où le CC a été créé
_CC_INIT_KEY = "_proppilot_cc_init"  # False = render #1, True = render #2+


def _current_run_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return ctx.run_id if ctx else None
    except Exception:
        return None


def get_cookie_manager():
    """
    Retourne le CookieController en le rendant une seule fois par rerun Streamlit.
    Guard anti-DuplicateWidgetID : si déjà rendu ce tour-ci, retourne le cache.

    Détecte render #1 via l'absence de 'proppilot_cc' dans st.session_state
    (clé interne de CookieController, créée lors du premier CookieController()).
    getAll() retourne {} au render #1 (pas None) — on ne peut pas s'y fier.
    """
    from streamlit_cookies_controller import CookieController

    run_id = _current_run_id()

    if st.session_state.get(_CC_RUN_KEY) == run_id and _CC_KEY in st.session_state:
        return st.session_state[_CC_KEY]

    # 'proppilot_cc' absent = render #1 de cette session (lib jamais initialisée)
    first_session_render = "proppilot_cc" not in st.session_state

    cc = CookieController(key="proppilot_cc")
    st.session_state[_CC_KEY] = cc
    st.session_state[_CC_RUN_KEY] = run_id
    # Render #1 → non initialisé (React pas encore répondu)
    # Render #2+ → initialisé (cookies disponibles dans st.session_state['proppilot_cc'])
    st.session_state[_CC_INIT_KEY] = not first_session_render

    return cc


def is_cookie_loading() -> bool:
    """
    True si render #1 (React n'a pas encore envoyé les cookies au backend).
    Doit être appelé APRÈS get_cookie_manager().
    """
    return not st.session_state.get(_CC_INIT_KEY, False)


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
    """
    Écrit la session dans un cookie JSON unique valable 30 jours.

    Appeler uniquement depuis un render stable (sans st.rerun()/st.switch_page()
    immédiatement après). Passer write_pending_cookie=True à require_auth()
    sur les pages landing — ne pas appeler directement depuis un handler de form.
    """
    cc = get_cookie_manager()
    if not cc:
        return
    try:
        payload = json.dumps({
            "user_id":     str(user_id),
            "token":       token,
            "agency_name": agency_name,
            "plan":        plan,
            "plan_active": plan_active,
            "is_admin":    is_admin,
            "email":       email,
            "hmac":        _hmac(str(user_id)),
        })
        cc.set(
            _SESSION_COOKIE,
            payload,
            max_age=SESSION_DAYS * 86400,
            same_site="lax",
        )
    except Exception as e:
        logger.error("save_session error : %s", e)


def load_session() -> dict | None:
    """
    Restaure la session depuis le cookie JSON.
    Retourne un dict compatible avec _set_session(), ou None.
    Doit être appelé APRÈS get_cookie_manager() ET is_cookie_loading() == False.
    """
    cc = get_cookie_manager()
    if not cc:
        return None
    try:
        raw = cc.get(_SESSION_COOKIE)
        if not raw:
            return None
        data = json.loads(raw)
        user_id = data.get("user_id", "")
        if not user_id or data.get("hmac") != _hmac(str(user_id)):
            logger.warning("Cookie HMAC invalide — session rejetée")
            return None
        return {
            "user_id":     user_id,
            "token":       data.get("token", ""),
            "agency_name": data.get("agency_name") or "Mon Agence",
            "plan":        data.get("plan") or "Starter",
            "plan_active": bool(data.get("plan_active", False)),
            "is_admin":    bool(data.get("is_admin", False)),
            "email":       data.get("email") or "",
        }
    except Exception as e:
        logger.error("load_session error : %s", e)
        return None


def clear_session() -> None:
    """Supprime le cookie de session (appelé au logout)."""
    cc = get_cookie_manager()
    if not cc:
        return
    try:
        cc.remove(_SESSION_COOKIE, same_site="lax")
    except Exception as e:
        logger.error("clear_session error : %s", e)
