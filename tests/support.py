"""Shared test helpers for the JWT-authenticated application plane."""

from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path
from typing import NamedTuple

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.base import LoadedExtension

DEV_JWT_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_JWT_AUDIENCE = "https://spectres.runtime/api"
ADMIN_SCOPES = ["agent_os:admin"]
FULL_USER_SCOPES = [
    "config:read",
    "registry:read",
    "agents:read",
    "agents:*:run",
    "workflows:read",
    "workflows:run",
    "sessions:read",
    "sessions:write",
    "sessions:delete",
    "memories:read",
    "memories:write",
    "memories:delete",
    "schedules:read",
    "schedules:write",
    "schedules:delete",
    "approvals:read",
    "approvals:write",
    "approvals:delete",
    "metrics:read",
    "traces:read",
]


class JwtApplication(NamedTuple):
    """A full application client plus the Extensions loaded into it."""

    client: TestClient
    extensions: list[LoadedExtension]


def dev_token(sub: str, scopes: list[str], *, name: str | None = None, secret: str = DEV_JWT_KEY, audience: str = DEV_JWT_AUDIENCE) -> str:
    """Sign a development JWT accepted by the ``jwt_application`` fixture by default.

    ``name`` defaults to the title-cased subject; pass ``""`` to omit the name claim.
    """
    from agno.os.auth import create_dev_token

    return create_dev_token(sub, secret=secret, audience=audience, email=f"{sub}@example.com", name=sub.title() if name is None else name, scopes=scopes)


def auth_headers(sub: str, scopes: list[str], *, name: str | None = None) -> dict[str, str]:
    """Return a bearer Authorization header for a development JWT."""
    return {"Authorization": f"Bearer {dev_token(sub, scopes, name=name)}"}


def migrated_extension_session_factory(extension_id: str) -> sessionmaker[Session]:
    """Apply an Extension's real migrations to the test database and return a session factory."""
    from spectres.db.migration import migrate_schema
    from spectres.db.postgres import get_postgres_db

    engine = get_postgres_db().db_engine
    package = import_module(f"spectres.extensions.{extension_id}")
    migrate_schema(
        engine,
        script_location=Path(str(package.__file__)).parent / "migrations",
        version_table=f"{extension_id}_schema_version",
        lock_namespace=f"spectres.runtime.extension.{extension_id}",
    )
    return sessionmaker(bind=engine)


def add_test_identity(app: FastAPI) -> None:
    """Install middleware that sets request identity from ``x-test-*`` headers.

    ``x-test-user`` defaults to ``alice``; an empty value simulates a missing identity.
    """

    @app.middleware("http")
    async def set_identity(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        scopes = request.headers.get("x-test-scopes")
        request.state.user_id = request.headers.get("x-test-user", "alice")
        request.state.scopes = scopes.split(",") if scopes else []
        request.state.is_internal_service = request.headers.get("x-test-internal") == "true"
        return await call_next(request)
