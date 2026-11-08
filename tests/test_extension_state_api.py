"""Real-JWT/PostgreSQL tests for Extension activation APIs."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
USER_SCOPES = ["agents:read", "agents:*:run"]
ADMIN_SCOPES = ["agent_os:admin"]

pytestmark = pytest.mark.db


def _headers(sub: str, scopes: list[str]) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Build the complete application with development JWT authentication."""
    from spectres import main as main_module
    from spectres.config import settings

    old_key, old_audience, old_algorithm = settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm
    settings.jwt_verification_key = DEV_KEY
    settings.jwt_audience = DEV_AUDIENCE
    settings.jwt_algorithm = "HS256"
    try:
        agent_os, extensions = main_module.create_agent_os()
        app = agent_os.get_app()
        main_module.mount_extension_routers(app, extensions)
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm = old_key, old_audience, old_algorithm


def test_catalog_requires_authentication(client: TestClient) -> None:
    """The Extension catalog is not a public unauthenticated route."""
    assert client.get("/api/v1/extensions").status_code == 401


def test_authenticated_user_can_read_catalog(client: TestClient) -> None:
    """An ordinary authenticated identity can read current activation state."""
    response = client.get("/api/v1/extensions", headers=_headers("alice", USER_SCOPES))

    assert response.status_code == 200
    etf_grid = next(item for item in response.json()["items"] if item["id"] == "etf_grid")
    assert etf_grid == {
        "id": "etf_grid",
        "name": "ETF Grid",
        "description": "ETF grid trading status, trade ledger, signals, and scheduled data workflows.",
        "enabled": True,
        "updated_at": etf_grid["updated_at"],
    }


def test_ordinary_user_cannot_change_activation(client: TestClient) -> None:
    """A valid non-admin identity cannot change global Extension state."""
    response = client.patch("/api/v1/extensions/etf_grid", headers=_headers("alice", USER_SCOPES), json={"enabled": False})

    assert response.status_code == 403


def test_admin_can_disable_and_restore_without_recreating_application(client: TestClient) -> None:
    """State changes take effect in the existing application and catalog."""
    admin = _headers("operator", ADMIN_SCOPES)
    user = _headers("alice", USER_SCOPES)

    disabled = client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    catalog = client.get("/api/v1/extensions", headers=user)
    assert next(item for item in catalog.json()["items"] if item["id"] == "etf_grid")["enabled"] is False

    restored = client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True})
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True


def test_unknown_extension_returns_404(client: TestClient) -> None:
    """An administrator cannot toggle an id absent from discovered code."""
    response = client.patch("/api/v1/extensions/missing", headers=_headers("operator", ADMIN_SCOPES), json={"enabled": False})

    assert response.status_code == 404


def test_invalid_activation_body_returns_422(client: TestClient) -> None:
    """The activation body requires a boolean enabled field."""
    response = client.patch("/api/v1/extensions/etf_grid", headers=_headers("operator", ADMIN_SCOPES), json={})

    assert response.status_code == 422


def test_disabled_extension_rejects_existing_router_and_restores_without_remount(client: TestClient) -> None:
    """Router guards take effect immediately and recover after re-enablement."""
    admin = _headers("operator", ADMIN_SCOPES)
    user = _headers("alice", USER_SCOPES)
    path = "/api/v1/extensions/etf-grid/instruments"
    assert client.get(path, headers=user).status_code == 200

    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200
    disabled = client.get(path, headers=user)
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "extension_disabled"
    assert client.get(path, headers=admin).status_code == 403

    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True}).status_code == 200
    assert client.get(path, headers=user).status_code == 200
