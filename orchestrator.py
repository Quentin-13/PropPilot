"""
Orchestrateur LangGraph — StateGraph principal.
Gère le flux lead : qualification → scoring → routage → nurturing/RDV/appel voix.
Intègre : LeadQualifier, Nurturing, VoiceCall (leads chauds non joignables).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agents.lead_qualifier import LeadQualifierAgent
from agents.nurturing import NurturingAgent
from config.settings import get_settings
from memory.journey_repository import log_action
from memory.models import Canal, Lead

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# STATE DEFINITION
# ─────────────────────────────────────────────────────────────

class AgencyState(TypedDict):
    """État partagé entre tous les nœuds du graphe."""
    # Contexte client
    client_id: str
    tier: str

    # Infos lead
    lead_id: Optional[str]
    telephone: str
    prenom: str
    nom: str
    email: str
    canal: str              # Canal.value
    source_data: dict

    # Message entrant
    message_entrant: str

    # Résultats qualification
    score: int
    next_action: str        # "continue" | "rdv" | "nurturing_14j" | "nurturing_30j"
    qualification_complete: bool

    # Messages à envoyer
    message_sortant: str
    messages_log: list[str]

    # Statut pipeline
    status: str             # "new" | "qualifying" | "scored" | "routed" | "error"
    error: Optional[str]

    # Appel voix (optionnel)
    voice_call_id: Optional[str]
    voice_call_triggered: bool


def make_initial_state(
    client_id: str,
    telephone: str,
    message: str,
    canal: str = "sms",
    prenom: str = "",
    nom: str = "",
    email: str = "",
    tier: str = "Starter",
    lead_id: Optional[str] = None,
    source_data: Optional[dict] = None,
) -> AgencyState:
    """Crée l'état initial du graphe pour un nouveau message entrant."""
    return AgencyState(
        client_id=client_id,
        tier=tier,
        lead_id=lead_id,
        telephone=telephone,
        prenom=prenom,
        nom=nom,
        email=email,
        canal=canal,
        source_data=source_data or {},
        message_entrant=message,
        score=0,
        next_action="continue",
        qualification_complete=False,
        message_sortant="",
        messages_log=[],
        status="new",
        error=None,
        voice_call_id=None,
        voice_call_triggered=False,
    )


# ─────────────────────────────────────────────────────────────
# NODES
# ─────────────────────────────────────────────────────────────

def node_check_existing_lead(state: AgencyState) -> AgencyState:
    """Vérifie si le lead existe déjà (même numéro de téléphone)."""
    from memory.database import get_connection

    if state["lead_id"]:
        # Lead ID fourni explicitement
        return {**state, "status": "existing_lead"}

    # Recherche par téléphone
    telephone = state["telephone"]
    client_id = state["client_id"]

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM leads WHERE client_id = ? AND telephone = ? ORDER BY created_at DESC LIMIT 1",
            (client_id, telephone),
        ).fetchone()

    if row:
        logger.info(f"Lead existant trouvé : {row['id']}")
        return {**state, "lead_id": row["id"], "status": "existing_lead"}

    return {**state, "status": "new_lead"}


def node_qualify_new_lead(state: AgencyState) -> AgencyState:
    """Crée et envoie le premier message de bienvenue pour un nouveau lead."""
    agent = LeadQualifierAgent(client_id=state["client_id"], tier=state["tier"])
    canal = Canal(state.get("canal", "sms"))

    result = agent.handle_new_lead(
        telephone=state["telephone"],
        message_initial=state["message_entrant"],
        canal=canal,
        prenom=state["prenom"],
        nom=state["nom"],
        email=state["email"],
        source_data=state.get("source_data"),
    )

    if result["status"] == "limit_reached":
        return {
            **state,
            "status": "limit_reached",
            "message_sortant": result.get("usage_message", ""),
            "error": "Limite de leads atteinte ce mois",
        }

    lead_id = result["lead_id"]
    log_action(
        lead_id=lead_id,
        client_id=state["client_id"],
        stage="qualification",
        action_done="new_lead_created",
        action_result=result.get("message", "")[:200],
        next_action="continue_qualification",
        agent_name="lea",
    )

    return {
        **state,
        "lead_id": lead_id,
        "message_sortant": result["message"],
        "status": "qualifying",
        "messages_log": state["messages_log"] + [f"Nouveau lead créé : {lead_id}"],
    }


