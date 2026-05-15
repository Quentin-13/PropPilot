"""
Tests — lib/crm_connectors/ (push-only layer PropPilot → CRM)

Couverture :
- Apimo connector mock + vrai HTTP simulé
- Email parsing connector mock
- Factory : routing, crm_sync_log, gestion erreur
- next_action : calcul, cache, priorités
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Fixture lead_data de base ────────────────────────────────────────────────

@pytest.fixture
def lead_data():
    return {
        "id": "lead-push-001",
        "client_id": "client-test-001",
        "prenom": "Marie",
        "nom": "Dupont",
        "telephone": "+33612345678",
        "email": "marie.dupont@test.fr",
        "type_projet": "achat",
        "budget_min": 300000,
        "budget_max": 400000,
        "zone": "Lyon 6ème",
        "type_bien": "T3",
        "surface_min": 65,
        "surface_max": 80,
        "motivation": "mutation_pro",
        "score_label": "chaud",
        "resume": "Acheteur T3 Lyon 6, mutation professionnelle, budget 300-400k.",
        "next_action_label": "Rappeler avant 18h",
        "next_action_reason": "Lead chaud non recontacté depuis 24h.",
    }


# ─── Chantier 2 : connecteur Apimo ────────────────────────────────────────────

class TestApimoConnector:

    def test_mock_mode_push_returns_true(self, lead_data):
        """Mode mock (pas de clé) → push_lead retourne True sans appel réseau."""
        from lib.crm_connectors.apimo import ApimoConnector
        conn = ApimoConnector(provider_id="", api_token="")
        assert conn._mock is True
        result = conn.push_lead(lead_data)
        assert result is True

    def test_mock_mode_test_key_prefix(self, lead_data):
        """Préfixe test_ → mode mock activé automatiquement."""
        from lib.crm_connectors.apimo import ApimoConnector
        conn = ApimoConnector(provider_id="12345", api_token="test_fake_token")
        assert conn._mock is True

    def test_test_connection_mock(self):
        """test_connection en mock retourne success=True."""
        from lib.crm_connectors.apimo import ApimoConnector
        conn = ApimoConnector(provider_id="", api_token="")
        result = conn.test_connection()
        assert result["success"] is True
        assert "MOCK" in result["message"]

    def test_push_lead_http_success(self, lead_data):
        """push_lead en mode réel avec HTTP 201 → retourne True."""
        from lib.crm_connectors.apimo import ApimoConnector

        mock_contact_resp = MagicMock()
        mock_contact_resp.status_code = 201
        mock_contact_resp.json.return_value = {"id": "apimo-contact-42"}

        mock_note_resp = MagicMock()
        mock_note_resp.status_code = 201

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [mock_contact_resp, mock_note_resp]

        conn = ApimoConnector(provider_id="123", api_token="real_token")
        # httpx importé lazily → on patche au niveau du module httpx
        with patch("httpx.Client", return_value=mock_client):
            result = conn.push_lead(lead_data)

        assert result is True

    def test_push_lead_401_returns_false_no_retry(self, lead_data):
        """HTTP 401 → retourne False immédiatement sans retry."""
        from lib.crm_connectors.apimo import ApimoConnector

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        conn = ApimoConnector(provider_id="123", api_token="bad_token")
        with patch("httpx.Client", return_value=mock_client):
            result = conn.push_lead(lead_data)

        assert result is False
        # 401 → une seule tentative (pas de retry)
        assert mock_client.post.call_count == 1

    def test_push_lead_network_error_retries_and_returns_false(self, lead_data):
        """Erreur réseau → retry 3x puis retourne False."""
        from lib.crm_connectors.apimo import ApimoConnector

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = ConnectionError("timeout")

        conn = ApimoConnector(provider_id="123", api_token="real_token")
        with patch("httpx.Client", return_value=mock_client), \
             patch("lib.crm_connectors.apimo.time.sleep"):
            result = conn.push_lead(lead_data)

        assert result is False
        assert mock_client.post.call_count == 3  # 3 tentatives


# ─── Chantier 3 : connecteur Email parsing ────────────────────────────────────

class TestEmailParsingConnector:

    def test_push_lead_mock_sendgrid_missing(self, lead_data):
        """Sans clé SendGrid → mode mock (log [MOCK]), retourne True."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector

        mock_settings = MagicMock()
        mock_settings.sendgrid_available = False

        conn = EmailParsingConnector(target_email="import@crm.fr", crm_label="Netty")
        # get_settings importé lazily dans _send() → patcher config.settings
        with patch("config.settings.get_settings", return_value=mock_settings):
            result = conn.push_lead(lead_data)

        assert result is True

    def test_subject_contains_action_label(self, lead_data):
        """Le sujet suit le format [PropPilot] avec nom et statut."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector
        conn = EmailParsingConnector(target_email="test@crm.fr")
        subject = conn._build_subject(lead_data)
        assert subject.startswith("[PropPilot]")
        assert "Marie" in subject or "Dupont" in subject
        assert "chaud" in subject

    def test_subject_without_action(self, lead_data):
        """Sans next_action_label → sujet sans [ACTION:]."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector
        conn = EmailParsingConnector(target_email="test@crm.fr")
        lead_data_no_action = {**lead_data, "next_action_label": None}
        subject = conn._build_subject(lead_data_no_action)
        assert "[ACTION:" not in subject

    def test_body_plain_text_structure(self, lead_data):
        """Le corps est plain text avec les champs requis (format spec)."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector
        conn = EmailParsingConnector(target_email="test@crm.fr")
        body = conn._build_body(lead_data)
        assert "NOM: Dupont" in body
        assert "PRENOM: Marie" in body
        assert "TELEPHONE: +33612345678" in body
        assert "STATUT:" in body
        assert "PROCHAINE_ACTION: Rappeler avant 18h" in body
        assert "PropPilot — Mise à jour automatique" in body

    def test_no_target_email_returns_false(self, lead_data):
        """Sans email cible → push_lead retourne False."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector
        conn = EmailParsingConnector(target_email="")
        result = conn.push_lead(lead_data)
        assert result is False

    def test_push_lead_sendgrid_success(self, lead_data):
        """Avec SendGrid disponible → envoie et retourne True."""
        from lib.crm_connectors.email_parsing import EmailParsingConnector

        mock_settings = MagicMock()
        mock_settings.sendgrid_available = True
        mock_settings.sendgrid_api_key = "SG.fake"
        mock_settings.sendgrid_from_email = "noreply@proppilot.fr"
        mock_settings.sendgrid_from_name = "PropPilot"

        mock_sg_response = MagicMock()
        mock_sg_response.status_code = 202

        mock_sg_instance = MagicMock()
        mock_sg_instance.send.return_value = mock_sg_response

        conn = EmailParsingConnector(target_email="import@crm.fr", reply_to_email="agent@agence.fr")
        # Imports lazily dans _send() → patcher au niveau des modules sources
        with patch("config.settings.get_settings", return_value=mock_settings), \
             patch("sendgrid.SendGridAPIClient", return_value=mock_sg_instance):
            result = conn.push_lead(lead_data)

        assert result is True


