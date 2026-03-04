"""
Tests Stripe — webhooks, activation/désactivation, middleware 402.
TESTING=true force le mock de tous les appels Stripe réels.
Skip automatique si PostgreSQL indisponible (tests DB).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_stripe_env(monkeypatch, _reset_db_between_tests):
    """
    Avant chaque test :
      - TESTING=true → mock automatique Stripe, SendGrid, Twilio
      - Variables Stripe présentes mais ignorées (TESTING prend le dessus)
    """
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock_key")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_mock_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_mock_secret")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_required(_reset_db_between_tests):
    """Skip si PostgreSQL n'est pas disponible localement."""
    if not _reset_db_between_tests:
        pytest.skip("PostgreSQL non disponible — test DB ignoré")
    yield


@pytest.fixture
def api_client():
    """Client de test FastAPI (lifespan gracieux si DB absente en mode test)."""
    from fastapi.testclient import TestClient
    from server import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ─── Constantes Stripe ────────────────────────────────────────────────────────

def test_stripe_price_ids_all_plans():
    """Les 4 forfaits ont tous un price_id défini."""
    from memory.stripe_billing import STRIPE_PRICE_IDS
    assert set(STRIPE_PRICE_IDS.keys()) == {"Indépendant", "Starter", "Pro", "Elite"}


def test_stripe_price_ids_values():
    """Les price_id correspondent aux valeurs fournies."""
    from memory.stripe_billing import STRIPE_PRICE_IDS
    assert STRIPE_PRICE_IDS["Indépendant"] == "price_1T7HCOL2FehJuqYZbPX1cpIK"
    assert STRIPE_PRICE_IDS["Starter"]     == "price_1T6U3DL2FehJuqYZSnHDZRcF"
    assert STRIPE_PRICE_IDS["Pro"]         == "price_1T6U3PL2FehJuqYZ5xK5YDJ3"
    assert STRIPE_PRICE_IDS["Elite"]       == "price_1T6U3dL2FehJuqYZ7VoAwlGn"


def test_plan_features_all_plans():
    """PLAN_FEATURES couvre les 4 forfaits avec les champs requis."""
    from memory.stripe_billing import PLAN_FEATURES
    assert set(PLAN_FEATURES.keys()) == {"Indépendant", "Starter", "Pro", "Elite"}
    for plan_name, info in PLAN_FEATURES.items():
        assert "prix" in info, f"{plan_name} manque 'prix'"
        assert "features" in info, f"{plan_name} manque 'features'"
        assert len(info["features"]) > 0, f"{plan_name} : features vides"
        assert "voix" in info
        assert "sms" in info


def test_plan_features_order():
    """L'ordre des plans est Indépendant → Starter → Pro → Elite."""
    from memory.stripe_billing import PLAN_FEATURES
    assert list(PLAN_FEATURES.keys()) == ["Indépendant", "Starter", "Pro", "Elite"]


# ─── create_checkout_session (mock) ──────────────────────────────────────────

def test_checkout_session_mock_returns_url():
    """En TESTING mode, crée une URL simulée sans appel Stripe."""
    from memory.stripe_billing import create_checkout_session
    result = create_checkout_session(
        user_id="user_abc",
        plan_name="Starter",
        customer_email="test@agence.fr",
        success_url="http://localhost:8501/success",
        cancel_url="http://localhost:8501/facturation",
    )
    assert "error" not in result
    assert "checkout_url" in result
    assert result.get("mock") is True
    assert "Starter" in result["checkout_url"] or "user_abc" in result.get("session_id", "")


def test_checkout_session_all_plans_mock():
    """Tous les forfaits génèrent une URL mock sans erreur."""
    from memory.stripe_billing import create_checkout_session
    for plan in ("Indépendant", "Starter", "Pro", "Elite"):
        result = create_checkout_session(
            user_id="u1", plan_name=plan,
            customer_email="x@y.fr",
            success_url="http://localhost/ok",
            cancel_url="http://localhost/cancel",
        )
        assert "error" not in result, f"Erreur pour {plan}: {result}"
        assert "checkout_url" in result


def test_checkout_session_unknown_plan():
    """Un plan inconnu retourne une erreur."""
    from memory.stripe_billing import create_checkout_session
    result = create_checkout_session(
        user_id="u1", plan_name="PlanInexistant",
        customer_email="x@y.fr",
        success_url="http://localhost/ok",
        cancel_url="http://localhost/cancel",
    )
    assert "error" in result


def test_create_portal_session_mock_no_db():
    """create_portal_session en mode mock ne nécessite pas la DB."""
    from memory.stripe_billing import create_portal_session

    with patch("memory.stripe_billing.get_user_subscription_info") as mock_info:
        mock_info.return_value = None
        # En mock mode (TESTING=True), on ne touche pas à la DB
        result = create_portal_session(user_id="u1", return_url="http://localhost/")
        assert "portal_url" in result
        assert result.get("mock") is True


# ─── Activation / Désactivation (DB) ─────────────────────────────────────────

