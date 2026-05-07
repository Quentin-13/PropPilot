"""
Dashboard super-admin PropPilot.

Accès réservé aux emails listés dans SUPER_ADMIN_EMAILS (env var).
Accessible via URL directe /99_admin — aucun lien dans les pages client.

5 onglets : Business · Coûts & Marge · Santé produit · Activité utilisateurs · Détail par client
"""
from __future__ import annotations

import csv
import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Admin — PropPilot",
    page_icon="🔐",
    layout="wide",
)

# ─── Garde super-admin ────────────────────────────────────────────────────────

from dashboard.auth_ui import require_auth
from dashboard.lib.admin_auth import is_super_admin
require_auth(require_active_plan=False)

_current_email = (st.session_state.get("email") or "").strip().lower()
if not is_super_admin(_current_email):
    st.error("⛔ Accès refusé. Cette page est réservée aux super-administrateurs.")
    st.stop()

# ─── Log accès ────────────────────────────────────────────────────────────────

from memory.database import get_connection

def _log_admin_access(action: str = "page_view") -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO admin_access_log (user_email, action) VALUES (%s, %s)",
                (_current_email, action),
            )
    except Exception:
        pass  # ne pas bloquer la page si la table n'existe pas encore

_log_admin_access()

# ─── CSS minimal ──────────────────────────────────────────────────────────────

st.markdown("""
<style>
.main { background: #09090b; }
.block-container { padding-top: 1.5rem; max-width: 1300px; }
h1, h2, h3 { color: white !important; }
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarNav"] { display: none !important; }

.admin-metric {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 10px;
    padding: 16px 20px;
}
.admin-metric .label {
    font-size: 0.78rem;
    color: #71717a;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}
.admin-metric .value {
    font-size: 1.9rem;
    font-weight: 800;
    color: white;
    line-height: 1.1;
}
.admin-metric .sub {
    font-size: 0.75rem;
    color: #52525b;
    margin-top: 4px;
}
.admin-metric .lime { color: #a3e635; }
.admin-metric .red  { color: #ef4444; }
.admin-metric .amber { color: #f59e0b; }

.section-sep { border-top: 1px solid #27272a; margin: 28px 0; }
</style>
""", unsafe_allow_html=True)

# ─── Helpers CSS card ─────────────────────────────────────────────────────────

def _card(label: str, value: str, sub: str = "", accent: str = "") -> str:
    accent_cls = f" {accent}" if accent else ""
    return f"""
    <div class="admin-metric">
        <div class="label">{label}</div>
        <div class="value{accent_cls}">{value}</div>
        {"" if not sub else f'<div class="sub">{sub}</div>'}
    </div>"""


# ─── Constantes ───────────────────────────────────────────────────────────────

_PLAN_MRR = {"Indépendant": 390, "Starter": 790, "Pro": 1490, "Elite": 2990}
_INFRA_COST = float(os.environ.get("INFRA_FIXED_COST_EUR_MONTHLY", "20"))
_SCORE_CHAUD = 18
_SCORE_TIEDE = 11


# ══════════════════════════════════════════════════════════════════════════════
# Fonctions admin_get_* — toutes sans filtre client_id (vue globale intentionnelle)
# ══════════════════════════════════════════════════════════════════════════════

