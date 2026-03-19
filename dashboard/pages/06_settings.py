"""
Page Settings — Onboarding Wizard + Configuration Agence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import json

from config.settings import get_settings
from memory.database import init_database

init_database()
settings = get_settings()

st.set_page_config(page_title="Configuration — PropPilot", layout="wide", page_icon="⚙️")

from dashboard.auth_ui import require_auth, render_sidebar_logout
require_auth()
render_sidebar_logout()

client_id = st.session_state.get("user_id", settings.agency_client_id)
tier = st.session_state.get("plan", settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)

st.title("⚙️ Configuration de votre PropPilot")
st.markdown(f"**{agency_name}** · Forfait {tier}")

# ─── Wizard steps ─────────────────────────────────────────────────────────────

if "wizard_step" not in st.session_state:
    st.session_state.wizard_step = 1

STEPS = [
    ("🏢", "Identité agence"),
    ("📱", "Numéro Twilio"),
    ("📅", "Google Calendar"),
    ("💳", "Forfait & Billing"),
    ("🚀", "Premier lead test"),
]

# Progress bar étapes
st.markdown("### Progression de la configuration")
cols = st.columns(len(STEPS))
for i, (icon, label) in enumerate(STEPS):
    step_num = i + 1
    with cols[i]:
        if step_num < st.session_state.wizard_step:
            st.markdown(f"<div style='text-align:center;color:#27ae60;'>✅<br><small>{label}</small></div>", unsafe_allow_html=True)
        elif step_num == st.session_state.wizard_step:
            st.markdown(f"<div style='text-align:center;color:#1a3a5c;font-weight:bold;'>{icon}<br><small><b>{label}</b></small></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='text-align:center;color:#aaa;'>{icon}<br><small>{label}</small></div>", unsafe_allow_html=True)

st.markdown("---")

# ─── ÉTAPE 1 : Identité agence ────────────────────────────────────────────────

if st.session_state.wizard_step == 1:
    st.markdown("## Étape 1 — Identité de votre agence")

    with st.form("step1_form"):
        agency_name = st.text_input("Nom de l'agence *", value=agency_name)
        col_a, col_b = st.columns(2)
        with col_a:
            commission_rate = st.number_input(
                "Taux de commission (%)",
                min_value=1.0, max_value=10.0,
                value=settings.agency_commission_rate * 100,
                step=0.5,
                help="Taux de commission moyen pour estimer le CA généré",
            )
        with col_b:
            avg_price = st.number_input(
                "Prix moyen de vente (€)",
                min_value=50000, max_value=5000000,
                value=int(settings.agency_average_price),
                step=10000,
                help="Prix moyen de vos transactions pour le calcul ROI",
            )

        conseiller_prenom = st.text_input("Prénom du conseiller IA", value="Sophie", help="Prénom utilisé dans les messages automatiques")
        conseiller_titre = st.text_input("Titre du conseiller IA", value="conseillère immobilier")

        submitted = st.form_submit_button("Suivant →", type="primary")
        if submitted:
            if not agency_name:
                st.error("Le nom de l'agence est requis")
            else:
                # Mise à jour du .env (ou session state pour la démo)
                st.session_state.config_agency_name = agency_name
                st.session_state.config_commission_rate = commission_rate / 100
                st.session_state.config_avg_price = avg_price
                st.session_state.config_conseiller_prenom = conseiller_prenom
                st.session_state.wizard_step = 2
                st.rerun()

# ─── ÉTAPE 2 : Numéro Twilio ──────────────────────────────────────────────────

elif st.session_state.wizard_step == 2:
    st.markdown("## Étape 2 — Numéro SMS / Téléphone")

    st.info("""
    **Pourquoi Twilio ?**
    Twilio vous fournit un numéro de téléphone français dédié pour recevoir les SMS/appels de vos prospects.
    Vos leads peuvent contacter ce numéro — l'IA répond instantanément.

    [Créer un compte Twilio →](https://www.twilio.com/try-twilio)
    """)

    with st.form("step2_form"):
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            twilio_sid = st.text_input(
                "Twilio Account SID",
                value=settings.twilio_account_sid or "",
                type="password",
                placeholder="ACxxxxxxxxxxxxxxxxx",
            )
        with col_b2:
            twilio_token = st.text_input(
                "Twilio Auth Token",
                value="",
                type="password",
                placeholder="xxxxxxxxxxxxxxxx",
            )

        phone_number = st.text_input(
            "Numéro Twilio (format E.164)",
            value=settings.twilio_phone_number or "",
            placeholder="+33100000001",
        )

        test_number = st.text_input(
            "Votre numéro pour tester (optionnel)",
            placeholder="+33600000000",
        )

        col_prev, col_test, col_next = st.columns([1, 1, 1])

        with col_prev:
            if st.form_submit_button("← Précédent"):
                st.session_state.wizard_step = 1
                st.rerun()

        with col_test:
            test_clicked = st.form_submit_button("📱 Tester SMS")

        with col_next:
            next_clicked = st.form_submit_button("Suivant →", type="primary")

    if test_clicked:
        from tools.twilio_tool import TwilioTool
        twilio = TwilioTool()
        if test_number:
            result = twilio.send_sms(
                to=test_number,
                body=f"🏠 Bonjour ! Votre agence IA {agency_name} est bien configurée. Ce message confirme que les SMS fonctionnent.",
            )
            if result["success"]:
                mock_txt = " (mode démo)" if result.get("mock") else ""
                st.success(f"✅ SMS envoyé{mock_txt} vers {test_number}")
            else:
                st.error(f"❌ Erreur : {result.get('error')}")
        else:
            st.warning("Entrez un numéro de test")

    if next_clicked:
        st.session_state.wizard_step = 3
        st.rerun()

# ─── ÉTAPE 3 : Google Calendar ────────────────────────────────────────────────

elif st.session_state.wizard_step == 3:
    st.markdown("## Étape 3 — Google Calendar")

    st.info("""
    **Booking RDV automatique**
    L'agent vocal propose des créneaux en temps réel pendant les appels.
    Configurez votre Google Calendar pour activer cette fonctionnalité.

    [Créer un compte de service Google →](https://console.cloud.google.com/iam-admin/serviceaccounts)
    """)

    with st.form("step3_form"):
        calendar_id = st.text_input(
            "ID Google Calendar",
            value=settings.google_calendar_id,
            placeholder="primary ou xxxxx@group.calendar.google.com",
        )

        service_account = st.text_area(
            "Clé JSON compte de service (optionnel)",
            height=100,
            placeholder='{"type": "service_account", ...}',
        )

        st.markdown("**Créneaux disponibles par défaut :**")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            heures_debut = st.selectbox("Heure début", ["09:00", "10:00"], index=0)
        with col_s2:
            heures_fin = st.selectbox("Heure fin", ["18:00", "19:00", "20:00"], index=0)

        col_prev, col_test_cal, col_next = st.columns([1, 1, 1])
        with col_prev:
            if st.form_submit_button("← Précédent"):
                st.session_state.wizard_step = 2
                st.rerun()
        with col_test_cal:
            cal_test = st.form_submit_button("📅 Tester créneau")
        with col_next:
            cal_next = st.form_submit_button("Suivant →", type="primary")

    if cal_test:
        st.success("[MOCK] Créneau test créé : Mardi 10h00 — 10h30 (Google Calendar non connecté en mode démo)")

    if cal_next:
        st.session_state.wizard_step = 4
        st.rerun()

# ─── ÉTAPE 4 : Forfait & Billing ──────────────────────────────────────────────

elif st.session_state.wizard_step == 4:
    st.markdown("## Étape 4 — Forfait & Facturation")

    current_tier = tier
    tier_prices = {"Indépendant": 290, "Starter": 790, "Pro": 1490, "Elite": 2990}

    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

    for col, (tier_name, price) in zip([col_s1, col_s2, col_s3, col_s4], tier_prices.items()):
        with col:
            is_current = tier_name == current_tier
            border_col = "#1a3a5c" if is_current else "#e9ecef"
            badge = " ← Actuel" if is_current else ""

            limits = {
                "Indépendant": "600 min voix · 3 000 SMS · 1 utilisateur",
                "Starter": "1 500 min voix · 8 000 SMS · 3 utilisateurs",
                "Pro": "3 000 min voix · 15 000 SMS · 6 utilisateurs",
                "Elite": "Illimité · White-label · Agents custom",
            }
            garantie = {
                "Indépendant": "Garantie ROI 60j — remboursement 50%",
                "Starter": "Garantie ROI 60j — remboursement 50%",
                "Pro": "Garantie ROI 60j — remboursement 50%",
                "Elite": "Garantie ROI 60j — remboursement 100%",
            }

            st.markdown(f"""
            <div style="border: 2px solid {border_col}; border-radius: 10px; padding: 20px; text-align: center; margin: 4px;">
                <div style="font-size: 20px; font-weight: 800;">{tier_name}{badge}</div>
                <div style="font-size: 28px; font-weight: 900; color: #1a3a5c; margin: 8px 0;">{price}€<span style="font-size:14px;">/mois</span></div>
                <div style="color: #666; font-size: 13px; margin-bottom: 12px;">{limits[tier_name]}</div>
                <div style="color: #27ae60; font-size: 12px;">✅ {garantie[tier_name]}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
    **🛡️ 60 Jours Satisfait ou Remboursé**
    Si vous n'êtes pas satisfait dans les 60 jours, nous
    vous remboursons intégralement. Sans questions.
    """)

    col_prev, col_next = st.columns([1, 1])
    with col_prev:
        if st.button("← Précédent"):
            st.session_state.wizard_step = 3
            st.rerun()
    with col_next:
        if st.button("Suivant →", type="primary"):
            st.session_state.wizard_step = 5
            st.rerun()

# ─── ÉTAPE 5 : Premier lead test ──────────────────────────────────────────────

elif st.session_state.wizard_step == 5:
    st.markdown("## Étape 5 — Testez votre premier lead !")

    st.success("""
    🎉 **Configuration terminée !**
    Votre agence IA est presque prête. Testez le flux complet avec un lead fictif.
    """)

    with st.form("step5_test"):
        st.markdown("**Simuler un message entrant :**")
        test_phone = st.text_input("Téléphone (fictif)", value="+33600000099")
        test_message = st.text_input(
            "Message du prospect",
            value="Bonjour, je cherche à acheter un appartement à Lyon, budget 350 000€",
        )
        test_prenom = st.text_input("Prénom (optionnel)", value="Jean")

        col_prev, col_run = st.columns([1, 1])
        with col_prev:
            if st.form_submit_button("← Précédent"):
                st.session_state.wizard_step = 4
                st.rerun()
        with col_run:
            run_test = st.form_submit_button("🚀 Lancer le test", type="primary")

    if run_test:
        with st.spinner("Traitement du lead en cours..."):
            from orchestrator import process_incoming_message
            try:
                result = process_incoming_message(
                    telephone=test_phone,
                    message=test_message,
                    client_id=client_id,
                    tier=tier,
                    canal="sms",
                    prenom=test_prenom,
                )
                st.markdown("### Résultat du test")
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    st.metric("Lead ID", result.get("lead_id", "—")[:8] if result.get("lead_id") else "—")
                    st.metric("Statut", result.get("status", "—"))
                with col_r2:
                    st.metric("Score", f"{result.get('score', 0)}/10")
                    st.metric("Action suivante", result.get("next_action", "—"))

                st.markdown("**Message envoyé au prospect :**")
                st.info(result.get("message_sortant", "—"))
                st.markdown("**Log :**")
                for log in result.get("messages_log", []):
                    st.text(f"• {log}")

                st.success("✅ **Votre agence IA est prête !** Les leads entrants seront traités automatiquement.")

                if st.button("🏠 Aller au dashboard"):
                    st.switch_page("app.py")

            except Exception as e:
                st.error(f"Erreur lors du test : {e}")
                st.info("Assurez-vous d'avoir lancé `python scripts/seed_demo_data.py` d'abord.")

# ─── Section CRM ──────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("## 🔗 Connecter votre CRM")
st.markdown("Synchronisez automatiquement vos leads entre PropPilot et votre logiciel métier.")

CRM_OPTIONS = ["Hektor (La Boîte Immo)", "Apimo", "Prospeneo", "Whise", "Adaptimmo", "Autre (import CSV)"]
CRM_KEYS = ["hektor", "apimo", "prospeneo", "whise", "adaptimmo", "csv"]

selected_crm_label = st.selectbox(
    "Quel CRM utilisez-vous ?",
    options=CRM_OPTIONS,
    index=0,
    key="crm_select",
)
selected_crm = CRM_KEYS[CRM_OPTIONS.index(selected_crm_label)]

if selected_crm == "csv":
    # ── Import CSV universel ──
    st.markdown("### Import CSV")
    st.info("Importez un fichier CSV exporté depuis votre CRM. Les colonnes sont détectées automatiquement.")

    uploaded_file = st.file_uploader(
        "Choisir un fichier CSV",
        type=["csv"],
        key="crm_csv_upload",
    )

    if uploaded_file is not None:
        col_csv1, col_csv2 = st.columns([2, 1])
        with col_csv1:
            st.success(f"Fichier chargé : **{uploaded_file.name}** ({uploaded_file.size} octets)")
        with col_csv2:
            if st.button("📥 Importer les leads", type="primary", key="crm_csv_import"):
                with st.spinner("Analyse et import en cours..."):
                    try:
                        from integrations.crm.csv_import import parse_csv_leads
                        content = uploaded_file.read().decode("utf-8", errors="replace")
                        leads, count, errors = parse_csv_leads(
                            file_content=content,
                            client_id=client_id,
                            source_name=uploaded_file.name,
                        )
                        from memory.lead_repository import create_lead
                        from integrations.sync.conflict_resolver import resolve
                        imported = 0
                        duplicates = 0
                        for lead in leads:
                            final_lead, is_dup = resolve(lead)
                            if not is_dup:
                                create_lead(final_lead)
                                imported += 1
                            else:
                                duplicates += 1
                        st.success(f"✅ **{imported} leads importés**, {duplicates} doublons ignorés")
                        if errors:
                            with st.expander(f"⚠️ {len(errors)} erreurs"):
                                for err in errors[:20]:
                                    st.text(err)
                    except Exception as e:
                        st.error(f"Erreur d'import : {e}")

    with st.expander("📄 Voir un exemple de fichier CSV"):
        try:
            from integrations.crm.csv_import import generate_sample_csv
            sample = generate_sample_csv("generic")
            st.code(sample, language="text")
            st.download_button(
                "Télécharger le modèle CSV",
                data=sample,
                file_name="modele_leads_proppilot.csv",
                mime="text/csv",
            )
        except Exception:
            st.text("prenom,nom,telephone,email,projet,localisation,budget")

else:
    # ── Connexion CRM via API ──
    st.markdown(f"### Configuration {selected_crm_label}")

    with st.form(f"crm_form_{selected_crm}"):
        col_crm1, col_crm2 = st.columns(2)
        with col_crm1:
            api_key_input = st.text_input(
                "Clé API",
                type="password",
                placeholder=f"Clé API {selected_crm_label}",
                help="Disponible dans les paramètres de votre CRM > Intégrations API",
            )
        with col_crm2:
            agency_id_input = st.text_input(
                "ID Agence dans le CRM",
                placeholder="ex: 12345",
                help="Identifiant de votre agence dans le CRM (souvent visible dans l'URL)",
            )

        col_crm_prev, col_crm_test, col_crm_save = st.columns([1, 1, 1])
        with col_crm_test:
            test_conn = st.form_submit_button("🔌 Tester la connexion")
        with col_crm_save:
            save_conn = st.form_submit_button("💾 Enregistrer", type="primary")

    if test_conn:
        with st.spinner(f"Test de connexion {selected_crm_label}..."):
            try:
                import asyncio
                from integrations.sync.scheduler import get_connector
                connector = get_connector(
                    crm_type=selected_crm,
                    api_key=api_key_input or "test_mock",
                    agency_id=agency_id_input or "demo",
                )
                result = asyncio.run(connector.test_connection())
                if result.get("success"):
                    mock_note = " (mode démo)" if result.get("mock") else ""
                    st.success(f"✅ Connexion réussie{mock_note}")
                    if result.get("agency_name"):
                        st.info(f"Agence trouvée : **{result['agency_name']}**")
                else:
                    st.error(f"❌ Échec : {result.get('error', 'Erreur inconnue')}")
            except Exception as e:
                st.error(f"Erreur : {e}")

    if save_conn:
        if not api_key_input:
            st.warning("Entrez une clé API pour enregistrer la connexion.")
        else:
            try:
                from integrations.crm.repository import save_crm_connection
                save_crm_connection(
                    client_id=client_id,
                    crm_type=selected_crm,
                    api_key=api_key_input,
                    agency_id_crm=agency_id_input or "",
                )
                st.success(f"✅ Connexion {selected_crm_label} enregistrée !")
            except Exception as e:
                st.error(f"Erreur lors de l'enregistrement : {e}")

    # ── Statut sync actuelle ──
    try:
        from integrations.crm.repository import get_crm_connection
        conn_data = get_crm_connection(client_id, selected_crm)
        if conn_data:
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            with col_stat1:
                status_icon = "✅" if conn_data.get("enabled") else "⚠️"
                st.metric("Statut", f"{status_icon} {'Actif' if conn_data.get('enabled') else 'Désactivé'}")
            with col_stat2:
                last_sync = conn_data.get("last_sync")
                st.metric("Dernière sync", last_sync[:16] if last_sync else "Jamais")
            with col_stat3:
                if st.button("🔄 Synchroniser maintenant", key="crm_sync_now"):
                    with st.spinner("Synchronisation en cours..."):
                        try:
                            import asyncio
                            from integrations.sync.scheduler import sync_client
                            report = asyncio.run(sync_client(conn_data))
                            st.success(
                                f"✅ {report['new_leads']} nouveaux leads · "
                                f"{report['skipped']} doublons ignorés"
                            )
                            if report["errors"]:
                                st.warning(f"{len(report['errors'])} erreurs : {report['errors'][0]}")
                        except Exception as e:
                            st.error(f"Erreur sync : {e}")
    except Exception:
        pass

# ── Paramètres de synchronisation ──
st.markdown("### Synchronisation automatique")
st.info(
    "PropPilot synchronise vos leads toutes les **15 minutes** si le scheduler est actif "
    "(service `proppilot-sync` dans Docker). "
    "La synchronisation manuelle est toujours disponible ci-dessus."
)

try:
    from integrations.crm.repository import get_crm_connection, save_crm_connection
    conn_data = get_crm_connection(client_id, selected_crm)
    if conn_data:
        col_tog1, col_tog2, col_tog3 = st.columns(3)
        with col_tog1:
            sync_leads = st.toggle(
                "Sync leads entrants",
                value=bool(conn_data.get("sync_leads", 1)),
                key="toggle_sync_leads",
            )
        with col_tog2:
            sync_rdv = st.toggle(
                "Sync RDV vers CRM",
                value=bool(conn_data.get("sync_rdv", 1)),
                key="toggle_sync_rdv",
            )
        with col_tog3:
            sync_listings = st.toggle(
                "Sync annonces vers CRM",
                value=bool(conn_data.get("sync_listings", 1)),
                key="toggle_sync_listings",
            )

        if st.button("💾 Sauvegarder les préférences de sync", key="save_sync_prefs"):
            try:
                save_crm_connection(
                    client_id=client_id,
                    crm_type=selected_crm,
                    api_key=conn_data.get("api_key", ""),
                    agency_id_crm=conn_data.get("agency_id_crm", ""),
                    sync_leads=sync_leads,
                    sync_rdv=sync_rdv,
                    sync_listings=sync_listings,
                )
                st.success("✅ Préférences sauvegardées")
            except Exception as e:
                st.error(f"Erreur : {e}")
except Exception:
    st.caption("Configurez et enregistrez une connexion CRM pour activer les options de sync.")

# ─── Configuration actuelle ───────────────────────────────────────────────────

st.markdown("---")
with st.expander("🔧 Configuration actuelle (lecture seule)"):
    config_display = {
        "Agence": agency_name,
        "Tier": tier,
        "Client ID": client_id,
        "Modèle Claude": settings.claude_model,
        "Twilio disponible": "✅ Oui" if settings.twilio_available else "⚠️ Mode mock",
        "Anthropic disponible": "✅ Oui" if settings.anthropic_available else "⚠️ Mode mock",
        "ElevenLabs disponible": "✅ Oui" if settings.elevenlabs_available else "⚠️ Mode mock",
        "SendGrid disponible": "✅ Oui" if settings.sendgrid_available else "⚠️ Mode mock",
        "Base de données": settings.database_path,
    }
    for key, val in config_display.items():
        st.text(f"{key}: {val}")
