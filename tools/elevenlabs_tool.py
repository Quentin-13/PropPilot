"""
ElevenLabs TTS — Voix française naturelle.
Mock automatique si ELEVENLABS_API_KEY absent.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Voix françaises disponibles chez ElevenLabs (IDs officiels)
FRENCH_VOICES = {
    "sophie": {
        "id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Sophie",
        "description": "Voix féminine, chaleureuse et professionnelle",
        "gender": "female",
    },
    "thomas": {
        "id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Thomas",
        "description": "Voix masculine, posée et rassurante",
        "gender": "male",
    },
    "camille": {
        "id": "N2lVS1w4EtoT3dr4eOWO",
        "name": "Camille",
        "description": "Voix féminine, dynamique et enthousiaste",
        "gender": "female",
    },
}

# Répertoire de sortie audio (démo)
AUDIO_OUTPUT_DIR = Path("./data/audio")


class ElevenLabsTool:
    """
    Wrapper ElevenLabs TTS avec mock automatique.
    Génère des fichiers audio MP3 pour les appels voix.
    """

    DEFAULT_MODEL = "eleven_multilingual_v2"  # Meilleur pour le français

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.elevenlabs_available
        self._client = None
        if self.mock_mode:
            logger.info("[ElevenLabs] Mode mock activé")

    def _get_client(self):
        if self._client is None and not self.mock_mode:
            from elevenlabs.client import ElevenLabs
            self._client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
        return self._client

    def text_to_speech(
        self,
        text: str,
        voice_name: str = "sophie",
        output_path: Optional[str] = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> dict:
        """
        Convertit du texte en audio MP3.

        Args:
            text: Texte à synthétiser
            voice_name: Nom de la voix (sophie, thomas, camille)
            output_path: Chemin de sortie fichier (auto-généré si absent)
            stability: Stabilité de la voix (0.0-1.0)
            similarity_boost: Ressemblance à la voix originale (0.0-1.0)

        Returns:
            {"success": bool, "audio_path": str, "duration_s": float, "mock": bool}
        """
        voice_config = FRENCH_VOICES.get(voice_name, FRENCH_VOICES["sophie"])

        if not output_path:
            AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            import uuid
            output_path = str(AUDIO_OUTPUT_DIR / f"tts_{uuid.uuid4().hex[:8]}.mp3")

        if self.mock_mode:
            # Créer un fichier audio vide pour la démo
            Path(output_path).touch()
            char_count = len(text)
            estimated_duration = char_count / 15.0  # ~15 chars/seconde en français
            logger.info(f"[MOCK TTS] Voice: {voice_config['name']} | Chars: {char_count} | Text: {text[:60]}...")
            return {
                "success": True,
                "audio_path": output_path,
                "duration_s": round(estimated_duration, 1),
                "voice": voice_config["name"],
                "mock": True,
                "text_preview": text[:100],
            }

        try:
            client = self._get_client()
            audio_generator = client.generate(
                text=text,
                voice=voice_config["id"],
                model=self.DEFAULT_MODEL,
                voice_settings={
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
            )
            # Écriture fichier
            with open(output_path, "wb") as f:
                for chunk in audio_generator:
                    f.write(chunk)

            file_size = os.path.getsize(output_path)
            # Estimation durée : ~128kbps MP3 → 16 bytes/ms
            duration_s = file_size / (128 * 1024 / 8)

            logger.info(f"Audio généré : {output_path} ({file_size / 1024:.0f}KB)")
            return {
                "success": True,
                "audio_path": output_path,
                "duration_s": round(duration_s, 1),
                "voice": voice_config["name"],
                "mock": False,
            }

        except Exception as e:
            logger.error(f"Erreur ElevenLabs TTS : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def get_available_voices(self) -> list[dict]:
        """Liste les voix disponibles (configurées + API ElevenLabs)."""
        if self.mock_mode:
            return list(FRENCH_VOICES.values())

        try:
            client = self._get_client()
            voices_response = client.voices.get_all()
            return [
                {
                    "id": v.voice_id,
                    "name": v.name,
                    "description": v.description or "",
                    "gender": "unknown",
                }
                for v in voices_response.voices
            ]
        except Exception as e:
            logger.error(f"Erreur liste voix : {e}")
            return list(FRENCH_VOICES.values())

    def synthesize_call_script(
        self,
        script_parts: list[dict],
        voice_name: str = "sophie",
        output_dir: Optional[str] = None,
    ) -> list[dict]:
        """
        Synthétise un script d'appel en plusieurs parties audio.

        Args:
            script_parts: [{"text": str, "pause_after_s": float}, ...]
            voice_name: Voix à utiliser
            output_dir: Dossier de sortie

        Returns: list[{"text": str, "audio_path": str, "duration_s": float}]
        """
        out_dir = Path(output_dir or AUDIO_OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for i, part in enumerate(script_parts):
            import uuid
            path = str(out_dir / f"script_{i:02d}_{uuid.uuid4().hex[:6]}.mp3")
            result = self.text_to_speech(
                text=part["text"],
                voice_name=voice_name,
                output_path=path,
            )
            results.append({
                "text": part["text"],
                "audio_path": result.get("audio_path", ""),
                "duration_s": result.get("duration_s", 0),
                "pause_after_s": part.get("pause_after_s", 0.5),
                "success": result.get("success", False),
            })

        return results
