"""
Page SMS — Conversations temps réel style WhatsApp Web.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout

settings = get_settings()

st.set_page_config(
    page_title="SMS — PropPilot",
    layout="wide",
    page_icon="💬",
)

require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)

st.session_state.setdefault("sms_skip_next_refresh", False)
st.session_state.setdefault("sms_thread_opened_at", 0.0)

_autorefresh_ok = False
try:
    from streamlit_autorefresh import st_autorefresh
    _autorefresh_ok = True
except ImportError:
    pass

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _time_ago(dt_str: str | None) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:
            return "à l'instant"
        if diff < 3600:
            return f"il y a {diff // 60} min"
        if diff < 86400:
            return f"il y a {diff // 3600} h"
        return f"il y a {diff // 86400} j"
    except Exception:
        return ""


def _fmt_msg_time(dt_str: str | None) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        paris = dt.astimezone(ZoneInfo("Europe/Paris"))
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        if paris.date() == today:
            return paris.strftime("%H:%M")
        return paris.strftime("%d/%m %H:%M")
    except Exception:
        return ""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


# ─── Chargement threads ───────────────────────────────────────────────────────

try:
    from memory.sms_repository import (
        get_sms_threads,
        get_thread_messages,
        mark_thread_as_read,
        send_sms as _send_sms,
    )
    threads = get_sms_threads(client_id)
except Exception as exc:
    st.error(f"Impossible de charger les conversations SMS : {exc}")
    st.stop()

# ─── Layout WhatsApp Web ──────────────────────────────────────────────────────

st.title("💬 SMS")

col_left, col_right = st.columns([1, 2])

# ═══════════════════════════════════════════════════════════════════════════════
# Colonne gauche — liste des threads
# ═══════════════════════════════════════════════════════════════════════════════

with col_left:
    if st.button("🔄 Rafraîchir", use_container_width=True, key="sms_refresh"):
        st.rerun()

    st.markdown(f"**{len(threads)} conversation{'s' if len(threads) != 1 else ''}**")
    st.markdown("---")

    if not threads:
        st.info("Aucune conversation SMS. Les messages entrants apparaissent ici automatiquement.")
    else:
        selected_id = st.session_state.get("selected_lead_id")

        for thread in threads:
            lead_id = thread["lead_id"]
            prenom = thread.get("prenom") or ""
            nom = thread.get("nom") or ""
            name = f"{prenom} {nom}".strip() or thread.get("telephone") or lead_id[:8]

            preview = (thread.get("dernier_message") or "")[:60]
            if thread.get("dernier_message_role") == "assistant":
                preview = f"vous: {preview}"

            nb_unread = thread.get("nb_non_lus") or 0
            time_str = _time_ago(thread.get("dernier_message_at"))
            is_selected = lead_id == selected_id
            border_color = "#3b82f6" if is_selected else "#2d3748"
            bg_color = "#1a3350" if is_selected else "#1e2130"

            badge_html = ""
            if nb_unread > 0:
                badge_html = (
                    f' <span style="background:#ef4444;color:white;border-radius:10px;'
                    f'padding:1px 7px;font-size:0.72rem;font-weight:700;">{nb_unread}</span>'
                )

            extra_html = ""
            extraction = thread.get("extraction_resume")
            if extraction:
                parts = []
                if extraction.get("budget"):
                    parts.append(f"💰 {_escape(str(extraction['budget']))}")
                if extraction.get("type_bien"):
                    parts.append(f"🏠 {_escape(str(extraction['type_bien']))}")
                if extraction.get("zone"):
                    parts.append(f"📍 {_escape(str(extraction['zone']))}")
                if parts:
                    extra_html = (
                        f'<div style="color:#64748b;font-size:0.74rem;margin-top:3px;">'
                        f'{"&nbsp;·&nbsp;".join(parts)}</div>'
                    )

            st.markdown(
                f'<div style="background:{bg_color};border-radius:8px;padding:10px 12px;'
                f'margin-bottom:4px;border-left:3px solid {border_color};">'
                f'<div style="font-weight:700;color:white;font-size:0.92rem;">'
                f'{_escape(name)}{badge_html}</div>'
                f'<div style="color:#94a3b8;font-size:0.82rem;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;">{_escape(preview)}</div>'
                f'<div style="color:#64748b;font-size:0.74rem;">{time_str}</div>'
                f'{extra_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

            if st.button("Ouvrir →", key=f"thread_{lead_id}", use_container_width=True):
                st.session_state["selected_lead_id"] = lead_id
                st.session_state["sms_thread_opened_at"] = time.time()
                try:
                    mark_thread_as_read(client_id, lead_id)
                except Exception:
                    pass
                st.rerun()

    st.markdown("---")
    if _autorefresh_ok:
        st.caption("🔄 Auto-refresh actif (en pause pendant la frappe)")
    else:
        st.caption("⚠️ streamlit-autorefresh non installé — pip install streamlit-autorefresh")

# ═══════════════════════════════════════════════════════════════════════════════
# Colonne droite — thread sélectionné
# ═══════════════════════════════════════════════════════════════════════════════

with col_right:
    selected_id = st.session_state.get("selected_lead_id")

    if not selected_id:
        st.markdown(
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:400px;color:#64748b;font-size:1.1rem;">'
            '👈 Sélectionnez une conversation</div>',
            unsafe_allow_html=True,
        )
    else:
        try:
            thread_data = get_thread_messages(client_id, selected_id)
        except Exception as exc:
            st.error(f"Impossible de charger la conversation : {exc}")
            st.stop()

        if not thread_data:
            st.error("Conversation introuvable ou accès non autorisé.")
            st.stop()

        lead = thread_data["lead"]
        messages = thread_data.get("messages", [])

        # ── Header ────────────────────────────────────────────────────────────
        lead_prenom = lead.get("prenom") or ""
        lead_nom = lead.get("nom") or ""
        lead_name = f"{lead_prenom} {lead_nom}".strip() or lead.get("telephone") or selected_id[:8]
        lead_tel = lead.get("telephone") or "—"
        lead_score = lead.get("score")
        score_str = f"{lead_score}/10" if lead_score is not None else "—"

        st.markdown(
            f'<div style="background:#1e2130;border-radius:8px;padding:12px 16px;margin-bottom:12px;">'
            f'<div style="font-weight:700;color:white;font-size:1.05rem;">{_escape(lead_name)}</div>'
            f'<div style="color:#94a3b8;font-size:0.84rem;">'
            f'{_escape(lead_tel)}&nbsp;·&nbsp;Score&nbsp;{score_str}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # ── Messages ──────────────────────────────────────────────────────────
        if not messages:
            st.info("Aucun message dans cette conversation.")
        else:
            msgs_html = '<div style="max-height:500px;overflow-y:auto;padding:4px 0;">'
            for msg in messages:
                is_out = msg.get("role") == "assistant"
                align = "flex-end" if is_out else "flex-start"
                bg = "#1a3350" if is_out else "#1e2130"
                radius = (
                    "border-radius:12px 12px 3px 12px;"
                    if is_out
                    else "border-radius:12px 12px 12px 3px;"
                )

                time_str = _fmt_msg_time(msg.get("created_at"))
                meta_html = time_str
                if is_out:
                    status = (msg.get("metadata") or {}).get("status", "")
                    status_icons = {
                        "queued": " ⏳",
                        "sent": " ✓",
                        "delivered": " ✓✓",
                        "failed": " ❌",
                        "undelivered": " ❌",
                    }
                    meta_html += status_icons.get(status, "")

                contenu_escaped = _escape(msg.get("contenu") or "")

                msgs_html += (
                    f'<div style="display:flex;justify-content:{align};margin-bottom:8px;">'
                    f'<div style="max-width:72%;background:{bg};{radius};padding:10px 14px;">'
                    f'<div style="color:#e2e8f0;font-size:0.88rem;line-height:1.45;">'
                    f'{contenu_escaped}</div>'
                    f'<div style="color:#64748b;font-size:0.71rem;margin-top:4px;text-align:right;">'
                    f'{meta_html}</div>'
                    f'</div></div>'
                )
            msgs_html += "</div>"
            st.markdown(msgs_html, unsafe_allow_html=True)

        # ── Zone de saisie ────────────────────────────────────────────────────
        st.markdown("---")
        with st.form("sms_send_form", clear_on_submit=True):
            body = st.text_area(
                "Tapez votre message...",
                height=80,
                key="sms_body_input",
                label_visibility="collapsed",
                placeholder="Tapez votre message...",
            )
            submitted = st.form_submit_button("📤 Envoyer", use_container_width=True)

        if submitted:
            if not body or not body.strip():
                st.error("Le message ne peut pas être vide.")
            else:
                try:
                    _send_sms(client_id, selected_id, body.strip())
                    st.success("SMS envoyé ✓")
                    st.session_state["sms_skip_next_refresh"] = True
                    st.rerun()
                except Exception as exc:
                    st.error(f"Erreur envoi : {exc}")

# ─── Auto-refresh — placé en dernier pour ne pas interrompre les submits ──────

_now = time.time()
_opened_at = st.session_state.get("sms_thread_opened_at", 0.0)
_typed_text = st.session_state.get("sms_body_input", "")
_skip = st.session_state.get("sms_skip_next_refresh", False)

should_skip_autorefresh = (
    (_now - _opened_at < 5)
    or bool(_typed_text and _typed_text.strip())
    or _skip
)

if _skip:
    st.session_state["sms_skip_next_refresh"] = False

if not should_skip_autorefresh and _autorefresh_ok:
    st_autorefresh(interval=10_000, limit=None, key="sms_autorefresh")
