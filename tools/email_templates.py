"""
Templates emails transactionnels PropPilot.
Chaque fonction retourne {"subject": str, "html": str, "text": str}.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# ─── CSS & structure de base ──────────────────────────────────────────────────

_BASE_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; background: #f0f4f8; color: #1e293b; }
  .wrapper { max-width: 600px; margin: 32px auto; background: #ffffff;
             border-radius: 12px; overflow: hidden;
             box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
  .header { background: #1a3a5c; padding: 32px; text-align: center; }
  .header-logo { font-size: 32px; margin-bottom: 8px; }
  .header-title { color: #ffffff; font-size: 22px; font-weight: 700; margin-bottom: 4px; }
  .header-sub { color: rgba(255,255,255,0.7); font-size: 13px; }
  .body { padding: 36px 40px; }
  .body h2 { font-size: 20px; font-weight: 700; color: #1a3a5c; margin-bottom: 16px; }
  .body p { font-size: 15px; line-height: 1.7; color: #374151; margin-bottom: 14px; }
  .body ul { padding-left: 0; list-style: none; margin-bottom: 20px; }
  .body ul li { font-size: 14px; color: #374151; padding: 6px 0;
                border-bottom: 1px solid #f1f5f9; display: flex; gap: 10px; }
  .body ul li:last-child { border-bottom: none; }
  .info-box { background: #f0f7ff; border-left: 4px solid #3b82f6;
              border-radius: 6px; padding: 16px 20px; margin: 20px 0; }
  .info-box p { margin: 0; font-size: 14px; }
  .warning-box { background: #fffbeb; border-left: 4px solid #f59e0b;
                 border-radius: 6px; padding: 16px 20px; margin: 20px 0; }
  .warning-box p { margin: 0; font-size: 14px; }
  .danger-box { background: #fff1f2; border-left: 4px solid #ef4444;
                border-radius: 6px; padding: 16px 20px; margin: 20px 0; }
  .danger-box p { margin: 0; font-size: 14px; }
  .stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }
  .stat-card { background: #f8fafc; border-radius: 8px; padding: 14px;
               text-align: center; border: 1px solid #e2e8f0; }
  .stat-value { font-size: 28px; font-weight: 800; color: #1a3a5c; display: block; }
  .stat-label { font-size: 11px; color: #64748b; text-transform: uppercase;
                letter-spacing: 0.05em; margin-top: 4px; }
  .progress-bar { background: #e2e8f0; border-radius: 100px; height: 8px; margin: 8px 0 4px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 100px; }
  .cta-block { text-align: center; margin: 28px 0; }
  .cta { display: inline-block; padding: 14px 32px; background: #3b82f6; color: #ffffff;
         text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px;
         letter-spacing: 0.02em; }
  .cta-gold { background: #f59e0b; color: #1e293b; }
  .cta-danger { background: #ef4444; }
  .divider { border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }
  .footer { background: #f8fafc; padding: 20px 40px; border-top: 1px solid #e2e8f0; }
  .footer p { font-size: 12px; color: #94a3b8; line-height: 1.6; margin: 0; text-align: center; }
  .footer a { color: #3b82f6; text-decoration: none; }
"""


