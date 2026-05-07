"""
Page "À vérifier manuellement" — leads dont l'extraction IA a échoué.
Affiche le transcript brut (appel ou SMS) pour permettre une saisie manuelle.
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

settings = get_settings()

st.set_page_config(
    page_title="À vérifier — PropPilot",
    layout="wide",
    page_icon="⚠️",
)

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)

st.title("⚠️ Leads à vérifier manuellement")
st.caption(
    "Ces leads n'ont pas pu être analysés automatiquement (extraction IA échouée après 3 tentatives). "
    "Consultez leur transcript et saisissez les informations clés."
)

# ─── Chargement ──────────────────────────────────────────────────────────────

from memory.lead_repository import get_leads_to_verify, update_lead
from memory.models import Lead, LeadStatus

try:
    leads_raw = get_leads_to_verify(client_id, limit=100)
except Exception as exc:
    st.error(f"Erreur chargement : {exc}")
    leads_raw = []

if not leads_raw:
    st.success("Aucun lead à vérifier — tout est OK !")
    st.stop()

st.markdown(f"**{len(leads_raw)} lead(s)** nécessitent votre attention.")
st.markdown("---")

# ─── Liste des leads à vérifier ──────────────────────────────────────────────

for lead_dict in leads_raw:
    lead_id = lead_dict.get("id", "")
    prenom = lead_dict.get("prenom") or ""
    nom = lead_dict.get("nom") or ""
    nom_complet = f"{prenom} {nom}".strip() or "Lead inconnu"
    telephone = lead_dict.get("telephone") or "—"
    score = lead_dict.get("score") or 0
    statut = lead_dict.get("statut") or "entrant"
    extraction_status = lead_dict.get("extraction_status") or "—"
    created_str = fmt_paris_datetime(lead_dict.get("created_at"), "%d/%m/%Y %H:%M")
    resume = lead_dict.get("resume") or ""

    with st.expander(
        f"**{nom_complet}** · {telephone} · créé {created_str} · statut: {statut}",
        expanded=False,
    ):
        col_info, col_actions = st.columns([2, 1])

        with col_info:
            st.markdown(f"**Score actuel :** {score}/24")
            st.markdown(f"**Statut extraction :** `{extraction_status}`")
            if resume:
                st.markdown(f"**Résumé disponible :** {resume}")

            # Transcript le plus récent (appel ou SMS)
            st.markdown("##### Transcript / historique SMS")
            try:
                from memory.lead_repository import get_conversation_history
                from memory.call_repository import get_extractions_by_lead

                convs = get_conversation_history(lead_id, limit=30)
                if convs:
                    for msg in convs[-10:]:
                        role_label = "Prospect" if msg.role == "user" else "Léa"
                        ts = fmt_paris_datetime(msg.created_at, "%d/%m %H:%M")
                        contenu_short = msg.contenu[:400] + ("…" if len(msg.contenu) > 400 else "")
                        st.markdown(
                            f'<div style="padding:6px 10px;margin:4px 0;border-radius:6px;'
                            f'background:{"#1e3a5f" if msg.role == "user" else "#1e2130"};">'
                            f'<span style="color:#94a3b8;font-size:0.75rem;">{ts} · {role_label}</span><br>'
                            f'<span style="color:#e2e8f0;font-size:0.88rem;">{contenu_short}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("Aucun message SMS enregistré.")

                extractions = get_extractions_by_lead(lead_id)
                for ext in extractions[:2]:
                    raw_resume = ext.get("resume_appel") or ""
                    if raw_resume:
                        src = ext.get("source", "call")
                        st.markdown(f"**Résumé extraction ({src}) :** {raw_resume[:500]}")

            except Exception as exc:
                st.caption(f"Transcript indisponible : {exc}")

        with col_actions:
            st.markdown("##### Saisie manuelle")

            manual_score = st.slider(
                "Score (0-24)",
                min_value=0, max_value=24, value=score or 0,
                key=f"score_{lead_id}",
            )
            manual_type = st.selectbox(
                "Type de lead",
                options=["acheteur", "vendeur", "locataire"],
                key=f"type_{lead_id}",
            )
            manual_statut = st.selectbox(
                "Statut",
                options=[s.value for s in LeadStatus],
                index=[s.value for s in LeadStatus].index(statut)
                if statut in [s.value for s in LeadStatus] else 0,
                key=f"statut_{lead_id}",
            )

            if st.button("💾 Sauvegarder", key=f"save_{lead_id}"):
                try:
                    from memory.database import get_connection
                    from datetime import datetime as dt

                    with get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE leads SET
                                score = %s,
                                lead_type = %s,
                                statut = %s,
                                extraction_status = 'manual',
                                updated_at = %s
                            WHERE id = %s AND client_id = %s
                            """,
                            (manual_score, manual_type, manual_statut, dt.utcnow(), lead_id, client_id),
                        )
                    st.success("Sauvegardé !")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Erreur : {exc}")

            if st.button("🗑️ Ignorer (marquer traité)", key=f"ignore_{lead_id}"):
                try:
                    from memory.database import get_connection
                    from datetime import datetime as dt

                    with get_connection() as conn:
                        conn.execute(
                            "UPDATE leads SET extraction_status = 'manual', updated_at = %s "
                            "WHERE id = %s AND client_id = %s",
                            (dt.utcnow(), lead_id, client_id),
                        )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Erreur : {exc}")
