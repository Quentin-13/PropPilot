"""
Initialisation PostgreSQL, migrations, connexion.
Utilise psycopg2 avec un wrapper compatible avec l'interface sqlite3 existante
(conn.execute(), placeholders ?, row_factory dict-like).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras

from config.settings import get_settings


# ─── Wrapper de compatibilité ─────────────────────────────────────────────────

class _PgConnection:
    """
    Wraps a psycopg2 connection + DictCursor pour imiter l'interface sqlite3 :
      - conn.execute(sql, params) → retourne un curseur fetchable
      - conn.executescript(sql)   → exécute plusieurs instructions DDL
      - Conversion automatique des placeholders ? → %s
    """

    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn
        self._cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def execute(self, sql: str, params=None):
        sql = sql.replace("?", "%s")
        if params is not None:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)
        return self._cur

    def executescript(self, sql: str) -> None:
        """Exécute un script SQL multi-instructions (DDL uniquement)."""
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._cur.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._cur.close()
        self._conn.close()


# ─── Connexion ────────────────────────────────────────────────────────────────

@contextmanager
def get_connection() -> Generator[_PgConnection, None, None]:
    """Context manager — connexion PostgreSQL avec interface sqlite3-compatible."""
    settings = get_settings()
    raw_conn = psycopg2.connect(settings.database_url)
    raw_conn.autocommit = False
    conn = _PgConnection(raw_conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Schéma ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    agency_name TEXT DEFAULT '',
    plan TEXT DEFAULT 'Starter' CHECK (plan IN ('Starter', 'Pro', 'Elite')),
    plan_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    prenom TEXT DEFAULT '',
    nom TEXT DEFAULT '',
    telephone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    source TEXT DEFAULT 'sms',
    projet TEXT DEFAULT 'inconnu',
    localisation TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    timeline TEXT DEFAULT '',
    financement TEXT DEFAULT '',
    motivation TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    score_urgence INTEGER DEFAULT 0,
    score_budget INTEGER DEFAULT 0,
    score_motivation INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'entrant',
    nurturing_sequence TEXT,
    nurturing_step INTEGER DEFAULT 0,
    prochain_followup TIMESTAMP,
    rdv_date TIMESTAMP,
    mandat_date TIMESTAMP,
    resume TEXT DEFAULT '',
    notes_agent TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    canal TEXT DEFAULT 'sms',
    role TEXT DEFAULT 'user',
    contenu TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS usage_tracking (
    id SERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    month TEXT NOT NULL,
    leads_count INTEGER DEFAULT 0,
    voice_minutes REAL DEFAULT 0,
    images_count INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    followups_count INTEGER DEFAULT 0,
    listings_count INTEGER DEFAULT 0,
    estimations_count INTEGER DEFAULT 0,
    api_cost_euros REAL DEFAULT 0,
    tier TEXT DEFAULT 'Starter',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, month)
);

CREATE TABLE IF NOT EXISTS api_actions (
    id SERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cost_euros REAL DEFAULT 0,
    success INTEGER DEFAULT 1,
    mock_used INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    retell_call_id TEXT DEFAULT '',
    direction TEXT DEFAULT 'outbound',
    duree_secondes INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'completed',
    transcript TEXT DEFAULT '',
    resume TEXT DEFAULT '',
    score_post_appel INTEGER DEFAULT 0,
    anomalies TEXT DEFAULT '[]',
    rdv_booke INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    lead_id TEXT DEFAULT '',
    client_id TEXT NOT NULL,
    type_bien TEXT DEFAULT '',
    adresse TEXT DEFAULT '',
    surface REAL DEFAULT 0,
    nb_pieces INTEGER DEFAULT 0,
    prix REAL DEFAULT 0,
    dpe TEXT DEFAULT '',
    titre TEXT DEFAULT '',
    description_longue TEXT DEFAULT '',
    description_courte TEXT DEFAULT '',
    points_forts TEXT DEFAULT '[]',
    mentions_legales TEXT DEFAULT '',
    mots_cles_seo TEXT DEFAULT '[]',
    images_urls TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS estimations (
    id TEXT PRIMARY KEY,
    lead_id TEXT DEFAULT '',
    client_id TEXT NOT NULL,
    adresse TEXT DEFAULT '',
    surface REAL DEFAULT 0,
    type_bien TEXT DEFAULT '',
    prix_estime_bas INTEGER DEFAULT 0,
    prix_estime_central INTEGER DEFAULT 0,
    prix_estime_haut INTEGER DEFAULT 0,
    prix_m2_net INTEGER DEFAULT 0,
    loyer_mensuel_estime INTEGER DEFAULT 0,
    rentabilite_brute REAL DEFAULT 0,
    delai_vente_estime_semaines INTEGER DEFAULT 0,
    justification TEXT DEFAULT '',
    mention_legale TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roi_metrics (
    id SERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    month TEXT NOT NULL,
    rdv_count INTEGER DEFAULT 0,
    mandats_count INTEGER DEFAULT 0,
    ventes_count INTEGER DEFAULT 0,
    ca_estime REAL DEFAULT 0,
    leads_entrants INTEGER DEFAULT 0,
    leads_qualifies INTEGER DEFAULT 0,
    taux_conversion_rdv REAL DEFAULT 0,
    taux_conversion_mandat REAL DEFAULT 0,
    garantie_objectif_rdv INTEGER DEFAULT 2,
    garantie_objectif_mandat INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, month)
);

CREATE TABLE IF NOT EXISTS crm_connections (
    id SERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    crm_type TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    agency_id_crm TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    sync_leads INTEGER DEFAULT 1,
    sync_rdv INTEGER DEFAULT 1,
    sync_listings INTEGER DEFAULT 1,
    last_sync TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, crm_type)
);

CREATE INDEX IF NOT EXISTS idx_leads_client ON leads(client_id);
CREATE INDEX IF NOT EXISTS idx_leads_statut ON leads(statut);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score);
CREATE INDEX IF NOT EXISTS idx_leads_prochain_followup ON leads(prochain_followup);
CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_usage_client_month ON usage_tracking(client_id, month);
CREATE INDEX IF NOT EXISTS idx_api_actions_client ON api_actions(client_id);
CREATE INDEX IF NOT EXISTS idx_calls_lead ON calls(lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_connections_client ON crm_connections(client_id)
"""


# ─── Init / Reset ─────────────────────────────────────────────────────────────

def init_database() -> None:
    """Initialise la base de données avec le schéma complet."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    settings = get_settings()
    print(f"✅ Base de données PostgreSQL initialisée : {settings.database_url}")


def reset_database() -> None:
    """Remet à zéro la base de données (usage dev/démo uniquement)."""
    tables = [
        "api_actions", "conversations", "calls", "listings", "estimations",
        "roi_metrics", "crm_connections", "usage_tracking", "leads", "users",
    ]
    with get_connection() as conn:
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    init_database()
    print("✅ Base de données réinitialisée.")