def node_continue_qualification(state: AgencyState) -> AgencyState:
    """Continue la qualification d'un lead existant."""
    agent = LeadQualifierAgent(client_id=state["client_id"], tier=state["tier"])
    canal = Canal(state.get("canal", "sms"))

    result = agent.handle_incoming_message(
        lead_id=state["lead_id"],
        message=state["message_entrant"],
        canal=canal,
    )

    new_score = result.get("score") or state["score"]
    qualification_complete = result.get("score") is not None

    if state.get("lead_id"):
        log_action(
            lead_id=state["lead_id"],
            client_id=state["client_id"],
            stage="qualification",
            action_done="message_sent",
            action_result=result.get("message", "")[:200],
            next_action=result["next_action"],
            agent_name="lea",
            metadata={"score": new_score, "qualification_complete": qualification_complete},
        )

    return {
        **state,
        "message_sortant": result["message"],
        "score": new_score,
        "next_action": result["next_action"],
        "qualification_complete": qualification_complete,
        "status": "scored" if qualification_complete else "qualifying",
    }


def node_route_lead(state: AgencyState) -> AgencyState:
    """Route le lead selon son score (RDV / nurturing 14j / nurturing 30j)."""
    score = state["score"]
    next_action = state["next_action"]

    log_msg = f"Lead {state['lead_id']} scoré {score}/10 → {next_action}"
    logger.info(log_msg)

    if state.get("lead_id"):
        log_action(
            lead_id=state["lead_id"],
            client_id=state["client_id"],
            stage="routing",
            action_done="lead_scored",
            action_result=f"score={score}/10 next={next_action}",
            next_action=next_action,
            agent_name="orchestrateur",
            metadata={"score": score, "next_action": next_action},
        )

    return {
        **state,
        "status": "routed",
        "messages_log": state["messages_log"] + [log_msg],
    }


def node_trigger_nurturing(state: AgencyState) -> AgencyState:
    """Active la séquence nurturing pour le lead."""
    agent = NurturingAgent(client_id=state["client_id"], tier=state["tier"])

    from memory.lead_repository import get_lead
    lead = get_lead(state["lead_id"])

    if lead and lead.nurturing_sequence:
        result = agent.send_followup(lead)
        log_msg = f"Nurturing activé : {lead.nurturing_sequence.value} — step {lead.nurturing_step}"
        log_action(
            lead_id=state["lead_id"],
            client_id=state["client_id"],
            stage="nurturing",
            action_done="sequence_started",
            action_result=lead.nurturing_sequence.value,
            agent_name="marc",
            metadata={"sequence": lead.nurturing_sequence.value, "step": lead.nurturing_step},
        )
        return {
            **state,
            "status": "nurturing_active",
            "messages_log": state["messages_log"] + [log_msg],
        }

    return {**state, "status": "nurturing_skipped"}


