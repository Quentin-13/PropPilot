"""
Auth UI — Login / Signup pour le dashboard Streamlit.

Fonctions publiques :
  require_auth()          → garde : affiche login et st.stop() si non connecté
  render_sidebar_logout() → infos agence + bouton déconnexion dans la sidebar
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import streamlit as st

from config.settings import get_settings


# ─── Helpers API ──────────────────────────────────────────────────────────────

def _api_url() -> str:
    return get_settings().api_url


def _do_login(email: str, password: str) -> dict:
    """POST /auth/login → dict avec access_token, user_id, agency_name, plan (ou "error")."""
    try:
        resp = httpx.post(
            f"{_api_url()}/auth/login",
            json={"email": email, "password": password},
            timeout=8.0,
        )
        data = resp.json()
        if resp.status_code == 200:
            return data
        return {"error": data.get("detail", "Identifiants incorrects.")}
    except httpx.ConnectError:
        return {"error": "Impossible de joindre le serveur API. Vérifiez qu'il est démarré."}
    except Exception as e:
        return {"error": str(e)}


def _do_signup(email: str, password: str, agency_name: str) -> dict:
    """POST /auth/signup → dict avec user_id, plan (ou "error")."""
    try:
        resp = httpx.post(
            f"{_api_url()}/auth/signup",
            json={"email": email, "password": password, "agency_name": agency_name},
            timeout=8.0,
        )
        data = resp.json()
        if resp.status_code == 201:
            return data
        return {"error": data.get("detail", "Erreur lors de la création du compte.")}
    except httpx.ConnectError:
        return {"error": "Impossible de joindre le serveur API. Vérifiez qu'il est démarré."}
    except Exception as e:
        return {"error": str(e)}


def _set_session(token: str, user_id: str, agency_name: str, plan: str) -> None:
    st.session_state["authenticated"] = True
    st.session_state["token"] = token
    st.session_state["user_id"] = user_id
    st.session_state["agency_name"] = agency_name or "Mon Agence"
    st.session_state["plan"] = plan or "Starter"


# ─── Page login / signup ──────────────────────────────────────────────────────

def show_auth_page() -> None:
    """Affiche la page d'authentification (tabs login + signup)."""
    # Cacher la navigation sidebar quand non connecté
    st.markdown("""
    <style>
    [data-testid="stSidebarNav"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.markdown("""
        <div style="text-align: center; padding: 40px 0 24px 0;">
            <span style="font-size: 48px;">🏠</span>
            <h1 style="margin: 8px 0 4px 0; font-size: 2rem;">PropPilot</h1>
            <p style="color: #64748b; margin: 0;">L'IA pour les agences immobilières françaises</p>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_signup = st.tabs(["Se connecter", "Créer mon compte"])

        # ── Login ──────────────────────────────────────────────────────────────
        with tab_login:
            with st.form("form_login", clear_on_submit=False):
                email = st.text_input("Email", placeholder="vous@agence.fr")
                password = st.text_input("Mot de passe", type="password")
                submitted = st.form_submit_button("Se connecter", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("Merci de remplir email et mot de passe.")
                else:
                    with st.spinner("Connexion en cours…"):
                        result = _do_login(email, password)
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        _set_session(
                            token=result["access_token"],
                            user_id=result.get("user_id", ""),
                            agency_name=result.get("agency_name", email),
                            plan=result.get("plan", "Starter"),
                        )
                        st.rerun()

        # ── Signup ─────────────────────────────────────────────────────────────
        with tab_signup:
            with st.form("form_signup", clear_on_submit=False):
                agency_name = st.text_input("Nom de l'agence", placeholder="Agence Martin Immobilier")
                email_s = st.text_input("Email professionnel", placeholder="vous@agence.fr")
                password_s = st.text_input(
                    "Mot de passe",
                    type="password",
                    help="Minimum 8 caractères recommandés",
                )
                submitted_s = st.form_submit_button("Créer mon compte", use_container_width=True, type="primary")

            if submitted_s:
                if not email_s or not password_s or not agency_name:
                    st.error("Merci de remplir tous les champs.")
                else:
                    with st.spinner("Création du compte…"):
                        result = _do_signup(email_s, password_s, agency_name)
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        # Auto-login immédiat après signup
                        with st.spinner("Connexion automatique…"):
                            login_result = _do_login(email_s, password_s)
                        if "error" not in login_result:
                            _set_session(
                                token=login_result["access_token"],
                                user_id=login_result.get("user_id", result.get("user_id", "")),
                                agency_name=agency_name,
                                plan="Starter",
                            )
                            st.success(f"Bienvenue, {agency_name} ! Compte créé avec succès.")
                            st.rerun()
                        else:
                            st.success("Compte créé. Connectez-vous dans l'onglet ci-contre.")

        st.markdown("""
        <div style="text-align: center; margin-top: 24px; color: #94a3b8; font-size: 12px;">
            Essai 14 jours · Garantie ROI 60 jours · Support email inclus
        </div>
        """, unsafe_allow_html=True)


# ─── Garde d'authentification ─────────────────────────────────────────────────

def require_auth() -> None:
    """
    Vérifie que l'utilisateur est authentifié.
    Si non → affiche la page login/signup et arrête l'exécution de la page.
    Doit être appelé APRÈS st.set_page_config().
    """
    if not st.session_state.get("authenticated"):
        show_auth_page()
        st.stop()


# ─── Sidebar : infos agence + déconnexion ─────────────────────────────────────

def render_sidebar_logout() -> None:
    """
    Affiche dans la sidebar :
      - Nom de l'agence et forfait
      - Bouton de déconnexion
    À appeler depuis un bloc `with st.sidebar:` ou directement.
    """
    agency_name = st.session_state.get("agency_name", "Mon Agence")
    plan = st.session_state.get("plan", "Starter")

    with st.sidebar:
        st.markdown(f"""
        <div style="padding: 8px 0 20px 0;">
            <div style="font-size: 24px;">🏠</div>
            <div style="font-size: 18px; font-weight: 700; color: white;">{agency_name}</div>
            <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">Forfait {plan}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        if st.button("🚪 Déconnexion", use_container_width=True, key="_logout_btn"):
            for key in ["authenticated", "token", "user_id", "agency_name", "plan"]:
                st.session_state.pop(key, None)
            st.rerun()

        st.markdown("---")
        st.markdown(
            "<div style='color: #94a3b8; font-size: 12px; text-transform: uppercase; "
            "letter-spacing: 1px;'>Navigation</div>",
            unsafe_allow_html=True,
        )
