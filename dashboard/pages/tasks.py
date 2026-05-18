"""
Tableau de bord client PropPilot.

Répond à 3 questions en moins de 10 secondes :
  1. Qu'est-ce que PropPilot a capté ?
  2. Quels leads nécessitent une action ?
  3. Qu'est-ce qui a été transmis au CRM ?
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout
from dashboard.lib.admin_auth import is_super_admin
from dashboard.utils.datetime_helpers import fmt_paris_datetime, to_paris_tz

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

try:
    from memory.phone_numbers import should_show_welcome
    if should_show_welcome(client_id):
        st.switch_page("pages/00_bienvenue.py")
except Exception:
    pass

# ─── CSS mobile-first ─────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Grille KPI responsive — 3 colonnes desktop, 2 mobile */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 24px;
}
@media (max-width: 700px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}

.kpi-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 16px;
    border-left: 4px solid var(--accent, #3b82f6);
}
.kpi-icon  { font-size: 1.3rem; margin-bottom: 6px; display: block; }
.kpi-val   { font-size: 2rem; font-weight: 800; color: white; line-height: 1.1; }
.kpi-label { font-size: 0.78rem; color: #8892a4; margin-top: 4px; }

/* Grille informations détectées — 3 colonnes desktop, 2 mobile */
.info-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 20px;
}
@media (max-width: 700px) {
    .info-grid { grid-template-columns: repeat(2, 1fr); }
}

.info-card {
    background: #1e2130;
    border-radius: 8px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.info-val   { font-size: 1.5rem; font-weight: 700; color: white; }
.info-label { font-size: 0.78rem; color: #94a3b8; }

/* Carte action lead */
.action-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 8px;
    border-left: 4px solid #a3e635;
}
.action-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}
.action-name  { color: white; font-weight: 600; font-size: 0.95rem; }
.action-next  { color: #e2e8f0; font-size: 0.88rem; margin: 4px 0; }
.action-why   { color: #94a3b8; font-size: 0.82rem; }

/* CRM bloc */
.crm-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 20px;
}
@media (max-width: 700px) {
    .crm-grid { grid-template-columns: repeat(2, 1fr); }
}
.crm-card {
    background: #1e2130;
    border-radius: 8px;
    padding: 12px 14px;
}
.crm-val   { font-size: 1.4rem; font-weight: 700; color: white; }
.crm-label { font-size: 0.78rem; color: #94a3b8; margin-top: 2px; }

/* Activité récente */
.activity-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #1a1d2e;
}
.activity-icon  { font-size: 1.1rem; width: 24px; text-align: center; }
.activity-label { color: #e2e8f0; font-size: 0.88rem; flex: 1; }
.activity-time  { color: #64748b; font-size: 0.78rem; white-space: nowrap; }

/* Bandeau */
.banner {
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 20px;
}
.section-hd {
    font-size: 0.9rem;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin: 20px 0 10px;
}
</style>
""", unsafe_allow_html=True)

# ─── Sélecteur de période ─────────────────────────────────────────────────────

_now_paris = datetime.now(ZoneInfo("Europe/Paris"))

st.title("Tableau de bord")

_period_col, _ = st.columns([2, 4])
with _period_col:
    _period_label = st.radio(
        "Période",
        options=["7 jours", "30 jours", "Depuis le début"],
        horizontal=True,
        label_visibility="collapsed",
        key="dash_period",
    )
_period_days = {"7 jours": 7, "30 jours": 30, "Depuis le début": 3650}.get(_period_label, 7)

# ─── Chargement des données ───────────────────────────────────────────────────

try:
    from dashboard.lib.cockpit import (
        get_priority_actions,
        get_dashboard_kpis,
        get_detected_info_stats,
        get_crm_export_stats,
        get_recent_activity,
        mark_action_done,
    )
    actions  = get_priority_actions(client_id)
    kpis     = get_dashboard_kpis(client_id, _period_days)
    info_stats = get_detected_info_stats(client_id, _period_days)
    crm_stats  = get_crm_export_stats(client_id, _period_days)
    activity   = get_recent_activity(client_id, limit=5)
except Exception as exc:
    st.error(f"Impossible de charger le tableau de bord : {exc}")
    st.stop()

# ─── Bandeau dynamique ────────────────────────────────────────────────────────

_n_actions   = len(actions)
_n_enrichis  = kpis["leads_enrichis"]
_n_appels    = kpis["appels_captes"]
_n_sms       = kpis["sms_captes"]

if _n_actions > 0:
    _pluriel = "s" if _n_actions > 1 else ""
    _verb    = "nécessitent" if _n_actions > 1 else "nécessite"
    _banner_color  = "#a3e635"
    _banner_border = "#a3e635"
    _banner_text   = (
        f"{_n_actions} lead{_pluriel} {_verb} votre attention aujourd'hui."
    )