def _base_html(header_emoji: str, header_title: str, header_sub: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>{_BASE_CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div class="header-logo">{header_emoji}</div>
    <div class="header-title">{header_title}</div>
    <div class="header-sub">{header_sub}</div>
  </div>
  <div class="body">
    {body}
  </div>
  <div class="footer">
    <p>
      🏠 <strong>PropPilot</strong> — L'IA pour les agences immobilières françaises<br>
      Questions ? <a href="mailto:contact@proppilot.fr">contact@proppilot.fr</a><br>
      <a href="mailto:contact@proppilot.fr?subject=Désabonnement emails PropPilot">Se désabonner</a>
    </p>
  </div>
</div>
</body>
</html>"""


# ─── Email 1 — Bienvenue après inscription ────────────────────────────────────

def welcome_signup(agency_name: str, plans_url: str = "https://proppilot-dashboard-production.up.railway.app/?auth=signup") -> dict:
    """Email envoyé après POST /auth/signup, avant paiement."""
    subject = f"Bienvenue sur PropPilot, {agency_name} 👋"

    body = f"""
    <h2>Bonjour {agency_name}, bienvenue dans PropPilot !</h2>
    <p>Votre compte a été créé avec succès. Vous êtes à quelques secondes de rejoindre
    200+ agences et mandataires qui ne perdent plus jamais un lead la nuit.</p>

    <p><strong>Votre équipe de 7 collaborateurs IA vous attend :</strong></p>
    <ul>
      <li>🎯 <strong>Léa</strong> — Qualifie vos leads entrants 24h/24</li>
      <li>📱 <strong>Marc</strong> — Gère vos séquences de nurturing SMS</li>
      <li>📞 <strong>Sophie</strong> — Effectue et reçoit vos appels voix</li>
      <li>📝 <strong>Hugo</strong> — Rédige vos annonces immobilières SEO</li>

      <li>📊 <strong>Thomas</strong> — Estime vos biens via DVF</li>
      <li>🔍 <strong>Julie</strong> — Détecte les anomalies dans vos dossiers</li>
    </ul>

    <div class="info-box">
      <p>💡 <strong>Prochaine étape :</strong> choisissez votre forfait pour activer votre équipe IA.
      Tous les agents sont inclus dès le premier forfait.</p>
    </div>

    <div class="cta-block">
      <a href="{plans_url}" class="cta">Choisir mon forfait →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Garantie ROI 60 jours — si vous n'obtenez pas au moins +2 RDV/mois, nous vous remboursons.
      Des questions ? Répondez à cet email ou écrivez à
      <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>.
    </p>
    """

    text = f"""Bonjour {agency_name}, bienvenue dans PropPilot !

Votre compte a été créé avec succès.

Votre équipe de 5 collaborateurs IA vous attend :
- Léa : qualifie vos leads 24h/24
- Marc : nurturing SMS automatisé
- Hugo : rédaction annonces SEO
- Thomas : estimation DVF
- Julie : détection anomalies dossiers

Prochaine étape : choisissez votre forfait → {plans_url}

Garantie ROI 60 jours incluse.
Questions : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("🏠", "PropPilot", "L'IA pour les agences immobilières françaises", body),
        "text": text,
    }


# ─── Email 2 — Confirmation de paiement ──────────────────────────────────────

def payment_confirmed(
    agency_name: str,
    plan: str,
    renewal_date: str | None = None,
    dashboard_url: str = "https://proppilot-dashboard-production.up.railway.app/",
) -> dict:
    """Email envoyé après checkout.session.completed."""
    if renewal_date is None:
        renewal_date = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")

    subject = f"Votre abonnement PropPilot {plan} est activé ✅"

    # Limites par plan pour le récap
    _plan_limits = {
        "Indépendant": "600 min voix · 3 000 SMS · 1 utilisateur",
        "Starter":     "1 500 min voix · 8 000 SMS · 3 utilisateurs",
        "Pro":         "3 000 min voix · 15 000 SMS · 6 utilisateurs",
        "Elite":       "Voix & SMS illimités · Utilisateurs illimités",
    }
    limits_line = _plan_limits.get(plan, "Voir tableau de bord")

    body = f"""
    <h2>Paiement confirmé — forfait {plan} activé !</h2>
    <p>Bonjour {agency_name}, votre abonnement est désormais actif.
    Vos 7 agents IA travaillent pour vous dès maintenant.</p>

    <div class="info-box">
      <p>
        📦 <strong>Forfait :</strong> {plan}<br>
        📊 <strong>Limites mensuelles :</strong> {limits_line}<br>
        🗓️ <strong>Prochain renouvellement :</strong> {renewal_date}
      </p>
    </div>

    <p>Accédez à votre tableau de bord pour suivre en temps réel l'activité de vos agents,
    vos leads qualifiés et votre progression vers la garantie ROI.</p>

    <div class="cta-block">
      <a href="{dashboard_url}" class="cta">Accéder à mon tableau de bord →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Vous pouvez gérer votre abonnement (factures, changement de carte, résiliation)
      depuis la page <strong>Facturation</strong> du tableau de bord.<br>
      Besoin d'aide ? <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>
    </p>
    """

    text = f"""Paiement confirmé — forfait {plan} activé !

Bonjour {agency_name},

Votre abonnement est actif :
- Forfait : {plan}
- Limites mensuelles : {limits_line}
- Prochain renouvellement : {renewal_date}

Accédez à votre tableau de bord : {dashboard_url}

Gestion abonnement (factures, carte) depuis la page Facturation.
Questions : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("✅", f"Forfait {plan} activé !", "Votre équipe IA est prête", body),
        "text": text,
    }


# ─── Email 3 — Alerte quota 80% ───────────────────────────────────────────────

def quota_alert_80(
    agency_name: str,
    action_label: str,
    used: float,
    limit: float,
    tier: str,
    upgrade_url: str = "mailto:contact@proppilot.fr?subject=Upgrade forfait PropPilot",
) -> dict:
    """Email envoyé quand voice_minutes ou SMS dépasse 80%."""
    pct = int(used / limit * 100) if limit > 0 else 0
    remaining = max(0, int(limit - used))
    bar_color = "#f59e0b" if pct < 90 else "#ef4444"

    subject = f"⚠️ Vous approchez de votre limite {action_label} PropPilot"

    body = f"""
    <h2>⚠️ {pct}% de votre quota {action_label} utilisé</h2>
    <p>Bonjour {agency_name}, vous approchez de votre limite mensuelle de <strong>{action_label}</strong>
    sur votre forfait <strong>{tier}</strong>.</p>

    <div class="warning-box">
      <p>
        📊 Utilisé : <strong>{int(used)}</strong> / {int(limit)}<br>
        ⏳ Restant : <strong>{remaining}</strong> ce mois<br>
        📈 Progression : <strong>{pct}%</strong>
      </p>
    </div>

    <div class="progress-bar">
      <div class="progress-fill" style="width:{min(pct,100)}%;background:{bar_color};"></div>
    </div>

    <p>À ce rythme, vous risquez de manquer des leads ou des follow-ups avant la fin du mois.
    Passez au forfait supérieur pour continuer sans interruption.</p>

    <div class="cta-block">
      <a href="{upgrade_url}" class="cta cta-gold">Upgrader mon forfait →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Votre quota se renouvelle automatiquement le 1er de chaque mois.<br>
      Questions : <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>
    </p>
    """

    text = f"""⚠️ {pct}% de votre quota {action_label} utilisé

Bonjour {agency_name},

Vous approchez de votre limite mensuelle de {action_label} ({tier}).

Utilisé : {int(used)} / {int(limit)}
Restant : {remaining} ce mois

Pour upgrader : {upgrade_url}

Votre quota se renouvelle le 1er de chaque mois.
Questions : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("⚠️", "Alerte quota PropPilot", f"Forfait {tier}", body),
        "text": text,
    }


