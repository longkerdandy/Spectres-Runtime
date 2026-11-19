"""Real-JWT/PostgreSQL tests for Extension activation APIs."""

import pytest
from fastapi.testclient import TestClient

from tests.support import ADMIN_SCOPES, auth_headers

USER_SCOPES = ["agents:read", "agents:*:run"]

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_catalog_requires_authentication(jwt_client: TestClient) -> None:
    """The Extension catalog is not a public unauthenticated route."""
    assert jwt_client.get("/api/v1/extensions").status_code == 401


def test_authenticated_user_can_read_catalog(jwt_client: TestClient) -> None:
    """An ordinary authenticated identity can read current activation state."""
    response = jwt_client.get("/api/v1/extensions", headers=auth_headers("alice", USER_SCOPES))

    assert response.status_code == 200
    etf_grid = next(item for item in response.json()["items"] if item["id"] == "etf_grid")
    assert etf_grid == {
        "id": "etf_grid",
        "name": "ETF Grid",
        "description": "ETF grid trading status, trade ledger, signals, and scheduled data workflows.",
        "enabled": True,
        "updated_at": etf_grid["updated_at"],
    }


def test_ordinary_user_cannot_change_activation(jwt_client: TestClient) -> None:
    """A valid non-admin identity cannot change global Extension state."""
    response = jwt_client.patch("/api/v1/extensions/etf_grid", headers=auth_headers("alice", USER_SCOPES), json={"enabled": False})

    assert response.status_code == 403


def test_admin_can_disable_and_restore_without_recreating_application(jwt_client: TestClient) -> None:
    """State changes take effect in the existing application and catalog."""
    admin = auth_headers("operator", ADMIN_SCOPES)
    user = auth_headers("alice", USER_SCOPES)

    disabled = jwt_client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    catalog = jwt_client.get("/api/v1/extensions", headers=user)
    assert next(item for item in catalog.json()["items"] if item["id"] == "etf_grid")["enabled"] is False

    restored = jwt_client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True})
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True


def test_unknown_extension_returns_404(jwt_client: TestClient) -> None:
    """An administrator cannot toggle an id absent from discovered code."""
    response = jwt_client.patch("/api/v1/extensions/missing", headers=auth_headers("operator", ADMIN_SCOPES), json={"enabled": False})

    assert response.status_code == 404


def test_invalid_activation_body_returns_422(jwt_client: TestClient) -> None:
    """The activation body requires a boolean enabled field."""
    response = jwt_client.patch("/api/v1/extensions/etf_grid", headers=auth_headers("operator", ADMIN_SCOPES), json={})

    assert response.status_code == 422


def test_disabled_extension_rejects_existing_router_and_restores_without_remount(jwt_client: TestClient) -> None:
    """Router guards take effect immediately and recover after re-enablement."""
    admin = auth_headers("operator", ADMIN_SCOPES)
    user = auth_headers("alice", USER_SCOPES)
    path = "/api/v1/extensions/etf-grid/status"
    assert jwt_client.get(path, headers=user).status_code == 200

    assert jwt_client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200
    disabled = jwt_client.get(path, headers=user)
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "extension_disabled"
    assert jwt_client.get(path, headers=admin).status_code == 403

    assert jwt_client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True}).status_code == 200
    assert jwt_client.get(path, headers=user).status_code == 200
