"""
SophieVoice — Agent vocal de qualification immobilière.
Pipeline : Twilio STT → Claude → ElevenLabs TTS → Twilio Play
"""
from __future__ import annotations

import logging
import uuid

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

SOPHIE_SYSTEM_PROMPT = """
Tu es Sophie, l'assistante vocale d'un conseiller
immobilier français. Tu parles au téléphone avec
un prospect qui a appelé concernant un bien immobilier.

Ton rôle est de qualifier le prospect en posant
les bonnes questions, une par une, de façon naturelle
et conversationnelle. Tu ne poses JAMAIS plusieurs
questions à la suite.

Questions de qualification à poser dans cet ordre :
1. C'est pour un projet d'achat ou de location ?
2. C'est pour une résidence principale, secondaire
   ou un investissement ?
3. Vous avez un délai en tête ?
4. Vous avez déjà eu un retour de votre banque
   ou d'un courtier sur votre capacité d'emprunt ?
5. Vous avez un apport ?
6. Vous êtes actuellement locataire ou propriétaire ?
7. Vous avez visité d'autres biens récemment ?

Règles importantes :
- Réponds TOUJOURS en français
- Sois naturelle, chaleureuse, professionnelle
- Phrases courtes, adaptées à l'oral
- Maximum 2-3 phrases par réponse
- Quand tu as collecté les infos essentielles
  (projet, financement, délai), dis :
  "Parfait, je transmets votre dossier à votre conseiller.
   Il vous recontacte très rapidement. Bonne journée !"
- Ne mentionne JAMAIS que tu es une IA
- Tu es "Sophie, l'assistante de votre conseiller"
"""


class SophieVoice:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate_response(
        self,
        conversation_history: list[dict],
        user_message: str,
    ) -> str:
        """Envoie la conversation à Claude et retourne la réponse de Sophie."""
        if not self.settings.anthropic_available:
            return (
                "Merci pour votre message. "
                "Votre conseiller vous recontacte très rapidement. "
                "Bonne journée !"
            )

        import anthropic

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

        messages = conversation_history.copy()
        messages.append({"role": "user", "content": user_message})

        response = client.messages.create(
            model=self.settings.claude_model,
            max_tokens=200,
            system=SOPHIE_SYSTEM_PROMPT,
            messages=messages,
        )

        return response.content[0].text

    async def text_to_speech(self, text: str) -> str | None:
        """
        Convertit le texte en audio via ElevenLabs Flash (eleven_flash_v2_5).
        Retourne l'URL publique Railway pour que Twilio puisse jouer l'audio.
        """
        if not self.settings.elevenlabs_available:
            logger.warning("[Sophie] ElevenLabs non configuré — fallback Polly")
            return None

        headers = {
            "xi-api-key": self.settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech"
                    f"/{self.settings.elevenlabs_voice_id}/stream",
                    headers=headers,
                    json=payload,
                )

                if resp.status_code != 200:
                    logger.error(
                        f"[ElevenLabs] Erreur {resp.status_code} : {resp.text[:200]}"
                    )
                    return None

                audio_id = uuid.uuid4().hex[:12]
                audio_path = f"/tmp/sophie_{audio_id}.mp3"
                with open(audio_path, "wb") as f:
                    f.write(resp.content)

                base_url = self.settings.base_url.rstrip("/")
                return f"{base_url}/audio/{audio_id}"

        except Exception as e:
            logger.error(f"[ElevenLabs] Exception : {e}")
            return None
