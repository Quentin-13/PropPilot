"""
Tests — logique de dates dans lib/lead_extraction/next_action.py

Couverture :
  1. _sanitize_deadline rejette les dates passées
  2. _sanitize_deadline accepte les dates futures
  3. _build_prompt injecte la date actuelle dans le prompt
  4. _build_context inclut current_date et current_year
  5. Deadline passée générée par le LLM → ignorée (None) dans compute_next_action
  6. Lead refroidi → priorité basse, pas urgence haute
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── 1. _sanitize_deadline — date passée → None ───────────────────────────────

def test_sanitize_deadline_past_returns_none():
    from lib.lead_extraction.next_action import _sanitize_deadline
    past = datetime.now() - timedelta(days=1)
    assert _sanitize_deadline(past) is None


def test_sanitize_deadline_far_past_returns_none():
    """'début janvier 2026' quand on est en mai 2026 → doit être rejeté."""
    from lib.lead_extraction.next_action import _sanitize_deadline
    janvier_2026 = datetime(2026, 1, 10, 9, 0, 0)
    # On simule qu'on est en mai 2026 (la date actuelle dans les tests peut varier,
    # mais janvier 2026 est bien dans le passé si on est >= février 2026)
    now = datetime.now()
    if now > janvier_2026:
        assert _sanitize_deadline(janvier_2026) is None
    else:
        pytest.skip("Ce test n'est pertinent qu'après janvier 2026")


def test_sanitize_deadline_future_returned_unchanged():
    from lib.lead_extraction.next_action import _sanitize_deadline
    future = datetime.now() + timedelta(days=30)
    result = _sanitize_deadline(future)
    assert result is not None
    assert abs((result - future).total_seconds()) < 1


def test_sanitize_deadline_none_returns_none():
    from lib.lead_extraction.next_action import _sanitize_deadline
    assert _sanitize_deadline(None) is None


# ─── 2. _build_context inclut current_date et current_year ───────────────────

def test_build_context_includes_current_date(monkeypatch):
    from lib.lead_extraction import next_action as na_module

    lead_row = {
        "id": "lead-test",
        "client_id": "client-test",
        "prenom": "Claire",
        "nom": "Dupont",
        "projet": "achat",
        "score": 5,
        "statut": "nurturing",
        "motivation": "",
        "created_at": datetime.now(),
    }

    monkeypatch.setattr(na_module, "_latest_activity_at", lambda lid: None)

    # Mocker les appels DB internes à _build_context
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("lib.lead_extraction.next_action.get_conversation_history", return_value=[], create=True):
        with patch("memory.database.get_connection", return_value=mock_conn):
            from lib.lead_extraction.next_action import _build_context
            ctx = _build_context(lead_row, "lead-test")

    assert "current_date" in ctx
    assert "current_year" in ctx
    assert ctx["current_year"] == datetime.now().year
    # Format attendu : JJ/MM/AAAA
    assert len(ctx["current_date"]) == 10
    assert ctx["current_date"][2] == "/"
    assert ctx["current_date"][5] == "/"


# ─── 3. _build_prompt injecte la date actuelle ────────────────────────────────

def test_build_prompt_contains_current_date():
    from lib.lead_extraction.next_action import _build_prompt

    ctx = {
        "prenom": "Claire",
        "nom": "Dupont",
        "type_projet": "achat",
        "score_label": "froid",
        "score": 5,
        "statut": "nurturing",
        "motivation": "",
        "silence_jours": 10,
        "conversations": [],
        "calls_summary": [],
        "current_date": "17/05/2026",
        "current_year": 2026,
    }

    prompt = _build_prompt(ctx)

    assert "17/05/2026" in prompt, "La date actuelle doit apparaître dans le prompt"
    assert "2027" in prompt, "L'année N+1 doit être mentionnée dans les règles"
    assert "l'année prochaine" in prompt.lower() or "année prochaine" in prompt.lower()


def test_build_prompt_rules_reference_next_year():
    """Les règles du prompt doivent nommer explicitement l'année suivante."""
    from lib.lead_extraction.next_action import _build_prompt

    current_year = datetime.now().year
    next_year = current_year + 1

    ctx = {
        "prenom": "Marc",
        "nom": "Bernard",
        "type_projet": "vente",
        "score_label": "froid",
        "score": 4,
        "statut": "nurturing",
        "motivation": "",
        "silence_jours": None,
        "conversations": [],
        "calls_summary": [],
        "current_date": f"17/05/{current_year}",
        "current_year": current_year,
    }

    prompt = _build_prompt(ctx)
    assert str(next_year) in prompt


# ─── 4. Deadline passée générée par LLM → ignorée ────────────────────────────

