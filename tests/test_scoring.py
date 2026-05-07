"""
Tests du nouveau scoring à deux grilles (acheteur/vendeur).
12 cas minimum : acheteurs, vendeurs, locataires, pièges, ambigus.

Invariants testés :
- Score normalisé 0-24
- Thresholds : ≥18 chaud, ≥11 tiède, <11 froid
- Redistribution des poids si axe absent (null ≠ 0)
- lead_type détecté depuis from_dict
- Cas piège : lead "tout rempli mais sans urgence" → pas chaud
- Cas piège : "juste une estimation pour info" → froid
"""
import pytest
from lib.lead_extraction.schema import (
    LeadExtractionResult,
    compute_score,
    score_to_action,
    score_to_label,
    SCORE_SEUIL_CHAUD,
    SCORE_SEUIL_TIEDE,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def acheteur(**axes) -> int:
    return compute_score("acheteur", axes)

def vendeur(**axes) -> int:
    return compute_score("vendeur", axes)


# ── tests compute_score ───────────────────────────────────────────────────────

class TestComputeScore:
    def test_acheteur_parfait_score_max(self):
        s = acheteur(score_urgence=3, score_capacite_fin=3, score_engagement=3, score_motivation=3)
        assert s == 24

    def test_acheteur_tout_nul_score_zero(self):
        s = acheteur(score_urgence=0, score_capacite_fin=0, score_engagement=0, score_motivation=0)
        assert s == 0

    def test_vendeur_parfait_score_max(self):
        s = vendeur(score_urgence=3, score_maturite=3, score_qualite_bien=3, score_motivation=3)
        assert s == 24

    def test_redistribution_axe_absent_ne_penalise_pas(self):
        """
        Vendeur sans info sur qualité du bien (null) :
        score doit être supérieur à si on mettait 0 pour ce champ.
        """
        with_null = vendeur(score_urgence=3, score_maturite=3, score_qualite_bien=None, score_motivation=3)
        with_zero = vendeur(score_urgence=3, score_maturite=3, score_qualite_bien=0, score_motivation=3)
        assert with_null > with_zero

    def test_redistribution_normalise_a_24(self):
        """Vendeur avec seulement urgence=3 connue → score normalisé ≠ 0."""
        s = vendeur(score_urgence=3, score_maturite=None, score_qualite_bien=None, score_motivation=None)
        assert s == 24  # 3/3 × 24 = 24

    def test_score_to_label(self):
        assert score_to_label(24) == "chaud"
        assert score_to_label(18) == "chaud"
        assert score_to_label(17) == "tiede"
        assert score_to_label(11) == "tiede"
        assert score_to_label(10) == "froid"
        assert score_to_label(0) == "froid"

    def test_score_to_action(self):
        assert score_to_action(24) == "rdv"
        assert score_to_action(18) == "rdv"
        assert score_to_action(17) == "nurturing_14j"
        assert score_to_action(11) == "nurturing_14j"
        assert score_to_action(10) == "nurturing_30j"
        assert score_to_action(0) == "nurturing_30j"


# ── cas métier acheteurs ──────────────────────────────────────────────────────

class TestAcheteurs:
    def test_cas1_acheteur_chaud_mutation_pret_visite(self):
        """Acheteur : mutation pro + prêt accordé + déjà visité → CHAUD."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 3,      # mutation pro, avant septembre
            "score_capacite_fin": 3, # accord de prêt
            "score_engagement": 3,   # 4 visites ailleurs
            "score_motivation": 3,   # mutation pro
            "projet": "achat",
            "localisation": "Lyon 6e",
            "resume": "Marc, mutation pro, accord prêt, 4 visites.",
        })
        assert result.lead_type == "acheteur"
        assert result.score_total >= SCORE_SEUIL_CHAUD
        assert result.prochaine_action == "rdv"

    def test_cas2_acheteur_tiede_apport_pas_urgent(self):
        """Acheteur : bon financement mais pas d'urgence → TIÈDE."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 1,      # délai vague 6 mois
            "score_capacite_fin": 2, # apport 30%
            "score_engagement": 2,   # a commencé à chercher
            "score_motivation": 1,   # projet vague
            "projet": "achat",
        })
        assert SCORE_SEUIL_TIEDE <= result.score_total < SCORE_SEUIL_CHAUD

    def test_cas3_acheteur_froid_sans_urgence_sans_financement(self):
        """Acheteur : aucune urgence, aucun financement mentionné → FROID."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 0,
            "score_capacite_fin": 0,
            "score_engagement": 0,
            "score_motivation": 0,
        })
        assert result.score_total < SCORE_SEUIL_TIEDE
        assert result.prochaine_action == "nurturing_30j"

    def test_cas4_piege_tout_rempli_mais_deux_ans(self):
        """
        PIÈGE : profil complet sur le papier mais horizon 2 ans,
        'pas de pression'. Doit rester FROID.
        """
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 0,      # "2 ans, pas de pression" = 0
            "score_capacite_fin": 2, # apport 30%
            "score_engagement": 1,   # quelques visites il y a 6 mois
            "score_motivation": 1,   # projet vague
        })
        assert result.score_total < SCORE_SEUIL_CHAUD
        # poids urgence ×3 = 0×3=0, capacite ×2=4, engagement ×2=2, motivation ×1=1 → total 7
        # normalisé 7/24 = 7 → FROID
        assert result.score_total < SCORE_SEUIL_TIEDE


# ── cas métier vendeurs ───────────────────────────────────────────────────────

class TestVendeurs:
    def test_cas5_vendeur_chaud_succession_deadline(self):
        """Vendeur : succession + délai notarial + estimation faite → CHAUD."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 3,      # succession, 3 mois
            "score_maturite": 3,     # estimation faite, prêt à signer
            "score_qualite_bien": 2, # maison 95m² Saint-Cyprien
            "score_motivation": 3,   # héritage
            "projet": "vente",
            "localisation": "Toulouse Saint-Cyprien",
        })
        assert result.lead_type == "vendeur"
        assert result.score_total >= SCORE_SEUIL_CHAUD
        assert result.prochaine_action == "rdv"

    def test_cas6_vendeur_tiede_decide_pas_encore_estime(self):
        """Vendeur : décision prise mais pas encore avancé dans le projet."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 2,      # veut vendre dans 6 mois
            "score_maturite": 2,     # décision prise ("on doit vendre")
            "score_qualite_bien": 2, # bien standard
            "score_motivation": 2,   # retraite
        })
        assert SCORE_SEUIL_TIEDE <= result.score_total < SCORE_SEUIL_CHAUD

    def test_cas7_vendeur_froid_curiosite_pure(self):
        """
        PIÈGE : "juste pour info, pas forcément envie de vendre".
        Doit être FROID.
        """
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 0,
            "score_maturite": 0,     # "juste pour info"
            "score_qualite_bien": 1,
            "score_motivation": 0,
        })
        assert result.score_total < SCORE_SEUIL_TIEDE
        assert result.prochaine_action == "nurturing_30j"

    def test_cas8_piege_vendeur_infos_absentes_pas_penalise(self):
        """
        RÈGLE CLEF : vendeur succession + urgence max + motivation max
        mais qualité bien inconnue (null).
        Doit quand même être CHAUD grâce à la redistribution.
        """
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 3,
            "score_maturite": 2,
            "score_qualite_bien": None,   # info absente → ne pénalise pas
            "score_motivation": 3,
        })
        # axes connus : urgence(3)×3 + maturite(2)×3 + motivation(3)×1 = 9+6+3=18
        # max_raw = (3+3+1)×3 = 21 ; normalisé = 18/21×24 ≈ 21 → CHAUD
        assert result.score_total >= SCORE_SEUIL_CHAUD

    def test_cas9_vendeur_succession_sans_info_bien(self):
        """
        L'exemple de la spec : 'succession, on doit vendre dans 3 mois,
        maison à Toulouse Saint-Cyprien' → CHAUD même sans prix en tête.
        """
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 3,       # succession + 3 mois
            "score_maturite": 2,      # "on doit vendre" = décision prise
            "score_qualite_bien": 2,  # maison Toulouse bon quartier
            "score_motivation": 3,    # héritage
        })
        assert result.score_total >= SCORE_SEUIL_CHAUD, (
            f"Score {result.score_total} insuffisant pour lead succession urgent"
        )


# ── locataires ────────────────────────────────────────────────────────────────

class TestLocataires:
    def test_cas10_locataire_chaud_bail_termine_cdi(self):
        """Locataire : bail qui se termine + CDI + 5 visites → CHAUD."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "locataire",
            "score_urgence": 3,
            "score_capacite_fin": 3,
            "score_engagement": 3,
            "score_motivation": 3,
            "projet": "location",
        })
        assert result.lead_type == "locataire"
        assert result.score_total >= SCORE_SEUIL_CHAUD

    def test_cas11_locataire_froid_curieux(self):
        """Locataire : curiosité sans urgence ni engagement."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "locataire",
            "score_urgence": 0,
            "score_capacite_fin": 1,
            "score_engagement": 0,
            "score_motivation": 0,
        })
        assert result.score_total < SCORE_SEUIL_TIEDE


# ── cas ambigu ────────────────────────────────────────────────────────────────

class TestAmbiguLeads:
    def test_cas12_ambigu_vend_pour_racheter(self):
        """Cas ambigu : veut vendre SA maison pour racheter plus grand."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "is_ambiguous": True,
            "linked_lead_hint": "Acheteur T4+ Lyon, budget ~340k€ après vente Grenoble",
            "score_urgence": 3,      # offre acceptée sur bien à acheter
            "score_maturite": 3,     # offre d'achat signée = urgence maximale
            "score_qualite_bien": 2,
            "score_motivation": 2,
        })
        assert result.is_ambiguous is True
        assert result.linked_lead_hint is not None
        assert result.lead_type == "vendeur"
        assert result.score_total >= SCORE_SEUIL_CHAUD