# ─── Email 4 — Échec de paiement ──────────────────────────────────────────────

def payment_failed(
    agency_name: str,
    portal_url: str = "https://billing.stripe.com/",
) -> dict:
    """Email envoyé après invoice.payment_failed."""
    subject = "⚠️ Problème de paiement PropPilot"

    body = f"""
    <h2>Un problème est survenu avec votre paiement</h2>
    <p>Bonjour {agency_name}, nous n'avons pas pu traiter votre paiement mensuel PropPilot.</p>

    <div class="danger-box">
      <p>⛔ Sans mise à jour de votre moyen de paiement, votre accès aux agents IA sera
      suspendu dans <strong>7 jours</strong>.</p>
    </div>

    <p>Pour régulariser votre situation en quelques secondes, cliquez sur le bouton ci-dessous
    pour accéder au portail de facturation Stripe et mettre à jour votre carte bancaire.</p>

    <div class="cta-block">
      <a href="{portal_url}" class="cta cta-danger">Mettre à jour mon paiement →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Si vous pensez qu'il s'agit d'une erreur ou avez besoin d'aide, contactez-nous immédiatement :
      <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>
    </p>
    """

    text = f"""⚠️ Problème de paiement PropPilot

Bonjour {agency_name},

Nous n'avons pas pu traiter votre paiement mensuel.

Sans mise à jour, votre accès sera suspendu dans 7 jours.

Mettez à jour votre paiement : {portal_url}

Besoin d'aide : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("⚠️", "Problème de paiement", "Action requise", body),
        "text": text,
    }


# ─── Email 5 — Abonnement annulé ─────────────────────────────────────────────

def subscription_cancelled(
    agency_name: str,
    end_date: str | None = None,
    reactivate_url: str = "https://proppilot-dashboard-production.up.railway.app/?auth=login",
) -> dict:
    """Email envoyé après customer.subscription.deleted."""
    if end_date is None:
        end_date = datetime.now().strftime("%d/%m/%Y")

    subject = "Votre abonnement PropPilot a été annulé"

    body = f"""
    <h2>Votre abonnement a été annulé</h2>
    <p>Bonjour {agency_name}, nous confirmons l'annulation de votre abonnement PropPilot.</p>

    <div class="warning-box">
      <p>
        📅 <strong>Date de fin d'accès :</strong> {end_date}<br>
        🔒 Après cette date, vos agents IA seront désactivés et vos données conservées 90 jours.
      </p>
    </div>

    <p>Vous souhaitez changer d'avis ? Réactivez votre abonnement à tout moment depuis votre
    espace client. Tous vos leads et données sont conservés.</p>

    <div class="cta-block">
      <a href="{reactivate_url}" class="cta">Réactiver mon abonnement →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Si vous avez annulé par erreur ou avez des questions, répondez à cet email ou contactez-nous :
      <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a><br>
      Vos données sont conservées 90 jours après la fin d'accès.
    </p>
    """

    text = f"""Votre abonnement PropPilot a été annulé

