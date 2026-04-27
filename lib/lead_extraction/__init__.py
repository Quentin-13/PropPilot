"""
Extraction d'informations structurées depuis du texte libre.
Utilisé par la pipeline de transcription d'appels (Whisper) et tout texte non structuré.

Usage :
    from lib.lead_extraction.scoring import extract_lead_info
    result = extract_lead_info(transcription_text, anthropic_client, client_id)
"""
from lib.lead_extraction.schema import (
    LeadExtractionResult,
    SCORE_SEUIL_RDV,
    SCORE_SEUIL_NURTURING_COURT,
    score_to_action,
)
from lib.lead_extraction.scoring import extract_lead_info, compute_score_from_fields

__all__ = [
    "LeadExtractionResult",
    "SCORE_SEUIL_RDV",
    "SCORE_SEUIL_NURTURING_COURT",
    "score_to_action",
    "extract_lead_info",
    "compute_score_from_fields",
]
