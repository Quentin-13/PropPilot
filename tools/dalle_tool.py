"""
DALL-E 3 — Génération images staging virtuel.
Mock automatique si OPENAI_API_KEY absent.
"""
from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path
from typing import Literal, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

IMAGE_OUTPUT_DIR = Path("./data/images")

# Styles d'intérieur français 2026
STAGING_STYLES = {
    "haussmannien_moderne": {
        "label": "Haussmannien Moderne",
        "description": "Parquet point de Hongrie, moulures conservées, mobilier contemporain épuré, palette beige-gris-blanc",
        "suffix": "Parisian Haussmann apartment interior, original moldings preserved, oak herringbone parquet, contemporary minimalist furniture in beige and warm grey, high ceilings, French windows, natural light, architectural photography, 8k",
    },
    "scandinave_epure": {
        "label": "Scandinave Épuré",
        "description": "Bois clair, textiles naturels, plantes, luminosité maximale, palette blanc-bois-vert sauge",
        "suffix": "Scandinavian minimalist French apartment interior, light birch wood, white walls, natural linen textiles, indoor plants, sage green accents, clean lines, hygge atmosphere, professional interior photography, 8k",
    },
    "contemporain": {
        "label": "Contemporain",
        "description": "Lignes épurées, matériaux mixtes, couleurs neutres avec accent, design actuel",
        "suffix": "Modern contemporary French apartment interior 2026, clean architectural lines, mixed materials marble and steel, neutral palette with warm accent colors, designer furniture, ambient lighting, professional real estate photography, 8k",
    },
    "provencal_renove": {
        "label": "Provençal Rénové",
        "description": "Pierre apparente, poutres bois, couleurs chaudes, esprit Provence contemporain",
        "suffix": "Renovated Provençal French home interior, exposed stone walls, wooden beams, warm terracotta and lavender palette, contemporary Provence furniture, Mediterranean light, professional interior design photography, 8k",
    },
}


