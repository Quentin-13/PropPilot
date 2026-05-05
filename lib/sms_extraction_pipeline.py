"""
Extraction structurée depuis un thread SMS complet via Claude.

Analyse la conversation SMS (tous les messages depuis le début) et extrait
les mêmes 15 champs que CallExtractionPipeline pour un affichage unifié.

Usage :
    from lib.sms_extraction_pipeline import SmsExtractionPipeline
    pipeline = SmsExtractionPipeline()
    data = pipeline.extract(lead_id="abc", messages=[...])
    # data est un CallExtractionData ou None si thread vide
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SMS_EXTRACTION_PROMPT_VERSION = "sms-v1"

# Coût Claude Sonnet (identique au pipeline appels)
_CLAUDE_COST_INPUT_PER_TOKEN = 3e-6
_CLAUDE_COST_OUTPUT_PER_TOKEN = 15e-6

SMS_EXTRACTION_PROMPT = """Tu es un expert en qualification immobilière française.
Analyse l'échange SMS suivant entre un conseiller (agence) et un prospect.

CONVERSATION SMS :
{thread}

RÈGLES :
- Si une information n'est pas mentionnée explicitement, retourne null
- Ne déduis pas ce qui n'est pas dit
- budget_min et budget_max sont des entiers en euros (ex: 350000)
- surface_min et surface_max sont des entiers en m²
- score_qualification : "chaud" (projet concret < 3 mois + financement OK), "tiede" (projet < 6 mois OU financement flou), "froid" (sinon)
- criteres, timing, financement sont des objets JSON

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
  "prochaine_action_suggeree": "<description libre : rappeler dans X jours, envoyer biens, proposer estimation, etc. ou null>",
  "resume_appel": "<résumé de l'échange en 2-3 phrases en langage naturel>",
  "points_attention": [
    "<objection ou signal d'achat ou blocage détecté, une entrée par élément>"
  ]
}}"""


def _format_thread(messages: list[dict]) -> str:
    """Formate les messages SMS pour le prompt Claude."""
    lines = []
    for msg in messages:
        role = msg.get("role", "user")
        speaker = "Conseiller" if role == "assistant" else "Prospect"
        created_at = msg.get("created_at")
        if created_at and hasattr(created_at, "strftime"):
            ts = created_at.strftime("%d/%m %H:%M")
        elif isinstance(created_at, str) and created_at:
            ts = created_at[:16].replace("T", " ")
        else:
            ts = ""
        body = msg.get("contenu") or ""
        prefix = f"[{ts}] " if ts else ""
        lines.append(f"{prefix}{speaker} : {body}")
    return "\n".join(lines)


class SmsExtractionPipeline:
    """Extrait les données structurées d'un thread SMS via Claude."""

    def __init__(self) -> None:
        from config.settings import get_settings
        s = get_settings()
        self._settings = s
        self._mock = (
            not s.anthropic_available
            or s.testing
            or s.mock_mode == "always"
        )

    def extract(self, lead_id: str, messages: list[dict]):
        """
        Analyse un thread SMS complet et retourne un CallExtractionData.

        Args:
            lead_id: ID du lead (pour corrélation dans les logs)
            messages: Liste de dicts {role, contenu, created_at}
                      dans l'ordre chronologique

        Returns:
            CallExtractionData ou None si le thread est vide.
        """
        from lib.call_extraction_pipeline import CallExtractionData

        if not messages:
            logger.info("[SMS] Thread vide lead_id=%s — skip", lead_id)
            return None

        if self._mock:
            logger.info("[MOCK] SmsExtractionPipeline.extract lead_id=%s", lead_id)
            mock = CallExtractionData.mock()
            mock.extraction_prompt_version = SMS_EXTRACTION_PROMPT_VERSION
            mock.source = "mock"
            return mock

        thread = _format_thread(messages)
        model = self._settings.claude_model
        prompt = SMS_EXTRACTION_PROMPT.format(thread=thread)

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
                response.usage.input_tokens * _CLAUDE_COST_INPUT_PER_TOKEN
                + response.usage.output_tokens * _CLAUDE_COST_OUTPUT_PER_TOKEN
            )

            log_api_action(
                client_id=lead_id,
                action_type="sms_extraction",
                provider="anthropic",
                model=model,
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
            )

            result = CallExtractionData.from_json(data, model=model, cost_usd=round(cost, 6))
            result.extraction_prompt_version = SMS_EXTRACTION_PROMPT_VERSION
            logger.info(
                "[SMS] Extraction OK lead_id=%s score=%s cost=$%.4f",
                lead_id, result.score_qualification, cost,
            )
            return result

        except Exception as exc:
            logger.error("[SMS] Extraction erreur lead_id=%s: %s — mock fallback", lead_id, exc)
            mock = CallExtractionData.mock()
            mock.extraction_prompt_version = SMS_EXTRACTION_PROMPT_VERSION
            mock.source = "mock_fallback"
            return mock
