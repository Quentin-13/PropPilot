"""Add is_internal column to users table.

Marks internal/test accounts so they are excluded from business KPIs
(MRR, churn, ARPU) while remaining visible in admin views.

Revision ID: 014
Revises: 013
Create Date: 2026-05-07
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

_INTERNAL_EMAILS = ("contact@proppilot.fr", "contact.maisondusommeil@gmail.com")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "is_internal BOOLEAN NOT NULL DEFAULT FALSE"
    )

    for email in _INTERNAL_EMAILS:
        op.execute(
            f"UPDATE users SET is_internal = TRUE WHERE email = '{email}'"
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_is_internal "
        "ON users(is_internal)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_is_internal")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_internal")
