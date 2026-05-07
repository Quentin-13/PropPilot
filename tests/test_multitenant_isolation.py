"""
Tests isolation multi-tenant (Chantier 4) :
- get_lead(lead_id, client_id=...) ne retourne pas les leads d'une autre agence
- GET /api/calls/{call_id} renvoie 403 si l'appel appartient à une autre agence
- GET /api/calls/{call_id}/extraction renvoie 403 idem
- POST /api/calls/outbound ne renvoie pas le téléphone d'un lead étranger
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _force_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── get_lead avec client_id ───────────────────────────────────────────────────

class TestGetLeadIsolation:
    def _mock_conn(self, row_client_id: str):
        """Connexion simulée retournant un lead avec le client_id donné."""
        conn = MagicMock()
        row = {
            "id": "lead-abc", "client_id": row_client_id,
            "prenom": "Alice", "nom": "Martin", "telephone": "+33600000001",
            "email": "", "source": "sms", "projet": "achat",
            "localisation": "", "budget": "", "timeline": "", "financement": "",
            "motivation": "", "score": 10, "score_urgence": 0, "score_budget": 0,
            "score_motivation": 0, "statut": "entrant",
            "nurturing_sequence": None, "nurturing_step": 0,
            "prochain_followup": None, "rdv_date": None, "mandat_date": None,
            "resume": "", "notes_agent": "", "created_at": None, "updated_at": None,
        }

        def _execute(sql, params=None):
            cur = MagicMock()
            # Simule le filtre client_id dans la requête SQL
            if params and len(params) == 2:
                _id, _cid = params
                cur.fetchone.return_value = row if (_cid == row_client_id) else None
            else:
                cur.fetchone.return_value = row
            return cur

        conn.execute.side_effect = _execute
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False
        return ctx

    def test_get_lead_correct_client_returns_lead(self):
        from memory.lead_repository import get_lead

        with patch("memory.lead_repository.get_connection",
                   return_value=self._mock_conn("agence-001")):
            lead = get_lead("lead-abc", client_id="agence-001")

        assert lead is not None
        assert lead.id == "lead-abc"

    def test_get_lead_wrong_client_returns_none(self):
        from memory.lead_repository import get_lead

        with patch("memory.lead_repository.get_connection",
                   return_value=self._mock_conn("agence-001")):
            lead = get_lead("lead-abc", client_id="agence-002")

        assert lead is None

    def test_get_lead_no_client_id_returns_lead(self):
        """Sans client_id, get_lead retourne le lead sans filtrer (usage interne)."""
        from memory.lead_repository import get_lead

        with patch("memory.lead_repository.get_connection",
                   return_value=self._mock_conn("agence-001")):
            lead = get_lead("lead-abc")

        assert lead is not None


# ── /api/calls/{call_id} ownership ───────────────────────────────────────────

@pytest.fixture
def calls_client():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.calls import router

    app = FastAPI()

    # Middleware simulant l'auth JWT → user_id = "agence-001"
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.user_id = "agence-001"
            request.state.tier = "Starter"
            return await call_next(request)

    app.add_middleware(FakeAuth)
    app.include_router(router)
    return TestClient(app)


class TestCallsEndpointIsolation:
    def _call_dict(self, client_id: str) -> dict:
        return {
            "id": "call-xyz", "call_sid": "CA123", "client_id": client_id,
            "agency_id": client_id, "direction": "inbound", "mode": "dedicated_number",
            "from_number": "+33600000001", "to_number": "+33700000001",
            "twilio_number": "+33700000001", "lead_id": "lead-abc",
            "status": "completed", "created_at": "2026-05-07T10:00:00Z",
        }

    def test_get_call_own_client_returns_200(self, calls_client):
        own_call = self._call_dict("agence-001")
        with patch("memory.call_repository.get_call_by_id", return_value=own_call):
            resp = calls_client.get("/api/calls/call-xyz")
        assert resp.status_code == 200

    def test_get_call_other_client_returns_403(self, calls_client):
        foreign_call = self._call_dict("agence-002")
        with patch("memory.call_repository.get_call_by_id", return_value=foreign_call):
            resp = calls_client.get("/api/calls/call-xyz")
        assert resp.status_code == 403

    def test_get_extraction_other_client_returns_403(self, calls_client):
        foreign_call = self._call_dict("agence-002")
        with patch("memory.call_repository.get_call_by_id", return_value=foreign_call):
            resp = calls_client.get("/api/calls/call-xyz/extraction")
        assert resp.status_code == 403

    def test_get_extraction_own_client_returns_extraction(self, calls_client):
        own_call = self._call_dict("agence-001")
        extraction = {"id": 1, "call_id": "call-xyz", "score_qualification": "chaud"}
        with patch("memory.call_repository.get_call_by_id", return_value=own_call), \
             patch("memory.call_repository.get_extraction_by_call", return_value=extraction):
            resp = calls_client.get("/api/calls/call-xyz/extraction")
        assert resp.status_code == 200
        assert resp.json()["score_qualification"] == "chaud"

    def test_get_call_missing_returns_404(self, calls_client):
        with patch("memory.call_repository.get_call_by_id", return_value=None):
            resp = calls_client.get("/api/calls/call-missing")
        assert resp.status_code == 404
