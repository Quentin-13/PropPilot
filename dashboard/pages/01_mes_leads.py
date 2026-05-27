"""
Page Leads — Mode agent-first : liste cartes → fiche détail → retour.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime

from config.settings import get_settings
from dashboard.utils.datetime_helpers import fmt_paris_datetime
from dashboard.utils.lead_formatters import format_lead_status
from dashboard.utils.call_helpers import render_call_button
from memory.lead_repository import (
    get_leads_by_client,
    search_leads_by_text,
    update_lead,
    add_conversation_message,
)
from memory.models import Canal, Lead, LeadStatus

settings = get_settings()

st.set_page_config(page_title="Mes leads — PropPilot", layout="wide", page_icon="👥")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

st.markdown("""
<style>
.main, [data-testid="stAppViewContainer"] { background: #0f1117; }
.block-container { padding-top: 1.5rem; }
h1, h2, h3, h4, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 { color: white !important; }
p, .stMarkdown p, .stMarkdown li { color: #e2e8f0; }
label, .stSelectbox label, .stSlider label { color: #cbd5e1 !important; }
[data-testid="stMain"] .stButton > button {
    background: #1e2130 !important;
    color: #e2e8f0 !important;
    border: 1px solid #334155 !important;
}
[data-testid="stMain"] .stButton > button[kind="primary"] {
    background: #3b82f6 !important;
    color: white !important;
    border: none !important;
}
[data-testid="stMain"] .stButton > button:hover { opacity: 0.85; }
/* Lead cards */
.lead-card {
    background: #1a1f35;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 4px;
}
.lead-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.lead-card-name { color: white; font-weight: 600; font-size: 1rem; }
.lead-card-action { color: #94a3b8; font-size: 0.82rem; }
.lead-card-meta { color: #64748b; font-size: 0.78rem; margin-top: 4px; }
.badge-chaud { background:#7f1d1d; color:#fca5a5; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600; white-space:nowrap; }
.badge-tiede { background:#78350f; color:#fcd34d; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600; white-space:nowrap; }
.badge-froid { background:#1e3a5f; color:#93c5fd; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600; white-space:nowrap; }
/* Detail panel */
.detail-header {
    background: #1a1f35;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.detail-name { color: white; font-weight: 700; font-size: 1.2rem; }
.detail-phone { color: #94a3b8; font-size: 0.9rem; margin-top: 2px; }
/* Mobile */
@media (max-width: 768px) {
    .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
    .detail-header { padding: 14px 14px; }
}
</style>
""", unsafe_allow_html=True)

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

# ─── Navigation pre-sélection (depuis page SMS) ──────────────────────────────

if "selected_lead_id" in st.session_state:
    _nav_id = st.session_state.pop("selected_lead_id")
    st.session_state["detail_lead_id"] = _nav_id
    st.query_params["lead"] = _nav_id
elif not st.session_state.get("detail_lead_id") and st.query_params.get("lead"):
    # Récupération après location.reload() : session_state perdu, query_param conservé
    st.session_state["detail_lead_id"] = st.query_params["lead"]

_in_detail = bool(st.session_state.get("detail_lead_id"))

# ─── Recherche + filtres (toujours lus, affichés seulement en mode liste) ──────

_STATUT_FILTER = {"Tous": None, **{format_lead_status(s.value): s.value for s in LeadStatus}}

if not _in_detail:
    st.title("Mes leads")

    search_query = st.text_input(
        "Recherche",
        placeholder="Rechercher un lead, une ville, un budget…",
        key="search_query",
        label_visibility="collapsed",
    )

    with st.expander("Filtres"):
        adv_col1, adv_col2, adv_col3, adv_col4 = st.columns(4)
        with adv_col1:
            filter_statut_label = st.selectbox(
                "Statut",
                options=list(_STATUT_FILTER.keys()),
                key="filter_statut",
            )
            filter_statut = _STATUT_FILTER[filter_statut_label]
        with adv_col2:
            filter_source = st.selectbox(
                "Source",
                options=["Toutes", "sms", "whatsapp", "email", "web", "seloger", "leboncoin", "manuel"],
                key="filter_source",
            )
        with adv_col3:
            filter_type = st.selectbox(
                "Type",
                options=["Tous", "acheteur", "vendeur", "locataire"],
                key="filter_type",
            )
        with adv_col4:
            filter_projet = st.selectbox(
                "Projet",
                options=["Tous", "achat", "vente", "location", "estimation", "inconnu"],
                key="filter_projet",
            )
else:
    # Mode détail — lire les valeurs sans recréer les widgets
    search_query = st.session_state.get("search_query", "")
    filter_statut = _STATUT_FILTER.get(st.session_state.get("filter_statut", "Tous"))
    filter_source = st.session_state.get("filter_source", "Toutes")
    filter_type = st.session_state.get("filter_type", "Tous")
    filter_projet = st.session_state.get("filter_projet", "Tous")

filter_score_min = 0

# ─── Chargement leads ─────────────────────────────────────────────────────────

if search_query:
    leads = search_leads_by_text(
        client_id=client_id,
        query=search_query,
        statut=filter_statut,
        score_min=filter_score_min if filter_score_min > 0 else None,
    )
else:
    leads = get_leads_by_client(
        client_id=client_id,
        statut=filter_statut,
        score_min=filter_score_min if filter_score_min > 0 else None,
        limit=200,
    )

if filter_type != "Tous":
    leads = [l for l in leads if getattr(l, "lead_type", "acheteur") == filter_type]
if filter_source != "Toutes":
    leads = [l for l in leads if l.source.value == filter_source]
if filter_projet != "Tous":
    leads = [l for l in leads if l.projet.value == filter_projet]

_next_actions: dict[str, dict] = {}
if leads:
    try:
        from memory.database import get_connection as _gc_na
        _lead_ids = [l.id for l in leads]
        _placeholders = ",".join(["?"] * len(_lead_ids))
        with _gc_na() as _conn_na:
            _na_rows = _conn_na.execute(
                f"SELECT id, next_action_label, next_action_priority, next_action_reason, next_action_deadline "
                f"FROM leads WHERE id IN ({_placeholders})",
                _lead_ids,
            ).fetchall()
        for _r in _na_rows:
            _next_actions[_r["id"]] = dict(_r)
    except Exception:
        pass

# ─── Helpers ──────────────────────────────────────────────────────────────────

_TYPE_ICONS = {"vendeur": "🏠", "acheteur": "🔑", "locataire": "🏢"}
_PRIORITY_ICONS = {"haute": "🔴", "moyenne": "🟡", "basse": "🔵"}
_PRIORITY_ORDER = {"haute": 0, "moyenne": 1, "basse": 2}


def _score_level(score: int) -> tuple[str, str]:
    if score >= 18:
        return "Chaud", "badge-chaud"
    elif score >= 11:
        return "Tiède", "badge-tiede"
    return "Froid", "badge-froid"


# ─── MODE DÉTAIL ──────────────────────────────────────────────────────────────

if _in_detail:
    lead_id = st.session_state["detail_lead_id"]

    # Bouton retour (en premier, visible immédiatement)
    if st.button("← Retour aux leads", key="back_btn"):
        del st.session_state["detail_lead_id"]
        if "lead" in st.query_params:
            del st.query_params["lead"]
        st.rerun()

    selected_lead = next((l for l in leads if l.id == lead_id), None)

    # Fallback : lead hors filtres (navigation depuis SMS par exemple)
    if not selected_lead:
        try:
            _all = get_leads_by_client(client_id=client_id, limit=1000)
            selected_lead = next((l for l in _all if l.id == lead_id), None)
        except Exception:
            pass

    # Charger next_action si absent (lead hors filtres)
    if selected_lead and lead_id not in _next_actions:
        try:
            from memory.database import get_connection as _gc2
            with _gc2() as _conn2:
                _r2 = _conn2.execute(
                    "SELECT id, next_action_label, next_action_priority, next_action_reason, next_action_deadline "
                    "FROM leads WHERE id = ?",
                    [lead_id],
                ).fetchone()
                if _r2:
                    _next_actions[lead_id] = dict(_r2)
        except Exception:
            pass

    if not selected_lead:
        st.warning("Lead introuvable. Il a peut-être été supprimé ou n'est pas dans les résultats actuels.")
    else:
        _na = _next_actions.get(selected_lead.id, {})
        _na_label = _na.get("next_action_label")
        _na_prio = _na.get("next_action_priority") or "moyenne"
        _na_reason = _na.get("next_action_reason") or ""
        _na_deadline = _na.get("next_action_deadline")
        _level, _badge_cls = _score_level(selected_lead.score)
        _prio_colors = {"haute": "#ef4444", "moyenne": "#f59e0b", "basse": "#3b82f6"}
        _prio_color = _prio_colors.get(_na_prio, "#6b7280")

        # 1. Header — nom / téléphone / niveau
        st.markdown(
            f'<div class="detail-header">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'<div>'
            f'<div class="detail-name">{selected_lead.nom_complet}</div>'
            f'<div class="detail-phone">{selected_lead.telephone or "Pas de téléphone"}</div>'
            f'</div>'
            f'<span class="{_badge_cls}">{_level}</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 2. Bloc action — prochaine action + raison
        if _na_label:
            _deadline_str = ""
            if _na_deadline:
                _dl = _na_deadline
                if isinstance(_dl, str):
                    try:
                        _dl = datetime.fromisoformat(_dl)
                    except Exception:
                        _dl = None
                if _dl:
                    _deadline_str = f" · Avant le {_dl.strftime('%d/%m/%Y %H:%M')}"
            st.markdown(
                f'<div style="background:#1e2130;border-radius:8px;padding:14px 18px;'
                f'border-left:4px solid {_prio_color};margin-bottom:12px;">'
                f'<div style="color:#94a3b8;font-size:0.78rem;margin-bottom:4px;">'
                f'ACTION RECOMMANDÉE · Priorité {_na_prio.upper()}{_deadline_str}</div>'
                f'<div style="color:white;font-weight:600;font-size:1rem;">{_na_label}</div>'
                + (f'<div style="color:#94a3b8;font-size:0.82rem;margin-top:6px;">{_na_reason}</div>' if _na_reason else "")
                + '</div>',
                unsafe_allow_html=True,
            )

        # 3. Boutons — Appeler / SMS / Marquer fait
        _lead_tel = selected_lead.telephone or ""
        _act_c1, _act_c2, _act_c3 = st.columns(3)
        with _act_c1:
            render_call_button(
                lead_id=lead_id,
                lead_phone=_lead_tel or None,
                client_id=client_id,
                api_url=settings.api_url,
                key=f"call_{lead_id}",
            )
        with _act_c2:
            if st.button("SMS / Conversation", key=f"sms_{lead_id}", use_container_width=True):
                st.session_state["selected_lead_id"] = lead_id
                st.switch_page("pages/04_sms.py")
        with _act_c3:
            if _na_label:
                if st.button("Marquer fait", key=f"done_{lead_id}", use_container_width=True):
                    if selected_lead.statut.value in ("entrant", "nurturing"):
                        selected_lead.statut = LeadStatus.QUALIFIE
                        update_lead(selected_lead)
                        st.success("Action marquée comme effectuée.")
                        st.rerun()
                    else:
                        st.info(f"Statut actuel : {format_lead_status(selected_lead.statut.value)}")

        # 4. Résumé automatique
        if selected_lead.resume:
            st.markdown(
                f'<div style="background:#1e2130;border-radius:8px;padding:12px 16px;'
                f'margin:10px 0;border-left:3px solid #334155;color:#e2e8f0;'
                f'font-size:0.9rem;font-style:italic;">{selected_lead.resume}</div>',
                unsafe_allow_html=True,
            )

        # 5. Informations utiles — visible sans expander
        try:
            from memory.call_repository import get_latest_extraction_for_lead
            _last_ext = get_latest_extraction_for_lead(lead_id)
        except Exception:
            _last_ext = None

        _zone = (_last_ext.get("zone_geographique") if _last_ext else None) or selected_lead.localisation or "—"
        _type_bien = (_last_ext.get("type_bien") if _last_ext else None) or "—"
        _motivation = (_last_ext.get("motivation") if _last_ext else None) or selected_lead.motivation or "—"
        _pts_attn = (_last_ext.get("points_attention") if _last_ext else None) or []

        _pts_html = ""
        if _pts_attn:
            _pts_list = _pts_attn if isinstance(_pts_attn, list) else [str(_pts_attn)]
            _pts_items = "".join(
                f'<div style="color:#e2e8f0;font-size:0.85rem;margin-top:3px;">• {pt}</div>'
                for pt in _pts_list
            )
            _pts_html = (
                f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid #2d3748;">'
                f'<span style="color:#f59e0b;font-size:0.78rem;">⚠️ POINTS D\'ATTENTION</span>'
                f'{_pts_items}</div>'
            )

        st.markdown(
            f'<div style="background:#1a1f35;border:1px solid #2d3748;border-radius:10px;'
            f'padding:16px 18px;margin:10px 0;">'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;">'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Projet</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{selected_lead.projet.value.capitalize()}</div></div>'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Budget</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{selected_lead.budget or "—"}</div></div>'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Zone</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{_zone}</div></div>'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Type de bien</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{_type_bien}</div></div>'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Motivation</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{_motivation}</div></div>'
            f'<div><span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">Financement</span>'
            f'<div style="color:#e2e8f0;margin-top:2px;">{selected_lead.financement or "—"}</div></div>'
            f'</div>'
            f'{_pts_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 6. Historique & informations secondaires en expander
        with st.expander("Historique & informations secondaires", expanded=False):
            # Notes agent
            st.markdown("**Notes agent**")
            new_notes = st.text_area(
                "Ajouter une note",
                value=selected_lead.notes_agent,
                height=80,
                key=f"notes_{lead_id}",
            )
            if st.button("💾 Sauvegarder notes", key=f"save_notes_{lead_id}"):
                selected_lead.notes_agent = new_notes
                update_lead(selected_lead)
                st.success("Notes sauvegardées")

            st.markdown("---")
            _sec_c1, _sec_c2 = st.columns(2)
            with _sec_c1:
                st.markdown(f"**Statut :** {format_lead_status(selected_lead.statut.value)}")
                st.markdown(f"**Email :** {selected_lead.email or '—'}")
                st.markdown(f"**Timeline :** {selected_lead.timeline or '—'}")
            with _sec_c2:
                st.markdown(f"**Source :** {selected_lead.source.value}")
                st.markdown(f"**Créé le :** {fmt_paris_datetime(selected_lead.created_at, '%d/%m/%Y')}")
                st.markdown(f"**Prochain suivi :** {fmt_paris_datetime(selected_lead.prochain_followup, '%d/%m %H:%M')}")

            st.markdown("---")
            st.markdown("**Historique des interactions**")
            try:
                from memory.lead_repository import get_conversation_history
                from memory.call_repository import get_calls_by_lead

                conversations = get_conversation_history(lead_id, limit=50)
                calls_hist = get_calls_by_lead(lead_id)

                timeline: list[dict] = []
                for conv in conversations:
                    canal = conv.canal.value if hasattr(conv.canal, "value") else str(conv.canal)
                    canal_icons = {"sms": "💬", "whatsapp": "💬", "email": "📧", "appel": "📞"}
                    icon = canal_icons.get(canal, "💬")
                    timeline.append({
                        "date": conv.created_at,
                        "icon": icon,
                        "label": f"{canal.upper()} · {conv.role.capitalize()}",
                        "content": conv.contenu[:200] + ("…" if len(conv.contenu) > 200 else ""),
                    })

                for call in calls_hist:
                    raw_dt = call.get("started_at") or call.get("created_at")
                    if isinstance(raw_dt, str):
                        try:
                            raw_dt = datetime.fromisoformat(raw_dt)
                        except Exception:
                            raw_dt = datetime.now()
                    dur = call.get("duration_seconds") or 0
                    dur_str = f"{dur//60}m{dur%60:02d}s" if dur else "?"
                    direction = (call.get("direction") or "").lower()
                    dir_icon = "⬇️" if "inbound" in direction else "⬆️"
                    resume = call.get("resume_appel") or ""
                    content = f"Durée : {dur_str}"
                    if resume:
                        content += f" · {resume[:150]}{'…' if len(resume) > 150 else ''}"
                    timeline.append({
                        "date": raw_dt,
                        "icon": f"📞{dir_icon}",
                        "label": f"Appel {'entrant' if 'inbound' in direction else 'sortant'}",
                        "content": content,
                    })

                timeline.sort(key=lambda x: x["date"] if x["date"] else datetime.min, reverse=True)

                if not timeline:
                    st.caption("Aucune interaction enregistrée pour ce lead.")
                else:
                    for item in timeline[:20]:
                        dt_str = fmt_paris_datetime(item["date"], "%d/%m/%Y %H:%M")
                        st.markdown(
                            f'<div style="display:flex;gap:12px;padding:8px 0;'
                            f'border-bottom:1px solid #1e2130;align-items:flex-start;">'
                            f'<span style="font-size:1.1rem;min-width:28px;">{item["icon"]}</span>'
                            f'<div><div style="color:#94a3b8;font-size:0.78rem;">'
                            f'{dt_str} · {item["label"]}</div>'
                            f'<div style="color:#e2e8f0;font-size:0.88rem;margin-top:2px;">'
                            f'{item["content"]}</div></div></div>',
                            unsafe_allow_html=True,
                        )
                    if len(timeline) > 20:
                        st.caption(f"+ {len(timeline) - 20} interactions plus anciennes")
            except Exception as exc:
                st.caption(f"Historique indisponible : {exc}")

# ─── MODE LISTE ───────────────────────────────────────────────────────────────

else:
    if not leads:
        st.info("Aucun lead trouvé. Les leads apparaissent ici dès que vos premiers contacts seront reçus via votre numéro PropPilot.")
    else:
        # Tri : priorité haute en premier, puis deadline croissante
        _lead_items = []
        for lead in leads:
            na = _next_actions.get(lead.id, {})
            _lead_items.append({
                "lead": lead,
                "na": na,
                "_priority": na.get("next_action_priority") or "basse",
                "_deadline": na.get("next_action_deadline"),
            })
        _lead_items.sort(key=lambda r: (
            _PRIORITY_ORDER.get(r["_priority"], 2),
            r["_deadline"] or datetime.max,
        ))

        st.markdown(f"**{len(leads)} leads** correspondant aux filtres")

        for item in _lead_items:
            lead = item["lead"]
            na = item["na"]
            _level, _badge_cls = _score_level(lead.score)
            lead_type = getattr(lead, "lead_type", "acheteur") or "acheteur"
            type_icon = _TYPE_ICONS.get(lead_type, "🔑")
            na_label = na.get("next_action_label") or "—"
            na_prio = na.get("next_action_priority") or "basse"
            na_icon = _PRIORITY_ICONS.get(na_prio, "⚪")

            st.markdown(
                f'<div class="lead-card">'
                f'<div class="lead-card-header">'
                f'<span class="lead-card-name">{type_icon} {lead.display_label}</span>'
                f'<span class="{_badge_cls}">{_level}</span>'
                f'</div>'
                f'<div class="lead-card-action">{na_icon} {na_label}</div>'
                f'<div class="lead-card-meta">'
                f'{lead.projet.value.capitalize()} · {lead.budget or "—"} · {lead.localisation or "—"}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("Voir la fiche →", key=f"sel_{lead.id}", use_container_width=True):
                st.session_state["detail_lead_id"] = lead.id
                st.query_params["lead"] = lead.id
                st.rerun()

# ─── Formulaire ajout lead manuel ─────────────────────────────────────────────

with st.expander("➕ Ajouter un lead manuellement"):
    with st.form("add_lead_form"):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            m_prenom = st.text_input("Prénom")
            m_nom = st.text_input("Nom")
            m_tel = st.text_input("Téléphone (format +33...)")
            m_email = st.text_input("Email (optionnel)")
        with col_m2:
            m_projet = st.selectbox("Projet", ["achat", "vente", "location", "estimation"])
            m_budget = st.text_input("Budget / Prix souhaité")
            m_localisation = st.text_input("Localisation")
            m_notes = st.text_area("Notes initiales", height=60)

        submitted = st.form_submit_button("Créer le lead")
        if submitted:
            if not m_tel:
                st.error("Le numéro de téléphone est requis")
            else:
                from memory.lead_repository import create_lead
                from memory.models import Lead, ProjetType
                from memory.usage_tracker import check_and_consume

                usage_ok = check_and_consume(client_id, "lead", tier=tier)
                if not usage_ok["allowed"]:
                    st.error(usage_ok["message"])
                else:
                    new_lead = Lead(
                        client_id=client_id,
                        prenom=m_prenom,
                        nom=m_nom,
                        telephone=m_tel,
                        email=m_email,
                        source=Canal.MANUEL,
                        projet=ProjetType(m_projet),
                        budget=m_budget,
                        localisation=m_localisation,
                        notes_agent=m_notes,
                        statut=LeadStatus.ENTRANT,
                    )
                    create_lead(new_lead)
                    st.success(f"Lead {m_prenom} {m_nom} créé avec succès !")
                    st.rerun()

# ─── Auto-refresh intelligent ─────────────────────────────────────────────────
try:
    from dashboard.lib.auto_refresh import inject_smart_refresh
    inject_smart_refresh(interval_seconds=60)
except Exception:
    pass
