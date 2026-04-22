"""
Orchestrateur LangGraph — StateGraph principal.
Gère le flux lead : qualification → scoring → routage → nurturing/RDV (SMS uniquement).
Intègre : LeadQualifier, Nurturing.
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
    agency_name: str        # Nom réel de l'agence (depuis DB users)

    # Infos lead
    lead_id: Optional[str]
    lead_status: str        # Statut DB du lead au moment du check (ex: "qualifie", "rdv_booke")
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
    status: str             # "new" | "qualifying" | "scored" | "routed" | "rdv_proposed" | "error"
    error: Optional[str]


def make_initial_state(
    client_id: str,
    telephone: str,
    message: str,
    canal: str = "sms",
    prenom: str = "",
    nom: str = "",
    email: str = "",
    tier: str = "Starter",
    agency_name: str = "",
    lead_id: Optional[str] = None,
    source_data: Optional[dict] = None,
) -> AgencyState:
    """Crée l'état initial du graphe pour un nouveau message entrant."""
    return AgencyState(
        client_id=client_id,
        tier=tier,
        agency_name=agency_name or get_settings().agency_name,
        lead_id=lead_id,
        lead_status="",
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
    )


# ─────────────────────────────────────────────────────────────
# NODES
# ─────────────────────────────────────────────────────────────

def node_check_existing_lead(state: AgencyState) -> AgencyState:
    """Vérifie si le lead existe déjà (même numéro de téléphone) et lit son statut."""
    from memory.database import get_connection

    if state["lead_id"]:
        # Lead ID fourni explicitement — lire son statut
        with get_connection() as conn:
            row = conn.execute(
                "SELECT statut FROM leads WHERE id = ? LIMIT 1",
                (state["lead_id"],),
            ).fetchone()
        lead_status = row["statut"] if row else ""
        return {**state, "lead_status": lead_status, "status": "existing_lead"}

    # Recherche par téléphone
    telephone = state["telephone"]
    client_id = state["client_id"]

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, statut FROM leads WHERE client_id = ? AND telephone = ? ORDER BY created_at DESC LIMIT 1",
            (client_id, telephone),
        ).fetchone()

    if row:
        logger.info(f"Lead existant trouvé : {row['id']} (statut: {row['statut']})")
        return {**state, "lead_id": row["id"], "lead_status": row["statut"], "status": "existing_lead"}

    return {**state, "lead_status": "", "status": "new_lead"}


def node_qualify_new_lead(state: AgencyState) -> AgencyState:
    """Crée et envoie le premier message de bienvenue pour un nouveau lead."""
    agent = LeadQualifierAgent(client_id=state["client_id"], tier=state["tier"], agency_name=state["agency_name"])
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
    agent = LeadQualifierAgent(client_id=state["client_id"], tier=state["tier"], agency_name=state["agency_name"])
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
    rdv_msg = (
        f"Excellent {prenom} ! Votre projet est clairement défini et j'ai exactement ce qu'il vous faut. "
        f"Je vous propose qu'on en parle de vive voix. "
        f"Seriez-vous disponible mardi ou jeudi cette semaine, en matinée ou après-midi ?"
    )

    lead.statut = LeadStatus.RDV_PROPOSE
    update_lead(lead)

    canal = Canal(state.get("canal", "sms"))

    if canal == Canal.SMS and lead.telephone:
        from tools.twilio_tool import TwilioTool
        twilio = TwilioTool()
        twilio.send_sms(
            to=twilio.format_french_number(lead.telephone),
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
        next_action="end",
        agent_name="lea",
        metadata={"canal": state.get("canal", "sms"), "score": state.get("score", 0)},
    )

    return {
        **state,
        "message_sortant": rdv_msg,
        "status": "rdv_proposed",
        "messages_log": state["messages_log"] + [f"RDV proposé au lead {state['lead_id']}"],
    }


_SPECIFIC_SLOT_KEYWORDS = (
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "matin", "après-midi", "aprem", "soir", "midi",
    "h", "heures", "9h", "10h", "11h", "14h", "15h", "16h", "17h",
)

_VAGUE_ACCEPTANCE_KEYWORDS = (
    "quand vous", "quand tu", "quand vous voulez", "quand tu veux",
    "peu importe", "n'importe quand", "nimporte quand",
    "libre", "disponible", "dispo",
    "ça m'arrange", "ca m'arrange",
    "ok pour", "oui pour",
)

_GENERAL_ACCEPTANCE_KEYWORDS = (
    "ok", "oui", "d'accord", "parfait", "ça me va", "ca me va",
    "ça convient", "ca convient", "confirmed", "confirme", "c'est bon",
    "c'est noté", "noté",
)


