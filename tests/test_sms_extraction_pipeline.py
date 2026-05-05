"""
Tests — lib/sms_extraction_pipeline.py

Vérifie l'extraction structurée SMS (mock + comportements limites).
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_messages(*bodies, role="user"):
    """Crée une liste de messages SMS minimale pour les tests."""
    return [
        {"role": role, "contenu": body, "created_at": datetime(2026, 5, 5, 10, i)}
        for i, body in enumerate(bodies)
    ]


def _make_response(data: dict) -> MagicMock:
    """Simule une réponse Anthropic avec le JSON donné."""
    content = MagicMock()
    content.text = json.dumps(data)
    response = MagicMock()
    response.content = [content]
    response.usage.input_tokens = 500
    response.usage.output_tokens = 200
    return response


_VALID_EXTRACTION = {
    "type_projet": "achat",
    "budget_min": None,
    "budget_max": 350000,
    "zone_geographique": "Lyon 6",
    "type_bien": "T3",
    "surface_min": None,
    "surface_max": None,
    "criteres": {"parking": None, "jardin": None, "ascenseur": None,
                 "balcon": None, "terrasse": None, "garage": None,
                 "cave": None, "autres": []},
    "timing": {"urgence": "3-6 mois", "echeance_souhaitee": None},
    "financement": {"type": None, "detail": None},
    "motivation": "premier_achat",
    "score_qualification": "tiede",
    "prochaine_action_suggeree": "Envoyer sélection T3 Lyon 6",
    "resume_appel": "Prospect cherche un T3 à Lyon 6, budget 350k€, délai 3-6 mois.",
    "points_attention": ["Financement non précisé"],
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_thread_returns_none():
    """Un thread vide retourne None sans appeler Claude."""
    from lib.sms_extraction_pipeline import SmsExtractionPipeline

    with patch("lib.sms_extraction_pipeline.SmsExtractionPipeline.__init__", return_value=None):
        pipeline = SmsExtractionPipeline.__new__(SmsExtractionPipeline)
        pipeline._mock = False
        pipeline._settings = MagicMock()

        result = pipeline.extract(lead_id="lead-001", messages=[])

    assert result is None


def test_mock_mode_returns_mock_data():
    """En mode mock, le pipeline retourne CallExtractionData.mock() sans appel réseau."""
    from lib.sms_extraction_pipeline import SmsExtractionPipeline, SMS_EXTRACTION_PROMPT_VERSION
    from lib.call_extraction_pipeline import CallExtractionData

    with patch("lib.sms_extraction_pipeline.SmsExtractionPipeline.__init__", return_value=None):
        pipeline = SmsExtractionPipeline.__new__(SmsExtractionPipeline)
        pipeline._mock = True
        pipeline._settings = MagicMock()

        messages = _make_messages("Je cherche un T3 à Lyon 6, budget 350k")
        result = pipeline.extract(lead_id="lead-001", messages=messages)

    assert result is not None
    assert isinstance(result, CallExtractionData)
    assert result.extraction_prompt_version == SMS_EXTRACTION_PROMPT_VERSION
    assert result.source == "mock"


def test_extract_parses_realistic_thread(monkeypatch):
    """Un thread réaliste avec budget + zone + type retourne les bons champs."""
    from lib.sms_extraction_pipeline import SmsExtractionPipeline, SMS_EXTRACTION_PROMPT_VERSION
    from lib.call_extraction_pipeline import CallExtractionData

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_response(_VALID_EXTRACTION)

    monkeypatch.setattr(
        "lib.sms_extraction_pipeline.SmsExtractionPipeline.__init__",
        lambda self: None,
    )
    pipeline = SmsExtractionPipeline.__new__(SmsExtractionPipeline)
    pipeline._mock = False
    pipeline._settings = MagicMock(
        claude_model="claude-sonnet-4-5",
        anthropic_api_key="test-key",
    )

    messages = [
        {"role": "user", "contenu": "Bonjour, je cherche un T3 à Lyon 6, budget 350k€",
         "created_at": datetime(2026, 5, 5, 10, 0)},
        {"role": "assistant", "contenu": "Bonjour ! Quel est votre délai ?",
         "created_at": datetime(2026, 5, 5, 10, 5)},
        {"role": "user", "contenu": "Dans 3 à 6 mois idéalement",
         "created_at": datetime(2026, 5, 5, 10, 8)},
    ]

    with patch("anthropic.Anthropic", return_value=mock_client), \
         patch("memory.cost_logger.log_api_action"):
        result = pipeline.extract(lead_id="lead-001", messages=messages)

    assert isinstance(result, CallExtractionData)
    assert result.budget_max == 350000
    assert result.zone_geographique == "Lyon 6"
    assert result.type_bien == "T3"
    assert result.score_qualification == "tiede"
    assert result.extraction_prompt_version == SMS_EXTRACTION_PROMPT_VERSION


def test_extract_handles_invalid_json(monkeypatch):
    """Si Claude retourne du JSON invalide, le pipeline retourne mock_fallback sans crash."""
    from lib.sms_extraction_pipeline import SmsExtractionPipeline

    bad_response = MagicMock()
    bad_content = MagicMock()
    bad_content.text = "Ce n'est pas du JSON valide { broken"
    bad_response.content = [bad_content]
    bad_response.usage.input_tokens = 100
    bad_response.usage.output_tokens = 10

    mock_client = MagicMock()
    mock_client.messages.create.return_value = bad_response

    pipeline = SmsExtractionPipeline.__new__(SmsExtractionPipeline)
    pipeline._mock = False
    pipeline._settings = MagicMock(
        claude_model="claude-sonnet-4-5",
        anthropic_api_key="test-key",
    )

    messages = _make_messages("Bonjour, je cherche un appartement")

    with patch("anthropic.Anthropic", return_value=mock_client), \
         patch("memory.cost_logger.log_api_action"):
        result = pipeline.extract(lead_id="lead-002", messages=messages)

    assert result is not None
    assert result.source == "mock_fallback"


def test_format_thread_ordering():
    """_format_thread ordonne et formatte correctement les messages."""
    from lib.sms_extraction_pipeline import _format_thread

    messages = [
        {"role": "user", "contenu": "Bonjour", "created_at": datetime(2026, 5, 5, 9, 0)},
        {"role": "assistant", "contenu": "Bonjour !", "created_at": datetime(2026, 5, 5, 9, 5)},
    ]
    result = _format_thread(messages)

    assert "Prospect : Bonjour" in result
    assert "Conseiller : Bonjour !" in result
    assert result.index("Prospect") < result.index("Conseiller")
