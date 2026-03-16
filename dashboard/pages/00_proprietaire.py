"""
Dashboard Propriétaire PropPilot — Vue business complète pour Quentin (fondateur).
Accessible UNIQUEMENT si is_admin=True dans la session.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config.settings import get_settings
from memory.database import get_connection

st.set_page_config(
    page_title="Propriétaire — PropPilot",
    page_icon="🔐",
    layout="wide",
)

# ─── CSS global ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main { background: #0f1117; }
.block-container { padding-top: 1.5rem; max-width: 1400px; }
h1, h2, h3 { color: white !important; }
[data-testid="metric-container"] {
    background: #1e2130 !important;
    border-radius: 12px !important;
    padding: 16px !important;
}
[data-testid="stDataFrame"] { border-radius: 10px; }

/* Sidebar */
[data-testid="stSidebar"] { background: #1a3a5c; }
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label { color: white !important; }

.section-title {
    font-size: 1.15rem; font-weight: 700; color: white;
    margin: 0 0 16px 0; padding-bottom: 8px;
    border-bottom: 1px solid #1e2130;
}
.proj-card {
    background: #1e2130; border-radius: 12px; padding: 20px;
    border-left: 4px solid #f59e0b;
}
.proj-value { font-size: 2rem; font-weight: 800; color: #f59e0b; }
.proj-label { font-size: 0.8rem; color: #8892a4; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

# ─── Sécurité ─────────────────────────────────────────────────────────────────
from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth(require_active_plan=False)
render_sidebar_logout()

if not st.session_state.get("is_admin", False):
    st.error("🚫 Accès non autorisé — réservé à l'administrateur PropPilot.")
    st.stop()

settings = get_settings()

PLAN_PRICES = {"Indépendant": 250, "Starter": 790, "Pro": 1490, "Elite": 2990}

# ─── Helpers requêtes ─────────────────────────────────────────────────────────

def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")

def _prev_month() -> str:
    first = datetime.now().replace(day=1)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")

def _safe_query(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        st.warning(f"Erreur DB : {e}")
        return []

def _safe_scalar(sql: str, params: tuple = (), default=0):
    try:
        with get_connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default

def _exec(sql: str, params: tuple = ()) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(sql, params)
        return True
    except Exception as e:
        st.error(f"Erreur : {e}")
        return False

def _fmt_k(val: float) -> str:
    """Format court : 39 400 → '39.4K€', 790 → '790€'."""
    if val >= 1000:
        return f"{val/1000:.1f}K€"
    return f"{val:,.0f}€"

# ─── Date en français ─────────────────────────────────────────────────────────
JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
MOIS  = ["janvier","février","mars","avril","mai","juin",
         "juillet","août","septembre","octobre","novembre","décembre"]

now = datetime.now()
date_fr = f"{JOURS[now.weekday()]} {now.day} {MOIS[now.month-1]} {now.year} · {now.strftime('%H:%M')}"

# ─── Logo SVG ─────────────────────────────────────────────────────────────────
_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 56" width="140" height="40">
  <g>
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEADER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown(f"""
<div style="display:flex; align-items:center; justify-content:space-between;
            flex-wrap:wrap; gap:12px; margin-bottom:24px;">
  <div style="display:flex; align-items:center; gap:16px;">
    {_LOGO_SVG}
    <div>
      <h2 style="margin:0; font-size:1.6rem; color:white;">Vue Propriétaire</h2>
      <p style="margin:2px 0 0 0; color:#8892a4; font-size:0.85rem;">{date_fr}</p>
    </div>
  </div>
  <span style="background:#ef4444; color:white; padding:4px 14px;
               border-radius:20px; font-size:0.78rem; font-weight:700;
               letter-spacing:0.08em;">CONFIDENTIEL</span>
</div>
""", unsafe_allow_html=True)

# ─── Données MRR (nécessaires pour la barre d'objectifs) ──────────────────────
month = _current_month()
prev  = _prev_month()

active_by_plan = _safe_query("""
    SELECT plan, COUNT(*) as count
    FROM users
    WHERE plan_active = TRUE
    GROUP BY plan
