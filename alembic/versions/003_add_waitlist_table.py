"""Add waitlist table.

Revision ID: 003
Revises: 002
Create Date: 2026-04-28
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id              SERIAL PRIMARY KEY,
            prenom          TEXT NOT NULL,
            nom             TEXT NOT NULL,
            email           TEXT NOT NULL UNIQUE,
            agence          TEXT NOT NULL,
            type_agence     TEXT NOT NULL,
            taille_equipe   TEXT NOT NULL,
            crm_utilise     TEXT NOT NULL,
            source          TEXT NOT NULL DEFAULT 'landing',
            ip_address      TEXT,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlist_email ON waitlist (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlist_created_at ON waitlist (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS waitlist")
