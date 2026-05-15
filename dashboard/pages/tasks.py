"""
Cockpit client — page d'accueil PropPilot après connexion.

Sections :
  1. Bandeau du jour (nombre d'actions en attente)
  2. 4 KPI cards (chauds, tièdes, nouveaux, actions)
  3. Actions prioritaires (next_action_* sur leads)
  4. Activité récente (expander)
  5. Rappels planifiés (expander — fonctionnalité préservée)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dashboard.utils.datetime_helpers import to_paris_tz

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout
from dashboard.lib.admin_auth import is_super_admin

settings = get_settings()

st.set_page_config(
    page_title="Tableau de bord — PropPilot",
    layout="wide",
    page_icon="🏠",
)

require_auth(write_pending_cookie=True)
render_sidebar_logout()

if is_super_admin(st.session_state.get("email", "")):
    st.switch_page("pages/99_admin.py")

client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── Chargement cockpit ───────────────────────────────────────────────────────

try:
    from dashboard.lib.cockpit import (
        get_priority_actions,
        get_cockpit_kpis,
        get_recent_activity,
        mark_action_done,
    )
    actions = get_priority_actions(client_id)
    kpis = get_cockpit_kpis(client_id)
except Exception as exc:
    st.error(f"Impossible de charger le tableau de bord : {exc}")
    st.stop()

# ─── Helpers ──────────────────────────────────────────────────────────────────

_now_paris = datetime.now(ZoneInfo("Europe/Paris"))


def _lead_label(row: dict) -> str:
    prenom = row.get("prenom") or ""
    nom = row.get("nom") or ""
    name = f"{prenom} {nom}".strip()
    return name or row.get("telephone") or (row.get("id") or "—")[:8]


def _score_badge(score) -> str:
    s = int(score or 0)
    if s >= 18:
        return '<span style="color:#ef4444;font-weight:700;">● Chaud</span>'
    if s >= 11:
        return '<span style="color:#f59e0b;font-weight:700;">● Tiède</span>'
    return '<span style="color:#64748b;font-weight:600;">● Froid</span>'


def _fmt_dt(val) -> str:
    if not val:
        return "—"
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val)
        except Exception:
            return str(val)
    try:
        val_paris = to_paris_tz(val)
        if val_paris.date() == _now_paris.date():
            return f"Aujourd'hui {val_paris.strftime('%H:%M')}"
        return val_paris.strftime("%d/%m %H:%M")
    except Exception:
        return str(val)


# ─── Bandeau du jour ──────────────────────────────────────────────────────────

n_actions = len(actions)
if n_actions > 0:
    pluriel = "s" if n_actions > 1 else ""
    verb = "nécessitent" if n_actions > 1 else "nécessite"
    st.markdown(
        f'<div style="background:#1c1f2e;border-left:4px solid #a3e635;'
        f'border-radius:8px;padding:12px 16px;margin-bottom:20px;">'
        f'<span style="color:#a3e635;font-weight:700;font-size:1rem;">'
        f'{n_actions} lead{pluriel} {verb} votre attention</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div style="background:#1c1f2e;border-left:4px solid #10b981;'
        'border-radius:8px;padding:12px 16px;margin-bottom:20px;">'
        '<span style="color:#10b981;font-weight:700;font-size:1rem;">'
        '✓ Vous êtes à jour</span>'
        '</div>',
        unsafe_allow_html=True,
    )

# ─── KPI cards ────────────────────────────────────────────────────────────────

def _kpi_card(col, label: str, value: int, color: str) -> None:
    with col:
        st.markdown(
            f'<div style="background:#1e2130;border-radius:12px;padding:16px;'
            f'border-left:4px solid {color};">'
            f'<div style="font-size:0.8rem;color:#8892a4;">{label}</div>'
            f'<div style="font-size:1.8rem;font-weight:800;color:white;">{value}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


col_k1, col_k2, col_k3, col_k4 = st.columns(4)
_kpi_card(col_k1, "Leads chauds",        kpis["chauds"],    "#ef4444")
_kpi_card(col_k2, "Leads tièdes",        kpis["tiedes"],    "#f59e0b")
_kpi_card(col_k3, "Nouveaux (7 jours)",  kpis["nouveaux"],  "#3b82f6")
_kpi_card(col_k4, "Actions en attente",  kpis["actions"],   "#a3e635")

st.markdown("<div style='margin-bottom:28px;'></div>", unsafe_allow_html=True)

# ─── Actions prioritaires ─────────────────────────────────────────────────────

st.markdown(
    '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px;">'
    'Leads nécessitant votre attention</div>',
    unsafe_allow_html=True,
)

if not actions:
    st.markdown(
        '<div style="color:#64748b;padding:20px 0;text-align:center;">'
        'En attente de vos premiers échanges prospects</div>',
        unsafe_allow_html=True,
    )
else:
    hdr = st.columns([2, 1, 3, 3, 1.5])
    for col, label in zip(hdr, ["Lead", "", "Prochaine action", "Pourquoi", ""]):
        with col:
            if label:
                st.markdown(
                    f'<span style="font-size:0.72rem;color:#64748b;font-weight:600;">'
                    f'{label.upper()}</span>',
                    unsafe_allow_html=True,
                )

    st.markdown(
        "<div style='border-bottom:1px solid #1e2130;margin-bottom:8px;'></div>",
        unsafe_allow_html=True,
    )

    for i, row in enumerate(actions):
        lead_id = row["id"]
        cols = st.columns([2, 1, 3, 3, 1.5])

        with cols[0]:
            if st.button(
                _lead_label(row),
                key=f"lead_link_{lead_id}_{i}",
                help="Voir la fiche lead",
            ):
                st.session_state["selected_lead_id"] = lead_id
                st.switch_page("pages/01_mes_leads.py")

        with cols[1]:
            st.markdown(_score_badge(row.get("score")), unsafe_allow_html=True)

        with cols[2]:
            st.markdown(
                f'<span style="color:#e2e8f0;">{row.get("next_action_label") or "—"}</span>',
                unsafe_allow_html=True,
            )

        with cols[3]:
            st.markdown(
                f'<span style="color:#94a3b8;font-size:0.9rem;">'
                f'{row.get("next_action_reason") or "—"}</span>',
                unsafe_allow_html=True,
            )

        with cols[4]:
            if st.button("Marquer comme fait", key=f"done_{lead_id}_{i}"):
                try:
                    mark_action_done(lead_id, client_id)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        st.markdown(
            "<div style='border-bottom:1px solid #1e2130;margin:4px 0;'></div>",
            unsafe_allow_html=True,
        )

st.markdown("<div style='margin-bottom:24px;'></div>", unsafe_allow_html=True)

# ─── Activité récente ─────────────────────────────────────────────────────────

try:
    recent = get_recent_activity(client_id, limit=5)
except Exception:
    recent = []

if recent:
    with st.expander("Activité récente"):
        for row in recent:
            statut = row.get("statut") or ""
            st.markdown(
                f'**{_lead_label(row)}**'
                f' <span style="color:#64748b;font-size:0.85rem;">'
                f'— {statut} · {_fmt_dt(row.get("updated_at"))}</span>',
                unsafe_allow_html=True,
            )

# ─── Rappels planifiés (fonctionnalité préservée) ────────────────────────────

try:
    from memory.reminder_repository import (
        get_reminders_by_client,
        mark_reminder_done,
        snooze_reminder,
    )
    reminders = get_reminders_by_client(client_id, include_done=False)
except Exception:
    reminders = []

if reminders:
    now = datetime.now()

    def _parse_dt(val) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except Exception:
            return None

    def _render_reminder_compact(r: dict) -> None:
        rid = r.get("id", "")
        sujet = r.get("sujet") or r.get("message", "")[:60]
        sched = _parse_dt(r.get("scheduled_at"))
        lead_id = r.get("lead_id")

        cols = st.columns([4, 1.5, 0.8, 0.8])
        with cols[0]:
            st.markdown(
                f'<span style="color:#e2e8f0;">{sujet}</span>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.markdown(
                f'<span style="color:#94a3b8;font-size:0.85rem;">{_fmt_dt(sched)}</span>',
                unsafe_allow_html=True,
            )
        with cols[2]:
            if st.button("✅ Fait", key=f"rem_done_{rid}"):
                try:
                    mark_reminder_done(rid)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with cols[3]:
            if lead_id and st.button("👤", key=f"rem_lead_{rid}", help="Voir lead"):
                st.session_state["selected_lead_id"] = lead_id
                st.switch_page("pages/01_mes_leads.py")
        st.markdown(
            "<div style='border-bottom:1px solid #1e2130;margin:4px 0;'></div>",
            unsafe_allow_html=True,
        )

    with st.expander(f"Rappels planifiés ({len(reminders)})"):
        for r in reminders:
            _render_reminder_compact(r)
