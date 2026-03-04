"""
Page Usage — Barres de consommation mensuelle par fonctionnalité.
JAMAIS de coûts API affichés ici — uniquement métriques métier.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime

from config.settings import get_settings
from config.tier_limits import TIERS
from memory.database import init_database
from memory.usage_tracker import get_usage_summary

init_database()
settings = get_settings()

st.set_page_config(page_title="Usage — PropPilot", layout="wide", page_icon="📊")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("📊 Utilisation mensuelle")
st.markdown(f"**{agency_name}** · Forfait **{tier}** · {datetime.now().strftime('%B %Y')}")

# ─── Usage data ────────────────────────────────────────────────────────────

usage = get_usage_summary(client_id, tier)

# ─── Alertes globales ──────────────────────────────────────────────────────

# Vérifie si une ressource est en alerte
max_pct = max(
    v["pct"] for v in usage.values()
    if isinstance(v, dict) and "pct" in v
)

if max_pct >= 100:
    st.markdown("""
    <div class="alert-red">
    🚫 <strong>Limite atteinte</strong> — Certains de vos agents sont en pause.<br>
    Pour reprendre immédiatement, contactez-nous : <a href="mailto:contact@proppilot.fr?subject=Upgrade forfait PropPilot" style="color: white; font-weight: 700;">contact@proppilot.fr</a>
    </div>
    """, unsafe_allow_html=True)
elif max_pct >= 95:
    days_left = 30 - datetime.now().day
    st.markdown(f"""
    <div class="alert-red">
    🔴 <strong>Limite proche</strong> — Vous arriverez à votre limite dans environ {days_left} jours.
    Pour continuer sans interruption, passez au forfait supérieur.
    </div>
    """, unsafe_allow_html=True)
elif max_pct >= 80:
    st.markdown("""
    <div class="alert-orange">
    ⚠️ <strong>Attention</strong> — Vous approchez de votre limite sur certaines fonctionnalités.
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")


# ─── Fonction affichage barre ───────────────────────────────────────────────

def display_usage_bar(label: str, used: float, limit, pct: float, unit: str = ""):
    """Affiche une barre de progression colorée selon le pourcentage."""
    limit_str = f"{int(limit):,}" if limit is not None else "∞"
    used_str = f"{int(used):,}" if isinstance(used, float) and used.is_integer() else f"{used:.1f}"

    # Couleur selon pourcentage
    if limit is None:
        color = "#27ae60"
        status = "Illimité ∞"
        pct_display = 0
    elif pct >= 100:
        color = "#e74c3c"
        status = "🚫 Limite atteinte"
        pct_display = 100
    elif pct >= 90:
        color = "#e74c3c"
        status = f"⚠️ {pct:.0f}%"
        pct_display = pct
    elif pct >= 70:
        color = "#f39c12"
        status = f"⚠️ {pct:.0f}%"
        pct_display = pct
    else:
        color = "#27ae60"
        status = f"{pct:.0f}%"
        pct_display = pct

    st.markdown(f"**{label}**")

    col_bar, col_stat = st.columns([4, 1])
    with col_bar:
        st.markdown(f"""
        <div style="background: #e9ecef; border-radius: 6px; height: 20px; overflow: hidden;">
            <div style="background: {color}; width: {min(pct_display, 100):.1f}%; height: 100%; border-radius: 6px; transition: width 0.3s;"></div>
        </div>
        <div style="font-size: 12px; color: #666; margin-top: 4px;">
            {used_str}{unit} / {limit_str}{unit}
        </div>
        """, unsafe_allow_html=True)

    with col_stat:
        st.markdown(f"<div style='color: {color}; font-weight: 600; padding-top: 2px;'>{status}</div>", unsafe_allow_html=True)


# ─── Barres d'usage ────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.markdown("### Activité principale")
    st.markdown("")

    display_usage_bar(
        "🧑 Leads qualifiés",
        usage["leads"]["used"],
        usage["leads"]["limit"],
        usage["leads"]["pct"],
    )
    st.markdown("")

    display_usage_bar(
        "📝 Annonces générées",
        usage["listings"]["used"],
        usage["listings"]["limit"],
        usage["listings"]["pct"],
    )
    st.markdown("")

    display_usage_bar(
        "📐 Estimations",
        usage["estimations"]["used"],
        usage["estimations"]["limit"],
        usage["estimations"]["pct"],
    )

with col2:
    st.markdown("### Communication")
    st.markdown("")

    display_usage_bar(
        "🎙️ Minutes voix",
        usage["voice"]["used"],
        usage["voice"]["limit"],
        usage["voice"]["pct"],
        unit=" min",
    )
    st.markdown("")

    display_usage_bar(
        "💬 Follow-ups SMS",
        usage["followups"]["used"],
        usage["followups"]["limit"],
        usage["followups"]["pct"],
    )
    st.markdown("")

    display_usage_bar(
        "🖼️ Images staging",
        usage["images"]["used"],
        usage["images"]["limit"],
        usage["images"]["pct"],
    )

st.markdown("---")

# ─── Détail par fonctionnalité ─────────────────────────────────────────────

