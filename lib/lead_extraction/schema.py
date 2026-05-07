"""
Schéma de données structurées d'un lead qualifié.

Deux grilles de scoring distinctes (acheteur/locataire et vendeur),
score normalisé sur 24 points, avec redistribution des poids si une
info est absente (ne jamais pénaliser le silence).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ── Seuils communs (échelle 0-24) ────────────────────────────────────────────
SCORE_MAX = 24
SCORE_SEUIL_CHAUD = 18   # relance sous 2h
SCORE_SEUIL_TIEDE = 11   # relance sous 24h
#                          < 11 → nurturing long

LeadType = Literal["acheteur", "vendeur", "locataire"]
ProchainAction = Literal["rdv", "nurturing_14j", "nurturing_30j"]

# ── Poids par grille ─────────────────────────────────────────────────────────
# Acheteur / Locataire : urgence×3 + capacite_fin×2 + engagement×2 + motivation×1
# Vendeur              : urgence×3 + maturite×3     + qualite_bien×2 + motivation×1
_WEIGHTS_ACHETEUR = {
    "score_urgence": 3,
    "score_capacite_fin": 2,
    "score_engagement": 2,
    "score_motivation": 1,
}
_WEIGHTS_VENDEUR = {
    "score_urgence": 3,
    "score_maturite": 3,
    "score_qualite_bien": 2,
    "score_motivation": 1,
}


def compute_score(lead_type: str, axes: dict[str, Optional[int]]) -> int:
    """
    Calcule le score normalisé sur 24.

    Redistribue les poids des axes inconnus (None) proportionnellement
    sur les axes renseignés. Ne pénalise jamais une info absente.

    Args:
        lead_type: "acheteur", "vendeur", ou "locataire"
        axes: dict axe → score 0-3 ou None si inconnu

    Returns:
        Score entier 0-24
    """
    weights = _WEIGHTS_VENDEUR if lead_type == "vendeur" else _WEIGHTS_ACHETEUR

    known_weight = sum(w for k, w in weights.items() if axes.get(k) is not None)
    if known_weight == 0:
        return 0

    raw = sum((axes[k] or 0) * w for k, w in weights.items() if axes.get(k) is not None)
    max_raw = known_weight * 3  # maximum si tous les axes connus valent 3

    return round(raw * SCORE_MAX / max_raw)


def score_to_action(score: int) -> ProchainAction:
    if score >= SCORE_SEUIL_CHAUD:
        return "rdv"
    if score >= SCORE_SEUIL_TIEDE:
        return "nurturing_14j"
    return "nurturing_30j"


def score_to_label(score: int) -> str:
    if score >= SCORE_SEUIL_CHAUD:
        return "chaud"
    if score >= SCORE_SEUIL_TIEDE:
        return "tiede"
    return "froid"


@dataclass
class LeadExtractionResult:
    """
    Résultat d'une extraction IA depuis un texte libre.
    Tous les axes sont None si non détectés (redistributés dans compute_score).
    """
    # Type de lead (obligatoire)
    lead_type: str = "acheteur"          # acheteur | vendeur | locataire

    # Axes communs
    score_urgence: Optional[int] = None           # 0-3
    score_motivation: Optional[int] = None        # 0-3

    # Axes acheteur / locataire
    score_capacite_fin: Optional[int] = None      # 0-3
    score_engagement: Optional[int] = None        # 0-3

    # Axes vendeur
    score_maturite: Optional[int] = None          # 0-3
    score_qualite_bien: Optional[int] = None      # 0-3

    # Score final normalisé 0-24 (calculé par compute_score)
    score_total: int = 0

    # Infos structurées
    projet: Optional[str] = None          # achat|vente|location|estimation
    localisation: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    financement: Optional[str] = None
    motivation: Optional[str] = None

    # Cas ambigu vendeur+acheteur
    is_ambiguous: bool = False
    linked_lead_hint: Optional[str] = None  # description de la fiche liée à créer

    # Action recommandée
    prochaine_action: ProchainAction = "nurturing_30j"

    # Résumé libre
    resume: str = ""

    # Méta
    raw_json: dict = field(default_factory=dict)
    extraction_source: str = "llm"  # "llm" | "mock"

    def _axes(self) -> dict[str, Optional[int]]:
        if self.lead_type == "vendeur":
            return {
                "score_urgence": self.score_urgence,
                "score_maturite": self.score_maturite,
                "score_qualite_bien": self.score_qualite_bien,
                "score_motivation": self.score_motivation,
            }
        return {
            "score_urgence": self.score_urgence,
            "score_capacite_fin": self.score_capacite_fin,
            "score_engagement": self.score_engagement,
            "score_motivation": self.score_motivation,
        }

    def recompute_score(self) -> None:
        """Recalcule score_total et prochaine_action depuis les axes."""
        self.score_total = compute_score(self.lead_type, self._axes())
        self.prochaine_action = score_to_action(self.score_total)

    @classmethod
    def from_dict(cls, d: dict, source: str = "llm") -> "LeadExtractionResult":
        lead_type = (d.get("lead_type") or "acheteur").lower()
        if lead_type not in ("acheteur", "vendeur", "locataire"):
            lead_type = "acheteur"

        result = cls(
            lead_type=lead_type,
            score_urgence=_to_int03(d.get("score_urgence")),
            score_motivation=_to_int03(d.get("score_motivation")),
            score_capacite_fin=_to_int03(d.get("score_capacite_fin")),
            score_engagement=_to_int03(d.get("score_engagement")),
            score_maturite=_to_int03(d.get("score_maturite")),
            score_qualite_bien=_to_int03(d.get("score_qualite_bien")),
            projet=d.get("projet"),
            localisation=d.get("localisation"),
            budget=d.get("budget"),
            timeline=d.get("timeline"),
            financement=d.get("financement"),
            motivation=d.get("motivation"),
            is_ambiguous=bool(d.get("is_ambiguous", False)),
            linked_lead_hint=d.get("linked_lead_hint"),
            resume=d.get("resume", ""),
            raw_json=d,
            extraction_source=source,
        )
        result.recompute_score()
        # Override action only if LLM explicitly provided it and score agrees
        llm_action = d.get("prochaine_action")
        if llm_action in ("rdv", "nurturing_14j", "nurturing_30j"):
            result.prochaine_action = llm_action
        return result

    @classmethod
    def mock(cls) -> "LeadExtractionResult":
        r = cls(
            lead_type="acheteur",
            score_urgence=3,
            score_capacite_fin=2,
            score_engagement=2,
            score_motivation=2,
            projet="achat",
            localisation="Paris 15e",
            budget="450 000€",
            timeline="3-6 mois",
            financement="Apport 20%",
            motivation="Mutation professionnelle",
            resume="[MOCK] Lead qualifié acheteur avec apport, mutation professionnelle.",
            extraction_source="mock",
        )
        r.recompute_score()
        return r


def _to_int03(v) -> Optional[int]:
    """Convertit en int 0-3, ou None si absent/invalide."""
    if v is None:
        return None
    try:
        return max(0, min(3, int(v)))
    except (ValueError, TypeError):
        return None
