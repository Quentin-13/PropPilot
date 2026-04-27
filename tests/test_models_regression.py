"""
Tests de non-régression — modèles de données et orchestrateur.
Couvre les bugs corrigés lors de l'audit 2026-04-19.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

pytestmark = pytest.mark.skip(reason="AgencyState / orchestrator supprimés — sprint cleanup-pivot")


# ─── B1 : User dataclass — champs is_admin et smspartner_number ───────────────

def test_user_has_is_admin_field():
    """B1 — is_admin doit exister et valoir False par défaut."""
    from memory.models import User
    u = User(email="test@example.com")
    assert hasattr(u, "is_admin"), "Champ is_admin manquant dans User"
    assert u.is_admin is False


def test_user_has_smspartner_number_field():
    """B1 — smspartner_number doit exister et valoir None par défaut."""
    from memory.models import User
    u = User(email="test@example.com")
    assert hasattr(u, "smspartner_number"), "Champ smspartner_number manquant dans User"
    assert u.smspartner_number is None


def test_user_is_admin_can_be_set():
    """B1 — is_admin doit être settable."""
    from memory.models import User
    u = User(email="admin@proppilot.fr", is_admin=True)
    assert u.is_admin is True


def test_user_all_fields_present():
    """B1 — vérification exhaustive des champs attendus par server.py."""
    from memory.models import User
    expected_fields = {"id", "email", "agency_name", "first_name", "plan",
                       "plan_active", "twilio_sms_number", "smspartner_number",
                       "is_admin", "created_at"}
    u = User()
    actual_fields = set(vars(u).keys())
    missing = expected_fields - actual_fields
    assert not missing, f"Champs manquants dans User : {missing}"


# ─── A2 : AgencyState sans champs voice_call_* ────────────────────────────────

def test_orchestrator_state_no_voice_call_fields():
    """A2 — AgencyState ne doit plus contenir voice_call_id ni voice_call_triggered."""
    from orchestrator import AgencyState
    fields = AgencyState.__annotations__
    assert "voice_call_id" not in fields, "voice_call_id toujours présent dans AgencyState"
    assert "voice_call_triggered" not in fields, "voice_call_triggered toujours présent dans AgencyState"


def test_make_initial_state_no_voice_fields():
    """A2 — make_initial_state ne doit pas initialiser de champs voix morts."""
    from orchestrator import make_initial_state
    state = make_initial_state(
        client_id="test_client",
        telephone="+33600000001",
        message="Bonjour",
    )
    assert "voice_call_id" not in state
    assert "voice_call_triggered" not in state


# ─── F2 : import Hektor sans IndentationError ─────────────────────────────────

def test_hektor_import_no_indentation_error():
    """F2 — L'import de HektorConnector ne doit pas lever IndentationError."""
    try:
        from integrations.crm.hektor import HektorConnector  # noqa: F401
    except IndentationError as e:
        pytest.fail(f"IndentationError dans hektor.py : {e}")


# ─── F1/C2 : Apimo test_connection utilise self.agency_id ─────────────────────

@pytest.mark.asyncio
async def test_apimo_test_connection_mock_returns_success():
    """F1 — test_connection en mode mock ne doit pas lever NameError sur agency_id."""
    from integrations.crm.apimo import ApimoCRMConnector
    connector = ApimoCRMConnector(api_key="", agency_id="agency_xyz")
    result = await connector.test_connection()
    assert result["success"] is True
    assert "agency_name" in result
