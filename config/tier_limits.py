"""
Définition des limites d'usage par tier.
Toute modification ici se répercute automatiquement sur le dashboard et le tracking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TierLimits:
    tier: str
    prix_mensuel: int                  # EUR/mois
    leads_par_mois: Optional[int]      # None = illimité
    minutes_voix_par_mois: Optional[float]
    images_par_mois: Optional[int]
    tokens_claude_par_mois: Optional[int]  # en tokens absolus
    followups_sms_par_mois: Optional[int]
    annonces_par_mois: Optional[int]
    estimations_par_mois: Optional[int]
    white_label: bool
    garantie_remboursement_pct: int    # % remboursement si ROI non atteint
    support: str


TIERS: dict[str, TierLimits] = {
    "Starter": TierLimits(
        tier="Starter",
        prix_mensuel=790,
        leads_par_mois=300,
        minutes_voix_par_mois=160.0,
        images_par_mois=50,
        tokens_claude_par_mois=5_000_000,
        followups_sms_par_mois=1_000,
        annonces_par_mois=30,
        estimations_par_mois=20,
        white_label=False,
        garantie_remboursement_pct=50,
        support="Email 48h",
    ),
    "Pro": TierLimits(
        tier="Pro",
        prix_mensuel=1490,
        leads_par_mois=800,
        minutes_voix_par_mois=550.0,
        images_par_mois=150,
        tokens_claude_par_mois=15_000_000,
        followups_sms_par_mois=3_000,
        annonces_par_mois=100,
        estimations_par_mois=60,
        white_label=False,
        garantie_remboursement_pct=50,
        support="Email 24h",
    ),
    "Elite": TierLimits(
        tier="Elite",
        prix_mensuel=2990,
        leads_par_mois=None,           # Illimité
        minutes_voix_par_mois=None,    # Illimité
        images_par_mois=500,
        tokens_claude_par_mois=50_000_000,
        followups_sms_par_mois=None,   # Illimité
        annonces_par_mois=400,
        estimations_par_mois=200,
        white_label=True,
        garantie_remboursement_pct=100,
        support="Slack dédié",
    ),
}

# Mapping action → champ TierLimits
ACTION_TO_FIELD: dict[str, str] = {
    "lead": "leads_par_mois",
    "voice_minute": "minutes_voix_par_mois",
    "image": "images_par_mois",
    "token": "tokens_claude_par_mois",
    "followup": "followups_sms_par_mois",
    "listing": "annonces_par_mois",
    "estimation": "estimations_par_mois",
}

# Labels métier (jamais de termes techniques)
ACTION_LABELS: dict[str, str] = {
    "lead": "leads qualifiés",
    "voice_minute": "minutes voix",
    "image": "images staging",
    "token": "requêtes IA",
    "followup": "follow-ups SMS",
    "listing": "annonces générées",
    "estimation": "estimations",
}


def get_tier_limits(tier: str) -> TierLimits:
    """Retourne les limites pour un tier donné. Défaut : Starter."""
    return TIERS.get(tier, TIERS["Starter"])


def get_limit_for_action(tier: str, action: str) -> Optional[int | float]:
    """Retourne la limite pour une action donnée, ou None si illimité."""
    limits = get_tier_limits(tier)
    field = ACTION_TO_FIELD.get(action)
    if not field:
        return None
    return getattr(limits, field, None)


def get_upgrade_message(tier: str, action: str) -> str:
    """Message d'upgrade personnalisé selon le tier actuel."""
    label = ACTION_LABELS.get(action, action)
    if tier == "Starter":
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Passez au forfait Pro (1 490€/mois) pour tripler vos capacités. "
            f"👉 Contactez-nous pour upgrader immédiatement."
        )
    elif tier == "Pro":
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Passez au forfait Elite (2 990€/mois) pour une capacité illimitée. "
            f"👉 Contactez-nous pour upgrader immédiatement."
        )
    else:
        return f"Limite de {label} atteinte pour ce mois. Contactez le support."
