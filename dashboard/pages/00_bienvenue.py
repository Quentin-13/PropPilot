"""
Page bienvenue — premier login client PropPilot.

Affichée si users.welcome_seen_at IS NULL.
Le bouton "J'ai compris" pose welcome_seen_at et redirige vers le cockpit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout
from dashboard.lib.admin_auth import is_super_admin

settings = get_settings()

st.set_page_config(
    page_title="Bienvenue — PropPilot",
    layout="wide",
    page_icon="🏠",
)

require_auth()
render_sidebar_logout()

# Super-admin et admins agence n'ont pas besoin de la page bienvenue
if is_super_admin(st.session_state.get("email", "")):
    st.switch_page("pages/99_admin.py")

client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── Chargement du contexte ───────────────────────────────────────────────────

from memory.phone_numbers import (
    assign_available_phone_number,
    get_client_welcome_context,
    mark_welcome_seen,
)

# Tente d'assigner un numéro si le client n'en a pas encore
assign_available_phone_number(client_id)

ctx = get_client_welcome_context(client_id)
phone_number  = ctx["phone_number"]
crm_label     = ctx["crm_label"]
crm_status    = ctx["crm_status"]
crm_last_sync = ctx["crm_last_sync_at"]

# ─── CSS ─────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.main { background: #0f1117; }
.block-container { padding-top: 2rem; max-width: 860px; }
h1, h2, h3 { color: white !important; }
[data-testid="stSidebar"] { background: #1a3a5c; }
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label { color: white !important; }

.welcome-section {
    background: #1e2130;
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
    border-left: 4px solid #3b82f6;
}
.welcome-section.green  { border-left-color: #10b981; }
.welcome-section.yellow { border-left-color: #f59e0b; }
.welcome-section.slate  { border-left-color: #475569; }

.number-box {
    background: #0f1117;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 14px 20px;
    font-size: 1.5rem;
    font-weight: 800;
    color: white;
    letter-spacing: 0.06em;
    display: inline-block;
    margin: 12px 0;
    font-family: monospace;
}
.check-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 6px 0;
    color: #cbd5e1;
    font-size: 0.95rem;
}
.check-icon { color: #10b981; font-size: 1rem; margin-top: 1px; }
.section-head {
    font-size: 1.05rem;
    font-weight: 700;
    color: white;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ─── Titre ───────────────────────────────────────────────────────────────────

agency_name = st.session_state.get("agency_name") or ""
prenom = agency_name.split()[0] if agency_name else ""
greeting = f"Bienvenue{', ' + prenom if prenom else ''} 👋"

st.title(greeting)
st.markdown(
    '<p style="color:#8892a4;font-size:1.05rem;margin-top:-8px;margin-bottom:28px;">'
    "PropPilot est la mémoire automatique de votre agence.</p>",
    unsafe_allow_html=True,
)

# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Numéro PropPilot
# ════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="welcome-section green">', unsafe_allow_html=True)
st.markdown('<div class="section-head">Votre numéro PropPilot</div>', unsafe_allow_html=True)

if phone_number:
    st.markdown(
        f'<div class="number-box">{phone_number}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="color:#94a3b8;margin-top:4px;margin-bottom:0;">'
        "Utilisez ce numéro sur les annonces ou le flux de leads du pilote.</p>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<p style="color:#94a3b8;margin-bottom:0;">'
        "Votre numéro PropPilot est en cours d'attribution. "
        "L'équipe PropPilot vous contacte rapidement.</p>",
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Les échanges du pilote
# ════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="welcome-section">', unsafe_allow_html=True)
st.markdown('<div class="section-head">Les échanges du pilote</div>', unsafe_allow_html=True)
st.markdown(
    '<p style="color:#94a3b8;margin-bottom:14px;">'
    "Pour que la mémoire soit complète, les appels entrants, les rappels sortants "
    "et les SMS du périmètre pilote doivent passer par PropPilot.</p>",
    unsafe_allow_html=True,
)

for item in [
    "Appels entrants sur le numéro PropPilot",
    "Appels sortants passés depuis PropPilot",
    "SMS envoyés et reçus depuis PropPilot",
]:
    st.markdown(
        f'<div class="check-item">'
        f'<span class="check-icon">✓</span>'
        f'<span>{item}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CRM
# ════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="welcome-section yellow">', unsafe_allow_html=True)
st.markdown('<div class="section-head">Votre CRM</div>', unsafe_allow_html=True)

def _short_crm_name(label: str) -> str:
    """Extrait le nom court du CRM pour le texte d'intro (ex : 'Hektor (La Boîte Immo)' → 'Hektor').
    Retourne 'Votre CRM' si le CRM n'est pas configuré ou si ce n'est pas un CRM traditionnel."""
    if not label:
        return "Votre CRM"
    short = label.split("(")[0].strip()
    if short in ("Email", "Import CSV"):
        return "Votre CRM"
    return short or "Votre CRM"

_crm_name = _short_crm_name(crm_label)

st.markdown(
    f'<p style="color:#94a3b8;margin-bottom:14px;">'
    f"{_crm_name} reste votre outil principal. PropPilot vient l'alimenter "
    f"automatiquement avec les résumés et informations clés détectées dans "
    f"les appels et SMS du pilote.</p>",
    unsafe_allow_html=True,
)

if crm_status == "active":
    from dashboard.utils.datetime_helpers import fmt_paris_datetime
    sync_str = fmt_paris_datetime(crm_last_sync, "%d/%m à %H:%M") if crm_last_sync else ""
    sync_span = (
        f'<span style="color:#64748b;font-size:0.85rem;">· Dernière sync {sync_str}</span>'
        if sync_str else ""
    )
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
        f'<span style="color:#10b981;font-weight:700;">&#9679; Remontée CRM active</span>'
        f'{sync_span}'
        f'</div>',
        unsafe_allow_html=True,
    )
    if crm_label:
        st.caption(f"CRM : {crm_label}")

elif crm_status == "configured":
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
        '<span style="color:#f59e0b;font-weight:700;">● En cours de configuration</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    if crm_label:
        st.caption(f"CRM : {crm_label}")

else:
    # none ou error → message rassurant, pas de détail technique
    st.markdown(
        '<p style="color:#94a3b8;margin-bottom:0;">'
        "La remontée vers votre CRM est en cours de configuration. "
        "L'équipe PropPilot vous accompagne pendant le pilote.</p>",
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Ce que PropPilot fait automatiquement
# ════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="welcome-section slate">', unsafe_allow_html=True)
st.markdown('<div class="section-head">Ce que PropPilot fait automatiquement</div>', unsafe_allow_html=True)

for item in [
    "Résumé automatique de chaque appel et SMS",
    "Informations détectées : projet, budget, délai, motivation",
    "Prochaine action recommandée pour chaque prospect",
    "Remontée CRM des informations clés",
]:
    st.markdown(
        f'<div class="check-item">'
        f'<span class="check-icon">→</span>'
        f'<span>{item}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Besoin d'aide
# ════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="welcome-section slate">', unsafe_allow_html=True)
st.markdown("<div class=\"section-head\">Besoin d'aide ?</div>", unsafe_allow_html=True)
st.markdown(
    '<p style="color:#94a3b8;margin-bottom:12px;">'
    'Contactez-nous à '
    '<a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>'
    "</p>",
    unsafe_allow_html=True,
)

_calendly = "https://calendly.com/contact-proppilot/appel-proppilot-20min"
st.link_button("Réserver un appel de 20 min", _calendly, use_container_width=False)

st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# Bouton final
# ════════════════════════════════════════════════════════════════════════════

st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

if st.button("J'ai compris, voir mon cockpit", type="primary", use_container_width=True):
    mark_welcome_seen(client_id)
    st.switch_page("pages/tasks.py")
