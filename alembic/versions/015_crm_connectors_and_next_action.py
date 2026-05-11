"""CRM push connectors + next_action fields.

Chantier 1 — Colonnes CRM push sur users, next_action sur leads, table crm_sync_log.

Revision ID: 015
Revises: 014
Create Date: 2026-05-11
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── CRM push config sur la table users (= clients) ────────────────────────
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "crm_type VARCHAR(32) DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "crm_config JSONB DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "crm_last_sync_at TIMESTAMP NULL"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "crm_last_error TEXT NULL"
    )

    # ── Prochaine action suggérée sur la table leads ───────────────────────────
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_label TEXT"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_priority VARCHAR(16)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_reason TEXT"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_deadline TIMESTAMP"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_computed_at TIMESTAMP"
    )

    # ── Table de log des pushs CRM ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS crm_sync_log (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            connector_type TEXT NOT NULL DEFAULT 'unknown',
            status TEXT NOT NULL DEFAULT 'success',
            error TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_sync_log_client "
        "ON crm_sync_log(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_sync_log_lead "
        "ON crm_sync_log(lead_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_sync_log_sent_at "
        "ON crm_sync_log(sent_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crm_sync_log")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS next_action_computed_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS next_action_deadline")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS next_action_reason")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS next_action_priority")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS next_action_label")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS crm_last_error")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS crm_last_sync_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS crm_config")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS crm_type")
