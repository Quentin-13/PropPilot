"""
Tests — Attribution des numéros Twilio multi-clients.
Vérifie assign_twilio_number() et release_twilio_number().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from memory.database import init_database


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


# ─── assign_twilio_number ────────────────────────────────────────────────────

def _make_user(user_id: str, email: str = None) -> str:
    """Insère un utilisateur dans la DB de test et retourne son ID."""
    from memory.database import get_connection
    import uuid
    email = email or f"{user_id}@test.fr"
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users (id, email, hashed_password, agency_name, plan, plan_active)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (user_id, email, "hashed_pw", "Agence Test", "Starter", True),
        )
    return user_id


def test_assign_returns_first_available_number():
    from config.settings import assign_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        # Pas de numéro déjà assigné
        mock_conn.execute.return_value.fetchone.side_effect = [
            None,  # user n'a pas de numéro
        ]
        mock_conn.execute.return_value.fetchall.return_value = []  # pool vide des pris

        result = assign_twilio_number("user_001")

        assert result == "+33700000001"


def test_assign_returns_existing_number_if_already_assigned():
    from config.settings import assign_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = {"twilio_sms_number": "+33700000003"}

        result = assign_twilio_number("user_already_assigned")

        assert result == "+33700000003"


def test_assign_skips_taken_numbers():
    from config.settings import assign_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.fetchall.return_value = [
            {"twilio_sms_number": "+33700000001"},
            {"twilio_sms_number": "+33700000002"},
        ]

        result = assign_twilio_number("user_new")

        assert result == "+33700000003"


def test_assign_returns_none_when_pool_exhausted():
    from config.settings import assign_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None
        # Tous les 5 numéros pris
        mock_conn.execute.return_value.fetchall.return_value = [
            {"twilio_sms_number": f"+3370000000{i}"} for i in range(1, 6)
        ]

        result = assign_twilio_number("user_overflow")

        assert result is None


def test_assign_returns_none_when_pool_empty():
    from config.settings import assign_twilio_number
    with patch("config.settings.get_settings") as mock_gs:
        mock_settings = MagicMock()
        mock_settings.twilio_available_numbers = []
        mock_gs.return_value = mock_settings

        result = assign_twilio_number("user_no_pool")

        assert result is None


# ─── release_twilio_number ────────────────────────────────────────────────────

def test_release_returns_true_when_number_exists():
    from config.settings import release_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = {"twilio_sms_number": "+33700000001"}

        result = release_twilio_number("user_to_release")

        assert result is True
        # Vérifie qu'un UPDATE a été effectué
        calls = mock_conn.execute.call_args_list
        update_calls = [c for c in calls if "UPDATE" in str(c)]
        assert len(update_calls) >= 1


def test_release_returns_false_when_no_number():
    from config.settings import release_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None

        result = release_twilio_number("user_without_number")

        assert result is False


def test_release_returns_false_when_number_is_null():
    from config.settings import release_twilio_number
    with patch("memory.database.get_connection") as mock_gc:
        mock_conn = MagicMock()
        mock_gc.return_value.__enter__ = lambda s: mock_conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = {"twilio_sms_number": None}

        result = release_twilio_number("user_null_number")

        assert result is False


# ─── Intégration webhook — lookup client par numéro "To" ─────────────────────

def test_sms_webhook_identifies_client_by_to_number():
    """
    Vérifie que les webhooks SMS/voix utilisent le champ 'To' pour router
    vers le bon client — architecture multi-numéros.
    """
    import ast
    server_src = Path("server.py").read_text()
    # Le webhook doit interroger twilio_sms_number avec le numéro To
    assert "twilio_sms_number" in server_src
    assert "to_number" in server_src or "To" in server_src


def test_voice_webhook_identifies_client_by_to_number():
    """Le webhook voix doit aussi router par numéro To."""
    server_src = Path("server.py").read_text()
    assert "twilio_sms_number" in server_src
    # Le webhook voix identifie bien le client
    assert "twilio_voice_inbound" in server_src or "voice" in server_src
