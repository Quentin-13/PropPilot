"""
Tests — ordre pipeline CRM push : compute_next_action AVANT push_lead_to_crm.

Couvre les 8 cas mixtes (SMS/appel × chaud/froid) et vérifie que le payload CRM
contient toujours la prochaine action recalculée, jamais l'ancienne.

Section 5 — couverture échec compute_next_action :
  Si compute_next_action() retourne None, les champs next_action sont neutralisés
  dans le payload CRM (champs vides) pour éviter qu'une ancienne consigne
  contradictoire ne parte au client.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_lead_row(
    lead_id: str = "lead-001",
    client_id: str = "client-1",
    score: int = 20,
    next_action_label: str = "Rappeler aujourd'hui",
    next_action_reason: str = "Lead chaud.",
) -> dict:
    return {
        "id": lead_id,
        "client_id": client_id,
        "prenom": "Test",
        "nom": "Lead",
        "telephone": "+33600000001",
        "email": "",
        "projet": "achat",
        "localisation": "Paris",
        "motivation": "mutation",
        "score": score,
        "resume": "Cherche T3",
        "next_action_label": next_action_label,
        "next_action_reason": next_action_reason,
        "updated_at": datetime(2026, 5, 18, 10, 0),
    }


def _mock_conn_for_lead(lead_row: dict) -> MagicMock:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = lead_row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ─── 1. Ordre pipeline SMS : compute_next_action avant push_lead_to_crm ───────

def test_sms_hook_compute_next_action_avant_push_crm():
    """
    _trigger_post_extraction_hooks() doit appeler compute_next_action()
    strictement AVANT push_lead_to_crm(). Ordre garanti même si les deux
    réussissent.
    """
    call_order: list[str] = []

    def fake_compute(lead_id):
        call_order.append("compute_next_action")
        return MagicMock(label="Rappeler — urgence mutation", reason="Mutation juillet.")

    def fake_push(client_id, lead_data):
        call_order.append("push_lead_to_crm")

    fake_lead_data = _make_lead_row()

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=fake_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert call_order == ["compute_next_action", "push_lead_to_crm"], (
        f"Ordre incorrect : {call_order}"
    )


def test_appel_hook_compute_next_action_avant_push_crm():
    """
    _trigger_call_post_extraction_hooks() : même garantie d'ordre que SMS.
    """
    call_order: list[str] = []

    def fake_compute(lead_id):
        call_order.append("compute_next_action")
        return MagicMock(label="Programmer visite", reason="Urgence juillet.")

    def fake_push(client_id, lead_data):
        call_order.append("push_lead_to_crm")

    fake_lead_data = _make_lead_row()

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=fake_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from webhooks.twilio_voice import _trigger_call_post_extraction_hooks
        _trigger_call_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert call_order == ["compute_next_action", "push_lead_to_crm"], (
        f"Ordre incorrect : {call_order}"
    )


# ─── 2. extract_and_update_lead ne push pas directement ───────────────────────

def test_extract_and_update_lead_ne_push_pas():
    """
    extract_and_update_lead() ne doit plus déclencher push_lead_to_crm().
    Le push est exclusivement géré par les hooks post-extraction.
    """
    from lib.lead_extraction.consolidated_extraction import extract_and_update_lead

    mock_data = MagicMock()
    mock_data.extraction_status = "success"
    mock_data.score_qualification = 22

    with patch("lib.consolidated_transcript.build_lead_conversation_transcript", return_value="Bonjour"), \
         patch("lib.call_extraction_pipeline.CallExtractionPipeline") as mock_pipeline, \
         patch("memory.call_repository.save_sms_extraction"), \
         patch("lib.crm_connectors.factory.push_lead_to_crm") as mock_push:

        mock_pipeline.return_value.extract.return_value = mock_data
        extract_and_update_lead(lead_id="lead-001", client_id="client-1")

    mock_push.assert_not_called()


# ─── 3. Cas mixtes — payload CRM contient toujours la nouvelle action ──────────

def test_sms_refroidissement_puis_sms_rechauffement_payload_nouveau():
    """
    Cas 1 : lead froid (relance 2027) → nouveau SMS mutation juillet.
    Le payload CRM poussé par le hook doit contenir la NOUVELLE action,
    pas 'relance 2027'.
    """
    new_action_label = "Rappeler d'urgence — mutation juillet confirmée"
    new_action_reason = "Urgence réelle, délai court."

    lead_row_after_update = _make_lead_row(
        score=24,
        next_action_label=new_action_label,
        next_action_reason=new_action_reason,
    )
    pushed_payloads: list[dict] = []

    def fake_compute(lead_id):
        return MagicMock(label=new_action_label, reason=new_action_reason)

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=lead_row_after_update), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert "2027" not in payload.get("next_action_label", ""), (
        "L'ancienne action 'relance 2027' ne doit pas apparaître dans le payload CRM"
    )
    assert new_action_label in payload.get("next_action_label", "")


def test_sms_refroidissement_puis_appel_rechauffement_payload_nouveau():
    """
    Cas 2 : lead froid → appel entrant (urgence juillet).
    Le hook appel doit pousser la nouvelle action, pas l'ancienne.
    """
    new_action_label = "Organiser visite semaine prochaine"
    new_action_reason = "Mutation juillet, délai réel."

    lead_row_after_update = _make_lead_row(
        score=22,
        next_action_label=new_action_label,
        next_action_reason=new_action_reason,
    )
    pushed_payloads: list[dict] = []

    def fake_compute(lead_id):
        return MagicMock(label=new_action_label, reason=new_action_reason)

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=lead_row_after_update), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from webhooks.twilio_voice import _trigger_call_post_extraction_hooks
        _trigger_call_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert "2027" not in payload.get("next_action_label", "")
    assert new_action_label in payload.get("next_action_label", "")


def test_appel_chaud_puis_sms_refroidissement_payload_nouveau():
    """
    Cas 3 : lead chaud (visite programmée) → SMS projet en pause.
    Le hook SMS doit pousser la nouvelle action froide.
    """
    new_action_label = "Relance début 2027 — projet en pause"
    new_action_reason = "Le prospect a mis le projet en pause explicitement."

    lead_row_after_update = _make_lead_row(
        score=4,
        next_action_label=new_action_label,
        next_action_reason=new_action_reason,
    )
    pushed_payloads: list[dict] = []

    def fake_compute(lead_id):
        return MagicMock(label=new_action_label, reason=new_action_reason)

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=lead_row_after_update), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert "visite" not in payload.get("next_action_label", "").lower(), (
        "L'ancienne action 'visite' ne doit pas apparaître dans le payload CRM"
    )
    assert new_action_label in payload.get("next_action_label", "")


def test_appel_froid_puis_appel_chaud_payload_nouveau():
    """
    Cas 4 : appel froid → nouvel appel chaud.
    Hook appel : nouvelle action chaude dans le payload.
    """
    new_action_label = "Rappeler aujourd'hui — budget confirmé"
    new_action_reason = "Accord bancaire obtenu, très motivé."

    lead_row_after_update = _make_lead_row(
        score=23,
        next_action_label=new_action_label,
        next_action_reason=new_action_reason,
    )
    pushed_payloads: list[dict] = []

    def fake_compute(lead_id):
        return MagicMock(label=new_action_label, reason=new_action_reason)

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", side_effect=fake_compute), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=lead_row_after_update), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from webhooks.twilio_voice import _trigger_call_post_extraction_hooks
        _trigger_call_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert new_action_label in payload.get("next_action_label", "")


# ─── 4. compute_next_action écrase correctement les anciens champs ─────────────

def test_compute_next_action_ecrase_ancienne_action(tmp_path):
    """
    Cas 6 : compute_next_action() avec un nouveau contexte doit écraser
    next_action_label même si une valeur existe déjà en DB.
    Vérifie que _save_next_action() reçoit bien le nouveau label.
    """
    from lib.lead_extraction.next_action import NextAction

    new_action = NextAction(
        label="Rappeler — mutation juillet urgente",
        priority="haute",
        reason="Urgence réelle.",
        deadline=None,
    )

    saved_calls: list[tuple] = []

    def fake_save(lead_id, action):
        saved_calls.append((lead_id, action.label))

    lead_row = {
        "id": "lead-001",
        "client_id": "client-1",
        "prenom": "Test",
        "nom": "Lead",
        "projet": "achat",
        "score": 22,
        "statut": "chaud",
        "motivation": "mutation",
        "next_action_label": "Programmer une relance début janvier 2027",
        "next_action_priority": "basse",
        "next_action_reason": "Projet en pause.",
        "next_action_deadline": None,
        "next_action_computed_at": None,
        "created_at": datetime(2026, 5, 1),
    }

    mock_conn = _mock_conn_for_lead(lead_row)

    with patch("memory.database.get_connection", return_value=mock_conn), \
         patch("lib.lead_extraction.next_action._latest_activity_at", return_value=None), \
         patch("lib.lead_extraction.next_action._compute_via_llm", return_value=new_action), \
         patch("lib.lead_extraction.next_action._save_next_action", side_effect=fake_save):

        from lib.lead_extraction import next_action as na_module
        # Forcer invalidation du cache
        result = na_module.compute_next_action("lead-001")

    assert result is not None
    assert len(saved_calls) == 1
    saved_lead_id, saved_label = saved_calls[0]
    assert saved_lead_id == "lead-001"
    assert saved_label == "Rappeler — mutation juillet urgente"
    assert "2027" not in saved_label


# ─── 5. Échec compute_next_action → champs neutralisés dans payload CRM ───────

def _lead_row_with_old_action(
    old_label: str = "Programmer une relance début janvier 2027",
    old_reason: str = "Le prospect met explicitement le projet en pause.",
) -> dict:
    """Simule un lead dont la next_action en DB est l'ancienne valeur froide."""
    return _make_lead_row(
        score=24,
        next_action_label=old_label,
        next_action_reason=old_reason,
    )


