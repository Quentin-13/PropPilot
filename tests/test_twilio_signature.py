"""
Tests — Validation signature Twilio sur les routes webhook.

Vérifie que :
- Une requête sans X-Twilio-Signature → 403
- Une requête avec signature invalide → 403
- Une requête avec signature valide → 200 (traitement normal)
- Si TWILIO_AUTH_TOKEN absent → la vérification est ignorée (mode démo/mock)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from unittest.mock import patch, MagicMock

import pytest


TWILIO_ROUTES = [
    "/webhooks/twilio/sms",
    "/webhooks/sms",
    "/webhooks/sms/status",
    "/webhooks/whatsapp",
    "/webhooks/whatsapp/status",
    "/webhooks/twilio/voice",
]

FAKE_AUTH_TOKEN = "test_auth_token_abc123"
FAKE_FORM = {"From": "+33600000001", "To": "+33700000001", "Body": "Bonjour"}


def _compute_twilio_signature(auth_token: str, url: str, params: dict) -> str:
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    signature_str = url + sorted_params
    expected = hmac.new(
        auth_token.encode("utf-8"),
        signature_str.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(expected).decode()


@pytest.fixture
def client_with_token():
    """Client FastAPI avec TWILIO_AUTH_TOKEN configuré."""
    os.environ["TESTING"] = "true"
    with patch("config.settings._settings_instance", None):
        with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": FAKE_AUTH_TOKEN}):
            from fastapi.testclient import TestClient
            from server import app
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


@pytest.fixture
def client_no_token():
    """Client FastAPI sans TWILIO_AUTH_TOKEN (mode mock/démo)."""
    os.environ["TESTING"] = "true"
    with patch("config.settings._settings_instance", None):
        env = {k: v for k, v in os.environ.items() if k != "TWILIO_AUTH_TOKEN"}
        env.pop("TWILIO_AUTH_TOKEN", None)
        with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": ""}, clear=False):
            from fastapi.testclient import TestClient
            from server import app
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


@pytest.mark.parametrize("route", TWILIO_ROUTES)
def test_missing_signature_returns_403(route):
    """Requête sans X-Twilio-Signature → 403 quand token configuré."""
    os.environ["TESTING"] = "true"
    from fastapi.testclient import TestClient

    async def _fake_validate(request):
        return False

    with patch("server.validate_twilio_signature", side_effect=_fake_validate):
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(route, data=FAKE_FORM)
    assert resp.status_code == 403, (
        f"{route} doit retourner 403 quand la signature est invalide, got {resp.status_code}"
    )


@pytest.mark.parametrize("route", TWILIO_ROUTES)
def test_invalid_signature_returns_403(route):
    """Requête avec signature incorrecte → 403."""
    os.environ["TESTING"] = "true"
    from fastapi.testclient import TestClient

    async def _fake_validate(request):
        return False

    with patch("server.validate_twilio_signature", side_effect=_fake_validate):
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                route,
                data=FAKE_FORM,
                headers={"X-Twilio-Signature": "invalidsignature=="},
            )
    assert resp.status_code == 403, (
        f"{route} doit retourner 403 quand la signature est invalide, got {resp.status_code}"
    )


@pytest.mark.parametrize("route", TWILIO_ROUTES)
def test_valid_signature_passes_through(route):
    """Requête avec signature valide → pas de 403 (la validation ne bloque pas)."""
    os.environ["TESTING"] = "true"
    from fastapi.testclient import TestClient

    async def _fake_validate(request):
        return True

    with patch("server.validate_twilio_signature", side_effect=_fake_validate):
        from server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(route, data=FAKE_FORM)
    assert resp.status_code != 403, (
        f"{route} ne doit pas retourner 403 avec une signature valide, got {resp.status_code}"
    )


def test_validate_twilio_signature_no_token_allows_all():
    """Sans TWILIO_AUTH_TOKEN, validate_twilio_signature retourne True (mode démo)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    with patch("tools.security.get_settings") as mock_settings:
        mock_settings.return_value.twilio_auth_token = None
        from tools.security import validate_twilio_signature

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""
        mock_request.url = "http://test.com/webhooks/twilio/sms"
        mock_request.client.host = "127.0.0.1"

        result = asyncio.get_event_loop().run_until_complete(
            validate_twilio_signature(mock_request)
        )
    assert result is True


def test_validate_twilio_signature_no_header_rejects():
    """X-Twilio-Signature absent avec token configuré → False."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    with patch("tools.security.get_settings") as mock_settings:
        mock_settings.return_value.twilio_auth_token = FAKE_AUTH_TOKEN

        from tools.security import validate_twilio_signature

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""
        mock_request.url = "http://test.com/webhooks/twilio/sms"
        mock_request.client.host = "127.0.0.1"
        mock_request.form = AsyncMock(return_value={})

        result = asyncio.get_event_loop().run_until_complete(
            validate_twilio_signature(mock_request)
        )
    assert result is False


def test_validate_twilio_signature_uses_request_validator():
    """validate_twilio_signature délègue à twilio.RequestValidator."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

    with mock_patch("tools.security.get_settings") as mock_settings:
        mock_settings.return_value.twilio_auth_token = FAKE_AUTH_TOKEN

        mock_validator_instance = MagicMock()
        mock_validator_instance.validate.return_value = True

        with mock_patch("twilio.request_validator.RequestValidator") as MockValidator:
            MockValidator.return_value = mock_validator_instance

            from tools.security import validate_twilio_signature

            mock_request = MagicMock()
            mock_request.headers.get.return_value = "somesignature"
            mock_request.url = "http://test.com/webhooks/twilio/sms"
            mock_request.client.host = "127.0.0.1"
            mock_request.form = AsyncMock(return_value={"From": "+33600000001"})

            result = asyncio.get_event_loop().run_until_complete(
                validate_twilio_signature(mock_request)
            )

        mock_validator_instance.validate.assert_called_once()
    assert result is True
