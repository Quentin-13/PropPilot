"""
Tests ElevenLabsTool — synthèse vocale Sophie.
Mode mock automatique quand TESTING=true ou clé absente.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("TESTING", "true")


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

    def test_voice_id_default_is_sophie(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.elevenlabs_voice_id == "EXAVITQu4vr4xnSDxMaL"

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
        assert len(voices) >= 3

    def test_sophie_in_list(self):
        tool = _tool()
        voices = tool.get_available_voices()
        names = [v["name"] for v in voices]
        assert "Sophie" in names


# ─── VoiceCallAgent — synthesize_sophie_intro ─────────────────────────────────

class TestVoiceCallSophie:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_MODE", "always")
        monkeypatch.setenv("AGENCY_NAME", "Agence Martin Immobilier")
        from config.settings import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _agent(self):
        from agents.voice_call import VoiceCallAgent
        return VoiceCallAgent(client_id="test_client", tier="Starter")

    def test_synthesize_sophie_intro_generic(self):
        agent = self._agent()
        result = agent.synthesize_sophie_intro()
        assert result["success"] is True
        assert result["mock"] is True
        assert "Sophie" in result["script"]
        assert "Agence Martin Immobilier" in result["script"]

    def test_synthesize_sophie_intro_with_lead(self):
        from memory.models import Lead, ProjetType
        lead = Lead(
            client_id="test_client",
            prenom="Claire",
            projet=ProjetType.ACHAT,
            localisation="Lyon",
        )
        agent = self._agent()
        result = agent.synthesize_sophie_intro(lead=lead)
        assert "Claire" in result["script"]
        assert "Lyon" in result["script"]
        assert result["success"] is True

    def test_synthesize_sophie_intro_has_duration(self):
        agent = self._agent()
        result = agent.synthesize_sophie_intro()
        assert result["duration_s"] > 0

    def test_sophie_script_is_french_and_professional(self):
        agent = self._agent()
        result = agent.synthesize_sophie_intro()
        script = result["script"]
        # Ton professionnel : présentation + objet de l'appel
        assert "Bonjour" in script
        assert "Sophie" in script
        assert "projet" in script.lower()
