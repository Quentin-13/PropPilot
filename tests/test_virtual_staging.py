"""
Tests unitaires — VirtualStagingAgent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.database import init_database
from agents.virtual_staging import VirtualStagingAgent
from tools.dalle_tool import STAGING_STYLES


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", "test_client")
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


def make_agent(tier="Starter"):
    return VirtualStagingAgent(client_id="test_client", tier=tier)


def test_stage_property_returns_success():
    """Le staging retourne un résultat structuré."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Appartement haussmannien 80m², parquet, moulures",
        style="contemporain",
        nb_images=1,
        rooms=["sejour"],
    )

    assert "success" in result
    assert "images" in result
    assert isinstance(result["images"], list)


def test_stage_property_mock_mode():
    """En mode mock, les images sont générées sans clé OpenAI."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Studio 25m², Paris",
        style="scandinave_epure",
        nb_images=1,
        rooms=["sejour"],
    )

    assert len(result["images"]) >= 1
    first_img = result["images"][0]
    assert "room" in first_img
    assert "prompt" in first_img


def test_stage_property_multiple_rooms():
    """Le staging génère une image par pièce demandée (dans la limite)."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Appartement 3 pièces Lyon",
        style="contemporain",
        nb_images=2,
        rooms=["sejour", "chambre"],
    )

    assert len(result["images"]) <= 2
    rooms_generated = [img["room"] for img in result["images"]]
    assert len(rooms_generated) == len(set(rooms_generated))  # pas de doublons


def test_stage_property_invalid_style_fallback():
    """Un style inconnu doit utiliser le style par défaut (contemporain)."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Maison 100m²",
        style="style_inexistant",
        nb_images=1,
        rooms=["sejour"],
    )

    assert "images" in result
    assert len(result["images"]) >= 1


def test_stage_property_limit_nb_images():
    """Le nombre d'images est limité au nombre de pièces demandées."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Villa 200m²",
        style="contemporain",
        nb_images=10,  # excessif
        rooms=["sejour", "chambre"],
    )

    assert len(result["images"]) <= 2


def test_staging_styles_all_defined():
    """Tous les styles requis sont bien définis dans STAGING_STYLES."""
    required_styles = ["contemporain", "haussmannien_moderne", "scandinave_epure", "provencal_renove"]
    for style in required_styles:
        assert style in STAGING_STYLES
        assert "label" in STAGING_STYLES[style]
        assert "description" in STAGING_STYLES[style]


def test_get_available_rooms():
    """La méthode retourne un dictionnaire de pièces disponibles."""
    agent = make_agent()
    rooms = agent.get_available_rooms()

    assert isinstance(rooms, dict)
    assert "sejour" in rooms
    assert len(rooms) >= 4


def test_generate_architectural_render_success():
    """Le rendu architectural retourne une structure valide."""
    agent = make_agent()
    result = agent.generate_architectural_render(
        type_bien="appartement",
        superficie=75.0,
        nb_pieces=3,
        style="contemporain",
        ville="Lyon",
    )

    assert "success" in result
    assert "prompt_used" in result or "image_path" in result


def test_staging_quota_check():
    """Le staging doit vérifier le quota images."""
    agent = VirtualStagingAgent(client_id="test_client", tier="Starter")

    # Consommer tout le quota
    from memory.usage_tracker import check_and_consume
    from config.tier_limits import TIERS
    limit = TIERS["Starter"].images_par_mois
    for _ in range(limit):
        check_and_consume("test_client", "image", tier="Starter")

    # Le prochain appel doit être bloqué
    result = agent.stage_property(
        property_description="Test",
        style="contemporain",
        nb_images=1,
        rooms=["sejour"],
    )

    # Les images doivent indiquer une limite atteinte ou résultat vide
    has_limit_error = (
        not result.get("success") or
        any(img.get("reason") == "limit_reached" for img in result.get("images", []))
    )
    assert has_limit_error


def test_image_data_has_prompt():
    """Chaque image générée doit avoir un prompt."""
    agent = make_agent()
    result = agent.stage_property(
        property_description="Loft industriel 60m²",
        style="contemporain",
        nb_images=1,
        rooms=["sejour"],
    )

    for img in result.get("images", []):
        assert "prompt" in img
        assert len(img["prompt"]) > 10
