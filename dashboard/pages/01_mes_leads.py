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
    st.info("Aucun lead trouvé. Lancez `python scripts/seed_demo_data.py` pour ajouter des données de démo.")
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
                if st.button("📞 Appeler", key=f"call_{lead_id}"):
                    st.info(f"Appel sortant vers {selected_lead.telephone or 'numéro manquant'} (Phase 2 — VoiceCallAgent)")

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
