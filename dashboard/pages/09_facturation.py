"""
Page Facturation — Abonnement Stripe.
Affiche le plan actuel, les 4 forfaits disponibles et les boutons de souscription/gestion.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import streamlit as st

from config.settings import get_settings
from memory.stripe_billing import PLAN_FEATURES

st.set_page_config(page_title="Facturation — PropPilot", layout="wide", page_icon="💳")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth(require_active_plan=False)
render_sidebar_logout()

settings = get_settings()
token = st.session_state.get("token", "")
user_id = st.session_state.get("user_id", "")
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("💳 Facturation & Abonnement")
st.markdown(f"**{agency_name}** · Forfait actuel : **{tier}**")


# ─── Helpers API ──────────────────────────────────────────────────────────────

def _api_headers() -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create_checkout(plan_name: str, engagement: bool = True) -> dict:
    base = settings.api_url.rstrip("/")
    try:
        resp = httpx.post(
            f"{base}/stripe/create-checkout-session",
            json={
                "plan": plan_name,
                "engagement": engagement,
                "success_url": "https://proppilot-dashboard-production.up.railway.app/10_success",
                "cancel_url": "https://proppilot-dashboard-production.up.railway.app/09_facturation",
            },
            headers=_api_headers(),
            timeout=10.0,
        )
        data = resp.json()
        if not resp.is_success:
            return {"error": data.get("detail", f"Erreur HTTP {resp.status_code}")}
        return data
    except Exception as e:
        return {"error": str(e)}


def _get_portal() -> dict:
    base = settings.api_url.rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/stripe/portal",
            headers=_api_headers(),
            timeout=10.0,
        )
        data = resp.json()
        if not resp.is_success:
            return {"error": data.get("detail", f"Erreur HTTP {resp.status_code}")}
        return data
    except Exception as e:
        return {"error": str(e)}


def _redirect(url: str) -> None:
    """Redirige le navigateur vers une URL externe."""
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={url}">',
        unsafe_allow_html=True,
    )
    st.info(f"Redirection en cours… [Cliquez ici si la redirection ne se lance pas]({url})")


# ─── Bannière plan inactif ────────────────────────────────────────────────────

# Vérification plan_active via API
try:
    _status_resp = httpx.get(
        f"{settings.api_url.rstrip('/')}/api/status",
        headers=_api_headers(),
        timeout=5.0,
    )
    plan_active = _status_resp.status_code != 402
except Exception:
    plan_active = True  # En cas d'erreur réseau, on suppose actif

if not plan_active:
    st.markdown("""
    <div style="background: #e74c3c; color: white; padding: 20px; border-radius: 10px;
                margin-bottom: 24px; text-align: center;">
        <strong style="font-size: 18px;">🚫 Abonnement inactif</strong><br>
        Votre accès aux agents IA est suspendu. Souscrivez à un forfait pour reprendre.
    </div>
    """, unsafe_allow_html=True)

# ─── Bouton portail Stripe ────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### Gérer mon abonnement")

col_portal, _ = st.columns([2, 3])
with col_portal:
    if st.button("🔧 Gérer mon abonnement Stripe", use_container_width=True):
        with st.spinner("Ouverture du portail Stripe…"):
            result = _get_portal()
        portal_url = result.get("portal_url")
        if "error" in result or not portal_url:
            st.error(f"Erreur : {result.get('error', 'Réponse inattendue du serveur.')}")
        else:
            _redirect(portal_url)

st.markdown("---")

# ─── Grille des 4 forfaits ────────────────────────────────────────────────────

st.markdown("### Choisir un forfait")
st.markdown("Tous les agents IA inclus dès le premier forfait. Seules les limites mensuelles diffèrent.")
st.markdown("")

# ── Toggle engagement ──────────────────────────────────────────────────────────
engagement_option = st.radio(
    "Type d'engagement",
    options=["Engagement 1 an", "Sans engagement"],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)
engagement = engagement_option == "Engagement 1 an"

if engagement:
    st.markdown(
        '<div style="background:#d4edda;color:#155724;padding:10px 18px;border-radius:8px;'
        'margin-bottom:16px;font-weight:600;">💰 Économisez jusqu\'à 7 200€/an avec l\'engagement 1 an</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div style="background:#fff3cd;color:#856404;padding:10px 18px;border-radius:8px;'
        'margin-bottom:16px;font-weight:600;">🔓 Résiliable à tout moment — sans frais</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

col1, col2, col3, col4 = st.columns(4)
cols = [col1, col2, col3, col4]
plan_names = ["Indépendant", "Starter", "Pro", "Elite"]

for col, plan_name in zip(cols, plan_names):
    features = PLAN_FEATURES[plan_name]
    is_current = plan_name == tier
    border = "#1a3a5c" if is_current else "#e9ecef"
    badge = " ✓ Actuel" if is_current else ""

    prix_affiche = features["prix_engagement"] if engagement else features["prix_no_commit"]
    economie = features["economie_annuelle"]
    engagement_label = "Engagement 12 mois" if engagement else "Sans engagement"
    voix_sms = features["voix"] + " voix &middot; " + features["sms"]

    if engagement:
        badge_economie = (
            '<div style="background:#d4edda;color:#155724;font-size:11px;font-weight:700;'
            'border-radius:5px;padding:3px 8px;display:inline-block;margin-bottom:6px;">'
            + "Économie " + economie + "</div>"
        )
    else:
        badge_economie = ""

    features_html = "".join(
        "<div>\u2705 " + feat + "</div>" for feat in features["features"][:6]
    )

    card_html = (
        '<div style="border: 2px solid ' + border + '; border-radius: 10px; padding: 20px;'
        ' text-align: center; min-height: 380px;">'
        '<div style="font-size: 18px; font-weight: 800; color: #1a3a5c;">' + plan_name + badge + "</div>"
        + badge_economie
        + '<div style="font-size: 28px; font-weight: 900; color: #e67e22; margin: 10px 0 2px 0;">' + prix_affiche + "</div>"
        '<div style="font-size: 11px; color: #888; margin-bottom: 10px;">' + engagement_label + "</div>"
        '<div style="font-size: 13px; color: #555; margin-bottom: 12px;">' + voix_sms + "</div>"
        '<div style="text-align: left; font-size: 13px; color: #333;">' + features_html + "</div>"
        "</div>"
    )

    with col:
        st.markdown(card_html, unsafe_allow_html=True)

        st.markdown("")
        btn_label = "✓ Forfait actuel" if is_current else f"Choisir {plan_name}"
        btn_disabled = is_current

        if not btn_disabled:
            if st.button(btn_label, key=f"checkout_{plan_name}", use_container_width=True, type="primary"):
                with st.spinner(f"Préparation du paiement {plan_name}…"):
                    result = _create_checkout(plan_name, engagement=engagement)
                checkout_url = result.get("checkout_url")
                if "error" in result or not checkout_url:
                    st.error(f"Erreur : {result.get('error', 'Réponse inattendue du serveur.')}")
                else:
                    _redirect(checkout_url)
        else:
            st.button(btn_label, key=f"checkout_{plan_name}", use_container_width=True, disabled=True)

# ─── Garantie ROI ─────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("""
### 🛡️ 60 Jours Satisfait ou Remboursé
Si vous n'êtes pas satisfait dans les 60 jours suivant votre inscription,
nous vous remboursons intégralement. Sans questions.

**Contact :** [contact@proppilot.fr](mailto:contact@proppilot.fr)
""")
