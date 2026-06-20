"""Shared pytest configuration for the Spectres Runtime test suite."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Point the settings loader at the committed test environment file.
os.environ.setdefault("SPECTRES_ENV_FILE", ".env.test")

# Load optional local test secrets (gitignored) so integration tests can call
# real LLM APIs such as GitHub Models without committing credentials.
_local_env = Path(__file__).parent.parent / ".env.test.local"
if _local_env.exists():
    load_dotenv(_local_env, override=False)


def _reset_test_database() -> None:
    """Drop and recreate the test database, then install pgvector."""
    import psycopg
    from psycopg.sql import SQL, Identifier

    from spectres.config import settings

    admin_url = f"postgresql://{settings.db_user}:{settings.db_pass}@{settings.db_host}:{settings.db_port}/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (settings.db_database,),
        )
        cur.execute(SQL("DROP DATABASE IF EXISTS {}").format(Identifier(settings.db_database)))
        cur.execute(SQL("CREATE DATABASE {}").format(Identifier(settings.db_database)))

    target_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(target_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")


@pytest.fixture(autouse=True)
def reset_database_for_integration(request: pytest.FixtureRequest) -> None:
    """Reset the test database before each integration test."""
    if request.node.get_closest_marker("integration") is None:
        return
    _reset_test_database()
