"""
Dashboard Admin PropPilot — Vue business complète pour Quentin (fondateur).
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
    page_title="Admin — PropPilot",
    page_icon="🔐",
    layout="wide",
)

# ─── Sécurité ─────────────────────────────────────────────────────────────────

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth(require_active_plan=False)
render_sidebar_logout()

if not st.session_state.get("is_admin", False):
    st.error("🚫 Accès non autorisé — réservé à l'administrateur PropPilot.")
    st.stop()

settings = get_settings()

PLAN_PRICES = {"Indépendant": 290, "Starter": 790, "Pro": 1490, "Elite": 2990}

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


# ─── Header ───────────────────────────────────────────────────────────────────

st.title("🔐 Admin PropPilot")
st.markdown(f"Dashboard propriétaire · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — MRR & REVENUS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("## 💰 MRR & Revenus")

month = _current_month()
prev = _prev_month()

# Clients actifs par forfait (ce mois)
active_by_plan = _safe_query("""
    SELECT plan, COUNT(*) as count
    FROM users
    WHERE plan_active = TRUE
    GROUP BY plan
""")

plan_counts: dict[str, int] = {r["plan"]: r["count"] for r in active_by_plan}
mrr = sum(PLAN_PRICES.get(p, 0) * n for p, n in plan_counts.items())
arr = mrr * 12

# Revenus mois précédent (depuis usage_tracking — tier au moment de la consommation)
prev_clients = _safe_query(
    "SELECT tier, COUNT(DISTINCT client_id) as cnt FROM usage_tracking WHERE month = %s GROUP BY tier",
    (prev,),
)
mrr_prev = sum(PLAN_PRICES.get(r["tier"], 0) * r["cnt"] for r in prev_clients)
mrr_delta = mrr - mrr_prev
mrr_delta_pct = (mrr_delta / mrr_prev * 100) if mrr_prev > 0 else 0

# Churn (subscription_status = cancelled)
churn_count = _safe_scalar(
    "SELECT COUNT(*) FROM users WHERE subscription_status = 'cancelled'"
)

# KPIs ligne principale
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("MRR", f"{mrr:,.0f}€", delta=f"{mrr_delta:+.0f}€ vs mois préc.")
with col2:
    st.metric("ARR", f"{arr:,.0f}€")
with col3:
    total_active = sum(plan_counts.values())
    st.metric("Clients actifs", total_active)
with col4:
    st.metric(
        "Évolution MRR",
        f"{mrr_delta_pct:+.1f}%",
        delta=f"{mrr_delta:+.0f}€",
        delta_color="normal",
    )
with col5:
    st.metric("Churn (annulés)", churn_count, delta_color="inverse")

st.markdown("")

# Bar chart clients par forfait
if plan_counts:
    df_plans = pd.DataFrame([
        {"Forfait": p, "Clients": plan_counts.get(p, 0), "MRR (€)": PLAN_PRICES.get(p, 0) * plan_counts.get(p, 0)}
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

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — COÛTS APIs
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("## ⚙️ Coûts APIs — " + month)

# Coûts réels depuis api_actions (loggés par cost_logger)
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

# Compléments depuis usage_tracking pour Twilio (voice) et ElevenLabs
voice_total = _safe_scalar("""
    SELECT COALESCE(SUM(voice_minutes), 0) FROM usage_tracking WHERE month = %s
""", (month,), 0.0)
sms_total = _safe_scalar("""
    SELECT COALESCE(SUM(followups_count), 0) FROM usage_tracking WHERE month = %s
