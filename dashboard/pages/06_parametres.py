"""
Page Paramètres — Configuration de l'agence et préférences.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from config.settings import get_settings

settings = get_settings()

st.set_page_config(page_title="Mes paramètres — PropPilot", layout="wide", page_icon="⚙️")

from dashboard.auth_ui import require_auth, render_sidebar_logout, require_non_demo
require_auth()
require_non_demo()
render_sidebar_logout()

client_id  = st.session_state.get("user_id",    settings.agency_client_id)
tier       = st.session_state.get("plan",        settings.agency_tier)
agency_name = st.session_state.get("agency_name", settings.agency_name)
user_email  = st.session_state.get("email", "")

# ─── Lecture DB ───────────────────────────────────────────────────────────────

current_first_name = ""
current_phone      = ""
try:
    from memory.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT first_name, phone FROM users WHERE id = %s LIMIT 1",
            (client_id,),
        ).fetchone()
    if row:
        current_first_name = row.get("first_name") or ""
        current_phone      = row.get("phone") or ""
except Exception:
    pass

# ─── En-tête ──────────────────────────────────────────────────────────────────

st.title("Mes paramètres")
st.caption("Configurez les informations de votre agence et vos préférences.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Identité de l'agence
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("### Identité de l'agence")

with st.form("identity_form"):
    col_a, col_b = st.columns(2)
    with col_a:
        new_agency_name = st.text_input(
            "Nom de l'agence *",
            value=agency_name,
            placeholder="ex: Agence Martin & Associés",
        )
        contact_email = st.text_input(
            "Email de contact",
            value=user_email,
            placeholder="contact@monagence.fr",
            disabled=True,
            help="L'email est associé à votre compte. Contactez-nous pour le modifier.",
        )
    with col_b:
        first_name = st.text_input(
            "Responsable principal",
            value=current_first_name,
            placeholder="ex: Thomas",
            help="Utilisé dans les messages vocaux quand un prospect appelle votre numéro.",
        )
        phone_input = st.text_input(
            "Votre numéro de téléphone",
            value=current_phone,
            placeholder="+33612345678",
            help="Format international obligatoire. Utilisé pour le click-to-call depuis le dashboard.",
        )

    identity_save = st.form_submit_button("Enregistrer", type="primary")

if identity_save:
    if not new_agency_name.strip():
        st.error("Le nom de l'agence est requis.")
    else:
        phone_clean = (phone_input or "").strip()
        if phone_clean and not re.fullmatch(r"\+[1-9]\d{6,14}", phone_clean):
            st.error("Numéro invalide. Utilisez le format E.164 : +33612345678")
        else:
            try:
                from memory.database import get_connection
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE users SET first_name = %s, phone = %s WHERE id = %s",
                        (first_name.strip() or None, phone_clean or None, client_id),
                    )
                st.session_state["agency_name"] = new_agency_name.strip()
                st.success("Informations enregistrées.")
            except Exception as e:
                st.error(f"Erreur lors de la sauvegarde : {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Paramètres commerciaux
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.markdown("### Paramètres commerciaux")
st.caption("Ces valeurs sont utilisées pour le calcul de votre ROI et les estimations de CA.")

with st.form("commercial_form"):
    col_c, col_d = st.columns(2)
    with col_c:
        commission_rate = st.number_input(
            "Taux de commission moyen (%)",
            min_value=1.0,
            max_value=10.0,
            value=float(st.session_state.get("config_commission_rate", settings.agency_commission_rate)) * 100,
            step=0.5,
        )
    with col_d:
        avg_price = st.number_input(
            "Prix moyen de vente (€)",
            min_value=50_000,
            max_value=5_000_000,
            value=int(st.session_state.get("config_avg_price", settings.agency_average_price)),
            step=10_000,
        )
    commercial_save = st.form_submit_button("Enregistrer", type="primary")

if commercial_save:
    st.session_state["config_commission_rate"] = commission_rate / 100
    st.session_state["config_avg_price"] = avg_price
    st.success("Paramètres commerciaux mis à jour.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CRM et synchronisation
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.markdown("### CRM et synchronisation")
st.caption("Synchronisez automatiquement vos leads entre PropPilot et votre logiciel métier.")

CRM_OPTIONS = ["Hektor (La Boîte Immo)", "Apimo", "Prospeneo", "Whise", "Adaptimmo", "Autre (import CSV)"]
CRM_KEYS    = ["hektor", "apimo", "prospeneo", "whise", "adaptimmo", "csv"]

selected_crm_label = st.selectbox(
    "Quel CRM utilisez-vous ?",
    options=CRM_OPTIONS,
    index=0,
    key="crm_select",
)
selected_crm = CRM_KEYS[CRM_OPTIONS.index(selected_crm_label)]

if selected_crm == "csv":
    st.markdown("#### Import CSV")
    st.info("Importez un fichier CSV exporté depuis votre CRM. Les colonnes sont détectées automatiquement.")

    uploaded_file = st.file_uploader("Choisir un fichier CSV", type=["csv"], key="crm_csv_upload")

    if uploaded_file is not None:
        col_csv1, col_csv2 = st.columns([2, 1])
        with col_csv1:
            st.success(f"Fichier chargé : **{uploaded_file.name}** ({uploaded_file.size} octets)")
        with col_csv2:
            if st.button("Importer les leads", type="primary", key="crm_csv_import"):
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
                        st.success(f"**{imported} leads importés**, {duplicates} doublons ignorés.")
                        if errors:
                            with st.expander(f"{len(errors)} erreurs"):
                                for err in errors[:20]:
                                    st.text(err)
                    except Exception as e:
                        st.error(f"Erreur d'import : {e}")

    with st.expander("Voir un exemple de fichier CSV"):
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
    # ── Connexion CRM via API ──────────────────────────────────────────────────
    st.markdown(f"#### Connexion {selected_crm_label}")

    with st.form(f"crm_form_{selected_crm}"):
        col_crm1, col_crm2 = st.columns(2)
        with col_crm1:
            api_key_input = st.text_input(
                "Clé API",
                type="password",
                placeholder=f"Clé API {selected_crm_label}",
                help="Disponible dans les paramètres de votre CRM > Intégrations API.",
            )
        with col_crm2:
            agency_id_input = st.text_input(
                "Identifiant agence dans le CRM",
                placeholder="ex: 12345",
                help="Visible dans l'URL ou les paramètres de votre CRM.",
            )
        col_crm_test, col_crm_save = st.columns(2)
        with col_crm_test:
            test_conn = st.form_submit_button("Tester la connexion")
        with col_crm_save:
            save_conn = st.form_submit_button("Enregistrer", type="primary")

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
                    st.success(f"Connexion réussie{mock_note}")
                    if result.get("agency_name"):
                        st.info(f"Agence trouvée : **{result['agency_name']}**")
                else:
                    st.error(f"Échec : {result.get('error', 'Erreur inconnue')}")
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
                st.success(f"Connexion {selected_crm_label} enregistrée.")
            except Exception as e:
                st.error(f"Erreur lors de l'enregistrement : {e}")

    # ── Statut connexion CRM ───────────────────────────────────────────────────
    try:
        from integrations.crm.repository import get_crm_connection
        conn_data = get_crm_connection(client_id, selected_crm)
        if conn_data:
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            with col_stat1:
                status_label = "Actif" if conn_data.get("enabled") else "Désactivé"
                st.metric("Statut", status_label)
            with col_stat2:
                last_sync = conn_data.get("last_sync")
                st.metric("Dernière synchronisation", last_sync[:16] if last_sync else "Jamais")
            with col_stat3:
                if st.button("Synchroniser maintenant", key="crm_sync_now"):
                    with st.spinner("Synchronisation en cours..."):
                        try:
                            import asyncio
                            from integrations.sync.scheduler import sync_client
                            report = asyncio.run(sync_client(conn_data))
                            st.success(
                                f"{report['new_leads']} nouveaux leads · "
                                f"{report['skipped']} doublons ignorés."
                            )
                            if report["errors"]:
                                st.warning(f"{len(report['errors'])} erreur(s) : {report['errors'][0]}")
                        except Exception as e:
                            st.error(f"Erreur : {e}")
    except Exception:
        pass

# ── Préférences de synchronisation ────────────────────────────────────────────
st.markdown("#### Préférences de synchronisation")

try:
    from integrations.crm.repository import get_crm_connection, save_crm_connection
    conn_data = get_crm_connection(client_id, selected_crm)
    if conn_data:
        col_tog1, col_tog2, col_tog3 = st.columns(3)
        with col_tog1:
            sync_leads = st.toggle(
                "Leads entrants",
                value=bool(conn_data.get("sync_leads", 1)),
                key="toggle_sync_leads",
            )
        with col_tog2:
            sync_rdv = st.toggle(
                "RDV vers CRM",
                value=bool(conn_data.get("sync_rdv", 1)),
                key="toggle_sync_rdv",
            )
        with col_tog3:
            sync_listings = st.toggle(
                "Annonces vers CRM",
                value=bool(conn_data.get("sync_listings", 1)),
                key="toggle_sync_listings",
            )
        if st.button("Enregistrer les préférences", key="save_sync_prefs"):
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
                st.success("Préférences enregistrées.")
            except Exception as e:
                st.error(f"Erreur : {e}")
    else:
        st.caption(
            "Votre synchronisation CRM n'est pas encore configurée. "
            "L'équipe PropPilot vous accompagne pendant le pilote."
        )
except Exception:
    st.caption(
        "Votre synchronisation CRM n'est pas encore configurée. "
        "L'équipe PropPilot vous accompagne pendant le pilote."
    )

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Export automatique vers votre CRM (Push)
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.markdown("### Export automatique vers votre CRM")
st.caption(
    "À chaque lead qualifié, PropPilot le transmet automatiquement vers votre CRM. "
    "Sens unique : PropPilot → CRM."
)

# Lire config push CRM actuelle
_crm_push_current: dict = {"crm_type": "none", "crm_config": {}}
try:
    from memory.database import get_connection as _gc2
    import json as _json
    with _gc2() as _conn2:
        _row_crm = _conn2.execute(
            "SELECT crm_type, crm_config, crm_last_sync_at, crm_last_error FROM users WHERE id = %s",
            (client_id,),
        ).fetchone()
    if _row_crm:
        _crm_push_current["crm_type"] = _row_crm.get("crm_type") or "none"
        _raw_cfg = _row_crm.get("crm_config")
        if isinstance(_raw_cfg, dict):
            _crm_push_current["crm_config"] = _raw_cfg
        elif isinstance(_raw_cfg, str) and _raw_cfg:
            _crm_push_current["crm_config"] = _json.loads(_raw_cfg)
        _crm_push_current["crm_last_sync_at"] = _row_crm.get("crm_last_sync_at")
        _crm_push_current["crm_last_error"]   = _row_crm.get("crm_last_error")
except Exception:
    pass

_CRM_PUSH_OPTIONS = ["Aucun", "Apimo", "Email parsing (Netty, Hektor, Modelo, etc.)"]
_CRM_PUSH_KEYS   = ["none", "apimo", "email"]
_current_type    = _crm_push_current.get("crm_type", "none")
_current_idx     = _CRM_PUSH_KEYS.index(_current_type) if _current_type in _CRM_PUSH_KEYS else 0

_selected_push_label = st.selectbox(
    "Connecteur actif",
    options=_CRM_PUSH_OPTIONS,
    index=_current_idx,
    key="crm_push_select",
)
_selected_push_type = _CRM_PUSH_KEYS[_CRM_PUSH_OPTIONS.index(_selected_push_label)]
_cfg = _crm_push_current.get("crm_config", {})

if _selected_push_type == "apimo":
    st.markdown("##### Configuration Apimo")
    st.caption("Vos identifiants Apimo sont disponibles dans Paramètres > API de votre espace Apimo.")

    with st.form("crm_push_apimo_form"):
        _apimo_provider = st.text_input(
            "Provider ID",
            value=_cfg.get("provider_id", ""),
            placeholder="ex: 12345",
        )
        _apimo_token = st.text_input(
            "API Token",
            value=_cfg.get("api_token", ""),
            type="password",
            placeholder="Votre token Apimo",
        )
        _col_test, _col_save = st.columns(2)
        with _col_test:
            _test_apimo = st.form_submit_button("Tester la connexion")
        with _col_save:
            _save_apimo = st.form_submit_button("Enregistrer", type="primary")

    if _test_apimo:
        with st.spinner("Test Apimo..."):
            try:
                from lib.crm_connectors.apimo import ApimoConnector
                _conn_test = ApimoConnector(
                    provider_id=_apimo_provider or "test",
                    api_token=_apimo_token or "test_mock",
                )
                _result = _conn_test.test_connection()
                if _result.get("success"):
                    st.success(_result["message"])
                else:
                    st.error(_result["message"])
            except Exception as _e:
                st.error(f"Erreur : {_e}")

    if _save_apimo:
        if not _apimo_provider or not _apimo_token:
            st.warning("Provider ID et API Token requis.")
        else:
            try:
                from lib.crm_connectors.factory import save_crm_push_config
                save_crm_push_config(
                    client_id=client_id,
                    crm_type="apimo",
                    config={"provider_id": _apimo_provider, "api_token": _apimo_token},
                )
                st.success("Connecteur Apimo enregistré — les leads seront transmis automatiquement.")
            except Exception as _e:
                st.error(f"Erreur : {_e}")

elif _selected_push_type == "email":
    st.markdown("##### Configuration Email parsing")
    st.caption(
        "PropPilot envoie un email structuré à votre CRM à chaque nouveau lead qualifié. "
        "Compatible avec tout CRM disposant d'une adresse d'import."
    )

    with st.form("crm_push_email_form"):
        _email_target = st.text_input(
            "Adresse email d'import du CRM",
            value=_cfg.get("target_email", ""),
            placeholder="import@moncrm.fr",
            help="Consultez la documentation de votre CRM pour trouver cette adresse.",
        )
        _crm_labels = ["Netty", "Hektor (La Boîte Immo)", "Modelo Office", "Périclès", "Krea", "Autre"]
        _current_label = _cfg.get("crm_label", "Autre")
        _email_crm_label = st.selectbox(
            "CRM destinataire",
            options=_crm_labels,
            index=_crm_labels.index(_current_label) if _current_label in _crm_labels else len(_crm_labels) - 1,
        )
        _col_test2, _col_save2 = st.columns(2)
        with _col_test2:
            _test_email = st.form_submit_button("Envoyer un email test")
        with _col_save2:
            _save_email = st.form_submit_button("Enregistrer", type="primary")

    if _test_email:
        if not _email_target:
            st.warning("Entrez une adresse email cible.")
        else:
            with st.spinner("Envoi email test..."):
                try:
                    from lib.crm_connectors.email_parsing import EmailParsingConnector
                    _test_connector = EmailParsingConnector(
                        target_email=_email_target,
                        crm_label=_email_crm_label,
                    )
                    _test_lead = {
                        "id": "test-lead-001",
                        "client_id": client_id,
                        "prenom": "Marie",
                        "nom": "Dupont (test)",
                        "telephone": "+33600000001",
                        "email": "marie.dupont@test.fr",
                        "lead_type": "acheteur",
                        "type_projet": "achat",
                        "budget_min": 300000,
                        "budget_max": 400000,
                        "zone": "Lyon 6ème",
                        "type_bien": "T3",
                        "surface_min": 65,
                        "surface_max": 80,
                        "score": 20,
                        "score_label": "chaud",
                        "statut": "chaud",
                        "motivation": "Mutation professionnelle, délai court",
                        "urgence": "< 3 mois",
                        "objections": "Financement à confirmer",
                        "financement_str": "prêt bancaire, apport 20%",
                        "updated_at": "2026-05-15 10:00",
                        "resume": "Lead test PropPilot — acheteur T3 Lyon 6, mutation pro. Budget cohérent avec le marché.",
                        "next_action_label": "Rappeler sous 2h pour proposer un RDV",
                        "next_action_reason": "Lead chaud, premier contact.",
                        "conversation_history": (
                            "[SMS IN  - 2026-05-15 09:55] Bonjour, je cherche un T3 à Lyon 6\n"
                            "[SMS OUT - 2026-05-15 09:56] Bonjour Marie, je suis Léa de PropPilot. "
                            "Quel est votre budget ?"
                        ),
                    }
                    _ok = _test_connector.push_test_lead(_test_lead)
                    if _ok:
                        st.success(f"Email test envoyé à {_email_target}.")
                    else:
                        st.error("Envoi échoué — vérifiez les logs.")
                except Exception as _e:
                    st.error(f"Erreur : {_e}")

    if _save_email:
        if not _email_target:
            st.warning("L'adresse email cible est requise.")
        else:
            try:
                from lib.crm_connectors.factory import save_crm_push_config
                save_crm_push_config(
                    client_id=client_id,
                    crm_type="email",
                    config={"target_email": _email_target, "crm_label": _email_crm_label},
                )
                st.success(f"Connecteur Email enregistré — leads transmis vers {_email_target}.")
            except Exception as _e:
                st.error(f"Erreur : {_e}")

else:
    if _current_type != "none":
        if st.button("Désactiver le connecteur", type="secondary"):
            try:
                from lib.crm_connectors.factory import save_crm_push_config
                save_crm_push_config(client_id=client_id, crm_type="none", config={})
                st.success("Connecteur désactivé.")
                st.rerun()
            except Exception as _e:
                st.error(f"Erreur : {_e}")

# ── Statut export CRM ──────────────────────────────────────────────────────────
if _selected_push_type != "none" or _current_type != "none":
    st.markdown("##### Statut de l'export")
    try:
        from lib.crm_connectors.factory import get_push_stats_7d
        _stats = get_push_stats_7d(client_id)
        _st_col1, _st_col2, _st_col3 = st.columns(3)
        with _st_col1:
            _last_sync = _crm_push_current.get("crm_last_sync_at")
            _sync_str  = _last_sync.strftime("%d/%m %H:%M") if _last_sync else "Jamais"
            st.metric("Dernière sync", _sync_str)
        with _st_col2:
            st.metric("Leads transmis (7 j)", _stats.get("success", 0))
        with _st_col3:
            st.metric("Erreurs (7 j)", _stats.get("error", 0))
        _last_err = _crm_push_current.get("crm_last_error")
        if _last_err:
            st.warning(f"Dernière erreur : {_last_err[:200]}")
    except Exception:
        st.caption("Statistiques indisponibles.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Préférences d'assistant
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
with st.expander("Préférences d'assistant IA", expanded=False):
    st.caption(
        "Personnalisez le nom et le rôle utilisés par votre assistant dans les échanges automatiques."
    )
    with st.form("assistant_prefs_form"):
        conseiller_prenom = st.text_input(
            "Prénom de l'assistant",
            value=st.session_state.get("config_conseiller_prenom", "Léa"),
            placeholder="ex: Léa",
        )
        conseiller_titre = st.text_input(
            "Titre de l'assistant",
            value=st.session_state.get("config_conseiller_titre", "conseillère immobilier"),
            placeholder="ex: conseillère immobilier",
        )
        prefs_save = st.form_submit_button("Enregistrer", type="primary")

    if prefs_save:
        st.session_state["config_conseiller_prenom"] = conseiller_prenom
        st.session_state["config_conseiller_titre"] = conseiller_titre
        st.success("Préférences d'assistant mises à jour.")
