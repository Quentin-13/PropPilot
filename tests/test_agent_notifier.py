"""
Tests — lib/agent_notifier.py

Couverture :
  1. Pas d'agent phone configuré → pas de crash, log approprié
  2. Pas de Twilio configuré → pas de crash, log approprié
  3. Agent phone + Twilio OK → notification envoyée
  4. Anti-spam : deux appels rapides sur le même lead → une seule notification
  5. notifications désactivées (sms_notif_enabled=False) → pas d'envoi
  6. Cooldown expiré → notification autorisée à nouveau
  7. Deep-link avec lead_id → corps contient ?lead_id=<lead_id>
  8. Sans lead_id → fallback dashboard général (pas de ?lead_id=)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_db_row(
    phone: str | None = "+33612345678",
    sms_notif_enabled: bool = True,
    twilio_sms_number: str | None = "+33700000001",
) -> dict:
    return {
        "phone": phone,
        "sms_notif_enabled": sms_notif_enabled,
        "twilio_sms_number": twilio_sms_number,
    }


def _make_settings(twilio_sid: str | None = "ACxxx", twilio_token: str | None = "token", sms_number: str | None = None):
    s = MagicMock()
    s.twilio_account_sid = twilio_sid
    s.twilio_auth_token = twilio_token
    s.twilio_sms_number = sms_number
    s.dashboard_url = "https://app.proppilot.fr"
    return s


def _mock_conn(row: dict | None):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ─── Reset anti-spam entre les tests ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cooldown():
    """Réinitialise le cache anti-spam avant chaque test."""
    from lib import agent_notifier
    agent_notifier._last_notif.clear()
    yield
    agent_notifier._last_notif.clear()


# ─── 1. Pas d'agent phone → skip silencieux ──────────────────────────────────

def test_no_agent_phone_no_crash():
    from lib.agent_notifier import notify_agent_sms

    row = _make_db_row(phone=None)
    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        # Ne doit pas lever d'exception
        notify_agent_sms(
            client_id="client-test",
            lead_id="lead-001",
            lead_name="Jean Dupont",
            from_number="+33611111111",
            dashboard_url="https://app.proppilot.fr",
        )


def test_no_agent_phone_no_sms_sent():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone=None)
    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch.object(twilio_tool.TwilioTool, "send_sms") as mock_send:
            notify_agent_sms(
                client_id="client-test",
                lead_id="lead-001",
                lead_name="",
                from_number="+33611111111",
                dashboard_url="https://app.proppilot.fr",
            )
            mock_send.assert_not_called()


# ─── 2. Pas de Twilio → skip silencieux ──────────────────────────────────────

def test_no_twilio_no_crash():
    from lib.agent_notifier import notify_agent_sms

    row = _make_db_row(phone="+33612345678", twilio_sms_number=None)
    settings_no_twilio = _make_settings(twilio_sid=None, twilio_token=None, sms_number=None)

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_no_twilio):
            notify_agent_sms(
                client_id="client-test",
                lead_id="lead-002",
                lead_name="Marie Martin",
                from_number="+33622222222",
                dashboard_url="https://app.proppilot.fr",
            )


def test_no_twilio_from_number_skipped():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number=None)
    settings_no_from = _make_settings(twilio_sid="ACxxx", twilio_token="tok", sms_number=None)

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_no_from):
            with patch.object(twilio_tool.TwilioTool, "send_sms") as mock_send:
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-003",
                    lead_name="Marie Martin",
                    from_number="+33622222222",
                    dashboard_url="https://app.proppilot.fr",
                )
                mock_send.assert_not_called()


# ─── 3. SMS envoyé si tout est configuré ─────────────────────────────────────

def test_sms_sent_when_configured():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(
                twilio_tool.TwilioTool,
                "send_sms",
                return_value={"success": True, "sid": "SM123", "mock": False},
            ) as mock_send:
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-004",
                    lead_name="Paul Bernard",
                    from_number="+33633333333",
                    dashboard_url="https://app.proppilot.fr",
                    next_action="Rappeler avant 18h",
                )
                mock_send.assert_called_once()
                call_args = mock_send.call_args
                # Vérifie que le destinataire est l'agent, pas le prospect
                assert call_args.kwargs.get("to") == "+33612345678" or call_args.args[0] == "+33612345678"


def test_sms_body_contains_lead_name():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")
    sent_bodies: list[str] = []

    def _capture_send(to, body, from_number=None):
        sent_bodies.append(body)
        return {"success": True, "sid": "SM456", "mock": False}

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(twilio_tool.TwilioTool, "send_sms", side_effect=_capture_send):
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-005",
                    lead_name="Claire Lefebvre",
                    from_number="+33644444444",
                    dashboard_url="https://app.proppilot.fr",
                    next_action="Prévoir relance début 2027",
                )

    assert len(sent_bodies) == 1
    body = sent_bodies[0]
    assert "Claire Lefebvre" in body
    assert "Prévoir relance début 2027" in body
    assert "Répondez depuis PropPilot" in body
    assert "Ouvrir PropPilot" not in body  # ancienne formulation supprimée


# ─── 4. Anti-spam : deux appels rapides → une seule notification ──────────────

def test_antispam_second_call_ignored():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(
                twilio_tool.TwilioTool,
                "send_sms",
                return_value={"success": True, "sid": "SM789", "mock": False},
            ) as mock_send:
                # Premier appel → envoi
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-006",
                    lead_name="Sophie Morel",
                    from_number="+33655555555",
                    dashboard_url="https://app.proppilot.fr",
                )
                # Deuxième appel immédiat → cooldown actif → pas d'envoi
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-006",
                    lead_name="Sophie Morel",
                    from_number="+33655555555",
                    dashboard_url="https://app.proppilot.fr",
                )
                # Troisième appel → même lead → toujours bloqué
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-006",
                    lead_name="Sophie Morel",
                    from_number="+33655555555",
                    dashboard_url="https://app.proppilot.fr",
                )

                assert mock_send.call_count == 1, (
                    f"Expected 1 SMS sent, got {mock_send.call_count}"
                )


def test_antispam_different_leads_both_notified():
    """Deux leads différents → deux notifications indépendantes."""
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(
                twilio_tool.TwilioTool,
                "send_sms",
                return_value={"success": True, "sid": "SM000", "mock": False},
            ) as mock_send:
                notify_agent_sms("client-test", "lead-A", "Alice", "+33600000001", "https://app")
                notify_agent_sms("client-test", "lead-B", "Bob",   "+33600000002", "https://app")
                assert mock_send.call_count == 2


# ─── 5. Notifications désactivées → pas d'envoi ──────────────────────────────

def test_notif_disabled_skipped():
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", sms_notif_enabled=False)
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(twilio_tool.TwilioTool, "send_sms") as mock_send:
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-007",
                    lead_name="Marc Leroy",
                    from_number="+33666666666",
                    dashboard_url="https://app.proppilot.fr",
                )
                mock_send.assert_not_called()


# ─── 6. Cooldown expiré → notification autorisée ────────────────────────────

def test_cooldown_expired_allows_resend():
    from lib import agent_notifier
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")

    # Simuler que le cooldown a expiré (timestamp dans le passé)
    agent_notifier._last_notif["lead-008"] = time.time() - 700  # 700s > 600s cooldown

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(
                twilio_tool.TwilioTool,
                "send_sms",
                return_value={"success": True, "sid": "SMabc", "mock": False},
            ) as mock_send:
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-008",
                    lead_name="Thomas Girard",
                    from_number="+33677777777",
                    dashboard_url="https://app.proppilot.fr",
                )
                mock_send.assert_called_once()


# ─── 7. Deep-link avec lead_id → corps contient ?lead_id= ────────────────────

def test_sms_body_contains_deep_link():
    """La notification doit contenir un deep-link direct vers la conversation."""
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")
    sent_bodies: list[str] = []

    def _capture(to, body, from_number=None):
        sent_bodies.append(body)
        return {"success": True, "sid": "SMdeep", "mock": False}

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(twilio_tool.TwilioTool, "send_sms", side_effect=_capture):
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="lead-xyz-123",
                    lead_name="Jean Dupont",
                    from_number="+33611111111",
                    dashboard_url="https://app.proppilot.fr",
                )

    assert len(sent_bodies) == 1
    body = sent_bodies[0]
    assert "?lead_id=lead-xyz-123" in body
    assert "https://app.proppilot.fr/sms?lead_id=lead-xyz-123" in body
    assert "Répondez depuis PropPilot" in body


# ─── 8. Sans lead_id → fallback dashboard général ────────────────────────────

def test_sms_body_fallback_without_lead_id():
    """Sans lead_id, le lien pointe vers le dashboard général (pas de ?lead_id=)."""
    from lib.agent_notifier import notify_agent_sms
    from tools import twilio_tool

    row = _make_db_row(phone="+33612345678", twilio_sms_number="+33700000001")
    settings_ok = _make_settings(twilio_sid="ACxxx", twilio_token="tok")
    sent_bodies: list[str] = []

    def _capture(to, body, from_number=None):
        sent_bodies.append(body)
        return {"success": True, "sid": "SMfb", "mock": False}

    with patch("memory.database.get_connection", return_value=_mock_conn(row)):
        with patch("config.settings.get_settings", return_value=settings_ok):
            with patch.object(twilio_tool.TwilioTool, "send_sms", side_effect=_capture):
                notify_agent_sms(
                    client_id="client-test",
                    lead_id="",
                    lead_name="Jean Dupont",
                    from_number="+33611111111",
                    dashboard_url="https://app.proppilot.fr",
                )

    assert len(sent_bodies) == 1
    body = sent_bodies[0]
    assert "?lead_id=" not in body
    assert "https://app.proppilot.fr" in body
    assert "Répondez depuis PropPilot" in body
