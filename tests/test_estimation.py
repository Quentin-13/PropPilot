"""
Tests unitaires — EstimationAgent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.estimation import EstimationAgent, DVF_REFERENCE_PRICES, DPE_ADJUSTMENTS

CLIENT_ID = "test_estimation_client"
TIER = "Pro"


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AGENCY_TIER", TIER)
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    from memory.database import init_database
    init_database()
    yield
    get_settings.cache_clear()


@pytest.fixture
def agent():
    return EstimationAgent(client_id=CLIENT_ID, tier=TIER)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _base_estimate(agent, **overrides):
    """Appel estimate() avec paramètres de base valides."""
    defaults = dict(
        type_bien="Appartement",
        adresse="1 rue Test, 75001 Paris",
        ville="Paris",
        code_postal="75001",
        surface=65.0,
        nb_pieces=3,
        dpe="C",
        etage=2,
        nb_etages=6,
        etat="bon",
        parking=False,
        exterieur=0.0,
        type_exterieur="",
        generate_pdf=False,
    )
    defaults.update(overrides)
    return agent.estimate(**defaults)


# ─── Test estimation de base ───────────────────────────────────────────────────

def test_estimate_returns_success(agent):
    """L'estimation retourne success=True."""
    result = _base_estimate(agent, adresse="10 rue de la Paix, 75001 Paris")
    assert result["success"] is True


def test_estimate_has_price_range(agent):
    """L'estimation fournit une fourchette de prix."""
    result = _base_estimate(
        agent,
        adresse="5 rue de la République, 69001 Lyon",
        ville="Lyon",
        code_postal="69001",
        surface=70.0,
    )
    assert result["prix_estime_bas"] > 0
    assert result["prix_estime_haut"] > result["prix_estime_bas"]
    assert result["prix_estime_central"] > 0
    assert result["prix_estime_bas"] <= result["prix_estime_central"] <= result["prix_estime_haut"]


def test_estimate_paris_price_range(agent):
    """L'estimation Paris est dans la fourchette réaliste."""
    result = _base_estimate(agent, surface=80.0, nb_pieces=4)
    prix_m2 = result.get("prix_m2_net", 0)
    # Paris oscille entre 6000 et 15000€/m²
    assert 4000 <= prix_m2 <= 20000, f"Prix/m² Paris hors fourchette : {prix_m2}"


def test_estimate_bordeaux_price_range(agent):
    """L'estimation Bordeaux est dans la fourchette réaliste."""
    result = _base_estimate(
        agent,
        adresse="Chartrons, 33300 Bordeaux",
        ville="Bordeaux",
        code_postal="33300",
        surface=65.0,
        nb_pieces=3,
        dpe="D",
    )
    prix_m2 = result.get("prix_m2_net", 0)
    # Bordeaux oscille entre 3000 et 7000€/m²
    assert 2000 <= prix_m2 <= 10000, f"Prix/m² Bordeaux hors fourchette : {prix_m2}"


def test_estimate_has_required_fields(agent):
    """Tous les champs obligatoires sont présents."""
    result = _base_estimate(
        agent,
        type_bien="Maison",
        adresse="12 rue des Capucines, 44000 Nantes",
        ville="Nantes",
        code_postal="44000",
        surface=120.0,
        nb_pieces=5,
        dpe="B",
    )
    required_fields = [
        "success", "estimation_id", "prix_estime_bas", "prix_estime_haut",
        "prix_estime_central", "prix_m2_net", "loyer_mensuel_estime",
        "rentabilite_brute", "delai_vente_estime_semaines",
        "justification", "mention_legale",
    ]
    for field in required_fields:
        assert field in result, f"Champ manquant : {field}"


def test_estimate_mention_legale_present(agent):
    """La mention légale loi Hoguet est présente."""
    result = _base_estimate(
        agent,
        adresse="Vieux-Port, 13001 Marseille",
        ville="Marseille",
        code_postal="13001",
        surface=55.0,
        nb_pieces=2,
        dpe="E",
    )
    mention = result.get("mention_legale", "")
    assert mention
    assert len(mention) > 20


def test_estimate_justification_non_empty(agent):
    """La justification de l'estimation n'est pas vide."""
    result = _base_estimate(
        agent,
        adresse="Hypercentre, 31000 Toulouse",
        ville="Toulouse",
        code_postal="31000",
        surface=60.0,
        nb_pieces=3,
    )
    assert result.get("justification")
    assert len(result["justification"]) > 20


def test_estimate_locatif_fields(agent):
    """Les données de rentabilité locative sont calculées."""
    result = _base_estimate(
        agent,
        adresse="Quartier Latin, 75005 Paris",
        surface=22.0,
        nb_pieces=1,
        dpe="D",
    )
    loyer = result.get("loyer_mensuel_estime", 0)
    rentabilite = result.get("rentabilite_brute", 0)
    assert loyer > 0
    assert rentabilite > 0
    assert 1.0 <= rentabilite <= 20.0  # Rentabilité brute réaliste en %


# ─── Test DPE adjustments ─────────────────────────────────────────────────────

def test_dpe_a_premium(agent):
    """Un bien DPE A est estimé plus haut qu'un bien DPE G, toutes choses égales."""
    result_a = _base_estimate(agent, dpe="A")
    result_g = _base_estimate(agent, dpe="G")

    prix_a = result_a.get("prix_estime_central", 0)
    prix_g = result_g.get("prix_estime_central", 0)

    assert prix_a > prix_g, f"DPE A ({prix_a}€) devrait être > DPE G ({prix_g}€)"


