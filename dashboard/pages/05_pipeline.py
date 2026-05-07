"""
Page Pipeline — vue kanban par statut, séparée vendeur / acheteur.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime, timedelta

from config.settings import get_settings
from dashboard.utils.datetime_helpers import fmt_paris_datetime
from memory.lead_repository import get_leads_by_client, get_pipeline_stats
from memory.models import LeadStatus

settings = get_settings()

st.set_page_config(
    page_title="Pipeline — PropPilot",
    layout="wide",
    page_icon="📊",
)

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("📊 Pipeline")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── Filtres ─────────────────────────────────────────────────────────────────

filt_col1, filt_col2 = st.columns([1, 3])
with filt_col1:
    periode = st.selectbox(
        "Période",
        options=["7 derniers jours", "30 derniers jours", "90 derniers jours", "Tout"],
        key="pipeline_periode",
    )

_PERIODE_JOURS = {
    "7 derniers jours": 7,
    "30 derniers jours": 30,
    "90 derniers jours": 90,
    "Tout": None,
}

_score_min_cut = None
_jours = _PERIODE_JOURS[periode]

# ─── Chargement leads ────────────────────────────────────────────────────────

all_leads = get_leads_by_client(client_id=client_id, limit=500)

if _jours:
    cutoff = datetime.now() - timedelta(days=_jours)
    all_leads = [l for l in all_leads if l.created_at and l.created_at >= cutoff]

vendeurs  = [l for l in all_leads if getattr(l, "lead_type", "acheteur") == "vendeur"]
acheteurs = [l for l in all_leads if getattr(l, "lead_type", "acheteur") == "acheteur"]
locataires = [l for l in all_leads if getattr(l, "lead_type", "acheteur") == "locataire"]

# ─── Résumé rapide ───────────────────────────────────────────────────────────

stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)
with stats_col1:
    st.metric("Total leads", len(all_leads))
with stats_col2:
    st.metric("🏠 Vendeurs", len(vendeurs))
with stats_col3:
    st.metric("🔑 Acheteurs", len(acheteurs))
with stats_col4:
    st.metric("🏢 Locataires", len(locataires))

st.markdown("---")

# ─── Fonction rendu colonne statut ───────────────────────────────────────────

_STATUT_ORDER = [
    "entrant", "en_qualification", "qualifie",
    "nurturing", "rdv_booke", "mandat", "vendu", "perdu", "disqualifié",
]
_STATUT_LABELS = {
    "entrant": "📥 Entrant",
    "en_qualification": "🔄 En qualification",
    "qualifie": "✅ Qualifié",
    "nurturing": "💬 Nurturing",
    "rdv_booke": "📅 RDV",
    "mandat": "📋 Mandat",
    "vendu": "🎉 Vendu",
    "perdu": "❌ Perdu",
    "disqualifié": "🚫 Disqualifié",
}

_TYPE_ICONS = {"vendeur": "🏠", "acheteur": "🔑", "locataire": "🏢"}


def _score_color(score: int) -> str:
    if score >= 18:
        return "#ef4444"
    if score >= 11:
        return "#f59e0b"
    return "#3b82f6"


def _render_lead_card(lead) -> str:
    score = lead.score or 0
    color = _score_color(score)
    lead_type = getattr(lead, "lead_type", "acheteur") or "acheteur"
    type_icon = _TYPE_ICONS.get(lead_type, "🔑")
    nom = (f"{lead.prenom} {lead.nom}").strip() or "—"
    budget = lead.budget or ""
    localisation = lead.localisation or ""
    followup_str = fmt_paris_datetime(lead.prochain_followup, "%d/%m") if lead.prochain_followup else ""

    return (
        f'<div style="background:#1e2130;border-radius:8px;padding:10px 12px;'
        f'margin-bottom:6px;border-left:3px solid {color};">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<span style="color:white;font-weight:600;font-size:0.88rem;">{nom}</span>'
        f'<span style="background:{color};color:white;border-radius:10px;'
        f'padding:1px 7px;font-size:0.75rem;">{score}/24</span>'
        f'</div>'
        f'<div style="color:#94a3b8;font-size:0.78rem;margin-top:3px;">'
        f'{type_icon} {lead_type}'
        f'{" · " + budget if budget else ""}'
        f'{" · " + localisation if localisation else ""}'
        f'</div>'
        + (f'<div style="color:#64748b;font-size:0.72rem;margin-top:2px;">📅 {followup_str}</div>'
           if followup_str else "")
        + '</div>'
    )


def _pipeline_section(leads, title: str):
    """Affiche les colonnes pipeline pour un groupe de leads."""
    if not leads:
        st.caption(f"Aucun lead {title.lower()} sur la période.")
        return

    by_statut: dict[str, list] = {s: [] for s in _STATUT_ORDER}
    for lead in leads:
        s = lead.statut.value if hasattr(lead.statut, "value") else str(lead.statut)
        if s in by_statut:
            by_statut[s].append(lead)

    # Colonnes actives (non vides ou statuts clés)
    active_statuts = [s for s in _STATUT_ORDER
                      if by_statut[s] or s in ("entrant", "qualifie", "rdv_booke", "mandat")][:6]

    cols = st.columns(len(active_statuts))
    for col, statut in zip(cols, active_statuts):
        bucket = by_statut[statut]
        label = _STATUT_LABELS.get(statut, statut)
        with col:
            st.markdown(
                f'<div style="background:#111827;border-radius:8px;padding:10px;">'
                f'<div style="color:#94a3b8;font-size:0.8rem;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">'
                f'{label} <span style="color:#475569;">({len(bucket)})</span></div>',
                unsafe_allow_html=True,
            )
            if bucket:
                cards_html = "".join(_render_lead_card(l) for l in sorted(
                    bucket, key=lambda x: x.score or 0, reverse=True
                )[:8])
                st.markdown(cards_html, unsafe_allow_html=True)
                if len(bucket) > 8:
                    st.caption(f"+ {len(bucket) - 8} de plus")
            else:
                st.markdown(
                    '<div style="color:#334155;font-size:0.8rem;text-align:center;padding:12px;">vide</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)


# ─── Onglets vendeur / acheteur / locataire ──────────────────────────────────

tab_v, tab_a, tab_l = st.tabs(["🏠 Vendeurs", "🔑 Acheteurs", "🏢 Locataires"])

with tab_v:
    _pipeline_section(vendeurs, "Vendeurs")

with tab_a:
    _pipeline_section(acheteurs, "Acheteurs")

with tab_l:
    _pipeline_section(locataires, "Locataires")