# ── régression urgence implicite ─────────────────────────────────────────────

class TestUrgenceImplicite:
    """
    Régression : le LLM sous-cote l'urgence quand le motif est fort
    sans mot temporel explicite.
    Bug observé en prod : SMS divorce + budget + zone → 5/24 froid
    au lieu de chaud attendu.
    """

    def test_divorce_explicite_doit_etre_chaud(self):
        """SMS prod réel : divorce + 'très urgent' → score_urgence=3 → CHAUD."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 3,
            "score_capacite_fin": None,
            "score_engagement": None,
            "score_motivation": 3,
            "projet": "achat",
            "localisation": "Toulouse",
            "budget": "300000",
            "motivation": "divorce",
        })
        assert result.score_total >= SCORE_SEUIL_CHAUD, (
            f"Lead divorce + très urgent doit être chaud, score: {result.score_total}"
        )

    def test_succession_implicite_doit_etre_chaud(self):
        """Vendeur succession sans mot 'urgent' → urgence=3 par contexte."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "vendeur",
            "score_urgence": 3,
            "score_maturite": 2,
            "score_qualite_bien": None,
            "score_motivation": 3,
            "projet": "vente",
            "motivation": "succession",
        })
        assert result.score_total >= SCORE_SEUIL_CHAUD

    def test_mutation_avec_deadline_doit_etre_chaud(self):
        """Acheteur mutation pro avec date précise → urgence=3."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 3,
            "score_capacite_fin": None,
            "score_engagement": None,
            "score_motivation": 3,
            "projet": "achat",
            "motivation": "mutation_pro",
        })
        assert result.score_total >= SCORE_SEUIL_CHAUD


# ── invariants de robustesse ──────────────────────────────────────────────────

class TestRobustesse:
    def test_lead_type_invalide_fallback_acheteur(self):
        result = LeadExtractionResult.from_dict({"lead_type": "n/a"})
        assert result.lead_type == "acheteur"

    def test_lead_type_absent_fallback_acheteur(self):
        result = LeadExtractionResult.from_dict({})
        assert result.lead_type == "acheteur"

    def test_axes_hors_range_clampes(self):
        """Valeurs hors 0-3 doivent être clampées."""
        result = LeadExtractionResult.from_dict({
            "lead_type": "acheteur",
            "score_urgence": 99,
            "score_capacite_fin": -5,
        })
        assert result.score_urgence == 3
        assert result.score_capacite_fin == 0

    def test_recompute_score_coherent_avec_label(self):
        """score_total et score_qualification doivent être cohérents."""
        from lib.call_extraction_pipeline import CallExtractionData
        from lib.lead_extraction.schema import _to_int03, score_to_label
        data = CallExtractionData.from_json(
            {
                "lead_type": "vendeur",
                "score_urgence": 3,
                "score_maturite": 3,
                "score_qualite_bien": 2,
                "score_motivation": 3,
            },
            model="test",
            cost_usd=0.0,
        )
        assert data.score_qualification == score_to_label(data.score_total)


# ── E2E intégration : SMS prod réel avec LLM mocké ───────────────────────────

_SMS_PROD_DIVORCE = (
    "Bonjour, je cherche une maison de minimum 90m2 sur Toulouse et alentours "
    "proche, j'ai 300k de budget. Très urgent, je suis actuellement en divorce"
)

_LLM_RESPONSE_DIVORCE = {
    "lead_type": "acheteur",
    "score_urgence": 3,
    "score_capacite_fin": None,
    "score_engagement": None,
    "score_maturite": None,
    "score_qualite_bien": None,
    "score_motivation": 3,
    "is_ambiguous": False,
    "linked_lead_hint": None,
    "projet": "achat",
    "localisation": "Toulouse et alentours",
    "budget": "300000",
    "timeline": None,
    "financement": None,
    "motivation": "divorce",
    "prochaine_action": "rdv",
    "resume": "Prospect en divorce cherche maison 90m² minimum sur Toulouse, budget 300k€. Situation très urgente.",
}


class TestSmsProdRegressionDivorce:
    """
    E2E : SMS prod réel (divorce + 'très urgent') avec LLM mocké.
    Vérifie que le pipeline complet sort CHAUD (≥18/24).

    Bug reproduit : avant le fix, le LLM retournait score_urgence=0 ou 1
    malgré 'très urgent' + 'divorce' → score 5/24 → froid.
    """

    def test_sms_prod_divorce_sort_chaud(self, monkeypatch):
        import json
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("TESTING", "true")
        monkeypatch.setenv("MOCK_MODE", "never")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from config.settings import get_settings
        get_settings.cache_clear()

        mock_content = MagicMock()
        mock_content.text = json.dumps(_LLM_RESPONSE_DIVORCE)
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage.input_tokens = 600
        mock_response.usage.output_tokens = 120
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        messages = [
            {
                "role": "user",
                "contenu": _SMS_PROD_DIVORCE,
                "created_at": datetime(2026, 5, 7, 9, 0),
            }
        ]

        with patch("anthropic.Anthropic", return_value=mock_client), \
             patch("memory.cost_logger.log_api_action"):
            from lib.sms_extraction_pipeline import SmsExtractionPipeline
            pipeline = SmsExtractionPipeline.__new__(SmsExtractionPipeline)
            pipeline._mock = False
            pipeline._settings = MagicMock(
                claude_model="claude-sonnet-4-6",
                anthropic_api_key="test-key",
            )
            result = pipeline.extract(lead_id="lead-divorce-prod", messages=messages)

        assert result is not None, "Le pipeline ne doit pas retourner None"
        assert result.score_total >= SCORE_SEUIL_CHAUD, (
            f"SMS prod divorce doit être CHAUD (≥{SCORE_SEUIL_CHAUD}), "
            f"score obtenu: {result.score_total}"
        )

        get_settings.cache_clear()
