"""
Tests Vonage — mock SMS + webhook entrant.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock


# ─── test_vonage_send_mock ──────────────────────────────────────────────────

def test_vonage_send_mock():
    """VonageTool en mode mock retourne success sans appel réseau."""
    # Force mock_mode en désactivant les clés
    with patch.dict(os.environ, {"VONAGE_API_KEY": "", "VONAGE_API_SECRET": ""}):
        # Invalider le cache settings
        from config.settings import get_settings
        get_settings.cache_clear()

        from tools.vonage_tool import VonageTool
        tool = VonageTool()

        assert tool.mock_mode is True

        result = tool.send_sms(to="+33612345678", body="Test PropPilot")
        assert result["success"] is True
        assert result["mock"] is True
        assert result["message_id"].startswith("mock_vonage_")
        assert result["to"] == "+33612345678"

        # Cleanup
        get_settings.cache_clear()


def test_vonage_format_french_number():
    """format_french_number convertit correctement les formats courants."""
    from config.settings import get_settings
    get_settings.cache_clear()

    from tools.vonage_tool import VonageTool
    tool = VonageTool()

    assert tool.format_french_number("0612345678") == "+33612345678"
    assert tool.format_french_number("33612345678") == "+33612345678"
    assert tool.format_french_number("+33612345678") == "+33612345678"
    assert tool.format_french_number("06 12 34 56 78") == "+33612345678"

    get_settings.cache_clear()


# ─── test_vonage_webhook ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vonage_webhook_post_returns_200():
    """POST /webhooks/vonage/sms retourne 200 et déclenche l'orchestrateur."""
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/proppilot_test")
    os.environ["TESTING"] = "true"

    from config.settings import get_settings
    get_settings.cache_clear()

    from httpx import AsyncClient, ASGITransport

    # Mock get_connection + process_incoming_message
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchone.return_value = None

    with (
        patch("memory.database.get_connection", return_value=mock_conn),
        patch("orchestrator.process_incoming_message") as mock_process,
        patch("memory.database.init_database"),
    ):
        from server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhooks/vonage/sms",
                json={"msisdn": "33612345678", "to": "33700000000", "text": "Bonjour"},
            )

        assert response.status_code == 200

    get_settings.cache_clear()
    os.environ.pop("TESTING", None)
