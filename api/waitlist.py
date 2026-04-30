"""
API Waitlist — inscription liste d'attente PropPilot.

Routes :
    POST /api/waitlist        — Inscription (validation + DB + emails)
    GET  /api/waitlist/count  — Nombre d'inscrits (public)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
import re as _re
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

# ── Rate limiting en mémoire (max 5 inscriptions par IP par heure) ────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()
_RATE_LIMIT = 5
_RATE_WINDOW = 3600  # secondes


def _check_rate_limit(ip: str) -> bool:
    """Retourne True si l'IP est autorisée, False si rate-limitée."""
    now = time.time()
    with _rate_lock:
        timestamps = _rate_store[ip]
        timestamps[:] = [t for t in timestamps if now - t < _RATE_WINDOW]
        if len(timestamps) >= _RATE_LIMIT:
            return False
        timestamps.append(now)
        return True


# ── Schémas ───────────────────────────────────────────────────────────────────

class WaitlistRequest(BaseModel):
    prenom: str = Field(..., min_length=1, max_length=100)
    nom: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=320)
    agence: Optional[str] = Field(default=None, max_length=200)
    type_agence: Optional[Literal["Indépendante", "Réseau", "Franchise", "Mandataire"]] = None
    taille_equipe: Optional[Literal["Solo", "2-5 agents", "6-15 agents", "16+ agents"]] = None
    crm_utilise: Optional[Literal["Hektor", "Apimo", "Netty", "Autre", "Aucun"]] = None
    # Honeypot : doit rester vide (rempli par bots)
    website: Optional[str] = Field(default=None)

    @field_validator("prenom", "nom", "agence", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower() if isinstance(v, str) else v
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Adresse email invalide")
        return v


class WaitlistResponse(BaseModel):
    success: bool
    message: str
    already_registered: bool = False


class WaitlistCountResponse(BaseModel):
    count: int


# ── Helpers email ─────────────────────────────────────────────────────────────

def _html_confirmation(prenom: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"/></head>
<body style="font-family:Inter,sans-serif;background:#f5f5f5;margin:0;padding:20px">
  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:40px">
    <div style="text-align:center;margin-bottom:32px">
      <span style="font-size:32px;font-weight:900;letter-spacing:-1px">
        Prop<span style="color:#a3e635">Pilot</span>
      </span>
    </div>
    <h1 style="color:#09090b;font-size:24px;margin-bottom:16px">
      Bienvenue {prenom} ! 🎉
    </h1>
    <p style="color:#3f3f46;line-height:1.6;margin-bottom:16px">
      Vous êtes maintenant sur la liste d'attente PropPilot.
      Nous vous contacterons en priorité lors du lancement.
    </p>
    <p style="color:#3f3f46;line-height:1.6;margin-bottom:24px">
      <strong>Prochaines étapes :</strong><br>
      → Nous analysons votre profil pour prioriser les intégrations CRM<br>
      → Vous recevrez une invitation personnalisée avant l'ouverture publique<br>
      → Questions ? Répondez directement à cet email
    </p>
    <div style="background:#f4f9e8;border-left:4px solid #a3e635;padding:16px;border-radius:4px;margin-bottom:24px">
      <p style="margin:0;color:#365314;font-size:14px">
        <strong>Rappel :</strong> PropPilot capture automatiquement vos appels,
        les transcrit et enrichit votre CRM — zéro saisie manuelle.
      </p>
    </div>
    <p style="color:#71717a;font-size:14px">
      L'équipe PropPilot<br>
      <a href="mailto:pro.quentingouaze@gmail.com" style="color:#a3e635">pro.quentingouaze@gmail.com</a>
    </p>
  </div>
</body>
</html>
""".strip()


def _html_admin_notification(data: WaitlistRequest) -> str:
    return f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"/></head>
<body style="font-family:Inter,sans-serif;background:#f5f5f5;margin:0;padding:20px">
  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:40px">
    <h1 style="color:#09090b;font-size:20px;margin-bottom:24px">
      Nouvelle inscription waitlist PropPilot
    </h1>
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="padding:8px 0;color:#71717a;width:40%">Prénom</td>
          <td style="padding:8px 0;font-weight:600">{data.prenom}</td></tr>
      <tr><td style="padding:8px 0;color:#71717a">Nom</td>
          <td style="padding:8px 0;font-weight:600">{data.nom}</td></tr>
      <tr><td style="padding:8px 0;color:#71717a">Email</td>
          <td style="padding:8px 0"><a href="mailto:{data.email}" style="color:#a3e635">{data.email}</a></td></tr>
      <tr><td style="padding:8px 0;color:#71717a">Agence</td>
          <td style="padding:8px 0;font-weight:600">{data.agence or '—'}</td></tr>
      <tr><td style="padding:8px 0;color:#71717a">Type</td>
          <td style="padding:8px 0">{data.type_agence or '—'}</td></tr>
      <tr><td style="padding:8px 0;color:#71717a">Équipe</td>
          <td style="padding:8px 0">{data.taille_equipe or '—'}</td></tr>
      <tr><td style="padding:8px 0;color:#71717a">CRM</td>
          <td style="padding:8px 0">{data.crm_utilise or '—'}</td></tr>
    </table>
  </div>
</body>
</html>
""".strip()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=WaitlistResponse, status_code=201)
async def register_waitlist(body: WaitlistRequest, request: Request):
    # Honeypot anti-spam
    if body.website:
        return WaitlistResponse(success=True, message="Inscription enregistrée.")

    # Rate limiting
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    client_ip = client_ip.split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessayez dans une heure.")

    from memory.database import get_connection
    from config.settings import get_settings
    from tools.twilio_tool import EmailTool

    settings = get_settings()

    # Vérification doublon + insertion
    try:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM waitlist WHERE email = %s",
                (body.email,),
            ).fetchone()

            if existing:
                return WaitlistResponse(
                    success=True,
                    message="Vous êtes déjà sur la liste d'attente. Nous vous contacterons prochainement.",
                    already_registered=True,
                )

            conn.execute(
                """
                INSERT INTO waitlist
                    (prenom, nom, email, agence, type_agence, taille_equipe, crm_utilise, source, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    body.prenom,
                    body.nom,
                    body.email,
                    body.agence,
                    body.type_agence,
                    body.taille_equipe,
                    body.crm_utilise,
                    "landing",
                    client_ip,
                ),
            )
    except Exception as e:
        logger.error(f"Erreur inscription waitlist : {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'inscription. Veuillez réessayer.")

    # Envoi emails en background (non-bloquant)
    email_tool = EmailTool()

    # Email confirmation prospect
    email_tool.send(
        to_email=body.email,
        to_name=f"{body.prenom} {body.nom}",
        subject="Bienvenue sur la liste d'attente PropPilot",
        body_text=f"Bonjour {body.prenom}, vous êtes inscrit(e) sur la liste d'attente PropPilot.",
        body_html=_html_confirmation(body.prenom),
    )

    # Email notification admin
    email_tool.send(
        to_email=settings.admin_notification_email,
        to_name="Admin PropPilot",
        subject=f"Nouvelle inscription waitlist : {body.prenom} {body.nom}",
        body_text=f"Nouvel inscrit : {body.prenom} {body.nom} — {body.agence or '—'} ({body.email})",
        body_html=_html_admin_notification(body),
    )

    logger.info(f"Waitlist inscription : {body.email} — {body.agence or '—'}")
    return WaitlistResponse(
        success=True,
        message=f"Merci {body.prenom} ! Vous êtes sur la liste d'attente. Consultez votre boîte mail.",
    )


@router.get("/count", response_model=WaitlistCountResponse)
async def waitlist_count():
    from memory.database import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM waitlist").fetchone()
            return WaitlistCountResponse(count=row[0] if row else 0)
    except Exception:
        return WaitlistCountResponse(count=0)
