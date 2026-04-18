"""
VoiceInboundAgent — Gestion des appels entrants uniquement.
Décroche, joue un message vocal naturel, déclenche un SMS de qualification.
Traite les transcriptions post-appel (résumé IA, booking RDV).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from config.settings import get_settings
from memory.database import get_connection
from memory.lead_repository import (
    add_conversation_message,
    get_lead,
    update_lead,
)
from memory.models import Call, Canal, Lead, LeadStatus
from memory.usage_tracker import check_and_consume
from tools.calendar_tool import CalendarTool

logger = logging.getLogger(__name__)


class VoiceInboundAgent:
    """
    Agent appels voix entrants.
    - Répond aux appels entrants sur le numéro Twilio 07 du client
    - Joue un message vocal naturel (TwiML Polly.Lea)
    - Déclenche un SMS de qualification en arrière-plan
    - Traite les transcriptions post-appel (résumé IA + booking RDV si détecté)
    """

    def __init__(self, client_id: str, tier: str = "Starter"):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()
        self._anthropic_client = None

    def _get_anthropic(self):
        if self._anthropic_client is None and self.settings.anthropic_available:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    # ─── Traitement post-appel ───────────────────────────────────────────────

    def process_call_ended(
        self,
        call_id: str,
        lead_id: str,
        transcript: str = "",
        duration_s: int = 0,
    ) -> dict:
        """
        Traite un appel entrant terminé : résumé IA, scoring, booking RDV.
        Appelé par le webhook Twilio (call-status callback).

        Returns:
            {"lead_updated": bool, "rdv_booked": bool, "anomalies": list, "summary": str}
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"lead_updated": False, "error": "Lead introuvable"}

        summary, post_score, rdv_detected, anomalies = self._analyze_call_transcript(
            transcript=transcript,
            lead=lead,
        )

        # Comptabilise les minutes voix entrant
        minutes_used = duration_s / 60.0
        check_and_consume(self.client_id, "voice_minute", amount=minutes_used, tier=self.tier)

        if post_score > lead.score:
            lead.score = post_score
        if rdv_detected:
            lead.statut = LeadStatus.RDV_BOOKÉ
            lead.rdv_date = datetime.now()
        update_lead(lead)

        self._update_call_in_db(
            call_id=call_id,
            duration_s=duration_s,
            transcript=transcript,
            summary=summary,
            score_post_appel=post_score,
            anomalies=anomalies,
            rdv_booke=rdv_detected,
        )

        if transcript:
            add_conversation_message(
                lead_id=lead_id,
                client_id=self.client_id,
                role="assistant",
                contenu=f"[Résumé appel entrant {call_id}] {summary}",
                canal=Canal.APPEL,
                metadata={"call_id": call_id, "duration_s": duration_s},
            )

        rdv_event = None
        if rdv_detected:
            rdv_event = self._auto_book_rdv(lead, summary)

        logger.info(f"Appel entrant {call_id} traité : durée {duration_s}s, score {post_score}, RDV: {rdv_detected}")

        return {
            "lead_updated": True,
            "rdv_booked": rdv_detected,
            "rdv_event": rdv_event,
            "anomalies": anomalies,
            "summary": summary,
            "duration_s": duration_s,
            "post_score": post_score,
        }

    # ─── Analyse transcription ────────────────────────────────────────────────

    def _analyze_call_transcript(
        self, transcript: str, lead: Lead
    ) -> tuple[str, int, bool, list]:
        """
        Analyse la transcription via Claude.
        Returns: (summary, post_score, rdv_detected, anomalies)
        """
        client = self._get_anthropic()

        if not transcript or not client:
            summary = "Appel entrant traité — contact réceptif."
            post_score = min(10, lead.score + 1)
            rdv_detected = "rdv" in transcript.lower() or "rendez-vous" in transcript.lower() if transcript else False
            return summary, post_score, rdv_detected, []

        prompt = f"""Analyse cette transcription d'appel immobilier entrant et retourne du JSON.

TRANSCRIPTION :
{transcript}

PROFIL LEAD EXISTANT :
- Projet : {lead.projet.value}
- Score actuel : {lead.score}/10
- Budget : {lead.budget}
- Localisation : {lead.localisation}

Retourne UNIQUEMENT ce JSON :
{{
  "resume": "<résumé en 2-3 phrases, ton professionnel>",
  "score_post_appel": <entier 0-10>,
  "rdv_confirme": <true/false>,
  "anomalies": [
    {{"type": "<financement|document|prix|delai>", "description": "<desc>", "severite": "<haute|moyenne|basse>"}}
  ],
  "prochaine_action": "<rappel|rdv|nurturing|mandat>"
}}"""

        try:
            from memory.cost_logger import log_api_action
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            log_api_action(
                client_id=self.client_id,
                action_type="lead",
                provider="anthropic",
                model=self.settings.claude_model,
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
            )

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            return (
                data.get("resume", ""),
                data.get("score_post_appel", lead.score),
                data.get("rdv_confirme", False),
                data.get("anomalies", []),
            )

        except Exception as e:
            logger.warning(f"Erreur analyse transcription appel entrant : {e}")
            return f"Appel traité — score {lead.score}/10.", lead.score, False, []

    def _auto_book_rdv(self, lead: Lead, summary: str) -> Optional[dict]:
        """Book automatiquement un RDV si détecté dans la transcription."""
        calendar = CalendarTool()
        slots = calendar.get_available_slots(days_ahead=7, user_id=self.client_id)

        if not slots:
            return None

        slot = slots[0]
        result = calendar.book_appointment(
            lead=lead,
            slot=slot,
            user_id=self.client_id,
            send_email=bool(lead.email),
        )
        if result.get("success"):
            logger.info(
                f"RDV booké post-appel — lead={lead.id} slot={slot['label']} "
                f"email={'✓' if result.get('email_sent') else '✗'}"
            )
        return result

    # ─── DB helpers ──────────────────────────────────────────────────────────

    def _save_call_to_db(self, lead_id: str, call_id: str, statut: str = "ringing") -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO calls
                   (id, lead_id, client_id, retell_call_id, direction, statut)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO NOTHING""",
                (call_id, lead_id, self.client_id, call_id, "inbound", statut),
            )

    def _update_call_in_db(
        self,
        call_id: str,
        duration_s: int,
        transcript: str,
        summary: str,
        score_post_appel: int,
        anomalies: list,
        rdv_booke: bool,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """UPDATE calls
                   SET duree_secondes = ?, statut = 'completed',
                       transcript = ?, resume = ?,
                       score_post_appel = ?, anomalies = ?, rdv_booke = ?
                   WHERE retell_call_id = ?""",
                (
                    duration_s, transcript, summary,
                    score_post_appel,
                    json.dumps(anomalies, ensure_ascii=False),
                    1 if rdv_booke else 0,
                    call_id,
                ),
            )

    def get_calls_history(self, limit: int = 50) -> list[dict]:
        """Historique des appels entrants pour le dashboard."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM calls WHERE client_id = ? AND direction = 'inbound'
                   ORDER BY created_at DESC LIMIT ?""",
                (self.client_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]
