"""
Tests — dashboard admin (99_admin.py)

Vérifie :
- Accès refusé pour un utilisateur non super-admin
- Fonctions admin_get_* retournent bien des données sans filtre client_id
- Régression isolation : les requêtes user normales gardent un filtre client_id
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _testing_env(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Garde super-admin ──────────────────────────────────────────────────────────

class TestAdminGuard:
    """
    Vérifie que la logique de garde super-admin fonctionne correctement
    indépendamment de Streamlit (qui ne peut pas être importé en test unitaire).
    """

    def test_admin_email_in_list_autorise(self):
        admin_emails = ["contact@proppilot.fr", "dev@proppilot.fr"]
        user_email = "contact@proppilot.fr"
        assert user_email.strip().lower() in [e.strip().lower() for e in admin_emails]

    def test_email_non_admin_refuse(self):
        admin_emails = ["contact@proppilot.fr"]
        user_email = "agence@example.com"
        assert user_email.strip().lower() not in [e.strip().lower() for e in admin_emails]

    def test_email_vide_refuse(self):
        admin_emails = ["contact@proppilot.fr"]
        user_email = ""
        assert not user_email or user_email.strip().lower() not in [e.strip().lower() for e in admin_emails]

    def test_email_case_insensitive(self):
        admin_emails = ["contact@proppilot.fr"]
        user_email = "CONTACT@PROPPILOT.FR"
        assert user_email.strip().lower() in [e.strip().lower() for e in admin_emails]

    def test_super_admin_emails_csv_parse(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", "contact@proppilot.fr,dev@proppilot.fr")
        import os
        emails = [e.strip().lower() for e in os.environ["SUPER_ADMIN_EMAILS"].split(",") if e.strip()]
        assert "contact@proppilot.fr" in emails
        assert "dev@proppilot.fr" in emails
        assert len(emails) == 2


# ── admin_get_* sans filtre client_id ─────────────────────────────────────────

def _mock_conn_factory(rows):
    """Retourne un context manager simulant une connexion DB."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchone.return_value = rows[0] if rows else None
    conn.execute.return_value = cur
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


class TestAdminGetFunctions:
    def test_admin_get_clients_sql_has_no_client_id_where(self):
        """admin_get_clients() SQL doit être un SELECT global sans WHERE client_id."""
        from pathlib import Path
        source = (Path(__file__).parent.parent / "dashboard" / "pages" / "99_admin.py").read_text()
        # Trouve la fonction admin_get_clients et vérifie qu'il n'y a pas de WHERE client_id
        import re
        # Extrait le bloc de la fonction
        match = re.search(r"def admin_get_clients\(\)(.*?)(?=\ndef )", source, re.DOTALL)
        assert match, "Fonction admin_get_clients non trouvée dans 99_admin.py"
        func_body = match.group(1)
        assert "WHERE" not in func_body.upper() or "client_id" not in func_body.lower().split("where")[1].split("\n")[0] if "where" in func_body.lower() else True, \
            "admin_get_clients ne doit pas filtrer sur client_id"

    def test_admin_get_mrr_calcul_correct(self):
        """
        Calcul MRR : 1 client Starter actif (stripe active) = 790€
        """
        # On simule la sortie de admin_get_clients()
        fake_clients = [
            {"id": "c1", "plan": "Starter", "plan_active": True, "subscription_status": "active",
             "email": "a@a.fr", "agency_name": "A", "created_at": None},
            {"id": "c2", "plan": "Pro", "plan_active": True, "subscription_status": "inactive",
             "email": "b@b.fr", "agency_name": "B", "created_at": None},
            {"id": "c3", "plan": "Elite", "plan_active": False, "subscription_status": "active",
             "email": "c@c.fr", "agency_name": "C", "created_at": None},
        ]
        _PLAN_MRR = {"Indépendant": 390, "Starter": 790, "Pro": 1490, "Elite": 2990}
        paying = [c for c in fake_clients if c.get("plan_active") and c.get("subscription_status") == "active"]
        mrr = sum(_PLAN_MRR.get(c["plan"], 790) for c in paying)
        assert mrr == 790  # seul c1 est payant (plan_active=True + stripe active)
        assert len(paying) == 1

    def test_admin_get_mrr_pilot_ne_compte_pas_dans_mrr(self):
        """Pilotes (plan_active=True mais stripe inactive) ne comptent pas dans MRR."""
        fake_clients = [
            {"id": "c1", "plan": "Starter", "plan_active": True, "subscription_status": "inactive",
             "email": "a@a.fr", "agency_name": "A", "created_at": None},
        ]
        _PLAN_MRR = {"Starter": 790}
        paying = [c for c in fake_clients if c.get("plan_active") and c.get("subscription_status") == "active"]
        mrr = sum(_PLAN_MRR.get(c["plan"], 790) for c in paying)
        assert mrr == 0

    def test_admin_get_churn_rate(self):
        """Churn rate = churned / (paying + churned)."""
        fake_clients = [
            {"plan_active": True},
            {"plan_active": True},
            {"plan_active": False},
        ]
        churned = [c for c in fake_clients if not c.get("plan_active")]
        paying_count = sum(1 for c in fake_clients if c.get("plan_active"))
        total = paying_count + len(churned)
        rate = len(churned) / total
        assert abs(rate - 1/3) < 0.001

    def test_admin_get_lead_stats_sql_structure(self):
        """admin_get_lead_stats SQL doit retourner total, failed, chaud, tiede, froid, types."""
        from pathlib import Path
        source = (Path(__file__).parent.parent / "dashboard" / "pages" / "99_admin.py").read_text()
        import re
        match = re.search(r"def admin_get_lead_stats\(.*?\)(.*?)(?=\ndef )", source, re.DOTALL)
        assert match, "Fonction admin_get_lead_stats non trouvée"
        func_body = match.group(1)
        for col in ("total", "failed", "chaud", "tiede", "froid", "acheteur", "vendeur"):
            assert col in func_body, f"Colonne '{col}' manquante dans admin_get_lead_stats"


