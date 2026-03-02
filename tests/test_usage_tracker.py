"""
Tests unitaires — UsageTracker.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.database import init_database
from memory.usage_tracker import check_and_consume, get_usage_summary


@pytest.fixture(autouse=True)
def setup_db(monkeypatch, _reset_db_between_tests):
    """Skippe tous les tests si PostgreSQL n'est pas disponible."""
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    if not _reset_db_between_tests:
        pytest.skip("PostgreSQL non disponible — tests DB ignorés")
    yield


def test_check_and_consume_allowed():
    """Consommation normale doit être autorisée."""
    result = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
    assert result["allowed"] is True
    assert result["current_usage"] == 1.0


def test_check_and_consume_increments():
    """Chaque consommation doit incrémenter correctement."""
    for i in range(5):
        result = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
        assert result["allowed"] is True
        assert result["current_usage"] == i + 1


def test_check_and_consume_limit_reached_voice():
    """Dépasser la limite voice_minute (1 500 Starter) doit bloquer."""
    # Consomme jusqu'à la limite en un seul appel pour aller vite
    check_and_consume("test_client", "voice_minute", amount=1499, tier="Starter")

    # Le dernier appel avant limite doit passer
    result_1500 = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
    assert result_1500["allowed"] is True

    # Au-delà de 1 500 doit être bloqué
    result_over = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
    assert result_over["allowed"] is False
    assert "limite" in result_over["message"].lower() or "contact" in result_over["message"].lower()


def test_check_and_consume_limit_reached_sms():
    """Dépasser la limite SMS (8 000 Starter) doit bloquer."""
    check_and_consume("test_client", "followup", amount=8000, tier="Starter")
    result_over = check_and_consume("test_client", "followup", amount=1, tier="Starter")
    assert result_over["allowed"] is False
    assert "contact@proppilot.fr" in result_over["message"]


def test_leads_unlimited_starter():
    """Leads sont illimités sur Starter."""
    for _ in range(500):
        result = check_and_consume("test_client", "lead", amount=1, tier="Starter")
        assert result["allowed"] is True
    assert result["remaining"] is None


def test_elite_unlimited():
    """Elite n'a pas de limite sur voice ni SMS."""
    for _ in range(3000):
        result = check_and_consume("elite_client", "voice_minute", amount=1, tier="Elite")
        assert result["allowed"] is True
    assert result["remaining"] is None

    for _ in range(10000):
        result = check_and_consume("elite_client", "followup", amount=1, tier="Elite")
        assert result["allowed"] is True
    assert result["remaining"] is None


def test_usage_summary_returns_all_metrics():
    """Le résumé doit contenir toutes les métriques métier."""
    check_and_consume("test_client", "voice_minute", amount=5, tier="Starter")
    check_and_consume("test_client", "followup", amount=10, tier="Starter")

    summary = get_usage_summary("test_client", "Starter")

    assert "leads" in summary
    assert "voice" in summary
    assert "images" in summary
    assert "followups" in summary
    assert "listings" in summary
    assert "estimations" in summary

    assert summary["voice"]["used"] == 5.0
    assert summary["followups"]["used"] == 10

    # Leads sont illimités (None limit, pct=0)
    assert summary["leads"]["limit"] is None
    assert summary["leads"]["pct"] == 0.0

    # Voice a une limite (900 Starter)
    assert summary["voice"]["limit"] == 1_500.0
    assert summary["voice"]["pct"] == pytest.approx(5 / 1500 * 100, rel=1e-3)

    # SMS a une limite (8 000 Starter)
    assert summary["followups"]["limit"] == 8_000
    assert summary["followups"]["pct"] == pytest.approx(10 / 8000 * 100, rel=1e-3)


def test_usage_summary_no_api_costs():
    """Le résumé client ne doit JAMAIS exposer api_cost_euros."""
    summary = get_usage_summary("test_client", "Starter")
    summary_str = str(summary)
    assert "api_cost" not in summary_str
    assert "euros" not in summary_str