def test_compute_via_llm_rejects_past_deadline(monkeypatch):
    """
    Si le LLM renvoie action_deadline_iso en janvier 2026 (passé),
    le résultat final doit avoir deadline=None.
    """
    from lib.lead_extraction import next_action as na_module

    lead_row = {
        "id": "lead-test",
        "client_id": "client-test",
        "prenom": "Claire",
        "nom": "Dupont",
        "projet": "achat",
        "score": 5,
        "statut": "nurturing",
        "motivation": "pause_projet",
        "created_at": datetime.now(),
        "next_action_label": None,
        "next_action_priority": None,
        "next_action_reason": None,
        "next_action_deadline": None,
        "next_action_computed_at": None,
    }

    # Simuler réponse LLM avec une deadline passée (janvier 2026)
    mock_llm_json = (
        '{"action_label": "Envoyer SMS de relance pour début janvier 2026",'
        ' "action_priority": "basse",'
        ' "action_reason": "Lead en pause, relance prévue.",'
        ' "action_deadline_iso": "2026-01-10T09:00:00+01:00"}'
    )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=mock_llm_json)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_settings = MagicMock()
    mock_settings.anthropic_available = True
    mock_settings.testing = False
    mock_settings.mock_mode = "never"
    mock_settings.claude_model = "claude-sonnet-4-6"

    mock_context = {
        "lead_id": "lead-test",
        "prenom": "Claire",
        "nom": "Dupont",
        "type_projet": "achat",
        "score_label": "froid",
        "score": 5,
        "statut": "nurturing",
        "motivation": "pause_projet",
        "silence_jours": 3,
        "conversations": [],
        "calls_summary": [],
        "current_date": "17/05/2026",
        "current_year": 2026,
        "created_at": datetime.now(),
        "last_agent_at": None,
        "last_prospect_at": None,
    }

    monkeypatch.setattr(na_module, "_build_context", lambda row, lid: mock_context)

    with patch("config.settings.get_settings", return_value=mock_settings):
        with patch("anthropic.Anthropic", return_value=mock_client):
            from lib.lead_extraction.next_action import _compute_via_llm
            result = _compute_via_llm(lead_row, "lead-test")

    now = datetime.now()
    janvier_2026 = datetime(2026, 1, 10, 9, 0, 0)

    if now > janvier_2026:
        # On est bien après janvier 2026 → la deadline doit être rejetée
        assert result is not None
        assert result.deadline is None, (
            f"Une deadline passée ({janvier_2026}) ne doit pas être conservée, "
            f"mais deadline={result.deadline}"
        )
    else:
        # Si on exécute le test avant janvier 2026, la deadline serait future
        assert result is not None


# ─── 5. Lead refroidi → priorité basse ───────────────────────────────────────

def test_mock_action_lead_froid_priorite_basse():
    """Un lead froid (score < 11) obtient priorité basse via _mock_action."""
    from lib.lead_extraction.next_action import _mock_action

    lead_froid = {
        "score": 4,
        "statut": "nurturing",
        "prenom": "Claire",
        "nom": "Dupont",
    }
    action = _mock_action(lead_froid)

    assert action.priority == "basse"
    assert action.deadline is None  # pas de deadline pour un lead froid en mock


def test_mock_action_lead_froid_pas_urgence():
    """Un lead refroidi ne doit pas avoir priorité haute."""
    from lib.lead_extraction.next_action import _mock_action

    lead_refroidi = {
        "score": 3,
        "statut": "nurturing",
        "prenom": "Claire",
        "nom": "Dupont",
    }
    action = _mock_action(lead_refroidi)
    assert action.priority != "haute"


# ─── 6. _parse_deadline avec date passée : pipeline complet ──────────────────

def test_parse_then_sanitize_past_date():
    """Pipeline complet : parse ISO → sanitize → None si passée."""
    from lib.lead_extraction.next_action import _parse_deadline, _sanitize_deadline

    # "début janvier 2026" en mai 2026 = passé
    iso_past = "2026-01-05T09:00:00+01:00"
    parsed = _parse_deadline(iso_past)
    sanitized = _sanitize_deadline(parsed)

    now = datetime.now()
    if now > datetime(2026, 1, 5, 9, 0, 0):
        assert sanitized is None
    else:
        pytest.skip("Test pertinent uniquement après le 05/01/2026")


def test_parse_then_sanitize_future_date():
    """Pipeline complet : parse ISO → sanitize → datetime si future."""
    from lib.lead_extraction.next_action import _parse_deadline, _sanitize_deadline

    future = datetime.now() + timedelta(days=200)
    iso_future = future.strftime("%Y-%m-%dT%H:%M:%S+01:00")
    parsed = _parse_deadline(iso_future)
    sanitized = _sanitize_deadline(parsed)

    assert sanitized is not None
    assert sanitized > datetime.now()