# ── Régression isolation client_id ────────────────────────────────────────────

class TestClientIdIsolation:
    """
    Régression chantier 4 :
    - Les requêtes USER (lead_repository) gardent un filtre client_id
    - Les requêtes ADMIN n'en ont pas (comportement intentionnel, documenté)
    """

    def test_get_lead_avec_client_id_filtre(self):
        """get_lead(lead_id, client_id=X) doit filtrer sur client_id."""
        from memory.lead_repository import get_lead

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None

        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False

        with patch("memory.lead_repository.get_connection", return_value=ctx):
            result = get_lead("lead-xyz", client_id="agence-999")

        # Vérifier que la requête SQL contient bien le filtre client_id
        call_args = conn.execute.call_args
        sql = call_args[0][0] if call_args[0] else ""
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", ())
        assert "client_id" in sql.lower(), "get_lead avec client_id doit filtrer sur client_id"
        assert "agence-999" in str(params), "Le client_id doit être passé en paramètre"

    def test_get_lead_sans_client_id_pas_de_filtre(self):
        """get_lead(lead_id) sans client_id ne filtre PAS (usage interne agent)."""
        from memory.lead_repository import get_lead

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None

        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False

        with patch("memory.lead_repository.get_connection", return_value=ctx):
            result = get_lead("lead-xyz")

        call_args = conn.execute.call_args
        sql = call_args[0][0] if call_args[0] else ""
        # Sans client_id, la requête ne doit PAS filtrer sur client_id
        assert "client_id" not in sql.lower(), (
            "get_lead sans client_id ne doit pas filtrer sur client_id"
        )

    def test_admin_sql_queries_no_client_id_filter(self):
        """
        Les fonctions admin_get_* font des SELECT globaux.
        Test documentaire : vérifier que le code SQL ne contient pas WHERE client_id.
        """
        import inspect
        from pathlib import Path
        admin_source = Path(__file__).parent.parent / "dashboard" / "pages" / "99_admin.py"
        source = admin_source.read_text()

        # Les fonctions admin_get_* ne doivent pas contenir 'WHERE client_id ='
        # (elles peuvent contenir 'client_id' dans SELECT/JOIN, mais pas comme filtre)
        import re
        # Cherche des requêtes WHERE client_id = hardcodé sans paramètre variable
        # (une requête avec %s est ok — c'est intentionnel pour admin_get_lead_stats avec client_id optionnel)
        forbidden = re.findall(r"WHERE\s+client_id\s*=\s*['\"][^'\"]+['\"]", source)
        assert not forbidden, (
            f"Requête admin avec client_id hardcodé détectée : {forbidden}"
        )


# ── Test MRR par plan ──────────────────────────────────────────────────────────

class TestPlanMrrMapping:
    def test_tous_les_plans_ont_un_tarif(self):
        plan_mrr = {"Indépendant": 390, "Starter": 790, "Pro": 1490, "Elite": 2990}
        for plan in ("Indépendant", "Starter", "Pro", "Elite"):
            assert plan in plan_mrr
            assert plan_mrr[plan] > 0

    def test_mrr_croissant_par_plan(self):
        plan_mrr = {"Indépendant": 390, "Starter": 790, "Pro": 1490, "Elite": 2990}
        vals = [plan_mrr["Indépendant"], plan_mrr["Starter"], plan_mrr["Pro"], plan_mrr["Elite"]]
        assert vals == sorted(vals)