def test_dpe_adjustments_values():
    """Les ajustements DPE sont dans les bonnes plages."""
    assert DPE_ADJUSTMENTS["A"] > 0    # Prime pour bon DPE
    assert DPE_ADJUSTMENTS["D"] == 0.0  # Référence neutre
    assert DPE_ADJUSTMENTS["G"] < 0    # Malus pour mauvais DPE
    assert DPE_ADJUSTMENTS["A"] > DPE_ADJUSTMENTS["B"] > DPE_ADJUSTMENTS["C"]
    assert DPE_ADJUSTMENTS["E"] > DPE_ADJUSTMENTS["F"] > DPE_ADJUSTMENTS["G"]


# ─── Test villes couvertes ─────────────────────────────────────────────────────

def test_dvf_reference_prices_coverage():
    """Les villes majeures françaises sont dans les données DVF."""
    villes_majeures = ["paris", "lyon", "bordeaux", "marseille", "toulouse", "nantes", "nice", "rennes"]
    for ville in villes_majeures:
        assert ville in DVF_REFERENCE_PRICES, f"Ville manquante : {ville}"


def test_estimate_unknown_city_fallback(agent):
    """Une ville inconnue utilise la valeur par défaut."""
    result = _base_estimate(
        agent,
        adresse="Centre-ville, 12345 Petiteville",
        ville="Petiteville",
        code_postal="12345",
    )
    assert result["success"] is True
    assert result["prix_estime_central"] > 0


# ─── Test persistance ─────────────────────────────────────────────────────────

def test_estimation_saved_in_db(agent):
    """L'estimation est sauvegardée en base de données."""
    from memory.database import get_connection

    result = _base_estimate(
        agent,
        adresse="Vieux Lyon, 69005 Lyon",
        ville="Lyon",
        code_postal="69005",
        surface=75.0,
        nb_pieces=4,
    )

    estimation_id = result.get("estimation_id")
    assert estimation_id

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, client_id, prix_estime_central FROM estimations WHERE id = ?",
            (estimation_id,),
        ).fetchone()

    assert row is not None
    assert row["client_id"] == CLIENT_ID
    assert row["prix_estime_central"] > 0


# ─── Test heuristique ─────────────────────────────────────────────────────────

def test_heuristic_estimation_consistency(agent):
    """L'estimation heuristique est cohérente avec les prix de marché."""
    result = agent._heuristic_estimation(
        surface=70.0,
        prix_m2_ref=DVF_REFERENCE_PRICES["paris"]["achat"],
        loyer_m2_ref=DVF_REFERENCE_PRICES["paris"]["location_m2"],
        dpe="C",
        etage=2,
        nb_etages=6,
        etat="bon",
        parking=False,
        exterieur=0.0,
        ville="Paris",
    )

    assert result["prix_estime_bas"] > 0
    assert result["prix_estime_haut"] > result["prix_estime_bas"]
    assert result["prix_estime_haut"] - result["prix_estime_bas"] > 10000  # Fourchette raisonnable


def test_delai_vente_by_dpe(agent):
    """Le délai de vente est ajusté selon la classe DPE."""
    result_a = _base_estimate(
        agent,
        adresse="Teste, 69001 Lyon",
        ville="Lyon",
        code_postal="69001",
        dpe="A",
    )
    result_g = _base_estimate(
        agent,
        adresse="Teste, 69001 Lyon",
        ville="Lyon",
        code_postal="69001",
        dpe="G",
    )
    # Les biens DPE A se vendent plus vite ou au moins aussi vite
    assert result_a.get("delai_vente_estime_semaines", 99) <= result_g.get("delai_vente_estime_semaines", 0)


# ─── Test quota ───────────────────────────────────────────────────────────────

def test_estimation_quota_check():
    """Le quota d'estimations est vérifié avant de générer."""
    from memory.usage_tracker import check_and_consume

    result = check_and_consume("quota_test_estimation", "estimation", tier="Starter")
    assert "allowed" in result
    assert "remaining" in result or "message" in result


# ─── Test comparables ─────────────────────────────────────────────────────────

def test_comparables_generated(agent):
    """Des biens comparables sont fournis dans la justification."""
    result = _base_estimate(
        agent,
        adresse="Pentes de la Croix-Rousse, 69001 Lyon",
        ville="Lyon",
        code_postal="69001",
        surface=68.0,
        nb_pieces=3,
    )
    # La justification doit mentionner des prix ou données
    justification = result.get("justification", "")
    assert justification
    has_price_ref = any(
        kw in justification.lower()
        for kw in ["€", "m²", "dvf", "comparable", "marché", "fourchette", "estimation", "m2"]
    )
    assert has_price_ref, f"Justification sans référence prix : {justification[:100]}"


def test_parking_premium(agent):
    """Un bien avec parking est estimé plus haut."""
    result_no = _base_estimate(agent, parking=False, surface=70.0)
    result_yes = _base_estimate(agent, parking=True, surface=70.0)
    assert result_yes.get("prix_estime_central", 0) > result_no.get("prix_estime_central", 0)


def test_exterieur_premium(agent):
    """Un bien avec extérieur est estimé plus haut."""
    result_no = _base_estimate(agent, exterieur=0.0, surface=70.0)
    result_yes = _base_estimate(agent, exterieur=10.0, type_exterieur="balcon", surface=70.0)
    assert result_yes.get("prix_estime_central", 0) >= result_no.get("prix_estime_central", 0)
