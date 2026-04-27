"""
Fonctions réutilisables d'extraction et de scoring leads.
Source originale : agents/lead_qualifier.py méthodes _compute_score() et _apply_score_and_route().

Usage futur (sprint Capture Appels) :
    from lib.lead_extraction.scoring import extract_lead_info
    result = extract_lead_info(whisper_transcript, anthropic_client, client_id="agency_001")
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from lib.lead_extraction.prompts import EXTRACTION_PROMPT
from lib.lead_extraction.schema import LeadExtractionResult, score_to_action

logger = logging.getLogger(__name__)


def extract_lead_info(
    text: str,
    anthropic_client,
    client_id: str,
    model: str = "claude-sonnet-4-5",
) -> LeadExtractionResult:
    """
    Extrait des informations structurées depuis un texte libre via Claude.

    Args:
        text: Texte à analyser (transcription Whisper, conversation SMS, etc.)
        anthropic_client: Instance anthropic.Anthropic (ou None pour mock)
        client_id: ID du client pour le log de coût
        model: Modèle Claude à utiliser

    Returns:
        LeadExtractionResult avec les données extraites et le score
    """
    if not anthropic_client:
        logger.info("[LeadExtraction] Pas de client Anthropic — mock")
        return LeadExtractionResult.mock()

    prompt = EXTRACTION_PROMPT.format(text=text)

    try:
        from memory.cost_logger import log_api_action

        response = anthropic_client.messages.create(
            model=model,
            max_tokens=600,
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

        # Strip markdown fences if present
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        data = json.loads(raw)
        return LeadExtractionResult.from_dict(data, source="llm")

    except Exception as e:
        logger.warning("[LeadExtraction] Erreur extraction : %s — fallback mock", e)
        return LeadExtractionResult.mock()


def compute_score_from_fields(
    score_urgence: int,
    score_budget: int,
    score_motivation: int,
) -> int:
    """
    Calcul pur du score total sans LLM.
    Utile pour recalculer le score quand les sous-scores sont déjà connus.
    """
    total = score_urgence + score_budget + score_motivation
    return min(total, 10)


def apply_extraction_to_lead(lead, result: LeadExtractionResult):
    """
    Applique les champs d'un LeadExtractionResult sur un objet Lead.
    Retourne le lead modifié (sans le sauvegarder en DB).
    """
    from memory.models import ProjetType, LeadStatus, NurturingSequence
    from datetime import datetime, timedelta

    lead.score = result.score_total
    lead.score_urgence = result.score_urgence
    lead.score_budget = result.score_budget
    lead.score_motivation = result.score_motivation
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

    # Routage par score
    action = result.prochaine_action
    if action == "rdv" or result.score_total >= 7:
        lead.statut = LeadStatus.QUALIFIE
        lead.nurturing_sequence = None
    elif result.score_total >= 4:
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
