"""
Tests emails transactionnels PropPilot.
Vérifie les 6 templates + méthodes EmailTool + mock TESTING=true.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


# ─── Tests templates ──────────────────────────────────────────────────────────

class TestWelcomeSignup:
    def test_subject_contains_agency_name(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Agence Martin")
        assert "Agence Martin" in t["subject"]

    def test_subject_contains_emoji(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Agence Martin")
        assert "👋" in t["subject"]

    def test_html_contains_7_agents(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Agence Martin")
        for agent in ["Léa", "Marc", "Sophie", "Hugo", "Camille", "Thomas", "Julie"]:
            assert agent in t["html"]

    def test_html_contains_plans_url(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Agence Martin")
        assert "proppilot-dashboard-production" in t["html"]

    def test_text_contains_7_agents(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Agence Martin")
        assert "Léa" in t["text"]
        assert "Julie" in t["text"]

    def test_returns_subject_html_text(self):
        from tools.email_templates import welcome_signup
        t = welcome_signup("Test")
        assert "subject" in t and "html" in t and "text" in t


class TestPaymentConfirmed:
    def test_subject_contains_plan(self):
        from tools.email_templates import payment_confirmed
        t = payment_confirmed("Agence Test", "Pro")
        assert "Pro" in t["subject"]

    def test_subject_contains_checkmark(self):
        from tools.email_templates import payment_confirmed
        t = payment_confirmed("Agence Test", "Starter")
        assert "✅" in t["subject"]

    def test_html_contains_renewal_date(self):
        from tools.email_templates import payment_confirmed
        t = payment_confirmed("Agence Test", "Starter", renewal_date="15/04/2026")
        assert "15/04/2026" in t["html"]

    def test_html_auto_renewal_date(self):
        from tools.email_templates import payment_confirmed
        t = payment_confirmed("Agence Test", "Pro")
        # Date auto générée — doit contenir /
        assert "/" in t["html"]

    def test_all_plans_have_limits_line(self):
        from tools.email_templates import payment_confirmed
        for plan in ("Indépendant", "Starter", "Pro", "Elite"):
            t = payment_confirmed("Test", plan)
            assert plan in t["html"]

    def test_html_contains_dashboard_url(self):
        from tools.email_templates import payment_confirmed
        t = payment_confirmed("Agence", "Pro")
        assert "proppilot-dashboard-production" in t["html"]


class TestQuotaAlert80:
    def test_subject_contains_action_label(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "Minutes voix", 480, 600, "Indépendant")
        assert "Minutes voix" in t["subject"]

    def test_subject_contains_warning_emoji(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "SMS", 6400, 8000, "Starter")
        assert "⚠️" in t["subject"]

    def test_html_contains_percentage(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "Minutes voix", 480, 600, "Indépendant")
        assert "80" in t["html"]

    def test_html_contains_used_and_limit(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "SMS", 6400, 8000, "Starter")
        assert "6400" in t["html"]
        assert "8000" in t["html"]

    def test_html_contains_progress_bar(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "SMS", 6400, 8000, "Starter")
        assert "progress-bar" in t["html"]

    def test_tier_in_html(self):
        from tools.email_templates import quota_alert_80
        t = quota_alert_80("Agence Test", "SMS", 6400, 8000, "Pro")
        assert "Pro" in t["html"]


class TestPaymentFailed:
    def test_subject_contains_warning(self):
        from tools.email_templates import payment_failed
        t = payment_failed("Agence Test")
        assert "⚠️" in t["subject"]

    def test_html_contains_portal_url(self):
        from tools.email_templates import payment_failed
        t = payment_failed("Agence Test", portal_url="https://billing.stripe.com/test")
        assert "billing.stripe.com" in t["html"]

    def test_html_mentions_suspension(self):
        from tools.email_templates import payment_failed
        t = payment_failed("Agence Test")
        assert "7 jours" in t["html"]

    def test_text_contains_portal_url(self):
        from tools.email_templates import payment_failed
        t = payment_failed("Agence Test", portal_url="https://billing.stripe.com/test")
        assert "billing.stripe.com" in t["text"]


class TestSubscriptionCancelled:
    def test_subject_contains_cancelled(self):
        from tools.email_templates import subscription_cancelled
        t = subscription_cancelled("Agence Test")
        assert "annulé" in t["subject"].lower()

    def test_html_contains_end_date(self):
        from tools.email_templates import subscription_cancelled
        t = subscription_cancelled("Agence Test", end_date="31/03/2026")
        assert "31/03/2026" in t["html"]

    def test_html_mentions_data_retention(self):
        from tools.email_templates import subscription_cancelled
        t = subscription_cancelled("Agence Test")
        assert "90 jours" in t["html"]

    def test_html_contains_reactivate_url(self):
        from tools.email_templates import subscription_cancelled
        t = subscription_cancelled("Agence Test")
        assert "proppilot-dashboard-production" in t["html"]


class TestWeeklyReport:
    def test_subject_contains_date(self):
        from tools.email_templates import weekly_report
        t = weekly_report("Agence Test", "24/02/2026", {})
        assert "24/02/2026" in t["subject"]

    def test_subject_contains_emoji(self):
        from tools.email_templates import weekly_report
        t = weekly_report("Agence Test", "24/02/2026", {})
        assert "📊" in t["subject"]

    def test_html_contains_stats(self):
        from tools.email_templates import weekly_report
        stats = {"leads_recus": 42, "leads_qualifies": 18, "appels": 7, "rdv": 3, "mandats": 1, "roi_estime": 4200}
        t = weekly_report("Agence Test", "24/02/2026", stats)
        assert "42" in t["html"]
        assert "18" in t["html"]
        assert "3" in t["html"]

    def test_html_contains_roi_when_positive(self):
        from tools.email_templates import weekly_report
        stats = {"roi_estime": 14000}
        t = weekly_report("Agence Test", "24/02/2026", stats)
        assert "14" in t["html"]  # 14 000€

    def test_html_no_roi_when_zero(self):
        from tools.email_templates import weekly_report
        stats = {"roi_estime": 0}
        t = weekly_report("Agence Test", "24/02/2026", stats)
        assert "ROI estimé" not in t["html"]

    def test_text_contains_all_metrics(self):
        from tools.email_templates import weekly_report
        stats = {"leads_recus": 10, "leads_qualifies": 5, "appels": 3, "rdv": 2, "mandats": 1}
        t = weekly_report("Agence Test", "24/02/2026", stats)
        assert "10" in t["text"]
        assert "5" in t["text"]

    def test_taux_qualification_computed(self):
        from tools.email_templates import weekly_report
        stats = {"leads_recus": 10, "leads_qualifies": 8}
        t = weekly_report("Agence Test", "24/02/2026", stats)
        assert "80%" in t["html"]


# ─── Tests EmailTool mock ──────────────────────────────────────────────────────

class TestEmailToolMock:
    """TESTING=true → mock forcé même si SENDGRID_API_KEY est présente."""

    def _tool(self):
        from tools.email_tool import EmailTool
        return EmailTool()

    def test_mock_mode_active_in_testing(self):
        tool = self._tool()
        assert tool.mock_mode is True

    def test_send_returns_mock_true(self):
        tool = self._tool()
        result = tool.send("test@test.fr", "Test", "Sujet", "Corps")
        assert result["mock"] is True
        assert result["success"] is True

    def test_send_welcome_signup_mock(self):
        tool = self._tool()
        result = tool.send_welcome_signup("test@test.fr", "Agence Test")
        assert result["mock"] is True
        assert result["success"] is True

    def test_send_payment_confirmed_mock(self):
        tool = self._tool()
        result = tool.send_payment_confirmed("test@test.fr", "Agence Test", "Pro")
        assert result["mock"] is True

    def test_send_quota_alert_80_mock(self):
        tool = self._tool()
        result = tool.send_quota_alert_80("test@test.fr", "Agence Test", "SMS", 6400, 8000, "Starter")
        assert result["mock"] is True

    def test_send_payment_failed_mock(self):
        tool = self._tool()
        result = tool.send_payment_failed("test@test.fr", "Agence Test")
        assert result["mock"] is True

    def test_send_subscription_cancelled_mock(self):
        tool = self._tool()
        result = tool.send_subscription_cancelled("test@test.fr", "Agence Test")
        assert result["mock"] is True

    def test_send_weekly_report_mock(self):
        tool = self._tool()
        result = tool.send_weekly_report("test@test.fr", "Agence Test", "24/02/2026", {})
        assert result["mock"] is True

    def test_mock_with_sendgrid_key_present(self, monkeypatch):
        """TESTING=true doit forcer mock même si SENDGRID_API_KEY est définie."""
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake_key_for_test")
        monkeypatch.setenv("TESTING", "true")
        from config.settings import get_settings
        get_settings.cache_clear()
        from tools.email_tool import EmailTool
        tool = EmailTool()
        assert tool.mock_mode is True
        result = tool.send("test@test.fr", "Test", "Sujet", "Corps")
        assert result["mock"] is True
        get_settings.cache_clear()

    def test_all_methods_return_success(self):
        tool = self._tool()
        methods_and_args = [
            (tool.send_welcome_signup, ("a@b.fr", "Agence")),
            (tool.send_payment_confirmed, ("a@b.fr", "Agence", "Pro")),
            (tool.send_quota_alert_80, ("a@b.fr", "Agence", "SMS", 100, 120, "Starter")),
            (tool.send_payment_failed, ("a@b.fr", "Agence")),
            (tool.send_subscription_cancelled, ("a@b.fr", "Agence")),
            (tool.send_weekly_report, ("a@b.fr", "Agence", "01/03/2026", {})),
        ]
        for method, args in methods_and_args:
            result = method(*args)
            assert result["success"] is True, f"{method.__name__} failed"
