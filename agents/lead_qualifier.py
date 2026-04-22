"""
LeadQualifierAgent — Qualification des leads entrants.
Déclencheurs : SMS, WhatsApp, formulaire web, SeLoger/LeBonCoin.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from config.prompts import (
    LEAD_QUALIFIER_FIRST_MESSAGE,
    LEAD_QUALIFIER_FIRST_MESSAGE_ANONYMOUS,
    LEAD_QUALIFIER_SCORING_PROMPT,
    get_lead_qualifier_system,
)
from config.settings import get_settings
from memory.lead_repository import (
    add_conversation_message,
    create_lead,
    format_history_for_llm,
    get_lead,
    update_lead,
)
from memory.models import Canal, Lead, LeadStatus, NurturingSequence, ProjetType
from memory.usage_tracker import check_and_consume

logger = logging.getLogger(__name__)


class LeadQualifierAgent:
    """
    Agent de qualification des leads entrants.
    Gère le flux de conversation jusqu'au scoring + routage.
    """

    CONSEILLER_PRENOM = "Léa"
    CONSEILLER_TITRE = "conseillère immobilier"

    def __init__(self, client_id: str, tier: str = "Starter", agency_name: str = ""):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()
        self._agency_name = agency_name
        self._anthropic_client = None

    def _get_agency_name(self) -> str:
        return self._agency_name or self.settings.agency_name

    def _get_anthropic_client(self):
        """Lazy init client Anthropic."""
        if self._anthropic_client is None:
            if not self.settings.anthropic_available:
                return None
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def handle_new_lead(
        self,
        telephone: str,
        message_initial: str,
        canal: Canal = Canal.SMS,
        prenom: str = "",
        nom: str = "",
        email: str = "",
        source_data: Optional[dict] = None,
    ) -> dict:
        """
        Point d'entrée pour un nouveau lead entrant.
        Crée le lead, envoie le premier message de qualification.

        Returns:
            {
                "lead_id": str,
                "message": str,       # message à envoyer au lead
                "status": str,        # "new_lead" | "limit_reached"
            }
        """
        # Vérification quota avant toute action
        usage_check = check_and_consume(self.client_id, "lead", tier=self.tier)
        if not usage_check["allowed"]:
            return {
                "lead_id": None,
                "message": None,
                "status": "limit_reached",
                "usage_message": usage_check["message"],
            }

        # Détection du type de projet dès le premier message
        projet_detecte = self._detect_projet(message_initial)

        # Création du lead
        lead = Lead(
            client_id=self.client_id,
            prenom=prenom,
            nom=nom,
            telephone=telephone,
            email=email,
            source=canal,
            statut=LeadStatus.EN_QUALIFICATION,
            projet=projet_detecte,
        )
        lead = create_lead(lead)

        # Enregistrement message initial
        add_conversation_message(
            lead_id=lead.id,
            client_id=self.client_id,
            role="user",
            contenu=message_initial,
            canal=canal,
        )

        # Génération message de bienvenue
        welcome_msg = self._generate_welcome_message(prenom)

        # Enregistrement réponse agent
        add_conversation_message(
            lead_id=lead.id,
            client_id=self.client_id,
            role="assistant",
            contenu=welcome_msg,
            canal=canal,
        )

        logger.info(f"Nouveau lead créé : {lead.id} ({canal.value})")

        return {
            "lead_id": lead.id,
            "message": welcome_msg,
            "status": "new_lead",
            "usage_message": usage_check["message"],
        }

    def handle_incoming_message(
        self,
        lead_id: str,
        message: str,
        canal: Canal = Canal.SMS,
    ) -> dict:
        """
        Traite un message entrant d'un lead existant.
        Continue la qualification ou déclenche le scoring si complet.

        Returns:
            {
                "message": str,           # réponse à envoyer
                "score": Optional[int],   # défini si qualification terminée
                "next_action": str,       # "continue" | "rdv" | "nurturing_14j" | "nurturing_30j"
                "lead": Lead,
            }
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"message": "Désolé, une erreur est survenue.", "next_action": "continue"}

        # Détection projet si encore INCONNU
        if lead.projet == ProjetType.INCONNU:
            projet_detecte = self._detect_projet(message)
            if projet_detecte != ProjetType.INCONNU:
                lead.projet = projet_detecte
                update_lead(lead)

        # Enregistrement message utilisateur
        add_conversation_message(
            lead_id=lead_id,
            client_id=self.client_id,
            role="user",
            contenu=message,
            canal=canal,
        )

        # Historique pour le LLM
        history = format_history_for_llm(lead_id, limit=20)

        # Génération réponse qualification
        agence_nom = self._get_agency_name()
        response_text, qualification_complete = self._generate_qualification_response(
            history=history,
            agence_nom=agence_nom,
            lead=lead,
        )

        # Enregistrement réponse agent
        add_conversation_message(
            lead_id=lead_id,
            client_id=self.client_id,
            role="assistant",
            contenu=response_text,
            canal=canal,
        )

        # Si qualification complète (≥ 7 échanges ou suffisamment d'info)
        next_action = "continue"
        if qualification_complete:
            scoring_result = self._compute_score(lead_id, history, agence_nom)
            lead = self._apply_score_and_route(lead, scoring_result)
            next_action = scoring_result.get("prochaine_action", "nurturing_30j")

        return {
            "message": response_text,
            "next_action": next_action,
            "lead": lead,
            "score": lead.score if qualification_complete else None,
        }

    def _detect_projet(self, message: str) -> ProjetType:
        """
        Détecte le type de projet dans un message entrant.
        Retourne ProjetType.INCONNU si aucun signal clair.
        """
        msg = message.lower()

        vente_keywords = ["vendre", "vente", "mandat", "mise en vente", "vend", "vendeur", "ma maison", "mon appartement", "mon bien"]
        achat_keywords = ["acheter", "achat", "cherche", "recherche", "budget", "acquérir", "acquéreur", "acheteur", "trouver"]
        location_keywords = ["louer", "location", "loyer", "locataire", "bail", "appartement à louer", "maison à louer"]
        estimation_keywords = ["estimer", "estimation", "valeur", "prix de mon bien", "combien vaut"]

        if any(kw in msg for kw in vente_keywords):
            return ProjetType.VENTE
        if any(kw in msg for kw in location_keywords):
            return ProjetType.LOCATION
        if any(kw in msg for kw in estimation_keywords):
            return ProjetType.ESTIMATION
        if any(kw in msg for kw in achat_keywords):
            return ProjetType.ACHAT

        return ProjetType.INCONNU

    def _generate_welcome_message(self, prenom: str = "") -> str:
        """Génère le message de bienvenue initial."""
        agence_nom = self._get_agency_name()
        if prenom:
            return LEAD_QUALIFIER_FIRST_MESSAGE.format(
                prenom=prenom,
                conseiller_prenom=self.CONSEILLER_PRENOM,
                conseiller_titre=self.CONSEILLER_TITRE,
                agence_nom=agence_nom,
            )
        else:
            return LEAD_QUALIFIER_FIRST_MESSAGE_ANONYMOUS.format(
                conseiller_prenom=self.CONSEILLER_PRENOM,
                conseiller_titre=self.CONSEILLER_TITRE,
                agence_nom=agence_nom,
            )

    def _generate_qualification_response(
        self,
        history: list[dict],
        agence_nom: str,
        lead: Lead,
    ) -> tuple[str, bool]:
        """
        Génère la prochaine question de qualification via Claude.
        Returns (response_text, qualification_complete).
        """
        client = self._get_anthropic_client()
        nb_exchanges = len(history)

        # Qualification complète si ≥ 7 échanges utilisateur (7 questions posées)
        user_messages = [m for m in history if m["role"] == "user"]
        qualification_complete = len(user_messages) >= 7

        if client:
            try:
                from memory.cost_logger import log_api_action
                system = get_lead_qualifier_system(agence_nom)

                response = client.messages.create(
                    model=self.settings.claude_model,
                    max_tokens=300,
                    system=system,
                    messages=history,
                )
                text = response.content[0].text

                # Log coût
                log_api_action(
                    client_id=self.client_id,
                    action_type="lead",
                    provider="anthropic",
                    model=self.settings.claude_model,
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                )

                return text, qualification_complete

            except Exception as e:
                logger.warning(f"Erreur Anthropic : {e} — utilisation du mock")

        # Mock si pas de clé
        return self._mock_qualification_response(len(user_messages)), qualification_complete

    def _mock_qualification_response(self, nb_user_messages: int) -> str:
        """Réponses mockées pour la démo sans API key."""
        responses = [
            "Parfait ! Et dans quelle ville ou secteur géographique recherchez-vous ? Ou s'agit-il d'un bien que vous souhaitez vendre ?",
            "Je vois, merci. Quel est votre budget pour ce projet ? (ou le prix auquel vous souhaitez vendre ?)",
            "Très bien. Dans quel délai souhaitez-vous conclure cette transaction ? Avez-vous une contrainte de temps ?",
            "Êtes-vous déjà propriétaire actuellement ? Y a-t-il un bien en cours de vente ou déjà sous compromis ?",
            "Et côté financement, avez-vous déjà un accord de principe de votre banque, ou un apport personnel ?",
            "Merci pour toutes ces informations ! Y a-t-il une raison particulière qui vous pousse à agir maintenant sur ce projet ?",
            "Parfait, j'ai maintenant tout ce qu'il me faut pour vous accompagner au mieux. Je vais étudier votre dossier et vous recontacter très vite avec une proposition concrète. Seriez-vous disponible pour un échange téléphonique de 15 minutes cette semaine ?",
        ]
        idx = min(nb_user_messages, len(responses) - 1)
        return f"[MOCK] {responses[idx]}"

    def _compute_score(
        self, lead_id: str, history: list[dict], agence_nom: str
    ) -> dict:
        """Calcule le score de qualification via Claude."""
        client = self._get_anthropic_client()

        conversation_text = "\n".join(
            f"{'Contact' if m['role'] == 'user' else 'Conseiller'}: {m['content']}"
            for m in history
        )

        prompt = LEAD_QUALIFIER_SCORING_PROMPT.format(
            conversation=conversation_text,
            projet_detecte="à déterminer",
        )

        if client:
            try:
                from memory.cost_logger import log_api_action
                response = client.messages.create(
                    model=self.settings.claude_model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()

                log_api_action(
                    client_id=self.client_id,
                    action_type="lead",
                    provider="anthropic",
                    model=self.settings.claude_model,
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                )

                # Parse JSON
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                return json.loads(text)

            except Exception as e:
                logger.warning(f"Erreur scoring : {e}")

        # Score mock
        return {
            "score_total": 7,
            "score_urgence": 3,
            "score_budget": 2,
            "score_motivation": 2,
            "projet": "achat",
            "localisation": "Paris 15e",
            "budget": "450 000€",
            "timeline": "3-6 mois",
            "financement": "Apport 20%",
            "motivation": "Mutation professionnelle",
            "prochaine_action": "rdv",
            "resume": "[MOCK] Lead qualifié acheteur avec apport, mutation professionnelle.",
        }

    def _apply_score_and_route(self, lead: Lead, scoring: dict) -> Lead:
        """Applique le score et route le lead vers la bonne séquence."""
        lead.score = scoring.get("score_total", 0)
        lead.score_urgence = scoring.get("score_urgence", 0)
        lead.score_budget = scoring.get("score_budget", 0)
        lead.score_motivation = scoring.get("score_motivation", 0)
        lead.resume = scoring.get("resume", "")

        # Mise à jour projet
        projet_str = scoring.get("projet", "inconnu")
        try:
            lead.projet = ProjetType(projet_str)
        except ValueError:
            lead.projet = ProjetType.INCONNU

        lead.localisation = scoring.get("localisation") or lead.localisation
        lead.budget = scoring.get("budget") or lead.budget
        lead.timeline = scoring.get("timeline") or lead.timeline
        lead.financement = scoring.get("financement") or lead.financement
        lead.motivation = scoring.get("motivation") or lead.motivation

        # Routage par score — leads LOCATION : toujours LEAD_FROID, max 3 SMS
        prochaine_action = scoring.get("prochaine_action", "nurturing_30j")
        if lead.projet == ProjetType.LOCATION:
            lead.statut = LeadStatus.NURTURING
            lead.nurturing_sequence = NurturingSequence.LEAD_FROID
            lead.prochain_followup = datetime.now() + timedelta(days=7)
        elif lead.score >= 7:
            lead.statut = LeadStatus.QUALIFIE
            lead.nurturing_sequence = None
            # RDV proposé dans le message → statut RDV booké après confirmation
        elif lead.score >= 4:
            lead.statut = LeadStatus.NURTURING
            lead.nurturing_sequence = NurturingSequence.VENDEUR_CHAUD if lead.projet == ProjetType.VENTE else NurturingSequence.ACHETEUR_QUALIFIE
            lead.prochain_followup = datetime.now() + timedelta(days=1)
        else:
            lead.statut = LeadStatus.NURTURING
            lead.nurturing_sequence = NurturingSequence.LEAD_FROID
            lead.prochain_followup = datetime.now() + timedelta(days=7)

        return update_lead(lead)