""", (month,), 0)

# Estimations coûts si non encore dans api_actions
COST_ANTHROPIC_PER_1K = 0.006 / 1.1      # $0.006 → ~€0.0055
COST_ELEVENLABS_PER_MIN = 0.30 / 1.1     # $0.30 → ~€0.27
COST_TWILIO_VOICE_PER_MIN = 0.02 / 1.1   # $0.02 → ~€0.018
COST_TWILIO_SMS_EACH = 0.01 / 1.1        # $0.01 → ~€0.009

tokens_total = sum(
    (r["tokens_in"] or 0) + (r["tokens_out"] or 0)
    for r in api_costs if r["provider"] == "anthropic"
)
cost_anthropic = costs_by_provider.get("anthropic") or (tokens_total / 1000 * COST_ANTHROPIC_PER_1K)
cost_elevenlabs = costs_by_provider.get("elevenlabs") or (voice_total * COST_ELEVENLABS_PER_MIN)
cost_twilio = costs_by_provider.get("twilio") or (
    voice_total * COST_TWILIO_VOICE_PER_MIN + sms_total * COST_TWILIO_SMS_EACH
)
cost_sendgrid = costs_by_provider.get("sendgrid", 0.0)  # Gratuit jusqu'à 100/jour

total_costs = cost_anthropic + cost_elevenlabs + cost_twilio + cost_sendgrid
marge_brute = mrr - total_costs
marge_pct = (marge_brute / mrr * 100) if mrr > 0 else 0

col_c1, col_c2, col_c3, col_c4, col_c5, col_c6 = st.columns(6)
with col_c1:
    st.metric("Anthropic", f"{cost_anthropic:.2f}€", help=f"{tokens_total:,} tokens")
with col_c2:
    st.metric("ElevenLabs", f"{cost_elevenlabs:.2f}€", help=f"{voice_total:.0f} min voix")
with col_c3:
    st.metric("Twilio", f"{cost_twilio:.2f}€", help=f"{voice_total:.0f} min · {sms_total} SMS")
with col_c4:
    st.metric("SendGrid", f"{cost_sendgrid:.2f}€", help="Gratuit jusqu'à 100/jour")
with col_c5:
    st.metric("Total coûts", f"{total_costs:.2f}€")
with col_c6:
    st.metric(
        "Marge brute",
        f"{marge_brute:,.0f}€",
        delta=f"{marge_pct:.1f}%",
        delta_color="normal",
    )

# Détail par provider
if api_costs:
    with st.expander("📋 Détail par provider (api_actions)"):
        df_costs = pd.DataFrame([
            {
                "Provider": r["provider"],
                "Actions": r["nb_actions"],
                "Tokens IN": r["tokens_in"] or 0,
                "Tokens OUT": r["tokens_out"] or 0,
                "Mocks": r["mocks"] or 0,
                "Coût (€)": round(r["total_euros"] or 0, 4),
            }
            for r in api_costs
        ])
        st.dataframe(df_costs, use_container_width=True, hide_index=True)

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CLIENTS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("## 👥 Gestion clients")

clients = _safe_query(f"""
    SELECT u.id,
           u.email,
           u.agency_name,
           u.plan,
           u.plan_active,
           u.subscription_status,
           u.trial_ends_at,
           u.created_at,
           COALESCE(ut.voice_minutes, 0)    AS voice_minutes,
           COALESCE(ut.followups_count, 0)  AS sms_count,
           COALESCE(ut.leads_count, 0)      AS leads_count,
           COALESCE(ut.tokens_used, 0)      AS tokens_used
    FROM users u
    LEFT JOIN usage_tracking ut
           ON u.id = ut.client_id AND ut.month = %s
    WHERE u.is_admin = FALSE OR u.is_admin IS NULL
    ORDER BY u.created_at DESC
""", (month,))

# Calcul dernière activité (dernière action API)
last_activity_rows = _safe_query("""
    SELECT client_id, MAX(created_at) AS last_act
    FROM api_actions
    GROUP BY client_id
