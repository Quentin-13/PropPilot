"""
Stripe billing — activation abonnements, webhooks, portail client.
Mock automatique si TESTING=true ou STRIPE_SECRET_KEY absent.
"""
from __future__ import annotations

import logging
from typing import Optional

from urllib.parse import quote

from config.settings import get_settings
from memory.database import get_connection

logger = logging.getLogger(__name__)


# ─── Constantes ───────────────────────────────────────────────────────────────

STRIPE_PRICE_IDS: dict[str, str] = {
    "Indépendant": "price_1T6U2dL2FehJuqYZsSHK11T7",
    "Starter":     "price_1T6U3DL2FehJuqYZSnHDZRcF",
    "Pro":         "price_1T6U3PL2FehJuqYZ5xK5YDJ3",
    "Elite":       "price_1T6U3dL2FehJuqYZ7VoAwlGn",
}

PLAN_FEATURES: dict[str, dict] = {
    "Indépendant": {
        "prix": "390€/mois",
        "voix": "600 min",
        "sms": "3 000 SMS",
        "utilisateurs": "1 utilisateur",
        "features": [
            "Tous les agents IA",
            "600 min voix/mois",
            "3 000 follow-ups SMS",
            "Leads illimités",
            "Annonces illimitées",
            "Estimations illimitées",
            "Garantie ROI 60j — remboursement 50%",
        ],
    },
    "Starter": {
        "prix": "790€/mois",
        "voix": "1 500 min",
        "sms": "8 000 SMS",
        "utilisateurs": "3 utilisateurs",
        "features": [
            "Tous les agents IA",
            "1 500 min voix/mois",
            "8 000 follow-ups SMS",
            "Leads illimités",
            "Annonces illimitées",
            "Estimations illimitées",
            "Support Email 48h",
            "Garantie ROI 60j — remboursement 50%",
        ],
    },
    "Pro": {
        "prix": "1 490€/mois",
        "voix": "3 000 min",
        "sms": "15 000 SMS",
        "utilisateurs": "6 utilisateurs",
        "features": [
            "Tous les agents IA",
            "3 000 min voix/mois",
            "15 000 follow-ups SMS",
            "Leads illimités",
            "Annonces illimitées",
            "Estimations illimitées",
            "Support Email 24h",
            "Garantie ROI 60j — remboursement 50%",
        ],
    },
    "Elite": {
        "prix": "2 990€/mois",
        "voix": "Illimité",
        "sms": "Illimité",
        "utilisateurs": "Utilisateurs illimités",
        "features": [
            "Tous les agents IA",
            "Voix & SMS illimités",
            "Leads illimités",
            "Annonces illimitées",
            "Estimations illimitées",
            "White-label dashboard",
            "Agents IA custom",
            "Account manager dédié",
            "Slack dédié",
            "Garantie ROI 60j — remboursement 100%",
        ],
    },
}


# ─── Helper Stripe ────────────────────────────────────────────────────────────

def _get_stripe():
    """Retourne le module stripe configuré, ou None si mock."""
    settings = get_settings()
    if not settings.stripe_available:
        return None
    import stripe as _stripe
    _stripe.api_key = settings.stripe_secret_key
    return _stripe


# ─── Lecture DB ───────────────────────────────────────────────────────────────

def is_plan_active(user_id: str) -> bool:
    """Vérifie en temps réel si le plan est actif pour un utilisateur."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT plan_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return bool(row["plan_active"]) if row else False


def get_user_subscription_info(user_id: str) -> Optional[dict]:
    """Retourne les infos d'abonnement complètes d'un utilisateur."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, email, agency_name, plan, plan_active,
                      stripe_customer_id, stripe_subscription_id,
                      subscription_status, trial_ends_at
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


# ─── Activation / Désactivation ───────────────────────────────────────────────