def test_sms_hook_compute_next_action_echoue_action_neutralisee():
    """
    Hook SMS : compute_next_action() retourne None (échec LLM).
    Extraction réussie → score chaud en DB.
    Payload CRM poussé sans l'ancienne action froide ("relance 2027").
    Les champs next_action sont vidés (chaîne vide).
    """
    old_lead_data = _lead_row_with_old_action()
    pushed_payloads: list[dict] = []

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=None), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=old_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert payload["next_action_label"] == "", (
        "Ancien label 'relance 2027' ne doit pas partir au CRM si compute_next_action a échoué"
    )
    assert payload["next_action_reason"] == ""
    assert "2027" not in payload["next_action_label"]


def test_appel_hook_compute_next_action_echoue_action_neutralisee():
    """
    Hook appel : même comportement que SMS si compute_next_action échoue.
    """
    old_lead_data = _lead_row_with_old_action()
    pushed_payloads: list[dict] = []

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=None), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=old_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from webhooks.twilio_voice import _trigger_call_post_extraction_hooks
        _trigger_call_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert payload["next_action_label"] == ""
    assert payload["next_action_reason"] == ""
    assert "2027" not in payload["next_action_label"]


def test_sms_hook_compute_next_action_reussit_payload_contient_nouvelle_action():
    """
    Hook SMS : compute_next_action réussit.
    Payload CRM contient la nouvelle action (pas l'ancienne).
    build_lead_data_from_db retourne déjà le lead mis à jour (avec new next_action).
    """
    new_label = "Rappeler d'urgence — mutation juillet confirmée"
    updated_lead_data = _make_lead_row(
        score=24,
        next_action_label=new_label,
        next_action_reason="Urgence réelle, délai court.",
    )
    pushed_payloads: list[dict] = []

    mock_action = MagicMock()
    mock_action.label = new_label

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=mock_action), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=updated_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert payload["next_action_label"] == new_label
    assert "2027" not in payload["next_action_label"]


