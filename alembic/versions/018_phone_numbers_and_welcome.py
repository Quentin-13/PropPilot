"""Pool de numéros PropPilot + flag onboarding bienvenue.

Revision ID: 018
Revises: 017
Create Date: 2026-05-16
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS phone_numbers (
            id SERIAL PRIMARY KEY,
            phone_number TEXT UNIQUE NOT NULL,
            provider TEXT NOT NULL DEFAULT 'twilio',
            status TEXT NOT NULL DEFAULT 'available'
                CHECK (status IN ('available', 'assigned', 'disabled')),
            client_id TEXT DEFAULT NULL,
            assigned_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_phone_numbers_available "
        "ON phone_numbers(status) WHERE status = 'available'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_phone_numbers_client "
        "ON phone_numbers(client_id) WHERE client_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS welcome_seen_at TIMESTAMP DEFAULT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS welcome_seen_at")
    op.execute("DROP INDEX IF EXISTS idx_phone_numbers_client")
    op.execute("DROP INDEX IF EXISTS idx_phone_numbers_available")
    op.execute("DROP TABLE IF EXISTS phone_numbers")
