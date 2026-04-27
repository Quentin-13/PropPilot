"""
Configuration centrale — lecture .env via Pydantic Settings v2.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

_log = logging.getLogger(__name__)

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Anthropic
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-sonnet-4-5"


    # Twilio — pool de numéros 07 dédiés (1 par client)
    twilio_account_sid: Optional[str] = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_sms_number: Optional[str] = Field(default=None, alias="TWILIO_SMS_NUMBER")
    twilio_whatsapp_number: str = Field(default="+14155238886", alias="TWILIO_WHATSAPP_NUMBER")
    # Pool multi-clients : numéros 07 disponibles, séparés par des virgules
    twilio_available_numbers_raw: str = Field(default="", alias="TWILIO_AVAILABLE_NUMBERS")

    @property
    def twilio_available_numbers(self) -> list[str]:
        """Parse la liste des numéros Twilio disponibles depuis la variable d'env."""
        return [n.strip() for n in (self.twilio_available_numbers_raw or "").split(",") if n.strip()]

    # SendGrid
    sendgrid_api_key: Optional[str] = Field(default=None, alias="SENDGRID_API_KEY")
    sendgrid_from_email: str = Field(default="noreply@proppilot.fr", alias="SENDGRID_FROM_EMAIL")
    sendgrid_from_name: str = Field(default="PropPilot", alias="SENDGRID_FROM_NAME")

    # Google Calendar
    google_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_ID")
    google_service_account_json: Optional[str] = Field(default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/calendar/callback",
        alias="GOOGLE_REDIRECT_URI",
    )
    google_scopes: list[str] = Field(
        default=["https://www.googleapis.com/auth/calendar"],
        alias="GOOGLE_SCOPES",
    )

    # Base de données
    database_path: str = Field(default="./data/agency.db", alias="DATABASE_PATH")
    database_url: str = Field(default="postgresql://localhost/proppilot", alias="DATABASE_URL")

    # JWT
    jwt_secret_key: str = Field(default="change-this-secret-in-production", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_hours: int = Field(default=24, alias="JWT_EXPIRE_HOURS")

    # Configuration Agence
    agency_name: str = Field(default="", alias="AGENCY_NAME")
    agency_tier: Literal["Indépendant", "Starter", "Pro", "Elite"] = Field(default="Starter", alias="AGENCY_TIER")
    agency_client_id: str = Field(default="client_demo", alias="AGENCY_CLIENT_ID")
    agency_commission_rate: float = Field(default=0.05, alias="AGENCY_COMMISSION_RATE")
    agency_average_price: float = Field(default=280000.0, alias="AGENCY_AVERAGE_PRICE")

    # URL de l'API FastAPI (pour le dashboard)
    api_url: str = Field(default="http://localhost:8000", alias="API_URL")

    # Stripe
    stripe_secret_key: Optional[str] = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: Optional[str] = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: Optional[str] = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")

    # Sécurité
    health_secret: Optional[str] = Field(default=None, alias="HEALTH_SECRET")

    # Admin
    admin_password: str = Field(default="changeme", alias="ADMIN_PASSWORD")

    # Mode
    debug: bool = Field(default=False, alias="DEBUG")
    mock_mode: Literal["auto", "always", "never"] = Field(default="auto", alias="MOCK_MODE")
    testing: bool = Field(default=False, alias="TESTING")
    enable_legacy_agents: bool = Field(default=False, alias="ENABLE_LEGACY_AGENTS")

    @field_validator("agency_tier", mode="before")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        valid = {"Indépendant", "Starter", "Pro", "Elite"}
        if v not in valid:
            return "Starter"
        return v

    @property
    def twilio_sms_available(self) -> bool:
        if self.testing or self.mock_mode == "always":
            return False
        return bool(self.twilio_account_sid and
                    self.twilio_auth_token and
                    self.twilio_sms_number)

    @property
    def twilio_available(self) -> bool:
        if self.testing or self.mock_mode == "always":
            return False
        if self.mock_mode == "never":
            return True
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def anthropic_available(self) -> bool:
        return bool(self.anthropic_api_key)


    @property
    def google_oauth_available(self) -> bool:
        if self.testing or self.mock_mode == "always":
            return False
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def sendgrid_available(self) -> bool:
        if self.testing or self.mock_mode == "always":
            return False
        return bool(self.sendgrid_api_key)

    @property
    def stripe_available(self) -> bool:
        if self.testing or self.mock_mode == "always":
            return False
        return bool(self.stripe_secret_key)

    def ensure_data_dir(self) -> Path:
        """Crée le répertoire data si inexistant."""
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path.parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings — chargé une seule fois."""
    return Settings()


def assign_twilio_number(user_id: str) -> Optional[str]:
    """
    Attribue un numéro Twilio libre à un client.
    Attribution atomique via CTE UPDATE…RETURNING : une seule instruction SQL
    protège contre les races concurrentes. La contrainte UNIQUE DB est le filet.
    Retourne le numéro assigné, ou None si le pool est épuisé / collision.
    """
    settings = get_settings()
    pool = settings.twilio_available_numbers
    if not pool:
        return None

    from memory.database import get_connection

    try:
        with get_connection() as conn:
            # Idempotent : renvoie le numéro déjà attribué
            row = conn.execute(
                "SELECT twilio_sms_number FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()
            if row and row["twilio_sms_number"]:
                return row["twilio_sms_number"]

            # Atomic : choisit le 1er numéro libre ET l'attribue en une seule instruction
            result = conn.execute(
                """
                WITH free AS (
                    SELECT n AS number
                    FROM unnest(%s::text[]) AS t(n)
                    WHERE n NOT IN (
                        SELECT twilio_sms_number FROM users
                        WHERE twilio_sms_number IS NOT NULL
                    )
                    LIMIT 1
                )
                UPDATE users
                    SET twilio_sms_number = free.number
                FROM free
                WHERE users.id = %s AND users.twilio_sms_number IS NULL
                RETURNING users.twilio_sms_number
                """,
                (pool, user_id),
            ).fetchone()

            if not result or not result["twilio_sms_number"]:
                _log.warning("[Twilio] Pool épuisé — aucun numéro disponible pour user %s", user_id)
                return None
            return result["twilio_sms_number"]

    except Exception as exc:
        _log.warning("[Twilio] assign_twilio_number erreur pour user %s: %s", user_id, exc)
        return None


def release_twilio_number(user_id: str) -> bool:
    """
    Libère le numéro Twilio d'un client (résiliation).
    Retourne True si un numéro a été libéré.
    """
    from memory.database import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT twilio_sms_number FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not row or not row["twilio_sms_number"]:
            return False

        conn.execute(
            "UPDATE users SET twilio_sms_number = NULL WHERE id = %s",
            (user_id,),
        )

    return True
