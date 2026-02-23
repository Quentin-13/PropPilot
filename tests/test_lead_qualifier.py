"""
Tests unitaires — LeadQualifierAgent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from memory.database import init_database
from memory.models import LeadStatus, NurturingSequence, ProjetType
from agents.lead_qualifier import LeadQualifierAgent


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Utilise une DB temporaire pour les tests."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", "test_client")
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    monkeypatch.setenv("AGENCY_NAME", "Test Agence")
    monkeypatch.setenv("MOCK_MODE", "always")

    # Reset cache settings
    from config.settings import get_settings
    get_settings.cache_clear()

    init_database()
    yield

    get_settings.cache_clear()


def test_handle_new_lead_creates_lead():
    """Un nouveau lead doit être créé en base."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    result = agent.handle_new_lead(
        telephone="+33600000001",
        message_initial="Je veux acheter un appartement",
        prenom="Test",
    )

    assert result["status"] == "new_lead"
    assert result["lead_id"] is not None
    assert result["message"] != ""
    assert "Sophie" in result["message"] or "MOCK" in result["message"] or "Bonjour" in result["message"]


def test_handle_new_lead_with_prenom():
    """Message de bienvenue doit inclure le prénom."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    result = agent.handle_new_lead(
        telephone="+33600000002",
        message_initial="Bonjour",
        prenom="Marie",
    )

    assert result["status"] == "new_lead"
    assert "Marie" in result["message"]


def test_handle_new_lead_limit_reached(monkeypatch):
    """Doit bloquer si la limite de leads est atteinte."""
    # Simuler usage au max
    def mock_check_and_consume(*args, **kwargs):
        return {
            "allowed": False,
            "message": "Limite atteinte",
            "remaining": 0,
            "upgrade_url": "",
        }

    monkeypatch.setattr("agents.lead_qualifier.check_and_consume", mock_check_and_consume)

    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")
    result = agent.handle_new_lead(
        telephone="+33600000003",
        message_initial="Test",
    )

    assert result["status"] == "limit_reached"
    assert result["lead_id"] is None


def test_handle_incoming_message_continues_qualification():
    """Le message entrant continue la qualification."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    # Créer d'abord le lead
    new_result = agent.handle_new_lead(
        telephone="+33600000004",
        message_initial="Bonjour",
    )
    lead_id = new_result["lead_id"]

    # Réponse au premier message
    result = agent.handle_incoming_message(
        lead_id=lead_id,
        message="Je veux acheter un appartement 3 pièces à Lyon",
    )

    assert result["message"] != ""
    assert result["next_action"] in ("continue", "rdv", "nurturing_14j", "nurturing_30j")


def test_scoring_routes_hot_lead():
    """Score ≥ 7 → statut qualifié."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 8,
        "score_urgence": 4,
        "score_budget": 2,
        "score_motivation": 2,
        "projet": "achat",
        "localisation": "Lyon 6e",
        "budget": "400 000€",
        "timeline": "3 mois",
        "financement": "Accord bancaire",
        "motivation": "Mutation",
        "prochaine_action": "rdv",
        "resume": "Lead chaud, mutation professionnelle.",
    }

    from memory.lead_repository import create_lead, get_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Pierre", telephone="+33600000005")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 8
    assert result_lead.statut == LeadStatus.QUALIFIE
    assert result_lead.nurturing_sequence is None


def test_scoring_routes_warm_lead():
    """Score 4-6 → nurturing 14j."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 5,
        "score_urgence": 2,
        "score_budget": 1,
        "score_motivation": 2,
        "projet": "achat",
        "localisation": "Paris",
        "budget": "250 000€",
        "timeline": "6-12 mois",
        "financement": "Pas encore",
        "motivation": "Achat résidence principale",
        "prochaine_action": "nurturing_14j",
        "resume": "Lead tiède.",
    }

    from memory.lead_repository import create_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Julie", telephone="+33600000006")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 5
    assert result_lead.statut == LeadStatus.NURTURING
    assert result_lead.nurturing_sequence is not None
    assert result_lead.prochain_followup is not None


def test_scoring_routes_cold_lead():
    """Score < 4 → nurturing 30j avec séquence lead_froid."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 2,
        "score_urgence": 1,
        "score_budget": 0,
        "score_motivation": 1,
        "projet": "inconnu",
        "localisation": None,
        "budget": None,
        "timeline": "Pas décidé",
        "financement": "Inconnu",
        "motivation": "Curiosité",
        "prochaine_action": "nurturing_30j",
        "resume": "Lead froid.",
    }

    from memory.lead_repository import create_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Marc", telephone="+33600000007")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 2
    assert result_lead.statut == LeadStatus.NURTURING
    assert result_lead.nurturing_sequence == NurturingSequence.LEAD_FROID
