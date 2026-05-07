"""
Tests — dashboard/lib/admin_auth.py

Vérifie la logique de détection super-admin utilisée pour la redirection
post-login et la garde d'accès à la page 99_admin.
"""
from __future__ import annotations

import pytest


class TestIsSuperAdmin:
    def test_email_admin_retourne_true(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("contact@proppilot.fr") is True

    def test_email_non_admin_retourne_false(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("agent@uneagence.fr") is False

    def test_email_vide_retourne_false(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("") is False

    def test_email_none_retourne_false(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin(None) is False  # type: ignore

    def test_email_majuscules_detecte(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("CONTACT@PROPPILOT.FR") is True

    def test_email_espaces_detecte(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("  contact@proppilot.fr  ") is True

    def test_csv_multi_admins(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr,dev@proppilot.fr")
        from dashboard.lib.admin_auth import is_super_admin
        assert is_super_admin("dev@proppilot.fr") is True
        assert is_super_admin("contact@proppilot.fr") is True
        assert is_super_admin("autre@proppilot.fr") is False

    def test_valeur_par_defaut_sans_env(self, monkeypatch):
        monkeypatch.delenv("SUPER_ADMIN_EMAILS", raising=False)
        from dashboard.lib import admin_auth
        import importlib
        importlib.reload(admin_auth)
        assert admin_auth.is_super_admin("contact@proppilot.fr") is True
        assert admin_auth.is_super_admin("autre@example.com") is False


class TestGetAdminEmails:
    def test_retourne_liste_normalisee(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "  Admin@Test.fr , other@test.fr ")
        from dashboard.lib.admin_auth import get_admin_emails
        emails = get_admin_emails()
        assert "admin@test.fr" in emails
        assert "other@test.fr" in emails
        assert len(emails) == 2

    def test_entrees_vides_ignorees(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr,,  ,dev@proppilot.fr")
        from dashboard.lib.admin_auth import get_admin_emails
        emails = get_admin_emails()
        assert len(emails) == 2
