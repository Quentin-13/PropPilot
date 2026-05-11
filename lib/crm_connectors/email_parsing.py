"""
Connecteur push PropPilot → CRM via email parsing universel.

Envoie un email plain text (PAS HTML) à l'adresse cible du CRM client.
Compatible avec tous les CRM qui importent des leads depuis leur boîte mail
(Netty, Hektor, Modelo Office, Périclès, Krea, etc.).

Sujet : [Lead PropPilot] {nom_prospect} - {type_projet} - {score_label} [ACTION: {label}]
Corps  : champs clés sur lignes séparées, parsing facile côté CRM
Reply-To : email du client PropPilot (pour recevoir les réponses du CRM)
"""
from __future__ import annotations

import logging
from typing import Optional

from lib.crm_connectors.base import CRMConnector

logger = logging.getLogger(__name__)


class EmailParsingConnector(CRMConnector):
    """Connecteur push universel : envoie un email plain text au CRM."""

    connector_type = "email"

    def __init__(
        self,
        target_email: str,
        reply_to_email: str = "",
        crm_label: str = "CRM",
    ):
        self._target_email = target_email
        self._reply_to_email = reply_to_email
        self._crm_label = crm_label

    # ─── Interface publique ────────────────────────────────────────────────────

    def push_lead(self, lead_data: dict) -> bool:
        if not self._target_email:
            logger.error("[Email CRM] Pas d'adresse email cible configurée")
            return False

        subject = self._build_subject(lead_data)
        body = self._build_body(lead_data)

        try:
            return self._send(subject=subject, body=body)
        except Exception as e:
            logger.error("[Email CRM] Envoi échoué : %s", e)
            return False

    def test_connection(self) -> dict:
        if not self._target_email:
            return {"success": False, "message": "Adresse email cible non configurée"}
        return {"success": True, "message": f"Configuration OK — cible : {self._target_email}"}

    # ─── Construction du message ───────────────────────────────────────────────

    def _build_subject(self, lead_data: dict) -> str:
        prenom = lead_data.get("prenom") or ""
        nom = lead_data.get("nom") or ""
        nom_complet = f"{prenom} {nom}".strip() or "Inconnu"
        type_projet = (lead_data.get("type_projet") or "inconnu").capitalize()
        score_label = (lead_data.get("score_label") or "froid").capitalize()
        subject = f"[Lead PropPilot] {nom_complet} - {type_projet} - {score_label}"
        if lead_data.get("next_action_label"):
            subject += f" [ACTION: {lead_data['next_action_label']}]"
        return subject

    def _build_body(self, lead_data: dict) -> str:
        from lib.crm_connectors.apimo_mapping import _budget_str, _surface_str

        budget_str = _budget_str(lead_data)
        surface_str = _surface_str(lead_data)

        lines = [
            "=== LEAD PROPPILOT ===",
            "",
            f"Nom: {lead_data.get('nom') or ''}",
            f"Prénom: {lead_data.get('prenom') or ''}",
            f"Téléphone: {lead_data.get('telephone') or ''}",
            f"Email: {lead_data.get('email') or ''}",
            "",
            f"Type projet: {lead_data.get('type_projet') or ''}",
            f"Budget: {budget_str}" if budget_str else "Budget: ",
            f"Zone: {lead_data.get('zone') or ''}",
            f"Type bien: {lead_data.get('type_bien') or ''}",
            f"Surface: {surface_str}" if surface_str else "Surface: ",
            f"Motivation: {lead_data.get('motivation') or ''}",
            f"Score: {lead_data.get('score_label') or 'froid'}",
            f"Résumé: {lead_data.get('resume') or ''}",
            f"Source: PropPilot",
        ]

        if lead_data.get("next_action_label"):
            lines += [
                "",
                "=== ACTION RECOMMANDÉE ===",
                f"Action recommandée: {lead_data['next_action_label']}",
            ]
            if lead_data.get("next_action_reason"):
                lines.append(f"Pourquoi: {lead_data['next_action_reason']}")

        lines += ["", "=== FIN ==="]
        return "\n".join(lines)

    # ─── Envoi SendGrid ────────────────────────────────────────────────────────

    def _send(self, subject: str, body: str) -> bool:
        from config.settings import get_settings
        s = get_settings()

        if not s.sendgrid_available:
            logger.info("[MOCK][Email CRM] subject=%s → %s", subject[:60], self._target_email)
            return True

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, ReplyTo

            mail = Mail(
                from_email=(s.sendgrid_from_email, s.sendgrid_from_name or "PropPilot"),
                to_emails=self._target_email,
                subject=subject,
                plain_text_content=body,
            )
            # Reply-To → email du client PropPilot pour recevoir les réponses
            if self._reply_to_email:
                mail.reply_to = ReplyTo(self._reply_to_email)

            sg = SendGridAPIClient(s.sendgrid_api_key)
            response = sg.send(mail)
            success = response.status_code in (200, 201, 202)
            if success:
                logger.info("[Email CRM] Envoyé → %s (status %s)", self._target_email, response.status_code)
            else:
                logger.warning("[Email CRM] Échec → %s (status %s)", self._target_email, response.status_code)
            return success
        except Exception as e:
            logger.error("[Email CRM] Erreur SendGrid : %s", e)
            return False
