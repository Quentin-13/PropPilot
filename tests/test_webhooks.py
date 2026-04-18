"""
Tests — Endpoints webhook leads et import CSV.
"""
from __future__ import annotations

import io
import os
import csv
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(_reset_db_between_tests):
    os.environ["TESTING"] = "true"
    from fastapi.testclient import TestClient
    from server import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _create_test_user(user_id: str = "test_user_wh"):
    """Crée un utilisateur de test en DB."""
    try:
        from memory.database import get_connection
        from memory.auth import _hash_password
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO users (id, email, password_hash, plan, plan_active)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO NOTHING""",
                (user_id, f"{user_id}@test.com", _hash_password("test123"), "Starter", True),
            )
        return True
    except Exception:
        return False


def test_webhook_leads_user_not_found(client, _reset_db_between_tests):
    """User inexistant → 404 (nécessite PostgreSQL)."""
    if not _reset_db_between_tests:
        pytest.skip("PostgreSQL non disponible")
    resp = client.post(
        "/webhooks/nonexistent_user_999/leads",
        json={"prenom": "Marie", "telephone": "+33600000001", "source": "seloger"},
    )
    assert resp.status_code == 404


def test_webhook_leads_creates_lead(client, _reset_db_between_tests, monkeypatch):
    """Webhook valide → lead créé + orchestrateur déclenché en background."""
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    user_created = _create_test_user("user_wh_001")
    if not user_created:
        pytest.skip("Impossible de créer l'utilisateur de test")

    # Mock orchestrateur pour ne pas déclencher de vrais appels
    monkeypatch.setattr(
        "server.process_incoming_message",
        lambda *a, **kw: {},
        raising=False,
    )

    resp = client.post(
        "/webhooks/user_wh_001/leads",
        json={
            "prenom": "Marie",
            "nom": "Dupont",
            "telephone": "+33600000001",
            "email": "marie@test.com",
            "source": "seloger",
            "projet": "achat",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "lead_id" in data
    assert len(data["lead_id"]) > 0


def test_webhook_leads_no_jwt_required(client, _reset_db_between_tests, monkeypatch):
    """Le webhook ne doit pas requérir de JWT — pas de header Authorization."""
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    _create_test_user("user_wh_002")
    monkeypatch.setattr(
        "server.process_incoming_message",
        lambda *a, **kw: {},
        raising=False,
    )

    # Appel sans header Authorization
    resp = client.post(
        "/webhooks/user_wh_002/leads",
        json={"telephone": "+33600000002", "source": "test"},
        # Pas d'header Authorization
    )
    # Ne doit pas retourner 401
    assert resp.status_code != 401


def test_api_leads_import_requires_jwt(client):
    """L'endpoint /api/leads/import requiert un JWT Bearer."""
    resp = client.post("/api/leads/import")
    assert resp.status_code == 401


def test_api_leads_import_csv(client, _reset_db_between_tests, monkeypatch):
    """Import CSV valide → leads créés."""
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    user_created = _create_test_user("user_import_001")
    if not user_created:
        pytest.skip("Impossible de créer l'utilisateur de test")

    from memory.auth import login
    try:
        token = login(f"user_import_001@test.com", "test123")
    except Exception:
        pytest.skip("Login non disponible")

    monkeypatch.setattr(
        "server.process_incoming_message",
        lambda *a, **kw: {},
        raising=False,
    )

    csv_content = "nom,prénom,téléphone,email\nDupont,Jean,+33600000010,jean@test.com\nMartin,Alice,+33600000011,alice@test.com"
    resp = client.post(
        "/api/leads/import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("leads.csv", csv_content.encode("utf-8"), "text/csv")},
        data={"source": "test_csv"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 2
    assert data["errors"] == []


def test_api_leads_import_missing_telephone(client, _reset_db_between_tests, monkeypatch):
    """Lignes CSV sans téléphone → erreurs."""
    db_ok = _reset_db_between_tests
    if not db_ok:
        pytest.skip("PostgreSQL non disponible")

    user_created = _create_test_user("user_import_002")
    if not user_created:
        pytest.skip("Impossible de créer l'utilisateur de test")

    from memory.auth import login
    try:
        token = login("user_import_002@test.com", "test123")
    except Exception:
        pytest.skip("Login non disponible")

    csv_content = "nom,prénom,email\nDupont,Jean,jean@test.com"
    resp = client.post(
        "/api/leads/import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("leads.csv", csv_content.encode("utf-8"), "text/csv")},
        data={"source": "test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert len(data["errors"]) == 1
