"""
Import CSV universel — fonctionne avec TOUS les CRM.
L'agent exporte ses contacts en CSV depuis son CRM,
importe dans PropPilot, Léa prend le relais.

Formats supportés :
- Export Hektor (La Boîte Immo)
- Export Apimo
- Export Prospeneo
- Format générique (prénom, nom, téléphone, email, projet)
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from memory.models import Canal, Lead, ProjetType

# Mapping des colonnes par CRM source
COLUMN_MAPPINGS: dict[str, dict[str, list[str]]] = {
    "hektor": {
        "prenom":      ["Prénom", "prénom", "firstname", "prenom"],
        "nom":         ["Nom", "nom", "lastname"],
        "telephone":   ["Téléphone", "téléphone", "telephone", "phone", "tel", "mobile"],
        "email":       ["Email", "email", "mail", "courriel"],
        "projet":      ["Type projet", "type_projet", "projet", "type"],
        "budget":      ["Budget", "budget", "budget_max"],
        "localisation":["Localisation", "localisation", "ville", "location", "secteur"],
    },
    "apimo": {
        "prenom":      ["contact_firstname"],
        "nom":         ["contact_lastname"],
        "telephone":   ["contact_phone"],
        "email":       ["contact_email"],
        "projet":      ["search_type"],
        "budget":      ["search_budget_max"],
        "localisation":["search_location"],
    },
    "prospeneo": {
        "prenom":      ["firstname", "prenom"],
        "nom":         ["lastname", "nom"],
        "telephone":   ["phone", "telephone", "mobile"],
        "email":       ["email"],
        "projet":      ["project_type", "type_projet"],
        "budget":      ["budget_max", "budget"],
        "localisation":["city", "location", "ville"],
    },
    "generic": {
        "prenom":      ["prénom", "prenom", "firstname", "first_name", "Prénom"],
        "nom":         ["nom", "lastname", "last_name", "Nom"],
        "telephone":   ["téléphone", "telephone", "phone", "mobile", "tel", "Téléphone"],
        "email":       ["email", "mail", "courriel", "Email"],
        "projet":      ["projet", "type", "project", "type_projet"],
        "budget":      ["budget", "prix_max", "budget_max", "Budget"],
        "localisation":["ville", "localisation", "location", "secteur", "Ville"],
    },
}


def detect_crm_format(headers: list[str]) -> str:
    """Détecte automatiquement le format CRM depuis les en-têtes CSV."""
    headers_set = set(h.lower().strip() for h in headers)

    if "contact_firstname" in headers_set or "contact_phone" in headers_set:
        return "apimo"
    if "Prénom" in headers or "prénom" in headers_set:
        return "hektor"
    if "project_type" in headers_set or "firstname" in headers_set:
        return "prospeneo"
    return "generic"


def parse_csv_leads(
    file_content: str,
    client_id: str,
    source_name: str = "Import CSV",
    crm_hint: Optional[str] = None,
) -> tuple[list[Lead], int, list[str]]:
    """
    Parse un CSV et retourne (leads, nb_success, errors).

    Args:
        file_content: Contenu brut du fichier CSV (UTF-8 ou latin-1)
        client_id:    ID du client PropPilot
        source_name:  Nom affiché dans lead.notes_agent
        crm_hint:     Format CRM forcé ("hektor", "apimo", etc.) — auto-détecté si None

    Returns:
        (leads, count, errors) — leads prêts à être passés à Léa
    """
    leads: list[Lead] = []
    errors: list[str] = []

    # Décoder le contenu si bytes
    if isinstance(file_content, bytes):
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                file_content = file_content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

    reader = csv.DictReader(io.StringIO(file_content))
    headers = list(reader.fieldnames or [])

    if not headers:
        return [], 0, ["Fichier CSV vide ou sans en-têtes"]

    crm_format = crm_hint if crm_hint in COLUMN_MAPPINGS else detect_crm_format(headers)
    mapping = COLUMN_MAPPINGS.get(crm_format, COLUMN_MAPPINGS["generic"])

    def find_value(row: dict, possible_keys: list[str]) -> str:
        for key in possible_keys:
            if key in row and row[key] and str(row[key]).strip():
                return str(row[key]).strip()
        return ""

    def parse_budget(budget_str: str) -> str:
        """Convertit une string budget en format PropPilot."""
        if not budget_str:
            return ""
        try:
            cleaned = budget_str.replace("€", "").replace(" ", "").replace(",", ".").replace("\u202f", "")
            amount = float(cleaned)
            if amount <= 0:
                return ""
            return f"{int(amount):,}€".replace(",", " ")
        except (ValueError, TypeError):
            return budget_str

    for i, row in enumerate(reader):
        line_num = i + 2  # ligne 1 = en-têtes

        try:
            telephone = find_value(row, mapping["telephone"])
            if not telephone:
                errors.append(f"Ligne {line_num} : téléphone manquant — lead ignoré")
                continue

            # Normalisation téléphone → E.164 basique
            tel = telephone.replace(" ", "").replace("-", "").replace(".", "")
            if tel.startswith("0") and len(tel) == 10:
                tel = "+33" + tel[1:]

            projet_str = find_value(row, mapping["projet"])
            projet = _parse_projet(projet_str)
            budget_str = find_value(row, mapping["budget"])

            lead = Lead(
                client_id=client_id,
                prenom=find_value(row, mapping["prenom"]),
                nom=find_value(row, mapping["nom"]),
                telephone=tel,
                email=find_value(row, mapping["email"]),
                projet=projet,
                localisation=find_value(row, mapping["localisation"]),
                budget=parse_budget(budget_str),
                source=Canal.MANUEL,
                notes_agent=f"[Import:{source_name}:ligne_{line_num}]",
            )
            leads.append(lead)

        except Exception as e:
            errors.append(f"Ligne {line_num} : erreur — {e}")

    return leads, len(leads), errors


def _parse_projet(raw: str) -> ProjetType:
    """Normalise un type de projet depuis le CSV."""
    raw_lower = (raw or "").lower().strip()
    if any(k in raw_lower for k in ["achat", "buy", "acquéreur", "acquéreur"]):
        return ProjetType.ACHAT
    if any(k in raw_lower for k in ["vente", "sell", "vendeur"]):
        return ProjetType.VENTE
    if any(k in raw_lower for k in ["location", "locat", "locataire"]):
        return ProjetType.LOCATION
    if any(k in raw_lower for k in ["estim", "valuation"]):
        return ProjetType.ESTIMATION
    return ProjetType.INCONNU


def generate_sample_csv(crm_format: str = "generic") -> str:
    """Génère un CSV d'exemple pour aider l'utilisateur à préparer son fichier."""
    if crm_format == "hektor":
        return "Prénom,Nom,Téléphone,Email,Type projet,Budget,Localisation\nMarie,Dupont,0612345678,marie@test.fr,achat,250000,Lyon\n"
    if crm_format == "apimo":
        return "contact_firstname,contact_lastname,contact_phone,contact_email,search_type,search_budget_max,search_location\nJean,Martin,0687654321,jean@test.fr,achat,400000,Paris\n"
    return "prénom,nom,téléphone,email,projet,budget,ville\nMarie,Dupont,0612345678,marie@test.fr,achat,250000,Lyon\nJean,Martin,0687654321,jean@test.fr,vente,400000,Paris\n"
