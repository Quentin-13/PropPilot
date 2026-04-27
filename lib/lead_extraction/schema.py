"""
Schéma de données structurées d'un lead qualifié.
Source originale : agents/lead_qualifier.py + config/prompts.py (section scoring).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ── Seuils de score ──────────────────────────────────────────────────────────
SCORE_SEUIL_RDV = 7              # Score ≥ 7 → proposer un RDV immédiat
SCORE_SEUIL_NURTURING_COURT = 4  # Score 4-6 → nurturing 14 jours
#                                  Score < 4  → nurturing 30 jours

ProchainAction = Literal["rdv", "nurturing_14j", "nurturing_30j"]


def score_to_action(score: int) -> ProchainAction:
    """Routing déterministe basé sur le score total (0-10)."""
    if score >= SCORE_SEUIL_RDV:
        return "rdv"
    if score >= SCORE_SEUIL_NURTURING_COURT:
        return "nurturing_14j"
    return "nurturing_30j"


# ── Règles de scoring (extraites du prompt Léa pour référence) ───────────────
#
# Urgence (0-4 pts) :
#   délai < 3 mois  = 4 pts
#   délai 3-6 mois  = 2 pts
#   délai > 6 mois  = 1 pt
#   pas de délai    = 0 pt
#
# Budget qualifié (0-3 pts) :
#   accord bancaire     = 3 pts
#   apport > 20 %       = 2 pts
#   apport < 20 %       = 1 pt
#   rien                = 0 pt
#
# Motivation (0-3 pts) :
#   divorce / mutation / séparation = 3 pts
#   héritage / retraite             = 2 pts
#   projet vague                    = 1 pt
#   inconnu                         = 0 pt


@dataclass
class LeadExtractionResult:
    """
    Résultat d'une extraction IA depuis un texte libre (conversation ou transcription).
    Tous les champs texte sont None si non détectés.
    """
    # Scores
    score_total: int = 0
    score_urgence: int = 0       # 0-4
    score_budget: int = 0        # 0-3
    score_motivation: int = 0    # 0-3

    # Infos structurées
    projet: Optional[str] = None          # achat|vente|location|estimation
    localisation: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    financement: Optional[str] = None
    motivation: Optional[str] = None

    # Action recommandée
    prochaine_action: ProchainAction = "nurturing_30j"

    # Résumé libre
    resume: str = ""

    # Méta
    raw_json: dict = field(default_factory=dict)
    extraction_source: str = "llm"  # "llm" | "mock"

    @classmethod
    def from_dict(cls, d: dict, source: str = "llm") -> "LeadExtractionResult":
        score = d.get("score_total", 0)
        return cls(
            score_total=score,
            score_urgence=d.get("score_urgence", 0),
            score_budget=d.get("score_budget", 0),
            score_motivation=d.get("score_motivation", 0),
            projet=d.get("projet"),
            localisation=d.get("localisation"),
            budget=d.get("budget"),
            timeline=d.get("timeline"),
            financement=d.get("financement"),
            motivation=d.get("motivation"),
            prochaine_action=d.get("prochaine_action") or score_to_action(score),
            resume=d.get("resume", ""),
            raw_json=d,
            extraction_source=source,
        )

    @classmethod
    def mock(cls) -> "LeadExtractionResult":
        """Résultat mock pour les tests et le mode sans clé API."""
        return cls(
            score_total=7,
            score_urgence=3,
            score_budget=2,
            score_motivation=2,
            projet="achat",
            localisation="Paris 15e",
            budget="450 000€",
            timeline="3-6 mois",
            financement="Apport 20%",
            motivation="Mutation professionnelle",
            prochaine_action="rdv",
            resume="[MOCK] Lead qualifié acheteur avec apport, mutation professionnelle.",
            extraction_source="mock",
        )
