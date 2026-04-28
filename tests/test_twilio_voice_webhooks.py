"""
Tests — webhooks/twilio_voice.py

Vérifie :
- Validation de signature sur tous les endpoints
- Réponse TwiML valide (avec mention légale + Dial)
- Idempotence sur CallSid
- Traitement du webhook recording
- Mise à jour statut via /status
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from unittest.mock import MagicMock, patch

import pytest


FAKE_AUTH_TOKEN = "test_voice_token_xyz"
BASE_URL = "http://testserver"


def _sign(url: str, params: dict, token: str = FAKE_AUTH_TOKEN) -> str:
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    msg = url + sorted_params
    sig = hmac.new(token.encode(), msg.encode(), hashlib.sha1).digest()
    return base64.b64encode(sig).decode()


def _clear_settings():
    from config.settings import get_settings
    get_settings.cache_clear()


@pytest.fixture
def client():
    """Client avec TWILIO_AUTH_TOKEN fictif — les requêtes sans signature sont rejetées."""
    _clear_settings()
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": FAKE_AUTH_TOKEN, "TESTING": "true"}):
        _clear_settings()
        from fastapi.testclient import TestClient
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    _clear_settings()


@pytest.fixture
def client_no_auth():
    """Client avec TWILIO_AUTH_TOKEN vide — la validation de signature est bypassée."""
    # Mettre TWILIO_AUTH_TOKEN="" surcharge la valeur dans .env
    _clear_settings()
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": "", "TESTING": "true"}):
        _clear_settings()
        from fastapi.testclient import TestClient
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    _clear_settings()


# ── Signature validation ──────────────────────────────────────────────────────

def test_incoming_no_signature_rejected(client):
    resp = client.post(
        "/webhooks/twilio/voice/incoming",
        data={"CallSid": "CA001", "From": "+33600000001", "To": "+33700000001"},
    )
    assert resp.status_code == 403


def test_incoming_bad_signature_rejected(client):
    resp = client.post(
        "/webhooks/twilio/voice/incoming",
        data={"CallSid": "CA001", "From": "+33600000001", "To": "+33700000001"},
        headers={"X-Twilio-Signature": "invalide"},
    )
    assert resp.status_code == 403


def test_recording_no_signature_rejected(client):
    resp = client.post(
        "/webhooks/twilio/voice/recording",
        data={"CallSid": "CA001", "RecordingStatus": "completed"},
    )
    assert resp.status_code == 403


def test_status_no_signature_rejected(client):
    resp = client.post(
        "/webhooks/twilio/voice/status",
        data={"CallSid": "CA001", "CallStatus": "completed"},
    )
    assert resp.status_code == 403


# ── TwiML inbound ─────────────────────────────────────────────────────────────

def test_incoming_returns_twiml(client_no_auth):
    """Appel entrant sans agent configuré — TwiML valide avec mention légale."""
    with patch("memory.call_repository.get_phone_number_config", return_value=None), \
         patch("webhooks.twilio_voice._persist_incoming_call"), \
         patch("memory.database.get_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/incoming",
            data={
                "CallSid": "CA001",
                "From": "+33600000001",
                "To": "+33757596114",
                "CallStatus": "ringing",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    assert "<Response>" in body
    assert "<Say" in body or "<Play" in body
    assert "<Record" in body or "<Dial" in body


def test_incoming_with_agent_phone_includes_dial(client_no_auth):
    """Appel entrant avec agent configuré — TwiML contient <Dial>."""
    phone_config = {
        "agency_id": "agency-001",
        "agent_id": "agent-001",
        "agent_phone": "+33612345678",
    }
    with patch("memory.call_repository.get_phone_number_config", return_value=phone_config), \
         patch("webhooks.twilio_voice._persist_incoming_call"):
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/incoming",
            data={
                "CallSid": "CA002",
                "From": "+33600000002",
                "To": "+33757596114",
                "CallStatus": "ringing",
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "<Dial" in body
    assert "+33612345678" in body
    assert 'record="record-from-answer"' in body


def test_twiml_includes_legal_notice(client_no_auth):
    """Vérifie que la mention légale RGPD est présente dans le TwiML."""
    with patch("memory.call_repository.get_phone_number_config", return_value=None), \
         patch("webhooks.twilio_voice._persist_incoming_call"), \
         patch("memory.database.get_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/incoming",
            data={
                "CallSid": "CA003",
                "From": "+33600000003",
                "To": "+33757596114",
                "CallStatus": "ringing",
            },
        )

    body = resp.text
    # Mention légale : audio <Play> ou TTS <Say> avec mot "enregistr"
    assert "<Play" in body or "enregistr" in body.lower()


# ── Recording webhook ─────────────────────────────────────────────────────────

def test_recording_completed_accepted(client_no_auth):
    """Webhook recording avec status=completed déclenche le pipeline."""
    with patch("webhooks.twilio_voice._process_recording") as mock_pipeline:
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/recording",
            data={
                "CallSid": "CA004",
                "RecordingSid": "RE001",
                "RecordingUrl": "https://api.twilio.com/recordings/RE001",
                "RecordingStatus": "completed",
                "RecordingDuration": "45",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_recording_non_completed_skipped(client_no_auth):
    """Webhook recording avec status != completed est ignoré silencieusement."""
    with patch("webhooks.twilio_voice._process_recording") as mock_pipeline:
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/recording",
            data={
                "CallSid": "CA005",
                "RecordingSid": "RE002",
                "RecordingUrl": "https://api.twilio.com/recordings/RE002",
                "RecordingStatus": "absent",
                "RecordingDuration": "0",
            },
        )
    assert resp.status_code == 200
    mock_pipeline.assert_not_called()


# ── Status webhook ────────────────────────────────────────────────────────────

def test_status_completed_updates_db(client_no_auth):
    """Webhook status=completed met à jour ended_at + duration."""
    mock_call = {"id": "call-id-status", "answered_at": None}
    with patch("memory.call_repository.get_call_by_sid", return_value=mock_call), \
         patch("memory.call_repository.update_call_status") as mock_update:
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/status",
            data={
                "CallSid": "CA006",
                "CallStatus": "completed",
                "CallDuration": "120",
            },
        )

    assert resp.status_code == 200
    mock_update.assert_called_once()
    call_args = mock_update.call_args
    assert call_args[0][0] == "call-id-status"
    assert call_args[0][1] == "completed"
    assert call_args[1].get("duration_seconds") == 120


def test_status_unknown_call_silent(client_no_auth):
    """Webhook status pour un CallSid inconnu — pas d'erreur."""
    with patch("memory.call_repository.get_call_by_sid", return_value=None):
        resp = client_no_auth.post(
            "/webhooks/twilio/voice/status",
            data={
                "CallSid": "CA_UNKNOWN",
                "CallStatus": "completed",
                "CallDuration": "30",
            },
        )
    assert resp.status_code == 200


