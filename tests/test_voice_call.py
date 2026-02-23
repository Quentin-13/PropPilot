"""
Tests unitaires — VoiceCallAgent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from memory.database import init_database
from memory.models import Lead, LeadStatus, ProjetType
from agents.voice_call import VoiceCallAgent


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", "test_client")
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


def make_lead(score: int = 8, telephone: str = "+33600000001") -> Lead:
    """Crée et persiste un lead de test."""
    from memory.lead_repository import create_lead
    lead = Lead(
        client_id="test_client",
        prenom="Antoine",
        telephone=telephone,
        projet=ProjetType.ACHAT,
        score=score,
        score_budget=2,
        localisation="Bordeaux",
        budget="380 000€",
        statut=LeadStatus.QUALIFIE,
    )
    return create_lead(lead)


def make_agent(tier="Starter"):
    return VoiceCallAgent(client_id="test_client", tier=tier)


def test_call_hot_lead_no_phone():
    """Lead sans téléphone → échec."""
    from memory.lead_repository import create_lead
    lead = Lead(client_id="test_client", prenom="Test", score=8)
    lead = create_lead(lead)

    agent = make_agent()
    result = agent.call_hot_lead(lead.id)

    assert result["success"] is False
    assert "téléphone" in result["message"].lower()


def test_call_hot_lead_score_too_low():
    """Score < 7 → refus d'appel."""
    lead = make_lead(score=5)
    agent = make_agent()
    result = agent.call_hot_lead(lead.id)

    assert result["success"] is False
    assert "score" in result["message"].lower() or "faible" in result["message"].lower()


def test_call_hot_lead_inexistant():
    """Lead inexistant → échec propre."""
    agent = make_agent()
    result = agent.call_hot_lead("lead_inexistant_xxx")

    assert result["success"] is False
    assert "introuvable" in result["message"].lower()


def test_call_hot_lead_success_mock():
    """Appel vers lead chaud en mode mock → succès."""
    lead = make_lead(score=8, telephone="+33611223344")
    agent = make_agent()
    result = agent.call_hot_lead(lead.id)

    assert result["success"] is True
    assert "call_id" in result
    assert len(result.get("call_id", "")) > 0


def test_call_hot_lead_saves_to_db():
    """Un appel réussi doit être sauvegardé en base."""
    lead = make_lead(score=8, telephone="+33611223345")
    agent = make_agent()
    result = agent.call_hot_lead(lead.id)

    assert result["success"] is True

    from memory.database import get_connection
    with get_connection() as conn:
        call_row = conn.execute(
            "SELECT * FROM calls WHERE lead_id = ?", (lead.id,)
        ).fetchone()

    assert call_row is not None
    assert call_row["direction"] == "outbound"


def test_call_hot_lead_quota_exceeded():
    """Quota voix dépassé → refus."""
    from memory.usage_tracker import check_and_consume
    from config.tier_limits import TIERS

    limit = TIERS["Starter"].minutes_voix_par_mois
    check_and_consume("test_client", "voice_minute", amount=float(limit), tier="Starter")

    lead = make_lead(score=8, telephone="+33611223346")
    agent = make_agent(tier="Starter")
    result = agent.call_hot_lead(lead.id)

    assert result["success"] is False
    assert result.get("limit_reached") is True


def test_call_leads_not_responded_returns_list():
    """call_leads_not_responded retourne une liste."""
    agent = make_agent()
    results = agent.call_leads_not_responded(min_score=7, sms_delay_min=0)

    assert isinstance(results, list)


def test_get_calls_history_returns_list():
    """L'historique des appels retourne une liste."""
    agent = make_agent()
    calls = agent.get_calls_history(limit=10)

    assert isinstance(calls, list)


def test_analyze_call_transcript_mock():
    """L'analyse sans Claude retourne des valeurs par défaut."""
    lead = make_lead(score=6)
    agent = make_agent()

    summary, post_score, rdv_detected, anomalies = agent._analyze_call_transcript(
        transcript="",
        lead=lead,
        analysis={"call_summary": "Appel de qualification réussi"},
    )

    assert isinstance(summary, str)
    assert isinstance(post_score, int)
    assert isinstance(rdv_detected, bool)
    assert isinstance(anomalies, list)


def test_analyze_call_transcript_rdv_detection():
    """Détecte un RDV mentionné dans la transcription."""
    lead = make_lead(score=7)
    agent = make_agent()

    summary, post_score, rdv_detected, anomalies = agent._analyze_call_transcript(
        transcript="Oui je suis disponible, on peut prendre un rendez-vous mardi matin.",
        lead=lead,
        analysis={},
    )

    assert rdv_detected is True


def test_process_call_ended_lead_inexistant():
    """process_call_ended avec lead inexistant → erreur propre."""
    agent = make_agent()
    result = agent.process_call_ended(call_id="call_test_xxx", lead_id="lead_inexistant_xxx")

    assert result.get("lead_updated") is False
    assert "error" in result
