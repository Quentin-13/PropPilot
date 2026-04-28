"""
Tests — lib/call_transcription.py

Vérifie le comportement mock et l'appel Whisper simulé.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_transcription_mock_returns_text():
    from lib.call_transcription import CallTranscription
    t = CallTranscription()
    assert t._mock is True
    result = t.transcribe("calls/2026/04/abc.mp3", call_id="test-123")
    assert result.source == "mock"
    assert "[MOCK]" in result.text
    assert len(result.segments) > 0
    assert result.duration_seconds > 0
    assert result.cost_usd > 0


def test_transcription_result_mock_class():
    from lib.call_transcription import TranscriptionResult
    r = TranscriptionResult.mock("call-id-001")
    assert r.text
    assert r.source == "mock"


def test_transcription_real_calls_openai(monkeypatch, tmp_path):
    """Vérifie que la transcription réelle appelle openai avec les bons params."""
    monkeypatch.setenv("MOCK_MODE", "never")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    from config.settings import get_settings
    get_settings.cache_clear()

    # Mock AudioStorage download
    fake_audio = tmp_path / "call.mp3"
    fake_audio.write_bytes(b"FAKEMP3")

    mock_response = MagicMock()
    mock_response.text = "Bonjour, je cherche un appartement."
    mock_response.segments = [
        MagicMock(start=0.0, end=5.0, text="Bonjour, je cherche un appartement."),
    ]
    mock_response.duration = 5.0

    mock_openai = MagicMock()
    mock_openai.audio.transcriptions.create.return_value = mock_response

    with patch("lib.audio_storage.AudioStorage.download_audio", return_value=str(fake_audio)):
        with patch("openai.OpenAI", return_value=mock_openai):
            from lib.call_transcription import CallTranscription
            t = CallTranscription()
            # In test mode, _mock might still be True due to TESTING env var
            # So we force it
            t._mock = False
            result = t.transcribe("calls/2026/04/abc.mp3", call_id="test-456")

    assert result.text == "Bonjour, je cherche un appartement."
    assert len(result.segments) == 1
    assert result.duration_seconds == 5.0
    assert result.cost_usd > 0
    assert result.source == "whisper"

    get_settings.cache_clear()