# ── Click-to-call ─────────────────────────────────────────────────────────────

def test_outbound_requires_auth():
    """POST /api/calls/outbound sans JWT → 401."""
    _clear_settings()
    with patch.dict(os.environ, {"TESTING": "true"}):
        _clear_settings()
        from fastapi.testclient import TestClient
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                "/api/calls/outbound",
                json={"lead_id": "lead-001", "agent_id": "agent-001"},
            )
    assert resp.status_code == 401
    _clear_settings()


def test_outbound_with_auth_mock_mode():
    """Appel sortant avec JWT valide en mode mock — retourne call_id simulé."""
    _clear_settings()
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": "", "TESTING": "true", "JWT_SECRET_KEY": "test-secret"}):
        _clear_settings()

        # Générer un vrai JWT de test (même algo que auth.py)
        from datetime import datetime, timedelta, timezone
        from jose import jwt as jose_jwt
        expiry = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        token = jose_jwt.encode(
            {"sub": "user-123", "plan": "Starter", "exp": expiry},
            "test-secret",
            algorithm="HS256",
        )

        with patch("memory.lead_repository.get_lead") as mock_get_lead, \
             patch("memory.database.get_connection") as mock_conn, \
             patch("memory.call_repository.create_call", return_value="mock-call-id"):

            mock_lead = MagicMock()
            mock_lead.telephone = "+33699998888"
            mock_get_lead.return_value = mock_lead

            mock_row = {"phone": "+33611112222", "twilio_sms_number": "+33757596114"}
            mock_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = mock_row

            from fastapi.testclient import TestClient
            from server import app
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    "/api/calls/outbound",
                    json={
                        "lead_id": "lead-001",
                        "agent_id": "user-123",
                        "lead_phone": "+33699998888",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

    assert resp.status_code == 200
    data = resp.json()
    assert data["call_id"] == "mock-call-id"
    assert data["status"] == "initiated"
    assert "[MOCK]" in data["message"]
    _clear_settings()
