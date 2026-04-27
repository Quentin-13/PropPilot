"""
Tests unitaires — LeadQualifierAgent.
DÉSACTIVÉ dans le sprint cleanup-pivot : LeadQualifierAgent supprimé (Léa).
La logique de scoring est migrée dans lib/lead_extraction/.
"""
import pytest

pytestmark = pytest.mark.skip(reason="LeadQualifierAgent supprimé — sprint cleanup-pivot")


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch, request):
    """Utilise une DB temporaire pour les tests. Ignoré pour les tests marqués 'no_db'."""
    if request.node.get_closest_marker("no_db"):
        yield
        return

    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("AGENCY_CLIENT_ID", "test_client")
    monkeypatch.setenv("AGENCY_TIER", "Starter")
    monkeypatch.setenv("AGENCY_NAME", "Test Agence")
    monkeypatch.setenv("MOCK_MODE", "always")

    # Reset cache settings
    from config.settings import get_settings
    get_settings.cache_clear()

    init_database()
    yield

    get_settings.cache_clear()


def test_handle_new_lead_creates_lead():
    """Un nouveau lead doit être créé en base."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    result = agent.handle_new_lead(
        telephone="+33600000001",
        message_initial="Je veux acheter un appartement",
        prenom="Test",
    )

    assert result["status"] == "new_lead"
    assert result["lead_id"] is not None
    assert result["message"] != ""
    assert "Léa" in result["message"] or "MOCK" in result["message"] or "Bonjour" in result["message"]


def test_handle_new_lead_with_prenom():
    """Message de bienvenue doit inclure le prénom."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    result = agent.handle_new_lead(
        telephone="+33600000002",
        message_initial="Bonjour",
        prenom="Marie",
    )

    assert result["status"] == "new_lead"
    assert "Marie" in result["message"]


def test_handle_new_lead_limit_reached(monkeypatch):
    """Doit bloquer si la limite de leads est atteinte."""
    # Simuler usage au max
    def mock_check_and_consume(*args, **kwargs):
        return {
            "allowed": False,
            "message": "Limite atteinte",
            "remaining": 0,
            "upgrade_url": "",
        }

    monkeypatch.setattr("agents.lead_qualifier.check_and_consume", mock_check_and_consume)

    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")
    result = agent.handle_new_lead(
        telephone="+33600000003",
        message_initial="Test",
    )

    assert result["status"] == "limit_reached"
    assert result["lead_id"] is None


def test_handle_incoming_message_continues_qualification():
    """Le message entrant continue la qualification."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    # Créer d'abord le lead
    new_result = agent.handle_new_lead(
        telephone="+33600000004",
        message_initial="Bonjour",
    )
    lead_id = new_result["lead_id"]

    # Réponse au premier message
    result = agent.handle_incoming_message(
        lead_id=lead_id,
        message="Je veux acheter un appartement 3 pièces à Lyon",
    )

    assert result["message"] != ""
    assert result["next_action"] in ("continue", "rdv", "nurturing_14j", "nurturing_30j")


def test_scoring_routes_hot_lead():
    """Score ≥ 7 → statut qualifié."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 8,
        "score_urgence": 4,
        "score_budget": 2,
        "score_motivation": 2,
        "projet": "achat",
        "localisation": "Lyon 6e",
        "budget": "400 000€",
        "timeline": "3 mois",
        "financement": "Accord bancaire",
        "motivation": "Mutation",
        "prochaine_action": "rdv",
        "resume": "Lead chaud, mutation professionnelle.",
    }

    from memory.lead_repository import create_lead, get_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Pierre", telephone="+33600000005")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 8
    assert result_lead.statut == LeadStatus.QUALIFIE
    assert result_lead.nurturing_sequence is None


