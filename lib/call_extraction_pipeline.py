"""
Extraction structurée depuis une transcription d'appel.

Utilise Claude pour extraire les 13 champs définis dans la table call_extractions.
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

CALL_EXTRACTION_PROMPT = """Tu es un expert en qualification immobilière française.
Analyse la transcription d'appel suivante et extrais les informations structurées.

TRANSCRIPTION :
{transcript}

RÈGLES :
- Si une information n'est pas mentionnée, retourne null pour ce champ
- Ne déduis pas ce qui n'est pas dit explicitement
- budget_min et budget_max sont des entiers en euros (ex: 350000, sans espaces ni symboles)
- surface_min et surface_max sont des entiers en m²
- score_qualification : "chaud" (projet concret < 3 mois + financement OK), "tiede" (projet < 6 mois OU financement flou), "froid" (sinon)
- criteres, timing, financement, points_attention sont des objets/tableaux JSON

Retourne UNIQUEMENT un JSON valide, sans texte autour :
{{
  "type_projet": "<achat|vente|location|investissement|null>",
  "budget_min": <entier ou null>,
  "budget_max": <entier ou null>,
  "zone_geographique": "<ville/quartier/secteur ou null>",
  "type_bien": "<T1|T2|T3|T4|T5+|maison|villa|local|autre|null>",
  "surface_min": <entier ou null>,
  "surface_max": <entier ou null>,
  "criteres": {{
    "parking": <true|false|null>,
    "jardin": <true|false|null>,
    "ascenseur": <true|false|null>,
    "balcon": <true|false|null>,
    "terrasse": <true|false|null>,
    "garage": <true|false|null>,
    "cave": <true|false|null>,
    "autres": []
  }},
  "timing": {{
    "urgence": "<< 3 mois|3-6 mois|6-12 mois|> 12 mois|non précisé>",
    "echeance_souhaitee": "<description libre ou null>"
  }},
  "financement": {{
    "type": "<accord_bancaire|apport_fort|apport_faible|sans_apport|vente_en_cours|null>",
    "detail": "<description libre ou null>"
  }},
  "motivation": "<premier_achat|investissement_locatif|demenagement|agrandissement_famille|divorce|mutation_pro|retraite|autre|null>",
  "score_qualification": "<chaud|tiede|froid>",
  "prochaine_action_suggeree": "<description libre : rappeler dans X jours, envoyer biens, proposer estimation, etc.>",
  "resume_appel": "<résumé en 3-5 phrases en langage naturel>",
  "points_attention": [
    "<objection ou signal d'achat ou blocage détecté, une entrée par élément>"
  ]
}}"""


@dataclass
class CallExtractionData:
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
    score_qualification: str = "froid"
    prochaine_action_suggeree: Optional[str] = None
    resume_appel: Optional[str] = None
    points_attention: list = field(default_factory=list)
    extraction_model: str = "claude-sonnet-4-5"
    extraction_prompt_version: str = EXTRACTION_PROMPT_VERSION
    cost_usd: float = 0.0
    source: str = "claude"  # "claude" | "mock"

    @classmethod
    def mock(cls) -> "CallExtractionData":
        return cls(
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
            score_qualification="chaud",
            prochaine_action_suggeree="Envoyer sélection T3 Paris 15e, rappeler dans 3 jours",
            resume_appel=(
                "[MOCK] Couple cherche T3 Paris 15e, 65-80m², budget 400-500k€. "
                "Mutation professionnelle, déménagement dans 3-6 mois. "
                "Apport disponible, accord bancaire en cours. Profil chaud."
            ),
            points_attention=["Accord bancaire à confirmer", "Délai contraignant"],
            source="mock",
        )

    @classmethod
    def from_json(cls, data: dict, model: str, cost_usd: float) -> "CallExtractionData":
        return cls(
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
            score_qualification=data.get("score_qualification") or "froid",
            prochaine_action_suggeree=data.get("prochaine_action_suggeree"),
            resume_appel=data.get("resume_appel"),
            points_attention=data.get("points_attention") or [],
            extraction_model=model,
            extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
            cost_usd=cost_usd,
            source="claude",
        )


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

        Args:
            call_id: ID de l'appel (pour corrélation dans les logs)
            transcript: Texte de la transcription Whisper

        Returns:
            CallExtractionData prêt à être stocké en DB
        """
        if self._mock or not transcript.strip():
            logger.info("[MOCK] CallExtractionPipeline.extract call_id=%s", call_id)
            return CallExtractionData.mock()

        model = self._settings.claude_model
        prompt = CALL_EXTRACTION_PROMPT.format(transcript=transcript)

        try:
            import anthropic
            from memory.cost_logger import log_api_action

            client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
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

            raw = response.content[0].text.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)

            cost = (
                response.usage.input_tokens * CLAUDE_COST_INPUT_PER_TOKEN
                + response.usage.output_tokens * CLAUDE_COST_OUTPUT_PER_TOKEN
            )

            log_api_action(
                client_id=call_id,
                action_type="call_extraction",
                provider="anthropic",
                model=model,
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
            )

            result = CallExtractionData.from_json(data, model=model, cost_usd=round(cost, 6))
            logger.info(
                "[Claude] Extraction OK call_id=%s score=%s cost=$%.4f",
                call_id, result.score_qualification, cost,
            )
            return result

        except Exception as exc:
            logger.error("[Claude] Extraction erreur call_id=%s: %s — mock fallback", call_id, exc)
            mock = CallExtractionData.mock()
            mock.source = "mock_fallback"
            return mock
