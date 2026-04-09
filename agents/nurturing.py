"""
NurturingAgent — Séquences de follow-up automatisées.
Personnalisation via Claude + multi-canal (SMS/Email/WhatsApp).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from config.prompts import NURTURING_GENERATION_PROMPT, get_nurturing_system
from config.settings import get_settings
from memory.lead_repository import (
    add_conversation_message,
    format_history_for_llm,
    get_lead,
    get_leads_for_followup,
    update_lead,
)
from memory.models import Canal, Lead, LeadStatus, NurturingSequence, ProjetType
from memory.usage_tracker import check_and_consume

logger = logging.getLogger(__name__)

# Définition des séquences : (délai_jours, canal_preferé, sujet_contexte)
SEQUENCES: dict[NurturingSequence, list[dict]] = {
    NurturingSequence.VENDEUR_CHAUD: [
        {"delai_jours": 1,  "canal": Canal.SMS,      "contexte": "relance_douce"},
        {"delai_jours": 3,  "canal": Canal.EMAIL,     "contexte": "comparables_marche"},
        {"delai_jours": 7,  "canal": Canal.SMS,       "contexte": "urgence_acheteurs"},
        {"delai_jours": 14, "canal": Canal.SMS,       "contexte": "nouvelle_estimation"},
        {"delai_jours": 30, "canal": Canal.EMAIL,     "contexte": "bilan_marche_mensuel"},
    ],
    NurturingSequence.ACHETEUR_QUALIFIE: [
        {"delai_jours": 2,  "canal": Canal.SMS,      "contexte": "nouveaux_biens"},
        {"delai_jours": 5,  "canal": Canal.EMAIL,     "contexte": "biens_selection"},
        {"delai_jours": 10, "canal": Canal.SMS,       "contexte": "alerte_bien_rare"},
        {"delai_jours": 21, "canal": Canal.EMAIL,     "contexte": "bilan_recherche"},
    ],
    NurturingSequence.LEAD_FROID: [
        {"delai_jours": 7,  "canal": Canal.SMS,      "contexte": "reactivation_douce"},
        {"delai_jours": 21, "canal": Canal.EMAIL,     "contexte": "actualite_marche"},
        {"delai_jours": 45, "canal": Canal.SMS,       "contexte": "derniere_chance"},
    ],
}


class NurturingAgent:
    """
    Agent de nurturing automatisé.
    Génère et envoie des messages personnalisés selon la séquence du lead.
    """

    def __init__(self, client_id: str, tier: str = "Starter"):
        self.client_id = client_id
        self.tier = tier
        self.settings = get_settings()
        self._anthropic_client = None
        self._twilio = None

    def _get_anthropic_client(self):
        if self._anthropic_client is None and self.settings.anthropic_available:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def _get_twilio(self):
        if self._twilio is None:
            from tools.twilio_tool import TwilioTool
            self._twilio = TwilioTool()
        return self._twilio

    def process_due_followups(self) -> list[dict]:
        """
        Traite tous les follow-ups dus pour ce client.
        Appelé par le scheduler (toutes les heures en production).

        Returns: liste des résultats d'envoi
        """
        leads_due = get_leads_for_followup(self.client_id)
        results = []

        for lead in leads_due:
            result = self.send_followup(lead)
            results.append({"lead_id": lead.id, **result})

        logger.info(f"Nurturing : {len(leads_due)} follow-ups traités pour {self.client_id}")
        return results

    def send_followup(self, lead: Lead) -> dict:
        """
        Envoie le prochain message de nurturing pour un lead.

        Returns:
            {"sent": bool, "canal": str, "message": str, "next_followup": Optional[datetime]}
        """
        if not lead.nurturing_sequence:
            return {"sent": False, "reason": "Pas de séquence nurturing définie"}

        # Vérification quota follow-up
        usage_check = check_and_consume(self.client_id, "followup", tier=self.tier)
        if not usage_check["allowed"]:
            return {
                "sent": False,
                "reason": "limit_reached",
                "usage_message": usage_check["message"],
            }

        sequence_steps = SEQUENCES.get(lead.nurturing_sequence, [])
        current_step = lead.nurturing_step

        if current_step >= len(sequence_steps):
            # Séquence terminée → lead froid archivé
            lead.statut = LeadStatus.PERDU
            lead.nurturing_sequence = None
            lead.prochain_followup = None
            update_lead(lead)
            return {"sent": False, "reason": "sequence_terminee"}

        step_config = sequence_steps[current_step]
        canal = step_config["canal"]

        # Récupération de l'historique des messages envoyés
        historique = format_history_for_llm(lead.id, limit=10)
        historique_msgs = "\n".join(
            f"- {m['role']}: {m['content'][:100]}..." if len(m['content']) > 100 else f"- {m['role']}: {m['content']}"
            for m in historique[-5:]
        )

        # Génération message personnalisé
        message_data = self._generate_message(lead, step_config, canal, historique_msgs)

        # Envoi selon le canal
        sent = self._send_message(lead, message_data, canal)

        if sent:
            # Enregistrement en base
            add_conversation_message(
                lead_id=lead.id,
                client_id=self.client_id,
                role="assistant",
                contenu=message_data.get("message", ""),
                canal=canal,
                metadata={"step": current_step, "sequence": lead.nurturing_sequence.value},
            )

            # Avancement dans la séquence
            lead.nurturing_step = current_step + 1
            next_step = current_step + 1

            if next_step < len(sequence_steps):
                next_delay = sequence_steps[next_step]["delai_jours"]
                lead.prochain_followup = datetime.now() + timedelta(days=next_delay)
            else:
                lead.prochain_followup = None

            update_lead(lead)

        return {
            "sent": sent,
            "canal": canal.value,
            "message": message_data.get("message", ""),
            "next_followup": lead.prochain_followup.isoformat() if lead.prochain_followup else None,
            "step": current_step,
        }

    def _generate_message(
        self, lead: Lead, step_config: dict, canal: Canal, historique_msgs: str
    ) -> dict:
        """Génère le message personnalisé via Claude."""
        client = self._get_anthropic_client()
        agence_nom = self.settings.agency_name

        prompt = NURTURING_GENERATION_PROMPT.format(
            prenom=lead.prenom or "vous",
            projet=lead.projet.value,
            localisation=lead.localisation or "votre secteur",
            budget=lead.budget or "votre budget",
            timeline=lead.timeline or "à définir",
            score=lead.score,
            sequence_name=step_config.get("contexte", ""),
            canal=canal.value,
            jours_dernier_contact=step_config.get("delai_jours", 1),
            historique_messages=historique_msgs or "Premier message de la séquence",
        )

        if client:
            try:
                from memory.cost_logger import log_api_action
                system = get_nurturing_system(agence_nom)
                response = client.messages.create(
                    model=self.settings.claude_model,
                    max_tokens=400,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()

                log_api_action(
                    client_id=self.client_id,
                    action_type="followup",
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
                logger.warning(f"Erreur génération nurturing : {e}")

        # Mock message
        return self._mock_message(lead, canal, step_config["contexte"])

    def _mock_message(self, lead: Lead, canal: Canal, contexte: str) -> dict:
        """Messages mock pour démo sans API key."""
        prenom = lead.prenom or "vous"
        localisation = lead.localisation or "votre secteur"
        projet = lead.projet.value

        messages = {
            "relance_douce": f"[MOCK] Bonjour {prenom} ! Suite à notre échange sur votre projet {projet} à {localisation}, avez-vous avancé dans votre réflexion ? {self.settings.agency_name}",
            "comparables_marche": f"[MOCK] Bonjour {prenom}, j'ai des données de marché récentes pour {localisation} qui pourraient vous intéresser. Je vous prépare un bilan ? {self.settings.agency_name}",
            "urgence_acheteurs": f"[MOCK] Bonjour {prenom} ! Nous avons plusieurs acheteurs qualifiés cherchant à {localisation} en ce moment. Toujours vendeur ? {self.settings.agency_name}",
            "nouveaux_biens": f"[MOCK] Bonjour {prenom} ! 3 nouveaux biens correspondent à votre recherche à {localisation}. Souhaitez-vous les fiches ? {self.settings.agency_name}",
            "biens_selection": f"[MOCK] Bonjour {prenom}, j'ai sélectionné des biens dans votre budget à {localisation}. Un appel rapide cette semaine ? {self.settings.agency_name}",
            "reactivation_douce": f"[MOCK] Bonjour {prenom} ! Votre projet {projet} à {localisation} est-il toujours d'actualité ? Le marché a évolué. {self.settings.agency_name}",
            "actualite_marche": f"[MOCK] Bonjour {prenom}, les prix à {localisation} ont bougé. Une estimation gratuite de votre bien vous intéresse ? {self.settings.agency_name}",
            "derniere_chance": f"[MOCK] Bonjour {prenom} ! Dernière nouvelle de notre part — si votre projet {projet} reprend, n'hésitez pas à nous recontacter. {self.settings.agency_name}",
        }

        msg = messages.get(contexte, messages["relance_douce"])

        # Troncature SMS
        if canal == Canal.SMS and len(msg) > 160:
            msg = msg[:157] + "..."

        return {
            "sujet": f"Votre projet immobilier à {localisation}" if canal == Canal.EMAIL else None,
            "message": msg,
            "cta": "Répondez OUI pour un rappel" if canal == Canal.SMS else "Prendre rendez-vous",
            "ton": "chaleureux",
        }

    def _send_message(self, lead: Lead, message_data: dict, canal: Canal) -> bool:
        """Envoie le message via le canal approprié."""
        message = message_data.get("message", "")
        if not message:
            return False

        if canal == Canal.SMS:
            if not lead.telephone:
                return False
            twilio = self._get_twilio()
            client_sms_number = None
            try:
                from memory.database import get_connection
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT twilio_sms_number FROM users WHERE id = %s LIMIT 1",
                        (self.client_id,),
                    ).fetchone()
                    if row:
                        client_sms_number = row["twilio_sms_number"]
            except Exception:
                pass
            result = twilio.send_sms(
                to=twilio.format_french_number(lead.telephone),
                body=message,
                from_number=client_sms_number,
            )
            return result.get("success", False)

        elif canal == Canal.EMAIL:
            if not lead.email:
                # Fallback SMS via Twilio si pas d'email
                if lead.telephone:
                    twilio = self._get_twilio()
                    result = twilio.send_sms(
                        to=twilio.format_french_number(lead.telephone),
                        body=message[:160],
                    )
                    return result.get("success", False)
                return False
            from tools.email_tool import EmailTool
            email_tool = EmailTool()
            result = email_tool.send(
                to_email=lead.email,
                to_name=lead.nom_complet,
                subject=message_data.get("sujet", "Votre projet immobilier"),
                body_text=message,
            )
            return result.get("success", False)

        return False

    def handle_response_requalification(self, lead_id: str, response_message: str) -> dict:
        """
        Détecte si la réponse à un nurturing est positive et requalifie.
        Appelé quand un lead répond à un message de nurturing.

        Returns: {"requalified": bool, "new_score": int, "action": str}
        """
        lead = get_lead(lead_id)
        if not lead:
            return {"requalified": False}

        # Mots-clés positifs simples (heuristique + LLM possible)
        positive_keywords = [
            "oui", "ok", "d'accord", "intéressé", "intéressée", "quand",
            "disponible", "rappel", "rdv", "rendez-vous", "visite",
            "toujours", "je veux", "je souhaite", "contactez", "appelez",
        ]
        negative_patterns = [
            "ne suis plus", "ne suis pas", "pas intéressé", "plus intéressé",
            "non merci", "pas de suite", "annuler", "stop", "désinscri",
            "ne pas", "ça ne m'intéresse", "sans suite",
        ]

        response_lower = response_message.lower()
        has_positive = any(kw in response_lower for kw in positive_keywords)
        has_negative = any(pat in response_lower for pat in negative_patterns)
        is_positive = has_positive and not has_negative

        if is_positive:
            # Remontée du score minimum à 6 (nurturing 14j → qualifié)
            lead.score = max(lead.score, 6)
            lead.statut = LeadStatus.QUALIFIE
            lead.nurturing_sequence = None
            lead.prochain_followup = None
            update_lead(lead)

            add_conversation_message(
                lead_id=lead_id,
                client_id=self.client_id,
                role="user",
                contenu=response_message,
                canal=Canal.SMS,
            )

            logger.info(f"Lead {lead_id} requalifié suite à réponse positive nurturing")

            return {
                "requalified": True,
                "new_score": lead.score,
                "action": "rdv" if lead.score >= 7 else "qualifie",
            }

        return {"requalified": False, "action": "continue_nurturing"}
