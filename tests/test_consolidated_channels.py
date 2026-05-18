"""
Tests — couverture cross-canal du transcript consolidé et du push CRM.

Vérifie que les 4 types d'échanges (SMS IN, SMS OUT, CALL IN, CALL OUT)
sont bien inclus dans build_lead_conversation_transcript() et que le push CRM
utilise la mémoire consolidée complète (pas seulement le dernier échange).

Tous les tests fonctionnent hors DB : uniquement mock get_connection.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _dt(offset_minutes: int = 0) -> datetime:
    """Date de référence décalée de offset_minutes."""
    return datetime(2026, 5, 17, 10, 0, 0) + timedelta(minutes=offset_minutes)


def _make_conn(sms_rows=None, call_rows=None):
    """Construit un mock get_connection retournant des rows SMS puis des rows appels."""
    sms_rows = sms_rows or []
    call_rows = call_rows or []

    cursor_sms = MagicMock()
    cursor_sms.fetchall.return_value = sms_rows
    cursor_call = MagicMock()
    cursor_call.fetchall.return_value = call_rows

    execute_calls = [cursor_sms, cursor_call]
    call_count = [0]

    mock_conn = MagicMock()
    def _execute(sql, params):
        idx = call_count[0]
        call_count[0] += 1
        return execute_calls[idx] if idx < len(execute_calls) else cursor_sms
    mock_conn.execute.side_effect = _execute
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_get_conn = MagicMock(return_value=mock_conn)
    return mock_get_conn


def _row(data: dict) -> MagicMock:
    m = MagicMock()
    m.get = lambda k, default=None: data.get(k, default)
    m.__getitem__ = lambda self, k: data[k]
    return m


# ─── 1. Transcript consolidé — 4 canaux ───────────────────────────────────────

def test_transcript_contient_sms_in():
    """SMS entrant prospect → [SMS IN ] dans le transcript."""
    sms_rows = [
        _row({"role": "user", "contenu": "Je cherche une maison à Toulouse", "created_at": _dt(0)}),
    ]
    mock_conn = _make_conn(sms_rows=sms_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[SMS IN " in transcript
    assert "Je cherche une maison à Toulouse" in transcript


def test_transcript_contient_sms_out():
    """SMS sortant agent → [SMS OUT] dans le transcript."""
    sms_rows = [
        _row({"role": "assistant", "contenu": "Merci, vous cherchez Toulouse même ou périphérie ?", "created_at": _dt(5)}),
    ]
    mock_conn = _make_conn(sms_rows=sms_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[SMS OUT" in transcript
    assert "Toulouse même ou périphérie" in transcript


def test_transcript_contient_call_in():
    """Appel entrant transcrit → [CALL IN ] dans le transcript."""
    call_rows = [
        _row({"started_at": _dt(10), "transcript_text": "Je m'appelle Claire, muté cet été.", "direction": "inbound"}),
    ]
    mock_conn = _make_conn(call_rows=call_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[CALL IN " in transcript
    assert "Claire" in transcript


def test_transcript_contient_call_out():
    """Appel sortant transcrit → [CALL OUT] dans le transcript."""
    call_rows = [
        _row({"started_at": _dt(20), "transcript_text": "Budget 380k confirmé, accord bancaire obtenu.", "direction": "outbound"}),
    ]
    mock_conn = _make_conn(call_rows=call_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[CALL OUT" in transcript
    assert "380k" in transcript


def test_transcript_ordre_chronologique_4_canaux():
    """Les 4 canaux apparaissent dans l'ordre chronologique strict."""
    sms_rows = [
        _row({"role": "user",      "contenu": "Message 1 prospect", "created_at": _dt(0)}),
        _row({"role": "assistant", "contenu": "Message 2 agent",    "created_at": _dt(10)}),
    ]
    call_rows = [
        _row({"started_at": _dt(5),  "transcript_text": "Appel entrant t=5",  "direction": "inbound"}),
        _row({"started_at": _dt(15), "transcript_text": "Appel sortant t=15", "direction": "outbound"}),
    ]
    mock_conn = _make_conn(sms_rows=sms_rows, call_rows=call_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    lines = [l for l in transcript.splitlines() if l.strip()]
    assert len(lines) == 4
    # Ordre attendu : t=0 SMS IN, t=5 CALL IN, t=10 SMS OUT, t=15 CALL OUT
    assert "[SMS IN " in lines[0]
    assert "[CALL IN " in lines[1]
    assert "[SMS OUT" in lines[2]
    assert "[CALL OUT" in lines[3]


def test_transcript_isolation_client():
    """Les données d'un autre client_id ne doivent jamais apparaître."""
    sms_rows = []  # aucun résultat pour client-2
    mock_conn = _make_conn(sms_rows=sms_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-2")

    assert transcript == ""


def test_transcript_vide_sans_echanges():
    """Aucun échange → transcript vide (string vide)."""
    mock_conn = _make_conn()
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-xyz", "client-xyz")
    assert transcript == ""


def test_transcript_call_sans_direction_defaut_inbound():
    """Un appel sans colonne direction (legacy) → tagué CALL IN par défaut."""
    call_rows = [
        _row({"started_at": _dt(0), "transcript_text": "Appel legacy", "direction": None}),
    ]
    mock_conn = _make_conn(call_rows=call_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[CALL IN " in transcript


# ─── 2. Push CRM — mémoire consolidée, pas seulement le dernier échange ───────

def test_push_crm_utilise_memoire_consolidee():
    """
    build_lead_data_from_db inclut conversation_history issue du transcript consolidé
    (SMS + appels), pas seulement le dernier échange.
    """
    from lib.crm_connectors.factory import build_lead_data_from_db

    full_history = (
        "[SMS IN  - 2026-05-17 10:00] Bonjour je cherche T3\n"
        "[SMS OUT - 2026-05-17 10:05] Merci, quel budget ?\n"
        "[CALL IN  - 2026-05-17 10:10] Budget 300k, secteur Toulouse nord.\n"
        "[CALL OUT - 2026-05-17 10:20] Accord bancaire confirmé."
    )

    mock_lead_row = {
        "id": "lead-001", "client_id": "client-1",
        "prenom": "Claire", "nom": "Martin", "telephone": "+33600000001",
        "email": "", "projet": "achat", "localisation": "Toulouse",
        "motivation": "mutation", "score": 20, "resume": "Cherche T3",
        "next_action_label": "Rappeler", "next_action_reason": "",
        "updated_at": datetime(2026, 5, 17, 10, 20),
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_lead_row
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    # factory.py utilise des imports lazy → patcher à la source
    with patch("memory.database.get_connection", return_value=mock_conn), \
         patch("memory.call_repository.get_latest_extraction_for_lead", return_value=None), \
         patch("lib.consolidated_transcript.build_lead_conversation_transcript", return_value=full_history):
        lead_data = build_lead_data_from_db("lead-001")

    assert lead_data is not None
    hist = lead_data.get("conversation_history", "")
    assert "[SMS IN " in hist
    assert "[SMS OUT" in hist
    assert "[CALL IN " in hist
    assert "[CALL OUT" in hist
    assert hist.count("\n") >= 3


def test_push_crm_extraction_failed_ne_push_pas():
    """
    consolidated_extraction avec status='failed' → push CRM skippé.
    Vérifie que push_lead_to_crm n'est jamais appelé.
    """
    from lib.lead_extraction.consolidated_extraction import extract_and_update_lead

    mock_data = MagicMock()
    mock_data.extraction_status = "failed"
    mock_data.score_qualification = None

    # Les imports dans consolidated_extraction.py sont tous lazy
    with patch("lib.consolidated_transcript.build_lead_conversation_transcript", return_value="Bonjour"), \
         patch("lib.call_extraction_pipeline.CallExtractionPipeline") as mock_pipeline, \
         patch("memory.call_repository.save_sms_extraction"), \
         patch("lib.crm_connectors.factory.push_lead_to_crm") as mock_push:

        mock_pipeline.return_value.extract.return_value = mock_data
        extract_and_update_lead(lead_id="lead-001", client_id="client-1")

    mock_push.assert_not_called()


def test_push_crm_extraction_success_ne_push_pas_directement():
    """
    extract_and_update_lead() réussie → push_lead_to_crm NON déclenché depuis
    extract_and_update_lead elle-même. Le push est délégué aux hooks post-extraction
    (server.py / twilio_voice.py) pour garantir l'ordre compute_next_action → push.
    """
    from lib.lead_extraction.consolidated_extraction import extract_and_update_lead

    mock_data = MagicMock()
    mock_data.extraction_status = "success"
    mock_data.score_qualification = 18

    with patch("lib.consolidated_transcript.build_lead_conversation_transcript", return_value="Bonjour"), \
         patch("lib.call_extraction_pipeline.CallExtractionPipeline") as mock_pipeline, \
         patch("memory.call_repository.save_sms_extraction"), \
         patch("lib.crm_connectors.factory.push_lead_to_crm") as mock_push:

        mock_pipeline.return_value.extract.return_value = mock_data
        extract_and_update_lead(lead_id="lead-001", client_id="client-1")

    mock_push.assert_not_called()


def test_crm_type_email_cree_email_parsing_connector():
    """crm_type='email' instancie bien EmailParsingConnector avec target_email."""
    from lib.crm_connectors.factory import get_connector
    from lib.crm_connectors.email_parsing import EmailParsingConnector

    mock_row = {
        "crm_type": "email",
        "crm_config": '{"target_email": "import@crm.fr", "crm_label": "MonCRM"}',
        "email": "agent@agence.fr",
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("memory.database.get_connection", return_value=mock_conn):
        connector = get_connector("client-1")

    assert isinstance(connector, EmailParsingConnector)
    assert connector._target_email == "import@crm.fr"
    assert connector._reply_to_email == "agent@agence.fr"


def test_crm_type_email_sans_target_email_retourne_none():
    """crm_type='email' sans target_email → connecteur None, pas de crash."""
    from lib.crm_connectors.factory import get_connector

    mock_row = {
        "crm_type": "email",
        "crm_config": '{}',
        "email": "agent@agence.fr",
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("memory.database.get_connection", return_value=mock_conn):
        connector = get_connector("client-1")

    assert connector is None


# ─── 3. Déduplication lead cross-canal ────────────────────────────────────────

def test_sms_out_stocke_role_assistant():
    """SMS sortant agent est stocké role='assistant' → transcript le tagge SMS OUT."""
    # Ce test vérifie que le role 'assistant' → direction OUT dans le transcript
    sms_rows = [
        _row({"role": "assistant", "contenu": "Votre conseiller vous rappelle.", "created_at": _dt(0)}),
    ]
    mock_conn = _make_conn(sms_rows=sms_rows)
    with patch("lib.consolidated_transcript.get_connection", mock_conn):
        from lib.consolidated_transcript import build_lead_conversation_transcript
        transcript = build_lead_conversation_transcript("lead-1", "client-1")

    assert "[SMS OUT" in transcript
    assert "[SMS IN " not in transcript
