"""Integration tests for Logto-style JWT scope authorization."""

from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
ADMIN_SCOPES = ["agent_os:admin"]
USER_SCOPES = [
    "config:read",
    "registry:read",
    "agents:read",
    "agents:*:run",
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

pytestmark = pytest.mark.db


def _headers(sub: str, scopes: list[str]) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def scoped_client() -> Iterator[TestClient]:
    """Build the full application with JWT scope authorization enabled."""
    from spectres import main as main_module
    from spectres.config import settings

    old_key, old_audience, old_algorithm = settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm
    settings.jwt_verification_key = DEV_KEY
    settings.jwt_audience = DEV_AUDIENCE
    settings.jwt_algorithm = "HS256"
    try:
        agent_os, contributions = main_module.create_agent_os()
        app = agent_os.get_app()
        for contribution in contributions:
            for router in contribution.routers:
                app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm = old_key, old_audience, old_algorithm


def test_token_without_required_scope_is_forbidden(scoped_client: TestClient) -> None:
    """A valid identity without the route's scope is not enough."""
    response = scoped_client.get("/agents", headers=_headers("alice", []))
    assert response.status_code == 403


def test_user_scopes_preserve_daily_routes(scoped_client: TestClient) -> None:
    """The ordinary role can read config/registry and run the agent family."""
    assert scoped_client.get("/config", headers=_headers("alice", USER_SCOPES)).status_code == 200
    assert scoped_client.get("/registry", headers=_headers("alice", USER_SCOPES)).status_code == 200
    assert scoped_client.get("/agents", headers=_headers("alice", USER_SCOPES)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/users"),
        ("GET", "/components"),
        ("GET", "/service-accounts"),
        ("POST", "/databases/all/migrate"),
        ("POST", "/metrics/refresh"),
    ],
)
def test_admin_only_routes_reject_user(scoped_client: TestClient, method: str, path: str) -> None:
    """Administrative configuration and governance are denied to user."""
    response = scoped_client.request(method, path, headers=_headers("alice", USER_SCOPES))
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/users", "/components", "/service-accounts"])
def test_admin_scope_allows_management_routes(scoped_client: TestClient, path: str) -> None:
    """Agno's admin super-scope opens framework management surfaces."""
    response = scoped_client.get(path, headers=_headers("operator", ADMIN_SCOPES))
    assert response.status_code == 200


def test_admin_can_disable_and_restore_directory_user(scoped_client: TestClient) -> None:
    """The /users API administers the immediate disabled-user kill-switch."""
    subject = f"disposable-{uuid4().hex}"
    user_headers = _headers(subject, USER_SCOPES)
    admin_headers = _headers("operator", ADMIN_SCOPES)
    assert scoped_client.get("/agents", headers=user_headers).status_code == 200

    disabled = scoped_client.patch(f"/users/{subject}", headers=admin_headers, json={"disabled": True})
    assert disabled.status_code == 200
    assert scoped_client.get("/agents", headers=user_headers).status_code in (401, 403)

    restored = scoped_client.patch(f"/users/{subject}", headers=admin_headers, json={"disabled": False})
    assert restored.status_code == 200
    assert scoped_client.get("/agents", headers=user_headers).status_code == 200


def test_user_cannot_manage_directory_users(scoped_client: TestClient) -> None:
    """A non-admin cannot change another user's disabled state."""
    store = cast(FastAPI, scoped_client.app).state.user_store
    store.provision_from_claims("victim", {"email": "victim@example.com"})
    response = scoped_client.patch("/users/victim", headers=_headers("mallory", USER_SCOPES), json={"disabled": True})
    assert response.status_code == 403
    assert store.get("victim")["disabled"] is False


def test_extension_remains_shared_between_roles(scoped_client: TestClient) -> None:
    """Role enforcement adds no extension-specific scope or data partition."""
    path = "/api/v1/extensions/etf-grid/status"
    user_response = scoped_client.get(path, headers=_headers("alice", USER_SCOPES))
    admin_response = scoped_client.get(path, headers=_headers("operator", ADMIN_SCOPES))
    assert user_response.status_code == 200
    assert admin_response.status_code == 200
    assert user_response.json() == admin_response.json()
