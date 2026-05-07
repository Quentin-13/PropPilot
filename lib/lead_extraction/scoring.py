"""
Extraction et scoring leads via Claude.
Deux grilles distinctes : acheteur/locataire et vendeur.
Score normalisé 0-24 avec redistribution des poids si info absente.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from lib.lead_extraction.prompts import EXTRACTION_PROMPT
from lib.lead_extraction.schema import (
    LeadExtractionResult,
    SCORE_SEUIL_CHAUD,
    SCORE_SEUIL_TIEDE,
    compute_score,
    score_to_action,
)

logger = logging.getLogger(__name__)


def extract_lead_info(
    text: str,
    anthropic_client,
    client_id: str,
    model: str = "claude-sonnet-4-5",
) -> LeadExtractionResult:
    """
    Extrait des informations structurées depuis un texte libre via Claude.

    Returns LeadExtractionResult avec score normalisé 0-24.
    Fallback mock si pas de client Anthropic.
    """
    if not anthropic_client:
        logger.info("[LeadExtraction] Pas de client Anthropic — mock")
        return LeadExtractionResult.mock()

    prompt = EXTRACTION_PROMPT.format(text=text)

    try:
        from memory.cost_logger import log_api_action

        response = anthropic_client.messages.create(
            model=model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        log_api_action(
            client_id=client_id,
            action_type="lead",
            provider="anthropic",
            model=model,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
        )

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        data = json.loads(raw)
        return LeadExtractionResult.from_dict(data, source="llm")

    except Exception as e:
        logger.warning("[LeadExtraction] Erreur extraction : %s — fallback mock", e)
        return LeadExtractionResult.mock()


def apply_extraction_to_lead(lead, result: LeadExtractionResult):
    """
    Applique les champs d'un LeadExtractionResult sur un objet Lead.
    Retourne le lead modifié (sans le sauvegarder en DB).
    Ne rétrograde jamais le score existant.
    """
    from memory.models import ProjetType, LeadStatus, NurturingSequence
    from datetime import datetime, timedelta

    if result.score_total > (lead.score or 0):
        lead.score = result.score_total

    lead.resume = result.resume

    if result.projet:
        try:
            lead.projet = ProjetType(result.projet)
        except ValueError:
            pass

    if result.localisation:
        lead.localisation = result.localisation
    if result.budget:
        lead.budget = result.budget
    if result.timeline:
        lead.timeline = result.timeline
    if result.financement:
        lead.financement = result.financement
    if result.motivation:
        lead.motivation = result.motivation

    # Routage par score (seuils sur 24)
    if result.score_total >= SCORE_SEUIL_CHAUD:
        lead.statut = LeadStatus.QUALIFIE
        lead.nurturing_sequence = None
    elif result.score_total >= SCORE_SEUIL_TIEDE:
        lead.statut = LeadStatus.NURTURING
        lead.nurturing_sequence = (
            NurturingSequence.VENDEUR_CHAUD
            if result.projet == "vente"
            else NurturingSequence.ACHETEUR_QUALIFIE
        )
        lead.prochain_followup = datetime.now() + timedelta(days=1)
    else:
        lead.statut = LeadStatus.NURTURING
        lead.nurturing_sequence = NurturingSequence.LEAD_FROID
        lead.prochain_followup = datetime.now() + timedelta(days=7)

    return lead