def test_scoring_routes_warm_lead():
    """Score 4-6 → nurturing 14j."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 5,
        "score_urgence": 2,
        "score_budget": 1,
        "score_motivation": 2,
        "projet": "achat",
        "localisation": "Paris",
        "budget": "250 000€",
        "timeline": "6-12 mois",
        "financement": "Pas encore",
        "motivation": "Achat résidence principale",
        "prochaine_action": "nurturing_14j",
        "resume": "Lead tiède.",
    }

    from memory.lead_repository import create_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Julie", telephone="+33600000006")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 5
    assert result_lead.statut == LeadStatus.NURTURING
    assert result_lead.nurturing_sequence is not None
    assert result_lead.prochain_followup is not None


def test_scoring_routes_cold_lead():
    """Score < 4 → nurturing 30j avec séquence lead_froid."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    mock_scoring = {
        "score_total": 2,
        "score_urgence": 1,
        "score_budget": 0,
        "score_motivation": 1,
        "projet": "inconnu",
        "localisation": None,
        "budget": None,
        "timeline": "Pas décidé",
        "financement": "Inconnu",
        "motivation": "Curiosité",
        "prochaine_action": "nurturing_30j",
        "resume": "Lead froid.",
    }

    from memory.lead_repository import create_lead
    from memory.models import Lead

    lead = Lead(client_id="test_client", prenom="Marc", telephone="+33600000007")
    lead = create_lead(lead)

    result_lead = agent._apply_score_and_route(lead, mock_scoring)

    assert result_lead.score == 2
    assert result_lead.statut == LeadStatus.NURTURING
    assert result_lead.nurturing_sequence == NurturingSequence.LEAD_FROID


# ─────────────────────────────────────────────
# Tests anti-dérive comportementale (bugs Léa)
# ─────────────────────────────────────────────

@pytest.mark.no_db
def test_system_prompt_no_property_suggestion_rule():
    """Le system prompt doit interdire explicitement de proposer des biens."""
    from config.prompts import LEAD_QUALIFIER_SYSTEM
    prompt = LEAD_QUALIFIER_SYSTEM.lower()
    assert "catalogue" in prompt, "La règle 'pas d'accès au catalogue' doit être dans le prompt"
    assert "négociateur" in prompt, "La règle de renvoi vers le négociateur doit être dans le prompt"


@pytest.mark.no_db
def test_system_prompt_one_sms_per_turn_rule():
    """Le system prompt doit imposer un seul SMS par tour."""
    from config.prompts import LEAD_QUALIFIER_SYSTEM
    prompt = LEAD_QUALIFIER_SYSTEM.lower()
    assert "un seul" in prompt or "1 sms" in prompt or "un seul message" in prompt or "un seul sms" in prompt


@pytest.mark.no_db
def test_system_prompt_anti_hallucination_rule():
    """Le system prompt doit contenir la règle anti-hallucination."""
    from config.prompts import LEAD_QUALIFIER_SYSTEM
    prompt = LEAD_QUALIFIER_SYSTEM.lower()
    assert "hallucination" in prompt or "invente" in prompt or "n'invente" in prompt or "vérifier" in prompt


@pytest.mark.no_db
def test_system_prompt_rdv_after_7_questions():
    """Le system prompt doit interdire le RDV avant les 7 questions."""
    from config.prompts import LEAD_QUALIFIER_SYSTEM
    prompt = LEAD_QUALIFIER_SYSTEM.lower()
    assert "7 questions" in prompt or "sept questions" in prompt or "après les 7" in prompt


@pytest.mark.no_db
def test_mock_responses_no_property_hallucination():
    """Les réponses mock ne doivent jamais contenir de biens inventés."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    # Phrases caractéristiques d'une hallucination de biens
    property_hallucination_patterns = [
        "j'ai repéré",
        "j'ai trouvé",
        "j'ai sélectionné",
        "j'ai un bien",
        "appartement disponible",
        "maison disponible",
        "je vous propose ce bien",
        "référence ",
        "annonce n°",
    ]

    for i in range(7):
        response = agent._mock_qualification_response(i)
        response_lower = response.lower()
        for pattern in property_hallucination_patterns:
            assert pattern not in response_lower, (
                f"Réponse mock {i} contient une hallucination de bien ('{pattern}'): {response}"
            )


@pytest.mark.no_db
def test_mock_qualification_sequence_order():
    """Les réponses mock doivent suivre la séquence des 7 questions dans l'ordre."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    # Mots-clés attendus dans l'ordre des questions
    sequence_keywords = [
        # Q1 — après 0 échange user : question sur localisation ou type de projet
        ["ville", "secteur", "localisation", "géographique", "vendre", "achat", "projet"],
        # Q2 — budget
        ["budget", "prix", "loyer", "vendre"],
        # Q3 — timeline
        ["délai", "temps", "conclure", "combien de temps", "contrainte"],
        # Q4 — situation actuelle
        ["propriétaire", "compromis", "situation"],
        # Q5 — financement
        ["financement", "accord", "apport", "banque"],
        # Q6 — motivation
        ["raison", "particulière", "maintenant", "pourquoi", "information"],
        # Q7 — conclusion
        ["accompagner", "échange", "rappelle", "recontacter", "disponible"],
    ]

    for i, keywords in enumerate(sequence_keywords):
        response = agent._mock_qualification_response(i).lower()
        # Au moins un mot-clé doit être présent
        assert any(kw in response for kw in keywords), (
            f"Réponse mock {i} ne correspond pas à la Q{i+1} attendue. "
            f"Mots-clés attendus: {keywords}. Réponse: {response}"
        )


