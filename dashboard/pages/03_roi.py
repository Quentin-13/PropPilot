"""
Page ROI — Métriques de performance et tracker garantie remboursement.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime, timedelta

from config.settings import get_settings
from memory.lead_repository import get_pipeline_stats

settings = get_settings()

st.set_page_config(page_title="ROI — PropPilot", layout="wide", page_icon="💰")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("💰 ROI & Performance")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── Période ─────────────────────────────────────────────────────────────────
col_period, _ = st.columns([1, 3])
with col_period:
    month_str = st.selectbox(
        "Période",
        options=[
            datetime.now().strftime("%Y-%m"),
            (datetime.now() - timedelta(days=30)).strftime("%Y-%m"),
        ],
        format_func=lambda x: datetime.strptime(x, "%Y-%m").strftime("%B %Y"),
    )

# ─── Données pipeline ─────────────────────────────────────────────────────────
stats = get_pipeline_stats(client_id, month=month_str)
from memory.database import get_connection

# Calcul revenus estimés
commission_rate = settings.agency_commission_rate
avg_price = settings.agency_average_price
mandats = stats.get("mandat_count", 0)
ventes = stats.get("vendu", 0)
ca_estime = (mandats + ventes) * avg_price * commission_rate

# ─── KPIs principaux ──────────────────────────────────────────────────────────
st.markdown("### Performance du mois")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    leads_entrants = stats.get("total", 0)
    st.metric("Leads entrants", leads_entrants)

with col2:
    leads_qualifies = stats.get("qualifie", 0) + stats.get("rdv_booke", 0) + mandats + ventes
    taux_qual = leads_qualifies / leads_entrants * 100 if leads_entrants else 0
    st.metric("Leads qualifiés", leads_qualifies, delta=f"{taux_qual:.0f}% taux")

with col3:
    rdv = stats.get("rdv_count", 0)
    st.metric("RDV bookés", rdv, delta=f"+{max(0, rdv - 2)} vs objectif")

with col4:
    st.metric("Mandats", mandats)

with col5:
    st.metric("CA estimé", f"{ca_estime:,.0f}€", help="Basé sur commissions moyennes")

st.markdown("---")

# ─── Funnel de conversion ─────────────────────────────────────────────────────
st.markdown("### Funnel de conversion")

funnel_data = {
    "Leads entrants": leads_entrants,
    "Qualifiés": leads_qualifies,
    "RDV bookés": rdv,
    "Mandats": mandats,
    "Ventes": ventes,
}

import pandas as pd

funnel_rows = []
prev_val = None
for step, val in funnel_data.items():
    taux = val / prev_val * 100 if prev_val and prev_val > 0 else 100
    funnel_rows.append({"Étape": step, "Nombre": val, "Taux vs étape précédente": f"{taux:.0f}%"})
    prev_val = val if val > 0 else prev_val

st.dataframe(pd.DataFrame(funnel_rows), use_container_width=True, hide_index=True)

# ─── Tracker garantie ROI ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🛡️ 60 Jours Satisfait ou Remboursé")

# Calcul jours depuis le début (basé sur 1er jour du mois courant pour la démo)
start_date = datetime.now().replace(day=1)
days_elapsed = (datetime.now() - start_date).days
days_left = max(0, 60 - days_elapsed)

objectif_rdv = 2
objectif_mandat = 1

col_g1, col_g2, col_g3 = st.columns(3)

with col_g1:
    st.metric("Jours écoulés", f"J+{days_elapsed}/60")

with col_g2:
    rdv_ok = rdv >= objectif_rdv
    rdv_delta = rdv - objectif_rdv
    st.metric(
        "RDV supplémentaires",
        f"{rdv}/{objectif_rdv} objectif",
        delta=f"{rdv_delta:+d}",
        delta_color="normal" if rdv_ok else "inverse",
    )

with col_g3:
    mandat_ok = mandats >= objectif_mandat
    mandat_delta = mandats - objectif_mandat
    st.metric(
        "Mandats supplémentaires",
        f"{mandats}/{objectif_mandat} objectif",
        delta=f"{mandat_delta:+d}",
        delta_color="normal" if mandat_ok else "inverse",
    )

# Statut garantie
if rdv_ok and mandat_ok:
    st.success(f"""
    ✅ **Garantie ROI atteinte !**
    Vous avez dépassé les objectifs en {days_elapsed} jours.
    ROI calculé : **x{max(1, int(ca_estime / (settings.agency_commission_rate * 12000))):.0f}** sur votre abonnement.
    """)
else:
    manque_rdv = max(0, objectif_rdv - rdv)
    manque_mandat = max(0, objectif_mandat - mandats)
    st.warning(f"""
    ⏳ **En cours** — J+{days_elapsed}/60 · {days_left} jours restants

    Objectifs manquants : {f'+{manque_rdv} RDV' if manque_rdv > 0 else ''}{'  et  ' if manque_rdv > 0 and manque_mandat > 0 else ''}{f'+{manque_mandat} mandat' if manque_mandat > 0 else ''}

    Si l'objectif n'est pas atteint à J+60 → remboursement automatique selon votre forfait.
    """)

# ─── Comparaison mois précédent ───────────────────────────────────────────────
st.markdown("---")
st.markdown("### Évolution vs mois précédent")

prev_month = (datetime.now() - timedelta(days=30)).strftime("%Y-%m")
prev_stats = get_pipeline_stats(client_id, month=prev_month)

prev_rdv = prev_stats.get("rdv_count", 0)
prev_mandats = prev_stats.get("mandat_count", 0)
prev_leads = prev_stats.get("total", 0)

comp_col1, comp_col2, comp_col3 = st.columns(3)

with comp_col1:
    delta_leads = leads_entrants - prev_leads
    st.metric(
        "Leads entrants",
        leads_entrants,
        delta=f"{delta_leads:+d} vs mois précédent",
    )

with comp_col2:
    delta_rdv = rdv - prev_rdv
    st.metric(
        "RDV bookés",
        rdv,
        delta=f"{delta_rdv:+d} vs mois précédent",
    )

with comp_col3:
    delta_mandats = mandats - prev_mandats
    st.metric(
        "Mandats",
        mandats,
        delta=f"{delta_mandats:+d} vs mois précédent",
    )

# ─── ROI calculé ──────────────────────────────────────────────────────────────
from config.tier_limits import TIERS
tier_price = TIERS[tier].prix_mensuel

st.markdown("---")
st.markdown("### Calcul ROI")

roi_col1, roi_col2, roi_col3 = st.columns(3)
with roi_col1:
    st.metric("Abonnement mensuel", f"{tier_price}€")
with roi_col2:
    st.metric("CA généré estimé", f"{ca_estime:,.0f}€")
with roi_col3:
    roi_multiplier = ca_estime / tier_price if tier_price > 0 else 0
    st.metric("ROI", f"x{roi_multiplier:.1f}", help="CA généré / Coût abonnement")

st.markdown("""
> *CA estimé basé sur le nombre de mandats × prix moyen × taux de commission configuré.
> Les ventes peuvent être enregistrées manuellement dans la page Leads.*
""")
