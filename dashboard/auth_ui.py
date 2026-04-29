"""
Auth UI — Login / Signup pour le dashboard Streamlit.

Fonctions publiques :
  require_auth(require_active_plan=True)  → garde : vérifie auth + plan actif
  render_sidebar_logout()                 → infos agence + bouton déconnexion dans la sidebar
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import streamlit as st

from config.settings import get_settings
from dashboard.auth_cookies import (
    get_cookie_manager,
    save_session as _cookie_save,
    load_session as _cookie_load,
    clear_session as _cookie_clear,
)


# ─── Logo inline SVG ──────────────────────────────────────────────────────────

_LOGO_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 116" width="{size}" height="{size}">
  <defs>
    <linearGradient id="lg{uid}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#2563eb"/>
      <stop offset="100%" stop-color="#1e3a5f"/>
    </linearGradient>
  </defs>
  <polygon points="50,2 97,27 97,77 50,102 3,77 3,27" fill="url(#lg{uid})"/>
  <line x1="50" y1="2" x2="97" y2="27" stroke="#60a5fa" stroke-width="3.5" stroke-linecap="round"/>
  <text x="50" y="70" font-family="Arial Black, Arial, sans-serif"
        font-size="40" font-weight="900" fill="white" text-anchor="middle"
        letter-spacing="-1">PP</text>
</svg>"""


def _logo(size: int = 48, uid: str = "a") -> str:
    """Retourne l'inline SVG du logo PropPilot prêt pour st.markdown."""
    return _LOGO_SVG.format(size=size, uid=uid)


# ─── Helpers API ──────────────────────────────────────────────────────────────

def _api_url() -> str:
    return get_settings().api_url


def _do_login(email: str, password: str) -> dict:
    """POST /auth/login → dict avec access_token, user_id, agency_name, plan, plan_active (ou "error")."""
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
    """POST /auth/signup → dict avec user_id, plan, plan_active (ou "error")."""
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


_DEMO_EMAIL = "demo.dumortier@proppilot.fr"


def _set_session(
    token: str,
    user_id: str,
    agency_name: str,
    plan: str,
    plan_active: bool = True,
    is_admin: bool = False,
    email: str = "",
) -> None:
    st.session_state["authenticated"] = True
    st.session_state["token"] = token
    st.session_state["user_id"] = user_id
    st.session_state["agency_name"] = agency_name or "Mon Agence"
    st.session_state["plan"] = plan or "Starter"
    st.session_state["plan_active"] = plan_active
    st.session_state["is_admin"] = is_admin
    st.session_state["email"] = email
    st.session_state["is_demo"] = (email == _DEMO_EMAIL)


# ─── Attente d'activation ─────────────────────────────────────────────────────

