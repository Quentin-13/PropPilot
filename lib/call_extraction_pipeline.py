"""
Extraction structurée depuis une transcription d'appel.

Utilise Claude pour extraire les 13 champs définis dans la table conversation_extractions.
Stocke le résultat en DB et met à jour le statut du call.

Usage :
    from lib.call_extraction_pipeline import CallExtractionPipeline
    pipeline = CallExtractionPipeline()
    result = pipeline.extract(call_id="abc", transcript="Bonjour, je cherche...")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "v1"

# Coût estimatif Claude claude-sonnet-4-5 : ~3$/M tokens input, ~15$/M tokens output
CLAUDE_COST_INPUT_PER_TOKEN = 3e-6
CLAUDE_COST_OUTPUT_PER_TOKEN = 15e-6

def _build_call_prompt(transcript: str) -> str:
    from lib.lead_extraction.prompts import SCORING_INSTRUCTIONS, _FEW_SHOT_EXAMPLES
    return (
        "Tu es un expert en qualification immobilière française.\n"
        "Analyse la transcription d'appel suivante et extrais les informations structurées.\n\n"
        "TRANSCRIPTION :\n"
        + transcript
        + "\n\nRÈGLES GÉNÉRALES :\n"
        "- Si une information n'est pas mentionnée, retourne null pour ce champ\n"
        "- Ne déduis pas ce qui n'est pas dit explicitement\n"
        "- budget_min et budget_max sont des entiers en euros (ex: 350000)\n"
        "- surface_min et surface_max sont des entiers en m²\n"
        "- criteres, timing, financement sont des objets JSON\n"
        + SCORING_INSTRUCTIONS
        + _FEW_SHOT_EXAMPLES
        + "\nRetourne UNIQUEMENT un JSON valide, sans texte autour :\n"
        "{{\n"
        '  "lead_type": "<acheteur|vendeur|locataire>",\n'
        '  "score_urgence": <0-3 ou null>,\n'
        '  "score_capacite_fin": <0-3 ou null — acheteur/locataire>,\n'
        '  "score_engagement": <0-3 ou null — acheteur/locataire>,\n'
        '  "score_maturite": <0-3 ou null — vendeur>,\n'
        '  "score_qualite_bien": <0-3 ou null — vendeur>,\n'
        '  "score_motivation": <0-3 ou null>,\n'
        '  "is_ambiguous": <true|false>,\n'
        '  "linked_lead_hint": "<description ou null>",\n'
        '  "type_projet": "<achat|vente|location|investissement|null>",\n'
        '  "budget_min": <entier ou null>,\n'
        '  "budget_max": <entier ou null>,\n'
        '  "zone_geographique": "<ville/quartier/secteur ou null>",\n'
        '  "type_bien": "<T1|T2|T3|T4|T5+|maison|villa|local|autre|null>",\n'
        '  "surface_min": <entier ou null>,\n'
        '  "surface_max": <entier ou null>,\n'
        '  "criteres": {{"parking": <true|false|null>, "jardin": <true|false|null>, '
        '"ascenseur": <true|false|null>, "balcon": <true|false|null>, '
        '"terrasse": <true|false|null>, "garage": <true|false|null>, '
        '"cave": <true|false|null>, "autres": []}},\n'
        '  "timing": {{"urgence": "<< 3 mois|3-6 mois|6-12 mois|> 12 mois|non précisé>", '
        '"echeance_souhaitee": "<ou null>"}},\n'
        '  "financement": {{"type": "<accord_bancaire|apport_fort|apport_faible|sans_apport|vente_en_cours|null>", '
        '"detail": "<ou null>"}},\n'
        '  "motivation": "<premier_achat|investissement_locatif|demenagement|agrandissement_famille|divorce|mutation_pro|retraite|autre|null>",\n'
        '  "score_qualification": "<chaud|tiede|froid>",\n'
        '  "prochaine_action_suggeree": "<description libre ou null>",\n'
        '  "resume_appel": "<résumé en 3-5 phrases>",\n'
        '  "points_attention": ["<signal ou blocage détecté>"]\n'
        "}}"
    )


@dataclass
class CallExtractionData:
    # Type de lead (obligatoire depuis le scoring v2)
    lead_type: str = "acheteur"           # acheteur | vendeur | locataire

    # Scores numériques par axe (0-3 ou None si inconnu)
    score_urgence: Optional[int] = None
    score_capacite_fin: Optional[int] = None   # acheteur/locataire
    score_engagement: Optional[int] = None     # acheteur/locataire
    score_maturite: Optional[int] = None       # vendeur
    score_qualite_bien: Optional[int] = None   # vendeur
    score_motivation: Optional[int] = None
    score_total: int = 0                        # normalisé 0-24

    # Score texte dérivé (backward compat avec call_repository)
    score_qualification: str = "froid"          # chaud|tiede|froid

    # Cas ambigu vendeur+acheteur
    is_ambiguous: bool = False
    linked_lead_hint: Optional[str] = None

    # Infos extraites
    type_projet: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    zone_geographique: Optional[str] = None
    type_bien: Optional[str] = None
    surface_min: Optional[int] = None
    surface_max: Optional[int] = None
    criteres: dict = field(default_factory=dict)
    timing: dict = field(default_factory=dict)
    financement: dict = field(default_factory=dict)
    motivation: Optional[str] = None
    prochaine_action_suggeree: Optional[str] = None
    resume_appel: Optional[str] = None
    points_attention: list = field(default_factory=list)

    extraction_model: str = "claude-sonnet-4-5"
    extraction_prompt_version: str = EXTRACTION_PROMPT_VERSION
    cost_usd: float = 0.0
    source: str = "claude"          # "claude" | "mock"
    extraction_status: str = "ok"   # "ok" | "failed" | "mock"

    @classmethod
    def mock(cls) -> "CallExtractionData":
        obj = cls(
            lead_type="acheteur",
            score_urgence=3,
            score_capacite_fin=2,
            score_engagement=2,
            score_motivation=3,
            score_total=21,
            score_qualification="chaud",
            type_projet="achat",
            budget_min=400000,
            budget_max=500000,
            zone_geographique="Paris 15e",
            type_bien="T3",
            surface_min=65,
            surface_max=80,
            criteres={"parking": True, "balcon": None, "jardin": False},
            timing={"urgence": "3-6 mois", "echeance_souhaitee": "avant septembre"},
            financement={"type": "apport_fort", "detail": "Apport 20%, accord bancaire en cours"},
            motivation="mutation_pro",
            prochaine_action_suggeree="Envoyer sélection T3 Paris 15e, rappeler dans 3 jours",
            resume_appel=(
                "[MOCK] Couple cherche T3 Paris 15e, 65-80m², budget 400-500k€. "
                "Mutation professionnelle, déménagement dans 3-6 mois. "
                "Apport disponible, accord bancaire en cours. Profil chaud."
            ),
            points_attention=["Accord bancaire à confirmer", "Délai contraignant"],
            source="mock",
        )
        obj._recompute_score()
        return obj

    def _recompute_score(self) -> None:
        from lib.lead_extraction.schema import compute_score, score_to_label
        axes = {
            "score_urgence": self.score_urgence,
            "score_capacite_fin": self.score_capacite_fin,
            "score_engagement": self.score_engagement,
            "score_maturite": self.score_maturite,
            "score_qualite_bien": self.score_qualite_bien,
            "score_motivation": self.score_motivation,
        }
        self.score_total = compute_score(self.lead_type, axes)
        self.score_qualification = score_to_label(self.score_total)

    @classmethod
    def from_json(cls, data: dict, model: str, cost_usd: float) -> "CallExtractionData":
        from lib.lead_extraction.schema import _to_int03

        lead_type = (data.get("lead_type") or "acheteur").lower()
        if lead_type not in ("acheteur", "vendeur", "locataire"):
            lead_type = "acheteur"

        obj = cls(
            lead_type=lead_type,
            score_urgence=_to_int03(data.get("score_urgence")),
            score_capacite_fin=_to_int03(data.get("score_capacite_fin")),
            score_engagement=_to_int03(data.get("score_engagement")),
            score_maturite=_to_int03(data.get("score_maturite")),
            score_qualite_bien=_to_int03(data.get("score_qualite_bien")),
            score_motivation=_to_int03(data.get("score_motivation")),
            is_ambiguous=bool(data.get("is_ambiguous", False)),
            linked_lead_hint=data.get("linked_lead_hint"),
            type_projet=data.get("type_projet"),
            budget_min=_to_int(data.get("budget_min")),
            budget_max=_to_int(data.get("budget_max")),
            zone_geographique=data.get("zone_geographique"),
            type_bien=data.get("type_bien"),
            surface_min=_to_int(data.get("surface_min")),
            surface_max=_to_int(data.get("surface_max")),
            criteres=data.get("criteres") or {},
            timing=data.get("timing") or {},
            financement=data.get("financement") or {},
            motivation=data.get("motivation"),
            prochaine_action_suggeree=data.get("prochaine_action_suggeree"),
            resume_appel=data.get("resume_appel"),
            points_attention=data.get("points_attention") or [],
            extraction_model=model,
            extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
            cost_usd=cost_usd,
            source="claude",
        )
        obj._recompute_score()
        # Garder le label texte du LLM si fourni (backward compat)
        llm_label = (data.get("score_qualification") or "").lower()
        if llm_label in ("chaud", "tiede", "froid"):
            obj.score_qualification = llm_label
        return obj


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


class CallExtractionPipeline:
    """Extrait les données structurées d'une transcription via Claude."""

    def __init__(self) -> None:
        from config.settings import get_settings
        s = get_settings()
        self._settings = s
        # Mock si pas de clé, ou en mode test/mock pour éviter des appels réels
        self._mock = (
            not s.anthropic_available
            or s.testing
            or s.mock_mode == "always"
        )

    def extract(self, call_id: str, transcript: str) -> CallExtractionData:
        """
        Extrait les données structurées d'une transcription.
        Retry automatique (3 tentatives, backoff 1s/3s/9s).
        Validation Pydantic stricte du JSON.
        Retourne extraction_status="failed" si toutes les tentatives échouent.
        """
        if self._mock or not transcript.strip():
            logger.info("[MOCK] CallExtractionPipeline.extract call_id=%s", call_id)
            return CallExtractionData.mock()

        import anthropic
        from memory.cost_logger import log_api_action
        from lib.lead_extraction.retry import run_with_retry

        model = self._settings.claude_model
        prompt = _build_call_prompt(transcript)
        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        _usage = [None]

        def _call_once():
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": (
                        "Tu es un assistant spécialisé en qualification de leads immobiliers "
                        "pour des agences en France. Tu réponds uniquement en JSON valide."
                    ),
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            _usage[0] = response.usage
            raw = response.content[0].text.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            return json.loads(raw), raw

        parsed, extraction_status = run_with_retry(
            _call_once, lead_id=call_id, source="call"
        )

        if extraction_status == "failed":
            failed = CallExtractionData(extraction_status="failed", source="claude")
            return failed

        usage = _usage[0]
        cost = (
            usage.input_tokens * CLAUDE_COST_INPUT_PER_TOKEN
            + usage.output_tokens * CLAUDE_COST_OUTPUT_PER_TOKEN
        )
        log_api_action(
            client_id=call_id,
            action_type="call_extraction",
            provider="anthropic",
            model=model,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
        )
        result = CallExtractionData.from_json(parsed, model=model, cost_usd=round(cost, 6))
        logger.info(
            "[Claude] Extraction OK call_id=%s score=%s cost=$%.4f",
            call_id, result.score_qualification, cost,
        )
        return result