""")
last_activity: dict[str, datetime] = {
    r["client_id"]: r["last_act"] for r in last_activity_rows if r["last_act"]
}

now = datetime.now()
seuil_inactif = now - timedelta(days=7)

from config.tier_limits import TIERS

def _quota_pct(plan: str, voice: float, sms: int) -> float:
    """Retourne le % max de quota consommé parmi voix et SMS."""
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
    quota_pct = _quota_pct(c["plan"], c["voice_minutes"], c["sms_count"])

    status_flag = ""
    if days_inactive > 7:
        status_flag = "🔴 Inactif"
    elif quota_pct >= 80:
        status_flag = "🟠 Quota élevé"
    elif not c["plan_active"]:
        status_flag = "⚠️ Inactif"
    else:
        status_flag = "✅ Actif"

    rows_display.append({
        "Email": c["email"],
        "Agence": c["agency_name"] or "—",
        "Forfait": c["plan"],
        "Statut": status_flag,
        "Abonnement": c["subscription_status"] or "—",
        "Voix (min)": round(c["voice_minutes"], 0),
        "SMS": c["sms_count"],
        "Leads": c["leads_count"],
        "Quota %": round(quota_pct, 0),
        "Dernière activité": f"J-{days_inactive}" if days_inactive < 999 else "jamais",
        "Inscrit le": str(c["created_at"])[:10] if c["created_at"] else "—",
        "_id": c["id"],
    })

df_clients = pd.DataFrame(rows_display)

if df_clients.empty:
    st.info("Aucun client enregistré.")
else:
    # Coloration selon statut
    def _highlight(row):
        if "🔴" in str(row.get("Statut", "")):
            return ["background-color: #fee2e2"] * len(row)
        if "🟠" in str(row.get("Statut", "")):
            return ["background-color: #fef3c7"] * len(row)
        return [""] * len(row)

    display_cols = ["Email", "Agence", "Forfait", "Statut", "Abonnement",
                    "Voix (min)", "SMS", "Leads", "Quota %", "Dernière activité", "Inscrit le"]
    st.dataframe(
        df_clients[display_cols].style.apply(_highlight, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(f"**{len(df_clients)} clients** · 🔴 Inactif >7j · 🟠 Quota >80%")

    # ── Actions par client ─────────────────────────────────────────────────────
    st.markdown("### Actions")
    col_sel, col_action, col_plan, col_btn = st.columns([3, 2, 2, 1])

    client_emails = [r["Email"] for r in rows_display]

    with col_sel:
        selected_email = st.selectbox("Sélectionner un client", ["—"] + client_emails, key="admin_client_sel")

    with col_action:
        action = st.selectbox("Action", ["Activer plan", "Désactiver plan", "Changer forfait"], key="admin_action")

    with col_plan:
        new_plan = st.selectbox("Nouveau forfait", ["Indépendant", "Starter", "Pro", "Elite"], key="admin_new_plan")

    with col_btn:
        st.markdown("<div style='margin-top: 28px;'>", unsafe_allow_html=True)
        apply = st.button("Appliquer", type="primary", key="admin_apply")
        st.markdown("</div>", unsafe_allow_html=True)

    if apply and selected_email and selected_email != "—":
        sel_row = next((r for r in rows_display if r["Email"] == selected_email), None)
        if sel_row:
            uid = sel_row["_id"]
            if action == "Activer plan":
                ok = _exec("UPDATE users SET plan_active = TRUE WHERE id = %s", (uid,))
                if ok:
                    st.success(f"✅ Plan activé pour {selected_email}")
            elif action == "Désactiver plan":
                ok = _exec("UPDATE users SET plan_active = FALSE WHERE id = %s", (uid,))
                if ok:
                    st.success(f"✅ Plan désactivé pour {selected_email}")
            elif action == "Changer forfait":
                ok = _exec(
                    "UPDATE users SET plan = %s, plan_active = TRUE WHERE id = %s",
                    (new_plan, uid),
                )
                if ok:
                    st.success(f"✅ Forfait changé en **{new_plan}** pour {selected_email}")

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — ALERTES
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("## 🚨 Alertes")

alert_cols = st.columns(3)

# ── Clients en échec de paiement ────────────────────────────────────────────
with alert_cols[0]:
    st.markdown("### 💳 Échecs de paiement")
    past_due = _safe_query("""
        SELECT email, agency_name, plan
        FROM users
        WHERE subscription_status = 'past_due'
        ORDER BY email
    """)
    if past_due:
        for c in past_due:
            st.markdown(f"""
            <div style="background: #fee2e2; border-left: 4px solid #ef4444;
                        padding: 10px 14px; border-radius: 6px; margin: 6px 0;">
                <strong>{c['agency_name'] or c['email']}</strong><br>
                <small>{c['email']} · {c['plan']}</small>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ Aucun échec de paiement")

# ── Trials expirant dans 7 jours ────────────────────────────────────────────
with alert_cols[1]:
    st.markdown("### ⏳ Trials expirant bientôt")
    expiring = _safe_query("""
        SELECT email, agency_name, plan, trial_ends_at
        FROM users
        WHERE trial_ends_at IS NOT NULL
          AND trial_ends_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'
        ORDER BY trial_ends_at
    """)
    if expiring:
        for c in expiring:
            ends = str(c["trial_ends_at"])[:10] if c["trial_ends_at"] else "?"
            st.markdown(f"""
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b;
                        padding: 10px 14px; border-radius: 6px; margin: 6px 0;">
                <strong>{c['agency_name'] or c['email']}</strong><br>
                <small>Expire le {ends} · {c['plan']}</small>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ Aucun trial expirant sous 7 jours")

# ── Coûts API anormaux (>150% vs mois précédent) ────────────────────────────
with alert_cols[2]:
    st.markdown("### 📈 Coûts API anormaux")
    costs_prev = _safe_query("""
        SELECT provider, SUM(cost_euros) AS total_prev
        FROM api_actions
        WHERE TO_CHAR(created_at, 'YYYY-MM') = %s
        GROUP BY provider
    """, (prev,))
    prev_costs: dict[str, float] = {r["provider"]: r["total_prev"] or 0 for r in costs_prev}

    alerts_found = False
    for r in api_costs:
        prov = r["provider"]
        curr = r["total_euros"] or 0
        prv = prev_costs.get(prov, 0)
        if prv > 0 and curr > prv * 1.5:
            pct_increase = (curr - prv) / prv * 100
            alerts_found = True
            st.markdown(f"""
            <div style="background: #fee2e2; border-left: 4px solid #ef4444;
                        padding: 10px 14px; border-radius: 6px; margin: 6px 0;">
                <strong>{prov}</strong> +{pct_increase:.0f}% vs mois préc.<br>
                <small>{prv:.2f}€ → {curr:.2f}€</small>
            </div>
            """, unsafe_allow_html=True)

    if not alerts_found:
        st.success("✅ Aucun coût anormal détecté")

st.markdown("---")

# ─── Footer admin ────────────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align: center; color: #888; font-size: 11px;'>"
    "🔐 PropPilot Admin · Accès restreint — Données confidentielles"
    "</div>",
    unsafe_allow_html=True,
)
