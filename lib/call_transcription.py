"""
Transcription d'appels via Whisper API (OpenAI).

Pipeline :
  1. Télécharger l'audio depuis Backblaze B2
  2. Appeler whisper-1 avec language="fr", response_format="verbose_json"
  3. Retourner le texte complet + segments timestampés
  4. Nettoyer le fichier temporaire

En l'absence de clé OpenAI, retourne un mock.

Usage :
    from lib.call_transcription import CallTranscription
    result = CallTranscription().transcribe("calls/2026/04/abc.mp3")
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Coût Whisper : ~0,006 USD / minute (whisper-1)
WHISPER_COST_PER_MINUTE = 0.006


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    source: str = "whisper"  # "whisper" | "mock"

    @classmethod
    def mock(cls, call_id: str = "") -> "TranscriptionResult":
        return cls(
            text=(
                "[MOCK] Bonjour, je cherche un appartement dans le 15e arrondissement, "
                "environ 70 mètres carrés, budget autour de 450 000 euros. "
                "On a notre apport, on aimerait conclure d'ici 3 mois."
            ),
            segments=[
                {"start": 0.0, "end": 5.0, "text": "[MOCK] Bonjour, je cherche un appartement"},
                {"start": 5.0, "end": 10.0, "text": "dans le 15e, 70m², 450k€"},
            ],
            duration_seconds=10.0,
            cost_usd=0.001,
            source="mock",
        )


class CallTranscription:
    """Wrapper Whisper avec mock automatique si clé OpenAI absente."""

    def __init__(self) -> None:
        from config.settings import get_settings
        self._settings = get_settings()
        self._mock = not self._settings.openai_available

    def transcribe(self, remote_key: str, call_id: str = "") -> TranscriptionResult:
        """
        Transcrit un fichier audio stocké sur B2.

        Args:
            remote_key: Clé B2 (ex: calls/2026/04/abc.mp3)
            call_id: Utilisé dans les logs de corrélation

        Returns:
            TranscriptionResult avec texte + segments
        """
        if self._mock:
            logger.info("[MOCK] CallTranscription.transcribe call_id=%s", call_id)
            return TranscriptionResult.mock(call_id)

        from lib.audio_storage import AudioStorage

        local_path = None
        try:
            # 1. Download from B2
            local_path = AudioStorage().download_audio(remote_key)
            logger.info("[Whisper] Début transcription call_id=%s path=%s", call_id, local_path)

            # 2. Call Whisper API
            import openai
            client = openai.OpenAI(api_key=self._settings.openai_api_key)

            with open(local_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="fr",
                    response_format="verbose_json",
                )

            # 3. Parse response
            text = response.text or ""
            segments = [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in (response.segments or [])
            ]
            duration = response.duration or 0.0
            cost = round((duration / 60.0) * WHISPER_COST_PER_MINUTE, 6)

            logger.info(
                "[Whisper] OK call_id=%s duration=%.1fs cost=$%.4f",
                call_id, duration, cost,
            )
            return TranscriptionResult(
                text=text,
                segments=segments,
                duration_seconds=duration,
                cost_usd=cost,
                source="whisper",
            )

        except Exception as exc:
            logger.error("[Whisper] Erreur call_id=%s: %s", call_id, exc)
            raise
        finally:
            # 4. Cleanup temp file
            if local_path and Path(local_path).exists():
                try:
                    os.unlink(local_path)
                except OSError:
                    pass
