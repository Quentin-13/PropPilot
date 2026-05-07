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

def _build_sms_prompt(thread: str) -> str:
    from lib.lead_extraction.prompts import SCORING_INSTRUCTIONS, _FEW_SHOT_EXAMPLES
    return (
        "Tu es un expert en qualification immobilière française.\n"
        "Analyse l'échange SMS suivant entre un conseiller (agence) et un prospect.\n\n"
        "CONVERSATION SMS :\n"
        + thread
        + "\n\nRÈGLES GÉNÉRALES :\n"
        "- Si une information n'est pas mentionnée explicitement, retourne null\n"
        "- Ne déduis pas ce qui n'est pas dit\n"
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
        '  "resume_appel": "<résumé en 2-3 phrases>",\n'
        '  "points_attention": ["<signal ou blocage détecté>"]\n'
        "}}"
    )


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

        import anthropic
        from memory.cost_logger import log_api_action
        from lib.lead_extraction.retry import run_with_retry

        thread = _format_thread(messages)
        model = self._settings.claude_model
        prompt = _build_sms_prompt(thread)
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
            _call_once, lead_id=lead_id, source="sms"
        )

        if extraction_status == "failed":
            failed = CallExtractionData(extraction_status="failed", source="claude")
            failed.extraction_prompt_version = SMS_EXTRACTION_PROMPT_VERSION
            return failed

        usage = _usage[0]
        cost = (
            usage.input_tokens * _CLAUDE_COST_INPUT_PER_TOKEN
            + usage.output_tokens * _CLAUDE_COST_OUTPUT_PER_TOKEN
        )
        log_api_action(
            client_id=lead_id,
            action_type="sms_extraction",
            provider="anthropic",
            model=model,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
        )
        result = CallExtractionData.from_json(parsed, model=model, cost_usd=round(cost, 6))
        result.extraction_prompt_version = SMS_EXTRACTION_PROMPT_VERSION
        logger.info(
            "[SMS] Extraction OK lead_id=%s score=%s cost=$%.4f",
            lead_id, result.score_qualification, cost,
        )
        return result
