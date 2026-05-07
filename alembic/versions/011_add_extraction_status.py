"""Add extraction_status to leads and conversation_extractions.

Revision ID: 011
Revises: 010
Create Date: 2026-05-07

Objectif : filet de sécurité extraction LLM.
- leads.extraction_status         : 'ok' | 'failed' | 'mock'
- conversation_extractions.extraction_status : idem
  Permet d'identifier les leads dont l'extraction a échoué après 3 tentatives
  et de les afficher dans la vue "À vérifier manuellement".
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # leads
    op.execute(
        "ALTER TABLE leads "
        "ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'ok'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_leads_extraction_status "
        "ON leads(extraction_status) WHERE extraction_status != 'ok'"
    )

    # conversation_extractions
    op.execute(
        "ALTER TABLE conversation_extractions "
        "ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'ok'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_ext_status "
        "ON conversation_extractions(extraction_status) "
        "WHERE extraction_status != 'ok'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conv_ext_status")
    op.execute(
        "ALTER TABLE conversation_extractions "
        "DROP COLUMN IF EXISTS extraction_status"
    )
    op.execute("DROP INDEX IF EXISTS idx_leads_extraction_status")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS extraction_status")
