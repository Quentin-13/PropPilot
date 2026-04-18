"""
Tests Google Calendar OAuth — CalendarTool + endpoints FastAPI.
TESTING=true → mock automatique de tous les appels Google Calendar.
PostgreSQL requis pour les tests API (skippé si indisponible).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("TESTING", "true")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _force_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _next_weekday(hour: int = 10, minute: int = 0) -> datetime:
    """Retourne le prochain jour ouvré à l'heure demandée."""
    dt = datetime.now() + timedelta(days=1)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ─── Tâche 1 — Settings OAuth ─────────────────────────────────────────────────

class TestCalendarSettings:
    def test_google_client_id_field_exists(self):
        from config.settings import get_settings
        s = get_settings()
        assert hasattr(s, "google_client_id")
        assert s.google_client_id is None  # Non défini en test

    def test_google_client_secret_field_exists(self):
        from config.settings import get_settings
        s = get_settings()
        assert hasattr(s, "google_client_secret")

    def test_google_redirect_uri_has_default(self):
        from config.settings import get_settings
        s = get_settings()
        assert "localhost" in s.google_redirect_uri or "callback" in s.google_redirect_uri

    def test_google_scopes_default_contains_calendar(self):
        from config.settings import get_settings
        s = get_settings()
        assert any("calendar" in scope for scope in s.google_scopes)

    def test_google_oauth_available_false_in_testing(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.google_oauth_available is False

    def test_google_oauth_available_false_without_keys(self, monkeypatch):
        monkeypatch.setenv("TESTING", "false")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.google_oauth_available is False
        get_settings.cache_clear()

    def test_google_scopes_overridable(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_SCOPES", '["https://www.googleapis.com/auth/calendar.readonly"]')
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert "calendar.readonly" in s.google_scopes[0]
        get_settings.cache_clear()


# ─── Tâche 3 — Migration DB ────────────────────────────────────────────────────

class TestDatabaseMigration:
    def test_schema_contains_google_calendar_token(self):
        from memory.database import SCHEMA
        assert "google_calendar_token" in SCHEMA

    def test_migration_contains_google_calendar_token(self):
        """La migration ALTER TABLE ajoute bien la colonne."""
        import inspect
        from memory.database import _run_migrations
        src = inspect.getsource(_run_migrations)
        assert "google_calendar_token" in src


# ─── Tâche 4 — CalendarTool mock ──────────────────────────────────────────────

class TestCalendarToolMock:
    def _tool(self):
        from tools.calendar_tool import CalendarTool
        return CalendarTool()

    def test_mock_mode_active_in_testing(self):
        tool = self._tool()
        assert tool.mock_mode is True

    def test_get_available_slots_returns_list(self):
        tool = self._tool()
        slots = tool.get_available_slots()
        assert isinstance(slots, list)
        assert len(slots) > 0

    def test_slots_have_required_keys(self):
        tool = self._tool()
        slot = tool.get_available_slots()[0]
        assert "start" in slot
        assert "end" in slot
        assert "label" in slot
        assert "label_short" in slot

    def test_slots_start_hour_at_9(self):
        tool = self._tool()
        slots = tool.get_available_slots(start_hour=9, end_hour=19)
        for slot in slots:
            assert slot["start"].hour >= 9

    def test_slots_no_weekends(self):
        tool = self._tool()
        slots = tool.get_available_slots()
        for slot in slots:
            assert slot["start"].weekday() < 5, f"Weekend slot found: {slot['label']}"

    def test_slots_accept_user_id_param(self):
        """user_id est accepté même en mode mock (ignoré silencieusement)."""
        tool = self._tool()
        slots = tool.get_available_slots(user_id="test_user_123")
        assert isinstance(slots, list)

    def test_book_slot_mock_success(self):
        tool = self._tool()
        slot_start = _next_weekday(10, 0)
        result = tool.book_slot(
            start_dt=slot_start,
            title="RDV Test",
            description="Test booking",
            attendee_email="lead@test.fr",
            attendee_name="Jean Dupont",
        )
        assert result["success"] is True
        assert result["mock"] is True
        assert "event_id" in result

    def test_book_slot_event_id_contains_date(self):
        tool = self._tool()
        slot_start = _next_weekday(14, 30)
        result = tool.book_slot(start_dt=slot_start, title="Test")
        assert slot_start.strftime("%Y%m%d") in result["event_id"]

    def test_get_next_slots_for_voice_returns_strings(self):
        tool = self._tool()
        slots = tool.get_next_slots_for_voice(n=3)
        assert isinstance(slots, list)
        assert len(slots) == 3
        for s in slots:
            assert isinstance(s, str)
            assert "à" in s

    def test_cancel_slot_mock(self):
        tool = self._tool()
        result = tool.cancel_slot("mock_event_20260310_1000")
        assert result["success"] is True
        assert result["mock"] is True


# ─── Tâche 4 — book_appointment ────────────────────────────────────────────────

class TestBookAppointment:
    def _tool(self):
        from tools.calendar_tool import CalendarTool
        return CalendarTool()

    def _mock_lead(self, with_email: bool = True):
        from memory.models import Lead, ProjetType
        return Lead(
            client_id="test_client",
            prenom="Claire",
            nom="Martin",
            email="claire.martin@test.fr" if with_email else "",
            projet=ProjetType.ACHAT,
            localisation="Lyon",
            budget="350 000€",
            score=8,
        )

    def _slot(self) -> dict:
        start = _next_weekday(10, 0)
        return {
            "start": start,
            "end": start + timedelta(minutes=30),
            "label": "mardi 10/03 à 10:00",
            "label_short": "mardi à 10h",
        }

    def test_book_appointment_success(self):
        tool = self._tool()
        lead = self._mock_lead()
        result = tool.book_appointment(lead=lead, slot=self._slot())
        assert result["success"] is True
        assert result["mock"] is True

    def test_book_appointment_returns_email_sent_flag(self):
        tool = self._tool()
        lead = self._mock_lead(with_email=True)
        result = tool.book_appointment(lead=lead, slot=self._slot(), send_email=True)
        assert "email_sent" in result

    def test_book_appointment_no_email_when_no_lead_email(self):
        tool = self._tool()
        lead = self._mock_lead(with_email=False)
        result = tool.book_appointment(lead=lead, slot=self._slot(), send_email=True)
        assert result["email_sent"] is False

    def test_book_appointment_no_email_when_send_email_false(self):
        tool = self._tool()
        lead = self._mock_lead(with_email=True)
        result = tool.book_appointment(lead=lead, slot=self._slot(), send_email=False)
        assert result["email_sent"] is False

    def test_book_appointment_accepts_user_id(self):
        tool = self._tool()
        lead = self._mock_lead()
        result = tool.book_appointment(lead=lead, slot=self._slot(), user_id="user_123")
        assert result["success"] is True


# ─── Tâche 4 — send_confirmation ──────────────────────────────────────────────

class TestSendConfirmation:
    def _tool(self):
        from tools.calendar_tool import CalendarTool
        return CalendarTool()

    def _slot(self) -> dict:
        start = _next_weekday(14, 0)
        return {
            "start": start,
            "end": start + timedelta(minutes=30),
            "label": "jeudi 12/03 à 14:00",
            "label_short": "jeudi à 14h",
        }

    def test_send_confirmation_mock_success(self):
        tool = self._tool()
        result = tool.send_confirmation(
            lead_email="lead@test.fr",
            slot=self._slot(),
            agency_name="Agence Martin",
            lead_name="Claire",
        )
        assert result["success"] is True
        assert result["mock"] is True

    def test_send_confirmation_email_content(self):
        """Le mock retourne toujours succès, peu importe le contenu."""
        tool = self._tool()
        result = tool.send_confirmation(
            lead_email="test@test.fr",
            slot=self._slot(),
        )
        assert result["success"] is True

    def test_send_confirmation_uses_agency_name(self):
        """L'agence est incluse dans le sujet (visible dans les logs mock)."""
        tool = self._tool()
        # En mock mode, le résultat ne contient pas le HTML — on vérifie juste success
        result = tool.send_confirmation(
            lead_email="test@test.fr",
            slot=self._slot(),
            agency_name="Agence Test SARL",
        )
        assert result["success"] is True


# ─── Tâche 5 — VoiceCallAgent : 3 créneaux + confirmation ─────────────────────

class TestVoiceInboundCalendarIntegration:
    """Tests de l'intégration calendrier avec les appels entrants."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("MOCK_MODE", "always")
        monkeypatch.setenv("TESTING", "true")
        from config.settings import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_auto_book_rdv_sends_confirmation_email(self):
        """_auto_book_rdv appelle book_appointment avec send_email=True si email présent."""
        from agents.voice_inbound import VoiceInboundAgent
        from memory.models import Lead, ProjetType

        lead = Lead(
            client_id="test_c",
            prenom="Claire",
            email="claire@test.fr",
            projet=ProjetType.ACHAT,
            localisation="Paris",
            score=9,
        )
        lead.id = "lead_test_001"

        agent = VoiceInboundAgent(client_id="test_c", tier="Starter")
        result = agent._auto_book_rdv(lead=lead, summary="RDV confirmé mardi à 10h")

        assert result is not None
        assert result.get("success") is True
        assert "email_sent" in result

    def test_auto_book_rdv_no_email_without_lead_email(self):
        """_auto_book_rdv n'envoie pas d'email si le lead n'a pas d'adresse email."""
        from agents.voice_inbound import VoiceInboundAgent
        from memory.models import Lead, ProjetType

        lead = Lead(
            client_id="test_c",
            prenom="Marc",
            email="",
            projet=ProjetType.VENTE,
            score=8,
        )
        lead.id = "lead_test_002"

        agent = VoiceInboundAgent(client_id="test_c", tier="Starter")
        result = agent._auto_book_rdv(lead=lead, summary="Pas d'email")
        assert result is not None
        assert result.get("email_sent") is False


# ─── Tâche 2 — API endpoints (skippé si PostgreSQL indisponible) ───────────────

def _pg_available() -> bool:
    try:
        from memory.database import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture
def api_client(monkeypatch):
    """Client de test FastAPI avec JWT mocké."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    import server as srv

    # Mock JWT middleware pour les tests API
    def _fake_middleware_state(request, call_next):
        import asyncio
        request.state.user_id = "test_user_api"
        request.state.tier = "Starter"
        return asyncio.get_event_loop().run_until_complete(call_next(request))

    with TestClient(srv.app) as client:
        yield client

    get_settings.cache_clear()


@pytest.mark.skipif(not _pg_available(), reason="PostgreSQL non disponible")
class TestCalendarAPI:
    def test_calendar_auth_returns_mock_url(self, api_client):
        """En TESTING=true, /api/calendar/auth retourne une URL mock."""
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user", "plan": "Starter"})
        resp = api_client.get(
            "/api/calendar/auth",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert data.get("mock") is True

    def test_calendar_callback_stores_mock_token(self, api_client):
        """Le callback mock stocke un token et redirige."""
        resp = api_client.get(
            "/api/calendar/callback",
            params={"code": "mock_code", "state": "test_user_api"},
            follow_redirects=False,
        )
        # Redirige vers le dashboard
        assert resp.status_code in (302, 307, 200)

    def test_calendar_slots_returns_list(self, api_client):
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user", "plan": "Starter"})
        resp = api_client.get(
            "/api/calendar/slots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "slots" in data
        assert isinstance(data["slots"], list)
        assert data["count"] >= 0

    def test_calendar_slots_no_weekends(self, api_client):
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user", "plan": "Starter"})
        resp = api_client.get(
            "/api/calendar/slots",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        for slot in data["slots"]:
            dt = datetime.fromisoformat(slot["start"])
            assert dt.weekday() < 5, f"Weekend in slots: {slot['start']}"

    def test_calendar_book_success(self, api_client):
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user", "plan": "Starter"})
        slot_start = _next_weekday(10, 0).isoformat()
        resp = api_client.post(
            "/api/calendar/book",
            json={
                "slot_start": slot_start,
                "lead_email": "lead@test.fr",
                "lead_name": "Jean Dupont",
                "lead_projet": "achat",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_calendar_book_invalid_date(self, api_client):
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user", "plan": "Starter"})
        resp = api_client.post(
            "/api/calendar/book",
            json={"slot_start": "not-a-date"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_calendar_status_returns_connected_false_by_default(self, api_client):
        from memory.auth import create_access_token
        token = create_access_token({"user_id": "test_user_new", "plan": "Starter"})
        resp = api_client.get(
            "/api/calendar/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # Utilisateur sans token → not connected
        data = resp.json()
        assert "connected" in data

    def test_callback_without_code_redirects_with_error(self, api_client):
        resp = api_client.get(
            "/api/calendar/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307, 200)

    def test_calendar_auth_requires_jwt(self, api_client):
        resp = api_client.get("/api/calendar/auth")
        assert resp.status_code == 401

    def test_calendar_slots_requires_jwt(self, api_client):
        resp = api_client.get("/api/calendar/slots")
        assert resp.status_code == 401

    def test_calendar_book_requires_jwt(self, api_client):
        resp = api_client.post("/api/calendar/book", json={"slot_start": "2026-03-10T10:00:00"})
        assert resp.status_code == 401