def admin_get_clients() -> list[dict]:
    """Tous les clients/users avec leur plan et statut."""
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT id, email, agency_name, plan, plan_active,
                       subscription_status, created_at
                FROM users
                ORDER BY created_at DESC
            """).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_mrr() -> dict:
    """
    MRR calculé depuis users.plan × tarif fixe.
    Sources : table users, colonnes plan + plan_active.
    """
    clients = admin_get_clients()
    paying = [c for c in clients if c.get("plan_active") and c.get("subscription_status") == "active"]
    pilots = [c for c in clients if c.get("plan_active") and c.get("subscription_status") != "active"]
    mrr = sum(_PLAN_MRR.get(c.get("plan", "Starter"), 790) for c in paying)
    return {
        "mrr": mrr,
        "paying_count": len(paying),
        "pilot_count": len(pilots),
        "all_clients": clients,
    }


def admin_get_churn(days: int = 30) -> dict:
    """
    Churn : clients avec plan_active=False mis à jour dans les N derniers jours.
    Note : users n'a pas de colonne updated_at ni churned_at — on compte
    les plan_active=False comme churned, sans date précise.
    TODO: ajouter colonne churned_at à users pour un churn mensuel exact.
    """
    clients = admin_get_clients()
    churned = [c for c in clients if not c.get("plan_active")]
    paying_count = sum(1 for c in clients if c.get("plan_active"))
    total = paying_count + len(churned)
    churn_rate = len(churned) / total if total > 0 else 0
    return {"churned": len(churned), "churn_rate": churn_rate, "paying_count": paying_count}


def admin_get_api_costs(days: int) -> float:
    """Coût tokens API (Claude) sur les N derniers jours."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_euros), 0) FROM api_actions WHERE created_at >= %s",
                (cutoff,),
            ).fetchone()
        return float(row[0] or 0)
    except Exception:
        return 0.0


def admin_get_twilio_costs(days: int) -> float:
    """
    Coût Twilio sur les N derniers jours.
    Source : table twilio_usage (migration 013).
    TODO: instrumenter les webhooks Twilio pour alimenter cette table.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_eur), 0) FROM twilio_usage WHERE created_at >= %s",
                (cutoff,),
            ).fetchone()
        return float(row[0] or 0)
    except Exception:
        return 0.0


def admin_get_api_costs_by_client(days: int = 30) -> list[dict]:
    """Top clients par coût tokens sur N jours."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT a.client_id, u.agency_name,
                       COALESCE(SUM(a.cost_euros), 0) AS cost,
                       COUNT(*) AS nb_calls
                FROM api_actions a
                LEFT JOIN users u ON u.id = a.client_id
                WHERE a.created_at >= %s
                GROUP BY a.client_id, u.agency_name
                ORDER BY cost DESC
                LIMIT 10
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_twilio_costs_by_client(days: int = 30) -> list[dict]:
    """Top clients par coût Twilio sur N jours."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT t.client_id, u.agency_name,
                       COALESCE(SUM(t.cost_eur), 0) AS cost
                FROM twilio_usage t
                LEFT JOIN users u ON u.id = t.client_id
                WHERE t.created_at >= %s
                GROUP BY t.client_id, u.agency_name
                ORDER BY cost DESC
                LIMIT 10
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_lead_stats(days: int = 30, client_id: Optional[str] = None) -> dict:
    """KPIs leads sur N jours, optionnellement filtrés par client."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        extra = "AND client_id = %s" if client_id else ""
        params = (cutoff, client_id) if client_id else (cutoff,)
        with get_connection() as conn:
            row = conn.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE extraction_status = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE score >= {_SCORE_CHAUD}) AS chaud,
                    COUNT(*) FILTER (WHERE score >= {_SCORE_TIEDE} AND score < {_SCORE_CHAUD}) AS tiede,
                    COUNT(*) FILTER (WHERE score < {_SCORE_TIEDE}) AS froid,
                    COUNT(*) FILTER (WHERE lead_type = 'acheteur') AS acheteur,
                    COUNT(*) FILTER (WHERE lead_type = 'vendeur') AS vendeur,
                    COUNT(*) FILTER (WHERE lead_type = 'locataire') AS locataire
                FROM leads
                WHERE created_at >= %s {extra}
            """, params).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def admin_get_extraction_latency_24h() -> Optional[float]:
    """Latence moyenne d'extraction sur 24h (depuis api_actions)."""
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        with get_connection() as conn:
            # metadata stocke parfois la durée — sinon non disponible
            row = conn.execute("""
                SELECT COUNT(*) FROM api_actions
                WHERE created_at >= %s AND action_type ILIKE '%extract%'
            """, (cutoff,)).fetchone()
        # TODO: stocker duration_ms dans api_actions.metadata pour latence réelle
        return None
    except Exception:
        return None