def _show_plan_selection() -> None:
    """
    Affiche la page "En attente d'activation" pour les comptes non encore activés.
    L'activation est manuelle (Quentin envoie le lien Stripe après signature du devis).
    """
    agency_name = st.session_state.get("agency_name", "Mon Agence")

    st.markdown("""
    <style>
    [data-testid="stSidebarNav"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(f"""
        <div style="text-align: center; padding: 48px 0 32px 0;">
            {_logo(64, "wa")}
            <h1 style="margin: 12px 0 8px 0; font-size: 2rem; color: white;">Compte en attente</h1>
            <p style="color: #94a3b8; font-size: 1rem; margin: 0;">
                Bienvenue, <strong style="color: white;">{agency_name}</strong> !<br>
                Votre compte a bien été créé.
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: #1e2130; border-radius: 12px; padding: 28px 32px;
                    border-left: 4px solid #3b82f6; margin: 0 0 24px 0;">
            <div style="font-size: 1.05rem; font-weight: 700; color: white; margin-bottom: 10px;">
                Votre accès est en cours d'activation
            </div>
            <p style="color: #cbd5e1; margin: 0; line-height: 1.7;">
                PropPilot fonctionne sur invitation — votre abonnement est activé manuellement
                après signature de votre devis.<br><br>
                Si vous avez déjà échangé avec nous et souhaitez démarrer,
                contactez-nous ci-dessous.
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.link_button(
            "📅 Réserver un appel de démarrage",
            "https://calendly.com/contact-proppilot/appel-proppilot-20min",
            use_container_width=True,
            type="primary",
        )

        st.markdown("")

        st.markdown("""
        <div style="text-align: center; color: #94a3b8; font-size: 0.9rem;">
            Ou écrivez-nous directement :<br>
            <a href="mailto:contact@proppilot.fr"
               style="color: #60a5fa; font-weight: 600;">contact@proppilot.fr</a>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        if st.button("🚪 Déconnexion", use_container_width=False, key="_logout_btn_pending"):
            from dashboard.auth_cookies import clear_session as _cookie_clear
            _cookie_clear()
            for key in ["authenticated", "token", "user_id", "agency_name", "plan", "plan_active", "is_admin"]:
                st.session_state.pop(key, None)
            st.rerun()


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

    # Pré-sélection de l'onglet via query param ?auth=signup ou ?auth=login
    auth_param = st.query_params.get("auth", "login")

    with col:
        st.markdown(f"""
        <div style="text-align: center; padding: 40px 0 24px 0;">
            {_logo(56, "lp")}
            <h1 style="margin: 8px 0 4px 0; font-size: 2rem;">PropPilot</h1>
            <p style="color: #64748b; margin: 0;">L'IA pour les agences immobilières françaises</p>
        </div>
        """, unsafe_allow_html=True)

        # Ordonner les onglets selon le paramètre d'URL
        if auth_param == "signup":
            tab_signup, tab_login = st.tabs(["Créer mon compte", "Se connecter"])
        else:
            tab_login, tab_signup = st.tabs(["Se connecter", "Créer mon compte"])

        # ── Login ──────────────────────────────────────────────────────────────
        with tab_login:
            with st.form("form_login", clear_on_submit=False):
                email = st.text_input("Email", placeholder="vous@agence.fr")
                password = st.text_input("Mot de passe", type="password")
                remember = st.checkbox("Rester connecté 30 jours", value=True)
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
                        plan_active = result.get("plan_active", True)
                        uid = result.get("user_id", "")
                        aname = result.get("agency_name", email)
                        plan = result.get("plan", "Starter")
                        is_admin = result.get("is_admin", False)
                        token = result["access_token"]
                        _set_session(
                            token=token,
                            user_id=uid,
                            agency_name=aname,
                            plan=plan,
                            plan_active=plan_active,
                            is_admin=is_admin,
                            email=email,
                        )
                        if remember:
                            _cookie_save(uid, token, aname, plan, plan_active, is_admin, email)
                        if not plan_active:
                            st.session_state["plan_inactive_reason"] = "inactive"
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
                            plan_active = login_result.get("plan_active", result.get("plan_active", False))
                            _set_session(
                                token=login_result["access_token"],
                                user_id=login_result.get("user_id", result.get("user_id", "")),
                                agency_name=agency_name,
                                plan=login_result.get("plan", "Starter"),
                                plan_active=plan_active,
                                is_admin=login_result.get("is_admin", False),
                            )
                            if not plan_active:
                                st.session_state["plan_inactive_reason"] = "new_signup"
                            st.rerun()
                        else:
                            st.success("Compte créé. Connectez-vous dans l'onglet ci-contre.")

        st.markdown("""
        <div style="text-align: center; margin-top: 24px; color: #94a3b8; font-size: 12px;">
            60 Jours Satisfait ou Remboursé · Support email inclus
        </div>
        <div style="text-align: center; margin-top: 16px; color: #71717a; font-size: 11px; line-height: 1.6; padding: 0 8px;">
            Vous n'avez pas encore de compte ? PropPilot est en bêta privée.<br>
            <a href="https://proppilot.fr#waitlist"
               style="color: #a3e635; text-decoration: none;">
                Inscrivez-vous à la liste d'attente
            </a>
            pour un accès prioritaire au lancement.
        </div>
        """, unsafe_allow_html=True)


# ─── Garde mode démo ──────────────────────────────────────────────────────────

def require_non_demo() -> None:
    """Bloque la page pour les comptes démo (affiche message + st.stop)."""
    if st.session_state.get("is_demo", False):
        st.info("Cette fonctionnalité n'est pas disponible en mode démo.")
        st.stop()


# ─── Garde d'authentification ─────────────────────────────────────────────────

def require_auth(require_active_plan: bool = True) -> None:
    """
    Vérifie que l'utilisateur est authentifié (et, par défaut, que son plan est actif).

    Args:
        require_active_plan: Si True (défaut), redirige vers la sélection de forfait
                             quand plan_active=False. Passer False sur la page facturation
                             pour éviter une boucle de redirection.

    Doit être appelé APRÈS st.set_page_config().
    """
    # Rendre le cookie manager (nécessaire pour qu'il communique ses valeurs)
    get_cookie_manager()

    if not st.session_state.get("authenticated"):
        # Tentative de restauration depuis cookie
        saved = _cookie_load()
        if saved:
            _set_session(
                token=saved["token"],
                user_id=saved["user_id"],
                agency_name=saved["agency_name"],
                plan=saved["plan"],
                plan_active=saved["plan_active"],
                is_admin=saved["is_admin"],
                email=saved.get("email", ""),
            )
            st.rerun()

        show_auth_page()
        st.stop()

    if require_active_plan and not st.session_state.get("plan_active", True):
        _show_plan_selection()
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
    is_admin = st.session_state.get("is_admin", False)
    is_demo = st.session_state.get("is_demo", False)

    with st.sidebar:
        if is_admin:
            # Admin : sidebar réduite à la seule page Propriétaire
            st.markdown("""
<style>
/* Admin : masquer tout sauf propriétaire */
[data-testid="stSidebarNav"] li
  { display: none !important; }
[data-testid="stSidebarNav"] li:nth-child(1)
  { display: block !important; }
</style>
""", unsafe_allow_html=True)
        elif is_demo:
            # Mode démo : Pipeline, Leads, Conversations, Calendrier, Stats uniquement
            st.markdown("""
<style>
[data-testid="stSidebarNav"] a[href*="proprietaire"]  { display: none !important; }
[data-testid="stSidebarNav"] a[href*="admin"]          { display: none !important; }
[data-testid="stSidebarNav"] a[href*="utilisation"]    { display: none !important; }
[data-testid="stSidebarNav"] a[href*="annonce"]        { display: none !important; }
[data-testid="stSidebarNav"] a[href*="estimation"]     { display: none !important; }
[data-testid="stSidebarNav"] a[href*="parametres"]     { display: none !important; }
[data-testid="stSidebarNav"] a[href*="facturation"]    { display: none !important; }
[data-testid="stSidebarNav"] a[href*="integrations"]   { display: none !important; }
/* Masquer les nouvelles pages de l'auto-nav — gérées par les boutons ci-dessous */
[data-testid="stSidebarNav"] a[href*="tasks"]          { display: none !important; }
[data-testid="stSidebarNav"] a[href*="calls"]          { display: none !important; }
[data-testid="stSidebarNav"] a[href*="mes_leads"]      { display: none !important; }
</style>
""", unsafe_allow_html=True)
        else:
            # Client : masquer Propriétaire (admin only) et 07_admin (obsolète)
            st.markdown("""
<style>
/* Masquer propriétaire et admin pour les clients */
[data-testid="stSidebarNav"] li:nth-child(1)
  { display: none !important; }
[data-testid="stSidebarNav"] li:nth-child(8)
  { display: none !important; }
/* Sécurité supplémentaire — masquer par nom */
[data-testid="stSidebarNav"] a[href*="proprietaire"]
  { display: none !important; }
[data-testid="stSidebarNav"] a[href*="admin"]
  { display: none !important; }
/* Masquer les nouvelles pages de l'auto-nav — gérées par les boutons ci-dessous */
[data-testid="stSidebarNav"] a[href*="tasks"]     { display: none !important; }
[data-testid="stSidebarNav"] a[href*="calls"]     { display: none !important; }
[data-testid="stSidebarNav"] a[href*="mes_leads"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

        st.markdown(_logo(36, "sb"), unsafe_allow_html=True)
        plan_suffix = "" if is_demo else f" · {plan}"
        st.markdown(
            f"<div style='font-size:15px;font-weight:700;color:white;margin-top:4px;'>{agency_name}</div>"
            f"<div style='font-size:12px;color:#94a3b8;margin-bottom:16px;'>PropPilot{plan_suffix}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("---")

        if st.button("🏠 Accueil", use_container_width=True, key="_home_btn"):
            st.switch_page("app.py")

        if st.button("🚪 Déconnexion", use_container_width=True, key="_logout_btn"):
            _cookie_clear()
            for key in ["authenticated", "token", "user_id", "agency_name", "plan", "plan_active", "is_admin"]:
                st.session_state.pop(key, None)
            st.rerun()

        st.markdown("---")
        st.markdown(
            "<div style='color: #94a3b8; font-size: 12px; text-transform: uppercase; "
            "letter-spacing: 1px; margin-bottom: 6px;'>Navigation</div>",
            unsafe_allow_html=True,
        )

        if not is_admin:
            if st.button("📋 Tâches du jour", use_container_width=True, key="_nav_tasks"):
                st.switch_page("pages/tasks.py")
            if st.button("👥 Mes leads", use_container_width=True, key="_nav_leads"):
                st.switch_page("pages/01_mes_leads.py")
            if st.button("📞 Appels capturés", use_container_width=True, key="_nav_calls"):
                st.switch_page("pages/calls.py")
            st.markdown(
                "<div style='color: #94a3b8; font-size: 11px; margin: 8px 0 4px 0; "
                "text-transform: uppercase; letter-spacing: 1px;'>Outils</div>",
                unsafe_allow_html=True,
            )
