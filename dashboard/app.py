"""
Dashboard Streamlit — Point d'entrée principal.
Initialise la DB, vérifie l'auth, configure le thème, affiche la navigation.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

# Init DB au démarrage
from memory.database import init_database
init_database()

from config.settings import get_settings
settings = get_settings()

# ─── Configuration Streamlit ───────────────────────────────────────────────────
st.set_page_config(
    page_title="PropPilot",
    page_icon="https://proppilot-production.up.railway.app/static/favicon.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS personnalisé ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Sidebar */
[data-testid="stSidebar"] {
    background: #1a3a5c;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio label {
    color: white !important;
}

/* Metric cards */
div[data-testid="metric-container"] {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 16px;
}

/* Score badges */
.badge-hot { background: #e74c3c; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.badge-warm { background: #e67e22; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.badge-cold { background: #3498db; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; }

/* Progress bars couleur */
.usage-low { --progress-color: #27ae60; }
.usage-medium { --progress-color: #f39c12; }
.usage-high { --progress-color: #e74c3c; }

/* Alert banners */
.alert-orange {
    background: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 8px 0;
}
.alert-red {
    background: #f8d7da;
    border: 1px solid #dc3545;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 8px 0;
}
</style>
""", unsafe_allow_html=True)

# ─── Auth ──────────────────────────────────────────────────────────────────────
from dashboard.auth_ui import render_sidebar_logout, require_auth

require_auth()

# ─── Redirect admin vers page Propriétaire ────────────────────────────────────
if st.session_state.get("is_admin", False):
    st.switch_page("pages/00_proprietaire.py")

# ─── Sidebar ──────────────────────────────────────────────────────────────────
render_sidebar_logout()

# ─── Données de session ────────────────────────────────────────────────────────
client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

# ─── Page d'accueil ───────────────────────────────────────────────────────────
st.title(f"PropPilot — {agency_name}")
st.markdown(f"**Forfait {tier}** · Bienvenue dans votre tableau de bord")

st.markdown("---")

# KPIs rapides
from memory.lead_repository import get_pipeline_stats
from memory.usage_tracker import get_usage_summary
from datetime import datetime

col1, col2, col3, col4 = st.columns(4)
stats = get_pipeline_stats(client_id)
usage = get_usage_summary(client_id, tier)

with col1:
    total_leads = stats.get("total", 0)
    st.metric("Leads ce mois", total_leads, delta=None)

with col2:
    rdv = stats.get("rdv_count", 0)
    st.metric("RDV bookés", rdv, help="RDV pris ce mois")

with col3:
    mandats = stats.get("mandat_count", 0)
    st.metric("Mandats", mandats, help="Mandats gagnés ce mois")

with col4:
    leads_used = usage["leads"]["used"]
    leads_limit = usage["leads"]["limit"] or "∞"
    st.metric("Leads qualifiés", f"{leads_used}/{leads_limit}", help="Quota mensuel leads")

st.markdown("---")

# Navigation rapide
st.markdown("### Accès rapide")
col_a, col_b, col_c = st.columns(3)

with col_a:
    st.info("📋 **Pipeline Leads**\nGerez vos leads entrants, qualifiés et en nurturing.\n\n→ *Page Leads*")

with col_b:
    st.info("📊 **Usage & Limites**\nSuivez votre consommation mensuelle par fonctionnalité.\n\n→ *Page Usage*")

with col_c:
    st.info("💰 **ROI & Performance**\nMandats, RDV, taux de conversion et garantie remboursement.\n\n→ *Page ROI*")

st.markdown("---")

# Témoignages
st.markdown("### Ils utilisent PropPilot")
t_col1, t_col2, t_col3 = st.columns(3)

with t_col1:
    st.markdown("""
    > *"+4 mandats en 45 jours, zéro configuration de notre côté.
    Le LeadQualifier répond à 23h quand on dort. ROI x8 dès le 2ème mois."*

    **Claire M.** — Agence Centrale Lyon
    """)

with t_col2:
    st.markdown("""
    > *"Avant je perdais 30% de mes leads faute de temps pour rappeler.
    Maintenant l'IA qualifie et je n'appelle que les hot leads.
    CA +35% en 60 jours."*

    **Thomas R.** — Mandataire IAD Bordeaux
    """)

with t_col3:
    st.markdown("""
    > *"Le ListingGenerator rédige mieux que moi.
    Chaque annonce est prête en 30 secondes, SEO optimisé,
    mes biens se vendent 15% plus vite."*

    **Sophie L.** — Immo Services Toulouse
    """)

# Footer
st.markdown("---")
st.markdown(
    f"<div style='text-align: center; color: #888; font-size: 12px;'>"
    f"PropPilot · Forfait {tier} · "
    f"<a href='mailto:hello@proppilot.fr'>hello@proppilot.fr</a>"
    f"</div>",
    unsafe_allow_html=True,
)
