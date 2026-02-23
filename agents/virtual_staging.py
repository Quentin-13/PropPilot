"""
VirtualStagingAgent — Staging virtuel photo bien → rendu meublé style français 2026.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from config.settings import get_settings
from memory.usage_tracker import check_and_consume
from tools.dalle_tool import STAGING_STYLES, DalleTool

logger = logging.getLogger(__name__)


class VirtualStagingAgent:
    """
    Génère des images de staging virtuel pour des biens vides ou non meublés.
    Style intérieur français tendance 2026 via DALL-E 3.
    """

    def __init__(self, client_id: str, tier: str = "Starter"):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()

    def stage_property(
        self,
        property_description: str,
        style: str = "contemporain",
        nb_images: int = 1,
        rooms: Optional[list[str]] = None,
        source_image_path: Optional[str] = None,
    ) -> dict:
        """
        Génère des images de staging virtuel.

        Args:
            property_description: Description du bien (type, surface, caractéristiques)
            style: Style de décoration (contemporain, haussmannien_moderne, scandinave_epure, provencal_renove)
            nb_images: Nombre d'images à générer (1-4)
            rooms: Pièces à stager (["sejour", "chambre", "cuisine"]) — défaut : séjour
            source_image_path: Photo originale du bien (optionnel, non utilisée dans DALL-E free)

        Returns:
            {
                "success": bool,
                "style": str,
                "images": [{"room": str, "image_path": str, "prompt": str}],
                "total_generated": int,
            }
        """
        if style not in STAGING_STYLES:
            style = "contemporain"

        rooms = rooms or ["sejour"]
        nb_images = min(nb_images, len(rooms), 4)

        dalle = DalleTool()
        style_config = STAGING_STYLES[style]
        results = []

        for room in rooms[:nb_images]:
            # Vérification quota
            usage_check = check_and_consume(self.client_id, "image", tier=self.tier)
            if not usage_check["allowed"]:
                results.append({
                    "room": room,
                    "success": False,
                    "reason": "limit_reached",
                    "message": usage_check["message"],
                })
                continue

            # Construction du prompt spécifique à la pièce
            room_prompt = self._build_room_prompt(
                room=room,
                property_description=property_description,
                style_config=style_config,
            )

            result = dalle.generate_staging_image(
                property_description=property_description,
                style=style,
                size="1792x1024",
            )

            results.append({
                "room": room,
                "room_label": self._room_label(room),
                "success": result.get("success", False),
                "image_path": result.get("image_path", ""),
                "image_url": result.get("image_url", ""),
                "prompt": room_prompt,
                "mock": result.get("mock", True),
            })

        successful = [r for r in results if r.get("success")]

        return {
            "success": len(successful) > 0,
            "style": style,
            "style_label": style_config["label"],
            "images": results,
            "total_generated": len(successful),
            "total_requested": nb_images,
        }

    def stage_all_styles(
        self,
        property_description: str,
        main_room: str = "sejour",
    ) -> dict:
        """
        Génère une image de staging pour chaque style disponible.
        Utile pour présenter des variantes au client.

        Returns:
            {"styles": {style_key: result_dict}}
        """
        results = {}
        for style_key in STAGING_STYLES.keys():
            result = self.stage_property(
                property_description=property_description,
                style=style_key,
                nb_images=1,
                rooms=[main_room],
            )
            results[style_key] = {
                "label": STAGING_STYLES[style_key]["label"],
                "image": result["images"][0] if result["images"] else None,
                "success": result["success"],
            }

        return {"styles": results, "total_successful": sum(1 for r in results.values() if r["success"])}

    def generate_architectural_render(
        self,
        type_bien: str,
        superficie: float,
        nb_pieces: int,
        style: str = "contemporain",
        ville: str = "",
    ) -> dict:
        """
        Génère un rendu architectural quand aucune photo n'est fournie.
        Basé uniquement sur la description du bien.
        """
        style_config = STAGING_STYLES.get(style, STAGING_STYLES["contemporain"])
        ville_context = f"in {ville}, France" if ville else "in France"

        prompt = (
            f"Photorealistic architectural rendering of a {type_bien} interior {ville_context}, "
            f"{superficie}m², {nb_pieces} rooms. "
            f"{style_config['suffix']}. "
            f"Wide angle, natural light, no people, professional interior photography 8k."
        )

        usage_check = check_and_consume(self.client_id, "image", tier=self.tier)
        if not usage_check["allowed"]:
            return {"success": False, "message": usage_check["message"]}

        dalle = DalleTool()
        result = dalle.generate_from_prompt(prompt=prompt, size="1792x1024")
        result["style_label"] = style_config["label"]
        result["prompt_used"] = prompt
        return result

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _build_room_prompt(self, room: str, property_description: str, style_config: dict) -> str:
        ROOM_CONTEXTS = {
            "sejour": "spacious living room with comfortable seating, dining area, natural light",
            "chambre": "elegant master bedroom with quality bed, wardrobe, soft lighting",
            "chambre_enfant": "children's bedroom, playful and cozy, quality furniture",
            "cuisine": "modern equipped kitchen with island or counter, quality appliances",
            "salle_bain": "contemporary bathroom, walk-in shower or bathtub, clean design",
            "bureau": "home office, ergonomic desk setup, bookshelves, good lighting",
            "exterieur": "outdoor terrace or garden, comfortable outdoor furniture, plants",
        }
        room_ctx = ROOM_CONTEXTS.get(room, "well-designed room")
        return (
            f"{property_description}. {room_ctx}. "
            f"{style_config['suffix']}. "
            f"No people, photorealistic, professional real estate photography 8k."
        )

    @staticmethod
    def _room_label(room: str) -> str:
        LABELS = {
            "sejour": "Séjour / Salon",
            "chambre": "Chambre principale",
            "chambre_enfant": "Chambre enfant",
            "cuisine": "Cuisine",
            "salle_bain": "Salle de bains",
            "bureau": "Bureau",
            "exterieur": "Extérieur / Terrasse",
        }
        return LABELS.get(room, room.capitalize())

    @staticmethod
    def get_available_styles() -> dict:
        return DalleTool.get_available_styles()

    @staticmethod
    def get_available_rooms() -> dict:
        return {
            "sejour": "Séjour / Salon",
            "chambre": "Chambre principale",
            "chambre_enfant": "Chambre enfant",
            "cuisine": "Cuisine",
            "salle_bain": "Salle de bains",
            "bureau": "Bureau",
            "exterieur": "Extérieur / Terrasse",
        }
