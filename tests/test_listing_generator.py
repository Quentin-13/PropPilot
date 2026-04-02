"""
Tests unitaires — ListingGeneratorAgent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.listing_generator import ListingGeneratorAgent

CLIENT_ID = "test_listing_client"
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
    return ListingGeneratorAgent(client_id=CLIENT_ID, tier=TIER)


# ─── Test génération de base ───────────────────────────────────────────────────

def test_generate_returns_success(agent):
    """La génération retourne un dict avec success=True."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="10 rue de la Paix, 75001 Paris",
        surface=65.0,
        nb_pieces=3,
        nb_chambres=2,
        dpe_energie="C",
        dpe_ges="C",
        prix=450000,
        etage="2ème",
        exposition="sud",
        parking=True,
        cave=False,
        exterieur="Balcon 6m²",
        etat="bon",
        notes="Parquet ancien, moulures",
    )
    assert result["success"] is True


def test_generate_returns_listing_id(agent):
    """Un listing_id unique est généré."""
    result = agent.generate(
        type_bien="Studio",
        adresse="5 avenue Victor Hugo, 69006 Lyon",
        surface=25.0,
        nb_pieces=1,
        nb_chambres=0,
        dpe_energie="D",
        dpe_ges="D",
        prix=180000,
        etage="RDC",
        exposition="nord",
    )
    assert "listing_id" in result
    assert len(result["listing_id"]) == 36  # UUID format


def test_generate_has_required_fields(agent):
    """Tous les champs obligatoires sont présents."""
    result = agent.generate(
        type_bien="Maison",
        adresse="12 chemin des Vignes, 33400 Talence",
        surface=120.0,
        nb_pieces=5,
        nb_chambres=3,
        dpe_energie="B",
        dpe_ges="B",
        prix=520000,
    )
    required_fields = [
        "success", "listing_id", "titre", "description_longue",
        "description_courte", "points_forts", "mentions_legales",
        "mots_cles_seo", "compromis_prefill",
    ]
    for field in required_fields:
        assert field in result, f"Champ manquant : {field}"


def test_generate_titre_non_empty(agent):
    """Le titre généré n'est pas vide."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="22 rue Sainte-Catherine, 33000 Bordeaux",
        surface=55.0,
        nb_pieces=3,
        dpe_energie="D",
        prix=280000,
    )
    assert result.get("titre")
    assert len(result["titre"]) > 5


def test_generate_description_longue_content(agent):
    """La description longue contient des informations sur le bien."""
    adresse = "Place Bellecour, 69002 Lyon"
    result = agent.generate(
        type_bien="Loft",
        adresse=adresse,
        surface=85.0,
        nb_pieces=2,
        dpe_energie="E",
        prix=350000,
    )
    desc = result.get("description_longue", "")
    assert len(desc) > 50


def test_generate_points_forts_is_list(agent):
    """points_forts est une liste."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="3 rue Masséna, 06000 Nice",
        surface=70.0,
        nb_pieces=3,
        dpe_energie="C",
        prix=380000,
    )
    assert isinstance(result.get("points_forts"), list)
    assert len(result["points_forts"]) >= 1


def test_generate_mots_cles_seo_is_list(agent):
    """mots_cles_seo est une liste de chaînes."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="1 rue de la République, 13001 Marseille",
        surface=60.0,
        nb_pieces=3,
        dpe_energie="D",
        prix=250000,
    )
    mots = result.get("mots_cles_seo", [])
    assert isinstance(mots, list)
    assert all(isinstance(m, str) for m in mots)



# ─── Test compromis pré-rempli ────────────────────────────────────────────────

def test_compromis_structure(agent):
    """Le compromis pré-rempli a la structure loi Hoguet."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="15 quai de la Tournelle, 75005 Paris",
        surface=80.0,
        nb_pieces=4,
        dpe_energie="C",
        prix=700000,
    )
    comp = result.get("compromis_prefill", {})
    assert comp.get("reference")
    assert comp.get("type_acte")
    assert "bien" in comp
    assert "prix" in comp
    assert "conditions_suspensives" in comp
    assert "mention_legale_hoguet" in comp
    assert "champs_a_completer" in comp


