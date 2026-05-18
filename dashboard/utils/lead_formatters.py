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


def filter_leads_by_search(leads: list, next_actions: dict, query: str) -> list:
    """Filtre une liste de Lead sur une recherche texte libre (case-insensitive).

    Champs couverts : nom, prénom, téléphone, email, localisation, budget,
    motivation, résumé, notes, financement, timeline, projet,
    next_action_label, next_action_reason.

    Retourne tous les leads si query est vide ou blanc.
    Compatible avec n'importe quel objet Lead-like (duck typing).
    """
    q = query.strip().lower()
    if not q:
        return leads
    result = []
    for lead in leads:
        na = next_actions.get(getattr(lead, "id", ""), {})
        proj = getattr(lead, "projet", None)
        fields = [
            getattr(lead, "prenom", ""),
            getattr(lead, "nom", ""),
            getattr(lead, "telephone", ""),
            getattr(lead, "email", ""),
            getattr(lead, "localisation", ""),
            getattr(lead, "budget", ""),
            getattr(lead, "motivation", ""),
            getattr(lead, "resume", ""),
            getattr(lead, "notes_agent", ""),
            getattr(lead, "financement", ""),
            getattr(lead, "timeline", ""),
            getattr(proj, "value", "") if proj else "",
            na.get("next_action_label") or "",
            na.get("next_action_reason") or "",
        ]
        if any(q in (f or "").lower() for f in fields):
            result.append(lead)
    return result
