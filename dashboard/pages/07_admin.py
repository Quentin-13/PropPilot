"""
Page Admin — Back-office coûts API, marges, usage par client.
⚠️ ACCÈS RESTREINT — Ne jamais exposer au client final.
Protégée par mot de passe (ADMIN_PASSWORD dans .env).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from config.settings import get_settings
from memory.database import init_database

init_database()
settings = get_settings()

st.set_page_config(page_title="Admin — PropPilot", layout="wide", page_icon="🔐")

# ─── Authentification ─────────────────────────────────────────────────────────

ADMIN_PASSWORD = getattr(settings, "admin_password", None) or "admin2026"

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if not st.session_state.admin_authenticated:
    st.title("🔐 Accès Back-office Admin")
    st.warning("Cette page est réservée à l'équipe interne. Ne jamais partager l'accès.")

    with st.form("auth_form"):
        pwd = st.text_input("Mot de passe admin", type="password")
        submitted = st.form_submit_button("Connexion")

    if submitted:
        if pwd == ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    st.stop()

# ─── Interface admin ──────────────────────────────────────────────────────────

st.title("🔐 Back-office Admin — Coûts & Marges")
st.caption("Usage interne uniquement — Ne jamais exposer au client")

if st.button("Se déconnecter", type="secondary"):
    st.session_state.admin_authenticated = False
    st.rerun()

st.markdown("---")

# ─── Sélection période ────────────────────────────────────────────────────────

col_period, _ = st.columns([1, 3])
with col_period:
    months = [
        (datetime.now() - timedelta(days=i * 30)).strftime("%Y-%m")
        for i in range(6)
    ]
    selected_month = st.selectbox(
        "Mois",
        options=months,
        format_func=lambda x: datetime.strptime(x, "%Y-%m").strftime("%B %Y"),
    )

# ─── Rapport coûts ────────────────────────────────────────────────────────────

from memory.cost_logger import get_cost_report_admin

report = get_cost_report_admin(month=selected_month, client_id=None)

# KPIs globaux
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_rev = report.get("total_revenue_eur", 0)
    st.metric("Revenus SaaS", f"{total_rev:,.0f}€")

with col2:
    total_cost = report.get("total_api_cost_eur", 0)
    st.metric("Coûts API", f"{total_cost:,.2f}€", help="Anthropic + OpenAI + Twilio + ElevenLabs")

with col3:
    margin = report.get("margin_eur", 0)
    margin_pct = report.get("margin_pct", 0)
    delta_color = "normal" if margin >= 0 else "inverse"
    st.metric("Marge brute", f"{margin:,.0f}€", delta=f"{margin_pct:.1f}%")

with col4:
    nb_actions = sum(p.get("nb_actions", 0) for p in report.get("by_provider", []))
    nb_mocks = sum(p.get("mocks", 0) for p in report.get("by_provider", []))
    st.metric("Actions API", nb_actions, delta=f"{nb_mocks} mocks")

st.markdown("---")

# ─── Coûts par provider ───────────────────────────────────────────────────────

st.markdown("### Coûts par provider")

by_provider = report.get("by_provider", [])
if by_provider:
    df_providers = pd.DataFrame(by_provider)
    df_providers["total_cost"] = df_providers["total_cost"].apply(lambda x: f"{x:.4f}€")
    df_providers.columns = df_providers.columns.str.replace("_", " ").str.title()
    st.dataframe(df_providers, use_container_width=True, hide_index=True)
else:
    st.info("Aucune action API enregistrée pour cette période.")

# ─── Coûts par client ─────────────────────────────────────────────────────────

st.markdown("### Coûts par client")

by_client = report.get("by_client", [])
if by_client:
    from config.tier_limits import TIERS

    rows = []
    for client in by_client:
        cid = client.get("client_id", "")
        cost = client.get("total_cost", 0)
        nb = client.get("nb_actions", 0)

        # Récupérer le tier depuis usage_tracking
        from memory.database import get_connection
        with get_connection() as conn:
            usage_row = conn.execute(
                "SELECT tier FROM usage_tracking WHERE client_id = ? AND month = ?",
                (cid, selected_month),
            ).fetchone()

        tier = usage_row["tier"] if usage_row else "Starter"
        revenue = TIERS.get(tier, TIERS["Starter"]).prix_mensuel
        margin_client = revenue - cost
        margin_pct_client = margin_client / revenue * 100 if revenue > 0 else 0

        rows.append({
            "Client ID": cid[:12],
            "Tier": tier,
            "Revenus (€)": revenue,
            "Coûts API (€)": f"{cost:.2f}",
            "Marge (€)": f"{margin_client:.2f}",
            "Marge (%)": f"{margin_pct_client:.1f}%",
            "Actions": nb,
        })

    df_clients = pd.DataFrame(rows)
    st.dataframe(df_clients, use_container_width=True, hide_index=True)
else:
    st.info("Aucune donnée client pour cette période.")

# ─── Détail actions récentes ──────────────────────────────────────────────────

st.markdown("---")
with st.expander("🔍 Dernières actions API (50 lignes)"):
    from memory.database import get_connection

    with get_connection() as conn:
        rows_api = conn.execute(
            """SELECT client_id, action_type, provider, model,
                      tokens_input, tokens_output, cost_euros,
                      success, mock_used, created_at
               FROM api_actions
               WHERE TO_CHAR(created_at, 'YYYY-MM') = ?
               ORDER BY created_at DESC LIMIT 50""",
            (selected_month,),
        ).fetchall()

    if rows_api:
        df_api = pd.DataFrame([dict(r) for r in rows_api])
        df_api["cost_euros"] = df_api["cost_euros"].apply(lambda x: f"{x:.5f}€")
        df_api["mock_used"] = df_api["mock_used"].apply(lambda x: "✅" if x else "—")
        df_api["success"] = df_api["success"].apply(lambda x: "✅" if x else "❌")
        df_api["created_at"] = df_api["created_at"].apply(lambda x: str(x)[:16])
        df_api.rename(columns={
            "client_id": "Client",
            "action_type": "Action",
            "provider": "Provider",
            "model": "Modèle",
            "tokens_input": "Tokens In",
            "tokens_output": "Tokens Out",
            "cost_euros": "Coût",
            "success": "OK",
            "mock_used": "Mock",
            "created_at": "Date",
        }, inplace=True)
        st.dataframe(df_api, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune action API enregistrée.")

# ─── Synchronisation Apimo ────────────────────────────────────────────────────

st.markdown("---")
with st.expander("🔄 Synchronisation CRM Apimo"):
    st.markdown("Synchronise tous les leads qualifiés (score ≥ 7) vers Apimo CRM.")

    if st.button("🔄 Lancer la sync Apimo", type="secondary"):
        from integrations.apimo import ApimoClient
        apimo = ApimoClient()

        with st.spinner("Synchronisation en cours..."):
            result = apimo.sync_all_qualified_leads(settings.agency_client_id)

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.metric("Total leads", result["total"])
        with col_a2:
            st.metric("Synchronisés", result["synced"])
        with col_a3:
            st.metric("Erreurs", result["errors"])

        if result.get("mock"):
            st.info("Mode démo — synchronisation simulée (clés Apimo requises pour production)")
        else:
            st.success("✅ Synchronisation réelle effectuée")

# ─── Reset données démo ───────────────────────────────────────────────────────

st.markdown("---")
with st.expander("⚠️ Actions dangereuses — Base de données"):
    st.warning("Ces actions sont irréversibles.")

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        if st.button("🌱 Recharger données démo", type="secondary"):
            import subprocess
            result = subprocess.run(
                ["python3", str(ROOT / "scripts" / "seed_demo_data.py")],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                st.success("✅ Données démo rechargées")
            else:
                st.error(f"Erreur : {result.stderr[:300]}")

    with col_d2:
        confirm_reset = st.checkbox("Je confirme vouloir TOUT supprimer")
        if st.button("🗑️ Reset base de données", type="secondary", disabled=not confirm_reset):
            import subprocess
            result = subprocess.run(
                ["python3", str(ROOT / "scripts" / "reset_db.py")],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                st.success("✅ Base de données réinitialisée")
            else:
                st.error(f"Erreur : {result.stderr[:300]}")
