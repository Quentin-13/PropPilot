"""
Tests Chantier 5 — Onboarding & pool numéros PropPilot.

Fonctions testées (pas de Streamlit) :
  - assign_available_phone_number
  - should_show_welcome
  - mark_welcome_seen
  - get_client_welcome_context
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


def _mock_conn(fetchone_return=None, fetchall_return=None):
    """Construit un faux contexte get_connection()."""
    conn = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchone.return_value = fetchone_return
    execute_result.fetchall.return_value = fetchall_return or []
    conn.execute.return_value = execute_result
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, conn


# ══════════════════════════════════════════════════════════════════════════════
# assign_available_phone_number
# ══════════════════════════════════════════════════════════════════════════════

class TestAssignAvailablePhoneNumber:

    def test_returns_existing_pool_assignment(self):
        """Client déjà assigné dans phone_numbers → retourne son numéro sans rien modifier."""
        cm, conn = _mock_conn(fetchone_return={"phone_number": "+33700000001"})

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import assign_available_phone_number
            result = assign_available_phone_number("client-001")

        assert result == "+33700000001"
        # Doit s'arrêter après le premier SELECT (idempotent)
        conn.execute.assert_called_once()

    def test_returns_existing_twilio_sms_number(self):
        """Client sans entrée pool mais avec users.twilio_sms_number → retourne ce numéro."""
        cm, conn = _mock_conn()

        # Premier execute (phone_numbers) → None, second execute (users) → numéro existant
        conn.execute.return_value.fetchone.side_effect = [
            None,                                     # phone_numbers : pas d'entrée
            {"twilio_sms_number": "+33700000002"},    # users : numéro existant
        ]

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import assign_available_phone_number
            result = assign_available_phone_number("client-002")

        assert result == "+33700000002"

    def test_assigns_available_number_from_pool(self):
        """Client sans numéro → assigne le premier disponible du pool."""
        cm, conn = _mock_conn()

        conn.execute.return_value.fetchone.side_effect = [
            None,                                     # phone_numbers : pas d'entrée
            {"twilio_sms_number": None},              # users : pas de numéro
            {"phone_number": "+33700000003"},         # CTE UPDATE → numéro attribué
            MagicMock(),                              # UPDATE users
        ]

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import assign_available_phone_number
            result = assign_available_phone_number("client-003")

        assert result == "+33700000003"

    def test_returns_none_when_pool_exhausted(self):
        """Aucun numéro disponible → retourne None sans lever d'exception."""
        cm, conn = _mock_conn()

        conn.execute.return_value.fetchone.side_effect = [
            None,                        # phone_numbers : pas d'entrée
            {"twilio_sms_number": None}, # users : pas de numéro
            None,                        # CTE UPDATE → pool épuisé
        ]

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import assign_available_phone_number
            result = assign_available_phone_number("client-004")

        assert result is None

    def test_client_id_isolation(self):
        """Deux clients différents ne partagent pas le même numéro."""
        results = []
        for i, cid in enumerate(["client-A", "client-B"]):
            cm, conn = _mock_conn()
            number = f"+3370000000{i + 1}"
            conn.execute.return_value.fetchone.side_effect = [
                None,
                {"twilio_sms_number": None},
                {"phone_number": number},
                MagicMock(),
            ]
            with patch("memory.phone_numbers.get_connection", return_value=cm):
                from memory.phone_numbers import assign_available_phone_number
                results.append(assign_available_phone_number(cid))

        assert results[0] != results[1]

    def test_empty_client_id_returns_none(self):
        from memory.phone_numbers import assign_available_phone_number
        assert assign_available_phone_number("") is None
        assert assign_available_phone_number(None) is None  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════════
# should_show_welcome / mark_welcome_seen
# ══════════════════════════════════════════════════════════════════════════════

class TestWelcomeFlag:

    def test_first_login_shows_welcome(self):
        """welcome_seen_at IS NULL → should_show_welcome retourne True."""
        cm, _ = _mock_conn(fetchone_return={"welcome_seen_at": None})

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import should_show_welcome
            assert should_show_welcome("client-001") is True

    def test_returning_user_skips_welcome(self):
        """welcome_seen_at renseigné → should_show_welcome retourne False."""
        from datetime import datetime, timezone
        ts = datetime(2026, 5, 16, 10, 0, 0, tzinfo=timezone.utc)
        cm, _ = _mock_conn(fetchone_return={"welcome_seen_at": ts})

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import should_show_welcome
            assert should_show_welcome("client-001") is False

    def test_mark_welcome_seen_updates_db(self):
        """mark_welcome_seen doit exécuter un UPDATE avec le bon client_id."""
        cm, conn = _mock_conn()

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import mark_welcome_seen
            mark_welcome_seen("client-001")

        sql_called = conn.execute.call_args[0][0]
        assert "welcome_seen_at" in sql_called.lower()
        assert conn.execute.call_args[0][1] == ("client-001",)


# ══════════════════════════════════════════════════════════════════════════════
# get_client_welcome_context
# ══════════════════════════════════════════════════════════════════════════════

class TestWelcomeContext:

    def test_crm_none_returns_none_status(self):
        """CRM non configuré → crm_status='none', pas d'erreur."""
        row = {
            "twilio_sms_number": "+33700000001",
            "crm_type": "none",
            "crm_last_sync_at": None,
            "crm_last_error": None,
        }
        cm, _ = _mock_conn(fetchone_return=row)

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import get_client_welcome_context
            ctx = get_client_welcome_context("client-001")

        assert ctx["crm_status"] == "none"
        assert ctx["phone_number"] == "+33700000001"

    def test_crm_active_returns_active_status(self):
        """CRM avec sync_at et pas d'erreur → crm_status='active'."""
        from datetime import datetime, timezone
        row = {
            "twilio_sms_number": None,
            "crm_type": "hektor",
            "crm_last_sync_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            "crm_last_error": None,
        }
        cm, _ = _mock_conn(fetchone_return=row)

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import get_client_welcome_context
            ctx = get_client_welcome_context("client-001")

        assert ctx["crm_status"] == "active"
        assert ctx["crm_label"] == "Hektor (La Boîte Immo)"

    def test_crm_configured_without_sync(self):
        """CRM configuré mais jamais synchro → crm_status='configured'."""
        row = {
            "twilio_sms_number": None,
            "crm_type": "apimo",
            "crm_last_sync_at": None,
            "crm_last_error": None,
        }
        cm, _ = _mock_conn(fetchone_return=row)

        with patch("memory.phone_numbers.get_connection", return_value=cm):
            from memory.phone_numbers import get_client_welcome_context
            ctx = get_client_welcome_context("client-001")

        assert ctx["crm_status"] == "configured"