# ─── Chantier 2 : mapping Apimo ───────────────────────────────────────────────

class TestApimoMapping:

    def test_build_note_text_contains_required_fields(self, lead_data):
        from lib.crm_connectors.apimo_mapping import build_note_text
        note = build_note_text(lead_data)
        assert "PropPilot" in note
        assert "proppilot-chaud" in note
        assert "Achat" in note
        assert "Lyon 6ème" in note
        assert "300" in note  # budget
        assert "Rappeler avant 18h" in note

    def test_budget_str_both(self):
        from lib.crm_connectors.apimo_mapping import _budget_str
        result = _budget_str({"budget_min": 300000, "budget_max": 400000})
        assert "300" in result and "400" in result

    def test_budget_str_max_only(self):
        from lib.crm_connectors.apimo_mapping import _budget_str
        result = _budget_str({"budget_min": None, "budget_max": 400000})
        assert "400" in result
        assert "jusqu'à" in result

    def test_surface_str_both(self):
        from lib.crm_connectors.apimo_mapping import _surface_str
        result = _surface_str({"surface_min": 65, "surface_max": 80})
        assert "65" in result and "80" in result and "m²" in result


# ─── Test intégration : fallback si API Apimo 500 ─────────────────────────────

class TestCRMFallback:

    def test_api_500_lead_stays_in_proppilot(self, lead_data):
        """Si Apimo répond 500 → push retourne False, lead non perdu côté PropPilot."""
        from lib.crm_connectors.apimo import ApimoConnector

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        conn = ApimoConnector(provider_id="123", api_token="real_token")
        with patch("httpx.Client", return_value=mock_client), \
             patch("lib.crm_connectors.apimo.time.sleep"):
            result = conn.push_lead(lead_data)

        # L'erreur est remontée (False) mais aucune exception n'a été levée
        assert result is False
        # Le lead_data dict est intact côté Python
        assert lead_data["id"] == "lead-push-001"


# ─── Chantier 6 : next_action ─────────────────────────────────────────────────

