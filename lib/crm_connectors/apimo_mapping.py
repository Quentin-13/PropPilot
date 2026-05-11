"""
Mapping PropPilot → Apimo API.
Centralise les transformations de champs — ajustable sans toucher au code métier.
"""
from __future__ import annotations

SCORE_LABEL_TO_TAG = {
    "chaud": "proppilot-chaud",
    "tiede": "proppilot-tiede",
    "froid": "proppilot-froid",
}

SCORE_LABEL_TO_FR = {
    "chaud": "Chaud 🔴",
    "tiede": "Tiède 🟠",
    "froid": "Froid 🔵",
}

TYPE_PROJET_TO_FR = {
    "achat": "Achat",
    "vente": "Vente",
    "location": "Location",
    "investissement": "Investissement",
    "inconnu": "Non précisé",
}

MOTIVATION_TO_FR = {
    "premier_achat": "Premier achat",
    "investissement_locatif": "Investissement locatif",
    "demenagement": "Déménagement",
    "agrandissement_famille": "Agrandissement famille",
    "divorce": "Divorce / séparation",
    "mutation_pro": "Mutation professionnelle",
    "retraite": "Retraite",
    "autre": "Autre",
}


def build_contact_payload(lead_data: dict) -> dict:
    """Construit le payload JSON pour POST /providers/{id}/contacts."""
    return {
        "first_name": lead_data.get("prenom") or "",
        "last_name": lead_data.get("nom") or "",
        "phone": lead_data.get("telephone") or "",
        "email": lead_data.get("email") or "",
        "origin": "web",
        "comment": _build_short_comment(lead_data),
    }


def build_note_text(lead_data: dict) -> str:
    """Construit le texte de la note qualification pour le contact Apimo."""
    score_label = (lead_data.get("score_label") or "froid").lower()
    tag = SCORE_LABEL_TO_TAG.get(score_label, "proppilot-froid")
    score_fr = SCORE_LABEL_TO_FR.get(score_label, "Froid")
    type_projet = TYPE_PROJET_TO_FR.get(lead_data.get("type_projet") or "inconnu", "Non précisé")
    motivation = MOTIVATION_TO_FR.get(lead_data.get("motivation") or "", "")
    budget_str = _budget_str(lead_data)
    surface_str = _surface_str(lead_data)

    lines = [
        "[PropPilot — Qualification IA]",
        f"Score : {score_fr}  |  Tag : #{tag}",
        "Source : PropPilot",
        "---",
        f"Projet : {type_projet}",
    ]
    if budget_str:
        lines.append(f"Budget : {budget_str}")
    lines.append(f"Zone : {lead_data.get('zone') or '—'}")
    lines.append(f"Type de bien : {lead_data.get('type_bien') or '—'}")
    if surface_str:
        lines.append(f"Surface : {surface_str}")
    if motivation:
        lines.append(f"Motivation : {motivation}")
    lines += ["", f"Résumé : {lead_data.get('resume') or '—'}"]

    if lead_data.get("next_action_label"):
        lines += [
            "",
            "--- ACTION RECOMMANDÉE ---",
            f"Action : {lead_data['next_action_label']}",
        ]
        if lead_data.get("next_action_reason"):
            lines.append(f"Pourquoi : {lead_data['next_action_reason']}")

    return "\n".join(lines)


def _build_short_comment(lead_data: dict) -> str:
    type_projet = TYPE_PROJET_TO_FR.get(lead_data.get("type_projet") or "inconnu", "Non précisé")
    score_label = lead_data.get("score_label") or "froid"
    score_fr = SCORE_LABEL_TO_FR.get(score_label, "Froid")
    zone = lead_data.get("zone") or ""
    return f"Lead IA PropPilot — {score_fr} — {type_projet}{' — ' + zone if zone else ''}"


def _budget_str(lead_data: dict) -> str:
    bmin = lead_data.get("budget_min")
    bmax = lead_data.get("budget_max")
    if bmin and bmax:
        return f"{int(bmin):,} € — {int(bmax):,} €".replace(",", " ")
    if bmin:
        return f"à partir de {int(bmin):,} €".replace(",", " ")
    if bmax:
        return f"jusqu'à {int(bmax):,} €".replace(",", " ")
    return ""


def _surface_str(lead_data: dict) -> str:
    smin = lead_data.get("surface_min")
    smax = lead_data.get("surface_max")
    if smin and smax:
        return f"{smin} — {smax} m²"
    if smin:
        return f"à partir de {smin} m²"
    if smax:
        return f"jusqu'à {smax} m²"
    return ""
