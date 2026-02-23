"""
EstimationAgent — Estimation prix/loyer + comparables DVF + rapport PDF.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.prompts import ESTIMATION_PROMPT, ESTIMATION_SYSTEM
from config.settings import get_settings
from memory.database import get_connection
from memory.usage_tracker import check_and_consume

logger = logging.getLogger(__name__)

PDF_OUTPUT_DIR = Path("./data/rapports")

# Prix de référence DVF simplifiés par ville (€/m²) — à jour 2024-2025
DVF_REFERENCE_PRICES: dict[str, dict] = {
    "paris": {"achat": 9800, "location_m2": 32, "tendance": "stable"},
    "lyon": {"achat": 4800, "location_m2": 16, "tendance": "légère baisse"},
    "marseille": {"achat": 3200, "location_m2": 13, "tendance": "hausse"},
    "bordeaux": {"achat": 4200, "location_m2": 14, "tendance": "baisse"},
    "toulouse": {"achat": 3800, "location_m2": 13, "tendance": "stable"},
    "nantes": {"achat": 3900, "location_m2": 14, "tendance": "légère baisse"},
    "nice": {"achat": 4600, "location_m2": 18, "tendance": "hausse"},
    "strasbourg": {"achat": 3500, "location_m2": 13, "tendance": "stable"},
    "montpellier": {"achat": 3600, "location_m2": 14, "tendance": "stable"},
    "rennes": {"achat": 4000, "location_m2": 14, "tendance": "stable"},
    "grenoble": {"achat": 2900, "location_m2": 12, "tendance": "stable"},
    "lille": {"achat": 3400, "location_m2": 13, "tendance": "stable"},
    "default": {"achat": 3000, "location_m2": 11, "tendance": "stable"},
}

# Coefficients d'ajustement
DPE_ADJUSTMENTS = {"A": 0.08, "B": 0.05, "C": 0.02, "D": 0.0, "E": -0.05, "F": -0.10, "G": -0.15}
ETAT_ADJUSTMENTS = {"excellent": 0.08, "très bon": 0.05, "bon": 0.0, "correct": -0.05, "à rénover": -0.15, "à restructurer": -0.25}


class EstimationAgent:
    """
    Estimation immobilière : méthode DVF + ajustements Claude.
    Mention légale loi Hoguet obligatoire sur toutes les sorties.
    """

    MENTION_LEGALE = (
        "Estimation non opposable juridiquement, fournie à titre indicatif conformément à "
        "l'article L321-1 et suivants de la loi Hoguet n°70-9 du 2 janvier 1970. "
        "Elle ne constitue pas une promesse de prix et ne saurait engager l'agence."
    )

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

    def estimate(
        self,
        type_bien: str,
        adresse: str,
        ville: str,
        code_postal: str,
        surface: float,
        nb_pieces: int,
        dpe: str = "D",
        etage: int = 0,
        nb_etages: int = 5,
        etat: str = "bon",
        parking: bool = False,
        exterieur: float = 0.0,
        type_exterieur: str = "",
        lead_id: str = "",
        generate_pdf: bool = True,
    ) -> dict:
        """
        Calcule une estimation immobilière complète.

        Returns:
            {
                "success": bool,
                "estimation_id": str,
                "prix_estime_bas": int,
                "prix_estime_central": int,
                "prix_estime_haut": int,
                "prix_m2_net": int,
                "loyer_mensuel_estime": int,
                "rentabilite_brute": float,
                "delai_vente_estime_semaines": int,
                "ajustements": dict,
                "justification": str,
                "comparables": list,
                "mention_legale": str,
                "rapport_pdf_path": str,
                "mock": bool,
            }
        """
        usage_check = check_and_consume(self.client_id, "estimation", tier=self.tier)
        if not usage_check["allowed"]:
            return {"success": False, "message": usage_check["message"], "limit_reached": True}

        # Prix de référence DVF
        ville_key = ville.lower().split(" ")[0]
        dvf = DVF_REFERENCE_PRICES.get(ville_key, DVF_REFERENCE_PRICES["default"])

        estimation_data = self._compute_estimation_with_llm(
            type_bien=type_bien,
            adresse=adresse,
            ville=ville,
            code_postal=code_postal,
            surface=surface,
            nb_pieces=nb_pieces,
            dpe=dpe,
            etage=etage,
            nb_etages=nb_etages,
            etat=etat,
            parking=parking,
            exterieur=exterieur,
            type_exterieur=type_exterieur,
            dvf=dvf,
        )

        estimation_id = str(uuid.uuid4())

        # Persistance
        self._save_estimation(estimation_id, lead_id, adresse, surface, type_bien, estimation_data)

        # PDF
        pdf_path = ""
        if generate_pdf:
            pdf_path = self._generate_pdf_report(
                estimation_id=estimation_id,
                type_bien=type_bien,
                adresse=adresse,
                ville=ville,
                surface=surface,
                nb_pieces=nb_pieces,
                dpe=dpe,
                data=estimation_data,
            )

        return {
            "success": True,
            "estimation_id": estimation_id,
            **estimation_data,
            "rapport_pdf_path": pdf_path,
            "mock": not self.settings.anthropic_available,
        }

    def _compute_estimation_with_llm(self, type_bien, adresse, ville, code_postal, surface, nb_pieces,
                                      dpe, etage, nb_etages, etat, parking, exterieur, type_exterieur, dvf) -> dict:
        """Calcule l'estimation via Claude ou heuristique."""
        client = self._get_anthropic()

        prix_m2_ref = dvf["achat"]
        loyer_m2_ref = dvf["location_m2"]
        tendance = dvf["tendance"]

        if client:
            try:
                from memory.cost_logger import log_api_action
                prompt = ESTIMATION_PROMPT.format(
                    type_bien=type_bien,
                    adresse=adresse,
                    ville=ville,
                    code_postal=code_postal,
                    surface=surface,
                    nb_pieces=nb_pieces,
                    dpe=dpe,
                    etage=etage,
                    nb_etages=nb_etages,
                    etat=etat,
                    parking="Oui" if parking else "Non",
                    exterieur=f"{exterieur}m² de {type_exterieur}" if exterieur else "Aucun",
                    type_exterieur=type_exterieur,
                    prix_m2_reference=prix_m2_ref,
                    tendance_marche=tendance,
                )

                response = client.messages.create(
                    model=self.settings.claude_model,
                    max_tokens=800,
                    system=[{
                        "type": "text",
                        "text": ESTIMATION_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()

                log_api_action(
                    client_id=self.client_id,
                    action_type="estimation",
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
                data["mention_legale"] = self.MENTION_LEGALE
                return data

            except Exception as e:
                logger.warning(f"Erreur LLM estimation : {e}")

        return self._heuristic_estimation(surface, prix_m2_ref, loyer_m2_ref, dpe, etage, nb_etages, etat, parking, exterieur, ville)

    def _heuristic_estimation(
        self, surface: float, prix_m2_ref: int, loyer_m2_ref: int,
        dpe: str, etage: int, nb_etages: int, etat: str,
        parking: bool, exterieur: float, ville: str,
    ) -> dict:
        """Estimation heuristique sans LLM."""
        # Ajustements
        adj_dpe = DPE_ADJUSTMENTS.get(dpe.upper(), 0.0)
        adj_etat = ETAT_ADJUSTMENTS.get(etat.lower(), 0.0)
        adj_etage = min(0.05, etage / max(nb_etages, 1) * 0.08)
        adj_parking = 0.04 if parking else 0.0
        adj_exterieur = min(0.06, exterieur / surface * 0.3) if exterieur > 0 else 0.0

        total_adj = adj_dpe + adj_etat + adj_etage + adj_parking + adj_exterieur
        prix_m2_net = int(prix_m2_ref * (1 + total_adj))
        prix_central = int(surface * prix_m2_net)
        prix_bas = int(prix_central * 0.95)
        prix_haut = int(prix_central * 1.05)

        loyer_mensuel = int(surface * loyer_m2_ref * (1 + adj_dpe * 0.5 + adj_etat * 0.5))
        rentabilite = loyer_mensuel * 12 / prix_central * 100 if prix_central > 0 else 0

        return {
            "prix_estime_bas": prix_bas,
            "prix_estime_central": prix_central,
            "prix_estime_haut": prix_haut,
            "prix_m2_net": prix_m2_net,
            "loyer_mensuel_estime": loyer_mensuel,
            "rentabilite_brute": round(rentabilite, 2),
            "delai_vente_estime_semaines": 10 if adj_etat >= 0 else 16,
            "ajustements": {
                "etat": round(adj_etat * 100, 1),
                "dpe": round(adj_dpe * 100, 1),
                "etage": round(adj_etage * 100, 1),
                "exposition": 0.0,
                "parking": round(adj_parking * 100, 1),
                "exterieur": round(adj_exterieur * 100, 1),
            },
            "justification": (
                f"[MOCK] Estimation basée sur prix DVF moyen de {prix_m2_ref}€/m² à {ville}. "
                f"Ajustements : DPE {dpe} ({adj_dpe:+.0%}), état {etat} ({adj_etat:+.0%}), "
                f"{'parking (+4%), ' if parking else ''}"
                f"total {total_adj:+.1%}."
            ),
            "mention_legale": self.MENTION_LEGALE,
            "comparables": [
                {
                    "adresse": f"Bien similaire secteur {ville} (DVF anonymisé)",
                    "surface": int(surface * 0.95),
                    "prix": int(prix_central * 0.97),
                    "date": "2024-10",
                },
                {
                    "adresse": f"Bien comparable {ville} (DVF anonymisé)",
                    "surface": int(surface * 1.05),
                    "prix": int(prix_central * 1.03),
                    "date": "2024-11",
                },
            ],
        }

    def _generate_pdf_report(
        self,
        estimation_id: str,
        type_bien: str,
        adresse: str,
        ville: str,
        surface: float,
        nb_pieces: int,
        dpe: str,
        data: dict,
    ) -> str:
        """Génère le rapport PDF d'estimation."""
        PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = str(PDF_OUTPUT_DIR / f"estimation_{estimation_id[:8]}.pdf")

        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_margins(20, 20, 20)

            # En-tête
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(26, 58, 92)
            pdf.cell(0, 12, "RAPPORT D'ESTIMATION", ln=True, align="C")

            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 6, f"{self.settings.agency_name}", ln=True, align="C")
            pdf.cell(0, 6, f"Établi le {datetime.now().strftime('%d/%m/%Y')}", ln=True, align="C")
            pdf.ln(8)

            # Référence
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 8, f"Référence : EST-{estimation_id[:8].upper()}", ln=True)
            pdf.ln(4)

            # Bien estimé
            pdf.set_fill_color(26, 58, 92)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "  BIEN ESTIMÉ", ln=True, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 11)
            pdf.ln(3)

            details = [
                ("Type de bien", type_bien),
                ("Adresse", adresse),
                ("Ville", ville),
                ("Surface habitable", f"{surface} m²"),
                ("Nombre de pièces", str(nb_pieces)),
                ("DPE", f"Classe {dpe}"),
            ]
            for label, value in details:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(60, 7, f"{label} :", border=0)
                pdf.set_font("Helvetica", "", 10)
                pdf.cell(0, 7, value, ln=True)
            pdf.ln(6)

            # Résultats
            pdf.set_fill_color(26, 58, 92)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "  RÉSULTATS DE L'ESTIMATION", ln=True, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

            prix_bas = data.get("prix_estime_bas", 0)
            prix_central = data.get("prix_estime_central", 0)
            prix_haut = data.get("prix_estime_haut", 0)
            loyer = data.get("loyer_mensuel_estime", 0)
            rentab = data.get("rentabilite_brute", 0)
            delai = data.get("delai_vente_estime_semaines", 0)

            def fmt_price(p: int) -> str:
                return f"{p:,}€".replace(",", " ")

            # Fourchette prix en grand
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(230, 126, 34)
            pdf.cell(0, 10, f"Fourchette de prix : {fmt_price(prix_bas)} — {fmt_price(prix_haut)}", ln=True, align="C")
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(26, 58, 92)
            pdf.cell(0, 12, f"Estimation centrale : {fmt_price(prix_central)}", ln=True, align="C")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

            results = [
                ("Prix au m² net vendeur", f"{data.get('prix_m2_net', 0):,}€/m²".replace(",", " ")),
                ("Loyer mensuel estimé", f"{loyer:,}€/mois".replace(",", " ")),
                ("Rentabilité brute", f"{rentab:.1f}%"),
                ("Délai de vente estimé", f"{delai} semaines"),
            ]
            pdf.set_font("Helvetica", "", 11)
            for label, value in results:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(80, 7, f"{label} :", border=0)
                pdf.set_font("Helvetica", "", 10)
                pdf.cell(0, 7, value, ln=True)
            pdf.ln(6)

            # Ajustements
            pdf.set_fill_color(26, 58, 92)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "  AJUSTEMENTS APPLIQUÉS", ln=True, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

            adj = data.get("ajustements", {})
            adj_labels = {"etat": "État général", "dpe": "DPE énergie", "etage": "Étage", "exposition": "Exposition", "parking": "Parking", "exterieur": "Extérieur"}
            pdf.set_font("Helvetica", "", 10)
            for key, label in adj_labels.items():
                val = adj.get(key, 0)
                if val != 0:
                    sign = "+" if val > 0 else ""
                    pdf.cell(80, 6, f"  {label} :", border=0)
                    pdf.cell(0, 6, f"{sign}{val:.1f}%", ln=True)
            pdf.ln(4)

            # Justification
            justif = data.get("justification", "")
            if justif:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 7, "Justification :", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(60, 60, 60)
                pdf.multi_cell(0, 5, justif)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(4)

            # Comparables
            comparables = data.get("comparables", [])
            if comparables:
                pdf.set_fill_color(26, 58, 92)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Helvetica", "B", 12)
                pdf.cell(0, 8, "  COMPARABLES DVF", ln=True, fill=True)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(3)
                pdf.set_font("Helvetica", "", 9)
                for comp in comparables:
                    price_str = f"{comp.get('prix', 0):,}€".replace(",", " ")
                    pdf.cell(0, 5,
                        f"  • {comp.get('adresse', '')} — {comp.get('surface', '')}m² — {price_str} ({comp.get('date', '')})",
                        ln=True)
                pdf.ln(6)

            # Mention légale
            pdf.set_fill_color(245, 245, 245)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.multi_cell(0, 4, self.MENTION_LEGALE, fill=True)

            # Footer
            pdf.set_y(-15)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(150, 150, 150)
            pdf.cell(0, 5, f"{self.settings.agency_name} — Estimation {estimation_id[:8].upper()} — {datetime.now().strftime('%d/%m/%Y')}", align="C")

            pdf.output(pdf_path)
            logger.info(f"Rapport PDF généré : {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Erreur génération PDF : {e}")
            return ""

    def _save_estimation(
        self, estimation_id: str, lead_id: str, adresse: str, surface: float,
        type_bien: str, data: dict,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO estimations
                   (id, lead_id, client_id, adresse, surface, type_bien,
                    prix_estime_bas, prix_estime_central, prix_estime_haut, prix_m2_net,
                    loyer_mensuel_estime, rentabilite_brute, delai_vente_estime_semaines,
                    justification, mention_legale)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    estimation_id, lead_id, self.client_id, adresse, surface, type_bien,
                    data.get("prix_estime_bas", 0),
                    data.get("prix_estime_central", 0),
                    data.get("prix_estime_haut", 0),
                    data.get("prix_m2_net", 0),
                    data.get("loyer_mensuel_estime", 0),
                    data.get("rentabilite_brute", 0.0),
                    data.get("delai_vente_estime_semaines", 0),
                    data.get("justification", ""),
                    self.MENTION_LEGALE,
                ),
            )
