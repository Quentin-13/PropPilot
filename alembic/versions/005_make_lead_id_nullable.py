"""Make calls.lead_id nullable for inbound calls created before lead extraction.

Revision ID: 005
Revises: 004
Create Date: 2026-05-03
"""

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("ALTER TABLE calls ALTER COLUMN lead_id DROP NOT NULL;")


def downgrade() -> None:
    # Peut échouer si des lignes ont déjà lead_id NULL — nettoyer avant de downgrader.
    op.execute("ALTER TABLE calls ALTER COLUMN lead_id SET NOT NULL;")