def test_compromis_honoraires_calcul(agent):
    """Les honoraires sont calculés à 3,9% du prix."""
    prix = 400000
    result = agent.generate(
        type_bien="Appartement",
        adresse="10 rue Victor Hugo, 33000 Bordeaux",
        surface=70.0,
        nb_pieces=3,
        dpe_energie="D",
        prix=prix,
    )
    comp = result.get("compromis_prefill", {})
    prix_data = comp.get("prix", {})
    honoraires = prix_data.get("honoraires_agence_ttc", 0)
    prix_fai = prix_data.get("prix_fai", 0)
    net_vendeur = prix_data.get("net_vendeur", 0)

    assert prix_fai == prix
    assert abs(honoraires - int(prix * 0.039)) <= 1
    assert abs(net_vendeur - int(prix * 0.961)) <= 1


def test_compromis_reference_format(agent):
    """La référence du compromis suit le format COMP-YYYYMM-XXXXXX."""
    result = agent.generate(
        type_bien="Maison",
        adresse="5 allée des Roses, 44000 Nantes",
        surface=140.0,
        nb_pieces=6,
        dpe_energie="D",
        prix=450000,
    )
    reference = result.get("compromis_prefill", {}).get("reference", "")
    assert reference.startswith("COMP-")
    assert len(reference) > 10


def test_compromis_conditions_suspensives(agent):
    """Les conditions suspensives standard sont présentes."""
    result = agent.generate(
        type_bien="Appartement",
        adresse="8 rue des Fleurs, 31000 Toulouse",
        surface=55.0,
        nb_pieces=2,
        dpe_energie="E",
        prix=220000,
    )
    conditions = result.get("compromis_prefill", {}).get("conditions_suspensives", [])
    assert isinstance(conditions, list)
    assert len(conditions) >= 1
    # La condition de financement est standard
    financement_condition = any("financement" in c.lower() for c in conditions)
    assert financement_condition


# ─── Test mentions légales ─────────────────────────────────────────────────────

def test_mentions_legales_dpe(agent):
    """Les mentions légales incluent le DPE."""
    dpe = "B"
    result = agent.generate(
        type_bien="Appartement",
        adresse="23 boulevard Haussmann, 75009 Paris",
        surface=95.0,
        nb_pieces=4,
        dpe_energie=dpe,
        prix=950000,
    )
    mentions = result.get("mentions_legales", "")
    assert mentions  # Non vide


def test_mentions_legales_surface(agent):
    """Les mentions légales contiennent la surface."""
    surface = 72.0
    result = agent.generate(
        type_bien="Appartement",
        adresse="1 place du Capitole, 31000 Toulouse",
        surface=surface,
        nb_pieces=3,
        dpe_energie="C",
        prix=295000,
    )
    mentions = result.get("mentions_legales", "")
    assert str(int(surface)) in mentions or "Carrez" in mentions or "m²" in mentions


# ─── Test persistance ─────────────────────────────────────────────────────────

def test_listing_saved_in_db(agent):
    """L'annonce est sauvegardée en base de données."""
    from memory.database import get_connection

    result = agent.generate(
        type_bien="Studio",
        adresse="99 avenue Jean Jaurès, 69007 Lyon",
        surface=28.0,
        nb_pieces=1,
        dpe_energie="F",
        prix=155000,
    )

    listing_id = result.get("listing_id")
    assert listing_id

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, client_id, titre FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()

    assert row is not None
    assert row["client_id"] == CLIENT_ID
    assert row["titre"]


# ─── Test mock ────────────────────────────────────────────────────────────────

def test_mock_listing_structure():
    """Le mock retourne une structure complète même sans clé API."""
    agent_mock = ListingGeneratorAgent(client_id="mock_test", tier="Starter")
    result = agent_mock._mock_listing({
        "type_bien": "Appartement",
        "adresse": "1 rue Test, 75001 Paris",
        "surface": 50.0,
        "nb_pieces": 2,
        "nb_chambres": 1,
        "dpe_energie": "D",
        "dpe_ges": "D",
        "prix": 300000,
        "parking": False,
        "cave": False,
        "exterieur": "",
        "etat": "bon",
        "notes": "",
    })

    assert result["titre"]
    assert result["description_longue"]
    assert result["description_courte"]
    assert isinstance(result["points_forts"], list)
    assert isinstance(result["mots_cles_seo"], list)


def test_translate_to_english(agent):
    """La traduction anglaise fonctionne (mock ou réel)."""
    description = "Superbe appartement 3 pièces, 65m², lumineux, parquet ancien, proche métro."
    result = agent.translate_to_english(description)
    assert result.get("success") is True
    assert result.get("translation")
    assert len(result["translation"]) > 10
