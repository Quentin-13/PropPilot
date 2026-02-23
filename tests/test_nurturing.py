"""
Tests unitaires — NurturingAgent.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.database import init_database
from memory.models import Canal, Lead, LeadStatus, NurturingSequence, ProjetType
from memory.lead_repository import create_lead, get_lead
from agents.nurturing import NurturingAgent


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AGENCY_CLIENT_ID", "test_client")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


def make_nurturing_lead(
    sequence: NurturingSequence,
    step: int = 0,
    days_overdue: int = 0,
    telephone: str = "+33600111001",
) -> Lead:
    """Helper : crée un lead en nurturing avec follow-up dû."""
    lead = Lead(
        client_id="test_client",
        prenom="Test",
        nom="Nurturing",
        telephone=telephone,
        email="test@test.fr",
        source=Canal.SMS,
        projet=ProjetType.ACHAT,
        localisation="Lyon",
        budget="300 000€",
        score=6,
        statut=LeadStatus.NURTURING,
        nurturing_sequence=sequence,
        nurturing_step=step,
        prochain_followup=datetime.now() - timedelta(hours=days_overdue * 24 + 1),
    )
    return create_lead(lead)


def test_send_followup_mock():
    """Le mock doit envoyer un message sans erreur."""
    lead = make_nurturing_lead(NurturingSequence.ACHETEUR_QUALIFIE, step=0, days_overdue=2)
    agent = NurturingAgent(client_id="test_client", tier="Starter")

    result = agent.send_followup(lead)

    assert result["sent"] is True
    assert result["canal"] in ("sms", "whatsapp", "email")
    assert result["message"] != ""


def test_send_followup_advances_step():
    """Envoi réussi doit incrémenter le step."""
    lead = make_nurturing_lead(NurturingSequence.VENDEUR_CHAUD, step=0, days_overdue=1)
    agent = NurturingAgent(client_id="test_client", tier="Starter")

    agent.send_followup(lead)

    updated_lead = get_lead(lead.id)
    assert updated_lead.nurturing_step == 1


def test_send_followup_sets_next_date():
    """Après envoi, prochain_followup doit être mis à jour."""
    lead = make_nurturing_lead(NurturingSequence.ACHETEUR_QUALIFIE, step=0, days_overdue=2)
    agent = NurturingAgent(client_id="test_client", tier="Starter")

    agent.send_followup(lead)

    updated_lead = get_lead(lead.id)
    assert updated_lead.prochain_followup is not None
    assert updated_lead.prochain_followup > datetime.now()


def test_sequence_terminee_archives_lead():
    """Quand la séquence est terminée, le lead doit être archivé."""
    from agents.nurturing import SEQUENCES

    # Step = dernier de la séquence
    seq = NurturingSequence.LEAD_FROID
    last_step = len(SEQUENCES[seq])
    lead = make_nurturing_lead(seq, step=last_step, days_overdue=1, telephone="+33600111999")

    agent = NurturingAgent(client_id="test_client", tier="Starter")
    result = agent.send_followup(lead)

    assert result["sent"] is False
    assert result["reason"] == "sequence_terminee"

    updated_lead = get_lead(lead.id)
    assert updated_lead.statut == LeadStatus.PERDU


def test_requalification_positive_response():
    """Réponse positive à un nurturing doit requalifier le lead."""
    lead = make_nurturing_lead(NurturingSequence.LEAD_FROID, step=1, telephone="+33600111002")
    lead.score = 2
    from memory.lead_repository import update_lead
    update_lead(lead)

    agent = NurturingAgent(client_id="test_client", tier="Starter")
    result = agent.handle_response_requalification(lead.id, "Oui, je suis toujours intéressé !")

    assert result["requalified"] is True
    assert result["new_score"] >= 6

    updated = get_lead(lead.id)
    assert updated.statut == LeadStatus.QUALIFIE


def test_requalification_negative_response():
    """Réponse négative ne doit pas requalifier."""
    lead = make_nurturing_lead(NurturingSequence.LEAD_FROID, step=0, telephone="+33600111003")
    agent = NurturingAgent(client_id="test_client", tier="Starter")

    result = agent.handle_response_requalification(lead.id, "Merci mais je ne suis plus intéressé")

    assert result["requalified"] is False


def test_limit_reached_blocks_followup(monkeypatch):
    """La limite de follow-ups doit bloquer l'envoi."""
    def mock_check(*args, **kwargs):
        return {"allowed": False, "message": "Limite atteinte", "remaining": 0}

    monkeypatch.setattr("agents.nurturing.check_and_consume", mock_check)

    lead = make_nurturing_lead(NurturingSequence.ACHETEUR_QUALIFIE, step=0, days_overdue=1, telephone="+33600111004")
    agent = NurturingAgent(client_id="test_client", tier="Starter")

    result = agent.send_followup(lead)
    assert result["sent"] is False
    assert result.get("reason") == "limit_reached"