def node_propose_rdv(state: AgencyState) -> AgencyState:
    """Envoie une proposition de RDV pour les leads chauds (score ≥ 7)."""
    from memory.lead_repository import get_lead, update_lead
    from memory.models import LeadStatus

    lead = get_lead(state["lead_id"])
    if not lead:
        return {**state, "status": "error", "error": "Lead introuvable"}

    # Message de proposition RDV
    prenom = lead.prenom or "vous"
    agence_nom = get_settings().agency_name
    rdv_msg = (
        f"Excellent {prenom} ! Votre projet est clairement défini et j'ai exactement ce qu'il vous faut. "
        f"Je vous propose qu'on en parle de vive voix. "
        f"Seriez-vous disponible mardi ou jeudi cette semaine, en matinée ou après-midi ? "
        f"— {agence_nom}"
    )

    lead.statut = LeadStatus.QUALIFIE
    update_lead(lead)

    canal = Canal(state.get("canal", "sms"))

    if canal == Canal.SMS and lead.telephone:
        from tools.vonage_tool import VonageTool
        vonage = VonageTool()
        vonage.send_sms(
            to=vonage.format_french_number(lead.telephone),
            body=rdv_msg,
        )
    elif canal == Canal.WHATSAPP and lead.telephone:
        from tools.twilio_tool import TwilioTool
        TwilioTool().send_whatsapp(to=lead.telephone, body=rdv_msg)

    log_action(
        lead_id=state["lead_id"],
        client_id=state["client_id"],
        stage="rdv_proposal",
        action_done="rdv_proposed",
        action_result=rdv_msg[:200],
        next_action="trigger_voice_call",
        agent_name="sophie",
        metadata={"canal": state.get("canal", "sms"), "score": state.get("score", 0)},
    )

    return {
        **state,
        "message_sortant": rdv_msg,
        "status": "rdv_proposed",
        "messages_log": state["messages_log"] + [f"RDV proposé au lead {state['lead_id']}"],
    }


def node_trigger_voice_call(state: AgencyState) -> AgencyState:
    """
    Déclenche un appel voix sortant via Retell AI pour les leads chauds
    qui n'ont pas répondu au SMS de RDV après un délai configurable.
    Optionnel — ne bloque pas le flux si l'appel échoue.
    """
    lead_id = state.get("lead_id")
    if not lead_id:
        return {**state, "status": "voice_skipped"}

    # Pas d'appel vocal pour les leads LOCATION
    try:
        from memory.lead_repository import get_lead as _get_lead
        from memory.models import ProjetType as _ProjetType
        _lead = _get_lead(lead_id)
        if _lead and _lead.projet == _ProjetType.LOCATION:
            logger.info(f"Appel voix ignoré — lead LOCATION : {lead_id}")
            return {**state, "voice_call_triggered": False, "status": "rdv_proposed"}
    except Exception:
        pass

    try:
        from agents.voice_call import VoiceCallAgent
        voice_agent = VoiceCallAgent(client_id=state["client_id"], tier=state["tier"])
        result = voice_agent.call_hot_lead(lead_id)

        if result.get("success"):
            call_id = result.get("call_id", "")
            logger.info(f"Appel voix déclenché : {call_id} pour lead {lead_id}")
            log_action(
                lead_id=lead_id,
                client_id=state["client_id"],
                stage="voice_call",
                action_done="call_initiated",
                action_result=call_id,
                agent_name="sophie",
                metadata={"call_id": call_id},
            )
            return {
                **state,
                "voice_call_id": call_id,
                "voice_call_triggered": True,
                "status": "voice_call_initiated",
                "messages_log": state["messages_log"] + [f"Appel voix initié : {call_id[:12]}"],
            }
        else:
            logger.info(f"Appel voix non déclenché : {result.get('message', '')}")
            return {**state, "voice_call_triggered": False, "status": "rdv_proposed"}

    except Exception as e:
        logger.warning(f"Erreur déclenchement appel voix : {e}")
        return {**state, "voice_call_triggered": False, "status": "rdv_proposed"}


# ─────────────────────────────────────────────────────────────
# CONDITIONAL EDGES
# ─────────────────────────────────────────────────────────────

def route_after_lead_check(state: AgencyState) -> Literal["qualify_new", "continue_qualification"]:
    """Décide si c'est un nouveau lead ou la suite d'une conversation."""
    if state["status"] == "existing_lead":
        return "continue_qualification"
    return "qualify_new"


def route_after_qualification(
    state: AgencyState,
) -> Literal["route_lead", "end_qualifying"]:
    """Continue la qualification ou route si le scoring est fait."""
    if state["qualification_complete"] or state["status"] in ("limit_reached", "error"):
        return "route_lead"
    return "end_qualifying"