with st.expander("📋 Détail complet de l'utilisation"):
    tier_limits = TIERS[tier]

    detail_data = [
        {
            "Fonctionnalité": "Leads qualifiés",
            "Utilisé": usage["leads"]["used"],
            "Limite": usage["leads"]["limit"] or "Illimité",
            "Restant": max(0, int((usage["leads"]["limit"] or 0) - usage["leads"]["used"])) if usage["leads"]["limit"] else "∞",
            "Progression": f"{usage['leads']['pct']:.0f}%",
        },
        {
            "Fonctionnalité": "Minutes voix",
            "Utilisé": f"{usage['voice']['used']:.1f}",
            "Limite": usage["voice"]["limit"] or "Illimité",
            "Restant": f"{max(0, (usage['voice']['limit'] or 0) - usage['voice']['used']):.0f}" if usage["voice"]["limit"] else "∞",
            "Progression": f"{usage['voice']['pct']:.0f}%",
        },
        {
            "Fonctionnalité": "Images staging",
            "Utilisé": usage["images"]["used"],
            "Limite": usage["images"]["limit"] or "Illimité",
            "Restant": max(0, int((usage["images"]["limit"] or 0) - usage["images"]["used"])) if usage["images"]["limit"] else "∞",
            "Progression": f"{usage['images']['pct']:.0f}%",
        },
        {
            "Fonctionnalité": "Follow-ups SMS",
            "Utilisé": usage["followups"]["used"],
            "Limite": usage["followups"]["limit"] or "Illimité",
            "Restant": max(0, int((usage["followups"]["limit"] or 0) - usage["followups"]["used"])) if usage["followups"]["limit"] else "∞",
            "Progression": f"{usage['followups']['pct']:.0f}%",
        },
        {
            "Fonctionnalité": "Annonces générées",
            "Utilisé": usage["listings"]["used"],
            "Limite": usage["listings"]["limit"] or "Illimité",
            "Restant": max(0, int((usage["listings"]["limit"] or 0) - usage["listings"]["used"])) if usage["listings"]["limit"] else "∞",
            "Progression": f"{usage['listings']['pct']:.0f}%",
        },
        {
            "Fonctionnalité": "Estimations",
            "Utilisé": usage["estimations"]["used"],
            "Limite": usage["estimations"]["limit"] or "Illimité",
            "Restant": max(0, int((usage["estimations"]["limit"] or 0) - usage["estimations"]["used"])) if usage["estimations"]["limit"] else "∞",
            "Progression": f"{usage['estimations']['pct']:.0f}%",
        },
    ]

    import pandas as pd
    st.dataframe(pd.DataFrame(detail_data), use_container_width=True, hide_index=True)

# ─── Upgrade CTA ────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### Votre forfait actuel")

tier_col1, tier_col2, tier_col3, tier_col4 = st.columns(4)

tiers_display = {
    "Indépendant": {"prix": "290€/mois", "voix": "600 min", "sms": "3 000 SMS", "highlight": tier == "Indépendant"},
    "Starter": {"prix": "790€/mois", "voix": "1 500 min", "sms": "8 000 SMS", "highlight": tier == "Starter"},
    "Pro": {"prix": "1 490€/mois", "voix": "3 000 min", "sms": "15 000 SMS", "highlight": tier == "Pro"},
    "Elite": {"prix": "2 990€/mois", "voix": "Illimité", "sms": "Illimité", "highlight": tier == "Elite"},
}

for col, (tier_name, info) in zip([tier_col1, tier_col2, tier_col3, tier_col4], tiers_display.items()):
    with col:
        border_color = "#1a3a5c" if info["highlight"] else "#e9ecef"
        badge = " ✓ Votre forfait" if info["highlight"] else ""
        upgrade_txt = "" if info["highlight"] else f"<a href='mailto:contact@proppilot.fr?subject=Upgrade vers {tier_name}' style='color: #e67e22;'>Passer à {tier_name} →</a>"

        st.markdown(f"""
        <div style="border: 2px solid {border_color}; border-radius: 10px; padding: 20px; text-align: center;">
            <div style="font-size: 18px; font-weight: 700;">{tier_name}{badge}</div>
            <div style="font-size: 24px; font-weight: 800; color: #1a3a5c; margin: 8px 0;">{info['prix']}</div>
            <div style="color: #666; font-size: 14px;">
                {info['voix']} voix · {info['sms']}
            </div>
            <div style="margin-top: 12px;">{upgrade_txt}</div>
        </div>
        """, unsafe_allow_html=True)

# Gain concret selon tier
if tier == "Indépendant":
    st.info("💡 **Passer Starter** → 1 500 min voix au lieu de 600, 8 000 SMS au lieu de 3 000, jusqu'à 3 utilisateurs. Contactez-nous : contact@proppilot.fr")
elif tier == "Starter":
    st.info("💡 **Passer Pro** → 3 000 min voix au lieu de 1 500, 15 000 SMS au lieu de 8 000, jusqu'à 6 utilisateurs. Contactez-nous : contact@proppilot.fr")
elif tier == "Pro":
    st.info("💡 **Passer Elite** → Voix et SMS illimités, white-label, agents custom, account manager dédié. Contactez-nous : contact@proppilot.fr")
