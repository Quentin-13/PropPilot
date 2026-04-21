"""
Page Facturation — Abonnement Stripe.
Affiche le plan actuel, les 4 forfaits disponibles et les boutons de souscription/gestion.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings

st.set_page_config(page_title="Abonnement — PropPilot", layout="wide", page_icon="💳")

from dashboard.auth_ui import require_auth, render_sidebar_logout, require_non_demo
require_auth(require_active_plan=False)
require_non_demo()
render_sidebar_logout()

settings = get_settings()

st.title("💳 Abonnement")

st.markdown("## Votre abonnement")
st.markdown(
    "Votre forfait est configuré sur mesure "
    "selon votre volume de leads."
)
st.markdown("---")
st.markdown("### Vous souhaitez faire évoluer votre abonnement ?")
st.markdown(
    "Réservez un appel de 20 minutes avec Quentin "
    "pour discuter de vos besoins."
)
st.link_button(
    "📅 Réserver un appel",
    "https://calendly.com/contact-proppilot/appel-proppilot-20min",
    use_container_width=True,
)
st.markdown("---")
st.markdown(
    "📩 Ou contactez-nous directement : "
    "contact@proppilot.fr"
)
