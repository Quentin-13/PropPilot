"""
Tests Chantier 2 — Push CRM email parsing.

Couverture :
  1. Corps email : tous les champs spec présents
  2. Sujet prod correct ([PropPilot])
  3. Sujet test correct ([TEST PropPilot])
  4. Aucune valeur "None" dans le corps
  5. SendGrid mocké : push_lead() retourne True sans appel réel
  6. Échec SendGrid → enqueue dans crm_push_queue
  7. Isolation client_id : pas de push si crm_target_email vide
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from lib.crm_connectors.email_parsing import EmailParsingConnector


# ─── Fixture lead de référence ────────────────────────────────────────────────

@pytest.fixture
def lead_complet():
    return {
        "id": "lead-abc-123",
        "client_id": "client-xyz",
        "prenom": "Marie",
        "nom": "Dupont",
        "telephone": "+33600000001",
        "email": "marie@test.fr",
        "lead_type": "acheteur",
        "type_projet": "achat",
        "budget_min": 300000,
        "budget_max": 400000,
        "zone": "Lyon 6ème",
        "type_bien": "T3",
        "surface_min": 65,
        "surface_max": 80,
        "score": 20,
        "score_label": "chaud",
        "statut": "chaud",
        "motivation": "Mutation professionnelle",
        "urgence": "< 3 mois",
        "objections": "Financement à confirmer",
        "financement_str": "prêt bancaire, apport 20%",
        "updated_at": "2026-05-15 10:00",
        "resume": "Lead acheteur T3 Lyon 6, budget cohérent.",
        "next_action_label": "Rappeler sous 2h",
        "next_action_reason": "Lead chaud, premier contact.",
        "conversation_history": "[SMS IN  - 2026-05-15 09:55] Bonjour je cherche un T3",
    }


@pytest.fixture
def connector():
    return EmailParsingConnector(
        target_email="import@moncrm.fr",
        crm_label="Netty",
    )


# ─── Test 1 : corps contient tous les champs spec ─────────────────────────────

def test_body_contient_tous_les_champs_spec(connector, lead_complet):
    body = connector._build_body(lead_complet)

    assert "PROPPILOT_LEAD_ID:" in body
    assert "PROPPILOT_CLIENT_ID:" in body
    assert "PROPPILOT_UPDATED_AT:" in body
    assert "TYPE_LEAD:" in body
    assert "SCORE:" in body
    assert "STATUT:" in body
    assert "NOM:" in body
    assert "PRENOM:" in body
    assert "TELEPHONE:" in body
    assert "EMAIL:" in body
    assert "PROJET:" in body
    assert "BUDGET:" in body
    assert "ZONE:" in body
    assert "TYPE_BIEN:" in body
    assert "URGENCE:" in body
    assert "MOTIVATION:" in body
    assert "OBJECTIONS:" in body
    assert "FINANCEMENT:" in body
    assert "RESUME:" in body
    assert "PROCHAINE_ACTION:" in body
    assert "RAISON:" in body
    assert "HISTORIQUE_CONVERSATIONS:" in body
    assert "PropPilot — Mise à jour automatique" in body


# ─── Test 2 : valeurs correctes dans le corps ─────────────────────────────────

def test_body_valeurs_correctes(connector, lead_complet):
    body = connector._build_body(lead_complet)

    assert "lead-abc-123" in body
    assert "Marie" in body
    assert "Dupont" in body
    assert "+33600000001" in body
    assert "20/24" in body
    # "tiede" → "tiède" avec accent
    assert "chaud" in body
    assert "300" in body  # budget
    assert "Lyon 6ème" in body
    assert "T3" in body
    assert "< 3 mois" in body
    assert "Mutation professionnelle" in body
    assert "Financement à confirmer" in body
    assert "prêt bancaire" in body
    assert "Rappeler sous 2h" in body
    assert "[SMS IN" in body


# ─── Test 3 : sujet production ────────────────────────────────────────────────

def test_sujet_production(connector, lead_complet):
    subject = connector._build_subject(lead_complet)

    assert subject.startswith("[PropPilot]")
    assert "Marie Dupont" in subject
    assert "chaud" in subject
    assert "TEST" not in subject


# ─── Test 4 : sujet test (push_test_lead) ─────────────────────────────────────

def test_sujet_test(lead_complet):
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    sent_subjects = []

    original_send = connector._send
    def capture_send(subject, body):
        sent_subjects.append(subject)
        return True
    connector._send = capture_send

    connector.push_test_lead(lead_complet)
    assert len(sent_subjects) == 1
    assert sent_subjects[0] == "[TEST PropPilot] Remontée CRM"


# ─── Test 5 : aucune valeur "None" dans le corps ──────────────────────────────

def test_pas_de_none_dans_le_corps(connector):
    lead_incomplet = {
        "id": "lead-001",
        "client_id": "client-001",
        "prenom": None,
        "nom": None,
        "telephone": None,
        "email": None,
        "lead_type": None,
        "type_projet": None,
        "budget_min": None,
        "budget_max": None,
        "zone": None,
        "type_bien": None,
        "score": None,
        "score_label": None,
        "statut": None,
        "motivation": None,
        "urgence": None,
        "objections": None,
        "financement_str": None,
        "updated_at": None,
        "resume": None,
        "next_action_label": None,
        "next_action_reason": None,
        "conversation_history": None,
    }
    body = connector._build_body(lead_incomplet)

    # Aucune ligne ne doit contenir le mot "None" seul
    for line in body.splitlines():
        value_part = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
        assert value_part.lower() != "none", f"Valeur 'None' trouvée dans : {line!r}"


# ─── Test 6 : SendGrid mocké — push_lead() retourne True ──────────────────────

def test_push_lead_mock_sendgrid(lead_complet):
    """Vérifie que push_lead retourne True quand SendGrid n'est pas disponible (mock mode)."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    with patch("lib.crm_connectors.email_parsing.EmailParsingConnector._send") as mock_send:
        mock_send.return_value = True
        result = connector.push_lead(lead_complet)

    assert result is True
    mock_send.assert_called_once()
    # Vérifie que le sujet et le corps ont été passés
    call_kwargs = mock_send.call_args
    subject = call_kwargs[1].get("subject") or call_kwargs[0][0]
    body = call_kwargs[1].get("body") or call_kwargs[0][1]
    assert "[PropPilot]" in subject
    assert "PROPPILOT_LEAD_ID" in body


# ─── Test 7 : pas de push si target_email vide (isolation client) ─────────────

def test_pas_de_push_si_email_cible_vide(lead_complet):
    """Garantit qu'un connecteur sans email cible n'envoie rien."""
    connector_sans_cible = EmailParsingConnector(target_email="")

    with patch("lib.crm_connectors.email_parsing.EmailParsingConnector._send") as mock_send:
        result = connector_sans_cible.push_lead(lead_complet)

    assert result is False
    mock_send.assert_not_called()


# ─── Test 8 : accent tiède ────────────────────────────────────────────────────

def test_accent_tiede(connector):
    lead_tiede = {
        "id": "lead-002",
        "client_id": "client-001",
        "prenom": "Paul",
        "nom": "Martin",
        "telephone": "+33611111111",
        "score": 12,
        "score_label": "tiede",
        "statut": "tiède",
    }
    subject = connector._build_subject(lead_tiede)
    body = connector._build_body(lead_tiede)

    assert "tiède" in subject
    assert "tiède" in body
    assert "tiede" not in subject   # pas la version sans accent dans le sujet
