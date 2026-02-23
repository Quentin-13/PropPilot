"""
EmailTool — Emails HTML transactionnels SendGrid/SMTP avec mock.
"""
from __future__ import annotations

import logging
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class EmailTool:
    """Wrapper SendGrid + fallback SMTP + mock."""

    TEMPLATE_BASE = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{subject}</title>
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #f5f5f5; margin: 0; padding: 0; }}
  .container {{ max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .header {{ background: #1a3a5c; color: white; padding: 24px 32px; }}
  .header h1 {{ margin: 0; font-size: 22px; font-weight: 600; }}
  .header p {{ margin: 4px 0 0; opacity: 0.8; font-size: 14px; }}
  .body {{ padding: 32px; color: #333; line-height: 1.6; }}
  .cta {{ display: inline-block; margin: 24px 0; padding: 14px 28px; background: #e67e22; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 16px; }}
  .footer {{ background: #f9f9f9; padding: 16px 32px; font-size: 12px; color: #888; border-top: 1px solid #eee; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{agence_nom}</h1>
    <p>Votre conseiller immobilier personnel</p>
  </div>
  <div class="body">
    {body_html}
    {cta_html}
  </div>
  <div class="footer">
    {agence_nom} — Ce message vous est envoyé car vous avez contacté notre agence.<br>
    Pour vous désinscrire : <a href="mailto:{from_email}?subject=Désabonnement">cliquez ici</a>
  </div>
</div>
</body>
</html>
"""

    def __init__(self):
        self.settings = get_settings()
        self.mock_mode = not self.settings.sendgrid_available

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        cta_url: Optional[str] = None,
        cta_label: str = "Prendre rendez-vous",
    ) -> dict:
        """
        Envoie un email transactionnel.

        Args:
            to_email: Adresse destinataire
            to_name: Nom du destinataire
            subject: Sujet de l'email
            body_text: Corps texte plain
            body_html: Corps HTML (optionnel, auto-généré si absent)
            cta_url: URL bouton CTA (optionnel)
            cta_label: Texte du bouton CTA

        Returns:
            {"success": bool, "mock": bool, "error": Optional[str]}
        """
        # Génération HTML si absent
        if not body_html:
            body_html_content = "".join(f"<p>{line}</p>" for line in body_text.split("\n") if line.strip())
            cta_html = f'<a href="{cta_url}" class="cta">{cta_label}</a>' if cta_url else ""

            body_html = self.TEMPLATE_BASE.format(
                subject=subject,
                agence_nom=self.settings.agency_name,
                body_html=body_html_content,
                cta_html=cta_html,
                from_email=self.settings.sendgrid_from_email,
            )

        if self.mock_mode:
            logger.info(
                f"[MOCK EMAIL] To: {to_email} ({to_name}) | "
                f"Subject: {subject} | Body: {body_text[:80]}..."
            )
            return {
                "success": True,
                "mock": True,
                "to": to_email,
                "subject": subject,
            }

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            mail = Mail(
                from_email=(self.settings.sendgrid_from_email, self.settings.sendgrid_from_name),
                to_emails=to_email,
                subject=subject,
                plain_text_content=body_text,
                html_content=body_html,
            )
            sg = SendGridAPIClient(self.settings.sendgrid_api_key)
            response = sg.send(mail)
            success = response.status_code in (200, 201, 202)
            logger.info(f"Email envoyé à {to_email} — statut {response.status_code}")
            return {"success": success, "status_code": response.status_code, "mock": False}

        except Exception as e:
            logger.error(f"Erreur envoi email : {e}")
            return {"success": False, "error": str(e), "mock": False}

    def send_limit_alert(self, to_email: str, to_name: str, action: str, tier: str) -> dict:
        """Email automatique quand un client atteint 100% de son quota."""
        from config.tier_limits import ACTION_LABELS
        action_label = ACTION_LABELS.get(action, action)

        subject = f"🚫 Limite atteinte : {action_label} — vos agents sont en pause"
        body = f"""Bonjour {to_name},

Vous avez atteint votre limite mensuelle de {action_label} sur votre forfait {tier}.

Vos agents IA sont actuellement en pause pour cette fonctionnalité.

Pour reprendre immédiatement et continuer à qualifier vos leads, passez au forfait supérieur.

À bientôt,
L'équipe PropPilot"""

        return self.send(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_text=body,
            cta_url="https://proppilot.fr/upgrade",
            cta_label="Passer au forfait supérieur",
        )