def test_no_rdv_before_qualification_complete():
    """Léa ne doit pas proposer de RDV avant que la qualification soit terminée."""
    agent = LeadQualifierAgent(client_id="test_client", tier="Starter")

    # Simuler une conversation courte (2 échanges seulement)
    new_result = agent.handle_new_lead(
        telephone="+33600000010",
        message_initial="Je cherche un appartement",
        prenom="Jérôme",
    )
    lead_id = new_result["lead_id"]

    # Répondre à Q4 (timeline) comme dans le bug réel
    result = agent.handle_incoming_message(
        lead_id=lead_id,
        message="Le plus rapidement possible",
    )

    # La qualification ne doit pas être terminée (< 7 échanges)
    assert result["next_action"] == "continue", (
        f"Léa a terminé la qualification prématurément : next_action={result['next_action']}"
    )
    assert result["score"] is None, "Un score ne doit pas être attribué avant les 7 questions"


@pytest.mark.no_db
def test_llm_receives_anti_hallucination_system_prompt():
    """Vérifie que le client Anthropic reçoit le system prompt avec les règles anti-dérive."""
    from unittest.mock import MagicMock, patch
    from config.prompts import get_lead_qualifier_system

    system = get_lead_qualifier_system("Test Agence")

    assert len(system) == 1
    prompt_text = system[0]["text"]

    # Règles critiques doivent être présentes
    assert "ZÉRO BIEN SPÉCIFIQUE" in prompt_text or "catalogue" in prompt_text.lower()
    assert "UN SEUL SMS" in prompt_text or "un seul message" in prompt_text.lower() or "un seul sms" in prompt_text.lower()
    assert "ZÉRO HALLUCINATION" in prompt_text or "n'invente" in prompt_text.lower() or "hallucination" in prompt_text.lower()
    assert "7 questions" in prompt_text or "SÉQUENCE STRICTE" in prompt_text
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ─────────────────────────────────────────────
# Tests non-régression bugs 3 critiques (démo jeudi)
# ─────────────────────────────────────────────

@pytest.mark.no_db
def test_bug1_agency_name_propagated_to_welcome_message():
    """Bug 1 — Le nom d'agence réel doit apparaître dans le message de bienvenue."""
    agent = LeadQualifierAgent(
        client_id="test_client",
        tier="Starter",
        agency_name="Guy Hoquet Saint-Étienne Nord",
    )
    msg = agent._generate_welcome_message(prenom="Jérôme")
    assert "Guy Hoquet Saint-Étienne Nord" in msg, (
        f"Le nom d'agence correct n'apparaît pas dans le message de bienvenue : {msg}"
    )
    assert "Mon Agence PropPilot" not in msg, (
        "Le nom d'agence par défaut ne doit PAS apparaître quand un nom réel est fourni"
    )


@pytest.mark.no_db
def test_bug1_agency_name_in_qualification_system_prompt():
    """Bug 1 — Le system prompt doit contenir le nom d'agence réel."""
    from config.prompts import get_lead_qualifier_system
    system = get_lead_qualifier_system("Guy Hoquet Saint-Étienne Nord")
    prompt_text = system[0]["text"]
    assert "Guy Hoquet Saint-Étienne Nord" in prompt_text
    assert "Mon Agence PropPilot" not in prompt_text


