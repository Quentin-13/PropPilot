"""Add lead_type column to leads (acheteur|vendeur|locataire).

Revision ID: 010
Revises: 009
Create Date: 2026-05-07
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_type TEXT DEFAULT 'acheteur'"
    )
    # Backfill depuis le champ projet existant
    op.execute("""
        UPDATE leads SET lead_type = CASE
            WHEN projet IN ('vente', 'estimation') THEN 'vendeur'
            WHEN projet = 'location' THEN 'locataire'
            ELSE 'acheteur'
        END
        WHERE lead_type IS NULL OR lead_type = 'acheteur'
    """)
    # Contrainte NOT NULL après backfill
    op.execute(
        "ALTER TABLE leads ALTER COLUMN lead_type SET NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_leads_lead_type ON leads(lead_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_leads_lead_type")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lead_type")
