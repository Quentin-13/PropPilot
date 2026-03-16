"""
Tests — JourneyRepository (log_action, get_journey, get_pending_actions).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta


def test_log_action_and_get_journey(_reset_db_between_tests):
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    from memory.lead_repository import create_lead
    from memory.models import Lead
    from memory.journey_repository import log_action, get_journey

    lead = create_lead(Lead(client_id="test_client", telephone="+33600000001"))

    log_action(
        lead_id=lead.id,
        client_id="test_client",
        stage="qualification",
        action_done="new_lead_created",
        action_result="bienvenue !",
        agent_name="lea",
    )
    log_action(
        lead_id=lead.id,
        client_id="test_client",
        stage="qualification",
        action_done="message_sent",
        action_result="question posée",
        agent_name="lea",
        metadata={"score": 0},
    )

    journey = get_journey(lead.id)
    assert len(journey) == 2
    assert journey[0]["action_done"] == "new_lead_created"
    assert journey[1]["action_done"] == "message_sent"
    assert journey[1]["metadata"] == {"score": 0}
    assert journey[0]["stage"] == "qualification"
    assert journey[0]["agent_name"] == "lea"


def test_get_journey_empty(_reset_db_between_tests):
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    from memory.journey_repository import get_journey
    result = get_journey("nonexistent_lead_id")
    assert result == []


def test_get_pending_actions(_reset_db_between_tests):
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    from memory.lead_repository import create_lead
    from memory.models import Lead
    from memory.journey_repository import log_action, get_pending_actions

    lead = create_lead(Lead(client_id="test_client_pending", telephone="+33600000002"))

    past_time = datetime.now() - timedelta(hours=1)
    future_time = datetime.now() + timedelta(hours=2)

    # Action due (passée)
    log_action(
        lead_id=lead.id,
        client_id="test_client_pending",
        stage="nurturing",
        action_done="followup_scheduled",
        next_action="send_sms",
        next_action_at=past_time,
        agent_name="marc",
    )
    # Action future (ne doit pas apparaître)
    log_action(
        lead_id=lead.id,
        client_id="test_client_pending",
        stage="nurturing",
        action_done="followup_scheduled",
        next_action="send_sms",
        next_action_at=future_time,
        agent_name="marc",
    )
    # Action sans next_action_at (ne doit pas apparaître)
    log_action(
        lead_id=lead.id,
        client_id="test_client_pending",
        stage="qualification",
        action_done="new_lead_created",
        agent_name="lea",
    )

    pending = get_pending_actions("test_client_pending")
    assert len(pending) == 1
    assert pending[0]["next_action"] == "send_sms"
    assert pending[0]["agent_name"] == "marc"


def test_log_action_no_db_does_not_raise(monkeypatch):
    """log_action ne doit jamais lever d'exception même si DB indisponible."""
    from memory.journey_repository import log_action

    def _bad_connect(*a, **kw):
        raise RuntimeError("DB down")

    monkeypatch.setattr("memory.journey_repository.get_connection", _bad_connect)
    # Ne doit pas lever
    log_action(
        lead_id="x",
        client_id="y",
        stage="test",
        action_done="noop",
    )
