"""Shared pytest configuration for the Spectres Runtime test suite."""

import os

# Configure the environment before any spectres module builds its settings.
# Point the settings loader at the committed test environment file.
os.environ.setdefault("SPECTRES_ENV_FILE", ".env.test")
# Keep external Agno telemetry disabled throughout the test process.
os.environ["AGNO_TELEMETRY"] = "false"

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.support import DEV_JWT_AUDIENCE, DEV_JWT_KEY, JwtApplication


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Require exactly one of unit/integration, and integration for db/llm tests."""
    invalid: list[str] = []
    for item in items:
        markers = {name for name in ("unit", "integration", "db", "llm") if item.get_closest_marker(name) is not None}
        is_unit, is_integration = "unit" in markers, "integration" in markers
        if is_unit == is_integration or (markers & {"db", "llm"} and not is_integration):
            invalid.append(f"{item.nodeid}: {sorted(markers) or 'no markers'}")
    if invalid:
        raise pytest.UsageError("Tests must be marked unit or integration (db/llm imply integration):\n" + "\n".join(invalid))


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


@pytest.fixture
def jwt_application(monkeypatch: pytest.MonkeyPatch) -> Iterator[JwtApplication]:
    """Build the full application with development JWT authentication enabled."""
    from spectres import main as main_module
    from spectres.config import settings

    monkeypatch.setattr(settings, "jwt_verification_key", DEV_JWT_KEY)
    monkeypatch.setattr(settings, "jwt_audience", DEV_JWT_AUDIENCE)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    agent_os, extensions, extension_state = main_module.create_agent_os()
    app = agent_os.get_app()
    main_module.mount_extension_routers(app, extensions, extension_state)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield JwtApplication(client, extensions)


@pytest.fixture
def jwt_client(jwt_application: JwtApplication) -> TestClient:
    """Return the client of the JWT-authenticated full application."""
    return jwt_application.client