def node_handle_rdv_confirmation(state: AgencyState) -> AgencyState:
    """
    Gère la réponse du lead après qu'un RDV a été proposé.
    - Acceptation vague → propose 2-3 créneaux précis
    - Créneau spécifique confirmé → confirme et marque RDV_BOOKÉ
    - Autre → message neutre
    """
    from memory.lead_repository import get_lead, update_lead
    from memory.models import LeadStatus
    from datetime import date, timedelta

    lead = get_lead(state["lead_id"])
    if not lead:
        return {**state, "status": "error", "error": "Lead introuvable"}

    message_lower = state["message_entrant"].lower()
    prenom = lead.prenom or "vous"

    has_specific_slot = any(kw in message_lower for kw in _SPECIFIC_SLOT_KEYWORDS)
    is_vague_acceptance = any(kw in message_lower for kw in _VAGUE_ACCEPTANCE_KEYWORDS)
    is_general_acceptance = any(kw in message_lower for kw in _GENERAL_ACCEPTANCE_KEYWORDS)

    # Créneau spécifique confirmé → RDV booké
    if has_specific_slot and (is_general_acceptance or is_vague_acceptance or has_specific_slot):
        confirmation_msg = (
            f"Parfait {prenom} ! J'ai bien noté votre confirmation. "
            f"Un(e) conseiller(ère) vous contactera pour finaliser les détails. "
            f"À très bientôt !"
        )
        lead.statut = LeadStatus.RDV_BOOKÉ
        update_lead(lead)

        log_action(
            lead_id=state["lead_id"],
            client_id=state["client_id"],
            stage="rdv_confirmation",
            action_done="rdv_confirmed",
            action_result=confirmation_msg[:200],
            next_action="end",
            agent_name="lea",
        )

        return {
            **state,
            "message_sortant": confirmation_msg,
            "status": "rdv_confirmed",
            "messages_log": state["messages_log"] + [f"RDV confirmé par {prenom}"],
        }

    # Acceptation vague → proposer des créneaux précis
    if is_vague_acceptance or is_general_acceptance:
        today = date.today()
        # Calcul des 3 prochains créneaux (mardi, jeudi, vendredi de la semaine courante/suivante)
        jours_cibles = []
        for delta in range(1, 14):
            d = today + timedelta(days=delta)
            if d.weekday() in (1, 3, 4) and len(jours_cibles) < 3:  # mardi=1, jeudi=3, vendredi=4
                jours_noms = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                jours_cibles.append(f"{jours_noms[d.weekday()]} {d.day} {['jan', 'fév', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sep', 'oct', 'nov', 'déc'][d.month - 1]}")

        slots_text = ", ".join(jours_cibles) if jours_cibles else "mardi ou jeudi"
        slots_msg = (
            f"Voici quelques créneaux disponibles pour {prenom} : "
            f"{jours_cibles[0] if jours_cibles else 'mardi'} à 10h, "
            f"{jours_cibles[1] if len(jours_cibles) > 1 else 'jeudi'} à 14h, "
            f"ou {jours_cibles[2] if len(jours_cibles) > 2 else 'vendredi'} à 11h. "
            f"Lequel vous convient le mieux ?"
        )

        log_action(
            lead_id=state["lead_id"],
            client_id=state["client_id"],
            stage="rdv_confirmation",
            action_done="slots_proposed",
            action_result=slots_msg[:200],
            next_action="awaiting_slot_choice",
            agent_name="lea",
        )

        return {
            **state,
            "message_sortant": slots_msg,
            "status": "rdv_proposed",
            "messages_log": state["messages_log"] + [f"Créneaux proposés à {prenom}"],
        }

    # Message hors-séquence après qualification — réponse neutre
    neutral_msg = (
        f"Bonjour {prenom} ! Pour confirmer votre rendez-vous ou toute question, "
        f"répondez-moi directement."
    )

    log_action(
        lead_id=state["lead_id"],
        client_id=state["client_id"],
        stage="rdv_confirmation",
        action_done="post_rdv_message",
        action_result=neutral_msg[:200],
        next_action="end",
        agent_name="lea",
    )

    return {
        **state,
        "message_sortant": neutral_msg,
        "status": "rdv_proposed",
        "messages_log": state["messages_log"] + [f"Message post-RDV de {prenom}"],
    }


# ─────────────────────────────────────────────────────────────
# CONDITIONAL EDGES
# ─────────────────────────────────────────────────────────────

def route_after_lead_check(state: AgencyState) -> Literal["qualify_new", "continue_qualification", "handle_rdv_confirmation"]:
    """Décide si c'est un nouveau lead, la suite d'une qualification, ou une confirmation de RDV."""
    if state["status"] != "existing_lead":
        return "qualify_new"
    # Lead qualifié, RDV proposé ou déjà booké → ne pas rejouer la qualification
    if state.get("lead_status") in ("qualifie", "rdv_propose", "rdv_booke"):
        return "handle_rdv_confirmation"
    return "continue_qualification"


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

def build_graph() -> StateGraph:
    """Construit et compile le graphe LangGraph."""
    graph = StateGraph(AgencyState)

    # Nœuds
    graph.add_node("check_existing_lead", node_check_existing_lead)
    graph.add_node("qualify_new", node_qualify_new_lead)
    graph.add_node("continue_qualification", node_continue_qualification)
    graph.add_node("handle_rdv_confirmation", node_handle_rdv_confirmation)
    graph.add_node("route_lead", node_route_lead)
    graph.add_node("trigger_nurturing", node_trigger_nurturing)
    graph.add_node("propose_rdv", node_propose_rdv)

    # Edges
    graph.add_edge(START, "check_existing_lead")
    graph.add_conditional_edges(
        "check_existing_lead",
        route_after_lead_check,
        {
            "qualify_new": "qualify_new",
            "continue_qualification": "continue_qualification",
            "handle_rdv_confirmation": "handle_rdv_confirmation",
        },
    )
    graph.add_edge("handle_rdv_confirmation", END)
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
    graph.add_edge("propose_rdv", END)

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
    agency_name: str = "",
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
        agency_name=agency_name,
        lead_id=lead_id,
    )

    final_state = graph.invoke(initial_state)
    logger.info(
        f"Message traité | Lead: {final_state.get('lead_id')} | "
        f"Status: {final_state.get('status')} | Score: {final_state.get('score')}"
    )
    return final_state
