"""Helpers d'affichage pour les leads — labels propres côté client."""
from __future__ import annotations

_LEAD_STATUS_LABELS: dict[str, str] = {
    "entrant":          "Nouveau",
    "en_qualification": "À qualifier",
    "qualifie":         "Qualifié",
    "rdv_propose":      "RDV proposé",
    "rdv_booke":        "RDV planifié",
    "mandat":           "Opportunité avancée",
    "vendu":            "Converti",
    "perdu":            "Perdu",
    "nurturing":        "Suivi long terme",
}


def format_lead_status(status: str | None) -> str:
    """Retourne le label client pour une valeur interne de statut.
    Fallback : retourne la valeur brute (jamais crash).
    """
    if not status:
        return "—"
    return _LEAD_STATUS_LABELS.get(status, status)
