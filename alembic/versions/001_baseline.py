"""Baseline — schéma complet PropPilot post-pivot cleanup.

Includes: users, leads, conversations, usage_tracking, api_actions, calls,
          listings, estimations, roi_metrics, crm_connections, lead_journey,
          reminders (ajouté Step 4 sprint cleanup-pivot).

Revision ID: 001_baseline
Revises:
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa

revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            agency_name TEXT DEFAULT '',
            plan TEXT DEFAULT 'Starter',
            plan_active BOOLEAN DEFAULT TRUE,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'inactive',
            trial_ends_at TIMESTAMP,
            google_calendar_token TEXT,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            smspartner_number TEXT DEFAULT NULL,
            twilio_sms_number TEXT DEFAULT NULL,
            first_name TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_twilio_sms_number "
        "ON users(twilio_sms_number) WHERE twilio_sms_number IS NOT NULL"
    )

    # ── leads ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            prenom TEXT DEFAULT '',
            nom TEXT DEFAULT '',
            telephone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            source TEXT DEFAULT 'sms',
            projet TEXT DEFAULT 'inconnu',
            localisation TEXT DEFAULT '',
            budget TEXT DEFAULT '',
            timeline TEXT DEFAULT '',
            financement TEXT DEFAULT '',
            motivation TEXT DEFAULT '',
            score INTEGER DEFAULT 0,
            score_urgence INTEGER DEFAULT 0,
            score_budget INTEGER DEFAULT 0,
            score_motivation INTEGER DEFAULT 0,
            statut TEXT DEFAULT 'entrant',
            nurturing_sequence TEXT,
            nurturing_step INTEGER DEFAULT 0,
            prochain_followup TIMESTAMP,
            rdv_date TIMESTAMP,
            mandat_date TIMESTAMP,
            resume TEXT DEFAULT '',
            notes_agent TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_client ON leads(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_statut ON leads(statut)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_prochain_followup ON leads(prochain_followup)")

    # ── conversations ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            canal TEXT DEFAULT 'sms',
            role TEXT DEFAULT 'user',
            contenu TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id)")

    # ── reminders (Step 4 sprint cleanup-pivot) ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'nurturing',
            canal TEXT DEFAULT 'sms',
            message TEXT NOT NULL,
            sujet TEXT DEFAULT '',
            scheduled_at TIMESTAMP NOT NULL,
            sent_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reminders_client ON reminders(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reminders_lead ON reminders(lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reminders_scheduled ON reminders(scheduled_at)")

    # ── usage_tracking ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_tracking (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            month TEXT NOT NULL,
            leads_count INTEGER DEFAULT 0,
            voice_minutes REAL DEFAULT 0,
            images_count INTEGER DEFAULT 0,
            tokens_used INTEGER DEFAULT 0,
            followups_count INTEGER DEFAULT 0,
            listings_count INTEGER DEFAULT 0,
            estimations_count INTEGER DEFAULT 0,
            api_cost_euros REAL DEFAULT 0,
            tier TEXT DEFAULT 'Starter',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(client_id, month)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_client_month ON usage_tracking(client_id, month)")

    # ── api_actions ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_actions (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            cost_euros REAL DEFAULT 0,
            success INTEGER DEFAULT 1,
            mock_used INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_actions_client ON api_actions(client_id)")

    # ── calls ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            retell_call_id TEXT DEFAULT '',
            direction TEXT DEFAULT 'outbound',
            duree_secondes INTEGER DEFAULT 0,
            statut TEXT DEFAULT 'completed',
            transcript TEXT DEFAULT '',
            resume TEXT DEFAULT '',
            score_post_appel INTEGER DEFAULT 0,
            anomalies TEXT DEFAULT '[]',
            rdv_booke INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_calls_lead ON calls(lead_id)")

    # ── listings ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            lead_id TEXT DEFAULT '',
            client_id TEXT NOT NULL,
            type_bien TEXT DEFAULT '',
            adresse TEXT DEFAULT '',
            surface REAL DEFAULT 0,
            nb_pieces INTEGER DEFAULT 0,
            prix REAL DEFAULT 0,
            dpe TEXT DEFAULT '',
            titre TEXT DEFAULT '',
            description_longue TEXT DEFAULT '',
            description_courte TEXT DEFAULT '',
            points_forts TEXT DEFAULT '[]',
            mentions_legales TEXT DEFAULT '',
            mots_cles_seo TEXT DEFAULT '[]',
            images_urls TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── estimations ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS estimations (
            id TEXT PRIMARY KEY,
            lead_id TEXT DEFAULT '',
            client_id TEXT NOT NULL,
            adresse TEXT DEFAULT '',
            surface REAL DEFAULT 0,
            type_bien TEXT DEFAULT '',
            prix_estime_bas INTEGER DEFAULT 0,
            prix_estime_central INTEGER DEFAULT 0,
            prix_estime_haut INTEGER DEFAULT 0,
            prix_m2_net INTEGER DEFAULT 0,
            loyer_mensuel_estime INTEGER DEFAULT 0,
            rentabilite_brute REAL DEFAULT 0,
            delai_vente_estime_semaines INTEGER DEFAULT 0,
            justification TEXT DEFAULT '',
            mention_legale TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── roi_metrics ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS roi_metrics (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            month TEXT NOT NULL,
            rdv_count INTEGER DEFAULT 0,
            mandats_count INTEGER DEFAULT 0,
            ventes_count INTEGER DEFAULT 0,
            ca_estime REAL DEFAULT 0,
            leads_entrants INTEGER DEFAULT 0,
            leads_qualifies INTEGER DEFAULT 0,
            taux_conversion_rdv REAL DEFAULT 0,
            taux_conversion_mandat REAL DEFAULT 0,
            garantie_objectif_rdv INTEGER DEFAULT 2,
            garantie_objectif_mandat INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(client_id, month)
        )
    """)

    # ── crm_connections ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS crm_connections (
            id SERIAL PRIMARY KEY,
            client_id TEXT NOT NULL,
            crm_type TEXT NOT NULL,
            api_key TEXT DEFAULT '',
            agency_id_crm TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            sync_leads INTEGER DEFAULT 1,
            sync_rdv INTEGER DEFAULT 1,
            sync_listings INTEGER DEFAULT 1,
            last_sync TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(client_id, crm_type)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_crm_connections_client ON crm_connections(client_id)")

    # ── lead_journey ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS lead_journey (
            id SERIAL PRIMARY KEY,
            lead_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            action_done TEXT NOT NULL,
            action_result TEXT DEFAULT '',
            next_action TEXT DEFAULT '',
            next_action_at TIMESTAMP,
            agent_name TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_lead ON lead_journey(lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_next_action ON lead_journey(next_action_at)")


def downgrade() -> None:
    for table in [
        "reminders", "lead_journey", "crm_connections", "roi_metrics",
        "estimations", "listings", "calls", "api_actions", "usage_tracking",
        "conversations", "leads", "users",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
