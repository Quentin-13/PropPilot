"""
Dashboard Streamlit — Page d'accueil client.
Initialise la DB, vérifie l'auth, affiche le tableau de bord personnalisé.
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

# ─── CSS global ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main { background: #0f1117; }
.block-container { padding-top: 2rem; max-width: 1200px; }
h1, h2, h3 { color: white !important; }

/* Sidebar */
[data-testid="stSidebar"] { background: #1a3a5c; }
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio label { color: white !important; }

/* Metric containers */
.stMetric { background: #1e2130; border-radius: 12px; padding: 16px; }
[data-testid="metric-container"] {
    background: #1e2130;
    border-radius: 12px;
    padding: 16px;
    border-left: 4px solid #3b82f6;
}

/* KPI cards */
.kpi-card {
    background: #1e2130;
    border-radius: 12px;
    padding: 20px 24px;
    height: 100%;
}
.kpi-value {
    font-size: 2.5rem;
    font-weight: 800;
    line-height: 1.1;
    margin: 4px 0;
}
.kpi-label {
    font-size: 0.85rem;
    color: #8892a4;
    margin: 0;
}
.kpi-icon {
    font-size: 1.4rem;
    margin-bottom: 4px;
    display: block;
}

/* Agent cards */
.agent-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 16px;
    height: 100%;
    border-left: 4px solid #334155;
}
.agent-card.active { border-left-color: #10b981; }
.agent-card.pending { border-left-color: #f59e0b; }
.agent-name {
    font-size: 1rem;
    font-weight: 700;
    color: white;
    margin-bottom: 2px;
}
.agent-status-active { color: #10b981; font-size: 0.8rem; font-weight: 600; }
.agent-status-pending { color: #f59e0b; font-size: 0.8rem; font-weight: 600; }
.agent-desc {
    font-size: 0.78rem;
    color: #8892a4;
    margin-top: 4px;
}

/* Checklist steps */
.step-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 8px;
    border-left: 4px solid #475569;
    display: flex;
    align-items: center;
    gap: 12px;
}
.step-card.done { border-left-color: #10b981; }

/* Score badges */
.badge-hot  { background:#e74c3c; color:white; padding:2px 8px; border-radius:12px; font-size:12px; }
.badge-warm { background:#e67e22; color:white; padding:2px 8px; border-radius:12px; font-size:12px; }
.badge-cold { background:#3498db; color:white; padding:2px 8px; border-radius:12px; font-size:12px; }

/* Progress bars */
.quota-bar-wrap { margin-bottom: 18px; }
.quota-label { font-size: 0.85rem; color: #cbd5e1; margin-bottom: 4px; }
.quota-sub   { font-size: 0.75rem; color: #64748b; }

/* Section titles */
.section-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: white;
    margin: 0 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e2130;
}

/* Plan badge */
.badge-plan-active   { background:#10b981; color:white; padding:3px 10px; border-radius:20px; font-size:0.8rem; font-weight:600; }
.badge-plan-inactive { background:#ef4444; color:white; padding:3px 10px; border-radius:20px; font-size:0.8rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ─── Auth ──────────────────────────────────────────────────────────────────────
from dashboard.auth_ui import render_sidebar_logout, require_auth

require_auth()

# Redirect admin
if st.session_state.get("is_admin", False):
    st.switch_page("pages/00_proprietaire.py")

render_sidebar_logout()

# ─── Données de session ────────────────────────────────────────────────────────
client_id  = st.session_state.get("user_id", settings.agency_client_id)
tier       = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", "") or "votre agence"
plan_active = st.session_state.get("plan_active", True)

# ─── Chargement données ────────────────────────────────────────────────────────
from memory.lead_repository import get_pipeline_stats, get_leads_by_client
from memory.usage_tracker import get_usage_summary
from datetime import datetime

JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
MOIS  = ["janvier","février","mars","avril","mai","juin",
         "juillet","août","septembre","octobre","novembre","décembre"]

stats  = get_pipeline_stats(client_id)
usage  = get_usage_summary(client_id, tier)
leads  = get_leads_by_client(client_id, limit=5)
leads_count = stats.get("total", 0)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 1 — Header
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 56" width="160" height="45">
  <g transform="translate(0,0)">
    <polygon points="28,0 53,14 53,42 28,56 3,42 3,14" fill="#0d1f3c"/>
    <line x1="3" y1="28" x2="53" y2="28" stroke="#1e3a6e" stroke-width="0.8"/>
    <line x1="28" y1="0" x2="28" y2="56" stroke="#1e3a6e" stroke-width="0.8"/>
    <polygon points="28,11 42,24 14,24" fill="none" stroke="white" stroke-width="1.6"/>
    <rect x="16" y="24" width="25" height="20" fill="none" stroke="white" stroke-width="1.6"/>
    <rect x="19" y="27" width="8" height="7" fill="#3b82f6" rx="1"/>
    <rect x="30" y="27" width="8" height="7" fill="#3b82f6" rx="1"/>
    <rect x="23" y="32" width="11" height="12" fill="#1e40af" rx="1"/>
    <circle cx="28" cy="16" r="3" fill="#e67e22"/>
    <circle cx="3" cy="14" r="2" fill="#3b82f6"/>
    <circle cx="53" cy="14" r="2" fill="#3b82f6"/>
    <circle cx="3" cy="42" r="2" fill="#3b82f6"/>
    <circle cx="53" cy="42" r="2" fill="#3b82f6"/>
  </g>
  <text x="65" y="30" font-family="Arial" font-size="22" font-weight="900"
        fill="white" letter-spacing="-0.5">Prop</text>
  <text x="120" y="30" font-family="Arial" font-size="22" font-weight="300"
        fill="#3b82f6" letter-spacing="2">Pilot</text>
  <rect x="65" y="34" width="118" height="2" fill="#e67e22" rx="1"/>
</svg>"""

