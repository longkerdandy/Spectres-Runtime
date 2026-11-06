"""Shared pytest configuration for the Spectres Runtime test suite."""

import os
from collections.abc import Iterator

import pytest

# Point the settings loader at the committed test environment file.
os.environ.setdefault("SPECTRES_ENV_FILE", ".env.test")


def _reset_test_database() -> None:
    """Delete all test data while preserving tables and database metadata."""
    import psycopg
    from psycopg.sql import SQL, Identifier

    from spectres.config import settings

    target_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(target_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
              AND schemaname NOT LIKE 'pg_toast%'
            """
        )
        tables = cur.fetchall()
        if not tables:
            return
        cur.execute(SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(SQL(", ").join(SQL("{}.{}").format(Identifier(schema), Identifier(table)) for schema, table in tables)))


@pytest.fixture(autouse=True)
def reset_trace_context() -> Iterator[None]:
    """Isolate the logging trace contextvar between tests.

    Tool error paths deliberately bind a trace id without resetting it (the
    tool boundary owns the trace for the rest of the logical operation); in
    the test process that would leak into the next test.
    """
    from spectres.logging import bind_trace, reset_trace

    token = bind_trace(None)
    yield
    reset_trace(token)


@pytest.fixture(autouse=True)
def reset_database_for_db_tests(request: pytest.FixtureRequest) -> None:
    """Reset the test database before each database test."""
    if request.node.get_closest_marker("db") is None:
        return
    _reset_test_database()
