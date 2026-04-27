"""
Tests ElevenLabsTool — synthèse vocale TTS.
Mode mock automatique quand TESTING=true ou clé absente.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("TESTING", "true")

pytestmark = pytest.mark.skip(reason="ElevenLabsTool supprimé — sprint cleanup-pivot step 7")


# ─── Fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _force_testing(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("AUDIO_OUTPUT_DIR", str(tmp_path))
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _tool():
    from tools.elevenlabs_tool import ElevenLabsTool
    return ElevenLabsTool()


# ─── Settings ─────────────────────────────────────────────────────────────────

class TestSettings:
    def test_model_id_default_is_multilingual_v2(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.elevenlabs_model_id == "eleven_multilingual_v2"

    def test_voice_id_default_is_none(self):
        """voice_id est configurable via ELEVENLABS_VOICE_ID, pas de défaut hardcodé."""
        from config.settings import get_settings
        s = get_settings()
        assert s.elevenlabs_voice_id is None  # configurable via env

    def test_model_id_overridable(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.elevenlabs_model_id == "eleven_turbo_v2"
        get_settings.cache_clear()

    def test_voice_id_overridable(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom_voice_id_xyz")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.elevenlabs_voice_id == "custom_voice_id_xyz"
        get_settings.cache_clear()


# ─── Mock mode ────────────────────────────────────────────────────────────────

class TestMockMode:
    def test_mock_mode_active_in_testing(self):
        tool = _tool()
        assert tool.mock_mode is True

    def test_model_attribute_from_settings(self):
        tool = _tool()
        assert tool.model == "eleven_multilingual_v2"

    def test_mock_with_key_present(self, monkeypatch):
        """TESTING=true force le mock même si la clé est présente."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-fake-key-for-test")
        monkeypatch.setenv("TESTING", "true")
        from config.settings import get_settings
        get_settings.cache_clear()
        tool = _tool()
        assert tool.mock_mode is True
        get_settings.cache_clear()


# ─── text_to_speech — phrase de test officielle ───────────────────────────────

class TestTextToSpeech:
    SOPHIE_INTRO = (
        "Bonjour, je suis Sophie, assistante de votre agence immobilière. "
        "J'appelle concernant votre projet immobilier."
    )

    def test_sophie_intro_success(self, tmp_path):
        tool = _tool()
        result = tool.text_to_speech(self.SOPHIE_INTRO, voice_name="sophie")
        assert result["success"] is True
        assert result["mock"] is True

    def test_sophie_intro_duration_estimated(self, tmp_path):
        tool = _tool()
        result = tool.text_to_speech(self.SOPHIE_INTRO, voice_name="sophie")
        assert result["duration_s"] > 0

    def test_sophie_intro_audio_file_created(self, tmp_path):
        tool = _tool()
        out = str(tmp_path / "sophie_intro.mp3")
        result = tool.text_to_speech(self.SOPHIE_INTRO, voice_name="sophie", output_path=out)
        assert result["success"] is True
        assert Path(out).exists()

    def test_sophie_voice_name_in_result(self):
        tool = _tool()
        result = tool.text_to_speech(self.SOPHIE_INTRO, voice_name="sophie")
        assert result["voice"] == "Sophie"

    def test_other_voices_work(self):
        tool = _tool()
        result = tool.text_to_speech("Test voix.", voice_name="thomas")
        assert result["success"] is True

    def test_text_preview_in_result(self):
        tool = _tool()
        result = tool.text_to_speech(self.SOPHIE_INTRO, voice_name="sophie")
        assert "text_preview" in result
        assert "Sophie" in result["text_preview"]

    def test_voice_settings_params_accepted(self):
        """Les 4 paramètres de qualité vocale sont bien acceptés."""
        tool = _tool()
        result = tool.text_to_speech(
            self.SOPHIE_INTRO,
            voice_name="sophie",
            stability=0.5,
            similarity_boost=0.75,
        )
        assert result["success"] is True

    def test_voice_id_uses_settings(self, monkeypatch):
        """Sophie utilise ELEVENLABS_VOICE_ID depuis les settings."""
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom_sophie_id")
        from config.settings import get_settings
        get_settings.cache_clear()
        from tools.elevenlabs_tool import ElevenLabsTool
        tool = ElevenLabsTool()
        assert tool.settings.elevenlabs_voice_id == "custom_sophie_id"
        get_settings.cache_clear()


# ─── synthesize_call_script ───────────────────────────────────────────────────

class TestSynthesizeCallScript:
    def test_returns_list(self):
        tool = _tool()
        parts = [
            {"text": "Bonjour, c'est Sophie.", "pause_after_s": 0.5},
            {"text": "J'appelle pour votre projet immobilier.", "pause_after_s": 1.0},
        ]
        results = tool.synthesize_call_script(parts, voice_name="sophie")
        assert isinstance(results, list)
        assert len(results) == 2

    def test_each_part_has_audio_path(self, tmp_path):
        tool = _tool()
        parts = [{"text": "Bonjour.", "pause_after_s": 0.5}]
        results = tool.synthesize_call_script(parts, voice_name="sophie", output_dir=str(tmp_path))
        assert results[0]["audio_path"] != ""
        assert results[0]["success"] is True

    def test_pause_after_preserved(self):
        tool = _tool()
        parts = [{"text": "Test.", "pause_after_s": 2.0}]
        results = tool.synthesize_call_script(parts)
        assert results[0]["pause_after_s"] == 2.0


# ─── get_available_voices ─────────────────────────────────────────────────────

class TestGetAvailableVoices:
    def test_returns_list_in_mock(self):
        tool = _tool()
        voices = tool.get_available_voices()
        assert isinstance(voices, list)
        assert len(voices) >= 2

    def test_sophie_in_list(self):
        tool = _tool()
        voices = tool.get_available_voices()
        names = [v["name"] for v in voices]
        assert "Sophie" in names


# ─── VoiceInboundAgent — appels entrants ──────────────────────────────────────

@pytest.mark.skip(reason="VoiceInboundAgent supprimé — sprint cleanup-pivot step 5")
class TestVoiceInboundAgent:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("MOCK_MODE", "always")
        monkeypatch.setenv("AGENCY_NAME", "Agence Martin Immobilier")
        from config.settings import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_agent_instantiates(self):
        from agents.voice_inbound import VoiceInboundAgent
        agent = VoiceInboundAgent(client_id="test_client", tier="Starter")
        assert agent.client_id == "test_client"

    def test_process_call_ended_no_transcript(self):
        """process_call_ended avec lead inexistant → erreur propre (nécessite PostgreSQL)."""
        pytest.skip("Requiert PostgreSQL")

    def test_no_outbound_calls(self):
        """VoiceInboundAgent ne doit pas avoir de méthode call_hot_lead."""
        from agents.voice_inbound import VoiceInboundAgent
        assert not hasattr(VoiceInboundAgent, "call_hot_lead")
