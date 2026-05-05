"""Rename call_extractions → conversation_extractions, add source column.

Revision ID: 008
Revises: 007
Create Date: 2026-05-05

Objectif : table unifiée pour les extractions IA multi-canal.
  - Renomme call_extractions → conversation_extractions
  - Backfill lead_id depuis calls (était toujours NULL)
  - Ajoute colonne source TEXT NOT NULL ('call' | 'sms')
  - Rend call_id nullable (les extractions SMS n'ont pas de call_id)
  - Recrée la FK call_id avec un nom explicite
  - Ajoute CHECK source-consistency
  - Ajoute index sur source et lead_id
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Renommer la table — les index/contraintes existants suivent
    op.rename_table("call_extractions", "conversation_extractions")

    # 2. Backfill lead_id depuis calls (colonne existante mais toujours NULL)
    op.execute("""
        UPDATE conversation_extractions ce
        SET lead_id = c.lead_id
        FROM calls c
        WHERE ce.call_id = c.id
          AND ce.lead_id IS NULL
    """)

    # 3. Ajouter colonne source, backfill, puis NOT NULL
    op.execute(
        "ALTER TABLE conversation_extractions ADD COLUMN IF NOT EXISTS source TEXT"
    )
    op.execute(
        "UPDATE conversation_extractions SET source = 'call' WHERE source IS NULL"
    )
    op.execute(
        "ALTER TABLE conversation_extractions ALTER COLUMN source SET NOT NULL"
    )

    # 4. Rendre call_id nullable
    #    La FK auto-nommée (call_extractions_call_id_fkey) est renommée quand on
    #    renomme la table uniquement sous certaines versions PG — on la cherche
    #    dynamiquement pour être robuste.
    op.execute("""
        DO $$
        DECLARE v_conname TEXT;
        BEGIN
            SELECT conname INTO v_conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname = 'conversation_extractions'
              AND c.contype = 'f'
              AND pg_get_constraintdef(c.oid) ILIKE '%calls%'
            LIMIT 1;

            IF v_conname IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE conversation_extractions DROP CONSTRAINT %I',
                    v_conname
                );
            END IF;
        END $$
    """)
    op.execute(
        "ALTER TABLE conversation_extractions ALTER COLUMN call_id DROP NOT NULL"
    )

    # 5. Recréer la FK avec un nom explicite (nullable, ON DELETE CASCADE)
    op.execute("""
        ALTER TABLE conversation_extractions
        ADD CONSTRAINT fk_conv_extractions_call
        FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
    """)

    # 6. CHECK : cohérence source / call_id
    op.execute("""
        ALTER TABLE conversation_extractions
        ADD CONSTRAINT ck_conv_extractions_source CHECK (
            (source = 'call' AND call_id IS NOT NULL) OR
            (source = 'sms'  AND call_id IS NULL)
        )
    """)

    # 7. Index supplémentaires
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_extractions_source "
        "ON conversation_extractions(source)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_extractions_lead_source "
        "ON conversation_extractions(lead_id, source) WHERE lead_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conv_extractions_lead_source")
    op.execute("DROP INDEX IF EXISTS idx_conv_extractions_source")

    op.execute(
        "ALTER TABLE conversation_extractions "
        "DROP CONSTRAINT IF EXISTS ck_conv_extractions_source"
    )

    # Supprimer la FK explicite, remettre call_id NOT NULL, recréer l'ancienne FK
    op.execute(
        "ALTER TABLE conversation_extractions "
        "DROP CONSTRAINT IF EXISTS fk_conv_extractions_call"
    )
    # Peut échouer si des lignes SMS existent déjà (call_id NULL) — nettoyer avant
    op.execute(
        "ALTER TABLE conversation_extractions ALTER COLUMN call_id SET NOT NULL"
    )
    op.execute("""
        ALTER TABLE conversation_extractions
        ADD CONSTRAINT call_extractions_call_id_fkey
        FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
    """)

    op.execute(
        "ALTER TABLE conversation_extractions DROP COLUMN IF EXISTS source"
    )

    op.rename_table("conversation_extractions", "call_extractions")
