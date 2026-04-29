"""
Page Leads — Pipeline + tableau + actions rapides.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from datetime import datetime

from config.settings import get_settings
from memory.lead_repository import (
    get_leads_by_client,
    get_pipeline_stats,
    update_lead,
    add_conversation_message,
)
from memory.models import Canal, Lead, LeadStatus

settings = get_settings()

st.set_page_config(page_title="Mes leads — PropPilot", layout="wide", page_icon="👥")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("👥 Mes leads")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── KPIs Pipeline ──────────────────────────────────────────────────────────

stats = get_pipeline_stats(client_id)

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Entrants", stats.get("entrant", 0))
with col2:
    st.metric("En qualification", stats.get("en_qualification", 0))
with col3:
    st.metric("Qualifiés", stats.get("qualifie", 0))
with col4:
    st.metric("RDV bookés", stats.get("rdv_booke", 0))
with col5:
    st.metric("Mandats", stats.get("mandat", 0))

st.markdown("---")

# ─── Filtres ────────────────────────────────────────────────────────────────

st.markdown("### Filtres")
col_f1, col_f2, col_f3, col_f4 = st.columns(4)

with col_f1:
    filter_statut = st.selectbox(
        "Statut",
        options=["Tous"] + [s.value for s in LeadStatus],
        key="filter_statut",
    )

with col_f2:
    filter_score_min = st.slider("Score minimum", 0, 10, 0, key="filter_score_min")

with col_f3:
    filter_source = st.selectbox(
        "Source",
        options=["Toutes", "sms", "whatsapp", "email", "web", "seloger", "leboncoin", "manuel"],
        key="filter_source",
    )

with col_f4:
    filter_projet = st.selectbox(
        "Projet",
        options=["Tous", "achat", "vente", "location", "estimation", "inconnu"],
        key="filter_projet",
    )

# ─── Chargement leads ────────────────────────────────────────────────────────

leads = get_leads_by_client(
    client_id=client_id,
    statut=filter_statut if filter_statut != "Tous" else None,
    score_min=filter_score_min if filter_score_min > 0 else None,
    limit=200,
)

# Filtrage source et projet côté Python
if filter_source != "Toutes":
    leads = [l for l in leads if l.source.value == filter_source]
if filter_projet != "Tous":
    leads = [l for l in leads if l.projet.value == filter_projet]

st.markdown(f"**{len(leads)} leads** correspondant aux filtres")

# ─── Tableau leads ───────────────────────────────────────────────────────────

if not leads:
    st.info("Aucun lead trouvé. Les leads apparaissent ici dès que vos premiers contacts seront reçus via votre numéro PropPilot.")
else:
    # Conversion en DataFrame
    rows = []
    for lead in leads:
        score_emoji = "🔴" if lead.score >= 7 else "🟠" if lead.score >= 4 else "🔵"
        rows.append({
            "ID": lead.id[:8],
            "_lead_id": lead.id,
            "Nom": lead.nom_complet,
            "Téléphone": lead.telephone,
            "Score": f"{score_emoji} {lead.score}/10",
            "_score_raw": lead.score,
            "Projet": lead.projet.value.capitalize(),
            "Budget": lead.budget or "—",
            "Localisation": lead.localisation or "—",
            "Statut": lead.statut.value.replace("_", " ").capitalize(),
            "Source": lead.source.value.capitalize(),
            "Prochain suivi": lead.prochain_followup.strftime("%d/%m %H:%M") if lead.prochain_followup else "—",
            "Créé le": lead.created_at.strftime("%d/%m/%Y"),
        })

    df = pd.DataFrame(rows)
    display_cols = ["Nom", "Score", "Projet", "Budget", "Localisation", "Statut", "Source", "Prochain suivi", "Créé le"]

    # Sélection lead pour actions
    selected_indices = st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="leads_table",
    )

    # ─── Panel détail + actions ───────────────────────────────────────────────

    selected_rows = selected_indices.selection.rows if selected_indices.selection else []
    if selected_rows:
        idx = selected_rows[0]
        lead_id = rows[idx]["_lead_id"]
        selected_lead = next((l for l in leads if l.id == lead_id), None)

        if selected_lead:
            st.markdown("---")
            st.markdown(f"### Détail — {selected_lead.nom_complet}")

            detail_col1, detail_col2, detail_col3 = st.columns(3)

            with detail_col1:
                st.markdown(f"**Score :** {selected_lead.score}/10 ({selected_lead.score_label})")
                st.markdown(f"**Statut :** {selected_lead.statut.value}")
                st.markdown(f"**Projet :** {selected_lead.projet.value}")
                st.markdown(f"**Canal :** {selected_lead.source.value}")

            with detail_col2:
                st.markdown(f"**Téléphone :** {selected_lead.telephone or '—'}")
                st.markdown(f"**Email :** {selected_lead.email or '—'}")
                st.markdown(f"**Budget :** {selected_lead.budget or '—'}")
                st.markdown(f"**Localisation :** {selected_lead.localisation or '—'}")

            with detail_col3:
                st.markdown(f"**Timeline :** {selected_lead.timeline or '—'}")
                st.markdown(f"**Financement :** {selected_lead.financement or '—'}")
                st.markdown(f"**Motivation :** {selected_lead.motivation or '—'}")
                st.markdown(f"**Séquence :** {selected_lead.nurturing_sequence.value if selected_lead.nurturing_sequence else '—'}")

            if selected_lead.resume:
                st.markdown(f"**Résumé IA :** *{selected_lead.resume}*")

            # Actions rapides
            st.markdown("#### Actions rapides")
            action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns(5)

            with action_col1:
                if st.button("📱 Envoyer SMS", key=f"sms_{lead_id}"):
                    if selected_lead.telephone:
                        from tools.twilio_tool import TwilioTool
                        twilio = TwilioTool()
                        result = twilio.send_sms(
                            to=selected_lead.telephone,
                            body=f"Bonjour {selected_lead.prenom} ! Votre conseiller {agency_name} souhaite vous rappeler. Êtes-vous disponible maintenant ?",
                        )
                        if result["success"]:
                            st.success(f"SMS {'(mock)' if result.get('mock') else ''} envoyé !")
                        else:
                            st.error("Erreur envoi SMS")
                    else:
                        st.warning("Pas de numéro de téléphone")

            with action_col2:
                # Vérifier si l'agent a renseigné son numéro de téléphone
                _agent_phone = None
                try:
                    from memory.database import get_connection as _gc
                    with _gc() as _conn:
                        _row = _conn.execute(
                            "SELECT phone FROM users WHERE id = %s LIMIT 1",
                            (client_id,),
                        ).fetchone()
                        if _row:
                            _agent_phone = _row.get("phone")
                except Exception:
                    pass

                if not _agent_phone:
                    if st.button(
                        "📞 Appeler",
                        key=f"call_{lead_id}",
                        disabled=True,
                        help="Renseignez votre numéro dans ⚙️ Mes paramètres pour activer le click-to-call",
                    ):
                        pass
                    st.caption("📵 Numéro agent requis — [Mes paramètres](pages/06_parametres.py)")
                elif not selected_lead.telephone:
                    if st.button("📞 Appeler", key=f"call_{lead_id}", disabled=True):
                        pass
                    st.caption("Pas de numéro pour ce lead")
                else:
                    if st.button("📞 Appeler", key=f"call_{lead_id}"):
                        try:
                            import httpx
                            token = st.session_state.get("token", "")
                            resp = httpx.post(
                                f"{settings.api_url}/api/calls/outbound",
                                json={
                                    "lead_id": lead_id,
                                    "agent_id": client_id,
                                    "lead_phone": selected_lead.telephone,
                                },
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=10.0,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(f"Appel initié ! {data.get('message', '')}")
                            else:
                                detail = resp.json().get("detail", resp.text)
                                st.error(f"Erreur : {detail}")
                        except Exception as exc:
                            st.error(f"Impossible de joindre l'API : {exc}")

            with action_col3:
                if st.button("📄 Générer annonce", key=f"listing_{lead_id}"):
                    st.info("Génération annonce (Phase 2 — ListingGeneratorAgent)")

            with action_col4:
                if st.button("✅ Mandat gagné", key=f"mandat_{lead_id}"):
                    selected_lead.statut = LeadStatus.MANDAT
                    selected_lead.mandat_date = datetime.now()
                    update_lead(selected_lead)
                    st.success("🎉 Mandat enregistré !")
                    st.rerun()

            with action_col5:
                if st.button("❌ Perdu", key=f"perdu_{lead_id}"):
                    selected_lead.statut = LeadStatus.PERDU
                    update_lead(selected_lead)
                    st.warning("Lead marqué comme perdu")
                    st.rerun()

            # Notes agent
            st.markdown("#### Notes agent")
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

            # ── Timeline interactions ──────────────────────────────────────────
            st.markdown("#### 📅 Historique des interactions")

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
                        dt_str = item["date"].strftime("%d/%m/%Y %H:%M") if item["date"] else "—"
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

            # ── Données extraites agrégées ─────────────────────────────────────
            try:
                from memory.call_repository import get_extractions_by_lead
                extractions = get_extractions_by_lead(lead_id)

                if extractions:
                    st.markdown("#### 🧠 Données extraites des appels")
                    last = extractions[0]

                    ext_col1, ext_col2, ext_col3 = st.columns(3)
                    with ext_col1:
                        st.markdown(f"**Type projet :** {last.get('type_projet') or '—'}")
                        bmin, bmax = last.get("budget_min"), last.get("budget_max")
                        if bmin or bmax:
                            bstr = f"{bmin:,} €".replace(",", " ") if bmin else ""
                            bstr += " — " if bmin and bmax else ""
                            bstr += f"{bmax:,} €".replace(",", " ") if bmax else ""
                            st.markdown(f"**Budget :** {bstr}")
                        else:
                            st.markdown("**Budget :** —")
                        st.markdown(f"**Zone :** {last.get('zone_geographique') or '—'}")
                        st.markdown(f"**Type bien :** {last.get('type_bien') or '—'}")
                    with ext_col2:
                        st.markdown(f"**Motivation :** {last.get('motivation') or '—'}")
                        st.markdown(f"**Score qualif :** {last.get('score_qualification') or '—'}")
                        next_act = last.get("prochaine_action_suggeree")
                        if next_act:
                            st.markdown(f"**Prochaine action :** *{next_act}*")
                    with ext_col3:
                        pts = last.get("points_attention") or []
                        if pts:
                            st.markdown("**⚠️ Points d'attention**")
                            for pt in (pts if isinstance(pts, list) else [str(pts)]):
                                st.markdown(f"• {pt}")
                    if len(extractions) > 1:
                        st.caption(f"Basé sur le dernier appel analysé · {len(extractions)} appel(s) total")
            except Exception:
                pass

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
