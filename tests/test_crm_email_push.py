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


# ─── Tests Resend ─────────────────────────────────────────────────────────────

def _mock_settings_resend(resend_ok=True, sendgrid_ok=False, smtp_ok=False):
    s = MagicMock()
    s.resend_available = resend_ok
    s.sendgrid_available = sendgrid_ok
    s.smtp_available = smtp_ok
    s.resend_api_key = "re_test_key"
    s.resend_from_email = "contact@proppilot.fr"
    s.resend_from_name = "PropPilot"
    return s


def test_resend_prioritaire_si_configure():
    """Resend doit être tenté en premier quand resend_available=True."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = _mock_settings_resend(resend_ok=True, sendgrid_ok=True, smtp_ok=True)

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=s), \
         patch.object(connector, "_send_via_resend", return_value=True) as mock_resend, \
         patch.object(connector, "_send_via_sendgrid") as mock_sg, \
         patch.object(connector, "_send_via_smtp") as mock_smtp:
        result = connector._send("Sujet", "Corps")

    assert result is True
    mock_resend.assert_called_once()
    mock_sg.assert_not_called()
    mock_smtp.assert_not_called()


def test_resend_succes_pas_de_fallback():
    """Si Resend réussit, SendGrid et SMTP ne sont jamais appelés."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = _mock_settings_resend(resend_ok=True, sendgrid_ok=True, smtp_ok=True)

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=s), \
         patch.object(connector, "_send_via_resend", return_value=True), \
         patch.object(connector, "_send_via_sendgrid") as mock_sg, \
         patch.object(connector, "_send_via_smtp") as mock_smtp:
        connector._send("Sujet", "Corps")

    mock_sg.assert_not_called()
    mock_smtp.assert_not_called()


def test_resend_echoue_fallback_sendgrid():
    """Si Resend échoue, SendGrid prend le relais."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = _mock_settings_resend(resend_ok=True, sendgrid_ok=True, smtp_ok=False)

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=s), \
         patch.object(connector, "_send_via_resend", return_value=False), \
         patch.object(connector, "_send_via_sendgrid", return_value=True) as mock_sg:
        result = connector._send("Sujet", "Corps")

    assert result is True
    mock_sg.assert_called_once()


def test_resend_payload_correct():
    """Le payload envoyé à Resend contient from/to/subject/text corrects."""
    import json
    import urllib.request

    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = MagicMock()
    s.resend_api_key = "re_test_key"
    s.resend_from_email = "contact@proppilot.fr"
    s.resend_from_name = "PropPilot"

    captured = {}

    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        captured["auth"] = req.get_header("Authorization")
        return FakeResp()

    with patch("urllib.request.urlopen", fake_urlopen):
        result = connector._send_via_resend("Mon sujet", "Mon corps", s)

    assert result is True
    assert captured["payload"]["from"] == "PropPilot <contact@proppilot.fr>"
    assert captured["payload"]["to"] == ["import@moncrm.fr"]
    assert captured["payload"]["subject"] == "Mon sujet"
    assert captured["payload"]["text"] == "Mon corps"
    assert "html" not in captured["payload"]
    # Clé jamais exposée en clair dans les données loggées (payload uniquement)
    assert captured["auth"] == "Bearer re_test_key"
    assert captured["url"] == "https://api.resend.com/emails"


def test_resend_echec_http_retourne_false():
    """Une HTTPError Resend (ex: 422) retourne False sans lever d'exception."""
    import urllib.error
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = MagicMock()
    s.resend_api_key = "re_test_key"
    s.resend_from_email = "contact@proppilot.fr"
    s.resend_from_name = "PropPilot"

    with patch("urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(None, 422, "Unprocessable", {}, None)):
        result = connector._send_via_resend("Sujet", "Corps", s)

    assert result is False


def test_mock_quand_aucun_transport():
    """Sans Resend/SendGrid/SMTP, le mock renvoie True (démo)."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")
    s = _mock_settings_resend(resend_ok=False, sendgrid_ok=False, smtp_ok=False)

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=s):
        result = connector._send("Sujet", "Corps")

    assert result is True


# ─── Tests SMTP fallback ──────────────────────────────────────────────────────

def test_smtp_fallback_quand_sendgrid_echoue(lead_complet):
    """Si SendGrid échoue, _send_via_smtp est appelé en fallback."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    with patch.object(connector, "_send_via_sendgrid", return_value=False), \
         patch.object(connector, "_send_via_smtp", return_value=True) as mock_smtp, \
         patch("lib.crm_connectors.email_parsing.EmailParsingConnector._send",
               wraps=connector._send):

        # On configure un settings avec sendgrid ET smtp disponibles
        mock_settings = MagicMock()
        mock_settings.sendgrid_available = True
        mock_settings.smtp_available = True

        with patch("lib.crm_connectors.email_parsing.get_settings", return_value=mock_settings):
            result = connector._send("Sujet test", "Corps test")

    assert result is True
    mock_smtp.assert_called_once()


