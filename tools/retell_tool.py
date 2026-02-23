"""
RetellTool — Orchestration appels voix IA via Retell AI.
Mock automatique si RETELL_API_KEY absent.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class RetellTool:
    """
    Wrapper Retell AI SDK.
    Gère création d'appels, récupération transcriptions, webhooks.
    """

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.retell_available
        self._client = None
        if self.mock_mode:
            logger.info("[Retell] Mode mock activé")

    def _get_client(self):
        if self._client is None and not self.mock_mode:
            from retell import Retell
            self._client = Retell(api_key=self.settings.retell_api_key)
        return self._client

    def create_outbound_call(
        self,
        to_phone: str,
        from_phone: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        retell_llm_dynamic_variables: Optional[dict] = None,
    ) -> dict:
        """
        Lance un appel sortant via Retell AI.

        Args:
            to_phone: Numéro à appeler (E.164)
            from_phone: Numéro appelant (TWILIO_PHONE_NUMBER)
            agent_id: ID agent Retell configuré
            metadata: Données arbitraires attachées à l'appel
            retell_llm_dynamic_variables: Variables injectées dans le prompt de l'agent

        Returns:
            {"success": bool, "call_id": str, "status": str, "mock": bool}
        """
        from_num = from_phone or self.settings.twilio_phone_number or "+33100000001"
        agent = agent_id or self.settings.retell_agent_id or "mock_agent"

        if self.mock_mode:
            import uuid
            call_id = f"mock_call_{uuid.uuid4().hex[:12]}"
            logger.info(f"[MOCK Retell] Appel sortant → {to_phone} | Agent: {agent}")
            return {
                "success": True,
                "call_id": call_id,
                "status": "registered",
                "to_phone": to_phone,
                "from_phone": from_num,
                "mock": True,
            }

        try:
            client = self._get_client()
            call = client.call.create_phone_call(
                from_number=from_num,
                to_number=to_phone,
                agent_id=agent,
                metadata=metadata or {},
                retell_llm_dynamic_variables=retell_llm_dynamic_variables or {},
            )
            return {
                "success": True,
                "call_id": call.call_id,
                "status": call.call_status,
                "to_phone": to_phone,
                "from_phone": from_num,
                "mock": False,
            }
        except Exception as e:
            logger.error(f"Erreur Retell outbound call : {e}")
            return {"success": False, "call_id": "", "error": str(e), "mock": False}

    def get_call(self, call_id: str) -> dict:
        """
        Récupère les détails d'un appel (statut, transcription, durée).

        Returns:
            {
                "call_id": str,
                "status": str,             # registered | ongoing | ended | error
                "duration_s": int,
                "transcript": str,         # Texte brut de la conversation
                "transcript_segments": list,
                "recording_url": str,
                "call_analysis": dict,     # Résumé IA + sentiment
                "mock": bool,
            }
        """
        if self.mock_mode or call_id.startswith("mock_"):
            return self._mock_call_data(call_id)

        try:
            client = self._get_client()
            call = client.call.retrieve(call_id)

            transcript_text = ""
            segments = []
            if hasattr(call, "transcript") and call.transcript:
                transcript_text = call.transcript
            if hasattr(call, "transcript_object") and call.transcript_object:
                segments = [
                    {
                        "role": seg.role,
                        "content": seg.content,
                        "words": getattr(seg, "words", []),
                    }
                    for seg in call.transcript_object
                ]

            analysis = {}
            if hasattr(call, "call_analysis") and call.call_analysis:
                analysis = {
                    "call_summary": getattr(call.call_analysis, "call_summary", ""),
                    "user_sentiment": getattr(call.call_analysis, "user_sentiment", ""),
                    "agent_task_completion_rating": getattr(call.call_analysis, "agent_task_completion_rating", ""),
                    "custom_analysis_data": getattr(call.call_analysis, "custom_analysis_data", {}),
                }

            return {
                "call_id": call.call_id,
                "status": call.call_status,
                "duration_s": int(getattr(call, "duration_ms", 0) / 1000),
                "transcript": transcript_text,
                "transcript_segments": segments,
                "recording_url": getattr(call, "recording_url", ""),
                "call_analysis": analysis,
                "mock": False,
            }
        except Exception as e:
            logger.error(f"Erreur Retell get_call : {e}")
            return {"call_id": call_id, "status": "error", "error": str(e), "mock": False}

    def list_calls(self, limit: int = 50, filter_by_agent: bool = True) -> list[dict]:
        """Liste les appels récents."""
        if self.mock_mode:
            return self._mock_calls_list()

        try:
            client = self._get_client()
            params = {"limit": limit}
            if filter_by_agent and self.settings.retell_agent_id:
                params["filter_criteria"] = [{"agent_id": [self.settings.retell_agent_id]}]

            calls = client.call.list(**params)
            return [
                {
                    "call_id": c.call_id,
                    "status": c.call_status,
                    "duration_s": int(getattr(c, "duration_ms", 0) / 1000),
                    "to_phone": getattr(c, "to_number", ""),
                    "created_at": str(getattr(c, "start_timestamp", "")),
                    "mock": False,
                }
                for c in calls
            ]
        except Exception as e:
            logger.error(f"Erreur Retell list_calls : {e}")
            return []

    def parse_webhook_event(self, payload: dict) -> dict:
        """
        Parse un événement webhook Retell entrant.

        Retell envoie : call_started, call_ended, call_analyzed

        Returns:
            {"event_type": str, "call_id": str, "data": dict}
        """
        event_type = payload.get("event", "")
        call_data = payload.get("data", {})
        call_id = call_data.get("call_id", "")

        if event_type == "call_ended":
            return {
                "event_type": "call_ended",
                "call_id": call_id,
                "data": {
                    "duration_s": int(call_data.get("duration_ms", 0) / 1000),
                    "transcript": call_data.get("transcript", ""),
                    "recording_url": call_data.get("recording_url", ""),
                },
            }
        elif event_type == "call_analyzed":
            analysis = call_data.get("call_analysis", {})
            return {
                "event_type": "call_analyzed",
                "call_id": call_id,
                "data": {
                    "summary": analysis.get("call_summary", ""),
                    "sentiment": analysis.get("user_sentiment", ""),
                    "task_completion": analysis.get("agent_task_completion_rating", ""),
                    "custom": analysis.get("custom_analysis_data", {}),
                },
            }
        else:
            return {"event_type": event_type, "call_id": call_id, "data": call_data}

    # ─── Mocks ───────────────────────────────────────────────────────────────

    def _mock_call_data(self, call_id: str) -> dict:
        """Données d'appel mock réalistes."""
        mock_transcripts = [
            """Agent: Bonjour Mathieu, c'est Sophie de PropPilot. Vous m'avez contacté concernant votre projet d'achat à Lyon, j'ai quelques informations à vous partager. Je ne vous dérange pas ?
Contact: Non, pas du tout, je vous en prie.
Agent: Parfait ! Votre dossier est excellent — accord bancaire en place, apport solide, délai clair. J'ai justement 3 biens qui correspondent parfaitement à vos critères dans le 6e. Seriez-vous disponible pour des visites mardi ou jeudi ?
Contact: Plutôt jeudi dans l'après-midi.
Agent: Noté ! Je vous confirme jeudi à 14h30. Je vous envoie les fiches des 3 biens par SMS d'ici une heure. À jeudi !
Contact: Parfait, merci beaucoup.""",

            """Agent: Bonjour, c'est Sophie de PropPilot. Vous avez demandé une estimation pour votre appartement à Bordeaux Chartrons ?
Contact: Oui effectivement, j'envisage de vendre.
Agent: Très bien. Pour affiner mon estimation, quelques questions : vous avez refait les travaux récemment ?
Contact: On a refait la cuisine en 2022 et les salles de bains en 2023.
Agent: Excellent, ça va valoriser significativement le bien. Avec le marché actuel à Chartrons, et votre DPE B, je situe la fourchette entre 310 000€ et 330 000€. Souhaitez-vous qu'on se rencontre pour une estimation formelle ?
Contact: Oui, pourquoi pas la semaine prochaine.
Agent: Je vous propose lundi à 10h ou mercredi à 14h ?""",
        ]

        import random
        transcript = random.choice(mock_transcripts)

        return {
            "call_id": call_id,
            "status": "ended",
            "duration_s": random.randint(120, 420),
            "transcript": transcript,
            "transcript_segments": self._parse_mock_transcript_segments(transcript),
            "recording_url": "",
            "call_analysis": {
                "call_summary": "Appel de qualification réussi. Contact réceptif, projet clair. RDV pris.",
                "user_sentiment": "Positive",
                "agent_task_completion_rating": "Complete",
                "custom": {"rdv_pris": True, "score_post_appel": 8},
            },
            "mock": True,
        }

    def _parse_mock_transcript_segments(self, transcript: str) -> list[dict]:
        segments = []
        for line in transcript.strip().split("\n"):
            if line.startswith("Agent:"):
                segments.append({"role": "agent", "content": line[6:].strip()})
            elif line.startswith("Contact:"):
                segments.append({"role": "user", "content": line[8:].strip()})
        return segments

    def _mock_calls_list(self) -> list[dict]:
        from datetime import timedelta
        import uuid
        import random

        calls = []
        durations = [185, 240, 380, 120, 290, 420, 95, 310]
        statuses = ["ended"] * 7 + ["error"]
        phones = ["+33612345601", "+33612345602", "+33612345605", "+33612345619"]

        for i in range(min(8, len(durations))):
            days_ago = i * 2 + random.randint(0, 1)
            calls.append({
                "call_id": f"mock_call_{uuid.uuid4().hex[:12]}",
                "status": statuses[i],
                "duration_s": durations[i],
                "to_phone": phones[i % len(phones)],
                "created_at": (datetime.now() - timedelta(days=days_ago)).isoformat(),
                "mock": True,
            })
        return calls
