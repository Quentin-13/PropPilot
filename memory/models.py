"""
Modèles de données — dataclasses Pydantic v2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class LeadStatus(str, Enum):
    ENTRANT = "entrant"
    EN_QUALIFICATION = "en_qualification"
    QUALIFIE = "qualifie"
    RDV_BOOKÉ = "rdv_booke"
    MANDAT = "mandat"
    VENDU = "vendu"
    PERDU = "perdu"
    NURTURING = "nurturing"


class ProjetType(str, Enum):
    ACHAT = "achat"
    VENTE = "vente"
    LOCATION = "location"
    ESTIMATION = "estimation"
    INCONNU = "inconnu"


class Canal(str, Enum):
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    APPEL = "appel"
    WEB = "web"
    SELOGER = "seloger"
    LEBONCOIN = "leboncoin"
    MANUEL = "manuel"


class NurturingSequence(str, Enum):
    VENDEUR_CHAUD = "vendeur_chaud"
    ACHETEUR_QUALIFIE = "acheteur_qualifie"
    LEAD_FROID = "lead_froid"


@dataclass
class Lead:
    id: str = field(default_factory=lambda: str(uuid4()))
    client_id: str = ""
    prenom: str = ""
    nom: str = ""
    telephone: str = ""
    email: str = ""
    source: Canal = Canal.SMS
    projet: ProjetType = ProjetType.INCONNU
    localisation: str = ""
    budget: str = ""
    timeline: str = ""
    financement: str = ""
    motivation: str = ""
    score: int = 0
    score_urgence: int = 0
    score_budget: int = 0
    score_motivation: int = 0
    statut: LeadStatus = LeadStatus.ENTRANT
    nurturing_sequence: Optional[NurturingSequence] = None
    nurturing_step: int = 0
    prochain_followup: Optional[datetime] = None
    rdv_date: Optional[datetime] = None
    mandat_date: Optional[datetime] = None
    resume: str = ""
    notes_agent: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def nom_complet(self) -> str:
        parts = [p for p in [self.prenom, self.nom] if p]
        return " ".join(parts) if parts else "Anonyme"

    @property
    def score_label(self) -> str:
        if self.score >= 7:
            return "Chaud 🔴"
        elif self.score >= 4:
            return "Tiède 🟠"
        else:
            return "Froid 🔵"

    @property
    def score_color(self) -> str:
        if self.score >= 7:
            return "red"
        elif self.score >= 4:
            return "orange"
        else:
            return "blue"


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: str(uuid4()))
    lead_id: str = ""
    client_id: str = ""
    canal: Canal = Canal.SMS
    role: str = "user"          # "user" ou "assistant"
    contenu: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class UsageRecord:
    id: Optional[int] = None
    client_id: str = ""
    month: str = ""              # format YYYY-MM
    leads_count: int = 0
    voice_minutes: float = 0.0
    images_count: int = 0
    tokens_used: int = 0
    followups_count: int = 0
    listings_count: int = 0
    estimations_count: int = 0
    api_cost_euros: float = 0.0
    tier: str = "Starter"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class APIAction:
    """Log d'une action API avec son coût réel (usage interne uniquement)."""
    id: Optional[int] = None
    client_id: str = ""
    action_type: str = ""        # lead, voice, image, token, listing, estimation
    provider: str = ""           # anthropic, openai, twilio, elevenlabs
    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_euros: float = 0.0
    success: bool = True
    mock_used: bool = False
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Call:
    id: str = field(default_factory=lambda: str(uuid4()))
    lead_id: str = ""
    client_id: str = ""
    retell_call_id: str = ""
    direction: str = "outbound"  # inbound / outbound
    duree_secondes: int = 0
    statut: str = "completed"
    transcript: str = ""
    resume: str = ""
    score_post_appel: int = 0
    anomalies: list = field(default_factory=list)
    rdv_booke: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Listing:
    id: str = field(default_factory=lambda: str(uuid4()))
    lead_id: str = ""
    client_id: str = ""
    type_bien: str = ""
    adresse: str = ""
    surface: float = 0.0
    nb_pieces: int = 0
    prix: float = 0.0
    dpe: str = ""
    titre: str = ""
    description_longue: str = ""
    description_courte: str = ""
    points_forts: list = field(default_factory=list)
    mentions_legales: str = ""
    mots_cles_seo: list = field(default_factory=list)
    images_urls: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class User:
    """Compte client PropPilot (agence ou mandataire)."""
    id: Optional[str] = None
    email: str = ""
    agency_name: str = ""
    plan: str = "Starter"
    plan_active: bool = False
    twilio_sms_number: Optional[str] = None  # Numéro 06/07 Twilio assigné à ce client
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Estimation:
    id: str = field(default_factory=lambda: str(uuid4()))
    lead_id: str = ""
    client_id: str = ""
    adresse: str = ""
    surface: float = 0.0
    type_bien: str = ""
    prix_estime_bas: int = 0
    prix_estime_central: int = 0
    prix_estime_haut: int = 0
    prix_m2_net: int = 0
    loyer_mensuel_estime: int = 0
    rentabilite_brute: float = 0.0
    delai_vente_estime_semaines: int = 0
    justification: str = ""
    mention_legale: str = "Estimation non opposable, donnée à titre indicatif conformément à la loi Hoguet."
    created_at: datetime = field(default_factory=datetime.now)