def test_activate_subscription(db_required):
    """checkout.session.completed → plan actif + infos Stripe en DB."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription, is_plan_active, get_user_subscription_info

    user = signup("stripe_activate@agence.fr", "pass1234", "Agence Activate")
    user_id = user["user_id"]
    assert is_plan_active(user_id) is True

    activate_subscription(
        user_id=user_id,
        plan_name="Pro",
        stripe_customer_id="cus_test_activate",
        stripe_subscription_id="sub_test_activate",
    )

    info = get_user_subscription_info(user_id)
    assert info["plan"] == "Pro"
    assert info["plan_active"] is True
    assert info["stripe_customer_id"] == "cus_test_activate"
    assert info["stripe_subscription_id"] == "sub_test_activate"
    assert info["subscription_status"] == "active"


def test_activate_subscription_independant(db_required):
    """Le forfait Indépendant s'active correctement."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription, get_user_subscription_info

    user = signup("stripe_indep@agence.fr", "pass1234", "Agence Indep")
    activate_subscription(
        user_id=user["user_id"],
        plan_name="Indépendant",
        stripe_customer_id="cus_indep",
        stripe_subscription_id="sub_indep",
    )
    info = get_user_subscription_info(user["user_id"])
    assert info["plan"] == "Indépendant"
    assert info["plan_active"] is True


def test_deactivate_subscription(db_required):
    """customer.subscription.deleted → plan_active=False en DB."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription, deactivate_subscription, is_plan_active

    user = signup("stripe_deact@agence.fr", "pass1234", "Agence Deact")
    user_id = user["user_id"]

    activate_subscription(user_id, "Starter", "cus_deact", "sub_deact")
    assert is_plan_active(user_id) is True

    deactivate_subscription("sub_deact")
    assert is_plan_active(user_id) is False


def test_deactivate_unknown_subscription(db_required):
    """Désactiver un sub_id inconnu ne plante pas."""
    from memory.stripe_billing import deactivate_subscription
    result = deactivate_subscription("sub_does_not_exist")
    assert result is None


def test_set_past_due(db_required):
    """invoice.payment_failed → subscription_status = past_due."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription, set_past_due, get_user_subscription_info

    user = signup("stripe_pastdue@agence.fr", "pass1234", "Agence PastDue")
    activate_subscription(user["user_id"], "Elite", "cus_pastdue", "sub_pastdue")

    user_info = set_past_due("cus_pastdue")
    assert user_info is not None
    assert "agency_name" in user_info

    info = get_user_subscription_info(user["user_id"])
    assert info["subscription_status"] == "past_due"
    assert info["plan_active"] is True  # past_due ne désactive pas immédiatement


def test_is_plan_active_unknown_user(db_required):
    """is_plan_active retourne False pour un user inexistant."""
    from memory.stripe_billing import is_plan_active
    assert is_plan_active("user_id_inexistant_xyz") is False


# ─── Endpoint GET /stripe/plans ──────────────────────────────────────────────

