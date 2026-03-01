"""
Authentification — signup, login, vérification JWT.
Utilise bcrypt pour les mots de passe et python-jose pour les tokens JWT.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from config.settings import get_settings
from memory.database import get_connection


def signup(email: str, password: str, agency_name: str) -> dict:
    """
    Crée un nouveau compte utilisateur.

    Returns:
        dict avec user_id, email, agency_name, plan
    Raises:
        ValueError si l'email est déjà enregistré
    """
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if existing:
            raise ValueError("Un compte avec cet email existe déjà.")

        user_id = str(uuid.uuid4())
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        conn.execute(
            """INSERT INTO users (id, email, password_hash, agency_name, plan, plan_active)
               VALUES (?, ?, ?, ?, 'Starter', TRUE)""",
            (user_id, email, password_hash, agency_name),
        )

    return {
        "user_id": user_id,
        "email": email,
        "agency_name": agency_name,
        "plan": "Starter",
    }


def login(email: str, password: str) -> str:
    """
    Vérifie les credentials et retourne un JWT token signé.

    Returns:
        JWT token string
    Raises:
        ValueError si les credentials sont invalides ou le compte inactif
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, password_hash, plan, plan_active FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if not row:
        raise ValueError("Email ou mot de passe incorrect.")

    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        raise ValueError("Email ou mot de passe incorrect.")

    if not row["plan_active"]:
        raise ValueError("Compte inactif. Contactez le support PropPilot.")

    settings = get_settings()
    expiry = datetime.now(tz=timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    token = jwt.encode(
        {"sub": row["id"], "plan": row["plan"], "exp": expiry},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token


def verify_token(token: str) -> Optional[dict]:
    """
    Décode et vérifie un JWT token.

    Returns:
        {"user_id": str, "plan": str} si valide, None sinon
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: Optional[str] = payload.get("sub")
        plan: str = payload.get("plan", "Starter")
        if not user_id:
            return None
        return {"user_id": user_id, "plan": plan}
    except JWTError:
        return None
