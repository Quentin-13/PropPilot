"""Add type_bien and last_extraction_at to leads.

Revision ID: 009
Revises: 008
Create Date: 2026-05-05
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS type_bien TEXT DEFAULT ''")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_extraction_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_extraction_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS type_bien")
