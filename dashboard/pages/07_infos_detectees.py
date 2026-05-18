"""
Page détail — Informations détectées.
Affiche un lead par carte pour la catégorie sélectionnée sur le tableau de bord.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings
from dashboard.auth_ui import require_auth, render_sidebar_logout
from dashboard.lib.admin_auth import is_super_admin
from dashboard.utils.datetime_helpers import fmt_paris_datetime

settings = get_settings()

st.set_page_config(
    page_title="Informations détectées — PropPilot",
    layout="wide",
    page_icon="🏠",
)

require_auth()
render_sidebar_logout()

if is_super_admin(st.session_state.get("email", "")):
    st.switch_page("pages/99_admin.py")

client_id = st.session_state.get("user_id", settings.agency_client_id)

# ─── CSS ─────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.main { background: #0f1117; }
.block-container { padding-top: 2rem; max-width: 900px; }
h2 { color: white !important; margin-bottom: 0 !important; }
[data-testid="stSidebar"] { background: #1a3a5c; }
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label { color: white !important; }

.lead-card {
    background: #1e2130;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 8px;
}
.lead-name  { color: white; font-weight: 700; font-size: 0.95rem; }
.lead-phone { color: #64748b; font-size: 0.83rem; margin-left: 6px; }
.lead-value { color: #e2e8f0; font-size: 0.88rem; margin: 6px 0 4px; }
.lead-date  { color: #64748b; font-size: 0.77rem; }
.badge-hot  { background:#ef4444; color:white; border-radius:4px; padding:2px 7px; font-size:0.72rem; font-weight:700; }
.badge-warm { background:#f59e0b; color:white; border-radius:4px; padding:2px 7px; font-size:0.72rem; font-weight:700; }
.badge-cold { background:#475569; color:white; border-radius:4px; padding:2px 7px; font-size:0.72rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)

# ─── Paramètres depuis session ────────────────────────────────────────────────

_category     = st.session_state.get("detected_info_category", "budgets")
_period_label = st.session_state.get("dash_period", "30 jours")   # fallback 30 j
_period_days  = {"7 jours": 7, "30 jours": 30, "Depuis le début": 3650}.get(_period_label, 30)

_PERIOD_DISPLAY = {
    "7 jours":        "7 derniers jours",
    "30 jours":       "30 derniers jours",
    "Depuis le début":"depuis le début",
}
_period_display = _PERIOD_DISPLAY.get(_period_label, "30 derniers jours")

_CATEGORY_META = {
    "budgets":     ("💰", "Budgets détectés"),
    "zones":       ("📍", "Zones détectées"),
    "types_bien":  ("🏠", "Types de bien détectés"),
    "motivations": ("💡", "Motivations détectées"),
    "financements":("🏦", "Financements détectés"),
    "objections":  ("⚠️", "Points d'attention détectés"),
}
_icon, _title = _CATEGORY_META.get(_category, ("🔍", _category.replace("_", " ").capitalize()))

# ─── Bouton retour ───────────────────────────────────────────────────────────

if st.button("← Retour au tableau de bord"):
    st.switch_page("pages/tasks.py")

# ─── Titre + période ─────────────────────────────────────────────────────────

st.markdown(f"## {_icon} {_title}")
st.markdown(
    f'<p style="color:#94a3b8;margin-top:-4px;margin-bottom:24px;">'
    f'Période : {_period_display}</p>',
    unsafe_allow_html=True,
)

# ─── Chargement des données ───────────────────────────────────────────────────

try:
    from dashboard.lib.cockpit import get_detected_info_detail
    rows = get_detected_info_detail(client_id, _category, _period_days)
except Exception as exc:
    st.error(f"Impossible de charger les données : {exc}")
    st.stop()

if not rows:
    st.info("Aucune information détectée pour cette catégorie sur cette période.")
    st.stop()

_plural = "s" if len(rows) > 1 else ""
st.markdown(
    f'<p style="color:#94a3b8;margin-bottom:16px;">'
    f'<strong style="color:white;">{len(rows)}</strong> lead{_plural} avec cette information détectée.</p>',
    unsafe_allow_html=True,
)

# ─── Helpers affichage ────────────────────────────────────────────────────────

def _score_badge(score) -> str:
    s = int(score or 0)
    if s >= 18:
        return f'<span class="badge-hot">Chaud · {s}</span>'
    if s >= 11:
        return f'<span class="badge-warm">Tiède · {s}</span>'
    return f'<span class="badge-cold">Froid · {s}</span>'


def _format_value(row: dict, category: str) -> str:
    if category == "budgets":
        lo = row.get("budget_min")
        hi = row.get("budget_max")
        if lo and hi:
            return f"{int(lo):,} € — {int(hi):,} €".replace(",", " ")
        if lo:
            return f"à partir de {int(lo):,} €".replace(",", " ")
        if hi:
            return f"jusqu'à {int(hi):,} €".replace(",", " ")
        return "Budget renseigné"
    if category == "zones":
        return str(row.get("zone_geographique") or "Zone renseignée")
    if category == "types_bien":
        return str(row.get("type_bien") or "Type renseigné")
    if category == "motivations":
        return str(row.get("motivation") or "Motivation renseignée")
    if category == "financements":
        fin = row.get("financement")
        if not fin:
            return "Financement renseigné"
        try:
            d = json.loads(fin) if isinstance(fin, str) else fin
            if not isinstance(d, dict) or not d:
                return "Financement renseigné"
            parts = []
            if d.get("type_pret"):
                parts.append(str(d["type_pret"]))
            if d.get("apport") is not None:
                parts.append(f"apport {int(d['apport']):,} €".replace(",", " "))
            if d.get("banque"):
                parts.append(str(d["banque"]))
            return " · ".join(parts) if parts else "Financement renseigné"
        except Exception:
            return "Financement renseigné"
    if category == "objections":
        pts = row.get("points_attention")
        if not pts:
            return "Point renseigné"
        try:
            items = json.loads(pts) if isinstance(pts, str) else pts
            if isinstance(items, list) and items:
                return " · ".join(str(x) for x in items[:3])
            return "Point renseigné"
        except Exception:
            return "Point renseigné"
    return "Information renseignée"

# ─── Rendu des cartes ─────────────────────────────────────────────────────────

for row in rows:
    lead_id      = row.get("lead_id") or ""
    prenom       = (row.get("prenom") or "").strip()
    nom          = (row.get("nom") or "").strip()
    name         = f"{prenom} {nom}".strip() or (row.get("telephone") or "Prospect")
    phone        = row.get("telephone") or ""
    score        = row.get("score") or 0
    extracted_at = row.get("extracted_at")
    value        = _format_value(row, _category)
    date_str     = fmt_paris_datetime(extracted_at, "%d/%m à %H:%M") if extracted_at else "—"

    card_col, btn_col = st.columns([6, 1])
    with card_col:
        st.markdown(
            f'<div class="lead-card">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
            f'<span class="lead-name">{name}</span>'
            f'<span class="lead-phone">{phone}</span>'
            f'{_score_badge(score)}'
            f'</div>'
            f'<div class="lead-value">{value}</div>'
            f'<div class="lead-date">Détecté le {date_str}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with btn_col:
        if lead_id and st.button("Voir la fiche →", key=f"lead_{lead_id}"):
            st.session_state["selected_lead_id"] = lead_id
            st.switch_page("pages/01_mes_leads.py")