""")
plan_counts: dict[str, int] = {r["plan"]: r["count"] for r in active_by_plan}
mrr = sum(PLAN_PRICES.get(p, 0) * n for p, n in plan_counts.items())
arr = mrr * 12
total_active = sum(plan_counts.values())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BARRE DE PROGRESSION OBJECTIFS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MRR_TARGET   = 5_000
CLIENT_TARGET = 10

clients_pct = min(total_active / CLIENT_TARGET * 100, 100)
mrr_pct     = min(mrr / MRR_TARGET * 100, 100)

def _bar_color(pct: float) -> str:
    if pct >= 70:
        return "#10b981"
    if pct >= 40:
        return "#f59e0b"
    return "#3b82f6"

c_color = _bar_color(clients_pct)
m_color = _bar_color(mrr_pct)

st.markdown(f"""
<div style="background:#1e2130;border-radius:12px;padding:20px;
            margin-bottom:24px;border-left:4px solid #3b82f6;">
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <span style="color:white;font-weight:700;">Objectif {CLIENT_TARGET} clients</span>
    <span style="color:{c_color};font-weight:700;">{total_active}/{CLIENT_TARGET}</span>
  </div>
  <div style="background:#334155;border-radius:6px;height:10px;margin-bottom:14px;">
    <div style="background:{c_color};width:{clients_pct:.1f}%;height:100%;
                border-radius:6px;transition:width 0.4s;"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <span style="color:white;font-weight:700;">Objectif MRR {MRR_TARGET:,}€</span>
    <span style="color:{m_color};font-weight:700;">{mrr_pct:.0f}%</span>
  </div>
  <div style="background:#334155;border-radius:6px;height:10px;margin-bottom:16px;">
    <div style="background:{m_color};width:{mrr_pct:.1f}%;height:100%;
                border-radius:6px;transition:width 0.4s;"></div>
  </div>
  <div style="display:flex;justify-content:space-between;
              font-size:0.85rem;color:#94a3b8;">
    <div>MRR cible : <strong style="color:white;">{MRR_TARGET:,}€</strong></div>
    <div>MRR actuel : <strong style="color:white;">{mrr:,.0f}€</strong></div>
    <div>Manquant : <strong style="color:white;">{max(0, MRR_TARGET - mrr):,.0f}€</strong></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 — MRR & REVENUS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("## 💰 MRR & Revenus")

prev_clients = _safe_query(
    "SELECT tier, COUNT(DISTINCT client_id) as cnt FROM usage_tracking WHERE month = %s GROUP BY tier",
    (prev,),
)
mrr_prev = sum(PLAN_PRICES.get(r["tier"], 0) * r["cnt"] for r in prev_clients)
mrr_delta = mrr - mrr_prev
mrr_delta_pct = (mrr_delta / mrr_prev * 100) if mrr_prev > 0 else 0

churn_count = _safe_scalar(
    "SELECT COUNT(*) FROM users WHERE subscription_status = 'cancelled'"
)

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("MRR", _fmt_k(mrr), delta=f"{mrr_delta:+.0f}€ vs mois préc.",
              help=f"MRR exact : {mrr:,}€")
with col2:
    st.metric("ARR", _fmt_k(arr), help=f"ARR exact : {arr:,}€")
with col3:
    st.metric("Clients actifs", total_active)
with col4:
    st.metric("Évolution MRR", f"{mrr_delta_pct:+.1f}%",
              delta=f"{mrr_delta:+.0f}€", delta_color="normal")
with col5:
    st.metric("Churn (annulés)", churn_count, delta_color="inverse")

st.markdown("")

