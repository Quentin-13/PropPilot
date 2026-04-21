"""
Page Conversations — Historique des échanges SMS par lead.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime

from memory.database import init_database

init_database()

st.set_page_config(
    page_title="Conversations — PropPilot",
    page_icon="💬",
    layout="wide",
)

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

from config.settings import get_settings
from memory.database import get_connection
from memory.lead_repository import get_leads_by_client, get_conversation_history

settings = get_settings()
client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── CSS ──────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.msg-user {
    background: #1e2130;
    border-radius: 12px 12px 2px 12px;
    padding: 10px 14px;
    margin: 4px 0 4px 60px;
    color: #e2e8f0;
    font-size: 0.92rem;
    text-align: right;
}
.msg-assistant {
    background: #1a3a5c;
    border-radius: 2px 12px 12px 12px;
    padding: 10px 14px;
    margin: 4px 60px 4px 0;
    color: #e2e8f0;
    font-size: 0.92rem;
}
.msg-meta {
    font-size: 0.75rem;
    color: #64748b;
    margin-bottom: 2px;
}
.lead-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 8px;
    cursor: pointer;
    border-left: 3px solid transparent;
}
.lead-card.selected {
    border-left-color: #3b82f6;
}
</style>
""", unsafe_allow_html=True)

# ─── Données ──────────────────────────────────────────────────────────────────

st.title("💬 Conversations")
st.caption("Historique des échanges SMS entre Léa et vos leads.")

# Leads ayant au moins un message
with get_connection() as conn:
    rows = conn.execute(
        """
        SELECT DISTINCT l.id, l.prenom, l.nom, l.telephone, l.score, l.statut,
               l.localisation, l.source,
               COUNT(c.id) AS nb_messages,
               MAX(c.created_at) AS last_message
        FROM leads l
        JOIN conversations c ON c.lead_id = l.id
        WHERE l.client_id = ?
        GROUP BY l.id
        ORDER BY last_message DESC
        """,
        (client_id,),
    ).fetchall()

if not rows:
    st.info("Aucune conversation pour le moment. Les échanges SMS apparaîtront ici.")
    st.stop()

# ─── Layout deux colonnes ─────────────────────────────────────────────────────

col_list, col_chat = st.columns([1, 2], gap="medium")

# ── Liste des leads avec conversations ────────────────────────────────────────

with col_list:
    st.markdown(f"**{len(rows)} conversation{'s' if len(rows) > 1 else ''}**")
    st.markdown("")

    # Lead sélectionné (par défaut le plus récent)
    if "conv_selected_lead" not in st.session_state:
        st.session_state["conv_selected_lead"] = rows[0]["id"] if rows else None

    for row in rows:
        score = row["score"] or 0
        if score >= 7:
            badge = "🔴"
        elif score >= 4:
            badge = "🟠"
        else:
            badge = "🔵"

        is_selected = st.session_state["conv_selected_lead"] == row["id"]
        border = "border-left: 3px solid #3b82f6;" if is_selected else "border-left: 3px solid transparent;"

        last_msg = row["last_message"]
        if hasattr(last_msg, "strftime"):
            last_str = last_msg.strftime("%d/%m à %H:%M")
        elif isinstance(last_msg, str):
            try:
                last_str = datetime.fromisoformat(last_msg[:19]).strftime("%d/%m à %H:%M")
            except Exception:
                last_str = last_msg[:10]
        else:
            last_str = ""

        if st.button(
            f"{badge} **{row['prenom']} {row['nom']}**  \n"
            f"{row['localisation']} · {row['nb_messages']} messages · {last_str}",
            key=f"btn_conv_{row['id']}",
            use_container_width=True,
        ):
            st.session_state["conv_selected_lead"] = row["id"]
            st.rerun()

# ── Thread de conversation ────────────────────────────────────────────────────

with col_chat:
    selected_id = st.session_state.get("conv_selected_lead")
    if not selected_id:
        st.info("Sélectionnez un lead pour voir la conversation.")
        st.stop()

    # Info lead
    lead_row = next((r for r in rows if r["id"] == selected_id), None)
    if not lead_row:
        st.info("Lead introuvable.")
        st.stop()

    score = lead_row["score"] or 0
    score_emoji = "🔴" if score >= 7 else ("🟠" if score >= 4 else "🔵")
    st.markdown(
        f"### {lead_row['prenom']} {lead_row['nom']} &nbsp; {score_emoji} **{score}/10**"
    )
    st.caption(
        f"{lead_row['localisation']} · {lead_row['source'].capitalize() if lead_row['source'] else ''} · "
        f"{lead_row['statut'].replace('_', ' ').capitalize() if lead_row['statut'] else ''}"
    )
    st.markdown("---")

    messages = get_conversation_history(selected_id, limit=100)
    if not messages:
        st.info("Aucun message dans cette conversation.")
    else:
        for msg in messages:
            role = msg.get("role", "user")
            contenu = msg.get("contenu", "")
            created = msg.get("created_at")

            if hasattr(created, "strftime"):
                time_str = created.strftime("%d/%m %H:%M")
            elif isinstance(created, str):
                try:
                    time_str = datetime.fromisoformat(created[:19]).strftime("%d/%m %H:%M")
                except Exception:
                    time_str = ""
            else:
                time_str = ""

            if role == "user":
                st.markdown(
                    f'<div class="msg-meta" style="text-align: right;">'
                    f'{lead_row["prenom"]} · {time_str}</div>'
                    f'<div class="msg-user">{contenu}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="msg-meta">Léa · {time_str}</div>'
                    f'<div class="msg-assistant">{contenu}</div>',
                    unsafe_allow_html=True,
                )
