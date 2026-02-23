"""
Tests unitaires — UsageTracker.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.database import init_database
from memory.usage_tracker import check_and_consume, get_usage_summary


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    from config.settings import get_settings
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


def test_check_and_consume_allowed():
    """Consommation normale doit être autorisée."""
    result = check_and_consume("test_client", "lead", amount=1, tier="Starter")
    assert result["allowed"] is True
    assert result["current_usage"] == 1.0


def test_check_and_consume_increments():
    """Chaque consommation doit incrémenter correctement."""
    for i in range(5):
        result = check_and_consume("test_client", "lead", amount=1, tier="Starter")
        assert result["allowed"] is True
        assert result["current_usage"] == i + 1


def test_check_and_consume_limit_reached():
    """Dépasser la limite doit bloquer."""
    # Starter : 300 leads/mois
    # Consomme jusqu'à la limite - 1
    for _ in range(299):
        check_and_consume("test_client", "lead", amount=1, tier="Starter")

    # Le 300ème doit passer
    result_300 = check_and_consume("test_client", "lead", amount=1, tier="Starter")
    assert result_300["allowed"] is True

    # Le 301ème doit être bloqué
    result_301 = check_and_consume("test_client", "lead", amount=1, tier="Starter")
    assert result_301["allowed"] is False
    assert "limite" in result_301["message"].lower() or "Limite" in result_301["message"]


def test_elite_unlimited():
    """Elite n'a pas de limite sur les leads."""
    for _ in range(500):
        result = check_and_consume("elite_client", "lead", amount=1, tier="Elite")
        assert result["allowed"] is True
    assert result["remaining"] is None


def test_usage_summary_returns_all_metrics():
    """Le résumé doit contenir toutes les métriques métier."""
    check_and_consume("test_client", "lead", amount=5, tier="Starter")
    check_and_consume("test_client", "followup", amount=10, tier="Starter")

    summary = get_usage_summary("test_client", "Starter")

    assert "leads" in summary
    assert "voice" in summary
    assert "images" in summary
    assert "followups" in summary
    assert "listings" in summary
    assert "estimations" in summary

    assert summary["leads"]["used"] == 5
    assert summary["followups"]["used"] == 10
    assert summary["leads"]["limit"] == 300
    assert summary["leads"]["pct"] == pytest.approx(5 / 300 * 100, rel=1e-3)


def test_usage_summary_no_api_costs():
    """Le résumé client ne doit JAMAIS exposer api_cost_euros."""
    summary = get_usage_summary("test_client", "Starter")
    summary_str = str(summary)
    assert "api_cost" not in summary_str
    assert "euros" not in summary_str


def test_different_clients_isolated():
    """Les usages de différents clients doivent être isolés."""
    check_and_consume("client_a", "lead", amount=10, tier="Starter")
    check_and_consume("client_b", "lead", amount=5, tier="Pro")

    summary_a = get_usage_summary("client_a", "Starter")
    summary_b = get_usage_summary("client_b", "Pro")

    assert summary_a["leads"]["used"] == 10
    assert summary_b["leads"]["used"] == 5


def test_alert_at_80_pct():
    """Alerte progressive à 80% d'utilisation."""
    # Consomme 80% de 300 = 240 leads
    check_and_consume("test_client", "lead", amount=240, tier="Starter")
    result = check_and_consume("test_client", "lead", amount=1, tier="Starter")
    assert result["allowed"] is True
    assert "approch" in result["message"].lower() or "limit" in result["message"].lower() or "reste" in result["message"]


def test_voice_minutes_fractional():
    """Les minutes voix supportent les valeurs décimales."""
    result = check_and_consume("test_client", "voice_minute", amount=2.5, tier="Starter")
    assert result["allowed"] is True

    result2 = check_and_consume("test_client", "voice_minute", amount=1.3, tier="Starter")
    assert result2["allowed"] is True
    assert abs(result2["current_usage"] - 3.8) < 0.01