def test_smtp_seul_quand_pas_sendgrid(lead_complet):
    """Sans SendGrid, SMTP seul est utilisé directement."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.sendgrid_available = False
    mock_settings.smtp_available = True

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=mock_settings), \
         patch.object(connector, "_send_via_smtp", return_value=True) as mock_smtp, \
         patch.object(connector, "_send_via_sendgrid") as mock_sg:

        result = connector._send("Sujet test", "Corps test")

    assert result is True
    mock_smtp.assert_called_once()
    mock_sg.assert_not_called()


def test_mock_quand_ni_sendgrid_ni_smtp():
    """Sans aucun transport configuré, le mock renvoie True (mode démo)."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.resend_available = False
    mock_settings.sendgrid_available = False
    mock_settings.smtp_available = False

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=mock_settings):
        result = connector._send("Sujet test", "Corps test")

    assert result is True


def test_smtp_echoue_retourne_false():
    """Si SMTP lève une exception, _send_via_smtp retourne False."""
    import smtplib
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.smtp_host = "smtp.hostinger.com"
    mock_settings.smtp_port = 587
    mock_settings.smtp_user = "contact@proppilot.fr"
    mock_settings.smtp_password = "secret"
    mock_settings.smtp_from_email = "contact@proppilot.fr"
    mock_settings.smtp_from_name = "PropPilot"
    mock_settings.smtp_use_tls = True

    with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("connexion refusée")):
        result = connector._send_via_smtp("Sujet", "Corps", mock_settings)

    assert result is False


def test_smtp_port_465_utilise_smtp_ssl():
    """Port 465 doit utiliser SMTP_SSL, pas SMTP."""
    import smtplib
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.smtp_host = "smtp.hostinger.com"
    mock_settings.smtp_port = 465
    mock_settings.smtp_user = "contact@proppilot.fr"
    mock_settings.smtp_password = "secret"
    mock_settings.smtp_from_email = "contact@proppilot.fr"
    mock_settings.smtp_from_name = "PropPilot"
    mock_settings.smtp_use_tls = True

    mock_server = MagicMock()
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP_SSL", return_value=mock_server) as mock_ssl, \
         patch("smtplib.SMTP") as mock_plain:
        result = connector._send_via_smtp("Sujet", "Corps", mock_settings)

    assert result is True
    mock_ssl.assert_called_once_with("smtp.hostinger.com", 465, timeout=15)
    mock_plain.assert_not_called()
    mock_server.starttls.assert_not_called()


def test_smtp_port_587_utilise_starttls():
    """Port 587 avec smtp_use_tls=True doit utiliser SMTP + starttls."""
    import smtplib
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.smtp_host = "smtp.hostinger.com"
    mock_settings.smtp_port = 587
    mock_settings.smtp_user = "contact@proppilot.fr"
    mock_settings.smtp_password = "secret"
    mock_settings.smtp_from_email = "contact@proppilot.fr"
    mock_settings.smtp_from_name = "PropPilot"
    mock_settings.smtp_use_tls = True

    mock_server = MagicMock()
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_server) as mock_plain, \
         patch("smtplib.SMTP_SSL") as mock_ssl:
        result = connector._send_via_smtp("Sujet", "Corps", mock_settings)

    assert result is True
    mock_plain.assert_called_once_with("smtp.hostinger.com", 587, timeout=15)
    mock_ssl.assert_not_called()
    mock_server.starttls.assert_called_once()


def test_sendgrid_succes_pas_de_smtp(lead_complet):
    """Si SendGrid réussit, SMTP ne doit pas être appelé."""
    connector = EmailParsingConnector(target_email="import@moncrm.fr")

    mock_settings = MagicMock()
    mock_settings.sendgrid_available = True
    mock_settings.smtp_available = True

    with patch("lib.crm_connectors.email_parsing.get_settings", return_value=mock_settings), \
         patch.object(connector, "_send_via_sendgrid", return_value=True) as mock_sg, \
         patch.object(connector, "_send_via_smtp") as mock_smtp:

        result = connector._send("Sujet", "Corps")

    assert result is True
    mock_sg.assert_called_once()
    mock_smtp.assert_not_called()


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
