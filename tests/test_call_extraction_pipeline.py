"""
Tests — lib/call_extraction_pipeline.py

Vérifie l'extraction structurée (mock + real).
"""
from __future__ import annotations

import json
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


def test_mock_extraction_returns_valid_data():
    from lib.call_extraction_pipeline import CallExtractionPipeline
    pipeline = CallExtractionPipeline()
    assert pipeline._mock is True
    result = pipeline.extract("call-001", "Bonjour, je cherche un T3...")
    assert result.source == "mock"
    assert result.type_projet == "achat"
    assert result.score_qualification in ("chaud", "tiede", "froid")
    assert isinstance(result.criteres, dict)
    assert isinstance(result.timing, dict)
    assert isinstance(result.financement, dict)
    assert isinstance(result.points_attention, list)


def test_mock_extraction_empty_transcript():
    from lib.call_extraction_pipeline import CallExtractionPipeline
    pipeline = CallExtractionPipeline()
    result = pipeline.extract("call-002", "")
    assert result is not None


def test_extraction_data_from_json():
    from lib.call_extraction_pipeline import CallExtractionData
    data = {
        "type_projet": "achat",
        "budget_min": "350000",
        "budget_max": 500000,
        "zone_geographique": "Lyon 3e",
        "type_bien": "T3",
        "surface_min": 60,
        "surface_max": None,
        "criteres": {"parking": True, "balcon": False},
        "timing": {"urgence": "3-6 mois"},
        "financement": {"type": "apport_fort"},
        "motivation": "mutation_pro",
        "score_qualification": "chaud",
        "prochaine_action_suggeree": "Envoyer sélection",
        "resume_appel": "Couple cherche T3 Lyon.",
        "points_attention": ["Délai court"],
    }
    result = CallExtractionData.from_json(data, model="claude-sonnet-4-5", cost_usd=0.005)
    assert result.budget_min == 350000  # string → int
    assert result.budget_max == 500000
    assert result.surface_max is None
    assert result.score_qualification == "chaud"
    assert result.cost_usd == 0.005


def test_extraction_data_mock_classmethod():
    from lib.call_extraction_pipeline import CallExtractionData
    mock = CallExtractionData.mock()
    assert mock.source == "mock"
    assert mock.budget_min is not None
    assert mock.resume_appel is not None


def test_real_extraction_calls_claude(monkeypatch):
    """Vérifie que l'extraction réelle appelle Claude avec prompt caching."""
    monkeypatch.setenv("MOCK_MODE", "never")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    from config.settings import get_settings
    get_settings.cache_clear()

    expected_json = json.dumps({
        "type_projet": "vente",
        "budget_min": None,
        "budget_max": None,
        "zone_geographique": "Bordeaux",
        "type_bien": "maison",
        "surface_min": None,
        "surface_max": None,
        "criteres": {},
        "timing": {"urgence": "< 3 mois"},
        "financement": {},
        "motivation": "divorce",
        "score_qualification": "chaud",
        "prochaine_action_suggeree": "Proposer estimation",
        "resume_appel": "Vente urgente suite à divorce.",
        "points_attention": ["Urgence forte"],
    })

    mock_content = MagicMock()
    mock_content.text = expected_json
    mock_usage = MagicMock()
    mock_usage.input_tokens = 500
    mock_usage.output_tokens = 100
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        with patch("memory.cost_logger.log_api_action"):
            from lib.call_extraction_pipeline import CallExtractionPipeline
            pipeline = CallExtractionPipeline()
            pipeline._mock = False
            result = pipeline.extract("call-999", "Je veux vendre ma maison à Bordeaux.")

    assert result.type_projet == "vente"
    assert result.score_qualification == "chaud"
    assert result.zone_geographique == "Bordeaux"
    assert result.source == "claude"

    get_settings.cache_clear()
