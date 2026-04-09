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


def test_call_hot_lead_disabled():
    """call_hot_lead retourne disabled — appels sortants supprimés (archi 1 numéro 06/07)."""
    from agents.voice_call import VoiceCallAgent
    agent = VoiceCallAgent(client_id="test_client", tier="Starter")
    result = agent.call_hot_lead("lead_test_001")
    assert result["success"] is False
    assert "sortant" in result["message"].lower() or "06/07" in result["message"].lower()


def test_no_retell_import():
    """VoiceCallAgent ne doit plus importer RetellTool."""
    import ast
    from pathlib import Path
    src = Path("agents/voice_call.py").read_text()
    assert "RetellTool" not in src or "from tools.retell_tool import RetellTool" not in src
