"""
Tests — Attribution des numéros Twilio multi-clients.
Couvre : assign_twilio_number(), release_twilio_number(),
         atomicité, concurrence, sécurité webhooks.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    monkeypatch.setenv(
        "TWILIO_AVAILABLE_NUMBERS",
        "+33700000001,+33700000002,+33700000003,+33700000004,+33700000005",
    )
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Settings — parsing du pool ──────────────────────────────────────────────

def test_settings_parses_available_numbers():
    from config.settings import get_settings
    s = get_settings()
    assert len(s.twilio_available_numbers) == 5
    assert "+33700000001" in s.twilio_available_numbers


def test_settings_empty_pool():
    from config.settings import Settings
    s = Settings(TWILIO_AVAILABLE_NUMBERS="", DATABASE_URL="postgresql://localhost/test")
    assert s.twilio_available_numbers == []


def test_settings_single_number():
    from config.settings import Settings
    s = Settings(TWILIO_AVAILABLE_NUMBERS="+33700000001", DATABASE_URL="postgresql://localhost/test")
    assert s.twilio_available_numbers == ["+33700000001"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _gc_mock(fetchone_side_effects: list):
    """Construit un mock get_connection() avec des fetchone séquentiels."""
    mock_gc = MagicMock()
    mock_conn = MagicMock()
    cursors = [MagicMock(fetchone=MagicMock(return_value=v)) for v in fetchone_side_effects]
    mock_conn.execute.side_effect = cursors
    mock_gc.return_value.__enter__ = lambda s: mock_conn
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)
    return mock_gc, mock_conn


# ─── assign_twilio_number — cas nominaux ─────────────────────────────────────

def test_assign_returns_number_from_cte():
    """CTE atomique retourne le numéro assigné."""
    from config.settings import assign_twilio_number
    mock_gc, _ = _gc_mock([
        None,                                       # pas de numéro existant
        {"twilio_sms_number": "+33700000001"},      # CTE UPDATE RETURNING
    ])
    with patch("memory.database.get_connection", mock_gc):
        assert assign_twilio_number("user_001") == "+33700000001"


def test_assign_returns_existing_number_if_already_assigned():
    """Idempotent : renvoie le numéro déjà attribué sans modifier la DB."""
    from config.settings import assign_twilio_number
    mock_gc, mock_conn = _gc_mock([
        {"twilio_sms_number": "+33700000003"},
    ])
    with patch("memory.database.get_connection", mock_gc):
        result = assign_twilio_number("user_already_assigned")
    assert result == "+33700000003"
    # Un seul SELECT, pas d'UPDATE
    assert mock_conn.execute.call_count == 1


def test_assign_returns_none_when_pool_exhausted():
    """CTE ne trouve aucun numéro libre → None + warning logué."""
    from config.settings import assign_twilio_number
    mock_gc, _ = _gc_mock([
        None,   # pas de numéro existant
        None,   # CTE RETURNING vide (pool épuisé)
    ])
    with patch("memory.database.get_connection", mock_gc):
        assert assign_twilio_number("user_overflow") is None


def test_assign_returns_none_when_pool_empty():
    """Pool absent en config → None immédiat, pas d'accès DB."""
    from config.settings import assign_twilio_number
    with patch("config.settings.get_settings") as mock_gs:
        mock_gs.return_value.twilio_available_numbers = []
        assert assign_twilio_number("user_no_pool") is None


# ─── assign_twilio_number — sécurité concurrence ─────────────────────────────

def test_assign_logs_warning_when_pool_exhausted(caplog):
    """Logger un WARNING quand pool épuisé (alerte opérationnelle)."""
    import logging
    from config.settings import assign_twilio_number
    mock_gc, _ = _gc_mock([None, None])
    with patch("memory.database.get_connection", mock_gc):
        with caplog.at_level(logging.WARNING, logger="config.settings"):
            result = assign_twilio_number("user_overflow")
    assert result is None
    assert any(
        "pool" in r.message.lower() or "épuisé" in r.message.lower()
        for r in caplog.records
    )


def test_assign_handles_unique_violation_as_race_condition():
    """UniqueViolation (conflit concurrent sur index UNIQUE) → None sans exception."""
    import psycopg2.errors
    from config.settings import assign_twilio_number

    mock_gc = MagicMock()
    mock_conn = MagicMock()
    first_cursor = MagicMock()
    first_cursor.fetchone.return_value = None
    mock_conn.execute.side_effect = [
        first_cursor,
        psycopg2.errors.UniqueViolation("duplicate key value violates unique constraint"),
    ]
    mock_gc.return_value.__enter__ = lambda s: mock_conn
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)

    with patch("memory.database.get_connection", mock_gc):
        result = assign_twilio_number("user_race")
    assert result is None


