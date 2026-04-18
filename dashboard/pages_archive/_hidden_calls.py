"""
Page Appels — Historique appels voix IA + transcriptions + anomalies.
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
from memory.database import init_database, get_connection

init_database()
settings = get_settings()

st.set_page_config(page_title="Appels — PropPilot", layout="wide", page_icon="📞")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("📞 Historique des Appels Voix IA")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── KPIs appels ──────────────────────────────────────────────────────────────

from agents.voice_inbound import VoiceInboundAgent
agent = VoiceInboundAgent(client_id=client_id, tier=tier)

# Appels depuis Retell (mock ou réel)
calls = agent.get_calls_history(limit=50)

if calls:
    total_calls = len(calls)
    completed = len([c for c in calls if c.get("status") == "ended" or c.get("statut") == "completed"])
    total_min = sum(c.get("duration_s", c.get("duree_secondes", 0)) for c in calls) / 60
    rdv_from_calls = len([c for c in calls if c.get("rdv_booke") or c.get("call_analysis", {}).get("custom", {}).get("rdv_pris")])
else:
    total_calls = completed = rdv_from_calls = 0
    total_min = 0.0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Appels ce mois", total_calls)
with col2:
    st.metric("Appels réussis", completed)
with col3:
    st.metric("Minutes consommées", f"{total_min:.0f}")
with col4:
    st.metric("RDV issus d'appels", rdv_from_calls)

st.markdown("---")

# ─── Lancer un appel sortant ──────────────────────────────────────────────────

with st.expander("📱 Lancer un appel sortant vers un lead chaud"):
    from memory.lead_repository import get_leads_by_client

    hot_leads = get_leads_by_client(
        client_id=client_id,
        statut="qualifie",
        score_min=7,
        limit=20,
    )

    if not hot_leads:
        st.info("Aucun lead qualifié (score ≥ 7) disponible pour un appel sortant.")
    else:
        lead_options = {f"{l.nom_complet} — {l.localisation} — Score {l.score}/10 — {l.telephone}": l.id for l in hot_leads}
        selected_label = st.selectbox("Choisir le lead à appeler", list(lead_options.keys()))

        col_call1, col_call2 = st.columns([1, 3])
        with col_call1:
            if st.button("📞 Appeler maintenant", type="primary"):
                with st.spinner("Initiation de l'appel..."):
                    result = agent.call_hot_lead(lead_options[selected_label])
                if result.get("success"):
                    st.success(f"✅ Appel initié ! ID : {result.get('call_id', '')[:12]}")
                else:
                    st.error(f"❌ {result.get('message', 'Erreur')}")
        with col_call2:
            st.info("L'appel sera géré par l'IA — transcription et résumé disponibles en fin d'appel.")

st.markdown("---")

# ─── Tableau des appels ───────────────────────────────────────────────────────

st.markdown("### Historique des appels")

if not calls:
    st.info("Aucun appel enregistré. Lancez un appel sortant ou attendez des appels entrants.")
else:
    rows = []
    for call in calls:
        duration_s = call.get("duration_s") or call.get("duree_secondes", 0)
        duration_fmt = f"{duration_s // 60}:{duration_s % 60:02d}" if duration_s else "—"

        status = call.get("status") or call.get("statut", "—")
        status_emoji = {"ended": "✅", "completed": "✅", "registered": "⏳", "ongoing": "🔴", "error": "❌"}.get(status, "—")

        call_analysis = call.get("call_analysis", {})
        sentiment = call_analysis.get("user_sentiment", "—") if isinstance(call_analysis, dict) else "—"

        rows.append({
            "_call_id": call.get("call_id") or call.get("id", ""),
            "Téléphone": call.get("to_phone") or call.get("id", "")[:8],
            "Statut": f"{status_emoji} {status}",
            "Durée": duration_fmt,
            "Sentiment": sentiment,
            "RDV": "✅" if (call.get("rdv_booke") or (isinstance(call_analysis, dict) and call_analysis.get("custom", {}).get("rdv_pris"))) else "—",
            "Date": call.get("created_at", "")[:16] if call.get("created_at") else "—",
        })

    df = pd.DataFrame(rows)
    display_cols = ["Téléphone", "Statut", "Durée", "Sentiment", "RDV", "Date"]

    selected = st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="calls_table",
    )

    # ─── Détail appel sélectionné ─────────────────────────────────────────────

    sel_rows = selected.selection.rows if selected.selection else []
    if sel_rows:
        idx = sel_rows[0]
        call_id = rows[idx]["_call_id"]
        selected_call = next((c for c in calls if (c.get("call_id") or c.get("id", "")) == call_id), None)

        if selected_call:
            st.markdown("---")
            st.markdown(f"### Détail appel — {selected_call.get('to_phone', call_id[:12])}")

            tab_transcript, tab_summary, tab_anomalies = st.tabs(["📝 Transcription", "🎯 Résumé IA", "⚠️ Anomalies"])

            with tab_transcript:
                transcript = selected_call.get("transcript", "")
                segments = selected_call.get("transcript_segments", [])

                if segments:
                    for seg in segments:
                        role = seg.get("role", "")
                        content = seg.get("content", "")
                        if role == "agent":
                            st.markdown(f"**🤖 Agent IA :** {content}")
                        else:
                            st.markdown(f"**👤 Contact :** {content}")
                elif transcript:
                    st.text_area("Transcription complète", value=transcript, height=300, disabled=True)
                else:
                    # Charger depuis Retell si disponible
                    from tools.retell_tool import RetellTool
                    retell = RetellTool()
                    with st.spinner("Chargement transcription..."):
                        call_details = retell.get_call(call_id)
                    transcript = call_details.get("transcript", "")
                    segments = call_details.get("transcript_segments", [])
                    if segments:
                        for seg in segments:
                            role = seg.get("role", "")
                            content = seg.get("content", "")
                            if role == "agent":
                                st.markdown(f"**🤖 Agent IA :** {content}")
                            else:
                                st.markdown(f"**👤 Contact :** {content}")
                    elif transcript:
                        st.text_area("Transcription", value=transcript, height=300, disabled=True)
                    else:
                        st.info("Transcription non disponible (appel en cours ou trop récent)")

            with tab_summary:
                analysis = selected_call.get("call_analysis", {})
                summary = selected_call.get("resume", "")

                if isinstance(analysis, dict) and analysis:
                    st.markdown(f"**Résumé :** {analysis.get('call_summary', summary or '—')}")
                    st.markdown(f"**Sentiment contact :** {analysis.get('user_sentiment', '—')}")
                    st.markdown(f"**Tâche accomplie :** {analysis.get('agent_task_completion_rating', '—')}")

                    custom = analysis.get("custom", {}) or analysis.get("custom_analysis_data", {})
                    if custom:
                        st.markdown("**Données personnalisées :**")
                        for k, v in custom.items():
                            st.text(f"  • {k}: {v}")
                elif summary:
                    st.markdown(summary)
                else:
                    st.info("Résumé non encore disponible")

            with tab_anomalies:
                anomalies = selected_call.get("anomalies", [])
                if isinstance(anomalies, str):
                    import json
                    try:
                        anomalies = json.loads(anomalies)
                    except Exception:
                        anomalies = []

                if anomalies:
                    for anomaly in anomalies:
                        sev = anomaly.get("severite", "basse")
                        color = {"haute": "🔴", "moyenne": "🟠", "basse": "🟡"}.get(sev, "⚪")
                        st.markdown(f"{color} **{anomaly.get('type', '').capitalize()}** — {anomaly.get('description', '')}")
                        st.caption(f"→ {anomaly.get('action_recommandee', '')}")
                else:
                    st.success("✅ Aucune anomalie détectée lors de cet appel")

# ─── Analyse anomalies ad-hoc ─────────────────────────────────────────────────

st.markdown("---")
with st.expander("🔍 Analyser un dossier pour anomalies"):
    from agents.anomaly_detector import AnomalyDetectorAgent

    with st.form("anomaly_form"):
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            a_projet = st.selectbox("Projet", ["achat", "vente", "location"])
            a_budget = st.number_input("Budget/Prix (€)", min_value=0, value=350000, step=10000)
            a_timeline = st.number_input("Délai (jours)", min_value=0, value=90, step=15)
            a_financement = st.text_input("Situation financement", placeholder="Accord LCL, apport 20%")
        with col_a2:
            a_prix_marche = st.number_input("Estimation marché (€, optionnel)", min_value=0, value=0, step=10000)
            a_titre = st.checkbox("Titre de propriété vérifié", value=True)
            a_syndic = st.checkbox("Syndic contacté", value=True)
            a_travaux = st.checkbox("Travaux déclarés OK", value=True)
            a_copropriete = st.checkbox("En copropriété", value=True)

        submitted = st.form_submit_button("🔍 Analyser", type="primary")
        if submitted:
            detector = AnomalyDetectorAgent(client_id=client_id, tier=tier)
            dossier = {
                "projet": a_projet,
                "budget": a_budget,
                "prix_demande": a_budget,
                "timeline_jours": a_timeline,
                "financement": a_financement,
                "titre_propriete": a_titre,
                "syndic_contacte": a_syndic,
                "travaux_declares": a_travaux,
                "en_copropriete": a_copropriete,
            }
            result = detector.analyze_dossier_dict(
                dossier=dossier,
                prix_marche_estime=a_prix_marche if a_prix_marche > 0 else None,
            )

            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                score = result["score_risque"]
                color = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟢"
                st.metric(f"{color} Score risque", f"{score}/10")
            with col_r2:
                st.metric("Anomalies", result["nb_anomalies"])
            with col_r3:
                st.metric("Critiques", result["nb_critiques"])

            if result["peut_signer_mandat"]:
                st.success(f"✅ {result['recommandation_globale']}")
            else:
                st.error(f"⚠️ {result['recommandation_globale']}")

            if result["anomalies"]:
                st.markdown("**Anomalies détectées :**")
                for anomaly in result["anomalies"]:
                    sev = anomaly.get("severite", "basse")
                    icon = {"haute": "🔴", "moyenne": "🟠", "basse": "🟡"}.get(sev, "⚪")
                    st.markdown(f"{icon} **{anomaly['type'].capitalize()}** — {anomaly['description']}")
                    st.caption(f"→ Action : {anomaly['action_recommandee']}")