def activate_subscription(
    user_id: str,
    plan_name: str,
    stripe_customer_id: str,
    stripe_subscription_id: str,
) -> None:
    """Active l'abonnement suite à un paiement checkout.session.completed."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE users
               SET plan = ?,
                   plan_active = TRUE,
                   stripe_customer_id = ?,
                   stripe_subscription_id = ?,
                   subscription_status = 'active'
               WHERE id = ?""",
            (plan_name, stripe_customer_id, stripe_subscription_id, user_id),
        )
    logger.info(f"[STRIPE] Abonnement activé — user={user_id} plan={plan_name}")


def deactivate_subscription(stripe_subscription_id: str) -> Optional[str]:
    """Désactive l'abonnement suite à customer.subscription.deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ).fetchone()
        if not row:
            logger.warning(f"[STRIPE] Abonnement non trouvé : {stripe_subscription_id}")
            return None
        user_id = row["id"]
        conn.execute(
            """UPDATE users
               SET plan_active = FALSE,
                   subscription_status = 'cancelled'
               WHERE stripe_subscription_id = ?""",
            (stripe_subscription_id,),
        )
    logger.info(f"[STRIPE] Abonnement désactivé — user={user_id}")
    return user_id


def set_past_due(stripe_customer_id: str) -> Optional[dict]:
    """Marque le compte en retard de paiement (invoice.payment_failed)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, agency_name FROM users WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        ).fetchone()
        if not row:
            logger.warning(f"[STRIPE] Client non trouvé : {stripe_customer_id}")
            return None
        conn.execute(
            "UPDATE users SET subscription_status = 'past_due' WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )
    logger.info(f"[STRIPE] Paiement échoué — customer={stripe_customer_id}")
    return dict(row)


# ─── Checkout & Portal ────────────────────────────────────────────────────────

def create_checkout_session(
    user_id: str,
    plan_name: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    """
    Crée une session Stripe Checkout pour le forfait choisi.
    Mode mock si TESTING=true ou STRIPE_SECRET_KEY absent.
    """
    price_id = STRIPE_PRICE_IDS.get(plan_name)
    if not price_id:
        return {"error": f"Plan '{plan_name}' inconnu. Plans disponibles : {list(STRIPE_PRICE_IDS.keys())}"}

    stripe = _get_stripe()
    if not stripe:
        logger.info(f"[MOCK STRIPE] Checkout session — user={user_id} plan={plan_name}")
        return {
            "checkout_url": f"{success_url}?plan={plan_name}&mock=true",
            "session_id": f"mock_cs_{plan_name}_{user_id[:8]}",
            "mock": True,
        }

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=customer_email or None,
            client_reference_id=user_id,
            metadata={"user_id": user_id, "plan": plan_name},
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}&plan=" + quote(plan_name, safe=""),
            cancel_url=cancel_url,
        )
        return {"checkout_url": session.url, "session_id": session.id, "mock": False}
    except Exception as e:
        logger.error(f"[STRIPE] Erreur create_checkout_session : {e}")
        return {"error": str(e)}


def create_portal_session(user_id: str, return_url: str) -> dict:
    """
    Crée une session portail client Stripe pour gérer l'abonnement.
    Mode mock si TESTING=true ou STRIPE_SECRET_KEY absent.
    """
    stripe = _get_stripe()
    if not stripe:
        logger.info(f"[MOCK STRIPE] Portal session — user={user_id}")
        return {"portal_url": return_url + "?mock_portal=true", "mock": True}

    info = get_user_subscription_info(user_id)
    if not info or not info.get("stripe_customer_id"):
        return {"error": "Aucun abonnement Stripe trouvé. Souscrivez d'abord à un forfait."}

    try:
        session = stripe.billing_portal.Session.create(
            customer=info["stripe_customer_id"],
            return_url=return_url,
        )
        return {"portal_url": session.url, "mock": False}
    except Exception as e:
        logger.error(f"[STRIPE] Erreur create_portal_session : {e}")
        return {"error": str(e)}