# Bar chart + table forfaits
if plan_counts:
    df_plans = pd.DataFrame([
        {"Forfait": p,
         "Clients": plan_counts.get(p, 0),
         "MRR (€)": PLAN_PRICES.get(p, 0) * plan_counts.get(p, 0)}
        for p in ["Indépendant", "Starter", "Pro", "Elite"]
    ])
    col_chart, col_table = st.columns([2, 1])
    with col_chart:
        st.markdown("**Clients actifs par forfait**")
        st.bar_chart(df_plans.set_index("Forfait")["Clients"], color="#3b82f6")
    with col_table:
        st.markdown("**Détail MRR par forfait**")
        st.dataframe(
            df_plans.style.format({"MRR (€)": "{:,.0f}€"}),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("Aucun client actif pour le moment.")

# ── Graphique MRR évolution 6 mois ────────────────────────────────────────────
st.markdown("")
st.markdown("**Évolution MRR (6 derniers mois)**")
months_data = _safe_query("""
    SELECT month,
           SUM(CASE WHEN tier='Indépendant' THEN 250
                    WHEN tier='Starter' THEN 790
                    WHEN tier='Pro' THEN 1490
                    WHEN tier='Elite' THEN 2990
                    ELSE 0 END) as mrr_estimate
    FROM usage_tracking
    GROUP BY month
    ORDER BY month DESC
    LIMIT 6
""")
if months_data:
    df_mrr_hist = pd.DataFrame(months_data).sort_values("month")
    df_mrr_hist = df_mrr_hist.rename(columns={"month": "Mois", "mrr_estimate": "MRR (€)"})
    st.area_chart(df_mrr_hist.set_index("Mois")["MRR (€)"], color="#3b82f6")
else:
    st.caption("Pas encore de données d'historique MRR.")

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 — COÛTS APIs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("## ⚙️ Coûts APIs — " + month)

api_costs = _safe_query("""
    SELECT provider,
           SUM(cost_euros)           AS total_euros,
           SUM(tokens_input)         AS tokens_in,
           SUM(tokens_output)        AS tokens_out,
           COUNT(*)                  AS nb_actions,
           SUM(CASE WHEN mock_used = 1 THEN 1 ELSE 0 END) AS mocks
    FROM api_actions
    WHERE TO_CHAR(created_at, 'YYYY-MM') = %s
    GROUP BY provider
""", (month,))

costs_by_provider: dict[str, float] = {r["provider"]: r["total_euros"] for r in api_costs}

voice_total = _safe_scalar(
    "SELECT COALESCE(SUM(voice_minutes), 0) FROM usage_tracking WHERE month = %s",
    (month,), 0.0)
sms_total = _safe_scalar(
    "SELECT COALESCE(SUM(followups_count), 0) FROM usage_tracking WHERE month = %s",
    (month,), 0)

COST_ANTHROPIC_PER_1K    = 0.006 / 1.1
COST_ELEVENLABS_PER_MIN  = 0.30  / 1.1
COST_TWILIO_VOICE_PER_MIN = 0.02 / 1.1
COST_TWILIO_SMS_EACH      = 0.01 / 1.1

tokens_total = sum(
    (r["tokens_in"] or 0) + (r["tokens_out"] or 0)
    for r in api_costs if r["provider"] == "anthropic"
)
cost_anthropic  = costs_by_provider.get("anthropic")  or (tokens_total / 1000 * COST_ANTHROPIC_PER_1K)
cost_elevenlabs = costs_by_provider.get("elevenlabs") or (voice_total * COST_ELEVENLABS_PER_MIN)
cost_twilio     = costs_by_provider.get("twilio")     or (
    voice_total * COST_TWILIO_VOICE_PER_MIN + sms_total * COST_TWILIO_SMS_EACH
)
cost_sendgrid   = costs_by_provider.get("sendgrid", 0.0)

total_costs = cost_anthropic + cost_elevenlabs + cost_twilio + cost_sendgrid
marge_brute = mrr - total_costs
marge_pct   = (marge_brute / mrr * 100) if mrr > 0 else 0

col_c1, col_c2, col_c3, col_c4, col_c5, col_c6 = st.columns(6)
with col_c1:
    st.metric("Anthropic",  f"{cost_anthropic:.2f}€",  help=f"{tokens_total:,} tokens")
with col_c2:
    st.metric("ElevenLabs", f"{cost_elevenlabs:.2f}€", help=f"{voice_total:.0f} min voix")
with col_c3:
    st.metric("Twilio",     f"{cost_twilio:.2f}€",     help=f"{voice_total:.0f} min · {sms_total} SMS")
with col_c4:
    st.metric("SendGrid",   f"{cost_sendgrid:.2f}€",   help="Gratuit jusqu'à 100/jour")
with col_c5:
    st.metric("Total coûts", f"{total_costs:.2f}€")
with col_c6:
    st.metric("Marge brute", _fmt_k(marge_brute),
              delta=f"{marge_pct:.1f}%", delta_color="normal",
              help=f"Marge exacte : {marge_brute:,.0f}€")

if api_costs:
    with st.expander("📋 Détail par provider (api_actions)"):
        df_costs = pd.DataFrame([
            {
                "Provider":   r["provider"],
                "Actions":    r["nb_actions"],
                "Tokens IN":  r["tokens_in"]  or 0,
                "Tokens OUT": r["tokens_out"] or 0,
                "Mocks":      r["mocks"]      or 0,
                "Coût (€)":   round(r["total_euros"] or 0, 4),
            }
            for r in api_costs
        ])
        st.dataframe(df_costs, use_container_width=True, hide_index=True)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 — PROJECTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("## 📈 Projections")
st.caption("Hypothèse : +2 nouveaux clients Indépendant par mois")

mrr_3m  = mrr + (2 * 3  * 250)
mrr_6m  = mrr + (2 * 6  * 250)
mrr_12m = mrr + (2 * 12 * 250)

proj_cols = st.columns(3)
projections = [
    ("Dans 3 mois", mrr_3m,  total_active + 6),
    ("Dans 6 mois", mrr_6m,  total_active + 12),
    ("Dans 12 mois", mrr_12m, total_active + 24),
]
for col, (label, proj_mrr, proj_clients) in zip(proj_cols, projections):
    with col:
        st.markdown(f"""
        <div class="proj-card">
            <div style="font-size:0.85rem;color:#8892a4;margin-bottom:6px;">{label}</div>
            <div class="proj-value">{_fmt_k(proj_mrr)}</div>
            <div class="proj-label">MRR estimé · {proj_clients} clients</div>
            <div style="font-size:0.78rem;color:#64748b;margin-top:8px;">
                ARR : {_fmt_k(proj_mrr * 12)}
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 — GESTION CLIENTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("## 👥 Gestion clients")

clients = _safe_query("""
    SELECT u.id,
           u.email,
           u.agency_name,
           u.plan,
           u.plan_active,
           u.subscription_status,
           u.trial_ends_at,
           u.created_at,
           COALESCE(ut.voice_minutes, 0)   AS voice_minutes,
           COALESCE(ut.followups_count, 0) AS sms_count,
           COALESCE(ut.leads_count, 0)     AS leads_count,
           COALESCE(ut.tokens_used, 0)     AS tokens_used
    FROM users u
    LEFT JOIN usage_tracking ut
           ON u.id = ut.client_id AND ut.month = %s
    WHERE u.is_admin = FALSE OR u.is_admin IS NULL
    ORDER BY u.created_at DESC
""", (month,))

last_activity_rows = _safe_query("""
    SELECT client_id, MAX(created_at) AS last_act
    FROM api_actions
    GROUP BY client_id
""")
last_activity: dict[str, datetime] = {
    r["client_id"]: r["last_act"] for r in last_activity_rows if r["last_act"]
}

from config.tier_limits import TIERS

def _quota_pct(plan: str, voice: float, sms: int) -> float:
    limits = TIERS.get(plan, TIERS["Starter"])
    pcents = []
    if limits.minutes_voix_par_mois:
        pcents.append(voice / limits.minutes_voix_par_mois * 100)
    if limits.followups_sms_par_mois:
        pcents.append(sms / limits.followups_sms_par_mois * 100)
    return max(pcents) if pcents else 0.0

rows_display = []
for c in clients:
    last_act = last_activity.get(c["id"])
    if isinstance(last_act, str):
        try:
            last_act = datetime.fromisoformat(last_act)
        except Exception:
            last_act = None

    days_inactive = (now - last_act).days if last_act else 999
    quota_pct     = _quota_pct(c["plan"], c["voice_minutes"], c["sms_count"])

    if days_inactive > 7:
        status_flag = "🔴 Inactif"
    elif quota_pct >= 80:
        status_flag = "🟠 Quota élevé"
    elif not c["plan_active"]:
        status_flag = "⚠️ Inactif"
    else:
        status_flag = "✅ Actif"

    created_str = ""
    if c["created_at"]:
        try:
            dt = datetime.fromisoformat(str(c["created_at"])[:19])
            created_str = dt.strftime("%d/%m/%Y")
        except Exception:
            created_str = str(c["created_at"])[:10]

    rows_display.append({
        "Email":          c["email"],
        "Agence":         c["agency_name"] or "—",
        "Forfait":        c["plan"],
        "MRR contrib.":   f"{PLAN_PRICES.get(c['plan'], 0):,}€",
        "Statut":         status_flag,
        "Abonnement":     c["subscription_status"] or "—",
        "Voix (min)":     round(c["voice_minutes"], 0),
        "SMS":            c["sms_count"],
        "Leads":          c["leads_count"],
        "Quota %":        round(quota_pct, 0),
        "Dernière activ.": f"J-{days_inactive}" if days_inactive < 999 else "jamais",
        "Inscrit le":     created_str,
        "_id":            c["id"],
    })

df_clients = pd.DataFrame(rows_display)

if df_clients.empty:
    st.info("Aucun client enregistré.")
else:
    # Filtre actifs/inactifs
    filtre = st.radio(
        "Afficher",
        ["Tous", "Actifs", "Inactifs"],
        horizontal=True,
        key="client_filter",
    )
    if filtre == "Actifs":
        df_show = df_clients[~df_clients["Statut"].str.startswith("🔴") & ~df_clients["Statut"].str.startswith("⚠️")]
    elif filtre == "Inactifs":
        df_show = df_clients[df_clients["Statut"].str.startswith("🔴") | df_clients["Statut"].str.startswith("⚠️")]
    else:
        df_show = df_clients

    def _highlight(row):
        base = "color: #000000; "
        if "🔴" in str(row.get("Statut", "")):
            return [base + "background-color: #fee2e2"] * len(row)
        if "🟠" in str(row.get("Statut", "")):
            return [base + "background-color: #fef3c7"] * len(row)
        return [base] * len(row)

    display_cols = ["Email", "Agence", "Forfait", "MRR contrib.", "Statut",
                    "Abonnement", "Voix (min)", "SMS", "Leads",
                    "Quota %", "Dernière activ.", "Inscrit le"]

    st.dataframe(
        df_show[display_cols].style.apply(_highlight, axis=1),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown(f"**{len(df_show)} clients affichés** · 🔴 Inactif >7j · 🟠 Quota >80%")

    # ── Actions par client ─────────────────────────────────────────────────────
    st.markdown("### Actions")
    col_sel, col_action, col_plan, col_btn = st.columns([3, 2, 2, 1])
    client_emails = [r["Email"] for r in rows_display]

    with col_sel:
        selected_email = st.selectbox("Sélectionner un client", ["—"] + client_emails, key="prop_client_sel")
    with col_action:
        action = st.selectbox("Action", ["Activer plan", "Désactiver plan", "Changer forfait"], key="prop_action")
    with col_plan:
        new_plan = st.selectbox("Nouveau forfait", ["Indépendant", "Starter", "Pro", "Elite"], key="prop_new_plan")
    with col_btn:
        st.markdown("<div style='margin-top: 28px;'>", unsafe_allow_html=True)
        apply = st.button("Appliquer", type="primary", key="prop_apply")
        st.markdown("</div>", unsafe_allow_html=True)

    if apply and selected_email and selected_email != "—":
        sel_row = next((r for r in rows_display if r["Email"] == selected_email), None)
        if sel_row:
            uid = sel_row["_id"]
            if action == "Activer plan":
                if _exec("UPDATE users SET plan_active = TRUE WHERE id = %s", (uid,)):
                    st.success(f"✅ Plan activé pour {selected_email}")
            elif action == "Désactiver plan":
                if _exec("UPDATE users SET plan_active = FALSE WHERE id = %s", (uid,)):
                    st.success(f"✅ Plan désactivé pour {selected_email}")
            elif action == "Changer forfait":
                if _exec("UPDATE users SET plan = %s, plan_active = TRUE WHERE id = %s", (new_plan, uid)):
                    st.success(f"✅ Forfait changé en **{new_plan}** pour {selected_email}")

st.markdown("---")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 5 — ALERTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("## 🚨 Alertes")

past_due = _safe_query("""
    SELECT email, agency_name, plan
    FROM users WHERE subscription_status = 'past_due'
    ORDER BY email
""")
expiring = _safe_query("""
    SELECT email, agency_name, plan, trial_ends_at
    FROM users
    WHERE trial_ends_at IS NOT NULL
      AND trial_ends_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'
    ORDER BY trial_ends_at
""")
costs_prev_rows = _safe_query("""
    SELECT provider, SUM(cost_euros) AS total_prev
    FROM api_actions
    WHERE TO_CHAR(created_at, 'YYYY-MM') = %s
    GROUP BY provider
""", (prev,))
prev_costs: dict[str, float] = {r["provider"]: r["total_prev"] or 0 for r in costs_prev_rows}

cost_alerts = [
    (r["provider"], r["total_euros"] or 0, prev_costs.get(r["provider"], 0))
    for r in api_costs
    if prev_costs.get(r["provider"], 0) > 0 and (r["total_euros"] or 0) > prev_costs.get(r["provider"], 0) * 1.5
]

total_alerts = len(past_due) + len(expiring) + len(cost_alerts)

if total_alerts == 0:
    st.success("Tout va bien ✅ — Aucune alerte active")
else:
    alert_cols = st.columns(3)

    with alert_cols[0]:
        if past_due:
            for c in past_due:
                st.markdown(f"""
                <div style="background:#1e2130;border-left:4px solid #ef4444;
                            padding:10px 14px;border-radius:8px;margin:4px 0;">
                    <span style="color:#ef4444;font-size:0.75rem;font-weight:700;">💳 PAIEMENT ÉCHOUÉ</span><br>
                    <strong style="color:white;">{c['agency_name'] or c['email']}</strong><br>
                    <small style="color:#94a3b8;">{c['email']} · {c['plan']}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:#10b981;font-size:0.85rem;">✅ Aucun échec paiement</span>',
                        unsafe_allow_html=True)

    with alert_cols[1]:
        if expiring:
            for c in expiring:
                ends = str(c["trial_ends_at"])[:10] if c["trial_ends_at"] else "?"
                st.markdown(f"""
                <div style="background:#1e2130;border-left:4px solid #f59e0b;
                            padding:10px 14px;border-radius:8px;margin:4px 0;">
                    <span style="color:#f59e0b;font-size:0.75rem;font-weight:700;">⏳ TRIAL EXPIRANT</span><br>
                    <strong style="color:white;">{c['agency_name'] or c['email']}</strong><br>
                    <small style="color:#94a3b8;">Expire le {ends} · {c['plan']}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:#10b981;font-size:0.85rem;">✅ Aucun trial expirant</span>',
                        unsafe_allow_html=True)

    with alert_cols[2]:
        if cost_alerts:
            for prov, curr, prv in cost_alerts:
                pct_inc = (curr - prv) / prv * 100
                st.markdown(f"""
                <div style="background:#1e2130;border-left:4px solid #ef4444;
                            padding:10px 14px;border-radius:8px;margin:4px 0;">
                    <span style="color:#ef4444;font-size:0.75rem;font-weight:700;">📈 COÛT ANORMAL</span><br>
                    <strong style="color:white;">{prov}</strong> +{pct_inc:.0f}%<br>
                    <small style="color:#94a3b8;">{prv:.2f}€ → {curr:.2f}€</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:#10b981;font-size:0.85rem;">✅ Aucun coût anormal</span>',
                        unsafe_allow_html=True)

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:40px;'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='text-align:center; color:#475569; font-size:11px;'>"
    "🔐 PropPilot · Vue Propriétaire · Accès restreint — Données confidentielles"
    "</div>",
    unsafe_allow_html=True,
)
