"""Ajoute last_action_completed_at sur leads pour le cockpit client.

Revision ID: 017
Revises: 016
Create Date: 2026-05-15
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_action_completed_at TIMESTAMP"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_action_completed_at")
