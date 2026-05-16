"""
Connecteur push PropPilot → CRM via email parsing universel.

Envoie un email plain text (PAS HTML) à l'adresse cible du CRM client.
Compatible avec tous les CRM qui importent des leads depuis leur boîte mail
(Netty, Hektor, Modelo Office, Périclès, Krea, etc.).

Sujet  : [PropPilot] Mise à jour lead — {nom ou tel} — {chaud/tiède/froid}
Corps  : champs structurés + historique conversations pour parsing CRM
Reply-To : email du client PropPilot (pour recevoir les réponses du CRM)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from config.settings import get_settings
from lib.crm_connectors.base import CRMConnector

logger = logging.getLogger(__name__)

_STATUT_DISPLAY = {"chaud": "chaud", "tiede": "tiède", "tiède": "tiède", "froid": "froid"}


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

    def push_test_lead(self, lead_data: dict) -> bool:
        """Envoi test avec sujet [TEST PropPilot] — utilisé depuis le dashboard."""
        if not self._target_email:
            return False
        body = self._build_body(lead_data)
        return self._send("[TEST PropPilot] Remontée CRM", body)

    # ─── Construction du message ───────────────────────────────────────────────

    def _build_subject(self, lead_data: dict) -> str:
        prenom = lead_data.get("prenom") or ""
        nom = lead_data.get("nom") or ""
        nom_complet = f"{prenom} {nom}".strip()
        ident = nom_complet or lead_data.get("telephone") or "Inconnu"
        statut_raw = lead_data.get("statut") or lead_data.get("score_label") or "froid"
        statut = _STATUT_DISPLAY.get(statut_raw, statut_raw)
        return f"[PropPilot] Mise à jour lead — {ident} — {statut}"

    def _build_body(self, lead_data: dict) -> str:
        from lib.crm_connectors.apimo_mapping import _budget_str, _surface_str

        def _s(val) -> str:
            """Retourne une chaîne propre, jamais 'None'."""
            if val is None:
                return ""
            s = str(val).strip()
            return s if s.lower() != "none" else ""

        lead_id    = _s(lead_data.get("id"))
        client_id  = _s(lead_data.get("client_id"))
        updated_at = _s(lead_data.get("updated_at")) or datetime.now().strftime("%Y-%m-%d %H:%M")
        lead_type  = _s(lead_data.get("lead_type")) or "acheteur"
        score      = lead_data.get("score")
        score_str  = f"{score}/24" if score is not None else ""
        statut_raw = lead_data.get("statut") or lead_data.get("score_label") or "froid"
        statut     = _STATUT_DISPLAY.get(statut_raw, statut_raw)
        nom        = _s(lead_data.get("nom"))
        prenom     = _s(lead_data.get("prenom"))
        telephone  = _s(lead_data.get("telephone"))
        email_lead = _s(lead_data.get("email"))
        projet     = _s(lead_data.get("type_projet"))
        budget     = _budget_str(lead_data) or ""
        zone       = _s(lead_data.get("zone"))
        type_bien  = _s(lead_data.get("type_bien"))
        surface    = _surface_str(lead_data) or ""
        urgence    = _s(lead_data.get("urgence"))
        motivation = _s(lead_data.get("motivation"))
        objections = _s(lead_data.get("objections"))
        financement = _s(lead_data.get("financement_str"))
        resume     = _s(lead_data.get("resume"))
        prochaine_action = _s(lead_data.get("next_action_label"))
        raison     = _s(lead_data.get("next_action_reason"))
        historique = _s(lead_data.get("conversation_history")) or "(Aucun échange enregistré)"

        def _opt(label: str, val: str) -> list[str]:
            """Retourne [label: val] seulement si val est non vide."""
            return [f"{label}: {val}"] if val else []

        lines: list[str] = [
            f"PROPPILOT_LEAD_ID: {lead_id}",
            f"PROPPILOT_CLIENT_ID: {client_id}",
            f"PROPPILOT_UPDATED_AT: {updated_at}",
            "",
            f"TYPE_LEAD: {lead_type}",
            f"SCORE: {score_str}",
            f"STATUT: {statut}",
            "",
            f"NOM: {nom}",
            f"PRENOM: {prenom}",
            f"TELEPHONE: {telephone}",
        ]
        if email_lead:
            lines.append(f"EMAIL: {email_lead}")

        # Section projet — champs optionnels
        project_fields = (
            _opt("PROJET", projet)
            + _opt("BUDGET", budget)
            + _opt("ZONE", zone)
            + _opt("TYPE_BIEN", type_bien)
            + _opt("SURFACE", surface)
        )
        if project_fields:
            lines += [""] + project_fields

        # Section qualification — champs optionnels
        qual_fields = (
            _opt("URGENCE", urgence)
            + _opt("MOTIVATION", motivation)
            + _opt("OBJECTIONS", objections)
            + _opt("FINANCEMENT", financement)
        )
        if qual_fields:
            lines += [""] + qual_fields

        # Résumé (toujours présent)
        lines += ["", "RESUME:", resume]

        # Actions — optionnelles
        action_fields = (
            _opt("PROCHAINE_ACTION", prochaine_action)
            + _opt("RAISON", raison)
        )
        if action_fields:
            lines += [""] + action_fields

        lines += [
            "",
            "HISTORIQUE_CONVERSATIONS:",
            historique,
            "---",
            "PropPilot — Mise à jour automatique",
        ]
        return "\n".join(lines)

    # ─── Envoi : Resend → SendGrid → SMTP → mock ──────────────────────────────

    def _send(self, subject: str, body: str) -> bool:
        s = get_settings()

        if not s.resend_available and not s.sendgrid_available and not s.smtp_available:
            logger.info("[MOCK][Email CRM] subject=%s → %s", subject[:60], self._target_email)
            return True

        if s.resend_available:
            ok = self._send_via_resend(subject, body, s)
            if ok:
                return True
            logger.warning("[Email CRM] Resend échoué — bascule sur SendGrid")

        if s.sendgrid_available:
            ok = self._send_via_sendgrid(subject, body, s)
            if ok:
                return True
            logger.warning("[Email CRM] SendGrid échoué — bascule sur SMTP")

        if s.smtp_available:
            return self._send_via_smtp(subject, body, s)

        return False

    def _send_via_resend(self, subject: str, body: str, s) -> bool:
        import json
        import urllib.request

        from_field = f"{s.resend_from_name} <{s.resend_from_email}>" if s.resend_from_name else s.resend_from_email
        payload = json.dumps({
            "from": from_field,
            "to": [self._target_email],
            "subject": subject,
            "text": body,
        }).encode()

        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {s.resend_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
            success = status in (200, 201, 202)
            if success:
                logger.info("[Email CRM][Resend] Envoyé → %s (status %s)", self._target_email, status)
            else:
                logger.warning("[Email CRM][Resend] Échec → %s (status %s)", self._target_email, status)
            return success
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode(errors="replace")[:500]
            except Exception:
                err_body = "(body illisible)"
            logger.error(
                "[Email CRM][Resend] HTTP %s from=%s to=%s body=%s",
                e.code, s.resend_from_email, self._target_email, err_body,
            )
            return False
        except Exception as e:
            logger.error("[Email CRM][Resend] Erreur : %s", e)
            return False

    def _send_via_sendgrid(self, subject: str, body: str, s) -> bool:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, ReplyTo

            mail = Mail(
                from_email=(s.sendgrid_from_email, s.sendgrid_from_name or "PropPilot"),
                to_emails=self._target_email,
                subject=subject,
                plain_text_content=body,
            )
            if self._reply_to_email:
                mail.reply_to = ReplyTo(self._reply_to_email)

            sg = SendGridAPIClient(s.sendgrid_api_key)
            response = sg.send(mail)
            success = response.status_code in (200, 201, 202)
            if success:
                logger.info("[Email CRM][SendGrid] Envoyé → %s (status %s)", self._target_email, response.status_code)
            else:
                logger.warning("[Email CRM][SendGrid] Échec → %s (status %s body=%s)", self._target_email, response.status_code, response.body)
            return success
        except Exception as e:
            logger.error("[Email CRM][SendGrid] Erreur : %s", e)
            return False

    def _send_via_smtp(self, subject: str, body: str, s) -> bool:
        import smtplib
        from email.mime.text import MIMEText
        from email.utils import formataddr

        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = formataddr((s.smtp_from_name or "PropPilot", s.smtp_from_email))
            msg["To"] = self._target_email
            if self._reply_to_email:
                msg["Reply-To"] = self._reply_to_email

            if s.smtp_port == 465:
                smtp_cls = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15)
            else:
                smtp_cls = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)

            with smtp_cls as server:
                if s.smtp_port != 465 and s.smtp_use_tls:
                    server.starttls()
                server.login(s.smtp_user, s.smtp_password)
                server.sendmail(s.smtp_from_email, [self._target_email], msg.as_string())

            logger.info("[Email CRM][SMTP] Envoyé → %s via %s", self._target_email, s.smtp_host)
            return True
        except Exception as e:
            logger.error("[Email CRM][SMTP] Erreur : %s", e)
            return False