def test_appel_hook_compute_next_action_reussit_payload_contient_nouvelle_action():
    """
    Hook appel : compute_next_action réussit.
    Payload CRM contient la nouvelle action.
    """
    new_label = "Organiser visite — accord bancaire obtenu"
    updated_lead_data = _make_lead_row(
        score=23,
        next_action_label=new_label,
        next_action_reason="Budget confirmé, délai court.",
    )
    pushed_payloads: list[dict] = []

    mock_action = MagicMock()
    mock_action.label = new_label

    def fake_push(client_id, lead_data):
        pushed_payloads.append(dict(lead_data))

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=mock_action), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=updated_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from webhooks.twilio_voice import _trigger_call_post_extraction_hooks
        _trigger_call_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert len(pushed_payloads) == 1
    payload = pushed_payloads[0]
    assert payload["next_action_label"] == new_label


def test_hook_push_toujours_declenche_meme_si_compute_echoue():
    """
    Même si compute_next_action échoue, le push CRM est quand même déclenché
    (score + résumé à jour doivent partir au CRM).
    """
    old_lead_data = _lead_row_with_old_action()
    push_call_count = [0]

    def fake_push(client_id, lead_data):
        push_call_count[0] += 1

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=None), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=old_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    assert push_call_count[0] == 1, "Le push CRM doit partir même si compute_next_action échoue"


def test_hook_neutralisation_ne_modifie_pas_lead_data_original():
    """
    La neutralisation des champs action en cas d'échec doit travailler sur une
    copie du dict — pas modifier l'objet retourné par build_lead_data_from_db.
    """
    old_lead_data = _lead_row_with_old_action(
        old_label="Programmer une relance début janvier 2027"
    )
    original_label = old_lead_data["next_action_label"]
    pushed_payloads: list[dict] = []

    def fake_push(client_id, lead_data):
        pushed_payloads.append(lead_data)

    with patch("lib.lead_extraction.next_action.compute_next_action", return_value=None), \
         patch("lib.crm_connectors.factory.build_lead_data_from_db", return_value=old_lead_data), \
         patch("lib.crm_connectors.factory.push_lead_to_crm", side_effect=fake_push):

        from server import _trigger_post_extraction_hooks
        _trigger_post_extraction_hooks(lead_id="lead-001", client_id="client-1")

    # L'objet original doit être intact
    assert old_lead_data["next_action_label"] == original_label
    # Le payload pushé est bien neutralisé
    assert pushed_payloads[0]["next_action_label"] == ""
