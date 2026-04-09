"""
VoiceCallAgent — Appels entrants/sortants IA + booking RDV.
Orchestration via Retell AI + ElevenLabs TTS.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from config.prompts import VOICE_CALL_SYSTEM
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
from tools.elevenlabs_tool import ElevenLabsTool
from tools.twilio_tool import TwilioTool

logger = logging.getLogger(__name__)


class VoiceCallAgent:
    """
    Agent appels voix IA.
    - Appels sortants automatiques pour leads score ≥ 7 non joignables par SMS
    - Réponse appels entrants vers numéro Twilio
    - Script de qualification adapté (vendeur vs acheteur)
    - Booking RDV en temps réel
    - Transcription + résumé IA post-appel
    """

    def __init__(self, client_id: str, tier: str = "Starter"):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()
        self._anthropic_client = None
        self._tts: Optional[ElevenLabsTool] = None

    def _get_anthropic(self):
        if self._anthropic_client is None and self.settings.anthropic_available:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def _get_tts(self) -> ElevenLabsTool:
        if self._tts is None:
            self._tts = ElevenLabsTool()
        return self._tts

    # ─── Synthèse vocale Sophie ───────────────────────────────────────────────

    def synthesize_sophie_intro(self, lead: Optional[Lead] = None) -> dict:
        """
        Génère l'audio d'introduction de Sophie pour un appel sortant.
        Voix naturelle en français, ton professionnel et chaleureux.

        Args:
            lead: Lead concerné (optionnel — générique si absent)

        Returns:
            {"success": bool, "audio_path": str, "duration_s": float,
             "script": str, "mock": bool}
        """
        prenom = lead.prenom if lead and lead.prenom else "cher contact"
        projet = lead.projet.value if lead and lead.projet else "immobilier"
        localisation = f" sur {lead.localisation}" if lead and lead.localisation else ""
        agence = self.settings.agency_name

        script = (
            f"Bonjour {prenom}, je suis Sophie, assistante de {agence}. "
            f"J'appelle concernant votre projet {projet}{localisation}. "
            "Est-ce que vous avez quelques minutes pour en parler ?"
        )

        tts = self._get_tts()
        result = tts.text_to_speech(text=script, voice_name="sophie")
        return {**result, "script": script}

    # ─── Appels sortants ──────────────────────────────────────────────────────

    def call_hot_lead(self, lead_id: str) -> dict:
        """
        Appels sortants désactivés — architecture 1 numéro 06/07 (entrant uniquement).
        Les prospects appellent le 06/07, Sophie répond et déclenche la qualification SMS.
        """
        logger.info(f"[VoiceCall] Appels sortants désactivés (lead {lead_id})")
        return {"success": False, "message": "Appels sortants non disponibles — le prospect doit appeler le 06/07"}

    def call_leads_not_responded(self, min_score: int = 7, sms_delay_min: int = 30) -> list[dict]:
        """
        Lance des appels vers tous les leads chauds n'ayant pas répondu au SMS.

        Args:
            min_score: Score minimum (défaut 7)
            sms_delay_min: Délai depuis le SMS sans réponse (défaut 30 min)

        Returns: Liste des résultats d'appel
        """
        from datetime import timedelta
        threshold = datetime.now() - timedelta(minutes=sms_delay_min)

        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id FROM leads
                   WHERE client_id = ?
                   AND score >= ?
                   AND statut IN ('qualifie', 'en_qualification')
                   AND telephone IS NOT NULL
                   AND updated_at < ?
                   ORDER BY score DESC
                   LIMIT 10""",
                (self.client_id, min_score, threshold.isoformat()),
            ).fetchall()

        results = []
        for row in rows:
            result = self.call_hot_lead(row["id"])
            results.append({"lead_id": row["id"], **result})

        logger.info(f"Appels sortants lancés : {len([r for r in results if r.get('success')])} / {len(results)}")
        return results

    # ─── Traitement post-appel ───────────────────────────────────────────────

    def process_call_ended(
        self,
        call_id: str,
        lead_id: str,
        transcript: str = "",
        duration_s: int = 0,
    ) -> dict:
        """
        Traite un appel terminé : transcription, résumé, scoring, booking RDV.
        Appelé par le webhook Twilio (call-status callback).

        Returns:
            {"lead_updated": bool, "rdv_booked": bool, "anomalies": list, "summary": str}
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"lead_updated": False, "error": "Lead introuvable"}

        analysis = {}

        # Résumé + score post-appel via Claude
        summary, post_score, rdv_detected, anomalies = self._analyze_call_transcript(
            transcript=transcript,
            lead=lead,
            analysis=analysis,
        )

        # Mise à jour temps voix consommé
        minutes_used = duration_s / 60.0
        check_and_consume(self.client_id, "voice_minute", amount=minutes_used, tier=self.tier)

        # Mise à jour lead
        if post_score > lead.score:
            lead.score = post_score
        if rdv_detected:
            lead.statut = LeadStatus.RDV_BOOKÉ
            lead.rdv_date = datetime.now()
        update_lead(lead)

        # Mise à jour de l'appel en base
        self._update_call_in_db(
            call_id=call_id,
            duration_s=duration_s,
            transcript=transcript,
            summary=summary,
            score_post_appel=post_score,
            anomalies=anomalies,
            rdv_booke=rdv_detected,
        )

        # Enregistrement conversation
        if transcript:
            add_conversation_message(
                lead_id=lead_id,
                client_id=self.client_id,
                role="assistant",
                contenu=f"[Résumé appel {call_id}] {summary}",
                canal=Canal.APPEL,
                metadata={"call_id": call_id, "duration_s": duration_s},
            )

        # Booking RDV si détecté
        rdv_event = None
        if rdv_detected:
            rdv_event = self._auto_book_rdv(lead, summary)

        logger.info(f"Appel {call_id} traité : durée {duration_s}s, score {post_score}, RDV: {rdv_detected}")

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
        self, transcript: str, lead: Lead, analysis: dict
    ) -> tuple[str, int, bool, list]:
        """
        Analyse la transcription via Claude.
        Returns: (summary, post_score, rdv_detected, anomalies)
        """
        client = self._get_anthropic()

        if not transcript or not client:
            # Mock minimal
            summary = analysis.get("call_summary", "Appel de qualification. Contact réceptif.")
            post_score = min(10, lead.score + 1)
            rdv_detected = "rdv" in transcript.lower() or "rendez-vous" in transcript.lower() if transcript else False
            return summary, post_score, rdv_detected, []

        prompt = f"""Analyse cette transcription d'appel immobilier et retourne du JSON.

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
  "rdv_datetime_mention": "<moment mentionné pour le RDV ou null>",
  "anomalies": [
    {{"type": "<financement|document|prix|delai>", "description": "<desc>", "severite": "<haute|moyenne|basse>"}}
  ],
  "points_cles": ["<point 1>", "<point 2>"],
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
            logger.warning(f"Erreur analyse transcription : {e}")
            return f"Appel traité — durée {lead.score}/10.", lead.score, False, []

    def _auto_book_rdv(self, lead: Lead, summary: str) -> Optional[dict]:
        """
        Book automatiquement un RDV si détecté dans l'appel.
        Utilise book_appointment (OAuth ou Service Account) + envoie email de confirmation.
        """
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
                f"RDV booké — lead={lead.id} slot={slot['label']} "
                f"email_confirmation={'✓' if result.get('email_sent') else '✗'}"
            )
        return result

    # ─── DB helpers ──────────────────────────────────────────────────────────

    def _save_call_to_db(
        self, lead_id: str, call_id: str, direction: str, statut: str
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO calls
                   (id, lead_id, client_id, retell_call_id, direction, statut)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO NOTHING""",
                (call_id, lead_id, self.client_id, call_id, direction, statut),
                # retell_call_id réutilisé pour stocker call_sid Twilio
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
        """Historique des appels pour le dashboard."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM calls WHERE client_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (self.client_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]
