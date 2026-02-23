"""
Tests unitaires — AnomalyDetectorAgent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from memory.database import init_database
from memory.models import Lead, ProjetType
from agents.anomaly_detector import AnomalyDetectorAgent


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


def make_detector():
    return AnomalyDetectorAgent(client_id="test_client", tier="Starter")


def test_dossier_propre_pas_anomalie():
    """Un dossier sain ne doit avoir aucune anomalie."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "achat",
        "budget": 350000,
        "prix_demande": 350000,
        "timeline_jours": 120,
        "financement": "Accord de principe BNP validé",
        "titre_propriete": True,
        "syndic_contacte": True,
        "travaux_declares": True,
        "en_copropriete": True,
    })

    assert result["nb_anomalies"] == 0
    assert result["score_risque"] == 0
    assert result["peut_signer_mandat"] is True


def test_financement_absent_timeline_court():
    """Financement absent + délai < 45j → anomalie haute."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "achat",
        "budget": 300000,
        "timeline_jours": 30,
        "financement": "pas encore de banque",
        "titre_propriete": True,
        "syndic_contacte": True,
        "travaux_declares": True,
        "en_copropriete": False,
    })

    anomalie_financement = next(
        (a for a in result["anomalies"] if a["type"] == "financement"), None
    )
    assert anomalie_financement is not None
    assert anomalie_financement["severite"] == "haute"
    assert result["score_risque"] >= 3


def test_prix_surevalue_30pct():
    """Prix demandé > 30% au-dessus du marché → anomalie prix."""
    detector = make_detector()
    result = detector.analyze_dossier_dict(
        dossier={
            "projet": "vente",
            "budget": 500000,
            "prix_demande": 500000,
            "timeline_jours": 120,
            "financement": "fonds propres",
            "titre_propriete": True,
            "syndic_contacte": True,
            "travaux_declares": True,
            "en_copropriete": False,
        },
        prix_marche_estime=350000,
    )

    anomalie_prix = next((a for a in result["anomalies"] if a["type"] == "prix"), None)
    assert anomalie_prix is not None
    assert anomalie_prix["severite"] in ("haute", "moyenne")


def test_prix_dans_fourchette_ok():
    """Prix dans la fourchette ±30% → pas d'anomalie prix."""
    detector = make_detector()
    result = detector.analyze_dossier_dict(
        dossier={
            "projet": "vente",
            "prix_demande": 370000,
            "budget": 370000,
            "timeline_jours": 90,
            "financement": "accord bancaire",
            "titre_propriete": True,
            "syndic_contacte": True,
            "travaux_declares": True,
        },
        prix_marche_estime=350000,
    )

    anomalies_prix = [a for a in result["anomalies"] if a["type"] == "prix"]
    assert len(anomalies_prix) == 0


def test_titre_propriete_manquant():
    """Titre de propriété manquant → anomalie haute."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "vente",
        "budget": 300000,
        "timeline_jours": 90,
        "financement": "accord bancaire",
        "titre_propriete": False,
        "syndic_contacte": True,
        "travaux_declares": True,
    })

    anomalie_titre = next((a for a in result["anomalies"] if a["type"] == "titre"), None)
    assert anomalie_titre is not None
    assert anomalie_titre["severite"] == "haute"
    assert result["peut_signer_mandat"] is False


def test_syndic_non_contacte_copropriete():
    """Syndic non contacté en copropriété → anomalie document."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "vente",
        "budget": 300000,
        "timeline_jours": 90,
        "financement": "accord bancaire",
        "titre_propriete": True,
        "syndic_contacte": False,
        "travaux_declares": True,
        "en_copropriete": True,
    })

    anomalie_syndic = next((a for a in result["anomalies"] if a["type"] == "document"), None)
    assert anomalie_syndic is not None
    assert anomalie_syndic["severite"] == "moyenne"


def test_syndic_non_contacte_hors_copropriete():
    """Syndic non contacté hors copropriété → pas d'anomalie."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "vente",
        "budget": 300000,
        "timeline_jours": 90,
        "financement": "accord bancaire",
        "titre_propriete": True,
        "syndic_contacte": False,
        "travaux_declares": True,
        "en_copropriete": False,
    })

    anomalies_syndic = [a for a in result["anomalies"] if a["type"] == "document"]
    assert len(anomalies_syndic) == 0


def test_score_risque_calcul():
    """Score risque = somme des poids des anomalies."""
    detector = make_detector()
    # 1 haute (3) + 1 moyenne (2) = 5
    result = detector.analyze_dossier_dict({
        "projet": "achat",
        "budget": 300000,
        "timeline_jours": 20,
        "financement": "pas de banque",
        "titre_propriete": False,
        "syndic_contacte": True,
        "travaux_declares": True,
        "en_copropriete": False,
    })

    assert result["score_risque"] >= 3
    assert result["nb_anomalies"] >= 1


def test_analyse_lead_dossier_lead_inexistant():
    """Lead inexistant → résultat minimal sans crash."""
    detector = make_detector()
    result = detector.analyze_lead_dossier("lead_inexistant_xxx")

    assert result["anomalies"] == []
    assert result["score_risque"] == 0


def test_analyse_lead_dossier_with_real_lead():
    """Analyse d'un lead réel depuis la base."""
    from memory.lead_repository import create_lead

    lead = Lead(
        client_id="test_client",
        prenom="Jean",
        telephone="+33600000010",
        financement="pas encore de banque",
        timeline="dans 1 mois",
        budget="300 000€",
    )
    lead.projet = ProjetType.ACHAT
    lead.score_budget = 1
    created = create_lead(lead)

    detector = make_detector()
    result = detector.analyze_lead_dossier(created.id)

    assert "anomalies" in result
    assert "score_risque" in result
    assert "peut_signer_mandat" in result
    assert isinstance(result["anomalies"], list)


def test_recommandation_dossier_propre():
    """Dossier propre → recommandation positive."""
    detector = make_detector()
    result = detector.analyze_dossier_dict({
        "projet": "achat",
        "budget": 350000,
        "timeline_jours": 120,
        "financement": "accord bancaire validé",
        "titre_propriete": True,
        "syndic_contacte": True,
        "travaux_declares": True,
        "en_copropriete": False,
    })

    assert "conforme" in result["recommandation_globale"].lower() or "sain" in result["recommandation_globale"].lower()


def test_compute_risk_score_max_10():
    """Le score risque ne dépasse pas 10."""
    detector = make_detector()
    anomalies = [{"severite": "haute"} for _ in range(10)]
    score = detector._compute_risk_score(anomalies)
    assert score == 10


def test_merge_anomalies_no_duplicates():
    """La fusion ne duplique pas les anomalies de même type."""
    detector = make_detector()
    heuristic = [{"type": "financement", "severite": "haute", "description": "test1"}]
    llm = [
        {"type": "financement", "severite": "moyenne", "description": "test2"},  # doublon
        {"type": "prix", "severite": "basse", "description": "test3"},          # nouveau
    ]
    merged = detector._merge_anomalies(heuristic, llm)
    types = [a["type"] for a in merged]
    assert types.count("financement") == 1
    assert "prix" in types
    assert len(merged) == 2