@pytest.mark.no_db
def test_bug2_no_extra_instruction_in_qualification():
    """Bug 2 — L'extra_instruction ne doit plus être injectée dans le LLM à Q6."""
    from unittest.mock import MagicMock, patch

    captured_calls = []

    def mock_create(**kwargs):
        captured_calls.append(kwargs)
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Question suivante ?")]
        mock_resp.usage.input_tokens = 100
        mock_resp.usage.output_tokens = 10
        return mock_resp

    agent = LeadQualifierAgent(client_id="test_client", tier="Starter", agency_name="Test Agence")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = mock_create
    agent._anthropic_client = mock_client

    # Simuler 6 messages utilisateur (proche de la fin — c'est là que l'extra_instruction était injectée)
    history_6_user = []
    for i in range(6):
        history_6_user.append({"role": "user", "content": f"Réponse {i+1}"})
        history_6_user.append({"role": "assistant", "content": f"Question {i+2} ?"})

    with patch("memory.cost_logger.log_api_action"):
        agent._generate_qualification_response(
            history=history_6_user,
            agence_nom="Test Agence",
            lead=MagicMock(projet=MagicMock(value="achat")),
        )

    assert len(captured_calls) == 1
    messages_sent = captured_calls[0]["messages"]
    # Aucun message supplémentaire ne doit avoir été injecté
    assert messages_sent == history_6_user, (
        "L'extra_instruction ne doit plus être ajoutée en tant que message utilisateur"
    )


@pytest.mark.no_db
def test_bug3_rdv_confirmation_keywords_detected():
    """Bug 3 — Les mots-clés de confirmation de RDV doivent être reconnus."""
    from orchestrator import _SPECIFIC_SLOT_KEYWORDS, _GENERAL_ACCEPTANCE_KEYWORDS

    all_keywords = _SPECIFIC_SLOT_KEYWORDS + _GENERAL_ACCEPTANCE_KEYWORDS

    confirmation_phrases = [
        "jeudi ça me va",
        "mardi matin",
        "vendredi après-midi",
        "d'accord",
        "parfait",
        "ça convient",
    ]

    for phrase in confirmation_phrases:
        phrase_lower = phrase.lower()
        assert any(kw in phrase_lower for kw in all_keywords), (
            f"La phrase '{phrase}' devrait être reconnue comme confirmation de RDV"
        )


@pytest.mark.no_db
def test_bug3_rdv_loop_routing():
    """Bug 3 — Un lead QUALIFIÉ doit router vers handle_rdv_confirmation, pas continue_qualification."""
    from orchestrator import route_after_lead_check, AgencyState

    # Simuler l'état après qu'un lead QUALIFIÉ envoie un nouveau message
    state_qualifie = AgencyState(
        client_id="test",
        tier="Starter",
        agency_name="Test Agence",
        lead_id="lead-123",
        lead_status="qualifie",
        telephone="+33600000001",
        prenom="Jérôme",
        nom="",
        email="",
        canal="sms",
        source_data={},
        message_entrant="Jeudi ça me va",
        score=8,
        next_action="rdv",
        qualification_complete=True,
        message_sortant="",
        messages_log=[],
        status="existing_lead",
        error=None,
    )

    route = route_after_lead_check(state_qualifie)
    assert route == "handle_rdv_confirmation", (
        f"Un lead QUALIFIÉ doit router vers 'handle_rdv_confirmation', pas '{route}'"
    )


@pytest.mark.no_db
def test_bug3_rdv_booke_routing():
    """Bug 3 — Un lead RDV_BOOKÉ doit aussi router vers handle_rdv_confirmation."""
    from orchestrator import route_after_lead_check, AgencyState

    state_rdv_booke = AgencyState(
        client_id="test",
        tier="Starter",
        agency_name="Test Agence",
        lead_id="lead-456",
        lead_status="rdv_booke",
        telephone="+33600000002",
        prenom="Marie",
        nom="",
        email="",
        canal="sms",
        source_data={},
        message_entrant="À jeudi !",
        score=9,
        next_action="rdv",
        qualification_complete=True,
        message_sortant="",
        messages_log=[],
        status="existing_lead",
        error=None,
    )

    route = route_after_lead_check(state_rdv_booke)
    assert route == "handle_rdv_confirmation", (
        f"Un lead RDV_BOOKÉ doit router vers 'handle_rdv_confirmation', pas '{route}'"
    )
