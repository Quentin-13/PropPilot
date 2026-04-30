"""
Page Mes tâches du jour — reminders créés par l'agent Marc, groupés par urgence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout

settings = get_settings()

st.set_page_config(
    page_title="Mes tâches du jour — PropPilot",
    layout="wide",
    page_icon="📋",
)

print(f"[AUTH-DBG] tasks.py: authenticated={st.session_state.get('authenticated')} "
      f"user_id={st.session_state.get('user_id')} "
      f"proppilot_cc={repr(st.session_state.get('proppilot_cc', '<ABSENT>'))[:80]} "
      f"pending_save={'_proppilot_pending_save' in st.session_state}")

require_auth(write_pending_cookie=True)
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── Header ───────────────────────────────────────────────────────────────────

st.title("📋 Mes tâches du jour")
st.markdown("Relances et actions planifiées par vos agents IA.")

# ─── Chargement ───────────────────────────────────────────────────────────────

try:
    from memory.reminder_repository import (
        get_reminders_by_client,
        mark_reminder_done,
        snooze_reminder,
    )
    reminders = get_reminders_by_client(client_id, include_done=False)
except Exception as exc:
    st.error(f"Impossible de charger les tâches : {exc}")
    st.stop()

# ─── Helpers ──────────────────────────────────────────────────────────────────

now = datetime.now()
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)


def _parse_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None


def _lead_name(r: dict) -> str:
    prenom = r.get("prenom") or ""
    nom = r.get("nom") or ""
    name = f"{prenom} {nom}".strip()
    return name or r.get("lead_id", "—")[:8]


def _type_badge(rtype: str) -> str:
    badges = {
        "nurturing": "💬 Nurturing",
        "rappel": "📞 Rappel",
        "rdv": "📅 RDV",
        "relance": "🔔 Relance",
        "email": "📧 Email",
    }
    return badges.get((rtype or "").lower(), f"🔹 {rtype or '?'}")


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    if dt.date() == now.date():
        return f"Aujourd'hui {dt.strftime('%H:%M')}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Hier {dt.strftime('%H:%M')}"
    return dt.strftime("%d/%m/%Y %H:%M")


# ─── Partitionnement ──────────────────────────────────────────────────────────

overdue, today_tasks, upcoming = [], [], []

for r in reminders:
    sched = _parse_dt(r.get("scheduled_at"))
    if sched is None:
        today_tasks.append(r)
    elif sched < today_start:
        overdue.append(r)
    elif sched < today_end:
        today_tasks.append(r)
    else:
        upcoming.append(r)

# ─── KPIs ─────────────────────────────────────────────────────────────────────

col_k1, col_k2, col_k3 = st.columns(3)
with col_k1:
    color = "#ef4444" if overdue else "#10b981"
    st.markdown(
        f'<div style="background:#1e2130;border-radius:12px;padding:16px;'
        f'border-left:4px solid {color};">'
        f'<div style="font-size:0.85rem;color:#8892a4;">En retard</div>'
        f'<div style="font-size:2rem;font-weight:800;color:white;">{len(overdue)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with col_k2:
    color2 = "#f59e0b" if today_tasks else "#10b981"
    st.markdown(
        f'<div style="background:#1e2130;border-radius:12px;padding:16px;'
        f'border-left:4px solid {color2};">'
        f'<div style="font-size:0.85rem;color:#8892a4;">Aujourd\'hui</div>'
        f'<div style="font-size:2rem;font-weight:800;color:white;">{len(today_tasks)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with col_k3:
    st.markdown(
        f'<div style="background:#1e2130;border-radius:12px;padding:16px;'
        f'border-left:4px solid #3b82f6;">'
        f'<div style="font-size:0.85rem;color:#8892a4;">À venir</div>'
        f'<div style="font-size:2rem;font-weight:800;color:white;">{len(upcoming)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)


# ─── Composant reminder card ──────────────────────────────────────────────────

def _render_reminder(r: dict, section_key: str) -> None:
    rid = r.get("id", "")
    lead_name = _lead_name(r)
    sched = _parse_dt(r.get("scheduled_at"))
    rtype = r.get("type", "nurturing")
    canal = r.get("canal", "sms")
    sujet = r.get("sujet") or ""
    message = r.get("message", "")
    lead_id = r.get("lead_id")

    with st.container():
        cols = st.columns([3, 1.5, 1, 0.8, 0.8])

        with cols[0]:
            title = sujet or (message[:60] + "…" if len(message) > 60 else message)
            st.markdown(
                f"**{title}**  \n"
                f'<span style="color:#94a3b8;font-size:0.82rem;">'
                f"{_type_badge(rtype)} · {canal.upper()}</span>",
                unsafe_allow_html=True,
            )

        with cols[1]:
            if lead_id:
                if st.button(
                    f"👤 {lead_name}",
                    key=f"lead_link_{rid}_{section_key}",
                    help="Voir la fiche lead",
                ):
                    st.session_state["selected_lead_id"] = lead_id
                    st.switch_page("pages/01_mes_leads.py")
            else:
                st.markdown(f"<span style='color:#94a3b8;'>{lead_name}</span>", unsafe_allow_html=True)

        with cols[2]:
            st.markdown(
                f"<span style='color:#94a3b8;font-size:0.85rem;'>{_fmt_dt(sched)}</span>",
                unsafe_allow_html=True,
            )

        with cols[3]:
            if st.button("✅ Fait", key=f"done_{rid}_{section_key}"):
                try:
                    mark_reminder_done(rid)
                    st.success("Marqué comme fait")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        with cols[4]:
            if st.button("⏰ Reporter", key=f"snooze_open_{rid}_{section_key}"):
                st.session_state[f"snooze_{rid}"] = not st.session_state.get(f"snooze_{rid}", False)

        # Formulaire reporter (toggle)
        if st.session_state.get(f"snooze_{rid}", False):
            with st.form(key=f"snooze_form_{rid}_{section_key}"):
                new_date = st.date_input("Nouvelle date", value=now.date() + timedelta(days=1), key=f"sd_{rid}")
                new_time = st.time_input("Heure", value=datetime.strptime("09:00", "%H:%M").time(), key=f"st_{rid}")
                col_ok, col_cancel = st.columns(2)
                with col_ok:
                    if st.form_submit_button("Reporter"):
                        new_dt = datetime.combine(new_date, new_time)
                        try:
                            snooze_reminder(rid, new_dt)
                            st.session_state.pop(f"snooze_{rid}", None)
                            st.success(f"Reporté au {new_dt.strftime('%d/%m %H:%M')}")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                with col_cancel:
                    if st.form_submit_button("Annuler"):
                        st.session_state.pop(f"snooze_{rid}", None)
                        st.rerun()

        st.markdown(
            "<div style='border-bottom:1px solid #1e2130;margin:4px 0;'></div>",
            unsafe_allow_html=True,
        )


# ─── Section : En retard ──────────────────────────────────────────────────────

if overdue:
    st.markdown(
        '<div style="color:#ef4444;font-size:1rem;font-weight:700;'
        'margin-bottom:12px;">🔴 En retard</div>',
        unsafe_allow_html=True,
    )
    for r in overdue:
        _render_reminder(r, "overdue")
    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)

# ─── Section : Aujourd'hui ────────────────────────────────────────────────────

if today_tasks:
    st.markdown(
        '<div style="color:#f59e0b;font-size:1rem;font-weight:700;'
        'margin-bottom:12px;">🟡 À faire aujourd\'hui</div>',
        unsafe_allow_html=True,
    )
    for r in today_tasks:
        _render_reminder(r, "today")
    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)
elif not overdue:
    st.success("Aucune tâche urgente — vous êtes à jour !")
    st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)

# ─── Section : À venir ────────────────────────────────────────────────────────

if upcoming:
    with st.expander(f"📅 À venir — {len(upcoming)} tâche{'s' if len(upcoming) != 1 else ''}"):
        for r in upcoming:
            _render_reminder(r, "upcoming")

# ─── Aucune tâche ─────────────────────────────────────────────────────────────

if not overdue and not today_tasks and not upcoming:
    st.info(
        "Aucune tâche planifiée pour le moment. "
        "L'agent Marc créera automatiquement des rappels lorsque des leads "
        "nécessitent un suivi."
    )