def route_after_scoring(
    state: AgencyState,
) -> Literal["propose_rdv", "trigger_nurturing", "end"]:
    """Route selon le score."""
    if state["status"] in ("limit_reached", "error"):
        return "end"

    next_action = state["next_action"]
    if next_action == "rdv" or state["score"] >= 7:
        return "propose_rdv"
    elif state["score"] >= 4:
        return "trigger_nurturing"
    else:
        return "trigger_nurturing"


# ─────────────────────────────────────────────────────────────
# GRAPH CONSTRUCTION
# ─────────────────────────────────────────────────────────────

def route_after_rdv_proposal(
    state: AgencyState,
) -> Literal["trigger_voice_call", "end"]:
    """
    Après proposition RDV, décide si on déclenche aussi un appel voix.
    L'appel voix est déclenché si le score est ≥ 8 (lead très chaud).
    """
    score = state.get("score", 0)
    if score >= 8:
        return "trigger_voice_call"
    return "end"


def build_graph() -> StateGraph:
    """Construit et compile le graphe LangGraph."""
    graph = StateGraph(AgencyState)

    # Nœuds
    graph.add_node("check_existing_lead", node_check_existing_lead)
    graph.add_node("qualify_new", node_qualify_new_lead)
    graph.add_node("continue_qualification", node_continue_qualification)
    graph.add_node("route_lead", node_route_lead)
    graph.add_node("trigger_nurturing", node_trigger_nurturing)
    graph.add_node("propose_rdv", node_propose_rdv)
    graph.add_node("trigger_voice_call", node_trigger_voice_call)

    # Edges
    graph.add_edge(START, "check_existing_lead")
    graph.add_conditional_edges(
        "check_existing_lead",
        route_after_lead_check,
        {
            "qualify_new": "qualify_new",
            "continue_qualification": "continue_qualification",
        },
    )
    graph.add_conditional_edges(
        "qualify_new",
        route_after_qualification,
        {
            "route_lead": "route_lead",
            "end_qualifying": END,
        },
    )
    graph.add_conditional_edges(
        "continue_qualification",
        route_after_qualification,
        {
            "route_lead": "route_lead",
            "end_qualifying": END,
        },
    )
    graph.add_conditional_edges(
        "route_lead",
        route_after_scoring,
        {
            "propose_rdv": "propose_rdv",
            "trigger_nurturing": "trigger_nurturing",
            "end": END,
        },
    )
    graph.add_edge("trigger_nurturing", END)
    graph.add_conditional_edges(
        "propose_rdv",
        route_after_rdv_proposal,
        {
            "trigger_voice_call": "trigger_voice_call",
            "end": END,
        },
    )
    graph.add_edge("trigger_voice_call", END)

    return graph.compile()


# Singleton du graphe compilé
_compiled_graph = None


def get_graph():
    """Retourne le graphe compilé (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def process_incoming_message(
    telephone: str,
    message: str,
    client_id: str,
    tier: str = "Starter",
    canal: str = "sms",
    prenom: str = "",
    nom: str = "",
    email: str = "",
    lead_id: Optional[str] = None,
) -> AgencyState:
    """
    Point d'entrée principal — traite un message entrant via le graphe.

    Args:
        telephone: Numéro du contact
        message: Texte du message reçu
        client_id: ID de l'agence cliente
        tier: Tier de l'agence
        canal: Canal du message
        prenom/nom/email: Infos optionnelles du contact
        lead_id: ID si lead déjà connu

    Returns:
        AgencyState final avec message_sortant à envoyer
    """
    graph = get_graph()
    initial_state = make_initial_state(
        client_id=client_id,
        telephone=telephone,
        message=message,
        canal=canal,
        prenom=prenom,
        nom=nom,
        email=email,
        tier=tier,
        lead_id=lead_id,
    )

    final_state = graph.invoke(initial_state)
    logger.info(
        f"Message traité | Lead: {final_state.get('lead_id')} | "
        f"Status: {final_state.get('status')} | Score: {final_state.get('score')}"
    )
    return final_state
