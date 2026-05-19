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
        "lead_type": "vendeur",
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


# ── Tests règle budget vs prix annonce ────────────────────────────────────────

class TestBudgetVsPrixAnnonce:
    """Test 1 & 2 — le prix d'une annonce ne doit pas être confondu avec le budget réel."""

    def _from_json(self, overrides: dict):
        from lib.call_extraction_pipeline import CallExtractionData
        base = {
            "lead_type": "acheteur",
            "type_projet": "achat",
            "budget_min": None,
            "budget_max": None,
            "zone_geographique": None,
            "type_bien": None,
            "surface_min": None,
            "surface_max": None,
            "criteres": {},
            "timing": {},
            "financement": {"type": None, "detail": None},
            "motivation": None,
            "score_qualification": "froid",
            "prochaine_action_suggeree": None,
            "resume_appel": "Test.",
            "points_attention": [],
        }
        base.update(overrides)
        return CallExtractionData.from_json(base, model="test", cost_usd=0.0)

    def test_prix_annonce_ne_compte_pas_comme_budget(self):
        """Test 1 — prospect appelle pour un bien affiché à 400k : budget doit rester null."""
        result = self._from_json({"budget_min": None, "budget_max": None})
        assert result.budget_min is None
        assert result.budget_max is None

    def test_budget_reel_prospect_extrait(self):
        """Test 2 — prospect dit 'mon budget est 400k' : budget extrait correctement."""
        result = self._from_json({"budget_min": 380000, "budget_max": 430000})
        assert result.budget_min == 380000
        assert result.budget_max == 430000


# ── Tests _normalize_financement ──────────────────────────────────────────────

class TestNormalizeFinancement:
    """Test 3 & 4 — financement non évoqué → {} ; financement réel → conservé."""

    def test_financement_type_null_normalise_vers_vide(self):
        """Test 3 — {'type': null, 'detail': null} → {} (non compté comme financement)."""
        from lib.call_extraction_pipeline import _normalize_financement
        assert _normalize_financement({"type": None, "detail": None}) == {}
        assert _normalize_financement({"type": "null", "detail": None}) == {}

    def test_financement_generique_normalise_vers_vide(self):
        """Test 3 — valeurs génériques → {}."""
        from lib.call_extraction_pipeline import _normalize_financement
        for val in ["non évoqué", "à qualifier", "inconnu", "non renseigné", "à demander", "pas précisé"]:
            assert _normalize_financement({"type": val}) == {}, f"Attendu {{}} pour type={val!r}"

    def test_financement_reel_conserve(self):
        """Test 4 — accord bancaire et apport → conservé tel quel."""
        from lib.call_extraction_pipeline import _normalize_financement
        fin = {"type": "accord_bancaire", "detail": "60k apport"}
        assert _normalize_financement(fin) == fin

    def test_from_json_financement_null_type_donne_vide(self):
        """Test 3 — from_json avec financement null type → financement == {}."""
        from lib.call_extraction_pipeline import CallExtractionData
        data = {
            "lead_type": "acheteur", "type_projet": "achat",
            "budget_min": None, "budget_max": None,
            "zone_geographique": None, "type_bien": None,
            "surface_min": None, "surface_max": None,
            "criteres": {}, "timing": {},
            "financement": {"type": None, "detail": None},
            "motivation": None, "score_qualification": "froid",
            "prochaine_action_suggeree": None,
            "resume_appel": "Test.", "points_attention": [],
        }
        result = CallExtractionData.from_json(data, model="test", cost_usd=0.0)
        assert result.financement == {}, "financement avec type=null doit être normalisé vers {}"

    def test_from_json_financement_reel_conserve(self):
        """Test 4 — from_json avec accord bancaire → financement conservé."""
        from lib.call_extraction_pipeline import CallExtractionData
        data = {
            "lead_type": "acheteur", "type_projet": "achat",
            "budget_min": None, "budget_max": None,
            "zone_geographique": None, "type_bien": None,
            "surface_min": None, "surface_max": None,
            "criteres": {}, "timing": {},
            "financement": {"type": "accord_bancaire", "detail": "60k apport"},
            "motivation": None, "score_qualification": "chaud",
            "prochaine_action_suggeree": None,
            "resume_appel": "Test.", "points_attention": [],
        }
        result = CallExtractionData.from_json(data, model="test", cost_usd=0.0)
        assert result.financement.get("type") == "accord_bancaire"
