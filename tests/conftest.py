"""
Configuration pytest globale — base de données PostgreSQL de test.
Chaque test obtient une base propre (truncate de toutes les tables).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://proppilot:proppilot@localhost:5432/proppilot",
)


def pytest_configure(config):
    """Force DATABASE_URL vers la base de test avant toute importation."""
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _reset_db_between_tests(monkeypatch):
    """
    Avant chaque test :
      - Force DATABASE_URL vers la base de test
      - Vide les tables (isolation entre tests sans recréer le schéma)
    Remplace le tmp_path SQLite des anciens fixtures.
    """
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)

    from config.settings import get_settings
    get_settings.cache_clear()

    from memory.database import get_connection, init_database
    init_database()

    # Truncate dans l'ordre inverse des FK
    tables = [
        "api_actions", "conversations", "calls", "listings", "estimations",
        "roi_metrics", "crm_connections", "usage_tracking", "leads", "users",
    ]
    with get_connection() as conn:
        for table in tables:
            conn.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")

    yield

    get_settings.cache_clear()
