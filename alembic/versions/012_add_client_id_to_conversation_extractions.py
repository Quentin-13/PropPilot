"""Add client_id to conversation_extractions for multi-tenant isolation.

Revision ID: 012
Revises: 011
Create Date: 2026-05-07
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_extractions ADD COLUMN IF NOT EXISTS client_id TEXT"
    )

    # Backfill depuis la table leads via lead_id
    op.execute(
        """
        UPDATE conversation_extractions ce
        SET client_id = l.client_id
        FROM leads l
        WHERE ce.lead_id = l.id
          AND ce.client_id IS NULL
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_extractions_client "
        "ON conversation_extractions(client_id) WHERE client_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_extractions DROP COLUMN IF EXISTS client_id"
    )