class TestNextAction:

    def test_mock_action_chaud(self):
        """Lead chaud → priorité haute."""
        from lib.lead_extraction.next_action import _mock_action
        action = _mock_action({"score": 20})
        assert action.priority == "haute"
        assert len(action.label) <= 80

    def test_mock_action_tiede(self):
        """Lead tiède → priorité moyenne."""
        from lib.lead_extraction.next_action import _mock_action
        action = _mock_action({"score": 14})
        assert action.priority == "moyenne"

    def test_mock_action_froid(self):
        """Lead froid → priorité basse."""
        from lib.lead_extraction.next_action import _mock_action
        action = _mock_action({"score": 3})
        assert action.priority == "basse"

    def test_cache_check_fresh_no_new_activity(self):
        """Cache valide si computed_at < 30 min ET pas de nouvelle activité."""
        from lib.lead_extraction.next_action import _is_cached
        computed_at = datetime.now() - timedelta(minutes=10)
        latest_activity = datetime.now() - timedelta(hours=2)
        assert _is_cached(computed_at, latest_activity) is True

    def test_cache_check_expired(self):
        """Cache invalide si computed_at > 30 min."""
        from lib.lead_extraction.next_action import _is_cached
        computed_at = datetime.now() - timedelta(minutes=45)
        assert _is_cached(computed_at, None) is False

    def test_cache_check_new_activity_invalidates(self):
        """Cache invalide si nouvelle activité après computed_at."""
        from lib.lead_extraction.next_action import _is_cached
        computed_at = datetime.now() - timedelta(minutes=5)
        latest_activity = datetime.now() - timedelta(minutes=2)  # plus récent que computed_at
        assert _is_cached(computed_at, latest_activity) is False

    def test_parse_deadline_valid_iso(self):
        """ISO 8601 avec timezone → datetime tz-naïf."""
        from lib.lead_extraction.next_action import _parse_deadline
        result = _parse_deadline("2026-05-11T18:00:00+02:00")
        assert result is not None
        assert result.tzinfo is None  # stocké sans tz pour PostgreSQL

    def test_parse_deadline_none(self):
        """None ou chaîne vide → None."""
        from lib.lead_extraction.next_action import _parse_deadline
        assert _parse_deadline(None) is None
        assert _parse_deadline("") is None

    def test_compute_next_action_mock_mode(self, monkeypatch):
        """En mode mock, compute_next_action retourne une action sans appel LLM."""
        from lib.lead_extraction import next_action as na_module

        mock_lead = {
            "id": "lead-test",
            "client_id": "client-test",
            "prenom": "Jean",
            "nom": "Martin",
            "projet": "achat",
            "score": 20,
            "statut": "entrant",
            "motivation": "mutation_pro",
            "created_at": datetime.now(),
            "next_action_label": None,
            "next_action_priority": None,
            "next_action_reason": None,
            "next_action_deadline": None,
            "next_action_computed_at": None,
        }

        monkeypatch.setattr(na_module, "_fetch_lead", lambda lid: mock_lead)
        monkeypatch.setattr(na_module, "_latest_activity_at", lambda lid: None)
        monkeypatch.setattr(na_module, "_save_next_action", lambda lid, action: None)

        mock_settings = MagicMock()
        mock_settings.anthropic_available = False
        mock_settings.testing = False
        mock_settings.mock_mode = "always"

        # get_settings est importé lazily dans _compute_via_llm → patcher config.settings
        with patch("config.settings.get_settings", return_value=mock_settings):
            from lib.lead_extraction.next_action import compute_next_action
            result = compute_next_action("lead-test")

        assert result is not None
        assert result.priority == "haute"  # score 20 → chaud → haute
        assert result.from_cache is False

    def test_compute_next_action_cache_hit(self, monkeypatch):
        """Deuxième appel dans les 30 min sans activité → utilise le cache."""
        from lib.lead_extraction import next_action as na_module

        computed_at = datetime.now() - timedelta(minutes=5)
        mock_lead = {
            "id": "lead-test",
            "score": 20,
            "statut": "entrant",
            "projet": "achat",
            "motivation": "",
            "created_at": datetime.now(),
            "next_action_label": "Rappeler maintenant",
            "next_action_priority": "haute",
            "next_action_reason": "Lead chaud.",
            "next_action_deadline": None,
            "next_action_computed_at": computed_at,
        }

        monkeypatch.setattr(na_module, "_fetch_lead", lambda lid: mock_lead)
        # Pas de nouvelle activité (plus ancienne que computed_at)
        monkeypatch.setattr(
            na_module, "_latest_activity_at",
            lambda lid: datetime.now() - timedelta(hours=1)
        )

        from lib.lead_extraction.next_action import compute_next_action
        result = compute_next_action("lead-test")

        assert result is not None
        assert result.from_cache is True
        assert result.label == "Rappeler maintenant"
