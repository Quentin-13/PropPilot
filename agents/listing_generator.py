"""
ListingGeneratorAgent — Descriptions SEO + prompts image + pré-remplissage compromis.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.prompts import LISTING_GENERATION_PROMPT, get_listing_system
from config.settings import get_settings
from memory.database import get_connection
from memory.usage_tracker import check_and_consume

logger = logging.getLogger(__name__)


class ListingGeneratorAgent:
    """
    Génère des annonces immobilières SEO complètes via Claude.
    Conforme obligations légales (loi ALUR, loi Carrez, DPE obligatoire).
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

    def generate(
        self,
        type_bien: str,
        adresse: str,
        surface: float,
        nb_pieces: int,
        nb_chambres: int = 0,
        dpe_energie: str = "D",
        dpe_ges: str = "D",
        prix: float = 0,
        etage: str = "RDC",
        exposition: str = "sud",
        parking: bool = False,
        cave: bool = False,
        exterieur: str = "",
        etat: str = "bon",
        notes: str = "",
        lead_id: str = "",
        generate_dalle_images: bool = False,
    ) -> dict:
        """
        Génère une annonce immobilière complète.

        Args:
            type_bien: Appartement, Maison, Studio, Loft...
            adresse: Adresse complète du bien
            surface: Surface habitable en m²
            nb_pieces: Nombre de pièces
            nb_chambres: Nombre de chambres
            dpe_energie: Classe DPE énergie (A à G)
            dpe_ges: Classe GES (A à G)
            prix: Prix de vente en euros
            etage: Étage ou "RDC"
            exposition: Orientation principale
            parking: Parking inclus
            cave: Cave/cellier inclus
            exterieur: Description extérieur (terrasse, balcon, jardin)
            etat: État général (excellent, bon, à rénover)
            notes: Notes complémentaires de l'agent
            lead_id: ID du lead associé (optionnel)
            generate_dalle_images: Générer les images via DALL-E

        Returns:
            {
                "success": bool,
                "listing_id": str,
                "titre": str,
                "description_longue": str,
                "description_courte": str,
                "points_forts": list,
                "mentions_legales": str,
                "mots_cles_seo": list,
                "prompts_dalle": list,
                "images": list,
                "compromis_prefill": dict,
                "mock": bool,
            }
        """
        # Vérification quota
        usage_check = check_and_consume(self.client_id, "listing", tier=self.tier)
        if not usage_check["allowed"]:
            return {"success": False, "message": usage_check["message"], "limit_reached": True}

        # Génération annonce
        listing_data = self._generate_with_llm(
            type_bien=type_bien,
            adresse=adresse,
            surface=surface,
            nb_pieces=nb_pieces,
            nb_chambres=nb_chambres,
            dpe_energie=dpe_energie,
            dpe_ges=dpe_ges,
            prix=prix,
            etage=etage,
            exposition=exposition,
            parking=parking,
            cave=cave,
            exterieur=exterieur,
            etat=etat,
            notes=notes,
        )

        listing_id = str(uuid.uuid4())

        # Génération images DALL-E (optionnel)
        images = []
        if generate_dalle_images and listing_data.get("prompts_dalle"):
            from tools.dalle_tool import DalleTool
            dalle = DalleTool()
            for prompt in listing_data.get("prompts_dalle", [])[:3]:
                usage_img = check_and_consume(self.client_id, "image", tier=self.tier)
                if usage_img["allowed"]:
                    img = dalle.generate_from_prompt(prompt)
                    if img.get("success"):
                        images.append(img.get("image_path", ""))

        # Pré-remplissage compromis
        compromis = self._prefill_compromis(
            listing_id=listing_id,
            type_bien=type_bien,
            adresse=adresse,
            surface=surface,
            prix=prix,
            dpe_energie=dpe_energie,
        )

        # Persistance
        self._save_listing(
            listing_id=listing_id,
            lead_id=lead_id,
            type_bien=type_bien,
            adresse=adresse,
            surface=surface,
            nb_pieces=nb_pieces,
            prix=prix,
            dpe=dpe_energie,
            images=images,
            data=listing_data,
        )

        return {
            "success": True,
            "listing_id": listing_id,
            **listing_data,
            "images": images,
            "compromis_prefill": compromis,
            "mock": not self.settings.anthropic_available,
        }

    def _generate_with_llm(self, **kwargs) -> dict:
        """Génère l'annonce via Claude."""
        client = self._get_anthropic()

        parking_str = "Oui" if kwargs["parking"] else "Non"
        cave_str = "Oui" if kwargs["cave"] else "Non"
        exterieur_str = kwargs["exterieur"] or "Aucun"
        prix_str = f"{int(kwargs['prix']):,}€".replace(",", " ") if kwargs["prix"] else "À définir"

        prompt = LISTING_GENERATION_PROMPT.format(
            type_bien=kwargs["type_bien"],
            adresse=kwargs["adresse"],
            surface=kwargs["surface"],
            nb_pieces=kwargs["nb_pieces"],
            nb_chambres=kwargs["nb_chambres"],
            dpe_energie=kwargs["dpe_energie"],
            dpe_ges=kwargs["dpe_ges"],
            prix=prix_str,
            etage=kwargs["etage"],
            exposition=kwargs["exposition"],
            parking=parking_str,
            cave=cave_str,
            exterieur=exterieur_str,
            etat=kwargs["etat"],
            notes=kwargs["notes"] or "Aucune note complémentaire",
        )

        if client:
            try:
                from memory.cost_logger import log_api_action
                system = get_listing_system()
                response = client.messages.create(
                    model=self.settings.claude_model,
                    max_tokens=1200,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()

                log_api_action(
                    client_id=self.client_id,
                    action_type="listing",
                    provider="anthropic",
                    model=self.settings.claude_model,
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                )

                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                return json.loads(text)

            except Exception as e:
                logger.warning(f"Erreur LLM listing : {e}")

        return self._mock_listing(kwargs)

    def _mock_listing(self, kwargs: dict) -> dict:
        """Annonce mock réaliste."""
        adresse = kwargs["adresse"]
        surface = kwargs["surface"]
        nb_pieces = kwargs["nb_pieces"]
        prix = kwargs.get("prix", 0)
        dpe = kwargs["dpe_energie"]
        type_bien = kwargs["type_bien"]

        ville = adresse.split(",")[-1].strip() if "," in adresse else adresse.split()[-1]
        prix_str = f"{int(prix):,}€".replace(",", " ") if prix else ""

        return {
            "titre": f"[MOCK] {ville} — {type_bien} {nb_pieces}P {surface}m² {' — ' + prix_str if prix_str else ''}",
            "description_longue": (
                f"[MOCK] Superbe {type_bien.lower()} de {surface} m² idéalement situé à {adresse}. "
                f"Ce bien de {nb_pieces} pièces bénéficie d'une belle luminosité et d'une distribution optimale. "
                f"DPE classe {dpe}. Parfait état général. "
                f"Secteur recherché avec toutes commodités à proximité : commerces, transports, écoles. "
                f"{'Parking inclus. ' if kwargs.get('parking') else ''}"
                f"{'Cave/cellier. ' if kwargs.get('cave') else ''}"
                f"Bien à ne pas manquer — visite sur rendez-vous."
            ),
            "description_courte": (
                f"[MOCK] {ville} — {type_bien} {nb_pieces}P {surface}m², DPE {dpe}. "
                f"{'Parking. ' if kwargs.get('parking') else ''}{'Cave. ' if kwargs.get('cave') else ''}"
                f"{prix_str + ' FAI.' if prix_str else ''}"
            ),
            "points_forts": [
                f"Surface {surface}m² bien agencée",
                f"DPE classe {dpe} — charges maîtrisées",
                f"Secteur {ville} prisé — commerces à pied",
                "Visite sur rendez-vous",
            ],
            "mentions_legales": (
                f"Surface : {surface} m² (loi Carrez). DPE : classe {dpe}. "
                f"Prix : {prix_str} FAI (dont honoraires 3,9% TTC)."
            ),
            "mots_cles_seo": [
                f"{type_bien.lower()} {ville}",
                f"{nb_pieces} pièces {ville}",
                f"acheter {ville}",
                f"DPE {dpe} {ville}",
                "immobilier investissement",
            ],
            "prompts_dalle": [
                f"Beautiful {type_bien} interior in {ville}, France, {surface}m², bright living room, natural light, modern French decor, professional real estate photography 8k",
                f"French {type_bien.lower()} kitchen interior, {ville}, contemporary design, white and wood, professional photography",
                f"French apartment exterior in {ville}, Haussmann building, sunny day, architectural photography",
            ],
        }

    def _prefill_compromis(
        self,
        listing_id: str,
        type_bien: str,
        adresse: str,
        surface: float,
        prix: float,
        dpe_energie: str,
    ) -> dict:
        """
        Pré-remplissage compromis de vente (structure conforme loi Hoguet).
        Ne constitue pas un acte juridique — à faire valider par notaire.
        """
        return {
            "reference": f"COMP-{datetime.now().strftime('%Y%m')}-{listing_id[:6].upper()}",
            "date_redaction": datetime.now().strftime("%d/%m/%Y"),
            "type_acte": "Promesse synallagmatique de vente (compromis)",
            "bien": {
                "type": type_bien,
                "adresse": adresse,
                "surface_loi_carrez": f"{surface} m²",
                "dpe_classe_energie": dpe_energie,
                "mention_dpe": f"Classe énergie {dpe_energie} — fourni à l'acheteur avant signature",
            },
            "prix": {
                "net_vendeur": int(prix * 0.961),
                "honoraires_agence_ttc": int(prix * 0.039),
                "prix_fai": int(prix),
                "honoraires_pct": "3,9% TTC à charge acquéreur",
            },
            "conditions_suspensives": [
                "Obtention du financement bancaire dans un délai de 45 jours",
                "Absence de servitude non déclarée",
                "Conformité du dossier de diagnostics techniques (DDT)",
            ],
            "delai_retractation": "10 jours à compter de la signature (art. L271-1 CCH)",
            "depot_garantie": f"{int(prix * 0.10):,}€ (10% du prix de vente)".replace(",", " "),
            "delai_acte_authentique": "3 mois après signature du compromis",
            "mention_legale_hoguet": (
                "Le présent avant-contrat est établi conformément à la loi Hoguet n°70-9 du 2 janvier 1970. "
                "L'agent immobilier est titulaire d'une carte professionnelle délivrée par la Chambre de Commerce et d'Industrie. "
                "Ce document ne constitue pas un acte notarié et devra être réitéré devant notaire."
            ),
            "champs_a_completer": [
                "Identité complète vendeur(s) + acheteur(s)",
                "Date de naissance et lieu",
                "Régime matrimonial",
                "Désignation cadastrale (section + numéro de parcelle)",
                "Quote-part de copropriété (tantièmes)",
                "Charges copropriété annuelles",
                "Présence/absence de syndic professionnel",
                "Date de signature acte authentique définitive",
            ],
        }

    def _save_listing(
        self,
        listing_id: str,
        lead_id: str,
        type_bien: str,
        adresse: str,
        surface: float,
        nb_pieces: int,
        prix: float,
        dpe: str,
        images: list,
        data: dict,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO listings
                   (id, lead_id, client_id, type_bien, adresse, surface, nb_pieces, prix, dpe,
                    titre, description_longue, description_courte, points_forts,
                    mentions_legales, mots_cles_seo, images_urls)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    listing_id, lead_id, self.client_id, type_bien, adresse, surface, nb_pieces, prix, dpe,
                    data.get("titre", ""),
                    data.get("description_longue", ""),
                    data.get("description_courte", ""),
                    json.dumps(data.get("points_forts", []), ensure_ascii=False),
                    data.get("mentions_legales", ""),
                    json.dumps(data.get("mots_cles_seo", []), ensure_ascii=False),
                    json.dumps(images, ensure_ascii=False),
                ),
            )

    def translate_to_english(self, description: str) -> dict:
        """Traduit la description en anglais (portails internationaux)."""
        client = self._get_anthropic()
        if not client:
            return {"success": True, "translation": f"[MOCK EN] {description[:200]}...", "mock": True}

        try:
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=600,
                messages=[{
                    "role": "user",
                    "content": f"Translate this French real estate description to professional English. Keep all legal mentions translated accurately:\n\n{description}",
                }],
            )
            return {"success": True, "translation": response.content[0].text.strip(), "mock": False}
        except Exception as e:
            return {"success": False, "error": str(e)}