class DalleTool:
    """
    Wrapper DALL-E 3 pour génération images staging et annonces.
    Mock automatique avec placeholder images.
    """

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.openai_available
        self._client = None
        if self.mock_mode:
            logger.info("[DALL-E] Mode mock activé")
        IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def _get_client(self):
        if self._client is None and not self.mock_mode:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def generate_staging_image(
        self,
        property_description: str,
        style: str = "contemporain",
        size: Literal["1024x1024", "1792x1024", "1024x1792"] = "1792x1024",
        quality: Literal["standard", "hd"] = "standard",
        source_image_base64: Optional[str] = None,
    ) -> dict:
        """
        Génère une image de staging virtuel pour un bien immobilier.

        Args:
            property_description: Description du bien (type, surface, pièces)
            style: Style de décoration (voir STAGING_STYLES)
            size: Taille de l'image
            quality: Qualité DALL-E ("standard" ou "hd")
            source_image_base64: Image source en base64 (optionnel)

        Returns:
            {"success": bool, "image_url": str, "image_path": str, "prompt": str, "mock": bool}
        """
        style_config = STAGING_STYLES.get(style, STAGING_STYLES["contemporain"])
        style_label = style_config["label"]

        prompt = (
            f"{property_description}. "
            f"Interior design style: {style_config['suffix']}. "
            f"No people, no text, no watermarks. "
            f"Photorealistic, wide angle lens, professional real estate photography."
        )

        if self.mock_mode:
            image_path = str(IMAGE_OUTPUT_DIR / f"staging_mock_{uuid.uuid4().hex[:8]}.png")
            Path(image_path).touch()
            logger.info(f"[MOCK DALL-E] Style: {style_label} | Prompt: {prompt[:80]}...")
            return {
                "success": True,
                "image_url": "",
                "image_path": image_path,
                "prompt": prompt,
                "style": style_label,
                "size": size,
                "mock": True,
                "mock_description": f"Image de staging {style_label} — {property_description[:60]}",
            }

        try:
            from memory.cost_logger import log_api_action
            client = self._get_client()

            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                response_format="url",
            )

            image_url = response.data[0].url
            revised_prompt = getattr(response.data[0], "revised_prompt", prompt)

            # Téléchargement de l'image
            image_path = str(IMAGE_OUTPUT_DIR / f"staging_{uuid.uuid4().hex[:8]}.png")
            import httpx
            img_response = httpx.get(image_url, timeout=30)
            with open(image_path, "wb") as f:
                f.write(img_response.content)

            # Coût DALL-E 3
            cost = 0.038 if size == "1024x1024" else 0.076
            log_api_action(
                client_id=self.settings.agency_client_id,
                action_type="image",
                provider="openai",
                model="dall-e-3",
                cost_euros=cost,
            )

            logger.info(f"Image staging générée : {image_path}")
            return {
                "success": True,
                "image_url": image_url,
                "image_path": image_path,
                "prompt": revised_prompt,
                "style": style_label,
                "size": size,
                "mock": False,
            }

        except Exception as e:
            logger.error(f"Erreur DALL-E génération : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def generate_multiple_stagings(
        self,
        property_description: str,
        styles: Optional[list[str]] = None,
        size: str = "1792x1024",
    ) -> list[dict]:
        """
        Génère plusieurs variantes de staging pour un bien.

        Args:
            property_description: Description du bien
            styles: Liste de styles (défaut : tous les 4)
            size: Taille des images

        Returns: List de résultats par style
        """
        from memory.usage_tracker import check_and_consume

        styles = styles or list(STAGING_STYLES.keys())
        results = []

        for style in styles:
            # Vérification quota avant chaque image
            usage_check = check_and_consume(
                self.settings.agency_client_id, "image", tier=self.settings.agency_tier
            )
            if not usage_check["allowed"]:
                results.append({
                    "style": style,
                    "success": False,
                    "reason": "limit_reached",
                    "message": usage_check["message"],
                })
                continue

            result = self.generate_staging_image(
                property_description=property_description,
                style=style,
                size=size,
            )
            result["style_key"] = style
            results.append(result)

        return results

    def generate_from_prompt(
        self,
        prompt: str,
        size: Literal["1024x1024", "1792x1024", "1024x1792"] = "1024x1024",
        quality: Literal["standard", "hd"] = "standard",
    ) -> dict:
        """Génère une image depuis un prompt DALL-E brut (pour annonces)."""
        if self.mock_mode:
            image_path = str(IMAGE_OUTPUT_DIR / f"listing_mock_{uuid.uuid4().hex[:8]}.png")
            Path(image_path).touch()
            logger.info(f"[MOCK DALL-E] Prompt image annonce : {prompt[:80]}...")
            return {
                "success": True,
                "image_url": "",
                "image_path": image_path,
                "prompt": prompt,
                "mock": True,
            }

        try:
            from memory.cost_logger import log_api_action
            client = self._get_client()
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )
            image_url = response.data[0].url
            image_path = str(IMAGE_OUTPUT_DIR / f"listing_{uuid.uuid4().hex[:8]}.png")

            import httpx
            img_response = httpx.get(image_url, timeout=30)
            with open(image_path, "wb") as f:
                f.write(img_response.content)

            cost = 0.038 if size == "1024x1024" else 0.076
            log_api_action(
                client_id=self.settings.agency_client_id,
                action_type="image",
                provider="openai",
                model="dall-e-3",
                cost_euros=cost,
            )

            return {"success": True, "image_url": image_url, "image_path": image_path, "mock": False}

        except Exception as e:
            logger.error(f"Erreur DALL-E prompt : {e}")
            return {"success": False, "error": str(e), "mock": False}

    @staticmethod
    def get_available_styles() -> dict:
        """Retourne les styles disponibles avec labels et descriptions."""
        return {k: {"label": v["label"], "description": v["description"]} for k, v in STAGING_STYLES.items()}