elif _n_enrichis > 0 or _n_appels > 0 or _n_sms > 0:
    _parts = []
    if _n_enrichis:
        _parts.append(f"enrichi {_n_enrichis} lead{'s' if _n_enrichis > 1 else ''}")
    if _n_appels:
        _parts.append(f"capté {_n_appels} appel{'s' if _n_appels > 1 else ''}")
    if _n_sms:
        _parts.append(f"traité {_n_sms} conversation{'s' if _n_sms > 1 else ''} SMS")
    _banner_color  = "#10b981"
    _banner_border = "#10b981"
    _banner_text   = "Cette semaine, PropPilot a " + " et ".join(_parts) + "."
else:
    _banner_color  = "#3b82f6"
    _banner_border = "#3b82f6"
    _banner_text   = "PropPilot est prêt à capter vos premiers appels et SMS prospects."

st.markdown(
    f'<div class="banner" style="background:#1c1f2e;border-left:4px solid {_banner_border};">'
    f'<span style="color:{_banner_color};font-weight:700;">{_banner_text}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ─── Actions à traiter ────────────────────────────────────────────────────────

st.markdown('<div class="section-hd">Actions à traiter</div>', unsafe_allow_html=True)

if not actions:
    st.markdown(
        '<div style="color:#64748b;padding:16px 0;text-align:center;">'
        '✓ Aucune action en attente</div>',
        unsafe_allow_html=True,
    )
else:
    def _score_badge(score) -> str:
        s = int(score or 0)
        if s >= 18:
            return '<span style="color:#ef4444;font-size:0.8rem;font-weight:700;">● Chaud</span>'
        if s >= 11:
            return '<span style="color:#f59e0b;font-size:0.8rem;font-weight:700;">● Tiède</span>'
        return '<span style="color:#64748b;font-size:0.8rem;font-weight:600;">● Froid</span>'

    def _lead_display(row: dict) -> str:
        prenom = row.get("prenom") or ""
        nom    = row.get("nom") or ""
        name   = f"{prenom} {nom}".strip()
        return name or row.get("telephone") or "Prospect"

    for i, row in enumerate(actions):
        lead_id = row["id"]
        st.markdown(
            f'<div class="action-card">'
            f'<div class="action-top">'
            f'<span class="action-name">{_lead_display(row)}</span>'
            f'{_score_badge(row.get("score"))}'
            f'</div>'
            f'<div class="action-next">→ {row.get("next_action_label") or "—"}</div>'
            f'<div class="action-why">{row.get("next_action_reason") or ""}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _btn_col, _link_col = st.columns([1.5, 4])
        with _btn_col:
            if st.button("Marquer comme fait", key=f"done_{lead_id}_{i}"):
                try:
                    mark_action_done(lead_id, client_id)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with _link_col:
            if st.button(f"Voir la fiche →", key=f"link_{lead_id}_{i}"):
                st.session_state["selected_lead_id"] = lead_id
                st.switch_page("pages/01_mes_leads.py")

# ─── KPI principaux ───────────────────────────────────────────────────────────

st.markdown('<div class="section-hd">Ce que PropPilot a fait</div>', unsafe_allow_html=True)

# (icon, valeur, libellé, couleur, page_cible ou None si même page)
_kpi_defs = [
    ("📞", kpis["appels_captes"],       "Appels captés",        "#3b82f6", "pages/calls.py"),
    ("💬", kpis["sms_captes"],          "SMS captés",           "#8b5cf6", "pages/04_sms.py"),
    ("👤", kpis["leads_crees"],         "Leads créés",          "#10b981", "pages/01_mes_leads.py"),
    ("✨", kpis["leads_enrichis"],      "Leads enrichis",       "#f59e0b", "pages/01_mes_leads.py"),
    ("🔗", kpis["envois_crm"],          "Envois CRM réussis",   "#06b6d4", "pages/06_parametres.py"),
    ("⚡", kpis["actions_recommandees"],"Actions recommandées", "#a3e635", None),
]

for _row_start in (0, 3):
    _cols = st.columns(3)
    for _col, (_icon, _val, _lbl, _color, _target) in zip(_cols, _kpi_defs[_row_start:_row_start + 3]):
        with _col:
            st.markdown(
                f'<div class="kpi-card" style="--accent:{_color};">'
                f'<span class="kpi-icon">{_icon}</span>'
                f'<div class="kpi-val">{_val}</div>'
                f'<div class="kpi-label">{_lbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if _target:
                if st.button("Voir le détail →", key=f"kpi_{_lbl}", use_container_width=True):
                    st.switch_page(_target)
            else:
                st.caption("↑ Voir ci-dessus")

# ─── Informations détectées ───────────────────────────────────────────────────

_info_total = sum(info_stats.values())
if _info_total > 0:
    st.markdown('<div class="section-hd">Informations détectées</div>', unsafe_allow_html=True)

    _info_defs = [
        ("💰", info_stats["budgets"],      "Budgets"),
        ("📍", info_stats["zones"],        "Zones"),
        ("🏠", info_stats["types_bien"],   "Types de bien"),
        ("💡", info_stats["motivations"],  "Motivations"),
        ("🏦", info_stats["financements"], "Financements"),
        ("⚠️", info_stats["objections"],   "Points d'attention"),
    ]
    _shown = [(ic, v, lb) for ic, v, lb in _info_defs if v > 0]

    _info_html = '<div class="info-grid">'
    for icon, val, label in _shown:
        _info_html += (
            f'<div class="info-card">'
            f'<span style="font-size:1.4rem;">{icon}</span>'
            f'<div><div class="info-val">{val}</div>'
            f'<div class="info-label">{label}</div></div>'
            f'</div>'
        )
    _info_html += '</div>'
    st.markdown(_info_html, unsafe_allow_html=True)

# ─── CRM alimenté ─────────────────────────────────────────────────────────────

_crm_configured = False
try:
    from memory.database import get_connection as _gc
    with _gc() as _c:
        _crm_row = _c.execute(
            "SELECT crm_type FROM users WHERE id = ?", (client_id,)
        ).fetchone()
    _crm_configured = bool(_crm_row and (_crm_row.get("crm_type") or "none") != "none")
except Exception:
    pass

if _crm_configured:
    st.markdown('<div class="section-hd">CRM alimenté</div>', unsafe_allow_html=True)

    _last_push_str = (
        fmt_paris_datetime(crm_stats["last_push_at"], "%d/%m à %H:%M")
        if crm_stats["last_push_at"] else "Aucun récemment"
    )
    _crm_html = (
        '<div class="crm-grid">'
        f'<div class="crm-card">'
        f'<div class="crm-val">{crm_stats["success_count"]}</div>'
        f'<div class="crm-label">Leads transmis ({_period_label})</div>'
        f'</div>'
        f'<div class="crm-card">'
        f'<div class="crm-val" style="font-size:1rem;">{_last_push_str}</div>'
        f'<div class="crm-label">Dernier envoi CRM</div>'
        f'</div>'
        '</div>'
    )
    st.markdown(_crm_html, unsafe_allow_html=True)

# ─── Activité récente ─────────────────────────────────────────────────────────

if activity:
    def _fmt_dt(val) -> str:
        if not val:
            return "—"
        try:
            v = to_paris_tz(val if hasattr(val, "tzinfo") else val)
            if v.date() == _now_paris.date():
                return f"Aujourd'hui {v.strftime('%H:%M')}"
            return v.strftime("%d/%m %H:%M")
        except Exception:
            return str(val)[:16]

    with st.expander("Activité récente", expanded=False):
        _rows_html = ""
        for ev in activity:
            _rows_html += (
                f'<div class="activity-row">'
                f'<span class="activity-icon">{ev["icon"]}</span>'
                f'<span class="activity-label">'
                f'<b>{ev["label"]}</b> — {ev["name"]}</span>'
                f'<span class="activity-time">{_fmt_dt(ev["at"])}</span>'
                f'</div>'
            )
        st.markdown(_rows_html, unsafe_allow_html=True)

# ─── Rappels planifiés (fonctionnalité préservée) ─────────────────────────────

try:
    from memory.reminder_repository import (
        get_reminders_by_client,
        mark_reminder_done,
    )
    reminders = get_reminders_by_client(client_id, include_done=False)
except Exception:
    reminders = []

if reminders:
    def _parse_dt(val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except Exception:
            return None

    with st.expander(f"Rappels planifiés ({len(reminders)})"):
        for r in reminders:
            rid   = r.get("id", "")
            sujet = r.get("sujet") or r.get("message", "")[:60]
            sched = _parse_dt(r.get("scheduled_at"))
            _rc1, _rc2, _rc3, _rc4 = st.columns([4, 1.5, 0.8, 0.8])
            with _rc1:
                st.markdown(f'<span style="color:#e2e8f0;">{sujet}</span>', unsafe_allow_html=True)
            with _rc2:
                st.markdown(
                    f'<span style="color:#94a3b8;font-size:0.85rem;">'
                    f'{fmt_paris_datetime(sched, "%d/%m %H:%M") if sched else "—"}'
                    f'</span>',
                    unsafe_allow_html=True,
                )
            with _rc3:
                if st.button("✅ Fait", key=f"rem_done_{rid}"):
                    try:
                        mark_reminder_done(rid)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with _rc4:
                lead_id = r.get("lead_id")
                if lead_id and st.button("👤", key=f"rem_lead_{rid}", help="Voir lead"):
                    st.session_state["selected_lead_id"] = lead_id
                    st.switch_page("pages/01_mes_leads.py")
            st.markdown(
                "<div style='border-bottom:1px solid #1e2130;margin:4px 0;'></div>",
                unsafe_allow_html=True,
            )

# ─── Auto-refresh ─────────────────────────────────────────────────────────────

try:
    from dashboard.lib.auto_refresh import inject_smart_refresh
    inject_smart_refresh(interval_seconds=60)
except Exception:
    pass
