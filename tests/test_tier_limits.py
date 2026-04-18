"""
Tests unitaires — TierLimits.
Vérifie les nouvelles valeurs de limites par forfait.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# Override de l'autouse fixture de conftest.py — ces tests ne nécessitent pas de DB
@pytest.fixture(autouse=True)
def _reset_db_between_tests(monkeypatch):
    """Pas de DB pour les tests de tier_limits (tests purement unitaires)."""
    monkeypatch.setenv("TESTING", "true")
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


from config.tier_limits import (
    TIERS,
    ALERT_ACTIONS,
    get_limit_for_action,
    get_tier_limits,
    get_upgrade_message,
)


# ─── Structure dataclass ─────────────────────────────────────────────────────

def test_all_tiers_present():
    assert set(TIERS.keys()) == {"Indépendant", "Starter", "Pro", "Elite"}


def test_tier_order():
    assert list(TIERS.keys()) == ["Indépendant", "Starter", "Pro", "Elite"]


def test_tier_limits_has_new_fields():
    s = TIERS["Starter"]
    assert hasattr(s, "utilisateurs")
    assert hasattr(s, "crm_integrations")
    assert hasattr(s, "anomaly_checks_par_mois")
    assert hasattr(s, "custom_agents")
    assert hasattr(s, "account_manager")


# ─── Indépendant ─────────────────────────────────────────────────────────────

def test_independant_voice_limit():
    assert TIERS["Indépendant"].minutes_voix_par_mois == 600.0


def test_independant_sms_limit():
    assert TIERS["Indépendant"].followups_sms_par_mois == 3_000


def test_independant_unlimited_leads():
    assert TIERS["Indépendant"].leads_par_mois is None


def test_independant_unlimited_listings():
    assert TIERS["Indépendant"].annonces_par_mois is None


def test_independant_unlimited_estimations():
    assert TIERS["Indépendant"].estimations_par_mois is None



def test_independant_unlimited_anomaly():
    assert TIERS["Indépendant"].anomaly_checks_par_mois is None


def test_independant_utilisateurs():
    assert TIERS["Indépendant"].utilisateurs == 1


def test_independant_crm_integrations():
    assert TIERS["Indépendant"].crm_integrations == 1


def test_independant_no_custom_agents():
    assert TIERS["Indépendant"].custom_agents is False


def test_independant_no_account_manager():
    assert TIERS["Indépendant"].account_manager is False


def test_independant_prix():
    assert TIERS["Indépendant"].prix_mensuel == 250


def test_independant_garantie_50():
    assert TIERS["Indépendant"].garantie_remboursement_pct == 50


# ─── Starter ─────────────────────────────────────────────────────────────────

def test_starter_voice_limit():
    assert TIERS["Starter"].minutes_voix_par_mois == 1_500.0


def test_starter_sms_limit():
    assert TIERS["Starter"].followups_sms_par_mois == 8_000


def test_starter_unlimited_leads():
    assert TIERS["Starter"].leads_par_mois is None


def test_starter_unlimited_listings():
    assert TIERS["Starter"].annonces_par_mois is None


def test_starter_unlimited_estimations():
    assert TIERS["Starter"].estimations_par_mois is None



def test_starter_unlimited_anomaly():
    assert TIERS["Starter"].anomaly_checks_par_mois is None


def test_starter_utilisateurs():
    assert TIERS["Starter"].utilisateurs == 3


def test_starter_crm_integrations():
    assert TIERS["Starter"].crm_integrations == 2


def test_starter_no_white_label():
    assert TIERS["Starter"].white_label is False


def test_starter_no_custom_agents():
    assert TIERS["Starter"].custom_agents is False


def test_starter_no_account_manager():
    assert TIERS["Starter"].account_manager is False


def test_starter_garantie_50():
    assert TIERS["Starter"].garantie_remboursement_pct == 50


def test_starter_prix():
    assert TIERS["Starter"].prix_mensuel == 790


# ─── Pro ─────────────────────────────────────────────────────────────────────

def test_pro_voice_limit():
    assert TIERS["Pro"].minutes_voix_par_mois == 3_000.0


def test_pro_sms_limit():
    assert TIERS["Pro"].followups_sms_par_mois == 15_000


def test_pro_unlimited_leads():
    assert TIERS["Pro"].leads_par_mois is None


def test_pro_unlimited_listings():
    assert TIERS["Pro"].annonces_par_mois is None


def test_pro_unlimited_estimations():
    assert TIERS["Pro"].estimations_par_mois is None



def test_pro_utilisateurs():
    assert TIERS["Pro"].utilisateurs == 6


def test_pro_crm_integrations():
    assert TIERS["Pro"].crm_integrations == 5


def test_pro_no_white_label():
    assert TIERS["Pro"].white_label is False


def test_pro_no_custom_agents():
    assert TIERS["Pro"].custom_agents is False


def test_pro_no_account_manager():
    assert TIERS["Pro"].account_manager is False


def test_pro_garantie_50():
    assert TIERS["Pro"].garantie_remboursement_pct == 50


def test_pro_prix():
    assert TIERS["Pro"].prix_mensuel == 1490


# ─── Elite ───────────────────────────────────────────────────────────────────

def test_elite_unlimited_voice():
    assert TIERS["Elite"].minutes_voix_par_mois is None


def test_elite_unlimited_sms():
    assert TIERS["Elite"].followups_sms_par_mois is None


def test_elite_unlimited_leads():
    assert TIERS["Elite"].leads_par_mois is None


def test_elite_unlimited_utilisateurs():
    assert TIERS["Elite"].utilisateurs is None


def test_elite_unlimited_crm():
    assert TIERS["Elite"].crm_integrations is None


def test_elite_unlimited_tokens():
    assert TIERS["Elite"].tokens_claude_par_mois is None


def test_elite_white_label():
    assert TIERS["Elite"].white_label is True


def test_elite_custom_agents():
    assert TIERS["Elite"].custom_agents is True


def test_elite_account_manager():
    assert TIERS["Elite"].account_manager is True


def test_elite_garantie_100():
    assert TIERS["Elite"].garantie_remboursement_pct == 100


def test_elite_prix():
    assert TIERS["Elite"].prix_mensuel == 2990


# ─── get_limit_for_action ────────────────────────────────────────────────────

def test_get_limit_voice_independant():
    assert get_limit_for_action("Indépendant", "voice_minute") == 600.0


def test_get_limit_voice_starter():
    assert get_limit_for_action("Starter", "voice_minute") == 1_500.0


def test_get_limit_voice_pro():
    assert get_limit_for_action("Pro", "voice_minute") == 3_000.0


def test_get_limit_voice_elite():
    assert get_limit_for_action("Elite", "voice_minute") is None


def test_get_limit_sms_independant():
    assert get_limit_for_action("Indépendant", "followup") == 3_000


def test_get_limit_sms_starter():
    assert get_limit_for_action("Starter", "followup") == 8_000


def test_get_limit_sms_pro():
    assert get_limit_for_action("Pro", "followup") == 15_000


def test_get_limit_sms_elite():
    assert get_limit_for_action("Elite", "followup") is None


def test_get_limit_lead_all_tiers_unlimited():
    for tier in ("Indépendant", "Starter", "Pro", "Elite"):
        assert get_limit_for_action(tier, "lead") is None


def test_get_limit_unknown_action():
    assert get_limit_for_action("Starter", "unknown_action") is None


# ─── get_upgrade_message ─────────────────────────────────────────────────────

def test_upgrade_message_independant_contains_contact():
    msg = get_upgrade_message("Indépendant", "voice_minute")
    assert "contact@proppilot.fr" in msg


def test_upgrade_message_independant_mentions_starter():
    msg = get_upgrade_message("Indépendant", "voice_minute")
    assert "Starter" in msg or "790" in msg


def test_upgrade_message_starter_contains_contact():
    msg = get_upgrade_message("Starter", "voice_minute")
    assert "contact@proppilot.fr" in msg


def test_upgrade_message_pro_contains_contact():
    msg = get_upgrade_message("Pro", "followup")
    assert "contact@proppilot.fr" in msg


def test_upgrade_message_elite_contains_contact():
    msg = get_upgrade_message("Elite", "voice_minute")
    assert "contact@proppilot.fr" in msg


def test_upgrade_message_starter_mentions_pro():
    msg = get_upgrade_message("Starter", "voice_minute")
    assert "Pro" in msg or "1 490" in msg


def test_upgrade_message_pro_mentions_elite():
    msg = get_upgrade_message("Pro", "followup")
    assert "Elite" in msg or "2 990" in msg


# ─── ALERT_ACTIONS ───────────────────────────────────────────────────────────

def test_alert_actions_contains_voice():
    assert "voice_minute" in ALERT_ACTIONS


def test_alert_actions_contains_followup():
    assert "followup" in ALERT_ACTIONS


def test_alert_actions_not_lead():
    assert "lead" not in ALERT_ACTIONS


# ─── Fallback tier inconnu ───────────────────────────────────────────────────

def test_unknown_tier_defaults_to_starter():
    limits = get_tier_limits("Unknown")
    assert limits.tier == "Starter"
