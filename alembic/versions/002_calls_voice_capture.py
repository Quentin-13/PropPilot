"""Calls voice capture — enrich calls table + add call_extractions + agency_phone_numbers.

Revision ID: 002
Revises: 001
Create Date: 2026-04-28
"""
from alembic import op

revision = "002"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enrich existing calls table (keep all Retell-era columns) ────────────
    # Each ADD COLUMN IF NOT EXISTS is idempotent.
    _add = [
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_sid TEXT",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS agency_id TEXT",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS agent_id TEXT",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'dedicated_number'",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS from_number TEXT DEFAULT ''",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS to_number TEXT DEFAULT ''",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS twilio_number TEXT DEFAULT ''",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS answered_at TIMESTAMP",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS duration_seconds INTEGER DEFAULT 0",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_url TEXT DEFAULT ''",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_duration INTEGER DEFAULT 0",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_text TEXT DEFAULT ''",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_segments JSONB DEFAULT '[]'",
        # 'status' is a richer state machine; 'statut' is the old Retell field (kept)
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'initiated'",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS cost_twilio NUMERIC(10,6) DEFAULT 0",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS cost_whisper NUMERIC(10,6) DEFAULT 0",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS cost_claude NUMERIC(10,6) DEFAULT 0",
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]
    for stmt in _add:
        op.execute(stmt)

    # Unique index on call_sid for idempotency
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_call_sid ON calls(call_sid) "
        "WHERE call_sid IS NOT NULL"
    )

    # ── call_extractions ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS call_extractions (
            id SERIAL PRIMARY KEY,
            call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
            lead_id TEXT,
            type_projet TEXT,
            budget_min INTEGER,
            budget_max INTEGER,
            zone_geographique TEXT,
            type_bien TEXT,
            surface_min INTEGER,
            surface_max INTEGER,
            criteres JSONB DEFAULT '{}',
            timing JSONB DEFAULT '{}',
            financement JSONB DEFAULT '{}',
            motivation TEXT,
            score_qualification TEXT DEFAULT 'froid',
            prochaine_action_suggeree TEXT,
            resume_appel TEXT,
            points_attention JSONB DEFAULT '[]',
            extraction_model TEXT DEFAULT 'claude-sonnet-4-5',
            extraction_prompt_version TEXT DEFAULT 'v1',
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_extractions_call ON call_extractions(call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_extractions_lead ON call_extractions(lead_id)")

    # ── agency_phone_numbers — numéro Twilio → agence → agent ────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agency_phone_numbers (
            id SERIAL PRIMARY KEY,
            twilio_number TEXT UNIQUE NOT NULL,
            agency_id TEXT NOT NULL,
            agent_id TEXT,
            agent_phone TEXT,
            label TEXT DEFAULT '',
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_phone_numbers_agency "
        "ON agency_phone_numbers(agency_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agency_phone_numbers CASCADE")
    op.execute("DROP TABLE IF EXISTS call_extractions CASCADE")
    # Drop added columns from calls (keep original columns)
    _drop = [
        "call_sid", "agency_id", "agent_id", "mode",
        "from_number", "to_number", "twilio_number",
        "started_at", "answered_at", "ended_at", "duration_seconds",
        "recording_url", "recording_duration",
        "transcript_text", "transcript_segments",
        "status", "cost_twilio", "cost_whisper", "cost_claude", "updated_at",
    ]
    for col in _drop:
        op.execute(f"ALTER TABLE calls DROP COLUMN IF EXISTS {col}")
