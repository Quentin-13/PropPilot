"""Drop waitlist table (feature removed).

Revision ID: 007
Revises: 006
Create Date: 2026-05-05
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_waitlist_email;")
    op.execute("DROP INDEX IF EXISTS ix_waitlist_created_at;")
    op.execute("DROP TABLE IF EXISTS waitlist;")


def downgrade() -> None:
    # Recrée le schéma exact de la migration 003
    op.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id            SERIAL PRIMARY KEY,
            prenom        TEXT NOT NULL,
            nom           TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            agence        TEXT NOT NULL,
            type_agence   TEXT NOT NULL,
            taille_equipe TEXT NOT NULL,
            crm_utilise   TEXT NOT NULL,
            source        TEXT NOT NULL DEFAULT 'landing',
            ip_address    TEXT,
            created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlist_email ON waitlist (email);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlist_created_at ON waitlist (created_at);")
