"""
Tests — VoiceCallAgent avec Twilio (migration depuis Retell).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _make_lead(lead_id: str = "lead_test_001", score: int = 8, telephone: str = "+33600000099"):
    from memory.models import Lead, ProjetType
    return Lead(
        id=lead_id,
        client_id="test_client",
        prenom="Marie",
        telephone=telephone,
        score=score,
        projet=ProjetType.ACHAT,
    )


def test_call_hot_lead_uses_twilio(monkeypatch, _reset_db_between_tests):
    """call_hot_lead doit utiliser TwilioTool.make_outbound_call, pas RetellTool."""
    from agents.voice_call import VoiceCallAgent
    from memory.lead_repository import create_lead

    # Créer un vrai lead en DB si disponible, sinon mocker get_lead
    lead = _make_lead()

    monkeypatch.setattr("agents.voice_call.get_lead", lambda lid: lead)
    monkeypatch.setattr("agents.voice_call.update_lead", lambda l: l)
    monkeypatch.setattr("agents.voice_call.add_conversation_message", lambda **kw: None)

    # Mock usage_tracker
    monkeypatch.setattr(
        "agents.voice_call.check_and_consume",
        lambda *a, **kw: {"allowed": True, "message": "ok"},
    )

    # Mock CalendarTool
    mock_calendar = MagicMock()
    mock_calendar.get_next_slots_for_voice.return_value = ["mardi 10h", "jeudi 14h", "vendredi 11h"]
    monkeypatch.setattr("agents.voice_call.CalendarTool", lambda: mock_calendar)

    # Mock ElevenLabsTool
    mock_tts = MagicMock()
    mock_tts.text_to_speech.return_value = {"success": True, "audio_path": "/tmp/test.mp3", "mock": True}
    monkeypatch.setattr("agents.voice_call.ElevenLabsTool", lambda: mock_tts)

    # Mock TwilioTool
    mock_twilio = MagicMock()
    mock_twilio.make_outbound_call.return_value = {
        "success": True,
        "call_sid": "CA_test_123",
        "mock": True,
    }
    monkeypatch.setattr("agents.voice_call.TwilioTool", lambda: mock_twilio)

    # Mock _save_call_to_db
    mock_save = MagicMock()

    agent = VoiceCallAgent(client_id="test_client", tier="Starter")
    agent._save_call_to_db = mock_save

    result = agent.call_hot_lead("lead_test_001")

    assert result["success"] is True
    assert result["call_id"] == "CA_test_123"
    mock_twilio.make_outbound_call.assert_called_once()
    # Vérifie que l'URL TwiML contient bien le lead_id
    call_args = mock_twilio.make_outbound_call.call_args
    assert "lead_test_001" in call_args.kwargs.get("twiml_url", "") or \
           "lead_test_001" in str(call_args)
    mock_save.assert_called_once_with(
        lead_id="lead_test_001",
        call_id="CA_test_123",
        direction="outbound",
        statut="registered",
    )


def test_call_hot_lead_low_score(monkeypatch):
    """Un lead avec score < 7 ne doit pas générer d'appel."""
    lead = _make_lead(score=5)
    monkeypatch.setattr("agents.voice_call.get_lead", lambda lid: lead)

    from agents.voice_call import VoiceCallAgent
    agent = VoiceCallAgent(client_id="test_client", tier="Starter")
    result = agent.call_hot_lead("lead_test_001")

    assert result["success"] is False
    assert "score" in result["message"].lower() or "faible" in result["message"].lower()


def test_call_hot_lead_no_telephone(monkeypatch):
    """Un lead sans téléphone ne doit pas générer d'appel."""
    lead = _make_lead(telephone="")
    monkeypatch.setattr("agents.voice_call.get_lead", lambda lid: lead)

    from agents.voice_call import VoiceCallAgent
    agent = VoiceCallAgent(client_id="test_client", tier="Starter")
    result = agent.call_hot_lead("lead_test_001")

    assert result["success"] is False


def test_call_hot_lead_limit_reached(monkeypatch):
    """Si quota voix dépassé, l'appel ne doit pas se déclencher."""
    lead = _make_lead(score=9)
    monkeypatch.setattr("agents.voice_call.get_lead", lambda lid: lead)
    monkeypatch.setattr(
        "agents.voice_call.check_and_consume",
        lambda *a, **kw: {"allowed": False, "message": "Limite voix atteinte"},
    )

    from agents.voice_call import VoiceCallAgent
    agent = VoiceCallAgent(client_id="test_client", tier="Starter")
    result = agent.call_hot_lead("lead_test_001")

    assert result["success"] is False
    assert result.get("limit_reached") is True


def test_no_retell_import():
    """VoiceCallAgent ne doit plus importer RetellTool."""
    import ast
    from pathlib import Path
    src = Path("agents/voice_call.py").read_text()
    assert "RetellTool" not in src or "from tools.retell_tool import RetellTool" not in src