now = datetime.now()
date_fr = f"{JOURS[now.weekday()]} {now.day} {MOIS[now.month-1]} {now.year} · {now.strftime('%H:%M')}"

prenom = agency_name.split()[0] if agency_name and agency_name != "votre agence" else ""
greeting = f"Bonjour, {prenom} 👋" if prenom else "Bonjour 👋"

badge_class = "badge-plan-active" if plan_active else "badge-plan-inactive"
badge_label = "Actif" if plan_active else "Inactif"

st.markdown(f"""
<div style="margin-bottom:16px;">{_LOGO_SVG}</div>
""", unsafe_allow_html=True)

st.title(greeting)

st.markdown(f"""
<div style="display:flex; align-items:center; justify-content:space-between;
            flex-wrap:wrap; gap:12px; margin-bottom:28px; margin-top:-12px;">
  <p style="margin:0; color:#8892a4; font-size:0.9rem;">{date_fr}</p>
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="color:#cbd5e1; font-size:0.9rem;">Forfait <strong style="color:white;">{tier}</strong></span>
    <span class="{badge_class}">{badge_label}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 2 — Checklist démarrage (si aucun lead)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if leads_count == 0:
    st.markdown('<p class="section-title">🚀 Prêt à décoller ? 3 étapes pour démarrer</p>',
                unsafe_allow_html=True)

    st.markdown("""
<a href="/11_integrations" target="_self" style="
  display:block; padding:16px 20px; margin-bottom:8px;
  background:#1e2130; border-radius:10px;
  border-left:4px solid #3b82f6; text-decoration:none;
  color:white; font-weight:600;">
  ☐ 1. Connecter votre première source de leads →
</a>
<a href="/06_settings" target="_self" style="
  display:block; padding:16px 20px; margin-bottom:8px;
  background:#1e2130; border-radius:10px;
  border-left:4px solid #3b82f6; text-decoration:none;
  color:white; font-weight:600;">
  ☐ 2. Configurer votre agence →
</a>
<a href="/08_calendar" target="_self" style="
  display:block; padding:16px 20px; margin-bottom:8px;
  background:#1e2130; border-radius:10px;
  border-left:4px solid #3b82f6; text-decoration:none;
  color:white; font-weight:600;">
  ☐ 3. Connecter Google Calendar →
</a>
""", unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom:28px;'></div>", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 3 — KPIs du mois
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown('<p class="section-title">📊 Ce mois-ci</p>', unsafe_allow_html=True)

total_leads = stats.get("total", 0)
rdv_count   = stats.get("rdv_count", 0)
mandat_count = stats.get("mandat_count", 0)
roi_estime  = mandat_count * 3000

col1, col2, col3, col4 = st.columns(4)
kpis = [
    (col1, "📥 Leads ce mois",  total_leads,                  "#3b82f6", "leads reçus"),
    (col2, "📅 RDV bookés",     rdv_count,                    "#10b981", "rendez-vous confirmés"),
    (col3, "📋 Mandats",        mandat_count,                 "#f59e0b", "mandats signés"),
    (col4, "💰 ROI estimé",     f"{roi_estime:,.0f} €".replace(",", " "), "#8b5cf6", "CA généré estimé"),
]
for col, label, value, color, subtitle in kpis:
    with col:
        st.markdown(f"""
        <div style="background:#1e2130;border-radius:12px;padding:20px;
                    border-left:4px solid {color};">
            <div style="font-size:0.85rem;color:#8892a4;margin-bottom:8px;">{label}</div>
            <div style="font-size:2.2rem;font-weight:800;color:white;">{value}</div>
            <div style="font-size:0.75rem;color:#8892a4;margin-top:4px;">{subtitle}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:32px;'></div>", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 4 — Statut des 7 agents
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown('<p class="section-title">🤖 Vos agents IA</p>', unsafe_allow_html=True)

_twilio_ok      = settings.twilio_available
_elevenlabs_ok  = settings.elevenlabs_available
_openai_ok      = settings.openai_available
# Google Calendar : actif si token présent en session (OAuth flow)
_calendar_ok    = bool(st.session_state.get("google_calendar_token"))

def _agent_card_html(emoji: str, name: str, active: bool, status_label: str, desc: str) -> str:
    card_class = "active" if active else "pending"
    status_class = "agent-status-active" if active else "agent-status-pending"
    return f"""
    <div class="agent-card {card_class}">
        <div class="agent-name">{emoji} {name}</div>
        <div class="{status_class}">{status_label}</div>
        <div class="agent-desc">{desc}</div>
    </div>
    """

agents = [
    {
        "emoji": "🎯", "name": "Léa",
        "active": _calendar_ok,
        "status": "Actif 🟢" if _calendar_ok else "En attente configuration 🟡",
        "desc": "Qualification leads & prise de RDV automatique",
    },
    {
        "emoji": "💬", "name": "Marc",
        "active": _twilio_ok,
        "status": "Actif 🟢" if _twilio_ok else "En attente SIRET Twilio 🟡",
        "desc": "Nurturing SMS & WhatsApp multi-canal",
    },
    {
        "emoji": "📞", "name": "Sophie",
        "active": _twilio_ok and _elevenlabs_ok,
        "status": "Actif 🟢" if (_twilio_ok and _elevenlabs_ok) else "En attente configuration 🟡",
        "desc": "Appels voix sortants & entrants en français",
    },
    {
        "emoji": "✍️", "name": "Hugo",
        "active": True,
        "status": "Actif 🟢",
        "desc": "Rédaction annonces SEO & compromis Hoguet",
    },
    {
        "emoji": "🏠", "name": "Camille",
        "active": _openai_ok,
        "status": "Actif 🟢" if _openai_ok else "Bientôt disponible 🟡",
        "desc": "Staging virtuel DALL-E — intérieur français 2026",
    },
    {
        "emoji": "📊", "name": "Thomas",
        "active": True,
        "status": "Actif 🟢",
        "desc": "Estimation DVF + rapport PDF loi Hoguet",
    },
    {
        "emoji": "📈", "name": "Julie",
        "active": True,
        "status": "Actif 🟢",
        "desc": "Détection anomalies dossier & alertes financement",
    },
]

row1 = st.columns(4)
row2 = st.columns(3)

for col, agent in zip(row1, agents[:4]):
    with col:
        st.markdown(_agent_card_html(
            agent["emoji"], agent["name"], agent["active"],
            agent["status"], agent["desc"]
        ), unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

for col, agent in zip(row2, agents[4:]):
    with col:
        st.markdown(_agent_card_html(
            agent["emoji"], agent["name"], agent["active"],
            agent["status"], agent["desc"]
        ), unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:32px;'></div>", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 5 — Activité récente (si leads existants)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if leads_count > 0 and leads:
    st.markdown('<p class="section-title">⚡ Activité récente</p>', unsafe_allow_html=True)

    def _score_badge(score: int | None) -> str:
        s = score or 0
        if s >= 7:
            return f'<span class="badge-hot">{s}</span>'
        if s >= 4:
            return f'<span class="badge-warm">{s}</span>'
        return f'<span class="badge-cold">{s}</span>'

    header = """
    <div style="display:grid; grid-template-columns:2fr 1.5fr 80px 1.5fr 1.2fr;
                gap:8px; padding:8px 12px; color:#64748b; font-size:0.78rem;
                font-weight:600; text-transform:uppercase; letter-spacing:0.05em;
                border-bottom:1px solid #1e2130; margin-bottom:4px;">
        <span>Contact</span><span>Source</span><span>Score</span>
        <span>Statut</span><span>Date</span>
    </div>
    """
    rows_html = ""
    for lead in leads[:5]:
        prenom  = lead.prenom or ""
        nom     = lead.nom or ""
        source  = lead.source.value if hasattr(lead.source, "value") else str(lead.source)
        score   = lead.score
        statut  = lead.statut.value if hasattr(lead.statut, "value") else str(lead.statut)
        created = lead.created_at.strftime("%d/%m") if lead.created_at else "—"

        rows_html += f"""
        <div style="display:grid; grid-template-columns:2fr 1.5fr 80px 1.5fr 1.2fr;
                    gap:8px; padding:10px 12px; background:#1e2130; border-radius:8px;
                    margin-bottom:4px; align-items:center; font-size:0.88rem; color:#e2e8f0;">
            <span style="font-weight:600;">{prenom} {nom}</span>
            <span style="color:#94a3b8;">{source}</span>
            <span>{_score_badge(score)}</span>
            <span style="color:#94a3b8;">{statut}</span>
            <span style="color:#64748b;">{created}</span>
        </div>
        """

    st.markdown(header + rows_html, unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:32px;'></div>", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOC 6 — Quota bar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown('<p class="section-title">📦 Utilisation du mois</p>', unsafe_allow_html=True)

voice_used  = usage["voice"]["used"]
voice_limit = usage["voice"]["limit"]
voice_pct   = usage["voice"]["pct"] / 100

sms_used    = usage["followups"]["used"]
sms_limit   = usage["followups"]["limit"]
sms_pct     = usage["followups"]["pct"] / 100

col_v, col_s = st.columns(2)

with col_v:
    voice_limit_label = f"{int(voice_limit)} min" if voice_limit else "Illimité"
    st.markdown(f"""
    <div class="quota-bar-wrap">
        <div class="quota-label">🎙 Minutes voix
            <span class="quota-sub" style="float:right;">{voice_used} / {voice_limit_label}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if voice_limit:
        st.progress(min(voice_pct, 1.0))
    else:
        st.progress(0.0)

with col_s:
    sms_limit_label = f"{int(sms_limit)}" if sms_limit else "Illimité"
    st.markdown(f"""
    <div class="quota-bar-wrap">
        <div class="quota-label">💬 Follow-ups SMS
            <span class="quota-sub" style="float:right;">{sms_used} / {sms_limit_label}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if sms_limit:
        st.progress(min(sms_pct, 1.0))
    else:
        st.progress(0.0)

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:40px;'></div>", unsafe_allow_html=True)
st.markdown(
    f"<div style='text-align:center; color:#475569; font-size:12px;'>"
    f"PropPilot · Forfait {tier} · "
    f"<a href='mailto:hello@proppilot.fr' style='color:#475569;'>hello@proppilot.fr</a>"
    f"</div>",
    unsafe_allow_html=True,
)