def test_stripe_plans_endpoint(api_client):
    """GET /stripe/plans retourne les 4 forfaits dans l'ordre."""
    resp = api_client.get("/stripe/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert "plans" in data
    assert len(data["plans"]) == 4
    plan_names = [p["name"] for p in data["plans"]]
    assert plan_names == ["Indépendant", "Starter", "Pro", "Elite"]


def test_stripe_plans_fields(api_client):
    """Chaque forfait contient les champs requis."""
    resp = api_client.get("/stripe/plans")
    for plan in resp.json()["plans"]:
        assert "name" in plan
        assert "price_id" in plan
        assert "prix_mensuel" in plan
        assert "features" in plan
        assert len(plan["features"]) > 0


def test_stripe_plans_prices(api_client):
    """Les prix correspondent aux valeurs définies."""
    resp = api_client.get("/stripe/plans")
    prices = {p["name"]: p["prix_mensuel"] for p in resp.json()["plans"]}
    assert prices["Indépendant"] == 290
    assert prices["Starter"] == 790
    assert prices["Pro"] == 1490
    assert prices["Elite"] == 2990


# ─── Webhooks FastAPI ─────────────────────────────────────────────────────────

def _webhook_payload(event_type: str, data_object: dict) -> bytes:
    return json.dumps({
        "id": "evt_test_mock",
        "type": event_type,
        "data": {"object": data_object},
    }).encode()


def test_webhook_unknown_event(api_client):
    """Un événement inconnu est ignoré (200 OK)."""
    payload = _webhook_payload("some.unknown.event", {"id": "obj_test"})
    resp = api_client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["event"] == "some.unknown.event"


def test_webhook_invalid_json(api_client):
    """Un payload JSON invalide retourne 400."""
    resp = api_client.post(
        "/stripe/webhook",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_webhook_checkout_completed(api_client, db_required):
    """checkout.session.completed active l'abonnement en DB."""
    from memory.auth import signup
    from memory.stripe_billing import get_user_subscription_info

    user = signup("webhook_checkout@agence.fr", "pass1234", "Agence Webhook")
    user_id = user["user_id"]

    payload = _webhook_payload("checkout.session.completed", {
        "client_reference_id": user_id,
        "metadata": {"user_id": user_id, "plan": "Pro"},
        "customer": "cus_wh_checkout",
        "subscription": "sub_wh_checkout",
    })
    resp = api_client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    info = get_user_subscription_info(user_id)
    assert info["plan"] == "Pro"
    assert info["plan_active"] is True
    assert info["subscription_status"] == "active"


def test_webhook_checkout_completed_no_user(api_client, db_required):
    """checkout.session.completed sans client_reference_id est ignoré silencieusement."""
    payload = _webhook_payload("checkout.session.completed", {
        "metadata": {},
        "customer": "cus_nobody",
        "subscription": "sub_nobody",
    })
    resp = api_client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200


def test_webhook_subscription_deleted(api_client, db_required):
    """customer.subscription.deleted désactive le compte."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription, is_plan_active

    user = signup("webhook_deleted@agence.fr", "pass1234", "Agence Deleted")
    user_id = user["user_id"]
    activate_subscription(user_id, "Starter", "cus_del", "sub_del_test")
    assert is_plan_active(user_id) is True

    payload = _webhook_payload("customer.subscription.deleted", {
        "id": "sub_del_test",
        "customer": "cus_del",
        "status": "canceled",
    })
    resp = api_client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert is_plan_active(user_id) is False


def test_webhook_payment_failed_sends_email(api_client, db_required):
    """invoice.payment_failed envoie un email d'alerte au client."""
    from memory.auth import signup
    from memory.stripe_billing import activate_subscription

    user = signup("webhook_failed@agence.fr", "pass1234", "Agence Failed")
    activate_subscription(user["user_id"], "Pro", "cus_fail", "sub_fail")

    sent_emails: list[dict] = []

    def mock_send(self, to_email, to_name, subject, body_text, **kwargs):
        sent_emails.append({"to": to_email, "subject": subject})
        return {"success": True, "mock": True}

    with patch("tools.email_tool.EmailTool.send", mock_send):
        payload = _webhook_payload("invoice.payment_failed", {
            "id": "in_test",
            "customer": "cus_fail",
            "subscription": "sub_fail",
            "customer_email": "webhook_failed@agence.fr",
        })
        resp = api_client.post(
            "/stripe/webhook",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    assert len(sent_emails) == 1
    assert "webhook_failed@agence.fr" in sent_emails[0]["to"]
    assert "⚠️" in sent_emails[0]["subject"] or "paiement" in sent_emails[0]["subject"].lower()


def test_webhook_payment_failed_no_customer(api_client, db_required):
    """invoice.payment_failed sans customer est ignoré silencieusement."""
    payload = _webhook_payload("invoice.payment_failed", {
        "id": "in_nobody",
        "customer": "",
    })
    resp = api_client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200


# ─── Middleware plan_active ───────────────────────────────────────────────────

def test_api_blocked_if_plan_inactive(api_client, db_required):
    """
    /api/* retourne 402 si plan_active=False.
    Scénario : utilisateur connecté, puis abonnement résilié via Stripe.
    """
    from memory.auth import signup, login
    from memory.database import get_connection

    user = signup("blocked@agence.fr", "pass1234", "Agence Blocked")
    user_id = user["user_id"]

    # Obtenir un token valide (plan_active=True)
    token = login("blocked@agence.fr", "pass1234")

    # Simuler résiliation Stripe → plan_active=False
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET plan_active = FALSE WHERE id = ?",
            (user_id,),
        )

    # Le token est encore valide JWT, mais le middleware doit bloquer
    resp = api_client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 402
    detail = resp.json().get("detail", "")
    assert "inactif" in detail.lower() or "abonnement" in detail.lower()


def test_api_allowed_if_plan_active(api_client, db_required):
    """
    /api/* est accessible si plan_active=True.
    """
    from memory.auth import signup, login

    user = signup("active@agence.fr", "pass1234", "Agence Active")
    token = login("active@agence.fr", "pass1234")

    resp = api_client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Pas de 401 ni de 402 — l'accès est autorisé (500 possible si services mock)
    assert resp.status_code not in (401, 402)


def test_api_no_token_returns_401(api_client):
    """Sans token, /api/* retourne 401."""
    resp = api_client.get("/api/status")
    assert resp.status_code == 401


def test_api_invalid_token_returns_401(api_client):
    """Avec un token invalide, /api/* retourne 401."""
    resp = api_client.get(
        "/api/status",
        headers={"Authorization": "Bearer token_invalide_xyz"},
    )
    assert resp.status_code == 401


# ─── Endpoint checkout-session (auth) ────────────────────────────────────────

def test_checkout_requires_auth(api_client):
    """POST /stripe/create-checkout-session sans token → 401."""
    resp = api_client.post(
        "/stripe/create-checkout-session",
        json={"plan": "Starter"},
    )
    assert resp.status_code == 401


def test_portal_requires_auth(api_client):
    """GET /stripe/portal sans token → 401."""
    resp = api_client.get("/stripe/portal")
    assert resp.status_code == 401