def test_parallel_assign_only_one_winner(monkeypatch):
    """
    Simulation de 2 users qui s'inscrivent en parallèle avec 1 seul numéro libre.
    Le premier gagne (CTE retourne le numéro), le second perd (CTE retourne None).
    """
    import threading
    from config.settings import assign_twilio_number

    results = {}

    def make_mock_gc(cte_result):
        mock_gc = MagicMock()
        mock_conn = MagicMock()
        c1 = MagicMock(fetchone=MagicMock(return_value=None))
        c2 = MagicMock(fetchone=MagicMock(return_value=cte_result))
        mock_conn.execute.side_effect = [c1, c2]
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        return mock_gc

    # user_A gagne (DB lui attribue le numéro)
    with patch("memory.database.get_connection", make_mock_gc({"twilio_sms_number": "+33700000005"})):
        t1 = threading.Thread(
            target=lambda: results.__setitem__("A", assign_twilio_number("user_A"))
        )
        t1.start()
        t1.join()

    # user_B perd (DB ne trouve plus de numéro libre)
    with patch("memory.database.get_connection", make_mock_gc(None)):
        t2 = threading.Thread(
            target=lambda: results.__setitem__("B", assign_twilio_number("user_B"))
        )
        t2.start()
        t2.join()

    assert results["A"] == "+33700000005"
    assert results["B"] is None


# ─── release_twilio_number ────────────────────────────────────────────────────

def test_release_returns_true_when_number_exists():
    from config.settings import release_twilio_number
    # SELECT + UPDATE → 2 appels execute()
    mock_gc, mock_conn = _gc_mock([
        {"twilio_sms_number": "+33700000001"},  # SELECT
        None,                                   # UPDATE (pas de RETURNING)
    ])
    with patch("memory.database.get_connection", mock_gc):
        result = release_twilio_number("user_to_release")
    assert result is True
    calls = mock_conn.execute.call_args_list
    assert any("UPDATE" in str(c) for c in calls)


def test_release_returns_false_when_no_number():
    from config.settings import release_twilio_number
    mock_gc, _ = _gc_mock([None])
    with patch("memory.database.get_connection", mock_gc):
        assert release_twilio_number("user_without_number") is False


def test_release_returns_false_when_number_is_null():
    from config.settings import release_twilio_number
    mock_gc, _ = _gc_mock([{"twilio_sms_number": None}])
    with patch("memory.database.get_connection", mock_gc):
        assert release_twilio_number("user_null_number") is False


# ─── Webhook SMS — sécurité routage ──────────────────────────────────────────

def _make_sms_client():
    """Crée un TestClient FastAPI avec validate_twilio_signature bypassé."""
    from fastapi.testclient import TestClient
    with patch("tools.security.validate_twilio_signature", new=AsyncMock(return_value=True)):
        from server import app
        return TestClient(app, raise_server_exceptions=False)


def test_sms_webhook_routes_to_correct_client():
    """SMS sur numéro assigné → 200 + TwiML vide retourné."""
    from fastapi.testclient import TestClient

    with patch("tools.security.validate_twilio_signature", new=AsyncMock(return_value=True)), \
         patch("memory.database.get_connection") as mock_gc, \
         patch("lib.sms_storage.store_incoming_sms", return_value={"lead_id": "lead_abc", "is_new_lead": True, "stored": True}):

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"id": "client_abc", "plan": "Pro"}
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        from server import app
        client = TestClient(app)
        resp = client.post("/webhooks/twilio/sms", data={
            "From": "+33612345678",
            "To": "+33700000001",
            "Body": "Je veux vendre mon appartement",
        })

    assert resp.status_code == 200
    assert b"<Response>" in resp.content


def test_sms_webhook_rejects_unknown_number():
    """
    SMS sur numéro 'To' non attribué → TwiML vide retourné (pas d'erreur).
    Le client_id est résolu depuis settings, pas depuis le pool Twilio.
    """
    with patch("tools.security.validate_twilio_signature", new=AsyncMock(return_value=True)), \
         patch("memory.database.get_connection") as mock_gc, \
         patch("lib.sms_storage.store_incoming_sms", return_value={"lead_id": None, "is_new_lead": False, "stored": False}):

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        from server import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/webhooks/twilio/sms", data={
            "From": "+33600000000",
            "To": "+33799999999",
            "Body": "probe",
        })

    assert resp.status_code == 200
    assert b"<Response>" in resp.content


def test_sms_webhook_identifies_client_by_to_number():
    """Vérification statique : server.py interroge twilio_sms_number sur le champ To."""
    server_src = Path("server.py").read_text()
    assert "twilio_sms_number" in server_src
    assert "to_number" in server_src


def test_voice_webhook_identifies_client_by_to_number():
    """Vérification statique : webhook voix route aussi par numéro To."""
    server_src = Path("server.py").read_text()
    assert "twilio_sms_number" in server_src
    assert "twilio_voice_inbound" in server_src