Bonjour {agency_name},

Votre abonnement PropPilot est annulé.

Date de fin d'accès : {end_date}
Après cette date, vos agents IA seront désactivés.
Vos données sont conservées 90 jours.

Réactiver votre abonnement : {reactivate_url}

Questions : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("😢", "Abonnement annulé", "Nous espérons vous revoir bientôt", body),
        "text": text,
    }


# ─── Email 6 — Rapport hebdomadaire ──────────────────────────────────────────

def weekly_report(
    agency_name: str,
    week_start: str,
    stats: dict,
    dashboard_url: str = "https://proppilot-dashboard-production.up.railway.app/",
) -> dict:
    """
    Email rapport hebdo envoyé tous les lundis à 8h.

    stats dict attendu :
      leads_recus, leads_qualifies, appels, rdv, mandats, roi_estime
    """
    subject = f"📊 Votre rapport PropPilot — semaine du {week_start}"

    leads_recus    = stats.get("leads_recus", 0)
    leads_qualifies = stats.get("leads_qualifies", 0)
    appels         = stats.get("appels", 0)
    rdv            = stats.get("rdv", 0)
    mandats        = stats.get("mandats", 0)
    roi_estime     = stats.get("roi_estime", 0)

    taux_qual = int(leads_qualifies / leads_recus * 100) if leads_recus > 0 else 0

    body = f"""
    <h2>📊 Rapport de la semaine du {week_start}</h2>
    <p>Bonjour {agency_name}, voici le bilan d'activité de vos agents IA cette semaine.</p>

    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-value">{leads_recus}</span>
        <span class="stat-label">Leads reçus</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{leads_qualifies}</span>
        <span class="stat-label">Leads qualifiés</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{taux_qual}%</span>
        <span class="stat-label">Taux qualification</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{appels}</span>
        <span class="stat-label">Appels effectués</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{rdv}</span>
        <span class="stat-label">RDV bookés</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{mandats}</span>
        <span class="stat-label">Mandats</span>
      </div>
    </div>

    {f'<div class="info-box"><p>💰 <strong>ROI estimé cette semaine :</strong> {roi_estime:,.0f}€</p></div>' if roi_estime > 0 else ""}

    <p>Consultez votre tableau de bord pour le détail complet : leads par statut,
    historique des conversations, et progression vers la garantie ROI.</p>

    <div class="cta-block">
      <a href="{dashboard_url}" class="cta">Voir le tableau de bord →</a>
    </div>

    <hr class="divider">
    <p style="font-size:13px;color:#64748b;">
      Ce rapport est envoyé automatiquement chaque lundi à 8h.<br>
      Pour modifier vos préférences ou poser une question :
      <a href="mailto:contact@proppilot.fr" style="color:#3b82f6;">contact@proppilot.fr</a>
    </p>
    """

    text = f"""Rapport PropPilot — semaine du {week_start}

Bonjour {agency_name},

Activité de vos agents IA cette semaine :
- Leads reçus      : {leads_recus}
- Leads qualifiés  : {leads_qualifies} ({taux_qual}%)
- Appels effectués : {appels}
- RDV bookés       : {rdv}
- Mandats          : {mandats}
{f'- ROI estimé       : {roi_estime:,.0f}€' if roi_estime > 0 else ''}

Tableau de bord complet : {dashboard_url}

Ce rapport est envoyé chaque lundi à 8h.
Questions : contact@proppilot.fr

L'équipe PropPilot"""

    return {
        "subject": subject,
        "html": _base_html("📊", "Rapport hebdomadaire", f"Semaine du {week_start}", body),
        "text": text,
    }
