"""
Extraction consolidée cross-canal.

Reconstruit le transcript complet d'un lead (SMS + appels) et lance
l'extraction IA sur l'historique total. Met à jour le lead existant
sans créer de doublon.

Règles :
- Transcript vide → retourne None, aucune modification
- Extraction réussie → met à jour leads.* y compris score à la baisse
  (reflète l'état actuel du lead d'après tout l'historique)
- Extraction échouée → marque leads.extraction_status='failed',
  ne touche pas aux autres champs
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def extract_and_update_lead(lead_id: str, client_id: str):
    """
    Lance l'extraction consolidée (SMS + appels) pour un lead existant.

    Contrairement aux extractions partielles (SMS seul, appel seul),
    l'extraction consolidée représente l'état actuel complet du lead.
    Le score peut donc baisser si le prospect a refroidi (overwrite_score=True).

    Persistance via save_sms_extraction (source='sms') — compatibilité schéma.

    Args:
        lead_id:   ID du lead à mettre à jour
        client_id: ID client — isolation multi-tenant obligatoire

    Returns:
        CallExtractionData si extraction lancée, None si transcript vide.
    """
    from lib.consolidated_transcript import build_lead_conversation_transcript
    from lib.call_extraction_pipeline import CallExtractionPipeline
    from memory.call_repository import save_sms_extraction

    transcript = build_lead_conversation_transcript(lead_id, client_id)
    if not transcript.strip():
        logger.info("[Consolidated] Transcript vide lead_id=%s — skip", lead_id)
        return None

    pipeline = CallExtractionPipeline()
    data = pipeline.extract(call_id=lead_id, transcript=transcript)

    # overwrite_score=True : l'extraction consolidée peut faire baisser le score
    # (différent des extractions partielles qui ne rétrogradent jamais)
    # Cas failed : _mark_lead_extraction_failed conserve toutes les données existantes
    save_sms_extraction(lead_id=lead_id, client_id=client_id, data=data, overwrite_score=True)

    logger.info(
        "[Consolidated] lead_id=%s status=%s score=%s",
        lead_id, data.extraction_status, data.score_qualification,
    )

    # Le push CRM est déclenché par les hooks post-extraction (server.py /
    # twilio_voice.py), APRÈS compute_next_action(), pour garantir que la
    # prochaine action recalculée est incluse dans le payload CRM.
    return data
