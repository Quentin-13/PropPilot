"""Add read_at column to conversations for SMS read tracking.

Revision ID: 006
Revises: 005
Create Date: 2026-05-04
"""

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS read_at TIMESTAMP NULL;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_client_read_at "
        "ON conversations(client_id, read_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversations_client_read_at;")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS read_at;")