def test_different_clients_isolated():
    """Les usages de différents clients doivent être isolés."""
    check_and_consume("client_a", "voice_minute", amount=10, tier="Starter")
    check_and_consume("client_b", "voice_minute", amount=5, tier="Pro")

    summary_a = get_usage_summary("client_a", "Starter")
    summary_b = get_usage_summary("client_b", "Pro")

    assert summary_a["voice"]["used"] == 10.0
    assert summary_b["voice"]["used"] == 5.0


def test_alert_at_80_pct_voice():
    """Alerte progressive à 80% d'utilisation des minutes voix."""
    # 80% de 1 500 = 1 200 minutes
    check_and_consume("test_client", "voice_minute", amount=1200, tier="Starter")
    result = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
    assert result["allowed"] is True
    assert "approch" in result["message"].lower() or "contact" in result["message"].lower()


def test_alert_at_80_pct_sms():
    """Alerte progressive à 80% d'utilisation des SMS."""
    # 80% de 8 000 = 6 400 SMS
    check_and_consume("test_client", "followup", amount=6400, tier="Starter")
    result = check_and_consume("test_client", "followup", amount=1, tier="Starter")
    assert result["allowed"] is True
    assert "approch" in result["message"].lower() or "contact" in result["message"].lower()


def test_80pct_email_alert_sent():
    """Un email d'alerte est envoyé automatiquement lors de la traversée du seuil 80%."""
    sent_emails = []

    def mock_send(self, to_email, to_name, subject, body_text, **kwargs):
        sent_emails.append({"to": to_email, "subject": subject})
        return {"success": True, "mock": True}

    with patch("tools.email_tool.EmailTool.send", mock_send):
        # Consomme 79% de 1 500 = 1 185 minutes (pas d'alerte)
        check_and_consume(
            "test_client", "voice_minute", amount=1185, tier="Starter",
            contact_email="agent@agence.fr", contact_name="Jean Dupont",
        )
        assert len(sent_emails) == 0

        # La consommation suivante traverse le seuil 80% → alerte
        check_and_consume(
            "test_client", "voice_minute", amount=10, tier="Starter",
            contact_email="agent@agence.fr", contact_name="Jean Dupont",
        )
        assert len(sent_emails) == 1
        assert "80" in sent_emails[0]["subject"] or "⚠️" in sent_emails[0]["subject"]

        # Les appels suivants au-dessus de 80% n'envoient plus d'alerte
        check_and_consume(
            "test_client", "voice_minute", amount=10, tier="Starter",
            contact_email="agent@agence.fr", contact_name="Jean Dupont",
        )
        assert len(sent_emails) == 1  # Toujours 1


def test_no_email_without_contact():
    """Sans contact_email, pas d'alerte même à 80%."""
    sent_emails = []

    def mock_send(self, *args, **kwargs):
        sent_emails.append(True)
        return {"success": True, "mock": True}

    with patch("tools.email_tool.EmailTool.send", mock_send):
        check_and_consume("test_client", "voice_minute", amount=1200, tier="Starter")
        assert len(sent_emails) == 0


def test_voice_minutes_fractional():
    """Les minutes voix supportent les valeurs décimales."""
    result = check_and_consume("test_client", "voice_minute", amount=2.5, tier="Starter")
    assert result["allowed"] is True

    result2 = check_and_consume("test_client", "voice_minute", amount=1.3, tier="Starter")
    assert result2["allowed"] is True
    assert abs(result2["current_usage"] - 3.8) < 0.01


def test_upgrade_message_contains_contact():
    """Les messages de dépassement de limite doivent mentionner contact@proppilot.fr."""
    check_and_consume("test_client", "voice_minute", amount=1500, tier="Starter")
    result = check_and_consume("test_client", "voice_minute", amount=1, tier="Starter")
    assert result["allowed"] is False
    assert "contact@proppilot.fr" in result["message"]
