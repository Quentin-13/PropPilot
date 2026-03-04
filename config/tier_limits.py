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
    prix_mensuel: int                       # EUR/mois
    utilisateurs: Optional[int]             # None = illimité
    crm_integrations: Optional[int]         # None = illimité
    leads_par_mois: Optional[int]           # None = illimité
    minutes_voix_par_mois: Optional[float]  # None = illimité
    images_par_mois: Optional[int]          # None = illimité
    tokens_claude_par_mois: Optional[int]   # None = illimité
    followups_sms_par_mois: Optional[int]   # None = illimité
    annonces_par_mois: Optional[int]        # None = illimité
    estimations_par_mois: Optional[int]     # None = illimité
    anomaly_checks_par_mois: Optional[int]  # None = illimité
    white_label: bool
    custom_agents: bool
    account_manager: bool
    garantie_remboursement_pct: int         # % remboursement si ROI non atteint
    support: str


TIERS: dict[str, TierLimits] = {
    "Indépendant": TierLimits(
        tier="Indépendant",
        prix_mensuel=290,
        utilisateurs=1,
        crm_integrations=1,
        leads_par_mois=None,            # Illimité
        minutes_voix_par_mois=600.0,
        images_par_mois=None,           # Illimité
        tokens_claude_par_mois=None,    # Illimité
        followups_sms_par_mois=3_000,
        annonces_par_mois=None,         # Illimité
        estimations_par_mois=None,      # Illimité
        anomaly_checks_par_mois=None,   # Illimité
        white_label=False,
        custom_agents=False,
        account_manager=False,
        garantie_remboursement_pct=50,
        support="Email 48h",
    ),
    "Starter": TierLimits(
        tier="Starter",
        prix_mensuel=790,
        utilisateurs=3,
        crm_integrations=2,
        leads_par_mois=None,            # Illimité
        minutes_voix_par_mois=1_500.0,
        images_par_mois=None,           # Illimité
        tokens_claude_par_mois=None,    # Illimité
        followups_sms_par_mois=8_000,
        annonces_par_mois=None,         # Illimité
        estimations_par_mois=None,      # Illimité
        anomaly_checks_par_mois=None,   # Illimité
        white_label=False,
        custom_agents=False,
        account_manager=False,
        garantie_remboursement_pct=50,
        support="Email 48h",
    ),
    "Pro": TierLimits(
        tier="Pro",
        prix_mensuel=1490,
        utilisateurs=6,
        crm_integrations=5,
        leads_par_mois=None,            # Illimité
        minutes_voix_par_mois=3_000.0,
        images_par_mois=None,           # Illimité
        tokens_claude_par_mois=None,    # Illimité
        followups_sms_par_mois=15_000,
        annonces_par_mois=None,         # Illimité
        estimations_par_mois=None,      # Illimité
        anomaly_checks_par_mois=None,   # Illimité
        white_label=False,
        custom_agents=False,
        account_manager=False,
        garantie_remboursement_pct=50,
        support="Email 24h",
    ),
    "Elite": TierLimits(
        tier="Elite",
        prix_mensuel=2990,
        utilisateurs=None,              # Illimité
        crm_integrations=None,          # Illimité
        leads_par_mois=None,            # Illimité
        minutes_voix_par_mois=None,     # Illimité
        images_par_mois=None,           # Illimité
        tokens_claude_par_mois=None,    # Illimité
        followups_sms_par_mois=None,    # Illimité
        annonces_par_mois=None,         # Illimité
        estimations_par_mois=None,      # Illimité
        anomaly_checks_par_mois=None,   # Illimité
        white_label=True,
        custom_agents=True,
        account_manager=True,
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
    "anomaly_check": "anomaly_checks_par_mois",
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
    "anomaly_check": "vérifications dossier",
}

# Actions qui déclenchent une alerte email à 80% (ressources critiques)
ALERT_ACTIONS: frozenset[str] = frozenset({"voice_minute", "followup"})


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
    if tier == "Indépendant":
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Passez au forfait Starter (790€/mois) pour augmenter vos capacités. "
            f"Contactez-nous : contact@proppilot.fr"
        )
    elif tier == "Starter":
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Passez au forfait Pro (1 490€/mois) pour augmenter vos capacités. "
            f"Contactez-nous : contact@proppilot.fr"
        )
    elif tier == "Pro":
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Passez au forfait Elite (2 990€/mois) pour une capacité illimitée. "
            f"Contactez-nous : contact@proppilot.fr"
        )
    else:
        return (
            f"Limite de {label} atteinte pour ce mois. "
            f"Contactez votre account manager ou écrivez à contact@proppilot.fr"
        )
