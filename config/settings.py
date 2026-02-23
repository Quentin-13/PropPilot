"""
Configuration centrale — lecture .env via Pydantic Settings v2.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

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

    # OpenAI
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    # Twilio
    twilio_account_sid: Optional[str] = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: Optional[str] = Field(default=None, alias="TWILIO_PHONE_NUMBER")
    twilio_whatsapp_number: str = Field(default="+14155238886", alias="TWILIO_WHATSAPP_NUMBER")

    # ElevenLabs
    elevenlabs_api_key: Optional[str] = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(default="EXAVITQu4vr4xnSDxMaL", alias="ELEVENLABS_VOICE_ID")

    # Retell
    retell_api_key: Optional[str] = Field(default=None, alias="RETELL_API_KEY")
    retell_agent_id: Optional[str] = Field(default=None, alias="RETELL_AGENT_ID")

    # SendGrid
    sendgrid_api_key: Optional[str] = Field(default=None, alias="SENDGRID_API_KEY")
    sendgrid_from_email: str = Field(default="noreply@proppilot.fr", alias="SENDGRID_FROM_EMAIL")
    sendgrid_from_name: str = Field(default="PropPilot", alias="SENDGRID_FROM_NAME")

    # Google Calendar
    google_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_ID")
    google_service_account_json: Optional[str] = Field(default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON")

    # Base de données
    database_path: str = Field(default="./data/agency.db", alias="DATABASE_PATH")

    # Configuration Agence
    agency_name: str = Field(default="Mon Agence PropPilot", alias="AGENCY_NAME")
    agency_tier: Literal["Starter", "Pro", "Elite"] = Field(default="Starter", alias="AGENCY_TIER")
    agency_client_id: str = Field(default="client_demo", alias="AGENCY_CLIENT_ID")
    agency_commission_rate: float = Field(default=0.05, alias="AGENCY_COMMISSION_RATE")
    agency_average_price: float = Field(default=280000.0, alias="AGENCY_AVERAGE_PRICE")

    # Admin
    admin_password: str = Field(default="changeme", alias="ADMIN_PASSWORD")

    # Mode
    debug: bool = Field(default=False, alias="DEBUG")
    mock_mode: Literal["auto", "always", "never"] = Field(default="auto", alias="MOCK_MODE")

    @field_validator("agency_tier", mode="before")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        valid = {"Starter", "Pro", "Elite"}
        if v not in valid:
            return "Starter"
        return v

    @property
    def twilio_available(self) -> bool:
        if self.mock_mode == "always":
            return False
        if self.mock_mode == "never":
            return True
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def anthropic_available(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def openai_available(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def elevenlabs_available(self) -> bool:
        if self.mock_mode == "always":
            return False
        return bool(self.elevenlabs_api_key)

    @property
    def retell_available(self) -> bool:
        if self.mock_mode == "always":
            return False
        return bool(self.retell_api_key)

    @property
    def sendgrid_available(self) -> bool:
        if self.mock_mode == "always":
            return False
        return bool(self.sendgrid_api_key)

    def ensure_data_dir(self) -> Path:
        """Crée le répertoire data si inexistant."""
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path.parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings — chargé une seule fois."""
    return Settings()
