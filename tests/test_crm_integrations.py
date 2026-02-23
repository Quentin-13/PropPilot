"""
Tests — Intégrations CRM PropPilot.
Tous les connecteurs tournent en mock mode (api_key vide ou "test_xxx").
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, timedelta

from memory.database import init_database
from memory.models import Lead, ProjetType, Canal


CLIENT_ID = "test_crm_client"
TIER = "Pro"


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_crm.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AGENCY_TIER", TIER)
    monkeypatch.setenv("MOCK_MODE", "always")
    from config.settings import get_settings
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


# ─── Tests base.py ─────────────────────────────────────────────────────────────

def test_normalize_project_type():
    from integrations.crm.hektor import HektorConnector
    c = HektorConnector(api_key="", agency_id="demo")
    assert c.normalize_project_type("achat") == ProjetType.ACHAT
    assert c.normalize_project_type("buy") == ProjetType.ACHAT
    assert c.normalize_project_type("vente") == ProjetType.VENTE
    assert c.normalize_project_type("sell") == ProjetType.VENTE
    assert c.normalize_project_type("sale") == ProjetType.VENTE
    assert c.normalize_project_type("location") == ProjetType.LOCATION
    assert c.normalize_project_type("rent") == ProjetType.LOCATION
    assert c.normalize_project_type("xyz") == ProjetType.INCONNU


def test_format_budget():
    from integrations.crm.hektor import HektorConnector
    c = HektorConnector(api_key="", agency_id="demo")
    result = c.format_budget(350000)
    assert "350" in result and "000" in result  # "350 000€"
    assert c.format_budget(None) == ""
    assert c.format_budget("") == ""
    assert c.format_budget(0) == ""


def test_inject_and_extract_crm_id():
    from integrations.crm.hektor import HektorConnector
    c = HektorConnector(api_key="", agency_id="demo")
    notes = c.inject_crm_id("", "ABC123")
    assert "[CRM:hektor:ABC123]" in notes
    extracted = c.extract_crm_id(notes)
    assert extracted == "ABC123"


def test_inject_crm_id_appends_to_existing():
    from integrations.crm.hektor import HektorConnector
    c = HektorConnector(api_key="", agency_id="demo")
    notes = c.inject_crm_id("Note existante", "XYZ999")
    assert "Note existante" in notes
    assert "[CRM:hektor:XYZ999]" in notes


def test_extract_crm_id_missing():
    from integrations.crm.hektor import HektorConnector
    c = HektorConnector(api_key="", agency_id="demo")
    assert c.extract_crm_id(None) is None
    assert c.extract_crm_id("notes sans tag") is None


# ─── Tests Hektor ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hektor_test_connection_mock():
    from integrations.crm.hektor import HektorConnector
    connector = HektorConnector(api_key="", agency_id="demo")
    result = await connector.test_connection()
    assert result["success"] is True
    assert "agency_name" in result


@pytest.mark.asyncio
async def test_hektor_get_new_leads_mock():
    from integrations.crm.hektor import HektorConnector
    connector = HektorConnector(api_key="", agency_id="demo")
    since = datetime.now() - timedelta(hours=24)
    leads = await connector.get_new_leads(since)
    assert isinstance(leads, list)
    assert len(leads) >= 1
    lead = leads[0]
    assert isinstance(lead, Lead)
    assert lead.telephone
    assert lead.prenom


@pytest.mark.asyncio
async def test_hektor_update_lead_status_mock():
    from integrations.crm.hektor import HektorConnector
    connector = HektorConnector(api_key="", agency_id="demo")
    result = await connector.update_lead_status("hektor_12345", "qualified", "Score 8/10")
    assert result is True


@pytest.mark.asyncio
async def test_hektor_create_appointment_mock():
    from integrations.crm.hektor import HektorConnector
    connector = HektorConnector(api_key="", agency_id="demo")
    rdv_dt = datetime.now() + timedelta(days=2)
    result = await connector.create_appointment("hektor_12345", rdv_dt, "Agent IA")
    assert result is True


@pytest.mark.asyncio
async def test_hektor_push_listing_mock():
    from integrations.crm.hektor import HektorConnector
    connector = HektorConnector(api_key="", agency_id="demo")
    listing = {"titre": "T3 Lyon", "prix": 320000, "surface": 68, "adresse": "Lyon 6ème"}
    result = await connector.push_listing(listing)
    assert result  # non-empty string ID


def test_hektor_parse_webhook_valid():
    from integrations.crm.hektor import HektorConnector
    payload = {
        "event": "contact.created",
        "contact": {
            "id": "H999",
            "firstname": "Marie",
            "lastname": "Dupont",
            "phone": "+33612345678",
            "email": "marie@example.com",
            "project": "buy",
            "location": "Nantes",
            "budget": 280000,
        },
    }
    lead = HektorConnector.parse_webhook_payload(payload, agency_id=CLIENT_ID)
    assert lead is not None
    assert lead.prenom == "Marie"
    assert lead.telephone == "+33612345678"
    assert lead.projet == ProjetType.ACHAT


def test_hektor_parse_webhook_wrong_event():
    from integrations.crm.hektor import HektorConnector
    payload = {"event": "property.updated", "contact": {"phone": "+33600000001"}}
    lead = HektorConnector.parse_webhook_payload(payload, agency_id=CLIENT_ID)
    assert lead is None


def test_hektor_parse_webhook_no_phone():
    from integrations.crm.hektor import HektorConnector
    payload = {"event": "contact.created", "contact": {"firstname": "X"}}
    lead = HektorConnector.parse_webhook_payload(payload, agency_id=CLIENT_ID)
    assert lead is None


# ─── Tests Apimo ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apimo_test_connection_mock():
    from integrations.crm.apimo import ApimoCRMConnector
    connector = ApimoCRMConnector(api_key="", agency_id="demo")
    result = await connector.test_connection()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_apimo_get_new_leads_mock():
    from integrations.crm.apimo import ApimoCRMConnector
    connector = ApimoCRMConnector(api_key="", agency_id="demo")
    since = datetime.now() - timedelta(hours=24)
    leads = await connector.get_new_leads(since)
    assert isinstance(leads, list)


@pytest.mark.asyncio
async def test_apimo_update_lead_status_mock():
    from integrations.crm.apimo import ApimoCRMConnector
    connector = ApimoCRMConnector(api_key="", agency_id="demo")
    result = await connector.update_lead_status("apimo_123", "rdv_booked", "Qualification OK")
    assert result is True


# ─── Tests Prospeneo ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prospeneo_test_connection_mock():
    from integrations.crm.prospeneo import ProspeneoConnector
    connector = ProspeneoConnector(api_key="", agency_id="demo")
    result = await connector.test_connection()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_prospeneo_get_new_leads_mock():
    from integrations.crm.prospeneo import ProspeneoConnector
    connector = ProspeneoConnector(api_key="", agency_id="demo")
    since = datetime.now() - timedelta(hours=24)
    leads = await connector.get_new_leads(since)
    assert isinstance(leads, list)
    if leads:
        assert isinstance(leads[0], Lead)


@pytest.mark.asyncio
async def test_prospeneo_push_listing_mock():
    from integrations.crm.prospeneo import ProspeneoConnector
    connector = ProspeneoConnector(api_key="", agency_id="demo")
    listing = {"titre": "Bel appartement T3", "prix": 320000, "surface": 72, "ville": "Montpellier"}
    result = await connector.push_listing(listing)
    assert result  # non-empty listing ID string


# ─── Tests Whise ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_whise_test_connection_mock():
    from integrations.crm.whise import WhiseConnector
    connector = WhiseConnector(api_key="", agency_id="demo")
    result = await connector.test_connection()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_whise_get_new_leads_mock():
    from integrations.crm.whise import WhiseConnector
    connector = WhiseConnector(api_key="", agency_id="demo")
    since = datetime.now() - timedelta(hours=24)
    leads = await connector.get_new_leads(since)
    assert isinstance(leads, list)


@pytest.mark.asyncio
async def test_whise_create_appointment_mock():
    from integrations.crm.whise import WhiseConnector
    connector = WhiseConnector(api_key="", agency_id="demo")
    rdv_dt = datetime.now() + timedelta(days=3)
    result = await connector.create_appointment("whise_456", rdv_dt, "Agent IA")
    assert result is True


# ─── Tests Adaptimmo ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adaptimmo_test_connection_mock():
    from integrations.crm.adaptimmo import AdaptimmoConnector
    connector = AdaptimmoConnector(api_key="", agency_id="demo")
    result = await connector.test_connection()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_adaptimmo_get_new_leads_mock():
    from integrations.crm.adaptimmo import AdaptimmoConnector
    connector = AdaptimmoConnector(api_key="", agency_id="demo")
    since = datetime.now() - timedelta(hours=24)
    leads = await connector.get_new_leads(since)
    assert isinstance(leads, list)


@pytest.mark.asyncio
async def test_adaptimmo_push_listing_mock():
    from integrations.crm.adaptimmo import AdaptimmoConnector
    connector = AdaptimmoConnector(api_key="", agency_id="demo")
    listing = {"titre": "Maison 4 pièces", "prix": 450000, "surface": 110, "ville": "Toulouse"}
    result = await connector.push_listing(listing)
    assert result  # non-empty listing ID string


# ─── Tests CSV Import ──────────────────────────────────────────────────────────

def test_csv_detect_format_generic():
    from integrations.crm.csv_import import detect_crm_format
    headers = ["prenom", "nom", "telephone", "email"]
    fmt = detect_crm_format(headers)
    assert fmt in ("generic", "hektor", "apimo", "prospeneo")


def test_csv_detect_format_apimo():
    from integrations.crm.csv_import import detect_crm_format
    fmt = detect_crm_format(["contact_firstname", "contact_phone", "contact_email"])
    assert fmt == "apimo"


def test_csv_parse_generic():
    from integrations.crm.csv_import import parse_csv_leads
    csv_content = "prenom,nom,telephone,email,projet,ville,budget\n"
    csv_content += "Alice,Martin,0601020304,alice@test.com,achat,Paris,400000\n"
    csv_content += "Bob,Durand,0702030405,bob@test.com,location,Lyon,1200\n"
    leads, count, errors = parse_csv_leads(csv_content, CLIENT_ID, "test.csv")
    assert count == 2
    assert len(leads) == 2
    assert leads[0].prenom == "Alice"
    assert leads[0].telephone == "+33601020304"
    assert leads[1].prenom == "Bob"


def test_csv_parse_missing_phone_skipped():
    from integrations.crm.csv_import import parse_csv_leads
    csv_content = "prenom,nom,telephone,email\n"
    csv_content += "Alice,Martin,,alice@test.com\n"  # pas de téléphone
    csv_content += "Bob,Durand,0702030405,bob@test.com\n"
    leads, count, errors = parse_csv_leads(csv_content, CLIENT_ID, "test.csv")
    assert count == 1
    assert leads[0].prenom == "Bob"
    assert len(errors) == 1


def test_csv_generate_sample_generic():
    from integrations.crm.csv_import import generate_sample_csv
    sample = generate_sample_csv("generic")
    assert len(sample) > 20
    # Sample contient des colonnes reconnues
    sample_lower = sample.lower()
    assert any(k in sample_lower for k in ["nom", "telephone", "email", "prénom"])


def test_csv_generate_sample_hektor():
    from integrations.crm.csv_import import generate_sample_csv
    sample = generate_sample_csv("hektor")
    assert "Téléphone" in sample or "téléphone" in sample.lower()


# ─── Tests Repository CRM ──────────────────────────────────────────────────────

def test_crm_repository_save_and_get():
    from integrations.crm.repository import save_crm_connection, get_crm_connection
    save_crm_connection(
        client_id=CLIENT_ID,
        crm_type="hektor",
        api_key="test_key_123",
        agency_id_crm="agence_456",
    )
    conn = get_crm_connection(CLIENT_ID, "hektor")
    assert conn is not None
    assert conn["crm_type"] == "hektor"
    assert conn["api_key"] == "test_key_123"
    assert conn["agency_id_crm"] == "agence_456"


def test_crm_repository_get_active_connections():
    from integrations.crm.repository import save_crm_connection, get_all_active_connections
    save_crm_connection(CLIENT_ID, "hektor", "key1", "ag1")
    save_crm_connection(CLIENT_ID, "apimo", "key2", "ag2")
    connections = get_all_active_connections()
    client_connections = [c for c in connections if c["client_id"] == CLIENT_ID]
    assert len(client_connections) == 2


def test_crm_repository_update_last_sync():
    from integrations.crm.repository import save_crm_connection, update_last_sync, get_crm_connection
    save_crm_connection(CLIENT_ID, "prospeneo", "key3", "ag3")
    update_last_sync(CLIENT_ID, "prospeneo")
    conn = get_crm_connection(CLIENT_ID, "prospeneo")
    assert conn is not None
    assert conn.get("last_sync") is not None


def test_crm_repository_disable():
    from integrations.crm.repository import save_crm_connection, disable_crm_connection, get_crm_connection
    save_crm_connection(CLIENT_ID, "whise", "key4", "ag4")
    # Vérifier qu'elle existe
    assert get_crm_connection(CLIENT_ID, "whise") is not None
    # Désactiver
    disable_crm_connection(CLIENT_ID, "whise")
    # get_crm_connection filtre sur enabled=1 → None après désactivation
    assert get_crm_connection(CLIENT_ID, "whise") is None


# ─── Tests Conflict Resolver ───────────────────────────────────────────────────

def test_resolve_new_lead_no_duplicate():
    from integrations.sync.conflict_resolver import resolve
    lead = Lead(
        client_id=CLIENT_ID,
        prenom="Nouveau",
        nom="Lead",
        telephone="+33699111222",
        email="nouveau@test.com",
        projet=ProjetType.ACHAT,
    )
    final, is_dup = resolve(lead)
    assert is_dup is False


def test_resolve_duplicate_by_phone():
    from integrations.sync.conflict_resolver import resolve
    from memory.lead_repository import create_lead
    # Créer un lead existant
    existing = Lead(
        client_id=CLIENT_ID,
        prenom="Existant",
        telephone="+33699333444",
        projet=ProjetType.ACHAT,
    )
    create_lead(existing)

    # Résoudre un lead entrant avec le même téléphone
    incoming = Lead(
        client_id=CLIENT_ID,
        prenom="Nouveau",
        telephone="+33699333444",
        email="enrichi@test.com",
        projet=ProjetType.ACHAT,
    )
    final, is_dup = resolve(incoming)
    assert is_dup is True
    # Le lead final doit avoir l'email enrichi
    assert final.email == "enrichi@test.com"


def test_merge_leads_enrichment():
    from integrations.sync.conflict_resolver import merge_leads
    from memory.lead_repository import create_lead
    existing = Lead(
        client_id=CLIENT_ID,
        prenom="Pierre",
        telephone="+33699555666",
        projet=ProjetType.ACHAT,
    )
    create_lead(existing)

    incoming = Lead(
        client_id=CLIENT_ID,
        telephone="+33699555666",
        email="pierre@example.com",
        localisation="Marseille",
        budget="500000",
        notes_agent="[Hektor] lead enrichi",
        projet=ProjetType.ACHAT,
    )
    merged = merge_leads(existing, incoming)
    assert merged.email == "pierre@example.com"
    assert merged.localisation == "Marseille"
    assert merged.budget == "500000"
    assert "Hektor" in (merged.notes_agent or "")


def test_duplicate_stats():
    from integrations.sync.conflict_resolver import get_duplicate_stats
    from memory.lead_repository import create_lead
    # Créer 2 leads avec le même téléphone
    for _ in range(2):
        create_lead(Lead(client_id=CLIENT_ID, telephone="+33611223344", projet=ProjetType.ACHAT))
    stats = get_duplicate_stats(CLIENT_ID)
    assert "phone_duplicates" in stats
    assert stats["phone_duplicates"] >= 1


# ─── Tests Scheduler ───────────────────────────────────────────────────────────

def test_get_connector_factory():
    from integrations.sync.scheduler import get_connector
    from integrations.crm.hektor import HektorConnector
    from integrations.crm.apimo import ApimoCRMConnector
    assert isinstance(get_connector("hektor", "test_key", "ag1"), HektorConnector)
    assert isinstance(get_connector("apimo", "", "ag2"), ApimoCRMConnector)


def test_get_connector_unsupported():
    from integrations.sync.scheduler import get_connector
    with pytest.raises(ValueError, match="non supporté"):
        get_connector("inexistant_crm", "", "")


@pytest.mark.asyncio
async def test_sync_client_mock():
    from integrations.crm.repository import save_crm_connection, get_crm_connection
    from integrations.sync.scheduler import sync_client
    save_crm_connection(CLIENT_ID, "hektor", "", "demo")
    conn = get_crm_connection(CLIENT_ID, "hektor")
    assert conn is not None

    report = await sync_client(conn)
    assert "new_leads" in report
    assert "skipped" in report
    assert "errors" in report
    assert report["client_id"] == CLIENT_ID


@pytest.mark.asyncio
async def test_sync_all_clients_empty():
    from integrations.sync.scheduler import sync_all_clients
    # Aucune connexion dans la DB de test → liste vide
    reports = await sync_all_clients()
    assert isinstance(reports, list)


# ─── Tests Portails ────────────────────────────────────────────────────────────

def test_parse_bienici_lead_valid():
    from integrations.portals.bienici import parse_bienici_lead
    payload = {
        "contactRequest": {
            "firstName": "Sophie",
            "lastName": "Lebrun",
            "phone": "0633445566",
            "email": "sophie@example.com",
            "message": "Je suis intéressée",
            "adId": "BIC-789",
        },
        "ad": {"price": 290000, "city": "Rennes", "transactionType": "buy"},
    }
    parsed = parse_bienici_lead(payload)
    assert parsed is not None
    assert parsed["prenom"] == "Sophie"
    assert parsed["telephone"] == "+33633445566"
    assert parsed["projet"] == ProjetType.ACHAT
    assert parsed["localisation"] == "Rennes"


def test_parse_bienici_lead_no_phone():
    from integrations.portals.bienici import parse_bienici_lead
    payload = {"contactRequest": {"firstName": "X"}, "ad": {}}
    assert parse_bienici_lead(payload) is None


def test_parse_logic_immo_lead_valid():
    from integrations.portals.logic_immo import parse_logic_immo_lead
    payload = {
        "lead": {
            "firstName": "Marc",
            "lastName": "Fernandez",
            "phone": "0755443322",
            "email": "marc@example.com",
            "message": "Bonjour",
            "transactionType": "rent",
            "city": "Strasbourg",
            "budget": 900,
        }
    }
    parsed = parse_logic_immo_lead(payload)
    assert parsed is not None
    assert parsed["prenom"] == "Marc"
    assert parsed["telephone"] == "+33755443322"
    assert parsed["projet"] == ProjetType.LOCATION
    assert parsed["localisation"] == "Strasbourg"


def test_parse_logic_immo_lead_no_phone():
    from integrations.portals.logic_immo import parse_logic_immo_lead
    assert parse_logic_immo_lead({}) is None
