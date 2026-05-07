"""Create admin dashboard tables (twilio_usage, user_activity, admin_access_log).

Revision ID: 013
Revises: 012
Create Date: 2026-05-07
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Coûts Twilio par client (SMS in/out, appels, numéros loués)
    op.execute("""
        CREATE TABLE IF NOT EXISTS twilio_usage (
            id        SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            type      TEXT NOT NULL,
            cost_eur  REAL NOT NULL DEFAULT 0,
            metadata  TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_twilio_usage_client "
        "ON twilio_usage(client_id, created_at)"
    )

    # Activité utilisateurs (logins, actions dashboard)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            id        SERIAL PRIMARY KEY,
            user_id   TEXT NOT NULL,
            client_id TEXT NOT NULL,
            action    TEXT NOT NULL,
            metadata  TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_activity_client "
        "ON user_activity(client_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_activity_user "
        "ON user_activity(user_id, created_at)"
    )

    # Log des accès à la page super-admin
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_access_log (
            id         SERIAL PRIMARY KEY,
            user_email TEXT NOT NULL,
            action     TEXT NOT NULL DEFAULT 'page_view',
            ip         TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_access_log")
    op.execute("DROP TABLE IF EXISTS user_activity")
    op.execute("DROP TABLE IF EXISTS twilio_usage")
