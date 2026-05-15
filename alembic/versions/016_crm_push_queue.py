"""crm_push_queue — table retry pour push CRM.

Revision ID: 016
Revises: 015
Create Date: 2026-05-15
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS crm_push_queue (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            payload_text TEXT DEFAULT '',
            target_email TEXT DEFAULT '',
            status TEXT DEFAULT 'pending'
                CHECK (status IN ('pending', 'sent', 'permanent_error')),
            attempts INTEGER DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_push_queue_pending "
        "ON crm_push_queue(client_id, status) WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_push_queue_lead "
        "ON crm_push_queue(lead_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_crm_push_queue_lead")
    op.execute("DROP INDEX IF EXISTS idx_crm_push_queue_pending")
    op.execute("DROP TABLE IF EXISTS crm_push_queue")