def admin_get_failed_extractions(limit: int = 50, client_id: Optional[str] = None) -> list[dict]:
    """Dernières extractions échouées."""
    try:
        extra = "AND l.client_id = %s" if client_id else ""
        params_list: list = []
        if client_id:
            params_list.append(client_id)
        with get_connection() as conn:
            rows = conn.execute(f"""
                SELECT l.id, l.client_id, u.agency_name,
                       l.extraction_status, l.resume,
                       l.created_at
                FROM leads l
                LEFT JOIN users u ON u.id = l.client_id
                WHERE l.extraction_status = 'failed' {extra}
                ORDER BY l.created_at DESC
                LIMIT %s
            """, (*params_list, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_user_activity(days: int = 7) -> list[dict]:
    """
    Activité utilisateurs sur N jours.
    Source : table user_activity (migration 013).
    TODO: instrumenter les pages dashboard pour alimenter cette table
          (login, vue lead, marquer rappelé).
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT ua.client_id, u.agency_name,
                       COUNT(*) FILTER (WHERE ua.action = 'login') AS logins,
                       COUNT(*) FILTER (WHERE ua.action = 'lead_marked_recontacted') AS marked,
                       MAX(ua.created_at) AS last_activity
                FROM user_activity ua
                LEFT JOIN users u ON u.id = ua.client_id
                WHERE ua.created_at >= %s
                GROUP BY ua.client_id, u.agency_name
                ORDER BY logins DESC
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_last_activity_by_client() -> list[dict]:
    """Dernière activité par client (pour détecter les silencieux)."""
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT u.id, u.agency_name, u.plan, u.plan_active,
                       MAX(ua.created_at) AS last_activity
                FROM users u
                LEFT JOIN user_activity ua ON ua.client_id = u.id
                GROUP BY u.id, u.agency_name, u.plan, u.plan_active
                ORDER BY last_activity ASC NULLS FIRST
            """).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_leads_for_client(client_id: str, limit: int = 20) -> list[dict]:
    """20 derniers leads d'un client spécifique."""
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT id, prenom, nom, lead_type, score,
                       statut, extraction_status, created_at
                FROM leads
                WHERE client_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (client_id, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def admin_get_mrr_history(months: int = 6) -> list[dict]:
    """
    Historique MRR approché : clients actifs par mois depuis usage_tracking.
    TODO: stocker un snapshot MRR mensuel pour une courbe exacte.
    """
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT month, COUNT(DISTINCT client_id) AS clients,
                       SUM(api_cost_euros) AS api_cost
                FROM usage_tracking
                GROUP BY month
                ORDER BY month DESC
                LIMIT %s
            """, (months,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# En-tête
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    "<h1 style='color:white;margin-bottom:4px;'>🔐 Admin PropPilot</h1>"
    f"<p style='color:#52525b;font-size:0.85rem;margin-bottom:24px;'>"
    f"Connecté en tant que <strong style='color:#a3e635;'>{_current_email}</strong> · "
    f"{datetime.now().strftime('%d/%m/%Y %H:%M')}</p>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# Onglets
# ══════════════════════════════════════════════════════════════════════════════

tab_biz, tab_costs, tab_health, tab_users, tab_client = st.tabs(
    ["Business", "Coûts & Marge", "Santé produit", "Activité utilisateurs", "Détail par client"]
)


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 1 — Business / Revenu
# ─────────────────────────────────────────────────────────────────────────────

with tab_biz:
    mrr_data = admin_get_mrr()
    churn_data = admin_get_churn()

    mrr = mrr_data["mrr"]
    paying = mrr_data["paying_count"]
    pilots = mrr_data["pilot_count"]
    churned = churn_data["churned"]
    churn_rate = churn_data["churn_rate"]

    arpu = mrr / paying if paying > 0 else 0
    ltv = arpu / churn_rate if churn_rate > 0 else None

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.markdown(_card("MRR", f"{mrr:,.0f} €".replace(",", " "), "abonnements actifs", "lime"), unsafe_allow_html=True)
    with c2:
        st.markdown(_card("Clients payants", str(paying), "plan_active + stripe active"), unsafe_allow_html=True)
    with c3:
        st.markdown(_card("Pilotes gratuits", str(pilots), "plan_active sans stripe"), unsafe_allow_html=True)
    with c4:
        st.markdown(_card("Churned total", str(churned), "plan_active = False", "red"), unsafe_allow_html=True)
    with c5:
        st.markdown(_card("ARPU", f"{arpu:,.0f} €".replace(",", " "), "MRR / payants"), unsafe_allow_html=True)
    with c6:
        ltv_str = f"{ltv:,.0f} €".replace(",", " ") if ltv else "N/A"
        st.markdown(_card("LTV estimée", ltv_str, "ARPU / churn rate"), unsafe_allow_html=True)

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### Évolution clients actifs par mois")
    st.info(
        "TODO: stocker un snapshot MRR mensuel pour une courbe MRR exacte. "
        "Affiché ci-dessous : nombre de clients actifs par mois depuis usage_tracking.",
        icon="ℹ️",
    )

    history = admin_get_mrr_history(6)
    if history:
        df_hist = pd.DataFrame(history)
        df_hist = df_hist.sort_values("month")
        st.line_chart(df_hist.set_index("month")["clients"], height=200)
    else:
        st.caption("Aucune donnée usage_tracking disponible.")

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### Tous les clients")
    all_clients = mrr_data["all_clients"]
    if all_clients:
        df_clients = pd.DataFrame(all_clients)[
            ["agency_name", "email", "plan", "plan_active", "subscription_status", "created_at"]
        ]
        df_clients.columns = ["Agence", "Email", "Plan", "Actif", "Stripe status", "Inscrit le"]
        st.dataframe(df_clients, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucun client.")


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 2 — Coûts & Marge
# ─────────────────────────────────────────────────────────────────────────────

with tab_costs:
    costs_1d  = admin_get_api_costs(1)
    costs_7d  = admin_get_api_costs(7)
    costs_30d = admin_get_api_costs(30)
    costs_60d = admin_get_api_costs(60)

    twilio_1d  = admin_get_twilio_costs(1)
    twilio_7d  = admin_get_twilio_costs(7)
    twilio_30d = admin_get_twilio_costs(30)
    twilio_60d = admin_get_twilio_costs(60)

    st.markdown("#### Coûts tokens API (Claude)")
    ca1, ca2, ca3, ca4 = st.columns(4)
    for col, label, val in [(ca1, "1 jour", costs_1d), (ca2, "7 jours", costs_7d),
                             (ca3, "30 jours", costs_30d), (ca4, "60 jours", costs_60d)]:
        with col:
            st.markdown(_card(label, f"{val:.3f} €"), unsafe_allow_html=True)

    st.markdown("<div style='margin:16px 0'></div>", unsafe_allow_html=True)
    st.markdown("#### Coûts Twilio (SMS + appels + numéros)")
    st.info(
        "TODO: instrumenter les webhooks Twilio (entrant/sortant) "
        "pour alimenter la table twilio_usage via POST /webhooks/twilio/status.",
        icon="ℹ️",
    )
    ct1, ct2, ct3, ct4 = st.columns(4)
    for col, label, val in [(ct1, "1 jour", twilio_1d), (ct2, "7 jours", twilio_7d),
                             (ct3, "30 jours", twilio_30d), (ct4, "60 jours", twilio_60d)]:
        with col:
            st.markdown(_card(label, f"{val:.3f} €"), unsafe_allow_html=True)

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)

    total_cost_30d = costs_30d + twilio_30d + _INFRA_COST
    mrr_for_margin = admin_get_mrr()["mrr"]
    marge_eur = mrr_for_margin - total_cost_30d
    marge_pct = (marge_eur / mrr_for_margin * 100) if mrr_for_margin > 0 else 0

    leads_30d = admin_get_lead_stats(30).get("total", 0)
    cost_per_lead = (costs_30d + twilio_30d) / leads_30d if leads_30d > 0 else 0

    cm1, cm2, cm3, cm4, cm5 = st.columns(5)
    with cm1:
        st.markdown(_card("Infra fixe / mois", f"{_INFRA_COST:.0f} €", "INFRA_FIXED_COST_EUR_MONTHLY"), unsafe_allow_html=True)
    with cm2:
        st.markdown(_card("Coût total 30j", f"{total_cost_30d:.2f} €", "tokens + Twilio + infra"), unsafe_allow_html=True)
    with cm3:
        accent = "lime" if marge_pct >= 50 else ("amber" if marge_pct >= 0 else "red")
        st.markdown(_card("Marge brute 30j", f"{marge_eur:.0f} €", f"{marge_pct:.1f} %", accent), unsafe_allow_html=True)
    with cm4:
        st.markdown(_card("MRR (source)", f"{mrr_for_margin:,} €".replace(",", " "), "abonnements actifs"), unsafe_allow_html=True)
    with cm5:
        st.markdown(_card("Coût / lead", f"{cost_per_lead:.3f} €", f"{leads_30d} leads 30j"), unsafe_allow_html=True)

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### Top 10 clients — coût tokens 30j")
    top_api = admin_get_api_costs_by_client(30)
    if top_api:
        st.dataframe(
            pd.DataFrame(top_api)[["agency_name", "client_id", "cost", "nb_calls"]].rename(
                columns={"agency_name": "Agence", "client_id": "ID", "cost": "Coût (€)", "nb_calls": "Appels API"}
            ),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("Aucune donnée api_actions sur 30j.")

    st.markdown("#### Top 10 clients — coût Twilio 30j")
    top_twilio = admin_get_twilio_costs_by_client(30)
    if top_twilio:
        st.dataframe(
            pd.DataFrame(top_twilio)[["agency_name", "client_id", "cost"]].rename(
                columns={"agency_name": "Agence", "client_id": "ID", "cost": "Coût Twilio (€)"}
            ),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("Aucune donnée twilio_usage sur 30j (table vide — voir TODO ci-dessus).")

    st.markdown("#### Coût vs Revenu par client (30j)")
    all_c = admin_get_mrr()["all_clients"]
    cost_map = {r["client_id"]: r["cost"] for r in top_api}
    rows_margin = []
    for c in all_c:
        if not c.get("plan_active"):
            continue
        rev = _PLAN_MRR.get(c.get("plan", "Starter"), 790)
        cost = cost_map.get(c["id"], 0.0)
        margin = rev - cost - _INFRA_COST / max(len(all_c), 1)
        rows_margin.append({
            "Agence": c.get("agency_name", "—"),
            "MRR (€)": rev,
            "Coût tokens (€)": round(cost, 3),
            "Marge (€)": round(margin, 2),
            "Marge %": f"{margin/rev*100:.1f}%" if rev else "—",
        })
    if rows_margin:
        df_margin = pd.DataFrame(rows_margin).sort_values("Marge (€)")
        st.dataframe(df_margin, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucun client payant actif.")


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 3 — Santé produit
# ─────────────────────────────────────────────────────────────────────────────

with tab_health:
    stats_1d  = admin_get_lead_stats(1)
    stats_7d  = admin_get_lead_stats(7)
    stats_30d = admin_get_lead_stats(30)

    total_1d  = stats_1d.get("total", 0)
    failed_1d = stats_1d.get("failed", 0)
    fail_rate = failed_1d / total_1d if total_1d > 0 else 0

    # ── Alertes ──────────────────────────────────────────────────────────────
    if fail_rate > 0.05:
        st.error(
            f"🚨 Taux d'extractions échouées sur 24h : **{fail_rate:.0%}** "
            f"({failed_1d}/{total_1d}) — seuil 5% dépassé.",
        )
    if total_1d == 0:
        now_h = datetime.now().hour
        if 8 <= now_h <= 20:
            st.warning("⚠️ Aucun lead extrait depuis plus de 6h en heures ouvrées.")

    # ── KPIs ─────────────────────────────────────────────────────────────────
    h1, h2, h3, h4, h5 = st.columns(5)
    with h1:
        st.markdown(_card("Leads 1j", str(total_1d)), unsafe_allow_html=True)
    with h2:
        st.markdown(_card("Leads 7j", str(stats_7d.get("total", 0))), unsafe_allow_html=True)
    with h3:
        st.markdown(_card("Leads 30j", str(stats_30d.get("total", 0))), unsafe_allow_html=True)
    with h4:
        accent = "red" if fail_rate > 0.05 else ""
        st.markdown(
            _card("Taux failed 24h", f"{fail_rate:.1%}", f"{failed_1d}/{total_1d}", accent),
            unsafe_allow_html=True,
        )
    with h5:
        latency = admin_get_extraction_latency_24h()
        lat_str = f"{latency:.1f}s" if latency else "N/A"
        st.markdown(
            _card("Latence moy. 24h", lat_str, "TODO: stocker duration_ms"),
            unsafe_allow_html=True,
        )

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)

    col_dist, col_score = st.columns(2)

    with col_dist:
        st.markdown("#### Distribution lead_type — 30j")
        types = {
            "Acheteur": stats_30d.get("acheteur", 0),
            "Vendeur": stats_30d.get("vendeur", 0),
            "Locataire": stats_30d.get("locataire", 0),
        }
        if sum(types.values()) > 0:
            st.bar_chart(pd.DataFrame.from_dict(types, orient="index", columns=["leads"]), height=180)
        else:
            st.caption("Aucun lead sur 30j.")

    with col_score:
        st.markdown("#### Distribution scores — 30j")
        scores = {
            "Chaud (≥18)": stats_30d.get("chaud", 0),
            "Tiède (11-17)": stats_30d.get("tiede", 0),
            "Froid (<11)": stats_30d.get("froid", 0),
        }
        if sum(scores.values()) > 0:
            st.bar_chart(pd.DataFrame.from_dict(scores, orient="index", columns=["leads"]), height=180)
        else:
            st.caption("Aucun lead scoré sur 30j.")

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### Extractions échouées récentes")

    all_clients_map = {c["id"]: c.get("agency_name", "—") for c in admin_get_clients()}
    filter_cid = st.selectbox(
        "Filtrer par client",
        options=["Tous"] + list(all_clients_map.values()),
        key="health_filter_client",
    )
    cid_filter = None
    if filter_cid != "Tous":
        cid_filter = next((k for k, v in all_clients_map.items() if v == filter_cid), None)

    failed_rows = admin_get_failed_extractions(limit=50, client_id=cid_filter)
    if failed_rows:
        df_failed = pd.DataFrame(failed_rows)
        df_failed["resume"] = df_failed["resume"].str[:200]
        df_failed = df_failed[["id", "agency_name", "extraction_status", "resume", "created_at"]].rename(
            columns={
                "id": "Lead ID", "agency_name": "Agence",
                "extraction_status": "Statut", "resume": "Résumé (tronqué)",
                "created_at": "Date",
            }
        )
        st.dataframe(df_failed, use_container_width=True, hide_index=True)
    else:
        st.success("Aucune extraction échouée — tout est nominal.")


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 4 — Activité utilisateurs
# ─────────────────────────────────────────────────────────────────────────────

with tab_users:
    st.info(
        "Les métriques d'activité proviennent de la table **user_activity** (migration 013). "
        "TODO: instrumenter les pages dashboard (login, vue lead, marquer rappelé) "
        "pour alimenter cette table en production.",
        icon="ℹ️",
    )

    activity = admin_get_user_activity(7)
    total_logins_7d = sum(r.get("logins", 0) for r in activity)
    active_clients = sum(1 for r in activity if (r.get("logins") or 0) > 0)
    total_clients = len(admin_get_clients())
    silent_clients = total_clients - active_clients
    total_marked_7d = sum(r.get("marked", 0) for r in activity)
    total_marked_30d = sum(r.get("marked", 0) for r in admin_get_user_activity(30))

    u1, u2, u3, u4 = st.columns(4)
    with u1:
        st.markdown(_card("Logins 7j", str(total_logins_7d), "tous clients"), unsafe_allow_html=True)
    with u2:
        st.markdown(_card("Clients actifs 7j", str(active_clients), f"sur {total_clients} total"), unsafe_allow_html=True)
    with u3:
        accent = "red" if silent_clients > active_clients else ""
        st.markdown(_card("Clients silencieux", str(silent_clients), "0 login depuis 7j", accent), unsafe_allow_html=True)
    with u4:
        st.markdown(_card("Marquer rappelé 7j", str(total_marked_7d), f"{total_marked_30d} sur 30j"), unsafe_allow_html=True)

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)

    last_activity = admin_get_last_activity_by_client()
    now_dt = datetime.utcnow()

    st.markdown("#### Clients silencieux à surveiller")
    silent_rows = []
    for c in last_activity:
        if not c.get("plan_active"):
            continue
        last = c.get("last_activity")
        days_ago = (now_dt - last).days if last else 999
        if days_ago >= 7:
            silent_rows.append({
                "Agence": c.get("agency_name", "—"),
                "Dernier login": last.strftime("%d/%m/%Y") if last else "jamais",
                "MRR (€)": _PLAN_MRR.get(c.get("plan", "Starter"), 0),
                "Jours inactif": days_ago,
            })
    if silent_rows:
        df_silent = pd.DataFrame(silent_rows).sort_values("MRR (€)", ascending=False)
        for _, row in df_silent.iterrows():
            col_data, col_btn = st.columns([5, 1])
            with col_data:
                st.markdown(
                    f"**{row['Agence']}** · {row['MRR (€)']} €/mois · "
                    f"inactif depuis {row['Jours inactif']}j · dernier login {row['Dernier login']}"
                )
            with col_btn:
                st.button("📧 Check-in", key=f"checkin_{row['Agence']}", disabled=True)
                st.caption("Bientôt disponible")
    else:
        if not last_activity:
            st.caption("Aucune activité enregistrée (table user_activity vide — voir TODO).")
        else:
            st.success("Tous les clients actifs se sont connectés dans les 7 derniers jours.")

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### Top clients actifs — 7j")
    if activity:
        df_active = pd.DataFrame(activity)[["agency_name", "logins", "marked", "last_activity"]].rename(
            columns={
                "agency_name": "Agence", "logins": "Logins 7j",
                "marked": "Marquer rappelé", "last_activity": "Dernière activité",
            }
        )
        st.dataframe(df_active, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucune activité enregistrée.")


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET 5 — Détail par client
# ─────────────────────────────────────────────────────────────────────────────

with tab_client:
    all_c = admin_get_clients()
    if not all_c:
        st.info("Aucun client en base.")
        st.stop()

    options = {f"{c.get('agency_name', '—')} ({c.get('email', '')})": c["id"] for c in all_c}
    selected_label = st.selectbox("Sélectionner un client", list(options.keys()))
    selected_cid = options[selected_label]
    selected_client = next((c for c in all_c if c["id"] == selected_cid), {})

    plan = selected_client.get("plan", "Starter")
    mrr_client = _PLAN_MRR.get(plan, 0) if selected_client.get("plan_active") else 0
    cost_tokens = admin_get_api_costs(30)  # TODO: filtrer par client dans api_actions
    # Filtrage précis par client
    try:
        cutoff_30 = datetime.utcnow() - timedelta(days=30)
        with get_connection() as conn:
            row_c = conn.execute(
                "SELECT COALESCE(SUM(cost_euros), 0) FROM api_actions WHERE client_id = %s AND created_at >= %s",
                (selected_cid, cutoff_30),
            ).fetchone()
        cost_tokens_client = float(row_c[0] or 0)
    except Exception:
        cost_tokens_client = 0.0

    twilio_client = admin_get_twilio_costs(30)  # TODO: filtrer par client_id
    marge_client = mrr_client - cost_tokens_client - _INFRA_COST / max(len(all_c), 1)

    # ── Vue 360° ──────────────────────────────────────────────────────────────
    st.markdown(f"### {selected_client.get('agency_name', '—')}")
    ci1, ci2, ci3, ci4 = st.columns(4)
    with ci1:
        st.metric("Plan", plan)
    with ci2:
        status = "Actif" if selected_client.get("plan_active") else "Inactif"
        st.metric("Statut", status)
    with ci3:
        st.metric("MRR", f"{mrr_client} €")
    with ci4:
        st.metric("Inscrit le", str(selected_client.get("created_at", "—"))[:10])

    st.markdown("<div style='margin:12px 0'></div>", unsafe_allow_html=True)
    ci5, ci6, ci7 = st.columns(3)
    with ci5:
        st.markdown(_card("Coût tokens 30j", f"{cost_tokens_client:.3f} €"), unsafe_allow_html=True)
    with ci6:
        st.markdown(_card("Coût Twilio 30j", "N/A", "TODO: filtrer twilio_usage"), unsafe_allow_html=True)
    with ci7:
        accent = "lime" if marge_client >= 0 else "red"
        st.markdown(_card("Marge brute 30j", f"{marge_client:.0f} €", "", accent), unsafe_allow_html=True)

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)

    stats_client_30 = admin_get_lead_stats(30, client_id=selected_cid)
    stats_client_7  = admin_get_lead_stats(7,  client_id=selected_cid)
    stats_client_all = admin_get_lead_stats(3650, client_id=selected_cid)

    cl1, cl2, cl3 = st.columns(3)
    with cl1:
        st.metric("Leads total", stats_client_all.get("total", 0))
    with cl2:
        st.metric("Leads 30j", stats_client_30.get("total", 0))
    with cl3:
        st.metric("Leads 7j", stats_client_7.get("total", 0))

    col_t, col_s = st.columns(2)
    with col_t:
        st.markdown("**Types de leads (30j)**")
        types_c = {
            "Acheteur": stats_client_30.get("acheteur", 0),
            "Vendeur": stats_client_30.get("vendeur", 0),
            "Locataire": stats_client_30.get("locataire", 0),
        }
        if sum(types_c.values()) > 0:
            st.bar_chart(pd.DataFrame.from_dict(types_c, orient="index", columns=["leads"]), height=150)
        else:
            st.caption("Aucun lead sur 30j.")
    with col_s:
        st.markdown("**Scores (30j)**")
        scores_c = {
            "Chaud": stats_client_30.get("chaud", 0),
            "Tiède": stats_client_30.get("tiede", 0),
            "Froid": stats_client_30.get("froid", 0),
        }
        if sum(scores_c.values()) > 0:
            st.bar_chart(pd.DataFrame.from_dict(scores_c, orient="index", columns=["leads"]), height=150)
        else:
            st.caption("Aucun lead scoré sur 30j.")

    st.markdown("<div class='section-sep'></div>", unsafe_allow_html=True)
    st.markdown("#### 20 derniers leads")
    leads_client = admin_get_leads_for_client(selected_cid, 20)
    if leads_client:
        df_leads = pd.DataFrame(leads_client)[[
            "id", "prenom", "nom", "lead_type", "score", "statut", "extraction_status", "created_at"
        ]].rename(columns={
            "id": "ID", "prenom": "Prénom", "nom": "Nom", "lead_type": "Type",
            "score": "Score", "statut": "Statut", "extraction_status": "Extraction",
            "created_at": "Date",
        })
        st.dataframe(df_leads, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucun lead pour ce client.")

    st.markdown("<div style='margin:16px 0'></div>", unsafe_allow_html=True)

    # ── Export CSV ────────────────────────────────────────────────────────────
    if leads_client:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=leads_client[0].keys())
        writer.writeheader()
        writer.writerows(leads_client)
        st.download_button(
            "⬇️ Exporter leads CSV",
            data=buf.getvalue(),
            file_name=f"leads_{selected_client.get('agency_name', selected_cid)}_{datetime.now():%Y%m%d}.csv",
            mime="text/csv",
        )
