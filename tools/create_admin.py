"""
Script one-shot : crée ou met à jour l'utilisateur admin PropPilot.
À exécuter UNE SEULE FOIS depuis la racine du projet :

    python tools/create_admin.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import bcrypt
import psycopg2
import psycopg2.extras

from config.settings import get_settings

ADMIN_EMAIL = "contact@proppilot.fr"
ADMIN_PASSWORD = "Flo260669."
ADMIN_AGENCY = "PropPilot Admin"
ADMIN_PLAN = "Elite"


def main() -> None:
    settings = get_settings()
    conn = psycopg2.connect(settings.database_url)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # 1. Ajouter la colonne is_admin si elle n'existe pas
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
            """)

            # 2. Chercher l'utilisateur existant
            cur.execute("SELECT id FROM users WHERE email = %s", (ADMIN_EMAIL,))
            row = cur.fetchone()

            if row:
                # Mise à jour uniquement
                cur.execute("""
                    UPDATE users
                    SET plan_active = TRUE,
                        plan        = %s,
                        is_admin    = TRUE
                    WHERE email = %s
                """, (ADMIN_PLAN, ADMIN_EMAIL))
                conn.commit()
                print(f"Admin mis à jour : {ADMIN_EMAIL} — plan={ADMIN_PLAN}, plan_active=True")

            else:
                # Création
                hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
                cur.execute("""
                    INSERT INTO users (email, hashed_password, agency_name, plan, plan_active, is_admin)
                    VALUES (%s, %s, %s, %s, TRUE, TRUE)
                """, (ADMIN_EMAIL, hashed, ADMIN_AGENCY, ADMIN_PLAN))
                conn.commit()
                print(f"Admin créé avec succès : {ADMIN_EMAIL} — plan={ADMIN_PLAN}")

    except Exception as exc:
        conn.rollback()
        print(f"Erreur : {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
